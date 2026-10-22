from django.db.models import Q

from .models import Anomalie, Profil, Recette


def secteur_impose(utilisateur):
    profil = getattr(utilisateur, "profil", None)
    if profil and profil.role == Profil.Role.AGENT:
        return profil.secteur_id or 0
    return None


def recettes_visibles(utilisateur):
    qs = Recette.objects.all()
    secteur_id = secteur_impose(utilisateur)
    return qs.filter(secteur_id=secteur_id) if secteur_id is not None else qs


def anomalies_visibles(utilisateur):
    qs = Anomalie.objects.filter(Q(brouillon=False) | Q(signale_par=utilisateur))
    secteur_id = secteur_impose(utilisateur)
    return qs.filter(secteur_id=secteur_id) if secteur_id is not None else qs