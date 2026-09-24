import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Categorie',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nom', models.CharField(max_length=100, unique=True)),
                ('description', models.CharField(blank=True, max_length=255)),
                ('actif', models.BooleanField(default=True, help_text="Décochez pour archiver sans supprimer l'historique.")),
            ],
            options={
                'ordering': ['nom'],
            },
        ),
        migrations.CreateModel(
            name='Anomalie',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mois', models.DateField()),
                ('description', models.TextField()),
                ('date_signalement', models.DateTimeField(auto_now_add=True)),
                ('traitee', models.BooleanField(default=False)),
                ('signale_par', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('categorie', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='anomalies', to='recettes.categorie')),
            ],
            options={
                'ordering': ['-date_signalement'],
            },
        ),
        migrations.CreateModel(
            name='Profil',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('role', models.CharField(choices=[('ADMIN', 'Administrateur'), ('RESPONSABLE', 'Responsable financier'), ('ELU', 'Élu / décideur'), ('AGENT', 'Agent de recouvrement')], default='RESPONSABLE', max_length=20)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='profil', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ObjectifBudgetaire',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mois', models.DateField(help_text='Premier jour du mois concerné')),
                ('montant_cible', models.DecimalField(decimal_places=2, max_digits=12)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
                ('categorie', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='objectifs', to='recettes.categorie')),
                ('fixe_par', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-mois', 'categorie'],
                'constraints': [models.UniqueConstraint(fields=('categorie', 'mois'), name='unique_objectif_categorie_mois')],
            },
        ),
        migrations.CreateModel(
            name='Recette',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('mois', models.DateField(help_text='Premier jour du mois concerné')),
                ('montant', models.DecimalField(decimal_places=2, max_digits=12)),
                ('date_saisie', models.DateTimeField(auto_now_add=True)),
                ('date_modification', models.DateTimeField(auto_now=True)),
                ('categorie', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='recettes', to='recettes.categorie')),
                ('saisie_par', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='recettes_saisies', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-mois', 'categorie'],
                'constraints': [models.UniqueConstraint(fields=('categorie', 'mois'), name='unique_categorie_mois')],
            },
        ),
    ]
