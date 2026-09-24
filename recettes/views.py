import json
from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, LogoutView
from django.core.mail import EmailMessage
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.db.models.functions import ExtractYear
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import exports, graphiques
from .alertes import (
    alertes_significatives,
    calculer_ecarts,
    execution_budgetaire,
    recouvrement_par_secteur,
)
from .context_processors import annees_disponibles, exercice_courant
from .decorateurs import role_requis
from .forms import (
    AnomalieForm,
    CategorieForm,
    ConnexionForm,
    HabilitationForm,
    ObjectifForm,
    ParametrageForm,
    RecetteForm,
    SecteurForm,
    UtilisateurAdminForm,
)
from .formats import ar
from .models import (
    CHAPITRES,
    CHAPITRES_DESCRIPTION,
    Anomalie,
    Categorie,
    EchangeAnomalie,
    Notification,
    ObjectifBudgetaire,
    ParametrageSysteme,
    Profil,
    RapportGenere,
    Recette,
    Secteur,
)
from .notifications import (
    notifier_anomalie,
    notifier_ecarts_significatifs,
    notifier_habilitation,
    notifier_relance,
)
from .prevision import fiabilite_modele, prevision_par_mois, previsions_par_categorie, serie_globale
from .rapports import (
    comparaison_exercices,
    generer_rapport_pdf,
    generer_rapport_xlsx,
)

ROLES_SAISIE = (Profil.Role.ADMIN, Profil.Role.RESPONSABLE, Profil.Role.AGENT)
ROLES_GESTION = (Profil.Role.ADMIN, Profil.Role.RESPONSABLE)
ROLES_BUDGET = (*ROLES_GESTION, Profil.Role.ELU)
ROLES_ANOMALIES = (Profil.Role.AGENT, *ROLES_GESTION)

MOIS_LABELS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
               "septembre", "octobre", "novembre", "décembre"]
LIBELLE_CHAPITRE = dict(CHAPITRES)


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

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["exercices"] = annees_disponibles()
        return ctx

    def form_valid(self, form):
        reponse = super().form_valid(form)
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
    parametres = ParametrageSysteme.charger()
    recettes_annee = Recette.objects.filter(mois__year=annee)
    total = _somme(recettes_annee)
    dernier_mois = recettes_annee.order_by("-mois").values_list("mois", flat=True).first()
    if dernier_mois:
        precedent = _somme(Recette.objects.filter(mois__year=annee - 1, mois__month__lte=dernier_mois.month))
    else:
        precedent = Decimal("0")
    execution = execution_budgetaire(annee)
    ecarts = calculer_ecarts(annee)
    alertes = [e for e in ecarts if e.significatif]
    pire = alertes[0] if alertes else (ecarts[0] if ecarts else None)

    suivi = recouvrement_par_secteur(annee=annee)
    for ligne in suivi["lignes"]:
        ligne["statut"] = "À surveiller" if ligne["anomalies_ouvertes"] else "Conforme"
    anomalies_ouvertes = Anomalie.objects.filter(traitee=False, brouillon=False)
    montant_anomalies = _somme(anomalies_ouvertes, "montant")

    previsions = previsions_par_categorie()
    globale = serie_globale()
    svg_traj = graphiques.svg_trajectoire(globale)
    hist = globale["mois_historique"][-12:]
    etiquettes = []
    if hist:
        etiquettes = [hist[0], hist[len(hist) // 3] if len(hist) > 3 else hist[0], hist[-1] + " (Actuel)"]
        etiquettes.append((globale["mois_prevus"][-1] + " (Projeté)") if globale["mois_prevus"] else "")

    focus = None
    if pire:
        serie = previsions.get(str(pire.categorie_id))
        if serie:
            focus = {
                "ecart": pire,
                "svg": graphiques.svg_focus(
                    serie["montants_historique"], float(pire.cible), serie["montants_prevus"], pire.ecart_pct
                ),
            }

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
            "svg_trajectoire": svg_traj,
            "etiquettes_trajectoire": etiquettes,
            "focus": focus,
            "data_json": json.dumps(previsions),
            "horizon": parametres.mois_a_prevoir,
        },
    )


def _periodes(annee):
    dernier = Recette.objects.filter(mois__year=annee).order_by("-mois").values_list("mois", flat=True).first()
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
    periodes = _periodes(annee)
    periode = request.GET.get("periode") or periodes[0][0]
    secteur_id = request.GET.get("secteur") or ""
    chapitre = request.GET.get("chapitre") or ""
    categorie_id = request.GET.get("categorie") or ""
    q = (request.GET.get("q") or "").strip()

    recettes = Recette.objects.select_related("categorie", "secteur", "saisie_par")
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
            "nb_total": Recette.objects.count(),
            "periodes": periodes,
            "periode": periode,
            "secteurs": Secteur.objects.filter(actif=True),
            "chapitres": [(c, LIBELLE_CHAPITRE[c]) for c, _ in CHAPITRES if Categorie.objects.filter(chapitre=c).exists()],
            "secteur_filtre": secteur_id,
            "chapitre_filtre": chapitre,
            "categorie_filtre": categorie_id,
            "q": q,
            "querystring": params.urlencode(),
            "exercice": annee,
        },
    )


def _impact_data(annee):
    """Objectif annuel et réalisé par compte, pour l'encart « Impact sur l'exercice » du formulaire."""
    objectifs = {
        l["categorie_id"]: l["t"]
        for l in ObjectifBudgetaire.objects.filter(mois__year=annee, statut="INSCRIT", secteur__isnull=True)
        .values("categorie_id").annotate(t=Sum("montant_cible"))
    }
    realise = {
        l["categorie_id"]: l["t"]
        for l in Recette.objects.filter(mois__year=annee).values("categorie_id").annotate(t=Sum("montant"))
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
    return {
        "form": form,
        "titre": titre,
        "recette": recette,
        "lecture": lecture,
        "impact_json": json.dumps(_impact_data(annee)),
        "annee": annee,
        "dernieres": Recette.objects.select_related("categorie", "secteur").order_by("-date_saisie")[:3],
        "aujourdhui": date.today().isoformat(),
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
            messages.success(request, f"Recette {recette.reference} enregistrée.")
            notifier_ecarts_significatifs()
            if request.POST.get("action") == "nouveau":
                return redirect("ajouter_recette")
            return redirect("liste_recettes")
    else:
        form = RecetteForm(utilisateur=request.user, initial={"date_imputation": date.today()})
    return render(request, "recettes/formulaire_recette.html",
                  _contexte_formulaire_recette(request, form, "Nouvelle recette"))


@login_required
def detail_recette(request, pk):
    recette = get_object_or_404(Recette.objects.select_related("categorie", "secteur", "saisie_par"), pk=pk)
    form = RecetteForm(instance=recette, utilisateur=request.user)
    return render(request, "recettes/formulaire_recette.html",
                  _contexte_formulaire_recette(request, form, f"Recette {recette.reference}", recette, lecture=True))


@role_requis(*ROLES_GESTION)
def modifier_recette(request, pk):
    recette = get_object_or_404(Recette, pk=pk)
    if request.method == "POST":
        form = RecetteForm(request.POST, request.FILES, instance=recette, utilisateur=request.user)
        if form.is_valid():
            form.save()
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
        recette.delete()
        messages.success(request, "Recette supprimée.")
        return redirect("liste_recettes")
    return render(request, "recettes/confirmer_suppression.html", {"objet": recette})


@login_required
def bordereau(request, pk):
    recette = get_object_or_404(Recette, pk=pk)
    if not recette.piece_jointe:
        raise Http404("Aucune pièce jointe.")
    return FileResponse(recette.piece_jointe.open("rb"), as_attachment=False, filename=recette.piece_jointe.name.split("/")[-1])


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
    else:
        donnees["actif"] = "on"
    form = SecteurForm(donnees, instance=secteur)
    if form.is_valid():
        form.save()
        messages.success(request, "Secteur mis à jour." if "suspendre" not in request.POST else "Régie suspendue.")
    else:
        _erreurs_en_messages(request, form)
    return redirect("gestion_secteurs")


@login_required
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


def _projection_globale(annee):
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
    for (_, m), v in prevision_par_mois().items():
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
    categorie_id = request.GET.get("categorie") or ""
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
    total_cible = sum((e.cible for e in ecarts), Decimal("0"))
    total_realise = sum((e.realise for e in ecarts), Decimal("0"))
    taux = float(total_realise / total_cible * 100) if total_cible else None
    ecart_net = total_realise - total_cible
    alertes = [e for e in ecarts if e.significatif]
    pire = alertes[0] if alertes else None

    previsions = prevision_par_mois()
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

    proj = _projection_globale(annee)
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
            "mois_defaut": date.today().replace(day=1),
            "mois_options": mois_options,
            "categories": categories,
            "chapitres": CHAPITRES,
            "secteurs": Secteur.objects.filter(actif=True),
            "historique_json": json.dumps(hist),
            "recents": ObjectifBudgetaire.objects.select_related("categorie", "fixe_par").order_by("-date_creation")[:3],
            "parametres": ParametrageSysteme.charger(),
        },
    )


@role_requis(*ROLES_GESTION)
@require_POST
def supprimer_objectif(request, pk):
    get_object_or_404(ObjectifBudgetaire, pk=pk).delete()
    messages.success(request, "Objectif supprimé.")
    return redirect("liste_objectifs")


@role_requis(*ROLES_BUDGET)
def comparaison(request):
    try:
        nb_annees = max(2, min(int(request.GET.get("annees", 3)), 10))
    except ValueError:
        nb_annees = 3
    donnees = comparaison_exercices(nb_annees)
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
    secteur_id = request.GET.get("secteur") or ""
    anomalies = Anomalie.objects.select_related("categorie", "secteur", "signale_par", "assigne_a").filter(
        traitee=False, brouillon=False)
    if request.GET.get("archives"):
        anomalies = Anomalie.objects.select_related("categorie", "secteur", "signale_par", "assigne_a").filter(traitee=True)
    if secteur_id:
        anomalies = anomalies.filter(secteur_id=secteur_id)
    liste = list(anomalies)
    brouillons = Anomalie.objects.filter(brouillon=True, signale_par=request.user)
    selection = None
    if request.GET.get("dossier"):
        selection = Anomalie.objects.filter(pk=request.GET["dossier"]).select_related("categorie", "secteur", "assigne_a", "signale_par").first()
    if selection is None and liste:
        selection = liste[0]
    ouvertes = Anomalie.objects.filter(traitee=False, brouillon=False)
    en_retard = [a for a in ouvertes if a.en_retard]
    clotures = Anomalie.objects.filter(traitee=True, date_regularisation__isnull=False)
    delais = [(a.date_regularisation - a.date_signalement).days for a in clotures]
    montant_retard = sum((a.montant for a in en_retard), Decimal("0"))
    return render(
        request,
        "recettes/liste_anomalies.html",
        {
            "anomalies": liste,
            "selection": selection,
            "echanges": selection.echanges.select_related("auteur") if selection else [],
            "secteurs": Secteur.objects.filter(actif=True),
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
        anomalie = get_object_or_404(Anomalie, pk=pk)
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
        initial = {"date_constat": date.today(), "date_echeance": date.today() + timedelta(days=15)}
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
            "nb_en_cours": Anomalie.objects.filter(traitee=False, brouillon=False).count(),
            "prochaine_ref": anomalie.reference if anomalie else f"ANO-{date.today().year}-{(Anomalie.objects.order_by('-pk').values_list('pk', flat=True).first() or 0) + 1:03d}",
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
    else:
        notifier_relance(anomalie, request.user)
        EchangeAnomalie.objects.create(anomalie=anomalie, auteur=request.user, titre="Relance du régisseur",
                                       texte=f"Relance adressée à {anomalie.assigne_a.get_full_name() or anomalie.assigne_a.username}.")
        messages.success(request, "Relance envoyée.")
    return redirect(f"{reverse('liste_anomalies')}?dossier={pk}")


@role_requis(*ROLES_ANOMALIES)
@require_POST
def supprimer_anomalie(request, pk):
    anomalie = get_object_or_404(Anomalie, pk=pk)
    if request.user.profil.role not in ROLES_GESTION and not (anomalie.brouillon and anomalie.signale_par_id == request.user.pk):
        messages.error(request, "Vous ne pouvez supprimer que vos brouillons.")
        return redirect("liste_anomalies")
    anomalie.delete()
    messages.success(request, "Dossier supprimé.")
    return redirect("liste_anomalies")


@login_required
def piece_anomalie(request, pk):
    anomalie = get_object_or_404(Anomalie, pk=pk)
    if not anomalie.piece_jointe:
        raise Http404("Aucune pièce jointe.")
    return FileResponse(anomalie.piece_jointe.open("rb"), filename=anomalie.piece_jointe.name.split("/")[-1])


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
    nb = notifier_ecarts_significatifs()
    messages.success(
        request,
        f"{nb} notification(s) envoyée(s)."
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


def _envoyer_lien_mot_de_passe(request, utilisateur):
    if not utilisateur.email:
        return False
    formulaire = PasswordResetForm({"email": utilisateur.email})
    if formulaire.is_valid():
        formulaire.save(
            request=request,
            subject_template_name="recettes/email/mot_de_passe_sujet.txt",
            email_template_name="recettes/email/mot_de_passe_corps.txt",
            from_email=None,
        )
        return True
    return False


@role_requis(Profil.Role.ADMIN)
@require_POST
def inviter_utilisateur(request):
    form = UtilisateurAdminForm(request.POST)
    if form.is_valid():
        user = form.save()
        envoye = _envoyer_lien_mot_de_passe(request, user)
        messages.success(
            request,
            f"Invitation créée pour {user.email}." + (" Un lien de création de mot de passe a été envoyé." if envoye else ""),
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
    form = UtilisateurAdminForm(donnees, instance=utilisateur)
    if form.is_valid():
        form.save()
        messages.success(request, f"Compte « {utilisateur.email or utilisateur.username} » mis à jour.")
    else:
        _erreurs_en_messages(request, form)
    return redirect("liste_utilisateurs")


@role_requis(Profil.Role.ADMIN)
@require_POST
def basculer_utilisateur(request, pk):
    utilisateur = get_object_or_404(User, pk=pk)
    if utilisateur == request.user:
        messages.error(request, "Vous ne pouvez pas désactiver votre propre compte.")
        return redirect("liste_utilisateurs")
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
    if request.POST.get("decision") == "valider":
        utilisateur.is_active = True
        utilisateur.save(update_fields=["is_active"])
        profil.en_attente = False
        profil.save(update_fields=["en_attente"])
        if utilisateur.email:
            from django.core.mail import send_mail
            from django.conf import settings

            send_mail(
                "[Recettes collectivité] Habilitation validée",
                f"Bonjour {profil.nom_affiche},\n\nVotre demande {profil.reference_demande} a été validée. "
                "Vous pouvez désormais vous connecter avec votre adresse e-mail et votre mot de passe.",
                settings.DEFAULT_FROM_EMAIL, [utilisateur.email], fail_silently=True,
            )
        messages.success(request, f"Habilitation validée pour {profil.nom_affiche}.")
    else:
        nom = profil.nom_affiche
        utilisateur.delete()
        messages.success(request, f"Demande de {nom} refusée et supprimée.")
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


def _construire_rapport(type_doc, format_, annee):
    if format_ == "CSV":
        reponse = exports.export_anomalies_csv() if type_doc == "ANOMALIES" else exports.export_recettes_csv()
        return reponse.content, reponse["Content-Type"], "csv"
    if format_ == "XLSX":
        contenu = generer_rapport_xlsx(type_doc, annee).getvalue()
        return contenu, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    return generer_rapport_pdf(type_doc, annee).getvalue(), "application/pdf", "pdf"


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
        contenu, mime, extension = _construire_rapport(type_doc, format_, annee)
        rapport = RapportGenere.objects.create(
            type_doc=type_doc, format=format_, periode=f"Exercice {annee}", cree_par=request.user, taille=len(contenu),
        )
        if request.POST.get("envoi") == "email":
            _envoyer_rapport(request.user, rapport, contenu, mime, extension)
            messages.success(request, f"Rapport {rapport.reference} transmis à {request.user.email}.")
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
            par_chapitre.append({"code": code, "libelle": libelle.split("— ")[1], "realise": realise,
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
            "par_chapitre": par_chapitre[:4],
            "nb_anomalies": Anomalie.objects.filter(traitee=False, brouillon=False).count(),
            "montant_anomalies": _somme(Anomalie.objects.filter(traitee=False, brouillon=False), "montant"),
            "exports": [(k, v) for k, v in [
                ("recettes", "Recettes (CSV)"), ("objectifs", "Objectifs budgétaires (CSV)"),
                ("ecarts", "Écarts (CSV)"), ("previsions", "Prévisions (CSV)"),
                ("exercices", "Comparaison des exercices (CSV)"), ("secteurs", "Recouvrement par secteur (CSV)"),
                ("anomalies", "Anomalies (CSV)"),
            ]],
        },
    )


def _envoyer_rapport(utilisateur, rapport, contenu, mime, extension):
    from django.conf import settings

    message = EmailMessage(
        subject=f"[Recettes collectivité] {rapport.get_type_doc_display()} — {rapport.reference}",
        body=f"Bonjour,\n\nVeuillez trouver ci-joint le document {rapport.reference} ({rapport.periode}).",
        from_email=settings.DEFAULT_FROM_EMAIL, to=[utilisateur.email],
    )
    message.attach(f"{rapport.reference}.{extension}", contenu, mime)
    message.send(fail_silently=True)


@role_requis(*ROLES_BUDGET)
def telecharger_rapport(request, pk):
    rapport = get_object_or_404(RapportGenere, pk=pk)
    annee = int(rapport.periode.split()[-1]) if rapport.periode.split()[-1].isdigit() else exercice_courant(request)
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
    return generateur()
