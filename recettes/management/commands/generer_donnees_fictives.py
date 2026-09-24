"""Génère les catégories, les secteurs, les comptes de démo, 36 mois de recettes en Ariary,
des objectifs budgétaires (dont un écart volontaire), des anomalies et quelques rapports."""

import math
import random
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone

from recettes.models import (
    Anomalie,
    Categorie,
    EchangeAnomalie,
    Notification,
    ObjectifBudgetaire,
    ParametrageSysteme,
    Profil,
    RapportGenere,
    Recette,
    Secteur,
)

P, T, R, V = (Categorie.Perception.DIRECTE, Categorie.Perception.TITRE,
              Categorie.Perception.ROLE, Categorie.Perception.VIREMENT)
EXO, NORMAL, HORS = Categorie.Tva.EXO, Categorie.Tva.NORMAL, Categorie.Tva.HORS

COMPTES = [
    ("70323", "Redevances occupation domaine public", "70", P, EXO, 12_000_000, 40_000, 1_800_000, 600_000, True, []),
    ("70688", "Prestations de services et concessions", "70", T, NORMAL, 8_000_000, 25_000, 1_000_000, 400_000, True, []),
    ("73111", "Taxe foncière sur les propriétés bâties", "73", R, EXO, 20_000_000, 90_000, 5_000_000, 900_000, False, []),
    ("73112", "Taxe foncière sur les propriétés non bâties", "73", R, EXO, 3_000_000, 10_000, 400_000, 150_000, False, []),
    ("7362", "Taxe de séjour forfaitaire & réelle", "73", T, EXO, 5_000_000, 30_000, 2_500_000, 400_000, True, ["CENTRE", "SUD"]),
    ("7411", "Dotation globale de fonctionnement (DGF)", "74", V, HORS, 9_000_000, 20_000, 300_000, 200_000, False, []),
    ("7472", "Subventions d'équilibre départementales", "74", T, HORS, 3_000_000, -8_000, 600_000, 250_000, False, ["EST", "NORD"]),
    ("752", "Loyers et revenus des immeubles communaux", "75", T, EXO, 2_500_000, 5_000, 150_000, 100_000, True, ["CENTRE"]),
]
DESCRIPTIONS = {
    "70323": "Terrasses, marchés, échafaudages & voirie", "70688": "Concessions funéraires & droits d'accès",
    "73111": "Imposition directe locale (rôle général)", "73112": "Terrains agricoles et zones naturelles",
    "7362": "Hébergements touristiques et plateformes", "7411": "Forfaitaire commune & péréquation de solidarité",
    "7472": "Fonds d'aide aux voiries et équipements publics", "752": "Baux d'habitation, commerces et conventions",
}

SECTEURS = [
    ("Secteur Nord", "NORD", "Zone d'activités & Port", "Voirie & Domaine Public", 0.32, 50_000_000, 15),
    ("Secteur Sud", "SUD", "Littoral & Stationnement", "Tourisme & Stationnement", 0.30, 40_000_000, 10),
    ("Secteur Centre", "CENTRE", "Cœur historique & Commerces", "Fiscalité & Affaires Générales", 0.25, 60_000_000, 15),
    ("Secteur Est", "EST", "Périurbain & Équipements", "Restauration & Éducation", 0.13, 30_000_000, 30),
]

MOT_DE_PASSE_DEMO = "demo1234"
COMPTES_DEMO = [
    ("admin_demo", Profil.Role.ADMIN, "admin.demo@collectivite.example", "Tiana", "Razafy", None),
    ("responsable_demo", Profil.Role.RESPONSABLE, "responsable.demo@collectivite.example", "Faneva", "Rakotomalala", None),
    ("elu_demo", Profil.Role.ELU, "elu.demo@collectivite.example", "Mialy", "Randria", None),
    ("agent_demo", Profil.Role.AGENT, "agent.demo@collectivite.example", "Marc", "Delorme", "NORD"),
]
AGENTS_SUPPLEMENTAIRES = [
    ("j.luciani", "j.luciani@collectivite.example", "Julien", "Luciani", "SUD"),
    ("c.vasseur", "c.vasseur@collectivite.example", "Claire", "Vasseur", "CENTRE"),
    ("a.benali", "a.benali@collectivite.example", "Ahmed", "Benali", "EST"),
]
MODES = {
    P: ["REGIE"], T: ["TITRE", "VIREMENT"], R: ["ROLE"], V: ["VIREMENT"],
}
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"]


def _mois_moins(d, n):
    total = d.year * 12 + (d.month - 1) - n
    return date(total // 12, total % 12 + 1, 1)


class Command(BaseCommand):
    help = "Génère catégories, secteurs, comptes de démo, recettes, objectifs, anomalies et rapports fictifs (Ariary)."

    def add_arguments(self, parser):
        parser.add_argument("--mois", type=int, default=36, help="Nombre de mois d'historique à générer")
        parser.add_argument("--vider", action="store_true", help="Supprime les données existantes avant de générer")

    def handle(self, *args, **options):
        nb_mois = options["mois"]
        if options["vider"]:
            for modele in (Recette, ObjectifBudgetaire, EchangeAnomalie, Anomalie, Notification, RapportGenere):
                modele.objects.all().delete()
            self.stdout.write(self.style.WARNING("Anciennes données supprimées."))

        ParametrageSysteme.charger()

        secteurs = {}
        for nom, code, description, pole, poids, plafond, freq in SECTEURS:
            secteur, _ = Secteur.objects.get_or_create(nom=nom, defaults={"code": code})
            secteur.description, secteur.pole = description, pole
            secteur.plafond_encaissement = Decimal(plafond)
            secteur.frequence_versement = freq
            secteur.iban = f"MG46 0000 {random.Random(code).randint(1000, 9999)} 0000 0{random.Random(nom).randint(100, 999)}"
            secteur.save()
            secteurs[code] = (secteur, poids)
        self.stdout.write(self.style.SUCCESS(f"{len(secteurs)} secteurs de recouvrement prêts."))

        for identifiant, role, email, prenom, nom, code_secteur in COMPTES_DEMO:
            self._compte(identifiant, email, prenom, nom, role, secteurs.get(code_secteur, (None,))[0])
        for identifiant, email, prenom, nom, code_secteur in AGENTS_SUPPLEMENTAIRES:
            self._compte(identifiant, email, prenom, nom, Profil.Role.AGENT, secteurs[code_secteur][0])
        attente, cree = User.objects.get_or_create(
            username="mh.saintgermain@collectivite.example",
            defaults={"email": "mh.saintgermain@collectivite.example", "first_name": "Marie-Hélène",
                      "last_name": "De Saint-Germain", "is_active": False},
        )
        if cree:
            attente.set_password(MOT_DE_PASSE_DEMO)
            attente.save()
        attente.profil.role = Profil.Role.RESPONSABLE
        attente.profil.en_attente = True
        attente.profil.date_demande = timezone.now() - timedelta(days=2)
        attente.profil.secteur = secteurs["CENTRE"][0]
        attente.profil.matricule = "RH-84920"
        attente.profil.save()

        for code, login, supp in [("NORD", "agent_demo", "responsable_demo"), ("SUD", "j.luciani", "agent_demo"),
                                  ("CENTRE", "c.vasseur", "responsable_demo"), ("EST", "a.benali", "agent_demo")]:
            s = secteurs[code][0]
            s.regisseur = User.objects.get(username=login)
            s.suppleant = User.objects.get(username=supp)
            s.save()
        self.stdout.write(self.style.SUCCESS(
            f"Comptes de démo prêts (mot de passe « {MOT_DE_PASSE_DEMO} ») : "
            + ", ".join(e for _, _, e, *_ in COMPTES_DEMO)))
        responsable = User.objects.get(username="responsable_demo")
        agent = User.objects.get(username="agent_demo")

        categories = {}
        for code, nom, chap, perception, tva, base, tendance, saison, bruit, agents, habilites in COMPTES:
            cat, _ = Categorie.objects.get_or_create(nom=nom)
            cat.code, cat.chapitre, cat.type_perception, cat.regime_tva = code, chap, perception, tva
            cat.ouverte_aux_agents, cat.description = agents, DESCRIPTIONS[code]
            cat.en_revision = code == "7362"
            cat.save()
            cat.secteurs_habilites.set([secteurs[h][0] for h in habilites])
            categories[code] = cat

        aujourdhui = date.today()
        dernier_mois = _mois_moins(date(aujourdhui.year, aujourdhui.month, 1), 1)
        random.seed(42)
        lots = []
        historique = {c[0]: [] for c in COMPTES}
        for i in range(nb_mois):
            mois = _mois_moins(dernier_mois, nb_mois - 1 - i)
            for code, nom, chap, perception, tva, base, tendance, saison, bruit, agents, habilites in COMPTES:
                cat = categories[code]
                cibles = [c for c in secteurs if not habilites or c in habilites]
                somme_poids = sum(secteurs[c][1] for c in cibles)
                total = 0
                for c in cibles:
                    secteur, poids = secteurs[c]
                    part = poids / somme_poids
                    s = saison * math.sin(2 * math.pi * (mois.month - 3) / 12)
                    montant = max(0, (base + tendance * i + s + random.uniform(-bruit, bruit)) * part)
                    montant = round(montant / 10) * 10
                    jour = random.randint(3, 26)
                    lots.append(Recette(
                        categorie=cat, secteur=secteur, mois=mois, date_imputation=mois.replace(day=jour),
                        montant=Decimal(montant), mode_reglement=random.choice(MODES[perception]),
                        libelle=f"{cat.nom} — {MOIS_FR[mois.month - 1]} {mois.year} ({secteur.nom.replace('Secteur ', '')})",
                        saisie_par=agent if (agents and random.random() < 0.6) else responsable,
                    ))
                    total += montant
                historique[code].append((mois, total))
        Recette.objects.bulk_create(lots, batch_size=500)
        for r in Recette.objects.filter(reference=""):
            Recette.objects.filter(pk=r.pk).update(reference=f"BOR-{r.date_imputation:%Y}-{r.pk:04d}")
        self.stdout.write(self.style.SUCCESS(f"{len(lots)} recettes générées sur {nb_mois} mois (jusqu'à {dernier_mois:%m/%Y})."))

        annee = dernier_mois.year
        random.seed(7)
        objectifs = 0
        for code, points in historique.items():
            cat = categories[code]
            for mois, total in points:
                if mois.year != annee:
                    continue
                cible = total * random.uniform(1.00, 1.06)
                if code == "7472" and mois == dernier_mois:
                    cible = total / 0.714
                ObjectifBudgetaire.objects.update_or_create(
                    categorie=cat, mois=mois, secteur=None,
                    defaults={"montant_cible": Decimal(round(cible / 10) * 10), "fixe_par": responsable,
                              "notes": "Inscription au budget primitif votée en séance du conseil.",
                              "type_budget": "BP", "statut": "INSCRIT"})
                objectifs += 1
            moyenne = sum(t for _, t in points[-3:]) / 3
            for k in (1, 2):
                m = _mois_moins(dernier_mois, -k)
                if m.year != annee:
                    continue
                ObjectifBudgetaire.objects.update_or_create(
                    categorie=cat, mois=m, secteur=None,
                    defaults={"montant_cible": Decimal(round(moyenne * 1.02 / 10) * 10), "fixe_par": responsable,
                              "type_budget": "BP", "statut": "INSCRIT"})
                objectifs += 1
        self.stdout.write(self.style.SUCCESS(f"{objectifs} objectifs budgétaires générés (dont un écart volontaire)."))

        nord, sud, centre = secteurs["NORD"][0], secteurs["SUD"][0], secteurs["CENTRE"][0]
        j = date.today()
        a1 = Anomalie.objects.create(
            categorie=categories["70323"], secteur=nord, mois=j.replace(day=1), motif="RETARD", montant=Decimal(14_500_000),
            date_constat=j - timedelta(days=30), date_echeance=j - timedelta(days=12), assigne_a=agent,
            description="Retard d'encaissement constaté sur les droits d'occupation temporaire. Rapprochement bancaire en attente du bordereau définitif.",
            signale_par=agent)
        a2 = Anomalie.objects.create(
            categorie=categories["73111"], secteur=centre, mois=j.replace(day=1), motif="ARRONDI", montant=Decimal(2_350_000),
            date_constat=j - timedelta(days=9), date_echeance=j + timedelta(days=6), assigne_a=User.objects.get(username="c.vasseur"),
            description="Différentiel de centimes agrégés sur 140 avis fonciers. Justificatif complémentaire demandé au service fiscal.",
            signale_par=responsable)
        a3 = Anomalie.objects.create(
            categorie=categories["7362"], secteur=sud, mois=j.replace(day=1), motif="DOUBLE", montant=Decimal(16_000_000),
            date_constat=j - timedelta(days=5), date_echeance=j + timedelta(days=10), assigne_a=User.objects.get(username="j.luciani"),
            description="Écriture passée deux fois par la plateforme hôtelière partenaire. Annulation de titre émise, en attente de visa.",
            signale_par=agent)
        a4 = Anomalie.objects.create(
            categorie=categories["70688"], secteur=sud, mois=(j - timedelta(days=60)).replace(day=1), motif="REJET",
            montant=Decimal(3_200_000), date_constat=j - timedelta(days=60), date_echeance=j - timedelta(days=45),
            assigne_a=User.objects.get(username="j.luciani"), description="Rejet technique de bordereau, régularisé après nouvelle transmission.",
            signale_par=agent, traitee=True, date_regularisation=timezone.now() - timedelta(days=50))
        Anomalie.objects.filter(pk=a4.pk).update(date_signalement=timezone.now() - timedelta(days=60))
        EchangeAnomalie.objects.create(anomalie=a1, auteur=agent, titre="Signalement transmis", texte="Dossier ouvert par le régisseur du secteur Nord.")
        EchangeAnomalie.objects.create(anomalie=a1, auteur=responsable, titre="Relance du régisseur", texte="Demande de justification formelle transmise.")
        EchangeAnomalie.objects.create(anomalie=a1, auteur=responsable, titre="Réponse du Trésor Public", texte="Virement de compensation annoncé sous 5 jours ouvrés.")
        EchangeAnomalie.objects.create(anomalie=a2, auteur=responsable, titre="Signalement transmis", texte="Dossier ouvert par le responsable financier.")
        EchangeAnomalie.objects.create(anomalie=a3, auteur=agent, titre="Signalement transmis", texte="Dossier ouvert par le régisseur.")
        EchangeAnomalie.objects.create(anomalie=a4, auteur=responsable, titre="Dossier régularisé", texte="Écart apuré, dossier clos.")

        for type_doc, delta in (("LIASSE", 6), ("ANOMALIES", 37), ("SYNTHESE", 47)):
            RapportGenere.objects.create(type_doc=type_doc, periode=f"Exercice {annee}", format="PDF",
                                         cree_par=responsable, taille=2_400_000 if type_doc == "LIASSE" else 460_000)
        self.stdout.write(self.style.SUCCESS("Anomalies, échanges et rapports générés."))

        from recettes.notifications import notifier_anomalie, notifier_ecarts_significatifs

        nb = notifier_ecarts_significatifs()
        for a in (a1, a2, a3):
            nb += notifier_anomalie(a)
        self.stdout.write(self.style.SUCCESS(f"{nb} notification(s) créée(s)."))

    def _compte(self, identifiant, email, prenom, nom, role, secteur):
        user, _ = User.objects.get_or_create(username=identifiant)
        user.set_password(MOT_DE_PASSE_DEMO)
        user.email, user.first_name, user.last_name, user.is_active = email, prenom, nom, True
        user.save()
        user.profil.role = role
        user.profil.secteur = secteur
        user.profil.recevoir_notifications = True
        user.profil.en_attente = False
        user.profil.save()
