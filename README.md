# RECETTES_COLLECTIVES_TERRITORIALES
CONCEPTION D'UN SYSTÈME D'AIDE À LA DÉCISION POUR LA PRÉVISION DES RECETTES D'UNE COLLECTIVITÉ TERRITORIALE



# PréviRecettes

Application Django de suivi et de prévision des recettes d'une collectivité territoriale. Les montants sont exprimés en Ariary (Ar).

## Installation

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py generer_donnees_fictives
python manage.py runserver
```

Ou lancer directement :

```bash
./lancer.sh
```

Ouvrir http://127.0.0.1:8000/.

## Commandes utiles

```bash
python manage.py test recettes
python manage.py envoyer_notifications
python manage.py createsuperuser
```

Les comptes de démonstration sont créés par `generer_donnees_fictives`. Leur mot de passe est `demo1234`.

## Comptes de démonstration

| E-mail | Rôle |
| --- | --- |
| `admin.demo@collectivite.example` | Administrateur |
| `responsable.demo@collectivite.example` | Responsable financier |
| `elu.demo@collectivite.example` | Élu / décideur |
| `agent.demo@collectivite.example` | Agent de recouvrement |
| `j.luciani@collectivite.example` | Agent de recouvrement |
| `c.vasseur@collectivite.example` | Agent de recouvrement |
| `a.benali@collectivite.example` | Agent de recouvrement |
| `mh.saintgermain@collectivite.example` | Responsable financier, en attente |

## Configuration

Les principales variables d'environnement sont `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_DB_PATH` et les variables SMTP `EMAIL_*`.

