from collections import defaultdict
from datetime import date

import numpy as np
from django.db.models import Sum
from django.utils import timezone

from .models import FacteurEconomique, ParametrageSysteme, PrevisionHistorisee, Recette

VERSION_MODELE = "tendance-lineaire-saisonnalite-v2"
Z_95 = 1.96


def _mois_suivant(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _indice_mois(d: date) -> int:
    return d.year * 12 + d.month - 1


def historique_mensuel_par_categorie(secteur_id=None) -> dict:
    qs = Recette.objects.all()
    if secteur_id is not None:
        qs = qs.filter(secteur_id=secteur_id)
    lignes = (
        qs.values("categorie_id", "categorie__nom", "mois")
        .annotate(total=Sum("montant"))
        .order_by("categorie_id", "mois")
    )
    debut_mois_courant = timezone.localdate().replace(day=1)
    par_categorie = {}
    for ligne in lignes:
        if ligne["mois"] >= debut_mois_courant:
            continue
        cat_id = ligne["categorie_id"]
        if cat_id not in par_categorie:
            par_categorie[cat_id] = (ligne["categorie__nom"], [])
        par_categorie[cat_id][1].append((ligne["mois"], float(ligne["total"])))
    return par_categorie


def _facteurs():
    return list(FacteurEconomique.objects.all())


def _coefficient(facteurs, categorie_id, mois):
    coefficient = 1.0
    for f in facteurs:
        if f.mois_debut <= mois <= f.mois_fin and (f.categorie_id is None or f.categorie_id == categorie_id):
            coefficient *= 1 + float(f.effet_pct) / 100
    return coefficient


def _modele(mois_historique, montants_historique, mois_a_prevoir, saisonnalite_minimum=24,
            facteurs=None, categorie_id=None):
    x = np.array([_indice_mois(m) - _indice_mois(mois_historique[0]) for m in mois_historique], dtype=float)
    y = np.array(montants_historique, dtype=float)
    n = len(y)

    if n >= 2 and np.ptp(x) > 0:
        pente, ordonnee = np.polyfit(x, y, 1)
    else:
        pente, ordonnee = 0.0, float(y.mean())
    tendance = pente * x + ordonnee
    residus = y - tendance

    etendue = int(x[-1] - x[0]) + 1
    saisonnalite = etendue >= saisonnalite_minimum
    indice = {}
    if saisonnalite:
        par_mois = defaultdict(list)
        for m, r in zip(mois_historique, residus):
            par_mois[m.month].append(float(r))
        indice = {k: float(np.mean(v)) for k, v in par_mois.items()}
        residus = residus - np.array([indice[m.month] for m in mois_historique])

    ddl = max(n - 2, 1)
    sigma = float(np.sqrt(np.sum(residus ** 2) / ddl)) if n > 2 else 0.0
    xbar = float(x.mean())
    sxx = float(np.sum((x - xbar) ** 2)) or 1.0

    mois_prevus, curseur = [], mois_historique[-1]
    for _ in range(mois_a_prevoir):
        curseur = _mois_suivant(curseur)
        mois_prevus.append(curseur)

    facteurs = facteurs or []
    montants, bas, haut = [], [], []
    for m in mois_prevus:
        x0 = _indice_mois(m) - _indice_mois(mois_historique[0])
        base = pente * x0 + ordonnee + indice.get(m.month, 0.0)
        marge = Z_95 * sigma * float(np.sqrt(1 + 1 / n + (x0 - xbar) ** 2 / sxx))
        coef = _coefficient(facteurs, categorie_id, m)
        montants.append(round(float(max(0.0, base * coef)), 2))
        bas.append(round(float(max(0.0, (base - marge) * coef)), 2))
        haut.append(round(float(max(0.0, (base + marge) * coef)), 2))
    return mois_prevus, montants, bas, haut, saisonnalite


def previsions_par_categorie(mois_a_prevoir: int | None = None, historique_minimum: int | None = None,
                             secteur_id=None) -> dict:
    parametres = ParametrageSysteme.charger()
    if mois_a_prevoir is None:
        mois_a_prevoir = parametres.mois_a_prevoir
    if historique_minimum is None:
        historique_minimum = parametres.historique_minimum
    facteurs = _facteurs()

    resultats = {}
    for cat_id, (label, points) in historique_mensuel_par_categorie(secteur_id).items():
        if len(points) < historique_minimum:
            continue
        mois_historique = [m for m, _ in points]
        montants_historique = [v for _, v in points]
        mois_prevus, montants, bas, haut, saisonnalite = _modele(
            mois_historique, montants_historique, mois_a_prevoir,
            parametres.saisonnalite_minimum_mois, facteurs, cat_id,
        )
        resultats[str(cat_id)] = {
            "label": label,
            "mois_historique": [m.strftime("%Y-%m") for m in mois_historique],
            "montants_historique": montants_historique,
            "mois_prevus": [m.strftime("%Y-%m") for m in mois_prevus],
            "montants_prevus": montants,
            "bornes_basses": bas,
            "bornes_hautes": haut,
            "saisonnalite": saisonnalite,
            "nb_mois_historique": len(points),
        }
    return resultats


def avertissements_modele(previsions: dict | None = None) -> list:
    previsions = previsions if previsions is not None else previsions_par_categorie()
    minimum = ParametrageSysteme.charger().saisonnalite_minimum_mois
    courts = [s["label"] for s in previsions.values() if not s["saisonnalite"]]
    messages = []
    if not previsions:
        messages.append("Historique insuffisant : aucune prévision n'a pu être calculée.")
    elif courts:
        messages.append(
            f"Moins de {minimum} mois d'historique pour {len(courts)} catégorie(s) : "
            "la prévision repose sur la tendance seule, sans effet saisonnier."
        )
    return messages


def fiabilite_modele(horizon_test: int = 3) -> float | None:
    erreurs = []
    parametres = ParametrageSysteme.charger()
    minimum = max(parametres.historique_minimum, 2)
    for cat_id, (_, points) in historique_mensuel_par_categorie().items():
        if len(points) < minimum + horizon_test:
            continue
        appris, teste = points[:-horizon_test], points[-horizon_test:]
        _, prevus, _, _, _ = _modele(
            [m for m, _ in appris], [v for _, v in appris], horizon_test, parametres.saisonnalite_minimum_mois,
        )
        for (_, reel), prevu in zip(teste, prevus):
            if reel:
                erreurs.append(abs(prevu - reel) / reel * 100)
    if not erreurs:
        return None
    return round(max(0.0, 100 - float(np.median(erreurs))), 1)


def prevision_par_mois(previsions: dict | None = None) -> dict:
    previsions = previsions if previsions is not None else previsions_par_categorie()
    plat = {}
    for cat_id, serie in previsions.items():
        for texte_mois, valeur in zip(serie["mois_prevus"], serie["montants_prevus"]):
            annee, mois = texte_mois.split("-")
            plat[(int(cat_id), date(int(annee), int(mois), 1))] = valeur
    return plat


def serie_globale(previsions: dict | None = None) -> dict:
    par_cat = previsions if previsions is not None else previsions_par_categorie()
    historique, prevu = {}, {}
    dernier_commun = ""
    for serie in par_cat.values():
        for m, v in zip(serie["mois_historique"], serie["montants_historique"]):
            historique[m] = historique.get(m, 0.0) + v
            dernier_commun = max(dernier_commun, m)
    for serie in par_cat.values():
        for m, v in zip(serie["mois_prevus"], serie["montants_prevus"]):
            if m > dernier_commun:
                prevu[m] = prevu.get(m, 0.0) + v
    mois_h, mois_p = sorted(historique), sorted(prevu)
    return {
        "mois_historique": mois_h,
        "montants_historique": [round(historique[m], 2) for m in mois_h],
        "mois_prevus": mois_p,
        "montants_prevus": [round(prevu[m], 2) for m in mois_p],
    }


def historiser_previsions(date_calcul: date | None = None) -> int:
    date_calcul = date_calcul or timezone.localdate()
    nb = 0
    for cat_id, serie in previsions_par_categorie().items():
        for texte_mois, valeur, bas, haut in zip(
            serie["mois_prevus"], serie["montants_prevus"], serie["bornes_basses"], serie["bornes_hautes"]
        ):
            annee, mois = texte_mois.split("-")
            PrevisionHistorisee.objects.update_or_create(
                categorie_id=int(cat_id), mois=date(int(annee), int(mois), 1), date_calcul=date_calcul,
                defaults={"montant_prevu": valeur, "borne_basse": bas, "borne_haute": haut, "version": VERSION_MODELE},
            )
            nb += 1
    return nb


def prevu_contre_realise() -> list:
    realise = {
        (l["categorie_id"], l["mois"]): l["t"]
        for l in Recette.objects.values("categorie_id", "mois").annotate(t=Sum("montant"))
    }
    lignes = []
    vus = set()
    for p in PrevisionHistorisee.objects.select_related("categorie").filter(
        mois__lt=timezone.localdate().replace(day=1)
    ).order_by("categorie_id", "mois", "-date_calcul"):
        cle = (p.categorie_id, p.mois)
        if cle in vus or cle not in realise:
            continue
        vus.add(cle)
        reel = realise[cle]
        ecart = float((reel - p.montant_prevu) / p.montant_prevu * 100) if p.montant_prevu else None
        lignes.append({
            "categorie": p.categorie.nom, "mois": p.mois, "prevu": p.montant_prevu,
            "realise": reel, "ecart_pct": round(ecart, 1) if ecart is not None else None,
            "date_calcul": p.date_calcul,
        })
    return lignes