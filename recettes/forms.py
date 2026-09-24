import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils.crypto import get_random_string

from .models import (
    Anomalie,
    Categorie,
    ObjectifBudgetaire,
    ParametrageSysteme,
    Profil,
    Recette,
    Secteur,
)

EXTENSIONS_PIECES = (".pdf", ".png", ".jpg", ".jpeg", ".csv", ".xlsx", ".pes")
TAILLE_MAX_PIECE = 10 * 1024 * 1024


def valider_piece(fichier):
    if not fichier:
        return fichier
    nom = getattr(fichier, "name", "").lower()
    if not nom.endswith(EXTENSIONS_PIECES):
        raise ValidationError("Format non accepté (PDF, image, CSV, Excel ou PES uniquement).")
    if getattr(fichier, "size", 0) > TAILLE_MAX_PIECE:
        raise ValidationError("Le fichier dépasse 10 Mo.")
    return fichier


class MontantField(forms.DecimalField):
    """Accepte « 16 500,00 » aussi bien que « 16500.00 »."""

    def to_python(self, value):
        if isinstance(value, str):
            value = re.sub(r"[\s\u00a0\u202f]", "", value).replace(",", ".")
            value = re.sub(r"(?i)(ar|mga)$", "", value)
        return super().to_python(value)


class CategorieChoix(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"Chapitre {obj.chapitre} — {obj.libelle_complet}"


class SecteurChoix(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.nom.replace('Secteur ', '')} — {obj.pole}" if obj.pole else obj.nom


class UtilisateurChoix(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.get_full_name() or obj.username} — {obj.profil.get_role_display()}"


class ConnexionForm(AuthenticationForm):
    username = forms.EmailField(label="Courriel professionnel", max_length=254)

    def clean(self):
        identifiant = self.cleaned_data.get("username")
        mot_de_passe = self.cleaned_data.get("password")
        if identifiant and mot_de_passe:
            candidat = User.objects.filter(email__iexact=identifiant).select_related("profil").first()
            if (
                candidat and not candidat.is_active and candidat.check_password(mot_de_passe)
                and getattr(candidat.profil, "en_attente", False)
            ):
                raise ValidationError(
                    "Votre demande d'habilitation est en cours d'instruction : "
                    "vous pourrez vous connecter dès sa validation par l'administrateur.",
                    code="en_attente",
                )
        return super().clean()

    error_messages = {
        "invalid_login": "Adresse courriel ou mot de passe incorrect.",
        "inactive": "Ce compte est désactivé. Contactez l'administrateur.",
    }


class FormulaireAvecUtilisateur(forms.ModelForm):

    def __init__(self, *args, utilisateur=None, **kwargs):
        self.utilisateur = utilisateur
        super().__init__(*args, **kwargs)
        self.fields["categorie"].queryset = self.categories_autorisees()
        if "secteur" in self.fields:
            self.fields["secteur"].queryset = Secteur.objects.filter(actif=True)

    def categories_autorisees(self):
        categories = Categorie.objects.filter(actif=True)
        profil = getattr(self.utilisateur, "profil", None)
        if profil and profil.role == Profil.Role.AGENT:
            categories = categories.filter(ouverte_aux_agents=True)
        return categories

    def clean_categorie(self):
        categorie = self.cleaned_data["categorie"]
        if not self.categories_autorisees().filter(pk=categorie.pk).exists():
            raise forms.ValidationError(
                "Votre profil ne vous autorise pas à saisir cette catégorie de recette."
            )
        return categorie

    def clean_piece_jointe(self):
        return valider_piece(self.cleaned_data.get("piece_jointe"))


class RecetteForm(FormulaireAvecUtilisateur):
    categorie = CategorieChoix(queryset=Categorie.objects.none(), label="Nature de la recette")
    secteur = SecteurChoix(queryset=Secteur.objects.none(), label="Secteur géographique")
    montant = MontantField(max_digits=12, decimal_places=2, min_value=Decimal("0"), label="Montant de la recette")
    date_imputation = forms.DateField(label="Date d'imputation", widget=forms.DateInput(attrs={"type": "date"}))
    libelle = forms.CharField(label="Libellé de l'encaissement", max_length=255, widget=forms.Textarea(attrs={"rows": 2}))

    class Meta:
        model = Recette
        fields = ["categorie", "secteur", "date_imputation", "montant", "mode_reglement", "libelle", "piece_jointe"]

    def clean_montant(self):
        montant = self.cleaned_data["montant"]
        if montant is not None and montant < 0:
            raise forms.ValidationError("Une recette perçue ne peut pas être négative.")
        return montant

    def clean(self):
        donnees = super().clean()
        categorie, secteur = donnees.get("categorie"), donnees.get("secteur")
        if categorie and secteur:
            habilites = categorie.secteurs_habilites.all()
            if habilites.exists() and secteur not in habilites:
                self.add_error(
                    "secteur",
                    f"Le compte {categorie.libelle_complet} n'est pas habilité pour ce secteur.",
                )
        return donnees


class AnomalieForm(FormulaireAvecUtilisateur):
    categorie = CategorieChoix(queryset=Categorie.objects.none(), label="Chapitre rattaché")
    secteur = SecteurChoix(queryset=Secteur.objects.none(), label="Secteur territorial concerné")
    assigne_a = UtilisateurChoix(queryset=User.objects.none(), required=False, label="Régisseur ou service assigné")
    montant = MontantField(max_digits=12, decimal_places=2, min_value=Decimal("0"), label="Montant contesté ou non apuré (Ar)")
    date_constat = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Date de constatation")
    date_echeance = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Échéance légale de reversement")
    motif = forms.ChoiceField(choices=Anomalie.Motif.choices, widget=forms.RadioSelect, label="Motif principal constaté")

    class Meta:
        model = Anomalie
        fields = [
            "categorie", "secteur", "motif", "assigne_a", "montant", "date_constat",
            "date_echeance", "description", "piece_jointe", "notifier_comptable",
        ]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigne_a"].queryset = User.objects.filter(is_active=True).select_related("profil").order_by("first_name", "username")
        self.fields["montant"].required = False
        self.fields["date_echeance"].required = False
        self.fields["notifier_comptable"].required = False

    def clean_montant(self):
        return self.cleaned_data.get("montant") or Decimal("0")

    def clean(self):
        donnees = super().clean()
        constat, echeance = donnees.get("date_constat"), donnees.get("date_echeance")
        if constat and echeance and echeance < constat:
            self.add_error("date_echeance", "L'échéance ne peut pas précéder la date de constatation.")
        return donnees


class CategorieForm(forms.ModelForm):
    secteurs_habilites = forms.ModelMultipleChoiceField(
        queryset=Secteur.objects.filter(actif=True), required=False, widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Categorie
        fields = [
            "nom", "code", "chapitre", "type_perception", "regime_tva", "secteurs_habilites",
            "actif", "en_revision", "ouverte_aux_agents",
        ]


class SecteurForm(forms.ModelForm):
    regisseur = UtilisateurChoix(queryset=User.objects.none(), required=False, label="Régisseur titulaire")
    suppleant = UtilisateurChoix(queryset=User.objects.none(), required=False, label="Mandataire suppléant")
    plafond_encaissement = MontantField(max_digits=12, decimal_places=2, min_value=Decimal("0"), label="Plafond légal (Ar)")

    class Meta:
        model = Secteur
        fields = ["nom", "code", "description", "pole", "regisseur", "suppleant", "iban",
                  "plafond_encaissement", "frequence_versement", "actif"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        actifs = User.objects.filter(is_active=True).select_related("profil").order_by("first_name", "username")
        self.fields["regisseur"].queryset = actifs
        self.fields["suppleant"].queryset = actifs
        self.fields["actif"].required = False


class ObjectifForm(forms.ModelForm):
    categorie = CategorieChoix(queryset=Categorie.objects.none(), label="Article budgétaire de destination")
    mois = forms.DateField(label="Mois d'échéance prévisionnelle")
    montant_cible = MontantField(max_digits=12, decimal_places=2, min_value=Decimal("0"), label="Montant prévisionnel inscrit")
    type_budget = forms.ChoiceField(choices=ObjectifBudgetaire.TypeBudget.choices, widget=forms.RadioSelect, initial="BP")
    secteur = forms.ModelChoiceField(queryset=Secteur.objects.none(), required=False)

    class Meta:
        model = ObjectifBudgetaire
        fields = ["categorie", "mois", "montant_cible", "type_budget", "secteur", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        kwargs.pop("utilisateur", None)
        super().__init__(*args, **kwargs)
        self.fields["categorie"].queryset = Categorie.objects.filter(actif=True)
        self.fields["secteur"].queryset = Secteur.objects.filter(actif=True)
        self.fields["notes"].required = False

    def clean_montant_cible(self):
        montant = self.cleaned_data["montant_cible"]
        if montant is not None and montant < 0:
            raise forms.ValidationError("Un objectif budgétaire ne peut pas être négatif.")
        return montant


INPUT_CLS = "w-full text-sm border border-[#E2E8F0] rounded-lg px-3 py-2 focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500"


class ParametrageForm(forms.ModelForm):

    class Meta:
        model = ParametrageSysteme
        fields = [
            "mois_a_prevoir",
            "historique_minimum",
            "seuil_alerte_pct",
            "jour_echeance_recouvrement",
            "notifications_email_actives",
        ]
        widgets = {
            "mois_a_prevoir": forms.NumberInput(attrs={"class": INPUT_CLS, "min": 1, "max": 24}),
            "historique_minimum": forms.NumberInput(attrs={"class": INPUT_CLS, "min": 1, "max": 36}),
            "seuil_alerte_pct": forms.NumberInput(attrs={"class": INPUT_CLS, "step": "0.5", "min": 0}),
            "jour_echeance_recouvrement": forms.NumberInput(attrs={"class": INPUT_CLS, "min": 1, "max": 28}),
            "notifications_email_actives": forms.CheckboxInput(attrs={"class": "w-4 h-4 rounded border-[#CBD5E1] text-emerald-600 focus:ring-emerald-500"}),
        }


class HabilitationForm(forms.Form):
    first_name = forms.CharField(label="Prénom", max_length=60)
    last_name = forms.CharField(label="Nom de famille", max_length=60)
    email = forms.EmailField(label="Courriel professionnel")
    telephone = forms.CharField(label="Téléphone", max_length=30, required=False)
    matricule = forms.CharField(label="Matricule", max_length=40)
    role = forms.ChoiceField(
        choices=[c for c in Profil.Role.choices if c[0] != Profil.Role.ADMIN], label="Fonction sollicitée",
    )
    secteur = forms.ModelChoiceField(queryset=Secteur.objects.none(), required=False, label="Pôle de rattachement")
    piece_nomination = forms.FileField(required=False, label="Arrêté de nomination")
    password1 = forms.CharField(label="Mot de passe", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmation", widget=forms.PasswordInput)
    deontologie = forms.BooleanField(label="Engagement déontologique")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["secteur"].queryset = Secteur.objects.filter(actif=True)
        for nom, champ in self.fields.items():
            if isinstance(champ.widget, forms.CheckboxInput):
                champ.widget.attrs["class"] = "rounded border-[#D1D5DB] text-[#131417] focus:ring-[#131417]/20 mt-0.5 shrink-0"
            elif isinstance(champ.widget, forms.ClearableFileInput):
                champ.widget.attrs["class"] = "text-xs text-[#6B7280]"
            else:
                champ.widget.attrs["class"] = "champ"

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise ValidationError("Un compte utilise déjà cette adresse e-mail.")
        return email

    def clean_piece_nomination(self):
        return valider_piece(self.cleaned_data.get("piece_nomination"))

    def clean(self):
        donnees = super().clean()
        p1, p2 = donnees.get("password1"), donnees.get("password2")
        if p1 and p2:
            if p1 != p2:
                self.add_error("password2", "Les deux mots de passe ne correspondent pas.")
            else:
                provisoire = User(username=donnees.get("email", ""), email=donnees.get("email", ""),
                                  first_name=donnees.get("first_name", ""), last_name=donnees.get("last_name", ""))
                try:
                    validate_password(p1, provisoire)
                except ValidationError as erreur:
                    self.add_error("password1", erreur)
        return donnees

    def save(self):
        d = self.cleaned_data
        user = User.objects.create_user(
            username=d["email"], email=d["email"], password=d["password1"],
            first_name=d["first_name"], last_name=d["last_name"], is_active=False,
        )
        from django.utils import timezone

        profil = user.profil
        profil.role = d["role"]
        profil.telephone = d.get("telephone", "")
        profil.matricule = d["matricule"]
        profil.secteur = d.get("secteur")
        profil.en_attente = True
        profil.date_demande = timezone.now()
        if d.get("piece_nomination"):
            profil.piece_nomination = d["piece_nomination"]
        profil.save()
        return user


class UtilisateurAdminForm(forms.ModelForm):
    """Invitation (création) et édition d'un agent depuis « Utilisateurs & Droits d'accès »."""

    role = forms.ChoiceField(choices=Profil.Role.choices, label="Rôle", widget=forms.RadioSelect)
    secteur = forms.ModelChoiceField(queryset=Secteur.objects.none(), required=False, label="Secteur territorial")
    telephone = forms.CharField(required=False, max_length=30)
    matricule = forms.CharField(required=False, max_length=40)
    recevoir_notifications = forms.BooleanField(required=False, initial=True, label="Reçoit les notifications par e-mail")

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "is_active"]
        labels = {"first_name": "Prénom", "last_name": "Nom", "email": "Adresse e-mail", "is_active": "Compte actif"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].required = True
        self.fields["secteur"].queryset = Secteur.objects.filter(actif=True)
        self.fields["is_active"].required = False
        if self.instance and self.instance.pk:
            profil = getattr(self.instance, "profil", None)
            if profil:
                self.fields["role"].initial = profil.role
                self.fields["recevoir_notifications"].initial = profil.recevoir_notifications
                self.fields["secteur"].initial = profil.secteur_id
                self.fields["telephone"].initial = profil.telephone
                self.fields["matricule"].initial = profil.matricule

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        doublon = User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
        if doublon.exists():
            raise forms.ValidationError("Un autre compte utilise déjà cette adresse e-mail.")
        return email

    def save(self, commit=True):
        creation = self.instance.pk is None
        user = super().save(commit=False)
        if creation:
            user.username = self.cleaned_data["email"]
            user.is_active = True
            user.set_password(get_random_string(32))
        user.save()
        profil = user.profil
        profil.role = self.cleaned_data["role"]
        profil.recevoir_notifications = self.cleaned_data["recevoir_notifications"]
        profil.secteur = self.cleaned_data.get("secteur")
        profil.telephone = self.cleaned_data.get("telephone", "")
        profil.matricule = self.cleaned_data.get("matricule", "")
        profil.save()
        return user
