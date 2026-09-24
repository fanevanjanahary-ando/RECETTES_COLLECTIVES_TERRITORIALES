from datetime import date

from django.db.models.functions import ExtractYear

from .models import Notification, Profil, Recette


def roles(request):
    utilisateur = getattr(request, "user", None)
    profil = getattr(utilisateur, "profil", None)
    role = profil.role if profil else None
    non_lues = 0
    if getattr(utilisateur, "is_authenticated", False):
        non_lues = Notification.objects.filter(destinataire=utilisateur, lue=False).count()
    return {
        "peut_saisir": role in (Profil.Role.ADMIN, Profil.Role.RESPONSABLE, Profil.Role.AGENT),
        "peut_gerer": role in (Profil.Role.ADMIN, Profil.Role.RESPONSABLE),
        "peut_administrer": role == Profil.Role.ADMIN,
        "peut_voir_anomalies": role in (Profil.Role.ADMIN, Profil.Role.RESPONSABLE, Profil.Role.AGENT),
        "peut_voir_budget": role in (Profil.Role.ADMIN, Profil.Role.RESPONSABLE, Profil.Role.ELU),
        "peut_voir_rapports": role in (Profil.Role.ADMIN, Profil.Role.RESPONSABLE, Profil.Role.ELU),
        "notifications_non_lues": non_lues,
        "profil_courant": profil,
    }


def annees_disponibles():
    annees = sorted(
        {a for a in Recette.objects.annotate(a=ExtractYear("mois")).values_list("a", flat=True).distinct()},
        reverse=True,
    )
    return annees or [date.today().year]


def exercice_courant(request):
    """Exercice (année) de travail : choisi à la connexion ou dans l'en-tête, sinon le plus récent."""
    annees = annees_disponibles()
    try:
        choisi = int(request.session.get("exercice", 0))
    except (TypeError, ValueError):
        choisi = 0
    return choisi if choisi in annees else annees[0]


def exercice(request):
    if not getattr(getattr(request, "user", None), "is_authenticated", False):
        return {}
    dernier = Recette.objects.order_by("-date_saisie").values_list("date_saisie", flat=True).first()
    return {
        "exercice_courant": exercice_courant(request),
        "exercices_disponibles": annees_disponibles(),
        "derniere_saisie": dernier,
    }
