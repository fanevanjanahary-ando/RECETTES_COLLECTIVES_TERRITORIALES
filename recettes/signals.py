from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profil

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def creer_profil(sender, instance, created, **kwargs):
    if created:
        role = Profil.Role.ADMIN if instance.is_superuser else Profil.Role.AGENT
        Profil.objects.get_or_create(user=instance, defaults={"role": role})
    elif instance.is_superuser:
        Profil.objects.filter(user=instance).exclude(role=Profil.Role.ADMIN).update(role=Profil.Role.ADMIN)