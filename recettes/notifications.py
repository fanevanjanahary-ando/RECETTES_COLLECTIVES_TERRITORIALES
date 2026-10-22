from datetime import date
import logging
import smtplib

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .alertes import alertes_significatives
from .formats import ar
from .models import Notification, ParametrageSysteme, Profil, Recette, Secteur

logger = logging.getLogger(__name__)


def _destinataires(roles) -> list:
    profils = (
        Profil.objects.filter(role__in=roles, recevoir_notifications=True, user__is_active=True)
        .select_related("user")
    )
    return [p.user for p in profils]

def _creer_et_envoyer(utilisateur, type_notif, sujet, message, cle_unicite="", lien="") -> bool:
    parametres = ParametrageSysteme.charger()
    defaults = {
        "type": type_notif,
        "sujet": sujet,
        "message": message,
        "lien": lien,
    }
    if cle_unicite:
        notification, creee = Notification.objects.get_or_create(
            destinataire=utilisateur,
            cle_unicite=cle_unicite,
            defaults=defaults,
        )
    else:
        notification = Notification.objects.create(
            destinataire=utilisateur, cle_unicite="", **defaults
        )
        creee = True

    if parametres.notifications_email_actives and utilisateur.email and not notification.envoyee_par_email:
        try:
            envoyes = send_mail(
                subject=f"[Recettes collectivité] {sujet}",
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[utilisateur.email],
                fail_silently=False,
            )
        except (OSError, smtplib.SMTPException):
            logger.exception(
                "Échec de l'envoi par e-mail de la notification %s à %s",
                notification.pk,
                utilisateur.email,
            )
            return creee
        if not envoyes:
            logger.error(
                "Le backend n'a pas envoyé l'e-mail de la notification %s à %s",
                notification.pk,
                utilisateur.email,
            )
        else:
            notification.envoyee_par_email = True
            notification.save(update_fields=["envoyee_par_email"])
    return creee

def notifier_ecarts_significatifs() -> int:
    destinataires = _destinataires([Profil.Role.ADMIN, Profil.Role.RESPONSABLE, Profil.Role.ELU])
    envoyees = 0
    for ecart in alertes_significatives():
        niveau = int(abs(ecart.ecart_pct) // 10) * 10
        cle = f"ECART-{ecart.objectif_id}-{ecart.categorie_id}-{ecart.mois:%Y-%m}-{niveau}"
        lieu = f" - {ecart.secteur}" if ecart.secteur else " - consolidé"
        sujet = f"Écart budgétaire sur « {ecart.categorie} »{lieu} ({ecart.mois:%m/%Y})"
        message = (
            f"Un écart de {ecart.ecart_pct:+.1f} % a été constaté "
            f"(seuil d'alerte configuré : {ecart.seuil_pct:.1f} %).\n\n"
            f"Catégorie : {ecart.categorie}\n"
            f"Secteur   : {ecart.secteur or 'Consolidé (tous secteurs)'}\n"
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
    aujourdhui = aujourdhui or timezone.localdate()
    parametres = ParametrageSysteme.charger()
    if aujourdhui.day < parametres.jour_echeance_recouvrement:
        return 0

    mois_attendu = _mois_precedent(date(aujourdhui.year, aujourdhui.month, 1))
    deja_saisi = set(
        Recette.objects.filter(mois=mois_attendu).values_list("secteur_id", "categorie_id")
    )
    from .models import Categorie

    manquants = []
    manquants_par_secteur = {}
    categories = Categorie.objects.filter(actif=True).prefetch_related("secteurs_habilites")
    for secteur in Secteur.objects.filter(actif=True):
        for categorie in categories:
            habilites = {s.id for s in categorie.secteurs_habilites.all()}
            if habilites and secteur.id not in habilites:
                continue
            if (secteur.id, categorie.id) not in deja_saisi:
                manquants_par_secteur.setdefault(secteur.id, []).append(f"  - {secteur.nom} / {categorie.nom}")

    if not manquants_par_secteur:
        return 0

    cle = f"ECHEANCE-{mois_attendu:%Y-%m}"
    sujet = f"Saisie des recettes de {mois_attendu:%m/%Y} incomplète"
    envoyees = 0
    profils = Profil.objects.filter(
        role__in=[Profil.Role.AGENT, Profil.Role.RESPONSABLE, Profil.Role.ADMIN],
        recevoir_notifications=True, user__is_active=True,
    ).select_related("user")
    for profil in profils:
        if profil.role == Profil.Role.AGENT:
            manquants = manquants_par_secteur.get(profil.secteur_id, []) if profil.secteur_id else []
        else:
            manquants = [ligne for lignes in manquants_par_secteur.values() for ligne in lignes]
        if not manquants:
            continue
        message = (
            f"L'échéance de saisie (le {parametres.jour_echeance_recouvrement} du mois) est dépassée.\n"
            f"{len(manquants)} couple(s) secteur / catégorie n'ont aucune recette enregistrée "
            f"pour {mois_attendu:%m/%Y} :\n\n" + "\n".join(manquants[:40])
        )
        if len(manquants) > 40:
            message += f"\n  ... et {len(manquants) - 40} autres."
        if _creer_et_envoyer(profil.user, Notification.Type.ECHEANCE, sujet, message, cle, "liste_recettes"):
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
    roles = [Profil.Role.ADMIN]
    if anomalie.notifier_comptable:
        roles.append(Profil.Role.RESPONSABLE)
    destinataires = _destinataires(roles)
    if anomalie.assigne_a_id and anomalie.assigne_a.is_active and anomalie.assigne_a not in destinataires:
        destinataires.append(anomalie.assigne_a)
    envoyees = 0
    for utilisateur in destinataires:
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
    cle = f"RELANCE-{anomalie.pk}-{timezone.localdate():%Y%m%d}-{auteur.pk}"
    sujet = f"Relance — anomalie {anomalie.reference}"
    message = (
        f"{auteur.get_full_name() or auteur.username} vous relance sur le dossier {anomalie.reference}.\n"
        f"{anomalie.intitule} — {ar(anomalie.montant)}\n"
        f"Échéance : {anomalie.date_echeance:%d/%m/%Y}" if anomalie.date_echeance else
        f"{auteur.get_full_name() or auteur.username} vous relance sur le dossier {anomalie.reference}."
    )
    return int(_creer_et_envoyer(cible, Notification.Type.ANOMALIE, sujet, message, cle, f"anomalies/?dossier={anomalie.pk}"))
