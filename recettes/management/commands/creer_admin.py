import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crée un superutilisateur à partir des variables d'environnement DJANGO_SUPERUSER_*, si aucun n'existe déjà avec ce nom."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not username or not password:
            self.stdout.write("DJANGO_SUPERUSER_USERNAME ou DJANGO_SUPERUSER_PASSWORD absent, rien à faire.")
            return

        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"Le compte {username} existe déjà, rien à faire.")
            return

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superutilisateur {username} créé."))