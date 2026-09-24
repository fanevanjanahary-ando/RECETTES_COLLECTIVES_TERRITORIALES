from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from recettes import views as v

urlpatterns = [
    path('admin/', admin.site.urls),

    path('connexion/', v.ConnexionView.as_view(), name='connexion'),
    path('deconnexion/', v.DeconnexionView.as_view(), name='deconnexion'),
    path('inscription/', v.inscription, name='inscription'),
    path('exercice/', v.changer_exercice, name='changer_exercice'),
    path('mot-de-passe/oubli/', auth_views.PasswordResetView.as_view(
        template_name='recettes/mot_de_passe_oubli.html',
        email_template_name='recettes/email/mot_de_passe_corps.txt',
        subject_template_name='recettes/email/mot_de_passe_sujet.txt',
        success_url=reverse_lazy('password_reset_done')), name='password_reset'),
    path('mot-de-passe/oubli/envoye/', auth_views.PasswordResetDoneView.as_view(
        template_name='recettes/mot_de_passe_oubli.html', extra_context={'envoye': True}), name='password_reset_done'),
    path('mot-de-passe/reinit/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='recettes/mot_de_passe_confirmer.html',
        success_url=reverse_lazy('password_reset_complete')), name='password_reset_confirm'),
    path('mot-de-passe/reinit/termine/', auth_views.PasswordResetCompleteView.as_view(
        template_name='recettes/mot_de_passe_termine.html'), name='password_reset_complete'),

    path('', v.dashboard, name='dashboard'),

    path('recettes/', v.liste_recettes, name='liste_recettes'),
    path('recettes/ajouter/', v.ajouter_recette, name='ajouter_recette'),
    path('recettes/<int:pk>/', v.detail_recette, name='detail_recette'),
    path('recettes/<int:pk>/modifier/', v.modifier_recette, name='modifier_recette'),
    path('recettes/<int:pk>/supprimer/', v.supprimer_recette, name='supprimer_recette'),
    path('recettes/<int:pk>/bordereau/', v.bordereau, name='bordereau'),

    path('categories/', v.liste_categories, name='liste_categories'),
    path('categories/ajouter/', v.ajouter_categorie, name='ajouter_categorie'),
    path('categories/<int:pk>/modifier/', v.modifier_categorie, name='modifier_categorie'),
    path('categories/<int:pk>/basculer/', v.basculer_categorie, name='basculer_categorie'),

    path('secteurs/', v.gestion_secteurs, name='gestion_secteurs'),
    path('secteurs/ajouter/', v.ajouter_secteur, name='ajouter_secteur'),
    path('secteurs/<int:pk>/modifier/', v.modifier_secteur, name='modifier_secteur'),
    path('secteurs/suivi/', v.suivi_secteurs, name='suivi_secteurs'),

    path('objectifs/', v.liste_objectifs, name='liste_objectifs'),
    path('objectifs/ajouter/', v.ajouter_objectif, name='ajouter_objectif'),
    path('objectifs/<int:pk>/supprimer/', v.supprimer_objectif, name='supprimer_objectif'),

    path('comparaison/', v.comparaison, name='comparaison'),

    path('anomalies/', v.liste_anomalies, name='liste_anomalies'),
    path('anomalies/signaler/', v.signaler_anomalie, name='signaler_anomalie'),
    path('anomalies/<int:pk>/modifier/', v.signaler_anomalie, name='modifier_anomalie'),
    path('anomalies/<int:pk>/traiter/', v.traiter_anomalie, name='traiter_anomalie'),
    path('anomalies/<int:pk>/relancer/', v.relancer_anomalie, name='relancer_anomalie'),
    path('anomalies/<int:pk>/supprimer/', v.supprimer_anomalie, name='supprimer_anomalie'),
    path('anomalies/<int:pk>/piece/', v.piece_anomalie, name='piece_anomalie'),

    path('notifications/', v.liste_notifications, name='liste_notifications'),
    path('notifications/lues/', v.marquer_notifications_lues, name='marquer_notifications_lues'),
    path('notifications/declencher/', v.declencher_notifications, name='declencher_notifications'),
    path('notifications/<int:pk>/ouvrir/', v.ouvrir_notification, name='ouvrir_notification'),
    path('notifications/<int:pk>/traiter/', v.traiter_notification, name='traiter_notification'),

    path('utilisateurs/', v.liste_utilisateurs, name='liste_utilisateurs'),
    path('utilisateurs/inviter/', v.inviter_utilisateur, name='inviter_utilisateur'),
    path('utilisateurs/<int:pk>/modifier/', v.modifier_utilisateur, name='modifier_utilisateur'),
    path('utilisateurs/<int:pk>/basculer/', v.basculer_utilisateur, name='basculer_utilisateur'),
    path('utilisateurs/<int:pk>/arbitrer/', v.arbitrer_utilisateur, name='arbitrer_utilisateur'),
    path('utilisateurs/<int:pk>/cle/', v.cle_utilisateur, name='cle_utilisateur'),
    path('parametrage/', v.parametrage, name='parametrage'),

    path('rapports/', v.rapports, name='rapports'),
    path('rapports/<int:pk>/telecharger/', v.telecharger_rapport, name='telecharger_rapport'),
    path('rapport.pdf', v.rapport_pdf, name='rapport_pdf'),
    path('export/<str:jeu>.csv', v.export_csv, name='export_csv'),
]
