from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profil

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def creer_profil(sender, instance, created, **kwargs):
    if created:
        Profil.objects.get_or_create(user=instance)
