#!/bin/bash

set -e

cd "$(dirname "$0")"

echo "=== Projet Prévision des recettes ==="

if [ ! -d "venv" ]; then
    echo "→ Création de l'environnement virtuel..."
    python3 -m venv venv
fi

source venv/bin/activate
export DJANGO_DEBUG=1

echo "→ Vérification des dépendances..."
pip install -q -r requirements.txt

if [ ! -f "recettes/static/recettes/vendor/tailwind-forms.css" ]; then
    echo "→ Construction des ressources locales (Node requis)..."
    npm install
    npm run assets
fi

echo "→ Migrations..."
python manage.py migrate

HAS_SUPERUSER=$(python manage.py shell -c "from django.contrib.auth.models import User; print(User.objects.filter(is_superuser=True).exists())" 2>/dev/null | tail -n 1)
if [ "$HAS_SUPERUSER" != "True" ]; then
    echo "→ Aucun compte administrateur : création (répondez aux questions ci-dessous)"
    python manage.py createsuperuser
fi

HAS_DATA=$(python manage.py shell -c "from recettes.models import Recette; print(Recette.objects.exists())" 2>/dev/null | tail -n 1)
if [ "$HAS_DATA" != "True" ]; then
    echo "→ Génération des données fictives..."
    python manage.py generer_donnees_fictives
fi

echo ""
echo "=== Serveur lancé : ouvrez http://127.0.0.1:8000/ dans votre navigateur ==="
echo "(Ctrl+C dans ce terminal pour arrêter le serveur)"
echo ""

python manage.py boucle_taches --intervalle 3600 > /dev/null 2>&1 &
TACHES_PID=$!
trap 'kill "$TACHES_PID" 2>/dev/null' EXIT

python manage.py runserver
