import os

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from recettes.models import Profil


class Command(BaseCommand):
    help = "Crée un superutilisateur à partir des variables d'environnement DJANGO_SUPERUSER_*, si aucun n'existe déjà avec ce nom."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        if not username or not password:
            if not username and not password:
                if not settings.DEBUG:
                    raise CommandError(
                        "Définissez DJANGO_SUPERUSER_USERNAME et DJANGO_SUPERUSER_PASSWORD en production."
                    )
                self.stdout.write("Variables DJANGO_SUPERUSER_* absentes, création ignorée.")
                return
            raise CommandError("DJANGO_SUPERUSER_USERNAME et DJANGO_SUPERUSER_PASSWORD sont requis ensemble.")
        if not email and not settings.DEBUG:
            raise CommandError("DJANGO_SUPERUSER_EMAIL est requis en production.")

        User = get_user_model()
        utilisateur = User.objects.filter(username=username).first()
        if utilisateur:
            if not utilisateur.is_superuser:
                raise CommandError(
                    f"Le compte « {username} » existe déjà sans être superutilisateur. "
                    "Choisissez un autre identifiant ou corrigez ce compte manuellement."
                )
            profil, _ = Profil.objects.get_or_create(user=utilisateur)
            if profil.role != Profil.Role.ADMIN:
                profil.role = Profil.Role.ADMIN
                profil.save(update_fields=["role"])
            if not utilisateur.is_staff:
                utilisateur.is_staff = True
                utilisateur.save(update_fields=["is_staff"])
            self.stdout.write(f"Le superutilisateur {username} existe déjà.")
            return

        utilisateur = User.objects.create_superuser(username=username, email=email, password=password)
        profil, _ = Profil.objects.get_or_create(user=utilisateur)
        profil.role = Profil.Role.ADMIN
        profil.save(update_fields=["role"])
        self.stdout.write(self.style.SUCCESS(f"Superutilisateur {username} créé."))