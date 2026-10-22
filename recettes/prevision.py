from datetime import date

import numpy as np
from django.db.models import Sum
from django.utils import timezone

from .models import FacteurEconomique, ParametrageSysteme, PrevisionHistorisee, Recette

VERSION_MODELE = "tendance-lineaire-saisonnalite-v3"
_T_975 = (
    0.0, 12.7062, 4.3027, 3.1824, 2.7764, 2.5706, 2.4469, 2.3646,
    2.3060, 2.2622, 2.2281, 2.2010, 2.1788, 2.1604, 2.1448, 2.1314,
    2.1199, 2.1098, 2.1009, 2.0930, 2.0860, 2.0796, 2.0739, 2.0687,
    2.0639, 2.0595, 2.0555, 2.0518, 2.0484, 2.0452, 2.0423,
)


def _t_critique_95(degres_liberte: int) -> float:
    if degres_liberte < 1:
        raise ValueError("Les degrés de liberté doivent être strictement positifs.")
    if degres_liberte < len(_T_975):
        return _T_975[degres_liberte]

    z = 1.959963984540054
    v = float(degres_liberte)
    z2 = z * z
    return (
        z
        + (z * z2 + z) / (4 * v)
        + (5 * z * z2**2 + 16 * z * z2 + 3 * z) / (96 * v**2)
        + (3 * z * z2**3 + 19 * z * z2**2 + 17 * z * z2 - 15 * z) / (384 * v**3)
        + (79 * z * z2**4 + 776 * z * z2**3 + 1482 * z * z2**2 - 1920 * z * z2 - 945 * z)
        / (92160 * v**4)
    )


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
    y = np.array(montants_historique, dtype=float)
    n = len(y)
    mois_origine = _indice_mois(mois_historique[0])
    x = np.array([_indice_mois(m) - mois_origine for m in mois_historique], dtype=float)
    etendue = int(x[-1] - x[0]) + 1
    mois_saisonniers = sorted({m.month for m in mois_historique})
    saisonnalite = n >= saisonnalite_minimum and etendue >= saisonnalite_minimum and len(mois_saisonniers) > 1

    def matrice_design(mois, avec_saisonnalite):
        offsets = np.array([_indice_mois(m) - mois_origine for m in mois], dtype=float)
        colonnes = [np.ones(len(mois)), offsets]
        if avec_saisonnalite:
            colonnes.extend(
                np.array([float(m.month == code) for m in mois])
                for code in mois_saisonniers[1:]
            )
        return np.column_stack(colonnes)

    matrice = matrice_design(mois_historique, saisonnalite)
    rang = np.linalg.matrix_rank(matrice)
    if rang < matrice.shape[1] or n <= matrice.shape[1]:
        saisonnalite = False
        matrice = matrice_design(mois_historique, False)
        rang = np.linalg.matrix_rank(matrice)
    if rang < matrice.shape[1] or n <= matrice.shape[1]:
        raise ValueError("L'historique ne contient pas assez de points indépendants pour la prévision.")

    coefficients, _, _, _ = np.linalg.lstsq(matrice, y, rcond=None)
    residus = y - matrice @ coefficients
    degres_liberte = n - matrice.shape[1]
    sigma = float(np.sqrt(np.sum(residus ** 2) / degres_liberte))
    inverse = np.linalg.pinv(matrice)

    mois_prevus, curseur = [], mois_historique[-1]
    for _ in range(mois_a_prevoir):
        curseur = _mois_suivant(curseur)
        mois_prevus.append(curseur)

    facteurs = facteurs or []
    montants, bas, haut = [], [], []
    for m in mois_prevus:
        vecteur = matrice_design([m], saisonnalite)[0]
        base = float(vecteur @ coefficients)
        levier = float(np.sum((vecteur @ inverse) ** 2))
        marge = _t_critique_95(degres_liberte) * sigma * float(np.sqrt(1 + levier))
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
    historique_minimum = max(historique_minimum, 3)
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
    minimum = max(parametres.historique_minimum, 3)
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