# Documentation technique

## Architecture et exécution

Application Django monolithique : `collectivite` porte la configuration et les routes, `recettes` contient les règles métier, les vues HTML, l'API JSON, les rapports et les commandes. SQLite sert au développement local ; Render utilise PostgreSQL via `DATABASE_URL`.

Les ressources front sont construites localement avec `npm run assets`. WhiteNoise sert les fichiers statiques en production. Les pièces justificatives et rapports utilisent le stockage Django sous `MEDIA_ROOT` ; sur Render, ce chemin doit pointer vers un disque persistant.

## Modules métier

- `models.py` : utilisateurs et profils, secteurs, catégories, recettes, objectifs, anomalies, notifications, facteurs économiques, rapports, journal d'audit et prévisions historisées.
- `forms.py` : validation des entrées, des montants, des pièces jointes et des dates d'imputation.
- `cloisonnement.py` : portée des recettes et anomalies visible par rôle et par secteur.
- `alertes.py` : écarts budgétaires, exécution et recouvrement.
- `notifications.py` : alertes d'écart, rappels sectoriels et reprises idempotentes des e-mails échoués.
- `prevision.py` : ajustement de tendance, effets saisonniers, intervalles de prédiction et historisation.
- `rapports.py`, `exports.py` : génération PDF, Excel et CSV.
- `api.py` : API JSON en lecture seule, protégée par authentification et rôles.
- `audit.py` : journalisation des actions sensibles.

## Prévisions statistiques

Les recettes du mois courant sont exclues de l'historique, car ce mois est incomplet. La prévision ajuste une régression linéaire sur les mois calendaires observés ; au-delà du seuil paramétré, des effets mensuels sont estimés avec des indicatrices saisonnières. Le calcul utilise le rang de la matrice ajustée et les degrés de liberté résiduels `n - p`, où `p` est le nombre de paramètres effectivement estimés. Une variance résiduelle est calculée sur ces degrés de liberté, puis l'intervalle de prédiction à 95 % utilise une valeur critique de Student et le levier de la prédiction, y compris l'incertitude d'une nouvelle observation. Les quantiles jusqu'à 30 degrés de liberté sont tabulés ; une expansion asymptotique est utilisée au-delà. Les facteurs économiques modifient la prévision et ses bornes.

Un historique trop court ou de rang insuffisant ne produit pas de prévision. L'intervalle de prédiction décrit une plage plausible pour une observation future ; il ne constitue ni un objectif budgétaire ni une garantie.

## Accès et sécurité

Les vues, exports et points d'API vérifient les rôles côté serveur. Les agents sont limités à leur secteur, aux catégories ouvertes à leur rôle et à leurs dossiers visibles ; un profil agent sans secteur n'obtient pas un accès consolidé. Les formulaires refusent les dates d'imputation futures. Les téléchargements de pièces ou rapports absents renvoient une réponse 404 journalisée au lieu d'une erreur 500.

Les e-mails utilisent les variables `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` ou `EMAIL_USE_SSL`, ainsi que `DEFAULT_FROM_EMAIL` et `EMAIL_TIMEOUT`. TLS et SSL ne peuvent pas être activés ensemble. Les échecs d'envoi sont journalisés et les notifications non envoyées peuvent être reprises sans doublon.

## Rappels et alertes

Les alertes d'écart excluent le mois courant. Le rappel de saisie compare les recettes du mois clos aux catégories actives autorisées dans chaque secteur. Il est déclenché au plus tôt au jour global configuré et après le délai J+7, J+10, J+15 ou J+30 du secteur. Les destinataires agents ne reçoivent que les informations de leur secteur ; les responsables et administrateurs habilités reçoivent les secteurs concernés. Les clés d'idempotence empêchent les envois répétés pour un même mois, secteur et destinataire.

La commande planifiée `python manage.py boucle_taches --une-fois` exécute les alertes, les rappels, les reprises d'e-mails d'anomalies et l'historisation des prévisions. `python manage.py envoyer_notifications` permet de déclencher les notifications manuellement.

## Fichiers et déploiement Render

Le système de fichiers Render est éphémère par défaut. Le Blueprint configure un disque persistant sous `/var/data` pour le service web et `DJANGO_MEDIA_ROOT=/var/data/media`. Render exige un plan payant pour ce disque ; un service Cron ne peut pas accéder au disque. La tâche planifiée ne manipule que la base de données et les e-mails.

Les identifiants SMTP et ceux du superutilisateur initial sont des variables secrètes saisies dans Render, jamais versionnées. Le démarrage appelle `creer_admin`, qui crée le superutilisateur sur une base vide et synchronise le rôle applicatif d'un superutilisateur déjà présent. Un identifiant déjà utilisé par un compte non-superutilisateur bloque le démarrage avec une erreur explicite.

## Vérifications

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test recettes
python -m compileall -q collectivite recettes manage.py
git diff --check
```

La suite utilise un hasher rapide uniquement lorsque Django est lancé avec `manage.py test`. Les mots de passe hors tests restent traités par le hasher Django configuré par défaut.
