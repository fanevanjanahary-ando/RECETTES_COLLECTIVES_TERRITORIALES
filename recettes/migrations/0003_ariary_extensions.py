import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('recettes', '0002_secteur_parametrage_notifications'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EchangeAnomalie',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('titre', models.CharField(max_length=120)),
                ('texte', models.TextField(blank=True)),
                ('date', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-date'],
            },
        ),
        migrations.CreateModel(
            name='RapportGenere',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type_doc', models.CharField(choices=[('LIASSE', 'Liasse mensuelle'), ('SYNTHESE', 'Synthèse analytique'), ('ANOMALIES', 'État des anomalies & régies')], max_length=12)),
                ('periode', models.CharField(max_length=60)),
                ('perimetre', models.CharField(default='Tous les secteurs', max_length=100)),
                ('format', models.CharField(choices=[('PDF', 'PDF'), ('XLSX', 'Excel (.xlsx)'), ('CSV', 'CSV')], default='PDF', max_length=5)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('taille', models.PositiveIntegerField(default=0)),
            ],
            options={
                'ordering': ['-date_creation'],
            },
        ),
        migrations.AlterModelOptions(
            name='categorie',
            options={'ordering': ['chapitre', 'code', 'nom']},
        ),
        migrations.RemoveConstraint(
            model_name='objectifbudgetaire',
            name='unique_objectif_categorie_mois',
        ),
        migrations.RemoveConstraint(
            model_name='recette',
            name='unique_categorie_secteur_mois',
        ),
        migrations.AddField(
            model_name='anomalie',
            name='assigne_a',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='anomalies_assignees', to=settings.AUTH_USER_MODEL, verbose_name='Régisseur ou agent assigné'),
        ),
        migrations.AddField(
            model_name='anomalie',
            name='brouillon',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='anomalie',
            name='date_constat',
            field=models.DateField(blank=True, null=True, verbose_name='Date de constatation'),
        ),
        migrations.AddField(
            model_name='anomalie',
            name='date_echeance',
            field=models.DateField(blank=True, null=True, verbose_name='Échéance légale de reversement'),
        ),
        migrations.AddField(
            model_name='anomalie',
            name='date_regularisation',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='anomalie',
            name='montant',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Montant contesté ou non apuré (Ar)'),
        ),
        migrations.AddField(
            model_name='anomalie',
            name='motif',
            field=models.CharField(choices=[('RETARD', 'Retard de versement régie'), ('ARRONDI', "Écart d'arrondi sur rôle"), ('DOUBLE', 'Double imputation'), ('REJET', 'Rejet de bordereau / mandat')], default='RETARD', max_length=10),
        ),
        migrations.AddField(
            model_name='anomalie',
            name='notifier_comptable',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='anomalie',
            name='piece_jointe',
            field=models.FileField(blank=True, null=True, upload_to='anomalies/%Y/%m/', verbose_name='Pièce justificative'),
        ),
        migrations.AddField(
            model_name='categorie',
            name='chapitre',
            field=models.CharField(choices=[('13', "Chapitre 13 — Subventions d'investissement"), ('70', 'Chapitre 70 — Ventes & prestations de services'), ('73', 'Chapitre 73 — Impôts et taxes'), ('74', 'Chapitre 74 — Dotations et subventions'), ('75', 'Chapitre 75 — Autres produits de gestion courante'), ('77', 'Chapitre 77 — Produits exceptionnels')], default='70', max_length=3, verbose_name='Chapitre parent'),
        ),
        migrations.AddField(
            model_name='categorie',
            name='code',
            field=models.CharField(blank=True, max_length=10, verbose_name='Code'),
        ),
        migrations.AddField(
            model_name='categorie',
            name='en_revision',
            field=models.BooleanField(default=False, verbose_name='En révision'),
        ),
        migrations.AddField(
            model_name='categorie',
            name='regime_tva',
            field=models.CharField(choices=[('EXO', 'Exonéré'), ('20', 'Taux normal 20,0 %'), ('10', 'Taux intermédiaire 10,0 %'), ('5.5', 'Taux réduit 5,5 %'), ('HORS', "Hors champ d'application")], default='EXO', max_length=5, verbose_name='Régime TVA'),
        ),
        migrations.AddField(
            model_name='categorie',
            name='secteurs_habilites',
            field=models.ManyToManyField(blank=True, help_text='Vide = tous les secteurs.', related_name='categories_habilitees', to='recettes.secteur'),
        ),
        migrations.AddField(
            model_name='categorie',
            name='type_perception',
            field=models.CharField(choices=[('DIRECTE', 'Perception directe (Régie)'), ('TITRE', 'Émission de titre'), ('ROLE', 'Rôle fiscal exécutoire'), ('VIREMENT', 'Virement bancaire / Trésor')], default='TITRE', max_length=10),
        ),
        migrations.AddField(
            model_name='notification',
            name='date_traitement',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='notification',
            name='lien',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='notification',
            name='traitee',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='objectifbudgetaire',
            name='notes',
            field=models.TextField(blank=True, verbose_name='Note explicative'),
        ),
        migrations.AddField(
            model_name='objectifbudgetaire',
            name='secteur',
            field=models.ForeignKey(blank=True, help_text='Vide = budget consolidé (ensemble des secteurs).', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='objectifs', to='recettes.secteur'),
        ),
        migrations.AddField(
            model_name='objectifbudgetaire',
            name='statut',
            field=models.CharField(choices=[('BROUILLON', 'Brouillon'), ('INSCRIT', 'Inscrit au budget')], default='INSCRIT', max_length=10),
        ),
        migrations.AddField(
            model_name='objectifbudgetaire',
            name='type_budget',
            field=models.CharField(choices=[('BP', 'Budget Primitif (BP)'), ('DM', 'Décision Modificative'), ('REPORT', 'Report de crédits')], default='BP', max_length=10),
        ),
        migrations.AddField(
            model_name='profil',
            name='date_demande',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='profil',
            name='en_attente',
            field=models.BooleanField(default=False, help_text="Demande d'habilitation déposée, en attente de validation par l'administrateur."),
        ),
        migrations.AddField(
            model_name='profil',
            name='matricule',
            field=models.CharField(blank=True, help_text="Matricule interne ou code d'agent.", max_length=40),
        ),
        migrations.AddField(
            model_name='profil',
            name='piece_nomination',
            field=models.FileField(blank=True, null=True, upload_to='habilitations/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='profil',
            name='secteur',
            field=models.ForeignKey(blank=True, help_text='Secteur de rattachement. Vide = transversal (tous les secteurs).', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='agents', to='recettes.secteur'),
        ),
        migrations.AddField(
            model_name='profil',
            name='telephone',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name='recette',
            name='date_imputation',
            field=models.DateField(blank=True, null=True, verbose_name="Date d'imputation"),
        ),
        migrations.AddField(
            model_name='recette',
            name='libelle',
            field=models.CharField(blank=True, max_length=255, verbose_name="Libellé de l'encaissement"),
        ),
        migrations.AddField(
            model_name='recette',
            name='mode_reglement',
            field=models.CharField(choices=[('VIREMENT', 'Virement Trésor Public'), ('TITRE', 'Titre de recette émis'), ('REGIE', 'Régie municipale'), ('PRELEVEMENT', 'Prélèvement'), ('ROLE', 'Rôle fiscal')], default='VIREMENT', max_length=15),
        ),
        migrations.AddField(
            model_name='recette',
            name='piece_jointe',
            field=models.FileField(blank=True, null=True, upload_to='bordereaux/%Y/%m/', verbose_name='Pièce justificative'),
        ),
        migrations.AddField(
            model_name='recette',
            name='reference',
            field=models.CharField(blank=True, max_length=30, verbose_name='N° de bordereau'),
        ),
        migrations.AddField(
            model_name='secteur',
            name='frequence_versement',
            field=models.PositiveSmallIntegerField(choices=[(7, 'Hebdomadaire (J+7)'), (10, 'Décadaire (J+10)'), (15, 'Bi-mensuelle (J+15)'), (30, 'Mensuelle (J+30)')], default=15, verbose_name='Fréquence de versement'),
        ),
        migrations.AddField(
            model_name='secteur',
            name='iban',
            field=models.CharField(blank=True, max_length=40, verbose_name='Compte de dépôt (IBAN / RIB)'),
        ),
        migrations.AddField(
            model_name='secteur',
            name='plafond_encaissement',
            field=models.DecimalField(decimal_places=2, default=Decimal('50000000'), max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name="Plafond légal d'encaissement (Ar)"),
        ),
        migrations.AddField(
            model_name='secteur',
            name='pole',
            field=models.CharField(blank=True, max_length=120, verbose_name='Pôle gestionnaire'),
        ),
        migrations.AddField(
            model_name='secteur',
            name='regisseur',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='secteurs_regisseur', to=settings.AUTH_USER_MODEL, verbose_name='Régisseur titulaire'),
        ),
        migrations.AddField(
            model_name='secteur',
            name='suppleant',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='secteurs_suppleant', to=settings.AUTH_USER_MODEL, verbose_name='Mandataire suppléant'),
        ),
        migrations.AlterField(
            model_name='categorie',
            name='nom',
            field=models.CharField(max_length=100, unique=True, verbose_name='Libellé officiel'),
        ),
        migrations.AlterField(
            model_name='objectifbudgetaire',
            name='montant_cible',
            field=models.DecimalField(decimal_places=2, help_text='Montant inscrit au budget pour ce mois, en Ariary. Ne peut pas être négatif.', max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))], verbose_name='Montant voté au budget'),
        ),
        migrations.AlterField(
            model_name='recette',
            name='montant',
            field=models.DecimalField(decimal_places=2, help_text='Montant perçu, en Ariary (Ar). Une recette ne peut pas être négative.', max_digits=12, validators=[django.core.validators.MinValueValidator(Decimal('0.00'))]),
        ),
        migrations.AddConstraint(
            model_name='objectifbudgetaire',
            constraint=models.UniqueConstraint(condition=models.Q(('secteur__isnull', True)), fields=('categorie', 'mois'), name='unique_objectif_consolide'),
        ),
        migrations.AddConstraint(
            model_name='objectifbudgetaire',
            constraint=models.UniqueConstraint(condition=models.Q(('secteur__isnull', False)), fields=('categorie', 'mois', 'secteur'), name='unique_objectif_secteur'),
        ),
        migrations.AddField(
            model_name='echangeanomalie',
            name='anomalie',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='echanges', to='recettes.anomalie'),
        ),
        migrations.AddField(
            model_name='echangeanomalie',
            name='auteur',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='rapportgenere',
            name='cree_par',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL),
        ),
    ]
