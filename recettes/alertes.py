from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Count, Sum

from .models import Anomalie, ObjectifBudgetaire, ParametrageSysteme, Recette, Secteur


@dataclass
class Ecart:
    categorie: str
    categorie_id: int
    mois: object
    realise: Decimal
    cible: Decimal
    ecart_pct: float
    seuil_pct: float
    code: str = ""
    secteur: str = ""
    objectif_id: int = 0

    @property
    def significatif(self) -> bool:
        return abs(self.ecart_pct) >= self.seuil_pct

    @property
    def sens(self) -> str:
        return "excédent" if self.ecart_pct > 0 else "déficit"

    @property
    def ecart_net(self) -> Decimal:
        return self.realise - self.cible


def realise_par_categorie_mois() -> dict:
    return {
        (ligne["categorie_id"], ligne["mois"]): ligne["total"]
        for ligne in Recette.objects.values("categorie_id", "mois").annotate(total=Sum("montant"))
    }


def realise_par_categorie_mois_secteur() -> dict:
    return {
        (ligne["categorie_id"], ligne["mois"], ligne["secteur_id"]): ligne["total"]
        for ligne in Recette.objects.values("categorie_id", "mois", "secteur_id").annotate(total=Sum("montant"))
    }


def _objectifs_inscrits():
    return ObjectifBudgetaire.objects.filter(statut=ObjectifBudgetaire.Statut.INSCRIT).select_related(
        "categorie", "secteur"
    )


def _realise_de(objectif, par_cat, par_cat_secteur):
    if objectif.secteur_id:
        return par_cat_secteur.get((objectif.categorie_id, objectif.mois, objectif.secteur_id))
    return par_cat.get((objectif.categorie_id, objectif.mois))


def calculer_ecarts(annee: int | None = None):
    seuil_pct = float(ParametrageSysteme.charger().seuil_alerte_pct)
    par_cat = realise_par_categorie_mois()
    par_cat_secteur = realise_par_categorie_mois_secteur()

    ecarts = []
    objectifs = _objectifs_inscrits()
    if annee:
        objectifs = objectifs.filter(mois__year=annee)
    for objectif in objectifs:
        realise = _realise_de(objectif, par_cat, par_cat_secteur)
        if realise is None or objectif.montant_cible == 0:
            continue
        ecart_pct = float((realise - objectif.montant_cible) / objectif.montant_cible * 100)
        ecarts.append(
            Ecart(
                categorie=objectif.categorie.nom,
                categorie_id=objectif.categorie_id,
                mois=objectif.mois,
                realise=realise,
                cible=objectif.montant_cible,
                ecart_pct=round(ecart_pct, 1),
                seuil_pct=seuil_pct,
                code=objectif.categorie.code,
                secteur=objectif.secteur.nom if objectif.secteur_id else "",
                objectif_id=objectif.pk,
            )
        )
    ecarts.sort(key=lambda e: abs(e.ecart_pct), reverse=True)
    return ecarts


def alertes_significatives(annee: int | None = None):
    return [e for e in calculer_ecarts(annee) if e.significatif]


def execution_budgetaire(annee: int | None = None):
    par_cat = realise_par_categorie_mois()
    par_cat_secteur = realise_par_categorie_mois_secteur()
    total_realise = Decimal("0")
    total_cible = Decimal("0")
    objectifs = _objectifs_inscrits()
    if annee:
        objectifs = objectifs.filter(mois__year=annee)
    for objectif in objectifs:
        realise = _realise_de(objectif, par_cat, par_cat_secteur)
        if realise is None:
            continue
        total_realise += realise
        total_cible += objectif.montant_cible
    taux_pct = float(total_realise / total_cible * 100) if total_cible else None
    return {"total_realise": total_realise, "total_cible": total_cible, "taux_pct": taux_pct}


def _mois_moins(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) - n
    return date(total // 12, total % 12 + 1, 1)


def recouvrement_par_secteur(nb_mois: int = 12, annee: int | None = None):
    qs = Recette.objects.all()
    if annee:
        qs = qs.filter(mois__year=annee)
    dernier = qs.order_by("-mois").values_list("mois", flat=True).first()
    if dernier is None:
        return {"lignes": [], "mois_debut": None, "mois_fin": None, "total": Decimal("0")}

    mois_debut = date(annee, 1, 1) if annee else _mois_moins(dernier, max(nb_mois - 1, 0))

    totaux = {
        ligne["secteur_id"]: ligne["total"]
        for ligne in Recette.objects.filter(mois__gte=mois_debut, mois__lte=dernier)
        .values("secteur_id")
        .annotate(total=Sum("montant"))
    }
    anomalies = {
        ligne["secteur_id"]: ligne
        for ligne in Anomalie.objects.filter(traitee=False, brouillon=False)
        .values("secteur_id")
        .annotate(nb=Count("id"), montant=Sum("montant"))
    }
    en_retard = {}
    for a in Anomalie.objects.filter(traitee=False, brouillon=False, date_echeance__lt=date.today()):
        en_retard[a.secteur_id] = max(en_retard.get(a.secteur_id, 0), a.jours_retard)

    total_general = sum(totaux.values(), Decimal("0"))
    lignes = []
    for secteur in Secteur.objects.filter(actif=True).select_related("regisseur", "suppleant"):
        total = totaux.get(secteur.id, Decimal("0"))
        part = float(total / total_general * 100) if total_general else 0.0
        info = anomalies.get(secteur.id, {})
        lignes.append(
            {
                "secteur": secteur,
                "total": total,
                "part_pct": round(part, 1),
                "anomalies_ouvertes": info.get("nb", 0),
                "montant_souffrance": info.get("montant") or Decimal("0"),
                "retard_jours": en_retard.get(secteur.id, 0),
            }
        )
    lignes.sort(key=lambda l: l["total"], reverse=True)
    return {"lignes": lignes, "mois_debut": mois_debut, "mois_fin": dernier, "total": total_general}
