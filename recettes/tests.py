from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .alertes import calculer_ecarts, recouvrement_par_secteur
from .models import (
    Anomalie,
    Categorie,
    Notification,
    ObjectifBudgetaire,
    ParametrageSysteme,
    Profil,
    Recette,
    Secteur,
)
from .notifications import notifier_ecarts_significatifs
from .prevision import previsions_par_categorie
from .rapports import comparaison_exercices

class BaseDonnees(TestCase):
    def setUp(self):
        self.taxes = Categorie.objects.create(nom="Taxes", ouverte_aux_agents=True)
        self.subventions = Categorie.objects.create(nom="Subventions", ouverte_aux_agents=False)
        self.nord = Secteur.objects.create(nom="Secteur Nord", code="NORD")
        self.sud = Secteur.objects.create(nom="Secteur Sud", code="SUD")

        self.agent = User.objects.create_user("agent", "agent@example.test", "MotDePasse!2026")
        self.agent.profil.role = Profil.Role.AGENT
        self.agent.profil.save()

        self.responsable = User.objects.create_user("respo", "respo@example.test", "MotDePasse!2026")
        self.responsable.profil.role = Profil.Role.RESPONSABLE
        self.responsable.profil.save()

        self.admin = User.objects.create_user("admin", "admin@example.test", "MotDePasse!2026")
        self.admin.profil.role = Profil.Role.ADMIN
        self.admin.profil.save()

class Point1_RestrictionCategorieAgent(BaseDonnees):

    def test_agent_ne_peut_pas_poster_une_categorie_interdite(self):
        self.client.force_login(self.agent)
        reponse = self.client.post(
            reverse("ajouter_recette"),
            {
                "categorie": self.subventions.pk,
                "secteur": self.nord.pk,
                "date_imputation": "2026-01-05",
                "montant": "1000.00",
                "mode_reglement": "VIREMENT",
                "libelle": "Test",
            },
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Recette.objects.filter(categorie=self.subventions).exists())

    def test_agent_peut_saisir_une_categorie_autorisee(self):
        self.client.force_login(self.agent)
        reponse = self.client.post(
            reverse("ajouter_recette"),
            {
                "categorie": self.taxes.pk,
                "secteur": self.nord.pk,
                "date_imputation": "2026-01-05",
                "montant": "1000.00",
                "mode_reglement": "VIREMENT",
                "libelle": "Test",
            },
        )
        self.assertEqual(reponse.status_code, 302)
        self.assertTrue(Recette.objects.filter(categorie=self.taxes).exists())

    def test_responsable_peut_saisir_toutes_les_categories(self):
        self.client.force_login(self.responsable)
        reponse = self.client.post(
            reverse("ajouter_recette"),
            {
                "categorie": self.subventions.pk,
                "secteur": self.nord.pk,
                "date_imputation": "2026-01-05",
                "montant": "500.00",
                "mode_reglement": "VIREMENT",
                "libelle": "Test",
            },
        )
        self.assertEqual(reponse.status_code, 302)

class Point9_MontantNegatif(BaseDonnees):

    def test_full_clean_refuse_un_montant_negatif(self):
        recette = Recette(categorie=self.taxes, secteur=self.nord, mois=date(2026, 1, 1), montant=Decimal("-500"))
        with self.assertRaises(ValidationError):
            recette.full_clean()

    def test_la_base_refuse_un_montant_negatif_meme_sans_validation(self):
        with self.assertRaises(IntegrityError):
            Recette.objects.create(
                categorie=self.taxes, secteur=self.nord, mois=date(2026, 2, 1), montant=Decimal("-500")
            )

    def test_objectif_negatif_refuse(self):
        objectif = ObjectifBudgetaire(categorie=self.taxes, mois=date(2026, 1, 1), montant_cible=Decimal("-10"))
        with self.assertRaises(ValidationError):
            objectif.full_clean()

class Point10_ComptesDemoAvecEmail(TestCase):

    def test_les_comptes_de_demo_ont_une_adresse(self):
        from django.core.management import call_command

        call_command("generer_donnees_fictives", "--mois", "4", verbosity=0)
        for username in ("admin_demo", "responsable_demo", "elu_demo", "agent_demo"):
            utilisateur = User.objects.get(username=username)
            self.assertTrue(utilisateur.email, f"{username} n'a pas d'adresse e-mail")
            self.assertIn("@", utilisateur.email)

class Point3_NotificationsReelles(BaseDonnees):

    def test_un_ecart_significatif_declenche_un_email_et_une_notification(self):
        Recette.objects.create(categorie=self.taxes, secteur=self.nord, mois=date(2026, 1, 1), montant=Decimal("1000"))
        ObjectifBudgetaire.objects.create(categorie=self.taxes, mois=date(2026, 1, 1), montant_cible=Decimal("2000"))

        envoyees = notifier_ecarts_significatifs()
        self.assertGreater(envoyees, 0)
        self.assertGreater(len(mail.outbox), 0)
        self.assertTrue(Notification.objects.filter(type=Notification.Type.ECART).exists())

    def test_pas_de_doublon_si_on_relance(self):
        Recette.objects.create(categorie=self.taxes, secteur=self.nord, mois=date(2026, 1, 1), montant=Decimal("1000"))
        ObjectifBudgetaire.objects.create(categorie=self.taxes, mois=date(2026, 1, 1), montant_cible=Decimal("2000"))
        premier = notifier_ecarts_significatifs()
        second = notifier_ecarts_significatifs()
        self.assertGreater(premier, 0)
        self.assertEqual(second, 0)

class Point2_SuiviParSecteur(BaseDonnees):

    def test_le_recouvrement_est_ventile_par_secteur(self):
        Recette.objects.create(categorie=self.taxes, secteur=self.nord, mois=date(2026, 1, 1), montant=Decimal("3000"))
        Recette.objects.create(categorie=self.taxes, secteur=self.sud, mois=date(2026, 1, 1), montant=Decimal("1000"))
        suivi = recouvrement_par_secteur()
        parts = {l["secteur"].nom: l["part_pct"] for l in suivi["lignes"]}
        self.assertEqual(parts["Secteur Nord"], 75.0)
        self.assertEqual(parts["Secteur Sud"], 25.0)

    def test_anomalie_rattachee_a_un_secteur(self):
        anomalie = Anomalie.objects.create(
            categorie=self.taxes, secteur=self.nord, mois=date(2026, 1, 1),
            description="Retard", signale_par=self.agent,
        )
        self.assertEqual(anomalie.secteur, self.nord)

class Point4_ModeleConfigurable(BaseDonnees):

    def test_la_page_de_parametrage_est_reservee_a_l_administrateur(self):
        self.client.force_login(self.responsable)
        reponse = self.client.get(reverse("parametrage"))
        self.assertEqual(reponse.status_code, 302)

    def test_l_administrateur_modifie_l_horizon_et_le_seuil(self):
        self.client.force_login(self.admin)
        reponse = self.client.post(
            reverse("parametrage"),
            {
                "mois_a_prevoir": 12,
                "historique_minimum": 4,
                "seuil_alerte_pct": "5.00",
                "jour_echeance_recouvrement": 15,
                "notifications_email_actives": "on",
            },
        )
        self.assertEqual(reponse.status_code, 302)
        parametres = ParametrageSysteme.charger()
        self.assertEqual(parametres.mois_a_prevoir, 12)
        self.assertEqual(parametres.seuil_alerte_pct, Decimal("5.00"))

    def test_le_seuil_configure_change_le_declenchement_des_alertes(self):
        Recette.objects.create(categorie=self.taxes, secteur=self.nord, mois=date(2026, 1, 1), montant=Decimal("1100"))
        ObjectifBudgetaire.objects.create(categorie=self.taxes, mois=date(2026, 1, 1), montant_cible=Decimal("1000"))

        parametres = ParametrageSysteme.charger()
        parametres.seuil_alerte_pct = Decimal("15.00")
        parametres.save()
        self.assertFalse(calculer_ecarts()[0].significatif)

        parametres.seuil_alerte_pct = Decimal("5.00")
        parametres.save()
        self.assertTrue(calculer_ecarts()[0].significatif)

class Point5_ComparaisonExercices(BaseDonnees):

    def test_variation_entre_deux_exercices(self):
        Recette.objects.create(categorie=self.taxes, secteur=self.nord, mois=date(2024, 1, 1), montant=Decimal("1000"))
        Recette.objects.create(categorie=self.taxes, secteur=self.nord, mois=date(2025, 1, 1), montant=Decimal("1200"))
        resultat = comparaison_exercices()
        self.assertEqual(resultat["annees"], [2024, 2025])
        self.assertEqual(resultat["lignes"][0]["variations"][2025], 20.0)

class Point6_GestionDesComptes(BaseDonnees):

    def test_l_administrateur_voit_la_liste_des_comptes(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("liste_utilisateurs")).status_code, 200)

    def test_un_responsable_ne_peut_pas_gerer_les_comptes(self):
        self.client.force_login(self.responsable)
        self.assertEqual(self.client.get(reverse("liste_utilisateurs")).status_code, 302)

    def test_modification_du_role_et_de_l_email(self):
        self.client.force_login(self.admin)
        reponse = self.client.post(
            reverse("modifier_utilisateur", args=[self.agent.pk]),
            {
                "first_name": "Jean", "last_name": "Dupont",
                "email": "jean.dupont@example.test", "is_active": "on",
                "role": Profil.Role.RESPONSABLE, "recevoir_notifications": "on",
            },
        )
        self.assertEqual(reponse.status_code, 302)
        self.agent.refresh_from_db()
        self.assertEqual(self.agent.email, "jean.dupont@example.test")
        self.assertEqual(self.agent.profil.role, Profil.Role.RESPONSABLE)

    def test_desactivation_d_un_compte(self):
        self.client.force_login(self.admin)
        self.client.post(reverse("basculer_utilisateur", args=[self.agent.pk]))
        self.agent.refresh_from_db()
        self.assertFalse(self.agent.is_active)

class Point7_ExportTableur(BaseDonnees):

    def test_export_recettes_csv(self):
        Recette.objects.create(categorie=self.taxes, secteur=self.nord, mois=date(2026, 1, 1), montant=Decimal("1000"))
        self.client.force_login(self.responsable)
        reponse = self.client.get(reverse("export_csv", args=["recettes"]))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn("text/csv", reponse["Content-Type"])
        contenu = reponse.content.decode("utf-8-sig")
        self.assertIn("Secteur", contenu)
        self.assertIn("Secteur Nord", contenu)

    def test_tous_les_exports_repondent(self):
        self.client.force_login(self.responsable)
        for jeu in ("recettes", "objectifs", "ecarts", "previsions", "exercices", "secteurs"):
            with self.subTest(jeu=jeu):
                self.assertEqual(self.client.get(reverse("export_csv", args=[jeu])).status_code, 200)

    def test_export_inconnu_renvoie_404(self):
        self.client.force_login(self.responsable)
        self.assertEqual(self.client.get(reverse("export_csv", args=["nimporte_quoi"])).status_code, 404)

    def test_page_rapports_accessible_au_responsable(self):
        self.client.force_login(self.responsable)
        self.assertEqual(self.client.get(reverse("rapports")).status_code, 200)

class Point8_DistinctionPrevuObjectif(BaseDonnees):

    def test_le_vocabulaire_est_explicite_sur_le_tableau_de_bord(self):
        Recette.objects.create(categorie=self.taxes, secteur=self.nord, mois=date(2026, 1, 1), montant=Decimal("1100"))
        ObjectifBudgetaire.objects.create(categorie=self.taxes, mois=date(2026, 1, 1), montant_cible=Decimal("2000"))
        self.client.force_login(self.responsable)
        contenu = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn("Projection", contenu)
        self.assertIn("Objectif voté", contenu)

    def test_la_page_budget_confronte_les_deux_notions(self):
        self.client.force_login(self.responsable)
        contenu = self.client.get(reverse("liste_objectifs")).content.decode()
        self.assertIn("Objectif voté confronté à la prévision du modèle", contenu)

class InscriptionEmailObligatoire(TestCase):

    def test_inscription_sans_email_refusee(self):
        reponse = self.client.post(
            reverse("inscription"),
            {
                "username": "nouveau", "email": "",
                "password1": "MotDePasse!2026", "password2": "MotDePasse!2026",
                "role": Profil.Role.RESPONSABLE,
            },
        )
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(User.objects.filter(username="nouveau").exists())

class MoteurDePrevision(TestCase):

    def setUp(self):
        self.categorie = Categorie.objects.create(nom="Redevances")
        self.secteur = Secteur.objects.create(nom="Secteur unique")

    def _ajouter_serie(self, valeurs, depart=date(2025, 1, 1)):
        mois = depart
        for valeur in valeurs:
            Recette.objects.create(categorie=self.categorie, secteur=self.secteur, mois=mois, montant=Decimal(str(valeur)))
            mois = date(mois.year + 1, 1, 1) if mois.month == 12 else date(mois.year, mois.month + 1, 1)

    def test_extrapole_correctement_une_tendance_lineaire(self):
        self._ajouter_serie([1000, 1100, 1200, 1300, 1400, 1500])
        resultat = previsions_par_categorie(mois_a_prevoir=3, historique_minimum=3)
        serie = resultat[str(self.categorie.id)]
        self.assertEqual(serie["montants_prevus"], [1600.0, 1700.0, 1800.0])
        self.assertEqual(serie["mois_prevus"], ["2025-07", "2025-08", "2025-09"])

    def test_categorie_sous_le_seuil_est_ignoree(self):
        self._ajouter_serie([1000, 1100])
        resultat = previsions_par_categorie(mois_a_prevoir=3, historique_minimum=3)
        self.assertNotIn(str(self.categorie.id), resultat)

    def test_ne_prevoit_jamais_de_montant_negatif(self):
        self._ajouter_serie([500, 300, 100, 0, 0, 0])
        resultat = previsions_par_categorie(mois_a_prevoir=6, historique_minimum=3)
        serie = resultat[str(self.categorie.id)]
        self.assertTrue(all(v >= 0 for v in serie["montants_prevus"]))

class ConnexionParEmail(BaseDonnees):

    def test_connexion_avec_l_adresse_email(self):
        reponse = self.client.post(
            reverse("connexion"), {"username": "respo@example.test", "password": "MotDePasse!2026"}
        )
        self.assertEqual(reponse.status_code, 302)

    def test_connexion_avec_identifiant_refusee(self):
        reponse = self.client.post(reverse("connexion"), {"username": "respo", "password": "MotDePasse!2026"})
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(reponse.wsgi_request.user.is_authenticated)


class DemandeHabilitation(TestCase):

    def test_inscription_cree_un_compte_inactif_en_attente(self):
        secteur = Secteur.objects.create(nom="Secteur Test", code="TST")
        reponse = self.client.post(
            reverse("inscription"),
            {
                "first_name": "Jean",
                "last_name": "Rakoto",
                "email": "jean.rakoto@collectivite.mg",
                "matricule": "RH-001",
                "role": "AGENT",
                "secteur": secteur.pk,
                "password1": "UnMotDePasse123",
                "password2": "UnMotDePasse123",
                "deontologie": "on",
            },
        )
        self.assertEqual(reponse.status_code, 200)
        utilisateur = User.objects.get(email="jean.rakoto@collectivite.mg")
        self.assertFalse(utilisateur.is_active)
        self.assertTrue(utilisateur.profil.en_attente)

    def test_administrateur_valide_l_habilitation(self):
        admin = User.objects.create_user("admin2", "admin2@example.test", "MotDePasse!2026")
        admin.profil.role = Profil.Role.ADMIN
        admin.profil.save()
        candidat = User.objects.create_user("candidat", "candidat@example.test", "x", is_active=False)
        candidat.profil.en_attente = True
        candidat.profil.save()

        self.client.force_login(admin)
        reponse = self.client.post(reverse("arbitrer_utilisateur", args=[candidat.pk]), {"decision": "valider"})
        self.assertEqual(reponse.status_code, 302)
        candidat.refresh_from_db()
        self.assertTrue(candidat.is_active)
        self.assertFalse(candidat.profil.en_attente)


class NomenclatureCategories(TestCase):

    def test_creation_d_un_compte_avec_code_et_chapitre(self):
        categorie = Categorie.objects.create(nom="Taxe de séjour", code="7362", chapitre="73")
        self.assertEqual(categorie.libelle_complet, "7362 · Taxe de séjour")

    def test_devise_ariary_dans_les_gabarits(self):
        admin = User.objects.create_user("admin3", "admin3@example.test", "MotDePasse!2026")
        admin.profil.role = Profil.Role.ADMIN
        admin.profil.save()
        self.client.force_login(admin)
        contenu = self.client.get(reverse("liste_categories")).content.decode()
        self.assertIn("Ar", contenu)
        self.assertNotIn("€", contenu)


class AnomaliesDeRecouvrement(BaseDonnees):

    def test_signalement_notifie_les_responsables(self):
        self.client.force_login(self.agent)
        reponse = self.client.post(
            reverse("signaler_anomalie"),
            {
                "categorie": self.taxes.pk,
                "secteur": self.nord.pk,
                "motif": "RETARD",
                "montant": "5000",
                "date_constat": "2026-01-05",
                "date_echeance": "2026-01-20",
                "description": "Retard de versement constaté en régie.",
            },
        )
        self.assertEqual(reponse.status_code, 302)
        anomalie = Anomalie.objects.get(secteur=self.nord)
        self.assertFalse(anomalie.brouillon)
        self.assertTrue(Notification.objects.filter(type=Notification.Type.ANOMALIE).exists())

    def test_traitement_reserve_a_la_gestion(self):
        anomalie = Anomalie.objects.create(
            categorie=self.taxes, secteur=self.nord, mois=date(2026, 1, 1),
            montant=Decimal("100"), description="Test", signale_par=self.agent,
        )
        self.client.force_login(self.agent)
        reponse = self.client.post(reverse("traiter_anomalie", args=[anomalie.pk]))
        self.assertEqual(reponse.status_code, 302)
        anomalie.refresh_from_db()
        self.assertFalse(anomalie.traitee)

        self.client.force_login(self.responsable)
        reponse = self.client.post(reverse("traiter_anomalie", args=[anomalie.pk]))
        anomalie.refresh_from_db()
        self.assertTrue(anomalie.traitee)
