"""Connexion par adresse e-mail (le nom d'utilisateur reste accepté en secours, ex. superutilisateur)."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOuIdentifiantBackend(ModelBackend):

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()
        identifiant = username or kwargs.get(User.USERNAME_FIELD)
        if not identifiant or password is None:
            return None
        identifiant = identifiant.strip()
        candidats = list(User.objects.filter(email__iexact=identifiant)[:2])
        if not candidats:
            candidats = list(User.objects.filter(username__iexact=identifiant)[:2])
        if len(candidats) != 1:
            return None
        user = candidats[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
