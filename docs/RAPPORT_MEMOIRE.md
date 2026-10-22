# Rapport de mémoire — Prévision et suivi des recettes territoriales

> Projet technique à compléter avec les informations institutionnelles, le protocole de validation métier et les résultats observés auprès d'une collectivité. Ce document décrit l'implémentation actuelle ; il ne prétend pas remplacer la validation du mémoire par l'établissement.

## Page de garde à compléter

- **Établissement :** [à compléter]
- **Parcours / niveau :** [à compléter]
- **Auteur :** [à compléter]
- **Encadreur :** [à compléter]
- **Année universitaire :** [à compléter]

## Résumé

Ce projet réalise une application web de suivi des recettes d'une collectivité territoriale. Elle permet de saisir des recettes par catégorie et secteur, de comparer les réalisations aux objectifs budgétaires, de signaler les anomalies et de produire des prévisions statistiques. Les accès sont contrôlés par rôle et, pour les agents, par secteur. Les prévisions et leurs intervalles de prédiction sont des indicateurs d'aide à la décision ; ils ne remplacent pas les objectifs votés ni l'analyse des responsables.

**Mots-clés :** collectivité territoriale, recettes, prévision, Django, tableau de bord, contrôle d'accès.

## 1. Contexte et problématique

La préparation et le suivi budgétaires nécessitent de rapprocher les recettes réalisées des objectifs, par période, catégorie et secteur. Des données dispersées ou des suivis manuels compliquent l'analyse des écarts, la détection des retards et l'anticipation des tendances.

La question abordée est la suivante : comment structurer le suivi des recettes et présenter des estimations statistiques compréhensibles, tout en limitant les accès selon les responsabilités des utilisateurs ?

## 2. Objectifs

### Objectif général

Concevoir une application web d'aide au suivi et à la prévision des recettes territoriales.

### Objectifs spécifiques

- structurer les recettes, objectifs, secteurs et catégories ;
- offrir des tableaux de bord, comparaisons et rapports exportables ;
- estimer les recettes à partir de l'historique et de facteurs configurés ;
- signaler les écarts et les échéances de saisie ;
- protéger les données par authentification, rôles et cloisonnement sectoriel ;
- fournir une documentation technique, une API en lecture seule et un manuel utilisateur.

## 3. Analyse des besoins

L'application distingue les profils d'administrateur, responsable financier, élu/décideur et agent de recouvrement. L'administrateur gère les habilitations, les référentiels et le paramétrage. Le responsable saisit et gère les données métier, traite les anomalies et produit les rapports. L'élu consulte les indicateurs en lecture. L'agent saisit dans son secteur, consulte son périmètre et signale des anomalies.

Une demande d'habilitation est initialement inactive. Un administrateur choisit explicitement de la valider ou de la refuser ; le refus désactive le compte sans supprimer son dossier. Les rôles seuls ne suffisent pas : les vues, API, exports et téléchargements appliquent également les limites de secteur.

## 4. Conception et architecture

Le projet est une application Django composée du projet `collectivite` et de l'application métier `recettes`. Les modèles relient les utilisateurs et profils aux secteurs, recettes, objectifs, catégories, anomalies, notifications et rapports. SQLite est utilisé localement et `DATABASE_URL` permet de connecter PostgreSQL en production.

Les principales couches sont :

1. **Présentation :** gabarits Django et ressources statiques locales.
2. **Contrôle d'accès :** décorateurs de rôle, authentification de session et filtres de visibilité.
3. **Métier :** modèles, formulaires, calculs d'écarts, notifications et prévisions.
4. **Sorties :** API JSON en lecture, exports CSV, classeurs Excel et rapports PDF.
5. **Exploitation :** migrations, commandes de gestion et tâche planifiée.

Le diagramme détaillé des cas d'utilisation, données et séquences figure dans [UML.md](./UML.md). Les routes et paramètres de l'API figurent dans [API.md](./API.md).

## 5. Méthode de prévision

Les observations sont agrégées par catégorie et mois. Le mois courant est exclu de l'historique afin de ne pas traiter une période partielle comme une période complète. La tendance est ajustée par moindres carrés sur le calendrier mensuel. Lorsque l'historique atteint le seuil défini, le modèle inclut des indicatrices des mois de l'année. Les facteurs économiques sont appliqués aux périodes concernées.

La variance résiduelle est estimée avec les degrés de liberté `n - p`, `n` étant le nombre d'observations et `p` le rang des paramètres estimés. L'intervalle de prédiction à 95 % utilise une valeur critique de Student et le levier du point prédit, auquel s'ajoute l'incertitude d'une nouvelle observation. Les quantiles de Student sont tabulés jusqu'à 30 degrés de liberté ; une expansion asymptotique est appliquée au-delà. Si le nombre de points ou le rang est insuffisant, aucune prévision n'est affichée. La fiabilité est évaluée par rétro-test sur les trois derniers mois disponibles et la médiane des erreurs relatives.

Cette méthode simple reste sensible aux ruptures de tendance, aux données manquantes et aux changements de périmètre comptable. L'intervalle exprime une incertitude statistique selon le modèle ; il ne garantit pas le résultat futur.

## 6. Réalisation

La saisie valide les montants, vérifie le format des pièces et refuse une date d'imputation future. Les écarts budgétaires sont calculés sur les mois clos pour le déclenchement des alertes. Les rappels de saisie vérifient les catégories actives par secteur et appliquent le jour global configuré ainsi que le délai de versement du secteur. Les notifications sont idempotentes ; un e-mail échoué reste reprenable sans générer de doublon.

Les rapports peuvent être conservés sous forme de fichiers médias. Si un fichier référencé n'existe plus, l'application renvoie une réponse 404 journalisée. En production Render, les médias sont dirigés vers un disque persistant ; les secrets SMTP et le compte administrateur sont configurés dans l'environnement, pas dans le dépôt.

Les textes juridiques non vérifiés ont été retirés de l'interface. Les règles applicables, délégations et paramètres comptables doivent être validés par les personnes compétentes de la collectivité.

## 7. Vérification et résultats

Les vérifications reproductibles sont :

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test recettes
python -m compileall -q collectivite recettes manage.py
git diff --check
```

Les tests couvrent les droits, les cloisonnements, l'API, les exports et rapports, les notifications, les échéances, les dates et les commandes. La suite de tests est à exécuter après chaque changement ; reporter ici la date, la commande et le résultat obtenus avant la remise finale du mémoire.

Les données générées par `generer_donnees_fictives` servent aux démonstrations et tests fonctionnels. Elles ne constituent pas une évaluation avec des recettes réelles. Aucune précision prédictive sur une collectivité n'est revendiquée sans jeu de données validé et protocole de mesure documenté.

## 8. Déploiement et limites

Le Blueprint Render configure une base PostgreSQL, des variables SMTP, un superutilisateur initial et un traitement Cron. Le service web utilise le disque persistant configuré pour les médias. Ce disque exige un plan payant et n'est pas partagé avec le Cron ; la tâche périodique ne manipule donc que la base et les e-mails.

Les limites actuelles incluent l'ajustement linéaire, la dépendance à l'exhaustivité des données et l'absence d'une validation empirique sur les données réelles de la collectivité. Les règles de versement et habilitations doivent être paramétrées et vérifiées par un responsable.

## Conclusion

Le projet met à disposition un socle cohérent pour la saisie sectorielle, l'analyse budgétaire, la production de rapports et la prévision. Avant une utilisation décisionnelle réelle, il reste nécessaire de confronter le paramétrage et les résultats à un historique vérifié, de faire valider les règles métier et de compléter les informations institutionnelles de la page de garde.
