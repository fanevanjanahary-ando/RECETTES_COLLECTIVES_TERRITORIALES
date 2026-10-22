# Documentation technique

## Architecture
Django 6, application unique `recettes`, base SQLite en local. Interface rendue côté serveur. Ressources front (Tailwind compilé, polices, Chart.js) générées par `npm run assets` dans `recettes/static/recettes/vendor/`.

## Modules
- `models.py` : données métier, journal d'audit, facteurs économiques, prévisions historisées.
- `prevision.py` : régression linéaire sur le calendrier réel des mois, indice saisonnier appliqué à partir de 24 mois d'historique (réglable), intervalle de confiance à 95 %, facteurs économiques multiplicatifs, historisation.
- `alertes.py` : écarts objectifs/réalisé, sans double comptage entre objectifs consolidés et par secteur ; plusieurs types de budget (BP, DM, Report) additionnés.
- `cloisonnement.py` : visibilité par secteur pour les agents.
- `notifications.py` : alertes d'écart (nouvelle alerte à chaque palier de 10 points), rappels d'échéance par secteur, anomalies.
- `rapports.py`, `exports.py` : PDF, Excel, CSV ; liasse mensuelle et synthèse analytique distinctes ; les rapports générés sont conservés.
- `api.py` : API JSON en lecture seule.
- `audit.py` : journal d'audit consultable dans `/admin/`.

## Sécurité
Contrôle d'accès par rôle et par secteur, limitation des tentatives de connexion (5 échecs, 15 minutes), journal d'audit des créations, modifications, suppressions et connexions, vérification du contenu des fichiers téléversés, échappement des sorties, neutralisation des formules dans les exports.

## Méthode de prévision
y = pente x mois + ordonnée, ajustée par moindres carrés sur les mois réellement saisis. Le mois en cours, partiel, est exclu. Intervalle : écart-type des résidus avec correction de levier, niveau 95 %. Fiabilité : rétro-test sur les 3 derniers mois, médiane des erreurs relatives.

## Limites connues
Prévision linéaire (pas de modèle de séries temporelles avancé), saisonnalité estimée sur peu d'années, compteur de tentatives de connexion propre à chaque processus.
