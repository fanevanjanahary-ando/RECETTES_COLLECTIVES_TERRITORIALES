from django.core.management.base import BaseCommand

from recettes.prevision import historiser_previsions


class Command(BaseCommand):
    help = "Recalcule les prévisions à partir des données actuelles et les enregistre dans l'historique."

    def handle(self, *args, **options):
        nb = historiser_previsions()
        self.stdout.write(self.style.SUCCESS(f"{nb} prévision(s) historisée(s)."))
