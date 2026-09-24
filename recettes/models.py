from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

class Profil(models.Model):

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Administrateur"
        RESPONSABLE = "RESPONSABLE", "Responsable financier"
        ELU = "ELU", "Élu / décideur"
        AGENT = "AGENT", "Agent de recouvrement"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profil")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.RESPONSABLE)
    recevoir_notifications = models.BooleanField(
        default=True,
        help_text="Décochez pour ne plus recevoir les e-mails d'alerte et de rappel.",
    )
    telephone = models.CharField(max_length=30, blank=True)
    matricule = models.CharField(max_length=40, blank=True, help_text="Matricule interne ou code d'agent.")
    secteur = models.ForeignKey(
        "Secteur", on_delete=models.SET_NULL, null=True, blank=True, related_name="agents",
        help_text="Secteur de rattachement. Vide = transversal (tous les secteurs).",
    )
    en_attente = models.BooleanField(
        default=False,
        help_text="Demande d'habilitation déposée, en attente de validation par l'administrateur.",
    )
    date_demande = models.DateTimeField(null=True, blank=True)
    piece_nomination = models.FileField(upload_to="habilitations/%Y/%m/", blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    @property
    def reference_demande(self):
        return f"HAB-{(self.date_demande or self.user.date_joined):%Y}-{self.user_id:04d}"

    @property
    def nom_affiche(self):
        return self.user.get_full_name() or self.user.username

    @property
    def initiales(self):
        nom = self.user.get_full_name() or self.user.username
        morceaux = [m for m in nom.replace("-", " ").replace("_", " ").split() if m]
        return "".join(m[0] for m in morceaux[:2]).upper() or "?"

class ParametrageSysteme(models.Model):

    mois_a_prevoir = models.PositiveSmallIntegerField(
        default=6,
        validators=[MinValueValidator(1), MaxValueValidator(36)],
        verbose_name="Horizon de prévision (mois)",
        help_text="Nombre de mois prévus au-delà du dernier mois connu (1 à 36).",
    )
    historique_minimum = models.PositiveSmallIntegerField(
        default=3,
        validators=[MinValueValidator(2), MaxValueValidator(60)],
        verbose_name="Historique minimum (mois)",
        help_text="En dessous de ce nombre de points, aucune prévision n'est calculée pour la catégorie.",
    )
    seuil_alerte_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("15.00"),
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("100.00"))],
        verbose_name="Seuil d'alerte d'écart (%)",
        help_text="Un écart entre réalisé et objectif supérieur ou égal à ce pourcentage déclenche une alerte.",
    )
    jour_echeance_recouvrement = models.PositiveSmallIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(28)],
        verbose_name="Jour d'échéance de saisie",
        help_text="Jour du mois avant lequel les recettes du mois précédent doivent être saisies.",
    )
    notifications_email_actives = models.BooleanField(
        default=True,
        verbose_name="Envoi réel des e-mails",
        help_text="Si décoché, les notifications restent visibles dans l'application mais aucun e-mail n'est envoyé.",
    )
    date_modification = models.DateTimeField(auto_now=True)
    modifie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        verbose_name = "Paramétrage du système"
        verbose_name_plural = "Paramétrage du système"

    def __str__(self):
        return "Paramétrage du système"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def charger(cls):
        objet, _ = cls.objects.get_or_create(pk=1)
        return objet

    @property
    def seuil_alerte_ratio(self) -> float:
        return float(self.seuil_alerte_pct) / 100

class Secteur(models.Model):

    class Frequence(models.IntegerChoices):
        SEPT = 7, "Hebdomadaire (J+7)"
        DIX = 10, "Décadaire (J+10)"
        QUINZE = 15, "Bi-mensuelle (J+15)"
        TRENTE = 30, "Mensuelle (J+30)"

    nom = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, blank=True, help_text="Code court affiché dans les tableaux (ex. : NORD).")
    description = models.CharField(max_length=255, blank=True)
    actif = models.BooleanField(default=True, help_text="Décochez pour archiver sans supprimer l'historique.")
    pole = models.CharField("Pôle gestionnaire", max_length=120, blank=True)
    regisseur = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="secteurs_regisseur", verbose_name="Régisseur titulaire",
    )
    suppleant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="secteurs_suppleant", verbose_name="Mandataire suppléant",
    )
    iban = models.CharField("Compte de dépôt (IBAN / RIB)", max_length=40, blank=True)
    plafond_encaissement = models.DecimalField(
        "Plafond légal d'encaissement (Ar)", max_digits=12, decimal_places=2, default=Decimal("50000000"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    frequence_versement = models.PositiveSmallIntegerField(
        "Fréquence de versement", choices=Frequence.choices, default=Frequence.QUINZE,
    )

    class Meta:
        ordering = ["nom"]
        verbose_name = "Secteur de recouvrement"
        verbose_name_plural = "Secteurs de recouvrement"

    def __str__(self):
        return self.nom

    @property
    def reference(self):
        return f"SEC-{self.pk:02d}" if self.pk else "SEC-NEW"

    @property
    def code_regie(self):
        return f"R-{self.pk:02d}-{(self.code or self.nom)[:3].upper()}" if self.pk else ""

    @property
    def iban_masque(self):
        return f"•••• {self.iban.replace(' ', '')[-3:]}" if self.iban else "Non renseigné"

CHAPITRES = [
    ("13", "Chapitre 13 — Subventions d'investissement"),
    ("70", "Chapitre 70 — Ventes & prestations de services"),
    ("73", "Chapitre 73 — Impôts et taxes"),
    ("74", "Chapitre 74 — Dotations et subventions"),
    ("75", "Chapitre 75 — Autres produits de gestion courante"),
    ("77", "Chapitre 77 — Produits exceptionnels"),
]
CHAPITRES_DESCRIPTION = {
    "13": "Subventions d'équipement et d'investissement",
    "70": "Redevances du domaine, droits de place, concessions",
    "73": "Fiscalité directe locale, taxes de séjour, rôles fiscaux",
    "74": "Dotations de l'État, péréquation, fonds de compensation",
    "75": "Loyers communaux, remboursements et produits divers",
    "77": "Produits exceptionnels",
}

class Categorie(models.Model):

    class Perception(models.TextChoices):
        DIRECTE = "DIRECTE", "Perception directe (Régie)"
        TITRE = "TITRE", "Émission de titre"
        ROLE = "ROLE", "Rôle fiscal exécutoire"
        VIREMENT = "VIREMENT", "Virement bancaire / Trésor"

    class Tva(models.TextChoices):
        EXO = "EXO", "Exonéré"
        NORMAL = "20", "Taux normal 20,0 %"
        INTER = "10", "Taux intermédiaire 10,0 %"
        REDUIT = "5.5", "Taux réduit 5,5 %"
        HORS = "HORS", "Hors champ d'application"

    nom = models.CharField(max_length=100, unique=True, verbose_name="Libellé officiel")
    code = models.CharField("Code", max_length=10, blank=True)
    chapitre = models.CharField("Chapitre parent", max_length=3, choices=CHAPITRES, default="70")
    type_perception = models.CharField(max_length=10, choices=Perception.choices, default=Perception.TITRE)
    regime_tva = models.CharField("Régime TVA", max_length=5, choices=Tva.choices, default=Tva.EXO)
    en_revision = models.BooleanField("En révision", default=False)
    secteurs_habilites = models.ManyToManyField(
        "Secteur", blank=True, related_name="categories_habilitees",
        help_text="Vide = tous les secteurs.",
    )
    description = models.CharField(max_length=255, blank=True)
    actif = models.BooleanField(default=True, help_text="Décochez pour archiver sans supprimer l'historique.")
    ouverte_aux_agents = models.BooleanField(
        default=False,
        verbose_name="Saisissable par les agents de recouvrement",
        help_text=(
            "Le cahier des charges (7.4) limite les agents à la collecte des taxes et des redevances. "
            "Cochez uniquement pour les catégories que les agents ont le droit de saisir."
        ),
    )

    class Meta:
        ordering = ["chapitre", "code", "nom"]

    def __str__(self):
        return self.nom

    @property
    def libelle_complet(self):
        return f"{self.code} · {self.nom}" if self.code else self.nom

    @property
    def sous_titre(self):
        return f"Cpte {self.code} · {self.nom}" if self.code else f"Chapitre {self.chapitre}"

class Recette(models.Model):

    class Mode(models.TextChoices):
        VIREMENT = "VIREMENT", "Virement Trésor Public"
        TITRE = "TITRE", "Titre de recette émis"
        REGIE = "REGIE", "Régie municipale"
        PRELEVEMENT = "PRELEVEMENT", "Prélèvement"
        ROLE = "ROLE", "Rôle fiscal"

    reference = models.CharField("N° de bordereau", max_length=30, blank=True)
    date_imputation = models.DateField("Date d'imputation", null=True, blank=True)
    mode_reglement = models.CharField(max_length=15, choices=Mode.choices, default=Mode.VIREMENT)
    libelle = models.CharField("Libellé de l'encaissement", max_length=255, blank=True)
    piece_jointe = models.FileField("Pièce justificative", upload_to="bordereaux/%Y/%m/", blank=True, null=True)
    categorie = models.ForeignKey(Categorie, on_delete=models.PROTECT, related_name="recettes")
    secteur = models.ForeignKey(Secteur, on_delete=models.PROTECT, related_name="recettes")
    mois = models.DateField(help_text="Premier jour du mois concerné")
    montant = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Montant perçu, en Ariary (Ar). Une recette ne peut pas être négative.",
    )
    saisie_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="recettes_saisies"
    )
    date_saisie = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-mois", "categorie", "secteur"]
        constraints = [
            models.CheckConstraint(condition=models.Q(montant__gte=0), name="recette_montant_positif"),
        ]

    def __str__(self):
        return f"{self.categorie} — {self.secteur} — {self.mois:%m/%Y} — {self.montant} Ar"

    def clean(self):
        super().clean()
        if self.montant is not None and self.montant < 0:
            raise ValidationError({"montant": "Une recette perçue ne peut pas être négative."})
        if self.date_imputation:
            self.mois = self.date_imputation.replace(day=1)
        elif self.mois and self.mois.day != 1:
            self.mois = self.mois.replace(day=1)

    def save(self, *args, **kwargs):
        if self.date_imputation:
            self.mois = self.date_imputation.replace(day=1)
        elif self.mois:
            self.date_imputation = self.mois
        super().save(*args, **kwargs)
        if not self.reference:
            self.reference = f"BOR-{self.date_imputation:%Y}-{self.pk:04d}"
            type(self).objects.filter(pk=self.pk).update(reference=self.reference)

class ObjectifBudgetaire(models.Model):

    class TypeBudget(models.TextChoices):
        BP = "BP", "Budget Primitif (BP)"
        DM = "DM", "Décision Modificative"
        REPORT = "REPORT", "Report de crédits"

    class Statut(models.TextChoices):
        BROUILLON = "BROUILLON", "Brouillon"
        INSCRIT = "INSCRIT", "Inscrit au budget"

    categorie = models.ForeignKey(Categorie, on_delete=models.CASCADE, related_name="objectifs")
    secteur = models.ForeignKey(
        Secteur, on_delete=models.CASCADE, null=True, blank=True, related_name="objectifs",
        help_text="Vide = budget consolidé (ensemble des secteurs).",
    )
    type_budget = models.CharField(max_length=10, choices=TypeBudget.choices, default=TypeBudget.BP)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.INSCRIT)
    notes = models.TextField("Note explicative", blank=True)
    mois = models.DateField(help_text="Premier jour du mois concerné")
    montant_cible = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        verbose_name="Montant voté au budget",
        help_text="Montant inscrit au budget pour ce mois, en Ariary. Ne peut pas être négatif.",
    )
    fixe_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-mois", "categorie"]
        constraints = [
            models.UniqueConstraint(
                fields=["categorie", "mois"], condition=models.Q(secteur__isnull=True),
                name="unique_objectif_consolide",
            ),
            models.UniqueConstraint(
                fields=["categorie", "mois", "secteur"], condition=models.Q(secteur__isnull=False),
                name="unique_objectif_secteur",
            ),
            models.CheckConstraint(condition=models.Q(montant_cible__gte=0), name="objectif_montant_positif"),
        ]

    def __str__(self):
        return f"Objectif {self.categorie} — {self.mois:%m/%Y} — {self.montant_cible} Ar"

    def clean(self):
        super().clean()
        if self.montant_cible is not None and self.montant_cible < 0:
            raise ValidationError({"montant_cible": "Un objectif budgétaire ne peut pas être négatif."})
        if self.mois and self.mois.day != 1:
            self.mois = self.mois.replace(day=1)

class Anomalie(models.Model):

    class Motif(models.TextChoices):
        RETARD = "RETARD", "Retard de versement régie"
        ARRONDI = "ARRONDI", "Écart d'arrondi sur rôle"
        DOUBLE = "DOUBLE", "Double imputation"
        REJET = "REJET", "Rejet de bordereau / mandat"

    categorie = models.ForeignKey(Categorie, on_delete=models.CASCADE, related_name="anomalies")
    secteur = models.ForeignKey(Secteur, on_delete=models.PROTECT, related_name="anomalies")
    mois = models.DateField()
    motif = models.CharField(max_length=10, choices=Motif.choices, default=Motif.RETARD)
    montant = models.DecimalField(
        "Montant contesté ou non apuré (Ar)", max_digits=12, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    date_constat = models.DateField("Date de constatation", null=True, blank=True)
    date_echeance = models.DateField("Échéance légale de reversement", null=True, blank=True)
    assigne_a = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="anomalies_assignees", verbose_name="Régisseur ou agent assigné",
    )
    description = models.TextField()
    piece_jointe = models.FileField("Pièce justificative", upload_to="anomalies/%Y/%m/", blank=True, null=True)
    notifier_comptable = models.BooleanField(default=True)
    brouillon = models.BooleanField(default=False)
    signale_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    date_signalement = models.DateTimeField(auto_now_add=True)
    traitee = models.BooleanField(default=False)
    date_regularisation = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date_signalement"]

    def __str__(self):
        return f"Anomalie {self.categorie} {self.secteur} {self.mois:%m/%Y} ({'traitée' if self.traitee else 'ouverte'})"

    def clean(self):
        super().clean()
        if self.date_constat:
            self.mois = self.date_constat.replace(day=1)
        elif self.mois and self.mois.day != 1:
            self.mois = self.mois.replace(day=1)

    @property
    def reference(self):
        annee = self.date_signalement.year if self.date_signalement else date.today().year
        return f"ANO-{annee}-{self.pk:03d}" if self.pk else f"ANO-{annee}-NEW"

    @property
    def en_retard(self):
        return bool(self.date_echeance and not self.traitee and self.date_echeance < date.today())

    @property
    def jours_retard(self):
        return (date.today() - self.date_echeance).days if self.en_retard else 0

    @property
    def statut(self):
        if self.brouillon:
            return "Brouillon"
        if self.traitee:
            return "Régularisée"
        return "Prioritaire" if self.en_retard else "En cours"

    @property
    def intitule(self):
        return f"{self.get_motif_display()} — {self.secteur.nom}"

class EchangeAnomalie(models.Model):

    anomalie = models.ForeignKey(Anomalie, on_delete=models.CASCADE, related_name="echanges")
    auteur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    titre = models.CharField(max_length=120)
    texte = models.TextField(blank=True)
    date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]

class Notification(models.Model):

    class Type(models.TextChoices):
        ECART = "ECART", "Écart budgétaire"
        ECHEANCE = "ECHEANCE", "Échéance de recouvrement"
        ANOMALIE = "ANOMALIE", "Anomalie signalée"
        SYSTEME = "SYSTEME", "Information système"

    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.SYSTEME)
    sujet = models.CharField(max_length=200)
    message = models.TextField()
    cle_unicite = models.CharField(
        max_length=200,
        blank=True,
        help_text="Empêche d'envoyer deux fois la même alerte (ex. : ECART-3-2026-04).",
    )
    lue = models.BooleanField(default=False)
    traitee = models.BooleanField(default=False)
    date_traitement = models.DateTimeField(null=True, blank=True)
    lien = models.CharField(max_length=200, blank=True)
    envoyee_par_email = models.BooleanField(default=False)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date_creation"]
        constraints = [
            models.UniqueConstraint(
                fields=["destinataire", "cle_unicite"],
                condition=~models.Q(cle_unicite=""),
                name="unique_notification_par_destinataire",
            )
        ]

    def __str__(self):
        return f"[{self.get_type_display()}] {self.sujet} → {self.destinataire}"


class RapportGenere(models.Model):

    class TypeDoc(models.TextChoices):
        LIASSE = "LIASSE", "Liasse mensuelle"
        SYNTHESE = "SYNTHESE", "Synthèse analytique"
        ANOMALIES = "ANOMALIES", "État des anomalies & régies"

    class Format(models.TextChoices):
        PDF = "PDF", "PDF"
        XLSX = "XLSX", "Excel (.xlsx)"
        CSV = "CSV", "CSV"

    type_doc = models.CharField(max_length=12, choices=TypeDoc.choices)
    periode = models.CharField(max_length=60)
    perimetre = models.CharField(max_length=100, default="Tous les secteurs")
    format = models.CharField(max_length=5, choices=Format.choices, default=Format.PDF)
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    taille = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-date_creation"]

    @property
    def reference(self):
        prefixe = {"LIASSE": "LIA", "SYNTHESE": "SYN", "ANOMALIES": "ANO"}[self.type_doc]
        return f"{prefixe}-{self.date_creation:%Y}-{self.pk:04d}"
