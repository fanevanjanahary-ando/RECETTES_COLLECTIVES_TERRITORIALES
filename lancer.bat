@echo off
cd /d "%~dp0"
if not exist venv python -m venv venv
call venv\Scripts\activate
set DJANGO_DEBUG=1
pip install -q -r requirements.txt
if not exist recettes\static\recettes\vendor\tailwind-forms.css (
    call npm install
    call npm run assets
)
python manage.py migrate
set HAS_DATA=
for /f %%i in ('python manage.py shell -c "from recettes.models import Recette; print(Recette.objects.exists())" 2^>nul') do set HAS_DATA=%%i
if not "%HAS_DATA%"=="True" python manage.py generer_donnees_fictives
start /b python manage.py boucle_taches --intervalle 3600
python manage.py runserver
