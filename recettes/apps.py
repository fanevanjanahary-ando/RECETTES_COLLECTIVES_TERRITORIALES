from django.apps import AppConfig

class RecettesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'recettes'

    def ready(self):
        import recettes.signals
