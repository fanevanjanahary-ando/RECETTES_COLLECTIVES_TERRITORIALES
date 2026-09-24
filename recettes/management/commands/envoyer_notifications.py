"""
Commande à planifier (cron sous Linux/macOS, Planificateur de tâches sous
Windows) pour envoyer réellement les notifications du point 8.6 du cahier
des charges.

Exemple de planification quotidienne à 7 h :
    0 7 * * * /chemin/venv/bin/python /chemin/manage.py envoyer_notifications

Usage manuel (utile en soutenance, avec le backend e-mail « console » :
les messages s'affichent dans le terminal) :
    python manage.py envoyer_notifications
    python manage.py envoyer_notifications --type ecarts
"""
from django.core.management.base import BaseCommand

from recettes.notifications import notifier_ecarts_significatifs, notifier_echeances_recouvrement


class Command(BaseCommand):
    help = "Envoie les alertes d'écart budgétaire et les rappels d'échéance de recouvrement."

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            choices=["tout", "ecarts", "echeances"],
            default="tout",
            help="Limiter l'envoi à un seul type de notification.",
        )

    def handle(self, *args, **options):
        total = 0
        if options["type"] in ("tout", "ecarts"):
            nb = notifier_ecarts_significatifs()
            total += nb
            self.stdout.write(self.style.SUCCESS(f"{nb} notification(s) d'écart budgétaire envoyée(s)."))
        if options["type"] in ("tout", "echeances"):
            nb = notifier_echeances_recouvrement()
            total += nb
            self.stdout.write(self.style.SUCCESS(f"{nb} rappel(s) d'échéance de recouvrement envoyé(s)."))
        if total == 0:
            self.stdout.write("Rien à envoyer : aucune nouvelle alerte (ou déjà notifiées).")
