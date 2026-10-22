# API JSON

L'API est en lecture seule et utilise la session authentifiée de l'application. Une requête sans connexion renvoie `401`, un rôle non autorisé `403`, et une méthode autre que `GET` renvoie `405`. Les listes sont bornées ; les paramètres numériques invalides sont ignorés ou remplacés par leur valeur par défaut.

| Chemin | Rôles | Paramètres | Résultat |
| --- | --- | --- | --- |
| `/api/referentiels/` | Administrateur, responsable, élu, agent | — | Exercices, secteurs accessibles et catégories actives ; pour un agent, catégories ouvertes à son rôle uniquement |
| `/api/recettes/` | Administrateur, responsable, élu, agent | `annee`, `secteur`, `categorie`, `limite` (1–500, défaut 100), `decalage` (défaut 0) | `{annee, total, limite, decalage, resultats}` ; les agents restent limités à leur secteur |
| `/api/previsions/` | Administrateur, responsable, élu | `secteur` | Fiabilité, avertissements et prévisions par catégorie avec montants historiques, prévus, bornes et mois |
| `/api/ecarts/` | Administrateur, responsable, élu | `annee` | Exécution budgétaire et écarts ; les alertes e-mail excluent le mois courant |
| `/api/secteurs/` | Administrateur, responsable, élu | `annee` | Totaux de recouvrement et anomalies ouvertes par secteur |

Les montants sont des chaînes décimales pour éviter une perte de précision JSON. Les prévisions sont statistiques ; les bornes forment un intervalle de prédiction à 95 %, non un objectif voté. L'API ne permet pas à un agent de consulter les écarts, les prévisions ou les indicateurs consolidés.
