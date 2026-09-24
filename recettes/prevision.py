
from collections import defaultdict
from datetime import date

import numpy as np
from django.db.models import Sum
from sklearn.linear_model import LinearRegression

from .models import ParametrageSysteme, Recette

def _mois_suivant(d: date) -> date:
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)

def historique_mensuel_par_categorie() -> dict:
    lignes = (
        Recette.objects.values("categorie_id", "categorie__nom", "mois")
        .annotate(total=Sum("montant"))
        .order_by("categorie_id", "mois")
    )
    par_categorie = {}
    for ligne in lignes:
        cat_id = ligne["categorie_id"]
        if cat_id not in par_categorie:
            par_categorie[cat_id] = (ligne["categorie__nom"], [])
        par_categorie[cat_id][1].append((ligne["mois"], float(ligne["total"])))
    return par_categorie

def _modele(mois_historique, montants_historique, mois_a_prevoir):
    """Régression linéaire (tendance) + indice saisonnier moyen par mois calendaire."""
    X = np.arange(len(montants_historique)).reshape(-1, 1)
    y = np.array(montants_historique)
    modele = LinearRegression()
    modele.fit(X, y)

    tendance_historique = modele.predict(X)
    ecarts_par_mois = defaultdict(list)
    for m, reel, tend in zip(mois_historique, montants_historique, tendance_historique):
        ecarts_par_mois[m.month].append(reel - tend)
    indice_saisonnier = {mois_num: float(np.mean(ecarts)) for mois_num, ecarts in ecarts_par_mois.items()}

    n = len(montants_historique)
    tendance_future = modele.predict(np.arange(n, n + mois_a_prevoir).reshape(-1, 1))

    mois_prevus, curseur = [], mois_historique[-1]
    for _ in range(mois_a_prevoir):
        curseur = _mois_suivant(curseur)
        mois_prevus.append(curseur)

    montants_prevus = [
        round(max(0.0, float(tend) + indice_saisonnier.get(m.month, 0.0)), 2)
        for m, tend in zip(mois_prevus, tendance_future)
    ]
    return mois_prevus, montants_prevus


def previsions_par_categorie(mois_a_prevoir: int | None = None, historique_minimum: int | None = None) -> dict:
    parametres = ParametrageSysteme.charger()
    if mois_a_prevoir is None:
        mois_a_prevoir = parametres.mois_a_prevoir
    if historique_minimum is None:
        historique_minimum = parametres.historique_minimum

    resultats = {}
    for cat_id, (label, points) in historique_mensuel_par_categorie().items():
        if len(points) < historique_minimum:
            continue
        mois_historique = [m for m, _ in points]
        montants_historique = [v for _, v in points]
        mois_prevus, montants_prevus = _modele(mois_historique, montants_historique, mois_a_prevoir)
        resultats[str(cat_id)] = {
            "label": label,
            "mois_historique": [m.strftime("%Y-%m") for m in mois_historique],
            "montants_historique": montants_historique,
            "mois_prevus": [m.strftime("%Y-%m") for m in mois_prevus],
            "montants_prevus": montants_prevus,
        }
    return resultats


def fiabilite_modele(horizon_test: int = 3) -> float | None:
    """Rétro-test : on « cache » les derniers mois, on les prévoit, puis on compare au réalisé.

    Renvoie 100 - erreur moyenne absolue en % (None si l'historique est trop court).
    """
    erreurs = []
    minimum = ParametrageSysteme.charger().historique_minimum
    for _, (_, points) in historique_mensuel_par_categorie().items():
        if len(points) < max(minimum, 2) + horizon_test:
            continue
        appris, teste = points[:-horizon_test], points[-horizon_test:]
        _, prevus = _modele([m for m, _ in appris], [v for _, v in appris], horizon_test)
        for (_, reel), prevu in zip(teste, prevus):
            if reel:
                erreurs.append(abs(prevu - reel) / reel * 100)
    if not erreurs:
        return None
    return round(max(0.0, 100 - sum(erreurs) / len(erreurs)), 1)

def prevision_par_mois() -> dict:
    plat = {}
    for cat_id, serie in previsions_par_categorie().items():
        for texte_mois, valeur in zip(serie["mois_prevus"], serie["montants_prevus"]):
            annee, mois = texte_mois.split("-")
            plat[(int(cat_id), date(int(annee), int(mois), 1))] = valeur
    return plat


def serie_globale() -> dict:
    """Historique mensuel et projection, tous comptes confondus (pour le graphique du tableau de bord)."""
    from collections import OrderedDict

    par_cat = previsions_par_categorie()
    historique = OrderedDict()
    prevu = OrderedDict()
    for serie in par_cat.values():
        for m, v in zip(serie["mois_historique"], serie["montants_historique"]):
            historique[m] = historique.get(m, 0.0) + v
        for m, v in zip(serie["mois_prevus"], serie["montants_prevus"]):
            prevu[m] = prevu.get(m, 0.0) + v
    mois_h = sorted(historique)
    mois_p = sorted(prevu)
    return {
        "mois_historique": mois_h,
        "montants_historique": [round(historique[m], 2) for m in mois_h],
        "mois_prevus": mois_p,
        "montants_prevus": [round(prevu[m], 2) for m in mois_p],
    }
