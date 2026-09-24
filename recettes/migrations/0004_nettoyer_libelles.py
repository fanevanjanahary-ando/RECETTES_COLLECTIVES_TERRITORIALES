from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recettes", "0003_ariary_extensions"),
    ]

    operations = [
        migrations.AlterField(
            model_name="categorie",
            name="code",
            field=models.CharField(blank=True, max_length=10, verbose_name="Code"),
        ),
        migrations.AlterField(
            model_name="rapportgenere",
            name="type_doc",
            field=models.CharField(
                choices=[
                    ("LIASSE", "Liasse mensuelle"),
                    ("SYNTHESE", "Synthèse analytique"),
                    ("ANOMALIES", "État des anomalies & régies"),
                ],
                max_length=12,
            ),
        ),
    ]