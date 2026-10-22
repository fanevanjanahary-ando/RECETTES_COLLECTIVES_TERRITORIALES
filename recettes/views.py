import hashlib
import json
import logging
import smtplib
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, LogoutView
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q, Sum
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import exports, graphiques
from .alertes import (
    calculer_ecarts,
    execution_budgetaire,
    recouvrement_par_secteur,
    sans_double_comptage,
)
from .audit import journaliser
from .cloisonnement import anomalies_visibles, recettes_visibles, secteur_impose
from .context_processors import annees_disponibles, exercice_courant
from .decorateurs import role_requis
from .forms import (
    AnomalieForm,
    CategorieForm,
    ConnexionForm,
    FacteurEconomiqueForm,
    HabilitationForm,
    ObjectifForm,
    ParametrageForm,
    RecetteForm,
    SecteurForm,
    UtilisateurAdminForm,
)
from .models import (
    CHAPITRES,
    CHAPITRES_DESCRIPTION,
    Anomalie,
    Categorie,
    EchangeAnomalie,
    FacteurEconomique,
    Notification,
    ObjectifBudgetaire,
    ParametrageSysteme,
    Profil,
    RapportGenere,
    Recette,
    Secteur,
    TentativeConnexion,
)
from .notifications import (
    notifier_anomalie,
    notifier_anomalies_en_attente,
    notifier_ecarts_significatifs,
    notifier_habilitation,
    notifier_relance,
)
from .prevision import (
    avertissements_modele,
    fiabilite_modele,
    prevision_par_mois,
    previsions_par_categorie,
)
from .rapports import (
    comparaison_exercices,
    generer_rapport_pdf,
    generer_rapport_xlsx,
    mois_depuis_texte,
)

ROLES_SAISIE = (Profil.Role.ADMIN, Profil.Role.RESPONSABLE, Profil.Role.AGENT)
ROLES_GESTION = (Profil.Role.ADMIN, Profil.Role.RESPONSABLE)
ROLES_BUDGET = (*ROLES_GESTION, Profil.Role.ELU)
ROLES_ANOMALIES = (Profil.Role.AGENT, *ROLES_GESTION)

MOIS_LABELS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
               "septembre", "octobre", "novembre", "décembre"]
LIBELLE_CHAPITRE = dict(CHAPITRES)
logger = logging.getLogger(__name__)


def _chiffres(valeur):
    valeur = (valeur or "").strip()
    return valeur if valeur.isdigit() else ""


def _json_sur(objet):
    texte = json.dumps(objet, default=str)
    return texte.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

def _somme(qs, champ="montant"):
    return qs.aggregate(t=Sum(champ))["t"] or Decimal("0")


def _mois_moins(d, n):
    total = d.year * 12 + (d.month - 1) - n
    return date(total // 12, total % 12 + 1, 1)


def _var_pct(actuel, precedent):
    return round(float((actuel - precedent) / precedent * 100), 1) if precedent else None


def _page_suivante(request, defaut):
    cible = request.POST.get("next") or request.GET.get("next") or ""
    if cible and url_has_allowed_host_and_scheme(cible, {request.get_host()}):
        return cible
    return reverse(defaut)


def _erreurs_en_messages(request, form):
    for champ, erreurs in form.errors.items():
        etiquette = form.fields[champ].label if champ in form.fields else ""
        for erreur in erreurs:
            messages.error(request, f"{etiquette + ' : ' if etiquette else ''}{erreur}")


class ConnexionView(LoginView):
    template_name = "recettes/connexion.html"
    form_class = ConnexionForm
    redirect_authenticated_user = True

    def _cle(self, identifiant):
        brut = f"{self.request.META.get('REMOTE_ADDR', '')}|{identifiant.strip().lower()}"
        return "connexion:" + hashlib.sha256(brut.encode()).hexdigest()

    def post(self, request, *args, **kwargs):
        identifiant = request.POST.get("username", "")
        cle = self._cle(identifiant)
        seuil = timezone.now() - timedelta(seconds=settings.LOGIN_VERROUILLAGE_SECONDES)
        tentatives = TentativeConnexion.objects.filter(
            pk=cle, date_modification__gte=seuil
        ).values_list("nombre", flat=True).first() or 0
        if tentatives >= settings.LOGIN_MAX_TENTATIVES:
            journaliser(request, "connexion_bloquee", identifiant)
            messages.error(
                request,
                f"Trop de tentatives échouées. Réessayez dans "
                f"{settings.LOGIN_VERROUILLAGE_SECONDES // 60} minutes.",
            )
            return self.render_to_response(
                self.get_context_data(form=self.get_form_class()(request))
            )
        return super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["exercices"] = annees_disponibles()
        return ctx

    def form_valid(self, form):
        TentativeConnexion.objects.filter(
            pk=self._cle(self.request.POST.get("username", ""))
        ).delete()
        reponse = super().form_valid(form)
        journaliser(self.request, "connexion", self.request.user.username)
        try:
            annee = int(self.request.POST.get("exercice", ""))
            if annee in annees_disponibles():
                self.request.session["exercice"] = annee
        except ValueError:
            pass
        if self.request.POST.get("remember"):
            self.request.session.set_expiry(60 * 60 * 24 * 30)
        else:
            self.request.session.set_expiry(0)
        return reponse

    def form_invalid(self, form):
        identifiant = self.request.POST.get("username", "")
        cle = self._cle(identifiant)
        maintenant = timezone.now()
        seuil = maintenant - timedelta(seconds=settings.LOGIN_VERROUILLAGE_SECONDES)
        with transaction.atomic():
            tentative, creee = TentativeConnexion.objects.select_for_update().get_or_create(
                pk=cle, defaults={"nombre": 1}
            )
            if not creee:
                if tentative.date_modification < seuil:
                    tentative.nombre = 0
                tentative.nombre += 1
                tentative.save(update_fields=["nombre", "date_modification"])
            TentativeConnexion.objects.filter(date_modification__lt=seuil).delete()
        journaliser(self.request, "connexion_echec", identifiant)
        return super().form_invalid(form)


class DeconnexionView(LogoutView):
    next_page = reverse_lazy("connexion")


def inscription(request):
    """Demande d'habilitation : le compte reste inactif jusqu'à l'arbitrage de l'administrateur."""
    confirmation = None
    if request.method == "POST":
        form = HabilitationForm(request.POST, request.FILES)
        if form.is_valid():
            user = form.save()
            notifier_habilitation(user.profil)
            confirmation = user.profil.reference_demande
            form = HabilitationForm()
    else:
        form = HabilitationForm()
    return render(request, "recettes/inscription.html", {"form": form, "confirmation": confirmation})


@login_required
@require_POST
def changer_exercice(request):
    try:
        annee = int(request.POST.get("exercice", ""))
    except ValueError:
        annee = None
    if annee in annees_disponibles():
        request.session["exercice"] = annee
    return redirect(_page_suivante(request, "dashboard"))


@login_required
def dashboard(request):
    annee = exercice_courant(request)
    secteur_id = secteur_impose(request.user)
    parametres = ParametrageSysteme.charger()
    recettes_annee = recettes_visibles(request.user).filter(mois__year=annee)
    total = _somme(recettes_annee)
    dernier_mois = recettes_annee.order_by("-mois").values_list("mois", flat=True).first()
    if dernier_mois:
        precedent = _somme(
            recettes_visibles(request.user).filter(mois__year=annee - 1, mois__month__lte=dernier_mois.month)
        )
    else:
        precedent = Decimal("0")
    execution = execution_budgetaire(annee, secteur_id)
    ecarts = calculer_ecarts(annee, secteur_id)
    mois_courant = timezone.localdate().replace(day=1)
    ecarts_clos = [e for e in ecarts if e.mois < mois_courant]
    alertes = [e for e in ecarts_clos if e.significatif]
    pire = alertes[0] if alertes else (ecarts_clos[0] if ecarts_clos else None)

    suivi = recouvrement_par_secteur(annee=annee, secteur_id=secteur_id)
    for ligne in suivi["lignes"]:
        ligne["statut"] = "À surveiller" if ligne["anomalies_ouvertes"] else "Conforme"
    anomalies_ouvertes = Anomalie.objects.filter(traitee=False, brouillon=False)
    if secteur_id is not None:
        anomalies_ouvertes = anomalies_ouvertes.filter(secteur_id=secteur_id)
    montant_anomalies = _somme(anomalies_ouvertes, "montant")

    previsions = previsions_par_categorie(secteur_id=secteur_id)

    return render(
        request,
        "recettes/dashboard.html",
        {
            "exercice": annee,
            "parametres": parametres,
            "total": total,
            "variation_n1": _var_pct(total, precedent) if precedent else None,
            "execution": execution,
            "pire": pire,
            "alertes": alertes,
            "suivi_secteurs": suivi,
            "anomalies_ouvertes_total": anomalies_ouvertes.count(),
            "montant_anomalies": montant_anomalies,
            "avertissements": avertissements_modele(previsions),
            "data_json": _json_sur(previsions),
            "horizon": parametres.mois_a_prevoir,
        },
    )


def _periodes(annee, utilisateur=None):
    recettes = recettes_visibles(utilisateur) if utilisateur is not None else Recette.objects.all()
    dernier = recettes.filter(mois__year=annee).order_by("-mois").values_list("mois", flat=True).first()
    options = []
    if dernier:
        for i in range(0, 6):
            m = _mois_moins(dernier, i)
            if m.year == annee:
                options.append((m.strftime("%Y-%m"), f"{MOIS_LABELS[m.month - 1].capitalize()} {m.year}"))
    options.append(("annee", f"Année {annee} complète"))
    return options


@login_required
def liste_recettes(request):
    annee = exercice_courant(request)
    periodes = _periodes(annee, request.user)
    periode = request.GET.get("periode") or periodes[0][0]
    impose = secteur_impose(request.user)
    secteur_id = str(impose) if impose is not None else _chiffres(request.GET.get("secteur"))
    chapitre = request.GET.get("chapitre") if request.GET.get("chapitre") in dict(CHAPITRES) else ""
    categorie_id = _chiffres(request.GET.get("categorie"))
    q = (request.GET.get("q") or "").strip()

    recettes = recettes_visibles(request.user).select_related("categorie", "secteur", "saisie_par")
    if periode == "annee":
        recettes = recettes.filter(mois__year=annee)
    elif periode == "toutes":
        pass
    else:
        try:
            y, m = periode.split("-")
            recettes = recettes.filter(mois=date(int(y), int(m), 1))
        except ValueError:
            recettes = recettes.filter(mois__year=annee)
    if secteur_id:
        recettes = recettes.filter(secteur_id=secteur_id)
    if categorie_id:
        recettes = recettes.filter(categorie_id=categorie_id)
    if chapitre:
        recettes = recettes.filter(categorie__chapitre=chapitre)
    if q:
        recettes = recettes.filter(
            Q(reference__icontains=q) | Q(libelle__icontains=q) | Q(categorie__nom__icontains=q)
            | Q(categorie__code__icontains=q) | Q(secteur__nom__icontains=q)
        )
    recettes = recettes.order_by("-date_imputation", "-id")

    total_selection = _somme(recettes)
    page = Paginator(recettes, 12).get_page(request.GET.get("page"))
    total_page = sum((r.montant for r in page), Decimal("0"))
    fenetre, dernier = [], None
    for n in page.paginator.page_range:
        if n in (1, page.paginator.num_pages) or abs(n - page.number) <= 1:
            if dernier and n - dernier > 1:
                fenetre.append(None)
            fenetre.append(n)
            dernier = n
    params = request.GET.copy()
    params.pop("page", None)
    return render(
        request,
        "recettes/liste_recettes.html",
        {
            "page": page,
            "fenetre": fenetre,
            "total_selection": total_selection,
            "total_page": total_page,
            "nb_total": recettes_visibles(request.user).count(),
            "periodes": periodes,
            "periode": periode,
            "secteurs": Secteur.objects.filter(actif=True, pk=impose) if impose is not None else Secteur.objects.filter(actif=True),
            "chapitres": [(c, LIBELLE_CHAPITRE[c]) for c, _ in CHAPITRES if Categorie.objects.filter(chapitre=c).exists()],
            "secteur_filtre": secteur_id,
            "chapitre_filtre": chapitre,
            "categorie_filtre": categorie_id,
            "q": q,
            "querystring": params.urlencode(),
            "exercice": annee,
        },
    )


def _impact_data(annee, secteur_id=None):
    """Objectif annuel et réalisé par compte, pour l'encart « Impact sur l'exercice » du formulaire."""
    objectifs = {
        l["categorie_id"]: l["t"]
        for l in ObjectifBudgetaire.objects.filter(
            mois__year=annee, statut="INSCRIT", secteur_id=secteur_id
        )
        .values("categorie_id").annotate(t=Sum("montant_cible"))
    }
    recettes = Recette.objects.filter(mois__year=annee)
    if secteur_id is not None:
        recettes = recettes.filter(secteur_id=secteur_id)
    realise = {
        l["categorie_id"]: l["t"]
        for l in recettes.values("categorie_id").annotate(t=Sum("montant"))
    }
    return {
        str(c.pk): {
            "label": c.libelle_complet,
            "cible": float(objectifs.get(c.pk, 0)),
            "realise": float(realise.get(c.pk, 0)),
        }
        for c in Categorie.objects.filter(actif=True)
    }


def _contexte_formulaire_recette(request, form, titre, recette=None, lecture=False):
    annee = exercice_courant(request)
    secteur_id = secteur_impose(request.user)
    return {
        "form": form,
        "titre": titre,
        "recette": recette,
        "lecture": lecture,
        "impact_json": _json_sur(_impact_data(annee, secteur_id)),
        "annee": annee,
        "dernieres": recettes_visibles(request.user).select_related("categorie", "secteur").order_by("-date_saisie")[:3],
        "aujourdhui": timezone.localdate().isoformat(),
    }


@role_requis(*ROLES_SAISIE)
def ajouter_recette(request):
    if request.method == "POST":
        form = RecetteForm(request.POST, request.FILES, utilisateur=request.user)
        if form.is_valid():
            recette = form.save(commit=False)
            recette.saisie_par = request.user
            recette.full_clean(exclude=["saisie_par"])
            recette.save()
            journaliser(
                request, "recette_creation", recette.reference,
                f"{recette.categorie} / {recette.secteur} / {recette.mois:%m/%Y} / {recette.montant} Ar",
            )
            messages.success(request, f"Recette {recette.reference} enregistrée.")
            notifier_ecarts_significatifs()
            if request.POST.get("action") == "nouveau":
                return redirect("ajouter_recette")
            return redirect("liste_recettes")
    else:
        form = RecetteForm(utilisateur=request.user, initial={"date_imputation": timezone.localdate()})
    return render(request, "recettes/formulaire_recette.html",
                  _contexte_formulaire_recette(request, form, "Nouvelle recette"))


@login_required
def detail_recette(request, pk):
    recette = get_object_or_404(
        recettes_visibles(request.user).select_related("categorie", "secteur", "saisie_par"), pk=pk
    )
    form = RecetteForm(instance=recette, utilisateur=request.user)
    return render(request, "recettes/formulaire_recette.html",
                  _contexte_formulaire_recette(request, form, f"Recette {recette.reference}", recette, lecture=True))


@role_requis(*ROLES_GESTION)
def modifier_recette(request, pk):
    recette = get_object_or_404(Recette, pk=pk)
    if request.method == "POST":
        form = RecetteForm(request.POST, request.FILES, instance=recette, utilisateur=request.user)
        if form.is_valid():
            avant = f"{recette.categorie} / {recette.secteur} / {recette.mois:%m/%Y} / {recette.montant} Ar"
            form.save()
            journaliser(
                request, "recette_modification", recette.reference,
                f"avant : {avant} ; après : {recette.categorie} / {recette.secteur} / "
                f"{recette.mois:%m/%Y} / {recette.montant} Ar",
            )
            messages.success(request, "Recette modifiée.")
            notifier_ecarts_significatifs()
            return redirect("liste_recettes")
    else:
        form = RecetteForm(instance=recette, utilisateur=request.user)
    return render(request, "recettes/formulaire_recette.html",
                  _contexte_formulaire_recette(request, form, f"Modifier {recette.reference}", recette))


@role_requis(*ROLES_GESTION)
def supprimer_recette(request, pk):
    recette = get_object_or_404(Recette, pk=pk)
    if request.method == "POST":
        journaliser(
            request, "recette_suppression", recette.reference,
            f"{recette.categorie} / {recette.secteur} / {recette.mois:%m/%Y} / "
            f"{recette.montant} Ar / {recette.libelle}",
        )
        recette.delete()
        messages.success(request, "Recette supprimée.")
        return redirect("liste_recettes")
    return render(request, "recettes/confirmer_suppression.html", {"objet": recette})


@role_requis(*ROLES_SAISIE)
def bordereau(request, pk):
    recette = get_object_or_404(recettes_visibles(request.user), pk=pk)
    if not recette.piece_jointe:
        raise Http404("Aucune pièce jointe.")
    try:
        fichier = recette.piece_jointe.open("rb")
    except OSError as erreur:
        logger.exception("Pièce justificative introuvable pour la recette %s", recette.pk)
        raise Http404("La pièce justificative n'est plus disponible.") from erreur
    return FileResponse(fichier, as_attachment=False, filename=recette.piece_jointe.name.split("/")[-1])


def _total_par_categorie(annee):
    return {
        l["categorie_id"]: l["t"]
        for l in Recette.objects.filter(mois__year=annee).values("categorie_id").annotate(t=Sum("montant"))
    }


@role_requis(Profil.Role.ADMIN)
def liste_categories(request):
    annee = exercice_courant(request)
    totaux = _total_par_categorie(annee)
    precedents = _total_par_categorie(annee - 1)
    categories = Categorie.objects.prefetch_related("secteurs_habilites")
    nb_secteurs = Secteur.objects.filter(actif=True).count()

    chapitres = []
    for code, libelle in CHAPITRES:
        comptes = []
        for c in categories:
            if c.chapitre != code:
                continue
            habilites = [s.nom.replace("Secteur ", "") for s in c.secteurs_habilites.all()]
            comptes.append({
                "categorie": c,
                "total": totaux.get(c.pk, Decimal("0")),
                "precedent": precedents.get(c.pk, Decimal("0")),
                "habilites": habilites,
                "habilites_ids": [s.pk for s in c.secteurs_habilites.all()],
                "global": not habilites or len(habilites) >= nb_secteurs,
            })
        if comptes:
            chapitres.append({
                "code": code, "libelle": libelle, "description": CHAPITRES_DESCRIPTION[code],
                "comptes": comptes, "total": sum((x["total"] for x in comptes), Decimal("0")),
            })
    total_exec = sum(totaux.values(), Decimal("0"))
    total_prec = sum(precedents.values(), Decimal("0"))
    return render(
        request,
        "recettes/liste_categories.html",
        {
            "chapitres": chapitres,
            "nb_chapitres": len(chapitres),
            "nb_comptes": categories.count(),
            "nb_actifs": categories.filter(actif=True).count(),
            "nb_revision": categories.filter(en_revision=True).count(),
            "total_exec": total_exec,
            "variation": _var_pct(total_exec, total_prec) if total_prec else None,
            "secteurs": Secteur.objects.filter(actif=True),
            "chapitres_choix": CHAPITRES,
            "perceptions": Categorie.Perception.choices,
            "regimes": Categorie.Tva.choices,
            "annee": annee,
        },
    )


@role_requis(Profil.Role.ADMIN)
@require_POST
def ajouter_categorie(request):
    form = CategorieForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Compte créé dans la nomenclature.")
    else:
        _erreurs_en_messages(request, form)
    return redirect("liste_categories")


@role_requis(Profil.Role.ADMIN)
@require_POST
def modifier_categorie(request, pk):
    categorie = get_object_or_404(Categorie, pk=pk)
    form = CategorieForm(request.POST, instance=categorie)
    if form.is_valid():
        form.save()
        messages.success(request, "Compte modifié.")
    else:
        _erreurs_en_messages(request, form)
    return redirect("liste_categories")


@role_requis(Profil.Role.ADMIN)
@require_POST
def basculer_categorie(request, pk):
    categorie = get_object_or_404(Categorie, pk=pk)
    categorie.actif = not categorie.actif
    categorie.save(update_fields=["actif"])
    messages.success(request, f"Compte « {categorie.nom} » {'réactivé' if categorie.actif else 'désactivé'}.")
    return redirect("liste_categories")


@role_requis(Profil.Role.ADMIN)
def gestion_secteurs(request):
    annee = exercice_courant(request)
    suivi = recouvrement_par_secteur(annee=annee)
    secteurs_tous = list(Secteur.objects.select_related("regisseur", "suppleant"))
    presents = {l["secteur"].pk for l in suivi["lignes"]}
    total = suivi["total"]
    lignes = list(suivi["lignes"])
    for s in secteurs_tous:
        if s.pk not in presents and not s.actif:
            lignes.append({"secteur": s, "total": Decimal("0"), "part_pct": 0, "anomalies_ouvertes": 0,
                           "montant_souffrance": Decimal("0"), "retard_jours": 0})
    plafond_total = sum((l["secteur"].plafond_encaissement for l in lignes), Decimal("0"))
    souffrance = sum((l["montant_souffrance"] for l in lignes), Decimal("0"))
    pire = max(lignes, key=lambda l: l["montant_souffrance"], default=None)
    avec_regisseur = sum(1 for l in lignes if l["secteur"].regisseur_id)
    registre = Anomalie.objects.select_related("secteur", "signale_par").order_by("-date_signalement")[:5]
    return render(
        request,
        "recettes/gestion_secteurs.html",
        {
            "lignes": lignes,
            "total": total,
            "plafond_total": plafond_total,
            "souffrance": souffrance,
            "pire": pire if pire and pire["montant_souffrance"] else None,
            "nb_regies": sum(1 for l in lignes if l["secteur"].actif),
            "nb_lignes": len(lignes),
            "sans_anomalie": sum(1 for l in lignes if not l["anomalies_ouvertes"]),
            "avec_regisseur": avec_regisseur,
            "utilisateurs": User.objects.filter(is_active=True).select_related("profil").order_by("first_name", "username"),
            "frequences": Secteur.Frequence.choices,
            "registre": registre,
            "annee": annee,
        },
    )


@role_requis(Profil.Role.ADMIN)
@require_POST
def ajouter_secteur(request):
    form = SecteurForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Secteur créé.")
    else:
        _erreurs_en_messages(request, form)
    return redirect("gestion_secteurs")


@role_requis(Profil.Role.ADMIN)
@require_POST
def modifier_secteur(request, pk):
    secteur = get_object_or_404(Secteur, pk=pk)
    donnees = request.POST.copy()
    if "suspendre" in donnees:
        donnees.pop("actif", None)
    elif "reactiver" in donnees or secteur.actif:
        donnees["actif"] = "on"
    else:
        donnees.pop("actif", None)
    form = SecteurForm(donnees, instance=secteur)
    if form.is_valid():
        form.save()
        messages.success(request, "Secteur mis à jour." if "suspendre" not in request.POST else "Régie suspendue.")
    else:
        _erreurs_en_messages(request, form)
    return redirect("gestion_secteurs")


@role_requis(*ROLES_BUDGET)
def suivi_secteurs(request):
    annee = exercice_courant(request)
    suivi = recouvrement_par_secteur(annee=annee)
    execution = execution_budgetaire(annee)
    total = suivi["total"]
    dernier = suivi["mois_fin"]
    precedent = _somme(Recette.objects.filter(
        mois__year=annee - 1, mois__month__lte=(dernier.month if dernier else 12)))
    lignes = suivi["lignes"]
    for l in lignes:
        l["statut"] = f"1 retard (+{l['retard_jours']}j)" if l["retard_jours"] else (
            f"{l['anomalies_ouvertes']} anomalie(s)" if l["anomalies_ouvertes"] else "Conforme")
        l["alerte"] = bool(l["anomalies_ouvertes"])
    maxi = max((l["total"] for l in lignes), default=Decimal("0")) or Decimal("1")
    for l in lignes:
        l["barre"] = round(float(l["total"] / maxi * 100), 1)
    pilote = lignes[0] if lignes else None
    regies_revue = sum(1 for l in lignes if l["alerte"])
    pire = max(lignes, key=lambda l: l["montant_souffrance"], default=None)
    priorite = None
    if pire and pire["montant_souffrance"]:
        priorite = Anomalie.objects.filter(secteur=pire["secteur"], traitee=False, brouillon=False).order_by("date_echeance").first()
    clotures = Anomalie.objects.filter(traitee=True, date_regularisation__isnull=False)
    delais = [(a.date_regularisation - a.date_signalement).days for a in clotures]
    return render(
        request,
        "recettes/suivi_secteurs.html",
        {
            "suivi": suivi,
            "lignes": lignes,
            "annee": annee,
            "variation_n1": _var_pct(total, precedent) if precedent else None,
            "execution": execution,
            "pilote": pilote,
            "regies_revue": regies_revue,
            "pire": pire if pire and pire["montant_souffrance"] else None,
            "priorite": priorite,
            "delai_moyen": round(sum(delais) / len(delais)) if delais else None,
            "nb_anomalies": Anomalie.objects.filter(traitee=False, brouillon=False).count(),
        },
    )


def _projection_globale(annee, previsions_plates):
    """Séries (réalisé / objectif / prévision) sur 6 mois : 4 derniers mois connus + 2 à venir."""
    dernier = Recette.objects.filter(mois__year=annee).order_by("-mois").values_list("mois", flat=True).first()
    if not dernier:
        return None
    mois = [_mois_moins(dernier, i) for i in (3, 2, 1, 0)] + [_mois_moins(dernier, -1), _mois_moins(dernier, -2)]
    realises = {
        l["mois"]: float(l["t"])
        for l in Recette.objects.filter(mois__in=mois[:4]).values("mois").annotate(t=Sum("montant"))
    }
    objectifs = {
        l["mois"]: float(l["t"])
        for l in ObjectifBudgetaire.objects.filter(mois__in=mois, statut="INSCRIT", secteur__isnull=True)
        .values("mois").annotate(t=Sum("montant_cible"))
    }
    prevus = {}
    for (_, m), v in previsions_plates.items():
        prevus[m] = prevus.get(m, 0.0) + v
    return {
        "mois": mois,
        "realise": [realises.get(m) for m in mois[:4]] + [None, None],
        "objectif": [objectifs.get(m) for m in mois],
        "prevision": [realises.get(m) if i == 3 else None for i, m in enumerate(mois[:4])] + [prevus.get(m) for m in mois[4:]],
    }


@role_requis(*ROLES_BUDGET)
def liste_objectifs(request):
    annee = exercice_courant(request)
    tous_ecarts = calculer_ecarts(annee)
    mois_dispo = sorted({e.mois for e in tous_ecarts}, reverse=True)
    choix_mois = request.GET.get("mois") or (mois_dispo[0].strftime("%Y-%m") if mois_dispo else "tous")
    categorie_id = _chiffres(request.GET.get("categorie"))
    ecarts = tous_ecarts
    if choix_mois != "tous":
        ecarts = [e for e in ecarts if e.mois.strftime("%Y-%m") == choix_mois]
    if categorie_id:
        ecarts = [e for e in ecarts if str(e.categorie_id) == categorie_id]

    mois_label = f"Exercice {annee}" if choix_mois == "tous" else ""
    if choix_mois != "tous":
        try:
            y, mm = choix_mois.split("-")
            mois_label = f"{MOIS_LABELS[int(mm) - 1].capitalize()} {y}"
        except (ValueError, IndexError):
            mois_label = choix_mois
    ecarts_totaux = sans_double_comptage(ecarts)
    total_cible = sum((e.cible for e in ecarts_totaux), Decimal("0"))
    total_realise = sum((e.realise for e in ecarts_totaux), Decimal("0"))
    taux = float(total_realise / total_cible * 100) if total_cible else None
    ecart_net = total_realise - total_cible
    alertes = [e for e in ecarts if e.significatif]
    pire = alertes[0] if alertes else None

    previsions_cat = previsions_par_categorie()
    previsions = prevision_par_mois(previsions_cat)
    confrontation = []
    for objectif in ObjectifBudgetaire.objects.filter(statut="INSCRIT", secteur__isnull=True, mois__year=annee).select_related("categorie"):
        prevu = previsions.get((objectif.categorie_id, objectif.mois))
        if prevu is None:
            continue
        cible = float(objectif.montant_cible)
        confrontation.append({
            "categorie": objectif.categorie.nom, "mois": objectif.mois, "objectif": objectif.montant_cible,
            "prevision": prevu, "ecart_pct": round((prevu - cible) / cible * 100, 1) if cible else None,
        })
    confrontation.sort(key=lambda c: (c["mois"], c["categorie"]))

    proj = _projection_globale(annee, previsions)
    return render(
        request,
        "recettes/liste_objectifs.html",
        {
            "ecarts": ecarts,
            "tous_ecarts": tous_ecarts,
            "mois_dispo": mois_dispo,
            "choix_mois": choix_mois,
            "mois_label": mois_label,
            "categorie_filtre": categorie_id,
            "categories": Categorie.objects.filter(actif=True),
            "total_cible": total_cible,
            "total_realise": total_realise,
            "taux": taux,
            "ecart_net": ecart_net,
            "ecart_net_pct": round(float(ecart_net / total_cible * 100), 1) if total_cible else None,
            "nb_alertes": len(alertes),
            "pire": pire,
            "fiabilite": fiabilite_modele(),
            "confrontation": confrontation,
            "brouillons": ObjectifBudgetaire.objects.filter(statut="BROUILLON").count(),
            "svg_projection": graphiques.svg_projection(proj["realise"], proj["objectif"], proj["prevision"]) if proj else "",
            "proj_mois": [m for m in (proj["mois"] if proj else [])],
            "peut_gerer": request.user.profil.role in ROLES_GESTION,
            "parametres": ParametrageSysteme.charger(),
            "avertissements": avertissements_modele(previsions_cat),
            "annee": annee,
        },
    )


@role_requis(*ROLES_GESTION)
def ajouter_objectif(request):
    annee = exercice_courant(request)
    if request.method == "POST":
        form = ObjectifForm(request.POST)
        if form.is_valid():
            objectif = form.save(commit=False)
            objectif.fixe_par = request.user
            brouillon = request.POST.get("action") == "brouillon"
            objectif.statut = ObjectifBudgetaire.Statut.BROUILLON if brouillon else ObjectifBudgetaire.Statut.INSCRIT
            objectif.full_clean(exclude=["fixe_par"])
            objectif.save()
            journaliser(
                request, "objectif_creation", f"{objectif.categorie} {objectif.mois:%m/%Y}",
                f"{objectif.get_type_budget_display()} / {objectif.secteur or 'consolidé'} / "
                f"{objectif.montant_cible} Ar",
            )
            messages.success(request, "Brouillon enregistré." if brouillon else "Objectif budgétaire inscrit au budget prévisionnel.")
            if not brouillon:
                notifier_ecarts_significatifs()
            return redirect("liste_objectifs")
    else:
        form = ObjectifForm()
    mois_options = [date(annee, m, 1) for m in range(1, 13)]
    categories = list(Categorie.objects.filter(actif=True))
    hist = {}
    for l in Recette.objects.filter(categorie__in=categories).values("categorie_id", "mois").annotate(t=Sum("montant")).order_by("mois"):
        hist.setdefault(str(l["categorie_id"]), []).append([l["mois"].strftime("%Y-%m"), float(l["t"])])
    return render(
        request,
        "recettes/formulaire_objectif.html",
        {
            "form": form,
            "annee": annee,
            "mois_defaut": timezone.localdate().replace(day=1),
            "mois_options": mois_options,
            "categories": categories,
            "chapitres": CHAPITRES,
            "secteurs": Secteur.objects.filter(actif=True),
            "historique_json": _json_sur(hist),
            "recents": ObjectifBudgetaire.objects.select_related("categorie", "fixe_par").order_by("-date_creation")[:3],
            "parametres": ParametrageSysteme.charger(),
        },
    )


@role_requis(*ROLES_GESTION)
@require_POST
def supprimer_objectif(request, pk):
    objectif = get_object_or_404(ObjectifBudgetaire, pk=pk)
    journaliser(
        request, "objectif_suppression", f"{objectif.categorie} {objectif.mois:%m/%Y}",
        f"{objectif.get_type_budget_display()} / {objectif.secteur or 'consolidé'} / "
        f"{objectif.montant_cible} Ar",
    )
    objectif.delete()
    messages.success(request, "Objectif supprimé.")
    return redirect("liste_objectifs")


@role_requis(*ROLES_BUDGET)
def comparaison(request):
    try:
        nb_annees = max(2, min(int(request.GET.get("annees", 3)), 10))
    except ValueError:
        nb_annees = 3
    donnees = comparaison_exercices(nb_annees, exercice_courant(request))
    graphes = {}
    if donnees["annees"]:
        groupes = [{"label": c["chapitre"], "valeurs": [float(c["totaux"][a]) for a in donnees["annees"]]}
                   for c in donnees["lignes_chapitres"]]
        total_proj = float(donnees["projection_totale"] or 0) or 1
        couleurs = ["#25272C", "#0D9488", "#5EEAD4", "#CBD5E1", "#94A3B8", "#64748B"]
        parts, legende = [], []
        for i, c in enumerate(donnees["lignes_chapitres"]):
            p = float(c["projection"]) / total_proj * 100
            parts.append((p, couleurs[i % len(couleurs)]))
            legende.append({"chapitre": c["chapitre"], "pct": p, "couleur": couleurs[i % len(couleurs)]})
        graphes = {
            "barres": graphiques.svg_barres(groupes, len(donnees["annees"])),
            "donut": graphiques.svg_donut(parts),
            "legende": legende,
            "groupes": groupes,
            "couleurs_annees": graphiques.COULEURS_ANNEES,
        }
    total_cumul = sum(donnees["totaux_generaux"].values(), Decimal("0")) if donnees["annees"] else Decimal("0")
    closes = [a for a in donnees["annees"] if a != donnees["avertissement_annee_partielle"]]
    var_a, var_b = (closes[-1], closes[-2]) if len(closes) >= 2 else (None, None)
    for c in donnees["lignes_chapitres"]:
        c["libelle"] = LIBELLE_CHAPITRE.get(c["chapitre"], c["chapitre"]).split("— ")[-1]
        c["var_close"] = c["variations"].get(var_a) if var_a else None
    if graphes:
        graphes["legende_annees"] = list(zip(donnees["annees"], graphiques.COULEURS_ANNEES))
        for g, c in zip(graphes["groupes"], donnees["lignes_chapitres"]):
            g["libelle"] = c["libelle"]
    derniere_close = None
    if donnees["annees"]:
        closes = [a for a in donnees["annees"] if a != donnees["avertissement_annee_partielle"]]
        if closes:
            a = closes[-1]
            idx = donnees["annees"].index(a)
            derniere_close = {
                "annee": a, "total": donnees["totaux_generaux"][a],
                "variation": donnees["variations_generales"].get(a) if idx > 0 else None,
            }
    return render(
        request,
        "recettes/comparaison.html",
        {
            "comparaison": donnees,
            "nb_annees": nb_annees,
            "choix_annees": [(3, "3 derniers exercices"), (5, "5 exercices"), (10, "Historique complet")],
            "graphes": graphes,
            "total_cumul": total_cumul,
            "derniere_close": derniere_close,
            "var_a": var_a,
            "var_b": var_b,
            "var_generale": donnees["variations_generales"].get(var_a) if var_a else None,
            "annee_derniere": donnees["annees"][-1] if donnees["annees"] else None,
            "annee_premiere": donnees["annees"][0] if donnees["annees"] else None,
            "part_recettes_propres": _part_recettes_propres(donnees),
        },
    )


def _part_recettes_propres(donnees):
    """Part des recettes hors dotations et subventions (chapitres 74 et 13) dans le total."""
    if not donnees["annees"]:
        return None
    derniere = donnees["annees"][-1]
    total = donnees["totaux_generaux"].get(derniere) or Decimal("0")
    if not total:
        return None
    externes = sum((c["totaux"][derniere] for c in donnees["lignes_chapitres"] if c["chapitre"] in ("74", "13")), Decimal("0"))
    return round(float((total - externes) / total * 100), 1)


@role_requis(*ROLES_ANOMALIES)
def liste_anomalies(request):
    impose = secteur_impose(request.user)
    secteur_id = str(impose) if impose is not None else _chiffres(request.GET.get("secteur"))
    visibles = anomalies_visibles(request.user)
    relations = ("categorie", "secteur", "signale_par", "assigne_a")
    if request.GET.get("archives"):
        anomalies = visibles.select_related(*relations).filter(traitee=True)
    else:
        anomalies = visibles.select_related(*relations).filter(traitee=False, brouillon=False)
    if secteur_id:
        anomalies = anomalies.filter(secteur_id=secteur_id)
    liste = list(anomalies)
    brouillons = Anomalie.objects.filter(brouillon=True, signale_par=request.user)
    selection = None
    dossier = _chiffres(request.GET.get("dossier"))
    if dossier:
        selection = visibles.filter(pk=dossier).select_related(*relations).first()
    if selection is None and liste:
        selection = liste[0]
    ouvertes = visibles.filter(traitee=False, brouillon=False)
    en_retard = [a for a in ouvertes if a.en_retard]
    clotures = visibles.filter(traitee=True, date_regularisation__isnull=False)
    delais = [(a.date_regularisation - a.date_signalement).days for a in clotures]
    montant_retard = sum((a.montant for a in en_retard), Decimal("0"))
    return render(
        request,
        "recettes/liste_anomalies.html",
        {
            "anomalies": liste,
            "selection": selection,
            "echanges": selection.echanges.select_related("auteur") if selection else [],
            "secteurs": Secteur.objects.filter(actif=True, pk=impose) if impose is not None else Secteur.objects.filter(actif=True),
            "secteur_filtre": secteur_id,
            "archives": bool(request.GET.get("archives")),
            "nb_ouvertes": ouvertes.count(),
            "nb_retard": len(en_retard),
            "montant_attente": _somme(ouvertes, "montant"),
            "montant_retard": montant_retard,
            "delai_moyen": round(sum(delais) / len(delais)) if delais else None,
            "brouillons": brouillons,
            "peut_gerer": request.user.profil.role in ROLES_GESTION,
        },
    )


@role_requis(*ROLES_ANOMALIES)
def signaler_anomalie(request, pk=None):
    anomalie = None
    if pk:
        anomalie = get_object_or_404(anomalies_visibles(request.user), pk=pk)
        if not (anomalie.brouillon and anomalie.signale_par_id == request.user.pk) and request.user.profil.role not in ROLES_GESTION:
            messages.error(request, "Ce dossier ne peut plus être modifié.")
            return redirect("liste_anomalies")
    if request.method == "POST":
        form = AnomalieForm(request.POST, request.FILES, instance=anomalie, utilisateur=request.user)
        if form.is_valid():
            brouillon = request.POST.get("action") == "brouillon"
            objet = form.save(commit=False)
            objet.signale_par = objet.signale_par or request.user
            objet.brouillon = brouillon
            objet.full_clean(exclude=["signale_par"])
            objet.save()
            if brouillon:
                messages.success(request, "Brouillon enregistré.")
                return redirect("modifier_anomalie", pk=objet.pk)
            EchangeAnomalie.objects.create(anomalie=objet, auteur=request.user, titre="Signalement transmis",
                                           texte=f"Dossier ouvert par {request.user.get_full_name() or request.user.username}.")
            notifier_anomalie(objet)
            messages.success(request, "Anomalie signalée et responsables notifiés.")
            return redirect(f"{reverse('liste_anomalies')}?dossier={objet.pk}")
    else:
        initial = {
            "date_constat": timezone.localdate(),
            "date_echeance": timezone.localdate() + timedelta(days=15),
        }
        secteur = getattr(request.user.profil, "secteur", None)
        if secteur:
            initial["secteur"] = secteur
        form = AnomalieForm(instance=anomalie, utilisateur=request.user, initial=initial)
    return render(
        request,
        "recettes/formulaire_anomalie.html",
        {
            "form": form,
            "anomalie": anomalie,
            "nb_en_cours": anomalies_visibles(request.user).filter(traitee=False, brouillon=False).count(),
            "prochaine_ref": anomalie.reference if anomalie else f"ANO-{timezone.localdate().year}-{(Anomalie.objects.order_by('-pk').values_list('pk', flat=True).first() or 0) + 1:03d}",
        },
    )


@role_requis(*ROLES_GESTION)
@require_POST
def traiter_anomalie(request, pk):
    anomalie = get_object_or_404(Anomalie, pk=pk)
    anomalie.traitee = True
    anomalie.date_regularisation = timezone.now()
    anomalie.save()
    EchangeAnomalie.objects.create(anomalie=anomalie, auteur=request.user, titre="Dossier régularisé",
                                   texte="Écart apuré, dossier clos.")
    messages.success(request, "Anomalie marquée comme traitée.")
    return redirect("liste_anomalies")


@role_requis(*ROLES_GESTION)
@require_POST
def relancer_anomalie(request, pk):
    anomalie = get_object_or_404(Anomalie, pk=pk)
    if anomalie.assigne_a is None:
        messages.error(request, "Aucun régisseur n'est assigné à ce dossier.")
    elif notifier_relance(anomalie, request.user):
        EchangeAnomalie.objects.create(anomalie=anomalie, auteur=request.user, titre="Relance du régisseur",
                                       texte=f"Relance adressée à {anomalie.assigne_a.get_full_name() or anomalie.assigne_a.username}.")
        messages.success(
            request,
            "Relance enregistrée dans l'application ; l'e-mail suit les préférences du destinataire.",
        )
    else:
        messages.info(request, "Ce régisseur a déjà été relancé aujourd'hui sur ce dossier.")
    return redirect(f"{reverse('liste_anomalies')}?dossier={pk}")


@role_requis(*ROLES_ANOMALIES)
@require_POST
def supprimer_anomalie(request, pk):
    anomalie = get_object_or_404(Anomalie, pk=pk)
    if request.user.profil.role not in ROLES_GESTION and not (anomalie.brouillon and anomalie.signale_par_id == request.user.pk):
        messages.error(request, "Vous ne pouvez supprimer que vos brouillons.")
        return redirect("liste_anomalies")
    journaliser(request, "anomalie_suppression", anomalie.reference, anomalie.intitule)
    anomalie.delete()
    messages.success(request, "Dossier supprimé.")
    return redirect("liste_anomalies")


@role_requis(*ROLES_ANOMALIES)
def piece_anomalie(request, pk):
    anomalie = get_object_or_404(anomalies_visibles(request.user), pk=pk)
    if not anomalie.piece_jointe:
        raise Http404("Aucune pièce jointe.")
    try:
        fichier = anomalie.piece_jointe.open("rb")
    except OSError as erreur:
        logger.exception("Pièce justificative introuvable pour l'anomalie %s", anomalie.pk)
        raise Http404("La pièce justificative n'est plus disponible.") from erreur
    return FileResponse(fichier, filename=anomalie.piece_jointe.name.split("/")[-1])


@login_required
def liste_notifications(request):
    notifications = list(Notification.objects.filter(destinataire=request.user))
    debut_mois = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    traitees = [n for n in notifications if n.traitee and n.date_traitement and n.date_traitement >= debut_mois]
    delais = [(n.date_traitement - n.date_creation).total_seconds() for n in notifications if n.traitee and n.date_traitement]
    delai_h = (sum(delais) / len(delais) / 3600) if delais else None
    a_traiter = [n for n in notifications if not n.traitee]
    parametres = ParametrageSysteme.charger()
    destinataires = Profil.objects.filter(
        role__in=[Profil.Role.RESPONSABLE, Profil.Role.ADMIN, Profil.Role.ELU],
        recevoir_notifications=True, user__is_active=True,
    ).select_related("user", "secteur").order_by("role")
    return render(
        request,
        "recettes/liste_notifications.html",
        {
            "notifications": notifications,
            "nb_a_traiter": len(a_traiter),
            "nb_non_lues": sum(1 for n in notifications if not n.lue),
            "nb_traitees_mois": len(traitees),
            "delai_h": delai_h,
            "parametres": parametres,
            "destinataires": destinataires,
            "peut_declencher": request.user.profil.role in ROLES_GESTION,
        },
    )


@login_required
@require_POST
def marquer_notifications_lues(request):
    Notification.objects.filter(destinataire=request.user, lue=False).update(lue=True)
    messages.success(request, "Notifications marquées comme lues.")
    return redirect("liste_notifications")


@login_required
def ouvrir_notification(request, pk):
    notif = get_object_or_404(Notification, pk=pk, destinataire=request.user)
    if not notif.lue:
        notif.lue = True
        notif.save(update_fields=["lue"])
    lien = notif.lien
    if lien.startswith("liste_") or lien in ("dashboard",):
        return redirect(lien)
    if lien:
        return redirect("/" + lien.lstrip("/"))
    return redirect("liste_notifications")


@login_required
@require_POST
def traiter_notification(request, pk):
    notif = get_object_or_404(Notification, pk=pk, destinataire=request.user)
    notif.traitee = True
    notif.lue = True
    notif.date_traitement = timezone.now()
    notif.save(update_fields=["traitee", "lue", "date_traitement"])
    return redirect("liste_notifications")


@role_requis(Profil.Role.ADMIN, Profil.Role.RESPONSABLE)
@require_POST
def declencher_notifications(request):
    nb = notifier_ecarts_significatifs() + notifier_anomalies_en_attente()
    messages.success(
        request,
        f"{nb} notification(s) créée(s) ou relancée(s)."
        if nb else "Vérification terminée : aucune nouvelle alerte à notifier.",
    )
    return redirect(_page_suivante(request, "liste_notifications"))


@role_requis(Profil.Role.ADMIN)
def liste_utilisateurs(request):
    utilisateurs = list(User.objects.select_related("profil", "profil__secteur").order_by("username"))
    actifs = [u for u in utilisateurs if u.is_active]
    return render(
        request,
        "recettes/liste_utilisateurs.html",
        {
            "utilisateurs": utilisateurs,
            "nb_actifs": len(actifs),
            "nb_total": len(utilisateurs),
            "nb_regisseurs": Secteur.objects.exclude(regisseur=None).count(),
            "nb_responsables": sum(1 for u in actifs if u.profil.role == Profil.Role.RESPONSABLE),
            "nb_attente": sum(1 for u in utilisateurs if u.profil.en_attente),
            "sans_email": sum(1 for u in utilisateurs if not u.email),
            "roles": Profil.Role.choices,
            "secteurs": Secteur.objects.filter(actif=True),
        },
    )


def _est_dernier_admin_actif(utilisateur):
    profil = getattr(utilisateur, "profil", None)
    if not (profil and profil.role == Profil.Role.ADMIN and utilisateur.is_active):
        return False
    return not User.objects.filter(
        is_active=True, profil__role=Profil.Role.ADMIN
    ).exclude(pk=utilisateur.pk).exists()


def _envoyer_lien_mot_de_passe(request, utilisateur):
    if not utilisateur.email:
        return False
    formulaire = PasswordResetForm({"email": utilisateur.email})
    if formulaire.is_valid():
        try:
            formulaire.save(
                request=request,
                subject_template_name="recettes/email/mot_de_passe_sujet.txt",
                email_template_name="recettes/email/mot_de_passe_corps.txt",
                from_email=None,
                use_https=request.is_secure(),
            )
        except (OSError, smtplib.SMTPException):
            logger.exception("Échec de l'envoi du lien de mot de passe à %s", utilisateur.email)
            return False
        return True
    return False


@role_requis(Profil.Role.ADMIN)
@require_POST
def inviter_utilisateur(request):
    form = UtilisateurAdminForm(request.POST)
    if form.is_valid():
        user = form.save()
        envoye = _envoyer_lien_mot_de_passe(request, user)
        if envoye:
            messages.success(request, f"Invitation créée pour {user.email}. Un lien de création de mot de passe a été envoyé.")
        else:
            messages.error(
                request,
                f"Invitation créée pour {user.email}, mais l'envoi du lien a échoué. "
                "Vous pouvez réessayer depuis la gestion des utilisateurs.",
            )
    else:
        _erreurs_en_messages(request, form)
    return redirect("liste_utilisateurs")


@role_requis(Profil.Role.ADMIN)
@require_POST
def modifier_utilisateur(request, pk):
    utilisateur = get_object_or_404(User, pk=pk)
    donnees = request.POST.copy()
    if utilisateur == request.user:
        donnees["is_active"] = "on"
        donnees["role"] = Profil.Role.ADMIN
    elif _est_dernier_admin_actif(utilisateur) and (
        donnees.get("role") != Profil.Role.ADMIN or "is_active" not in donnees
    ):
        messages.error(request, "Impossible : ce compte est le dernier administrateur actif.")
        return redirect("liste_utilisateurs")
    form = UtilisateurAdminForm(donnees, instance=utilisateur)
    if form.is_valid():
        form.save()
        journaliser(
            request, "utilisateur_modification", utilisateur.username,
            f"role={utilisateur.profil.role}",
        )
        messages.success(request, f"Compte « {utilisateur.email or utilisateur.username} » mis à jour.")
    else:
        _erreurs_en_messages(request, form)
    return redirect("liste_utilisateurs")


@role_requis(Profil.Role.ADMIN)
@require_POST
def basculer_utilisateur(request, pk):
    utilisateur = get_object_or_404(User, pk=pk)
    if utilisateur == request.user or _est_dernier_admin_actif(utilisateur):
        messages.error(
            request,
            "Ce compte ne peut pas être désactivé (compte courant ou dernier administrateur actif).",
        )
        return redirect("liste_utilisateurs")
    journaliser(request, "utilisateur_bascule", utilisateur.username)
    utilisateur.is_active = not utilisateur.is_active
    utilisateur.save(update_fields=["is_active"])
    etat = "réactivé" if utilisateur.is_active else "désactivé"
    messages.success(request, f"Compte « {utilisateur.username} » {etat}.")
    return redirect("liste_utilisateurs")


@role_requis(Profil.Role.ADMIN)
@require_POST
def arbitrer_utilisateur(request, pk):
    utilisateur = get_object_or_404(User, pk=pk)
    profil = utilisateur.profil
    if not profil.en_attente or utilisateur == request.user:
        messages.error(request, "Cette demande n'est pas en attente d'arbitrage.")
        return redirect("liste_utilisateurs")
    decision = request.POST.get("decision")
    if decision not in {"valider", "refuser"}:
        messages.error(request, "Choisissez explicitement de valider ou de refuser cette demande.")
        return redirect("liste_utilisateurs")
    journaliser(
        request,
        "habilitation_" + ("validation" if decision == "valider" else "refus"),
        utilisateur.username,
    )
    if decision == "valider":
        utilisateur.is_active = True
        utilisateur.save(update_fields=["is_active"])
        profil.en_attente = False
        profil.save(update_fields=["en_attente"])
        email_envoye = True
        if utilisateur.email:
            from django.core.mail import send_mail

            try:
                email_envoye = bool(send_mail(
                    "[Recettes collectivité] Habilitation validée",
                    f"Bonjour {profil.nom_affiche},\n\nVotre demande {profil.reference_demande} a été validée. "
                    "Vous pouvez désormais vous connecter avec votre adresse e-mail et votre mot de passe.",
                    settings.DEFAULT_FROM_EMAIL, [utilisateur.email], fail_silently=False,
                ))
            except (OSError, smtplib.SMTPException):
                logger.exception("Échec de l'envoi de l'e-mail de validation à %s", utilisateur.email)
                email_envoye = False
        if email_envoye:
            messages.success(request, f"Habilitation validée pour {profil.nom_affiche}.")
        else:
            messages.warning(
                request,
                f"Habilitation validée pour {profil.nom_affiche}, mais l'e-mail n'a pas pu être envoyé.",
            )
    else:
        nom = profil.nom_affiche
        utilisateur.is_active = False
        utilisateur.save(update_fields=["is_active"])
        profil.en_attente = False
        profil.save(update_fields=["en_attente"])
        messages.success(request, f"Demande de {nom} refusée. Le compte a été désactivé et conservé.")
    return redirect("liste_utilisateurs")


@role_requis(Profil.Role.ADMIN)
@require_POST
def cle_utilisateur(request, pk):
    utilisateur = get_object_or_404(User, pk=pk)
    if _envoyer_lien_mot_de_passe(request, utilisateur):
        messages.success(request, f"Lien de réinitialisation du mot de passe envoyé à {utilisateur.email}.")
    else:
        messages.error(request, "Impossible d'envoyer le lien : aucune adresse e-mail valide pour ce compte.")
    return redirect("liste_utilisateurs")


@role_requis(Profil.Role.ADMIN)
def parametrage(request):
    parametres = ParametrageSysteme.charger()
    if request.method == "POST":
        form = ParametrageForm(request.POST, instance=parametres)
        if form.is_valid():
            objet = form.save(commit=False)
            objet.modifie_par = request.user
            objet.save()
            journaliser(request, "parametrage_modification", "Paramétrage du système", str(form.cleaned_data))
            messages.success(request, "Paramétrage enregistré. Les prévisions et alertes en tiennent compte immédiatement.")
            return redirect(_page_suivante(request, "parametrage"))
    else:
        form = ParametrageForm(instance=parametres)
    return render(request, "recettes/parametrage.html", {"form": form, "parametres": parametres})


DOCUMENTS = [
    ("LIASSE", "Liasse mensuelle", "Réalisé vs Prévisions, analyse par chapitre comptable.", "Officiel", "PDF / Excel"),
    ("SYNTHESE", "Synthèse analytique", "Trajectoire budgétaire, comparatif n-1 et taux de recouvrement.", "Élus & DGS", "PDF"),
    ("ANOMALIES", "État des anomalies & régies", "Suivi des contentieux, décalages et relances comptables.", "Anomalies", "PDF / Excel"),
]


def _construire_rapport(type_doc, format_, annee, mois=None, secteur_id=None):
    if format_ == "CSV":
        reponse = (
            exports.export_anomalies_csv(secteur_id=secteur_id) if type_doc == "ANOMALIES"
            else exports.export_recettes_csv(annee=annee, secteur_id=secteur_id)
        )
        return reponse.content, reponse["Content-Type"], "csv"
    if format_ == "XLSX":
        contenu = generer_rapport_xlsx(type_doc, annee, mois).getvalue()
        return contenu, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    return generer_rapport_pdf(type_doc, annee, mois).getvalue(), "application/pdf", "pdf"


@role_requis(*ROLES_BUDGET)
def rapports(request):
    annee = exercice_courant(request)
    if request.method == "POST":
        if request.user.profil.role not in ROLES_BUDGET:
            raise Http404
        type_doc = request.POST.get("doc_type", "LIASSE")
        format_ = request.POST.get("format", "PDF")
        if type_doc not in dict(RapportGenere.TypeDoc.choices) or format_ not in dict(RapportGenere.Format.choices):
            raise Http404
        mois = mois_depuis_texte(request.POST.get("mois")) if type_doc == "LIASSE" else None
        if mois and mois.year != annee:
            annee = mois.year
        contenu, mime, extension = _construire_rapport(type_doc, format_, annee, mois)
        periode = f"{MOIS_LABELS[mois.month - 1].capitalize()} {mois.year}" if mois else f"Exercice {annee}"
        rapport = RapportGenere.objects.create(
            type_doc=type_doc, format=format_, periode=periode, cree_par=request.user, taille=len(contenu),
        )
        rapport.fichier.save(f"{rapport.reference}.{extension}", ContentFile(contenu), save=True)
        journaliser(request, "rapport_genere", rapport.reference, f"{type_doc} {format_} {periode}")
        if request.POST.get("envoi") == "email":
            if not request.user.email:
                messages.error(request, "Votre compte n'a pas d'adresse e-mail : aucun envoi effectué.")
            elif _envoyer_rapport(request.user, rapport, contenu, mime, extension):
                messages.success(request, f"Rapport {rapport.reference} transmis à {request.user.email}.")
            else:
                messages.error(request, "L'envoi de l'e-mail a échoué. Le rapport reste téléchargeable depuis l'historique.")
            return redirect("rapports")
        reponse = HttpResponse(contenu, content_type=mime)
        reponse["Content-Disposition"] = f'attachment; filename="{rapport.reference}.{extension}"'
        return reponse

    recettes = Recette.objects.filter(mois__year=annee)
    total = _somme(recettes)
    budget = _somme(ObjectifBudgetaire.objects.filter(mois__year=annee, statut="INSCRIT", secteur__isnull=True), "montant_cible")
    par_chapitre = []
    for code, libelle in CHAPITRES:
        realise = _somme(recettes.filter(categorie__chapitre=code))
        cible = _somme(ObjectifBudgetaire.objects.filter(
            mois__year=annee, statut="INSCRIT", secteur__isnull=True, categorie__chapitre=code), "montant_cible")
        if realise or cible:
            par_chapitre.append({"code": code, "libelle": libelle.split("— ")[-1], "realise": realise,
                                 "pct": round(float(realise / cible * 100), 1) if cible else None})
    historique = RapportGenere.objects.select_related("cree_par")
    return render(
        request,
        "recettes/rapports.html",
        {
            "documents": DOCUMENTS,
            "historique": historique[:5],
            "nb_rapports": historique.count(),
            "dernier": historique.first(),
            "annee": annee,
            "total": total,
            "budget": budget,
            "reste": budget - total if budget else None,
            "pct_budget": round(float(total / budget * 100), 1) if budget else None,
            "par_chapitre": par_chapitre,
            "mois_options": [
                (d.strftime("%Y-%m"), f"{MOIS_LABELS[d.month - 1].capitalize()} {d.year}")
                for d in sorted(
                    set(Recette.objects.filter(mois__year=annee).values_list("mois", flat=True)),
                    reverse=True,
                )
            ],
            "nb_anomalies": Anomalie.objects.filter(traitee=False, brouillon=False).count(),
            "montant_anomalies": _somme(Anomalie.objects.filter(traitee=False, brouillon=False), "montant"),
            "exports": [(k, v) for k, v in [
                ("recettes", "Recettes (CSV)"), ("objectifs", "Objectifs budgétaires (CSV)"),
                ("ecarts", "Écarts (CSV)"), ("previsions", "Prévisions (CSV)"),
                ("exercices", "Comparaison des exercices (CSV)"), ("secteurs", "Recouvrement par secteur (CSV)"),
                ("anomalies", "Anomalies (CSV)"), ("categories", "Catégories (CSV)"),
            ]],
        },
    )


def _envoyer_rapport(utilisateur, rapport, contenu, mime, extension):
    message = EmailMessage(
        subject=f"[Recettes collectivité] {rapport.get_type_doc_display()} — {rapport.reference}",
        body=f"Bonjour,\n\nVeuillez trouver ci-joint le document {rapport.reference} ({rapport.periode}).",
        from_email=settings.DEFAULT_FROM_EMAIL, to=[utilisateur.email],
    )
    message.attach(f"{rapport.reference}.{extension}", contenu, mime)
    try:
        return bool(message.send(fail_silently=False))
    except (OSError, smtplib.SMTPException):
        logger.exception("Échec de l'envoi du rapport %s à %s", rapport.pk, utilisateur.email)
        return False


@role_requis(*ROLES_BUDGET)
def telecharger_rapport(request, pk):
    rapport = get_object_or_404(RapportGenere, pk=pk)
    if rapport.fichier:
        extension = rapport.fichier.name.rsplit(".", 1)[-1]
        mimes = {
            "pdf": "application/pdf",
            "csv": "text/csv; charset=utf-8",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
        try:
            with rapport.fichier.open("rb") as fichier:
                contenu = fichier.read()
        except OSError as erreur:
            logger.exception("Fichier du rapport %s introuvable", rapport.pk)
            raise Http404("Le fichier du rapport n'est plus disponible.") from erreur
        mime = mimes.get(extension, "application/octet-stream")
    else:
        annee = (
            int(rapport.periode.split()[-1])
            if rapport.periode.split()[-1].isdigit() else exercice_courant(request)
        )
        contenu, mime, extension = _construire_rapport(rapport.type_doc, rapport.format, annee)
    reponse = HttpResponse(contenu, content_type=mime)
    reponse["Content-Disposition"] = f'attachment; filename="{rapport.reference}.{extension}"'
    return reponse


@role_requis(*ROLES_BUDGET)
def rapport_pdf(request):
    contenu = generer_rapport_pdf("LIASSE", exercice_courant(request)).getvalue()
    reponse = HttpResponse(contenu, content_type="application/pdf")
    reponse["Content-Disposition"] = 'attachment; filename="rapport_recettes.pdf"'
    return reponse


EXPORTS_DISPONIBLES = {
    "recettes": exports.export_recettes_csv,
    "objectifs": exports.export_objectifs_csv,
    "ecarts": exports.export_ecarts_csv,
    "previsions": exports.export_previsions_csv,
    "exercices": exports.export_comparaison_exercices_csv,
    "secteurs": exports.export_secteurs_csv,
    "anomalies": exports.export_anomalies_csv,
    "categories": exports.export_categories_csv,
}


@role_requis(*ROLES_BUDGET, Profil.Role.AGENT)
def export_csv(request, jeu):
    generateur = EXPORTS_DISPONIBLES.get(jeu)
    if generateur is None:
        raise Http404("Type d'export inconnu.")
    if request.user.profil.role == Profil.Role.AGENT and jeu not in ("recettes", "anomalies"):
        messages.error(request, "Vous n'avez pas les droits nécessaires pour cet export.")
        return redirect("dashboard")
    journaliser(request, "export_csv", jeu)
    return generateur(annee=exercice_courant(request), secteur_id=secteur_impose(request.user))


@role_requis(Profil.Role.ADMIN, Profil.Role.RESPONSABLE)
def liste_facteurs(request):
    if request.method == "POST":
        form = FacteurEconomiqueForm(request.POST)
        if form.is_valid():
            facteur = form.save(commit=False)
            facteur.cree_par = request.user
            facteur.full_clean(exclude=["cree_par"])
            facteur.save()
            journaliser(request, "facteur_creation", facteur.libelle, str(facteur.effet_pct))
            messages.success(
                request, "Facteur économique enregistré. Les prévisions en tiennent compte immédiatement."
            )
            return redirect("liste_facteurs")
        _erreurs_en_messages(request, form)
    else:
        form = FacteurEconomiqueForm()
    return render(request, "recettes/facteurs.html", {
        "form": form,
        "facteurs": FacteurEconomique.objects.select_related("categorie"),
    })


@role_requis(Profil.Role.ADMIN, Profil.Role.RESPONSABLE)
@require_POST
def supprimer_facteur(request, pk):
    facteur = get_object_or_404(FacteurEconomique, pk=pk)
    journaliser(request, "facteur_suppression", facteur.libelle)
    facteur.delete()
    messages.success(request, "Facteur supprimé.")
    return redirect("liste_facteurs")
