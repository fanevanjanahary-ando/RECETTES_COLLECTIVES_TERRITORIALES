# Manuel utilisateur

## Connexion et accès

Connectez-vous avec votre adresse e-mail ou votre identifiant. Après cinq échecs, l'accès est verrouillé pendant quinze minutes. Une demande d'habilitation reste inactive jusqu'à la décision explicite d'un administrateur.

Un refus désactive le compte et conserve son dossier. Un administrateur peut ensuite réactiver un compte ou modifier son rôle ; le dernier administrateur actif ne peut pas être désactivé.

## Rôles

| Rôle | Accès principal |
| --- | --- |
| Administrateur | Comptes et habilitations, secteurs, catégories, paramétrage, rapports et supervision |
| Responsable financier | Saisie et gestion des recettes, objectifs, traitement des anomalies, facteurs, notifications et rapports |
| Élu / décideur | Tableau de bord, comparaison, prévisions, écarts, suivi sectoriel et rapports en lecture |
| Agent de recouvrement | Saisie dans son secteur, catégories autorisées, consultation de ses données visibles et signalement d'anomalies |

Les droits sont aussi contrôlés par le serveur. Un agent sans secteur n'accède pas aux données consolidées. Les pièces jointes d'un autre secteur lui sont inaccessibles.

## Recettes

Saisissez la catégorie autorisée, le secteur, la date d'imputation, le montant, le mode de règlement et le libellé. Les dates futures et les montants négatifs sont refusés. La période comptable est déterminée à partir du mois de la date d'imputation. Vous pouvez joindre une pièce justificative dans les formats proposés par le formulaire.

Une pièce absente ou déplacée ne bloque pas l'application : son téléchargement répond « introuvable » et l'événement est journalisé. Signalez ce cas à l'administrateur pour rétablir le document.

## Anomalies et notifications

Un agent signale une anomalie pour son secteur. Les responsables habilités et, si sélectionné, le comptable reçoivent une notification. L'utilisateur assigné ne reçoit pas d'e-mail s'il a désactivé les notifications. Les échecs d'e-mail sont enregistrés et peuvent être repris par la tâche planifiée.

Les responsables et administrateurs peuvent traiter ou relancer un dossier. Les rappels de saisie portent sur les catégories attendues dans chaque secteur. Le délai dépend de la fréquence configurée (J+7, J+10, J+15 ou J+30), sans être antérieur au jour global défini dans le paramétrage.

## Budget, prévisions et rapports

Les objectifs représentent les crédits inscrits ; ils sont distincts des prévisions statistiques. Les alertes d'écart ne sont calculées que pour les mois clos, afin d'éviter de comparer un mois incomplet à son objectif entier.

Les bornes affichées sont un **intervalle de prédiction à 95 %**. Il représente l'incertitude statistique d'une observation future, pas un intervalle d'objectif et pas une garantie. Les résultats dépendent de la quantité et de la qualité de l'historique.

Les rôles autorisés peuvent générer et télécharger les rapports disponibles en PDF, Excel ou CSV. Les exports CSV protègent les cellules contre l'interprétation comme formule par un tableur. Les rapports et justificatifs historiques sont stockés dans le répertoire média configuré.

## Limites et précautions

Les résultats dépendent de la qualité des recettes saisies, des catégories autorisées, des objectifs validés et des fréquences de versement définies par l'administrateur. Les règles réglementaires de la collectivité et les délégations doivent être vérifiées auprès des responsables compétents ; l'application ne s'y substitue pas.
