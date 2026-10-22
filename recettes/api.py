from functools import wraps

from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .alertes import calculer_ecarts, execution_budgetaire, recouvrement_par_secteur
from .cloisonnement import recettes_visibles, secteur_impose
from .context_processors import annees_disponibles, exercice_courant
from .models import Profil, Secteur
from .prevision import avertissements_modele, fiabilite_modele, previsions_par_categorie

ROLES_API = (Profil.Role.ADMIN, Profil.Role.RESPONSABLE, Profil.Role.ELU, Profil.Role.AGENT)
ROLES_ANALYSE = (Profil.Role.ADMIN, Profil.Role.RESPONSABLE, Profil.Role.ELU)


def api_role(*roles):
    def decorateur(vue):
        @wraps(vue)
        def enveloppe(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({"erreur": "authentification requise"}, status=401)
            profil = getattr(request.user, "profil", None)
            if profil is None or profil.role not in roles:
                return JsonResponse({"erreur": "droits insuffisants"}, status=403)
            return vue(request, *args, **kwargs)
        return enveloppe
    return decorateur


def _entier(valeur):
    valeur = (valeur or "").strip()
    return int(valeur) if valeur.isdigit() else None


def _annee(request):
    demandee = _entier(request.GET.get("annee"))
    return demandee if demandee in annees_disponibles() else exercice_courant(request)


@require_GET
@api_role(*ROLES_API)
def api_recettes(request):
    annee = _annee(request)
    qs = recettes_visibles(request.user).filter(mois__year=annee).select_related("categorie", "secteur")
    secteur_id = _entier(request.GET.get("secteur"))
    categorie_id = _entier(request.GET.get("categorie"))
    if secteur_id:
        qs = qs.filter(secteur_id=secteur_id)
    if categorie_id:
        qs = qs.filter(categorie_id=categorie_id)
    limite = min(_entier(request.GET.get("limite")) or 100, 500)
    decalage = _entier(request.GET.get("decalage")) or 0
    total = qs.count()
    lignes = [
        {
            "id": r.pk,
            "reference": r.reference,
            "date_imputation": r.date_imputation.isoformat() if r.date_imputation else None,
            "mois": r.mois.strftime("%Y-%m"),
            "categorie": r.categorie.nom,
            "secteur": r.secteur.nom,
            "montant": str(r.montant),
        }
        for r in qs.order_by("-date_imputation", "-id")[decalage:decalage + limite]
    ]
    return JsonResponse({"annee": annee, "total": total, "limite": limite, "decalage": decalage, "resultats": lignes})


@require_GET
@api_role(*ROLES_ANALYSE)
def api_previsions(request):
    previsions = previsions_par_categorie(secteur_id=_entier(request.GET.get("secteur")))
    return JsonResponse({
        "fiabilite_pct": fiabilite_modele(),
        "avertissements": avertissements_modele(previsions),
        "categories": [{"categorie_id": int(cle), **serie} for cle, serie in previsions.items()],
    })


@require_GET
@api_role(*ROLES_ANALYSE)
def api_ecarts(request):
    annee = _annee(request)
    return JsonResponse({
        "annee": annee,
        "execution": {k: (str(v) if k != "taux_pct" else v) for k, v in execution_budgetaire(annee).items()},
        "ecarts": [
            {
                "categorie": e.categorie, "secteur": e.secteur or None, "mois": e.mois.strftime("%Y-%m"),
                "cible": str(e.cible), "realise": str(e.realise), "ecart_pct": e.ecart_pct,
                "significatif": e.significatif,
            }
            for e in calculer_ecarts(annee)
        ],
    })


@require_GET
@api_role(*ROLES_ANALYSE)
def api_secteurs(request):
    annee = _annee(request)
    suivi = recouvrement_par_secteur(annee=annee)
    return JsonResponse({
        "annee": annee,
        "total": str(suivi["total"]),
        "secteurs": [
            {
                "id": l["secteur"].pk, "nom": l["secteur"].nom, "total": str(l["total"]),
                "part_pct": l["part_pct"], "anomalies_ouvertes": l["anomalies_ouvertes"],
            }
            for l in suivi["lignes"]
        ],
    })


@require_GET
@api_role(*ROLES_API)
def api_referentiels(request):
    from .models import Categorie

    impose = secteur_impose(request.user)
    secteurs = Secteur.objects.filter(actif=True, pk=impose) if impose else Secteur.objects.filter(actif=True)
    return JsonResponse({
        "exercices": annees_disponibles(),
        "secteurs": [{"id": s.pk, "nom": s.nom, "code": s.code} for s in secteurs],
        "categories": [{"id": c.pk, "nom": c.nom, "code": c.code, "chapitre": c.chapitre}
                       for c in Categorie.objects.filter(actif=True)],
    })