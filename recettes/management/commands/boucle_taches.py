import time

from django.core.management.base import BaseCommand

from recettes.notifications import notifier_ecarts_significatifs, notifier_echeances_recouvrement
from recettes.prevision import historiser_previsions


class Command(BaseCommand):
    help = "Exécute périodiquement les notifications et l'historisation des prévisions (usage local)."

    def add_arguments(self, parser):
        parser.add_argument("--intervalle", type=int, default=3600, help="Secondes entre deux exécutions")
        parser.add_argument("--une-fois", action="store_true", help="Exécute une seule fois puis s'arrête")

    def handle(self, *args, **options):
        while True:
            ecarts = notifier_ecarts_significatifs()
            echeances = notifier_echeances_recouvrement()
            previsions = historiser_previsions()
            self.stdout.write(
                f"{ecarts} alerte(s), {echeances} rappel(s), {previsions} prévision(s) historisée(s)."
            )
            if options["une_fois"]:
                return
            time.sleep(options["intervalle"])
