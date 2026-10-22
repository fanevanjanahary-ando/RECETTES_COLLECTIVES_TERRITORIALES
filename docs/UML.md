# Modélisation UML

## Acteurs et cas d'utilisation

```mermaid
flowchart LR
    Agent([Agent de recouvrement])
    Responsable([Responsable financier])
    Elu([Élu / décideur])
    Admin([Administrateur])
    Auth[Se connecter et gérer son profil]
    Saisie[Saisir et consulter les recettes autorisées]
    Alerte[Signaler une anomalie]
    Budget[Consulter les objectifs et écarts]
    Prevision[Consulter les prévisions]
    Rapport[Générer et télécharger des rapports]
    Traitement[Traiter et relancer les anomalies]
    Referentiel[Gérer les catégories et secteurs]
    Comptes[Arbitrer les habilitations et gérer les comptes]
    Param[Configurer les seuils et échéances]
    Audit[Consulter le journal d'audit]
    Agent --> Auth
    Agent --> Saisie
    Agent --> Alerte
    Responsable --> Auth
    Responsable --> Saisie
    Responsable --> Budget
    Responsable --> Prevision
    Responsable --> Rapport
    Responsable --> Traitement
    Elu --> Auth
    Elu --> Budget
    Elu --> Prevision
    Elu --> Rapport
    Admin --> Auth
    Admin --> Saisie
    Admin --> Budget
    Admin --> Prevision
    Admin --> Rapport
    Admin --> Traitement
    Admin --> Referentiel
    Admin --> Comptes
    Admin --> Param
    Admin --> Audit
```

## Entités et relations

```mermaid
erDiagram
    USER ||--|| PROFIL : possède
    USER ||--o{ RECETTE : saisit
    USER ||--o{ ANOMALIE : signale
    USER ||--o{ ANOMALIE : reçoit_affectation
    USER ||--o{ NOTIFICATION : reçoit
    USER ||--o{ JOURNALAUDIT : déclenche
    USER ||--o{ RAPPORTGENERE : génère
    USER ||--o{ FACTEURECONOMIQUE : crée
    USER ||--o{ PARAMETRAGESYSTEME : modifie
    SECTEUR ||--o{ PROFIL : affecte
    SECTEUR ||--o{ RECETTE : concerne
    SECTEUR ||--o{ OBJECTIFBUDGETAIRE : cible
    SECTEUR ||--o{ ANOMALIE : concerne
    USER ||--o{ SECTEUR : régisseur_ou_suppléant
    CATEGORIE ||--o{ RECETTE : classe
    CATEGORIE ||--o{ OBJECTIFBUDGETAIRE : cible
    CATEGORIE ||--o{ ANOMALIE : classe
    CATEGORIE ||--o{ FACTEURECONOMIQUE : module
    CATEGORIE ||--o{ PREVISIONHISTORISEE : historise
    SECTEUR }o--o{ CATEGORIE : habilite
    ANOMALIE ||--o{ ECHANGEANOMALIE : suit
    PROFIL {
        string role
        boolean recevoir_notifications
        boolean en_attente
        string matricule
        string telephone
    }
    SECTEUR {
        string nom
        string code
        boolean actif
        integer frequence_versement
        decimal plafond_encaissement
        string iban
    }
    CATEGORIE {
        string code
        string nom
        string chapitre
        boolean actif
        boolean ouverte_aux_agents
    }
    RECETTE {
        string reference
        date date_imputation
        date mois
        decimal montant
        string mode_reglement
        string piece_jointe
    }
    OBJECTIFBUDGETAIRE {
        date mois
        string type_budget
        string statut
        decimal montant_cible
    }
    ANOMALIE {
        date mois
        date date_constat
        date date_echeance
        decimal montant
        boolean brouillon
        boolean traitee
    }
    NOTIFICATION {
        string type
        string cle_unicite
        boolean lue
        boolean envoyee_par_email
    }
    ECHANGEANOMALIE {
        string titre
        string texte
        datetime date
    }
    FACTEURECONOMIQUE {
        string libelle
        date mois_debut
        date mois_fin
        decimal effet_pct
    }
    PREVISIONHISTORISEE {
        date mois
        decimal montant_prevu
        decimal borne_basse
        decimal borne_haute
        date date_calcul
        string version
    }
    RAPPORTGENERE {
        string type_doc
        string format
        string periode
        string fichier
    }
    JOURNALAUDIT {
        string action
        string objet
        datetime date
        string adresse_ip
    }
    PARAMETRAGESYSTEME {
        smallint mois_a_prevoir
        smallint historique_minimum
        smallint saisonnalite_minimum_mois
        decimal seuil_alerte_pct
        smallint jour_echeance_recouvrement
        boolean notifications_email_actives
    }
    TENTATIVECONNEXION {
        string cle
        smallint nombre
        datetime date_modification
    }
```

## Séquence d'arbitrage d'une habilitation

```mermaid
sequenceDiagram
    actor C as Candidat
    participant V as Vue d'inscription
    participant DB as Base de données
    actor A as Administrateur
    participant M as Vue d'arbitrage
    C->>V: Dépose un formulaire et une pièce
    V->>DB: Crée le compte inactif et le profil en attente
    V-->>C: Référence de dossier
    A->>M: Choisit explicitement « valider » ou « refuser »
    alt Validation
        M->>DB: Active le compte et clôt l'attente
        M-->>C: Courriel de validation si l'envoi aboutit
    else Refus
        M->>DB: Désactive le compte et conserve le dossier
    else Valeur absente ou inconnue
        M-->>A: Refuse l'arbitrage sans modifier le compte
    end
```

## Séquence des rappels et reprises d'e-mails

```mermaid
sequenceDiagram
    participant Cron as Tâche planifiée
    participant N as notifications.py
    participant DB as Base de données
    participant SMTP as Serveur de courrier
    Cron->>N: boucle_taches --une-fois
    N->>DB: Calcule les écarts sur les mois clos
    N->>DB: Vérifie les catégories manquantes et échéances par secteur
    N->>DB: Crée ou retrouve les notifications idempotentes
    N->>SMTP: Envoie uniquement les courriels non confirmés
    alt Échec SMTP
        SMTP-->>N: Erreur journalisée
        N->>DB: Laisse envoyee_par_email à faux
        Cron->>N: Nouvelle tentative au passage suivant
    else Envoi confirmé
        SMTP-->>N: Succès
        N->>DB: Marque le courriel comme envoyé
    end
    N->>DB: Historise les prévisions calculées
```

## Organisation de l'API

L'API expose des routes `GET` pour les référentiels, les recettes, les prévisions, les écarts et le recouvrement. Les routes vérifient l'authentification et les rôles ; les agents ne peuvent consulter que leurs recettes sectorielles et les catégories autorisées. Voir [API.md](./API.md) pour les paramètres et réponses.
