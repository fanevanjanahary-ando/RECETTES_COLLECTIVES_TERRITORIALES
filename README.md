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

Sur une base vide, créez l'administrateur avec `python manage.py createsuperuser`. Ne réutilisez pas les identifiants de démonstration en production.

## Tâches périodiques
`lancer.sh` démarre `boucle_taches` (notifications et historisation des prévisions, toutes les heures). Manuellement : `python manage.py envoyer_notifications`, `python manage.py actualiser_previsions`.

## Déploiement

Pour un déploiement sur un hébergeur, configurez la base de données, le stockage persistant des médias, les paramètres SMTP et les tâches périodiques selon les services proposés par la plateforme. Créez le compte administrateur avec `python manage.py createsuperuser`. Les secrets doivent être définis dans l'environnement d'exécution et ne jamais être inscrits dans le dépôt.

### Configuration Gmail en local

Copiez `.env.example` vers `.env`, puis remplacez `EMAIL_HOST_PASSWORD` par un mot de passe d'application Google. Activez la validation en deux étapes du compte Google pour pouvoir en générer un. Le fichier `.env` est ignoré par Git ; ne partagez pas son contenu et ne versionnez jamais le mot de passe. Les variables déjà définies dans l'environnement d'exécution restent prioritaires.

## Tests
`python manage.py test recettes`

## Documentation
Voir `docs/DOCUMENTATION_TECHNIQUE.md`, `docs/API.md`, `docs/MANUEL_UTILISATEUR.md`, `docs/UML.md` et le projet de rapport `docs/RAPPORT_MEMOIRE.md`.



## Made by
RAKOTONDRAMANANA Andomanankasina Fanevanjanahary
