from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import User

from .models import (
    Anomalie,
    Categorie,
    EchangeAnomalie,
    FacteurEconomique,
    JournalAudit,
    Notification,
    ObjectifBudgetaire,
    ParametrageSysteme,
    Profil,
    PrevisionHistorisee,
    RapportGenere,
    Recette,
    Secteur,
)


admin.site.unregister(User)


@admin.register(User)
class UtilisateurAdmin(DjangoUserAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Profil)
class ProfilAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "secteur", "en_attente", "recevoir_notifications")
    list_filter = ("role", "en_attente", "recevoir_notifications")


@admin.register(ParametrageSysteme)
class ParametrageSystemeAdmin(admin.ModelAdmin):
    list_display = ("mois_a_prevoir", "seuil_alerte_pct", "notifications_email_actives", "date_modification")

    def has_add_permission(self, request):
        return not ParametrageSysteme.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Secteur)
class SecteurAdmin(admin.ModelAdmin):
    list_display = ("nom", "code", "pole", "regisseur", "actif")
    list_filter = ("actif",)


@admin.register(Categorie)
class CategorieAdmin(admin.ModelAdmin):
    list_display = ("code", "nom", "chapitre", "actif", "ouverte_aux_agents")
    list_filter = ("chapitre", "actif", "ouverte_aux_agents")


@admin.register(Recette)
class RecetteAdmin(admin.ModelAdmin):
    list_display = ("reference", "categorie", "secteur", "date_imputation", "montant", "saisie_par")
    list_filter = ("categorie", "secteur")
    ordering = ("-date_imputation",)


@admin.register(ObjectifBudgetaire)
class ObjectifBudgetaireAdmin(admin.ModelAdmin):
    list_display = ("categorie", "secteur", "mois", "montant_cible", "statut", "fixe_par")
    list_filter = ("categorie", "statut")


@admin.register(Anomalie)
class AnomalieAdmin(admin.ModelAdmin):
    list_display = ("categorie", "secteur", "motif", "montant", "traitee", "brouillon", "date_signalement")
    list_filter = ("traitee", "brouillon", "motif", "secteur")


admin.site.register(EchangeAnomalie)
admin.site.register(RapportGenere)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("sujet", "destinataire", "type", "lue", "traitee", "envoyee_par_email", "date_creation")
    list_filter = ("type", "lue", "traitee", "envoyee_par_email")


@admin.register(JournalAudit)
class JournalAuditAdmin(admin.ModelAdmin):
    list_display = ("date", "utilisateur", "action", "objet", "adresse_ip")
    list_filter = ("action",)
    search_fields = ("objet", "detail", "utilisateur__username")
    readonly_fields = ("date", "utilisateur", "action", "objet", "detail", "adresse_ip")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FacteurEconomique)
class FacteurEconomiqueAdmin(admin.ModelAdmin):
    list_display = ("libelle", "categorie", "mois_debut", "mois_fin", "effet_pct")


@admin.register(PrevisionHistorisee)
class PrevisionHistoriseeAdmin(admin.ModelAdmin):
    list_display = ("date_calcul", "categorie", "mois", "montant_prevu", "borne_basse", "borne_haute")
    list_filter = ("date_calcul", "categorie")
