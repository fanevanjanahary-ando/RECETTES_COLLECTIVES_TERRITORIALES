from .models import JournalAudit


def adresse_ip(request):
    return request.META.get("REMOTE_ADDR") or None


def journaliser(request, action, objet, detail=""):
    utilisateur = getattr(request, "user", None)
    JournalAudit.objects.create(
        utilisateur=utilisateur if getattr(utilisateur, "is_authenticated", False) else None,
        action=action,
        objet=str(objet)[:120],
        detail=str(detail)[:2000],
        adresse_ip=adresse_ip(request),
    )