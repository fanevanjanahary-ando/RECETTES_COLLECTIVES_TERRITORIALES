from datetime import date

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction

from .alertes import alertes_significatives
from .formats import ar
from .models import Notification, ParametrageSysteme, Profil, Recette, Secteur

def _destinataires(roles) -> list:
    profils = (
        Profil.objects.filter(role__in=roles, recevoir_notifications=True, user__is_active=True)
        .select_related("user")
    )
    return [p.user for p in profils]

def _creer_et_envoyer(utilisateur, type_notif, sujet, message, cle_unicite="", lien="") -> bool:
    parametres = ParametrageSysteme.charger()
    try:
        with transaction.atomic():
            notification = Notification.objects.create(
                destinataire=utilisateur,
                type=type_notif,
                sujet=sujet,
                message=message,
                cle_unicite=cle_unicite,
                lien=lien,
            )
    except IntegrityError:
        return False

    if parametres.notifications_email_actives and utilisateur.email:
        send_mail(
            subject=f"[Recettes collectivité] {sujet}",
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[utilisateur.email],
            fail_silently=True,
        )
        notification.envoyee_par_email = True
        notification.save(update_fields=["envoyee_par_email"])
    return True

def notifier_ecarts_significatifs() -> int:
    destinataires = _destinataires([Profil.Role.ADMIN, Profil.Role.RESPONSABLE, Profil.Role.ELU])
    envoyees = 0
    for ecart in alertes_significatives():
        cle = f"ECART-{ecart.categorie_id}-{ecart.mois:%Y-%m}"
        sujet = f"Écart budgétaire sur « {ecart.categorie} » ({ecart.mois:%m/%Y})"
        message = (
            f"Un écart de {ecart.ecart_pct:+.1f} % a été constaté "
            f"(seuil d'alerte configuré : {ecart.seuil_pct:.1f} %).\n\n"
            f"Catégorie : {ecart.categorie}\n"
            f"Mois      : {ecart.mois:%m/%Y}\n"
            f"Objectif voté  : {ar(ecart.cible)}\n"
            f"Réalisé        : {ar(ecart.realise)}\n"
            f"Nature         : {ecart.sens}\n\n"
            "Consultez le détail sur la page « Budget / écarts » de l'application."
        )
        for utilisateur in destinataires:
            if _creer_et_envoyer(utilisateur, Notification.Type.ECART, sujet, message, cle, "liste_objectifs"):
                envoyees += 1
    return envoyees

def _mois_precedent(d: date) -> date:
    return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)

def notifier_echeances_recouvrement(aujourdhui: date | None = None) -> int:
    aujourdhui = aujourdhui or date.today()
    parametres = ParametrageSysteme.charger()
    if aujourdhui.day < parametres.jour_echeance_recouvrement:
        return 0

    mois_attendu = _mois_precedent(date(aujourdhui.year, aujourdhui.month, 1))
    deja_saisi = set(
        Recette.objects.filter(mois=mois_attendu).values_list("secteur_id", "categorie_id")
    )
    from .models import Categorie

    manquants = []
    for secteur in Secteur.objects.filter(actif=True):
        for categorie in Categorie.objects.filter(actif=True):
            if (secteur.id, categorie.id) not in deja_saisi:
                manquants.append(f"  - {secteur.nom} / {categorie.nom}")

    if not manquants:
        return 0

    cle = f"ECHEANCE-{mois_attendu:%Y-%m}"
    sujet = f"Saisie des recettes de {mois_attendu:%m/%Y} incomplète"
    message = (
        f"L'échéance de saisie (le {parametres.jour_echeance_recouvrement} du mois) est dépassée.\n"
        f"{len(manquants)} couple(s) secteur / catégorie n'ont aucune recette enregistrée "
        f"pour {mois_attendu:%m/%Y} :\n\n" + "\n".join(manquants[:40])
    )
    if len(manquants) > 40:
        message += f"\n  ... et {len(manquants) - 40} autres."

    envoyees = 0
    for utilisateur in _destinataires([Profil.Role.AGENT, Profil.Role.RESPONSABLE, Profil.Role.ADMIN]):
        if _creer_et_envoyer(utilisateur, Notification.Type.ECHEANCE, sujet, message, cle, "liste_recettes"):
            envoyees += 1
    return envoyees

def notifier_anomalie(anomalie) -> int:
    cle = f"ANOMALIE-{anomalie.pk}"
    sujet = f"Anomalie signalée — {anomalie.categorie} / {anomalie.secteur} ({anomalie.mois:%m/%Y})"
    message = (
        f"Signalée par : {anomalie.signale_par or 'utilisateur inconnu'}\n"
        f"Catégorie    : {anomalie.categorie}\n"
        f"Secteur      : {anomalie.secteur}\n"
        f"Mois         : {anomalie.mois:%m/%Y}\n"
        f"Motif        : {anomalie.get_motif_display()}\n"
        f"Montant      : {ar(anomalie.montant)}\n\n"
        f"Description :\n{anomalie.description}"
    )
    envoyees = 0
    for utilisateur in _destinataires([Profil.Role.RESPONSABLE, Profil.Role.ADMIN]):
        if _creer_et_envoyer(utilisateur, Notification.Type.ANOMALIE, sujet, message, cle, f"anomalies/?dossier={anomalie.pk}"):
            envoyees += 1
    return envoyees

def notifications_non_lues(utilisateur):
    if not getattr(utilisateur, "is_authenticated", False):
        return Notification.objects.none()
    return Notification.objects.filter(destinataire=utilisateur, lue=False)


def notifier_habilitation(profil) -> int:
    """Prévient les administrateurs qu'une demande d'habilitation attend leur arbitrage."""
    utilisateur = profil.user
    cle = f"HABILITATION-{utilisateur.pk}"
    sujet = f"Demande d'habilitation — {profil.nom_affiche}"
    message = (
        f"Dossier {profil.reference_demande}\n"
        f"Agent : {profil.nom_affiche} ({utilisateur.email})\n"
        f"Fonction sollicitée : {profil.get_role_display()}\n"
        f"Secteur : {profil.secteur or 'Transversal'}\n\n"
        "Rendez-vous sur « Utilisateurs & Droits d'accès » pour arbitrer la demande."
    )
    envoyees = 0
    for admin in _destinataires([Profil.Role.ADMIN]):
        if _creer_et_envoyer(admin, Notification.Type.SYSTEME, sujet, message, cle, "liste_utilisateurs"):
            envoyees += 1
    return envoyees


def notifier_relance(anomalie, auteur) -> int:
    """Relance le régisseur / agent assigné à une anomalie."""
    cible = anomalie.assigne_a
    if cible is None:
        return 0
    cle = f"RELANCE-{anomalie.pk}-{date.today():%Y%m%d}-{auteur.pk}"
    sujet = f"Relance — anomalie {anomalie.reference}"
    message = (
        f"{auteur.get_full_name() or auteur.username} vous relance sur le dossier {anomalie.reference}.\n"
        f"{anomalie.intitule} — {ar(anomalie.montant)}\n"
        f"Échéance : {anomalie.date_echeance:%d/%m/%Y}" if anomalie.date_echeance else
        f"{auteur.get_full_name() or auteur.username} vous relance sur le dossier {anomalie.reference}."
    )
    return int(_creer_et_envoyer(cible, Notification.Type.ANOMALIE, sujet, message, cle, f"anomalies/?dossier={anomalie.pk}"))
