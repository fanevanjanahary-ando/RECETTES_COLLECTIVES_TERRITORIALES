# API JSON (lecture seule)

Authentification par session (connexion à l'application). Réponses en JSON. Erreurs : 401 non authentifié, 403 droits insuffisants.

| Chemin | Rôles | Paramètres | Contenu |
| --- | --- | --- | --- |
| `/api/referentiels/` | tous | aucun | exercices, secteurs, catégories |
| `/api/recettes/` | tous (agent limité à son secteur) | `annee`, `secteur`, `categorie`, `limite` (500 max), `decalage` | liste de recettes |
| `/api/previsions/` | admin, responsable, élu | `secteur` | prévisions par catégorie, bornes à 95 %, fiabilité, avertissements |
| `/api/ecarts/` | admin, responsable, élu | `annee` | exécution budgétaire et écarts |
| `/api/secteurs/` | admin, responsable, élu | `annee` | recouvrement par secteur |

Les montants sont des chaînes décimales. Les paramètres non numériques sont ignorés.
