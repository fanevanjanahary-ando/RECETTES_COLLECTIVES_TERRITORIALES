# PréviRecettes

Projet pédagogique, données fictives. Prévision et suivi des recettes d'une collectivité territoriale.

## Prérequis
- Python 3.12 ou plus (requis par Django 6)
- Node.js 18 ou plus (uniquement pour construire les ressources locales)

## Installation locale
Linux / macOS : `./lancer.sh`
Windows : `lancer.bat`

Le script crée l'environnement virtuel, installe les dépendances Python et Node, construit les ressources locales (Tailwind, polices, Chart.js), applique les migrations et charge les données de démonstration. Aucune ressource n'est chargée depuis Internet.

Sans script :
```
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
npm install
npm run assets
python manage.py migrate
python manage.py generer_donnees_fictives
python manage.py runserver
```

## Comptes de démonstration
Mot de passe : `demo1234`. Adresses : admin.demo@, responsable.demo@, elu.demo@, agent.demo@ `collectivite.example`.
Premier administrateur sur une base vide : `python manage.py createsuperuser` (rôle ADMIN attribué automatiquement) ou `python manage.py creer_admin` avec `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD`.

## Tâches périodiques
`lancer.sh` démarre `boucle_taches` (notifications et historisation des prévisions, toutes les heures). Manuellement : `python manage.py envoyer_notifications`, `python manage.py actualiser_previsions`.

## Tests
`python manage.py test recettes`

## Documentation
Voir `docs/DOCUMENTATION_TECHNIQUE.md`, `docs/API.md`, `docs/MANUEL_UTILISATEUR.md`, `docs/UML.md`.
