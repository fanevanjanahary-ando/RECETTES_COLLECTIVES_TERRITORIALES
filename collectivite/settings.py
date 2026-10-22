import os
import sys
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


def _env_bool(nom, defaut):
    return os.environ.get(nom, str(defaut)).strip().lower() in ('1', 'true', 'oui', 'yes')


DEBUG = _env_bool('DJANGO_DEBUG', not os.environ.get('DJANGO_SECRET_KEY'))

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', '')
if not SECRET_KEY:
    if DEBUG or 'test' in sys.argv:
        SECRET_KEY = 'cle-de-developpement-locale-uniquement-' + 'x' * 40
    else:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY doit etre definie quand DEBUG est desactive.')

ALLOWED_HOSTS = ['localhost', '127.0.0.1'] + (['testserver'] if 'test' in sys.argv else []) + [
    h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h.strip()
]
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if o.strip()
]
if not DEBUG and 'test' not in sys.argv:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = _env_bool('DJANGO_SSL_REDIRECT', True)
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'recettes',
]

AUTHENTICATION_BACKENDS = ['recettes.auth_backend.EmailOuIdentifiantBackend']

LOGIN_URL = 'connexion'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'connexion'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'collectivite.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'recettes.context_processors.roles',
                'recettes.context_processors.exercice',
            ],
        },
    },
]

WSGI_APPLICATION = 'collectivite.wsgi.application'

DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{os.environ.get('DJANGO_DB_PATH', BASE_DIR / 'db.sqlite3')}",
        conn_max_age=600,
        ssl_require=bool(os.environ.get('DATABASE_URL')),
    )
}

PASSWORD_RESET_TIMEOUT = 3 * 24 * 60 * 60

if 'test' in sys.argv:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'fr-fr'

TIME_ZONE = 'Indian/Antananarivo'

USE_I18N = True



USE_THOUSAND_SEPARATOR = False

USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}

MEDIA_URL = 'media/'
MEDIA_ROOT = Path(os.environ.get('DJANGO_MEDIA_ROOT', BASE_DIR / 'media'))
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
try:
    EMAIL_PORT = int(os.environ.get('EMAIL_PORT', 587))
    EMAIL_TIMEOUT = int(os.environ.get('EMAIL_TIMEOUT', 10))
except ValueError as erreur:
    raise ImproperlyConfigured('EMAIL_PORT et EMAIL_TIMEOUT doivent être des nombres entiers.') from erreur
if not 1 <= EMAIL_PORT <= 65535 or EMAIL_TIMEOUT <= 0:
    raise ImproperlyConfigured('EMAIL_PORT doit être entre 1 et 65535 et EMAIL_TIMEOUT doit être positif.')
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = _env_bool('EMAIL_USE_TLS', bool(EMAIL_HOST))
EMAIL_USE_SSL = _env_bool('EMAIL_USE_SSL', False)
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise ImproperlyConfigured('EMAIL_USE_TLS et EMAIL_USE_SSL ne peuvent pas être activés simultanément.')

EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND')
if EMAIL_HOST:
    EMAIL_BACKEND = EMAIL_BACKEND or 'django.core.mail.backends.smtp.EmailBackend'
elif not EMAIL_BACKEND and (DEBUG or 'test' in sys.argv):
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
elif not EMAIL_BACKEND:
    raise ImproperlyConfigured(
        'Configurez EMAIL_HOST ou EMAIL_BACKEND pour activer les e-mails hors mode DEBUG.'
    )
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'collectivite@example.com')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_MAX_TENTATIVES = int(os.environ.get('LOGIN_MAX_TENTATIVES', 5))
LOGIN_VERROUILLAGE_SECONDES = int(os.environ.get('LOGIN_VERROUILLAGE_SECONDES', 900))
