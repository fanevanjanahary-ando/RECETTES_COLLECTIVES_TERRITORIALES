# PréviRecettes

Application de prévision et de suivi des recettes d'une collectivité territoriale.

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
Les comptes de démonstration sont chargés uniquement par la commande de données fictives. Leur mot de passe est `demo1234` et leurs adresses sont `admin.demo@collectivite.example`, `responsable.demo@collectivite.example`, `elu.demo@collectivite.example` et `agent.demo@collectivite.example`.

Sur une base locale vide, créez l'administrateur avec `python manage.py createsuperuser` ou `python manage.py creer_admin` en définissant `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL` et `DJANGO_SUPERUSER_PASSWORD`. Ne réutilisez pas les identifiants de démonstration en production.

## Tâches périodiques
`lancer.sh` démarre `boucle_taches` (notifications et historisation des prévisions, toutes les heures). Manuellement : `python manage.py envoyer_notifications`, `python manage.py actualiser_previsions`.

## Déploiement Render

Le Blueprint utilise PostgreSQL, un disque persistant pour les médias et une tâche Cron quotidienne. Les disques persistants nécessitent un plan Render payant et ne sont pas accessibles depuis Cron ; le service web conserve les téléversements sous `/var/data/media`, tandis que Cron traite la base de données et les e-mails uniquement.

À la création du Blueprint, renseignez les secrets `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD`, ainsi que les paramètres SMTP du groupe `collectivite-mail`. Ces valeurs ne doivent pas être inscrites dans le dépôt. `creer_admin` est exécutée au démarrage du service et synchronise le rôle applicatif du superutilisateur existant.

## Tests
`python manage.py test recettes`

## Documentation
Voir `docs/DOCUMENTATION_TECHNIQUE.md`, `docs/API.md`, `docs/MANUEL_UTILISATEUR.md`, `docs/UML.md` et le projet de rapport `docs/RAPPORT_MEMOIRE.md`.
