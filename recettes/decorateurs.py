from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

def role_requis(*roles_autorises):
    def decorateur(vue):
        @wraps(vue)
        @login_required
        def enveloppe(request, *args, **kwargs):
            profil = getattr(request.user, "profil", None)
            if profil is None or profil.role not in roles_autorises:
                messages.error(request, "Vous n'avez pas les droits nécessaires pour accéder à cette page.")
                return redirect("dashboard")
            return vue(request, *args, **kwargs)
        return enveloppe
    return decorateur
