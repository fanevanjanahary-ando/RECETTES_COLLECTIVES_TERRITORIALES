"""
Migration correspondant aux corrections apportées après la première
recette de tests :

- `Secteur` : le suivi du recouvrement par secteur (7.4) n'était structuré
  nulle part. Les recettes et les anomalies existantes sont rattachées à un
  secteur par défaut, créé à la volée, pour ne rien perdre.
- `ParametrageSysteme` : l'horizon de prévision et le seuil d'alerte étaient
  des constantes dans le code, non modifiables par l'administrateur (7.1).
- `Notification` : aucune notification n'existait réellement (8.6).
- `Categorie.ouverte_aux_agents` : les agents pouvaient saisir n'importe
  quelle catégorie, y compris les subventions, contrairement au 7.4.
- Contraintes de positivité sur `Recette.montant` et
  `ObjectifBudgetaire.montant_cible` : un montant négatif passait sans
  aucune erreur, y compris via `full_clean()`.
"""
import django.core.validators
import django.db.models.deletion
from decimal import Decimal

from django.conf import settings
from django.db import migrations, models

SECTEUR_PAR_DEFAUT = "Ensemble de la collectivité"


def creer_secteur_par_defaut(apps, schema_editor):
    """
    Ne crée le secteur « fourre-tout » que s'il y a effectivement des données
    antérieures à rattacher. Sur une installation neuve, ce secteur technique
    n'a pas lieu d'exister : il apparaîtrait à 0 € dans le suivi par secteur
    et déclencherait de faux rappels d'échéance.
    """
    Recette = apps.get_model("recettes", "Recette")
    Anomalie = apps.get_model("recettes", "Anomalie")
    if not Recette.objects.exists() and not Anomalie.objects.exists():
        return

    Secteur = apps.get_model("recettes", "Secteur")
    Secteur.objects.get_or_create(
        nom=SECTEUR_PAR_DEFAUT,
        defaults={
            "code": "GLOBAL",
            "description": "Secteur créé automatiquement pour rattacher les données antérieures au découpage sectoriel.",
        },
    )


def rattacher_donnees_existantes(apps, schema_editor):
    Secteur = apps.get_model("recettes", "Secteur")
    secteur = Secteur.objects.filter(nom=SECTEUR_PAR_DEFAUT).first()
    if secteur is None:
        return

    Recette = apps.get_model("recettes", "Recette")
    Anomalie = apps.get_model("recettes", "Anomalie")
    Recette.objects.filter(secteur__isnull=True).update(secteur=secteur)
    Anomalie.objects.filter(secteur__isnull=True).update(secteur=secteur)


def corriger_montants_negatifs(apps, schema_editor):
    """
    Les contraintes de positivité échoueraient si des lignes négatives
    existaient déjà en base (c'était possible avant cette correction).
    On les ramène à zéro plutôt que de les supprimer, pour garder la trace
    de la ligne et permettre une correction manuelle.
    """
    Recette = apps.get_model("recettes", "Recette")
    ObjectifBudgetaire = apps.get_model("recettes", "ObjectifBudgetaire")
    Recette.objects.filter(montant__lt=0).update(montant=Decimal("0.00"))
    ObjectifBudgetaire.objects.filter(montant_cible__lt=0).update(montant_cible=Decimal("0.00"))


def inverse_neutre(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("recettes", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Secteur",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nom", models.CharField(max_length=100, unique=True)),
                ("code", models.CharField(blank=True, help_text="Code court affiché dans les tableaux (ex. : NORD).", max_length=10)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("actif", models.BooleanField(default=True, help_text="Décochez pour archiver sans supprimer l'historique.")),
            ],
            options={
                "verbose_name": "Secteur de recouvrement",
                "verbose_name_plural": "Secteurs de recouvrement",
                "ordering": ["nom"],
            },
        ),
        migrations.CreateModel(
            name="ParametrageSysteme",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mois_a_prevoir", models.PositiveSmallIntegerField(default=6, help_text="Nombre de mois prévus au-delà du dernier mois connu (1 à 36).", validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(36)], verbose_name="Horizon de prévision (mois)")),
                ("historique_minimum", models.PositiveSmallIntegerField(default=3, help_text="En dessous de ce nombre de points, aucune prévision n'est calculée pour la catégorie.", validators=[django.core.validators.MinValueValidator(2), django.core.validators.MaxValueValidator(60)], verbose_name="Historique minimum (mois)")),
                ("seuil_alerte_pct", models.DecimalField(decimal_places=2, default=Decimal("15.00"), help_text="Un écart entre réalisé et objectif supérieur ou égal à ce pourcentage déclenche une alerte.", max_digits=5, validators=[django.core.validators.MinValueValidator(Decimal("0.01")), django.core.validators.MaxValueValidator(Decimal("100.00"))], verbose_name="Seuil d'alerte d'écart (%)")),
                ("jour_echeance_recouvrement", models.PositiveSmallIntegerField(default=10, help_text="Jour du mois avant lequel les recettes du mois précédent doivent être saisies.", validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(28)], verbose_name="Jour d'échéance de saisie")),
                ("notifications_email_actives", models.BooleanField(default=True, help_text="Si décoché, les notifications restent visibles dans l'application mais aucun e-mail n'est envoyé.", verbose_name="Envoi réel des e-mails")),
                ("date_modification", models.DateTimeField(auto_now=True)),
                ("modifie_par", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Paramétrage du système",
                "verbose_name_plural": "Paramétrage du système",
            },
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("type", models.CharField(choices=[("ECART", "Écart budgétaire"), ("ECHEANCE", "Échéance de recouvrement"), ("ANOMALIE", "Anomalie signalée"), ("SYSTEME", "Information système")], default="SYSTEME", max_length=20)),
                ("sujet", models.CharField(max_length=200)),
                ("message", models.TextField()),
                ("cle_unicite", models.CharField(blank=True, help_text="Empêche d'envoyer deux fois la même alerte (ex. : ECART-3-2026-04).", max_length=200)),
                ("lue", models.BooleanField(default=False)),
                ("envoyee_par_email", models.BooleanField(default=False)),
                ("date_creation", models.DateTimeField(auto_now_add=True)),
                ("destinataire", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-date_creation"]},
        ),
        migrations.AddConstraint(
            model_name="notification",
            constraint=models.UniqueConstraint(
                condition=models.Q(("cle_unicite", ""), _negated=True),
                fields=("destinataire", "cle_unicite"),
                name="unique_notification_par_destinataire",
            ),
        ),

        migrations.AddField(
            model_name="profil",
            name="recevoir_notifications",
            field=models.BooleanField(default=True, help_text="Décochez pour ne plus recevoir les e-mails d'alerte et de rappel."),
        ),
        migrations.AddField(
            model_name="categorie",
            name="ouverte_aux_agents",
            field=models.BooleanField(default=False, help_text="Le cahier des charges (7.4) limite les agents à la collecte des taxes et des redevances. Cochez uniquement pour les catégories que les agents ont le droit de saisir.", verbose_name="Saisissable par les agents de recouvrement"),
        ),

        migrations.RunPython(creer_secteur_par_defaut, inverse_neutre),
        migrations.AddField(
            model_name="recette",
            name="secteur",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="recettes", to="recettes.secteur"),
        ),
        migrations.AddField(
            model_name="anomalie",
            name="secteur",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="anomalies", to="recettes.secteur"),
        ),
        migrations.RunPython(rattacher_donnees_existantes, inverse_neutre),
        migrations.AlterField(
            model_name="recette",
            name="secteur",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="recettes", to="recettes.secteur"),
        ),
        migrations.AlterField(
            model_name="anomalie",
            name="secteur",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="anomalies", to="recettes.secteur"),
        ),

        migrations.RunPython(corriger_montants_negatifs, inverse_neutre),
        migrations.AlterField(
            model_name="recette",
            name="montant",
            field=models.DecimalField(decimal_places=2, help_text="Montant perçu, en euros. Une recette ne peut pas être négative.", max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal("0.00"))]),
        ),
        migrations.AlterField(
            model_name="objectifbudgetaire",
            name="montant_cible",
            field=models.DecimalField(decimal_places=2, help_text="Montant inscrit au budget pour ce mois. Ne peut pas être négatif.", max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal("0.00"))], verbose_name="Montant voté au budget"),
        ),
        migrations.AddConstraint(
            model_name="recette",
            constraint=models.CheckConstraint(condition=models.Q(("montant__gte", 0)), name="recette_montant_positif"),
        ),
        migrations.AddConstraint(
            model_name="objectifbudgetaire",
            constraint=models.CheckConstraint(condition=models.Q(("montant_cible__gte", 0)), name="objectif_montant_positif"),
        ),

        migrations.RemoveConstraint(model_name="recette", name="unique_categorie_mois"),
        migrations.AlterModelOptions(
            name="recette",
            options={"ordering": ["-mois", "categorie", "secteur"]},
        ),
        migrations.AddConstraint(
            model_name="recette",
            constraint=models.UniqueConstraint(fields=("categorie", "secteur", "mois"), name="unique_categorie_secteur_mois"),
        ),
    ]
