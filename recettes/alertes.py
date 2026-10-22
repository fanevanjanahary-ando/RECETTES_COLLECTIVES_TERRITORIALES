from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

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
    secteur_id: int = 0

    @property
    def significatif(self) -> bool:
        return abs(self.ecart_pct) >= self.seuil_pct

    @property
    def sens(self) -> str:
        return "excédent" if self.ecart_pct > 0 else "déficit"

    @property
    def ecart_net(self) -> Decimal:
        return self.realise - self.cible


def realise_par_categorie_mois(secteur_id=None) -> dict:
    recettes = Recette.objects.all()
    if secteur_id is not None:
        recettes = recettes.filter(secteur_id=secteur_id)
    return {
        (ligne["categorie_id"], ligne["mois"]): ligne["total"]
        for ligne in recettes.values("categorie_id", "mois").annotate(total=Sum("montant"))
    }


def realise_par_categorie_mois_secteur(secteur_id=None) -> dict:
    recettes = Recette.objects.all()
    if secteur_id is not None:
        recettes = recettes.filter(secteur_id=secteur_id)
    return {
        (ligne["categorie_id"], ligne["mois"], ligne["secteur_id"]): ligne["total"]
        for ligne in recettes.values("categorie_id", "mois", "secteur_id").annotate(total=Sum("montant"))
    }


def _objectifs_inscrits(secteur_id=None):
    objectifs = ObjectifBudgetaire.objects.filter(statut=ObjectifBudgetaire.Statut.INSCRIT)
    if secteur_id is not None:
        objectifs = objectifs.filter(secteur_id=secteur_id)
    return objectifs.select_related(
        "categorie", "secteur"
    )


def _realise_de(objectif, par_cat, par_cat_secteur):
    if objectif.secteur_id:
        return par_cat_secteur.get((objectif.categorie_id, objectif.mois, objectif.secteur_id))
    return par_cat.get((objectif.categorie_id, objectif.mois))

def _realise_ou_zero(objectif, par_cat, par_cat_secteur):
    realise = _realise_de(objectif, par_cat, par_cat_secteur)
    if realise is None:
        debut_mois_courant = timezone.localdate().replace(day=1)
        if objectif.mois < debut_mois_courant:
            return Decimal("0")
    return realise

def _objectifs_agreges(annee: int | None = None, secteur_id=None):
    objectifs = _objectifs_inscrits(secteur_id).order_by("pk")
    if annee:
        objectifs = objectifs.filter(mois__year=annee)
    groupes = {}
    for objectif in objectifs:
        cle = (objectif.categorie_id, objectif.mois, objectif.secteur_id)
        if cle in groupes:
            groupes[cle]["cible"] += objectif.montant_cible
        else:
            groupes[cle] = {"objectif": objectif, "cible": objectif.montant_cible}
    return list(groupes.values())


def sans_double_comptage(ecarts):
    consolides = {(e.categorie_id, e.mois) for e in ecarts if not e.secteur_id}
    return [e for e in ecarts if not e.secteur_id or (e.categorie_id, e.mois) not in consolides]


def calculer_ecarts(annee: int | None = None, secteur_id=None):
    seuil_pct = float(ParametrageSysteme.charger().seuil_alerte_pct)
    par_cat = realise_par_categorie_mois(secteur_id)
    par_cat_secteur = realise_par_categorie_mois_secteur(secteur_id)

    ecarts = []
    for groupe in _objectifs_agreges(annee, secteur_id):
        objectif, cible = groupe["objectif"], groupe["cible"]
        realise = _realise_ou_zero(objectif, par_cat, par_cat_secteur)
        if realise is None or cible == 0:
            continue
        ecart_pct = float((realise - cible) / cible * 100)
        ecarts.append(
            Ecart(
                categorie=objectif.categorie.nom,
                categorie_id=objectif.categorie_id,
                mois=objectif.mois,
                realise=realise,
                cible=cible,
                ecart_pct=round(ecart_pct, 1),
                seuil_pct=seuil_pct,
                code=objectif.categorie.code,
                secteur=objectif.secteur.nom if objectif.secteur_id else "",
                objectif_id=objectif.pk,
                secteur_id=objectif.secteur_id or 0,
            )
        )
    ecarts.sort(key=lambda e: abs(e.ecart_pct), reverse=True)
    return ecarts


def alertes_significatives(annee: int | None = None):
    return [e for e in calculer_ecarts(annee) if e.significatif]


def execution_budgetaire(annee: int | None = None, secteur_id=None):
    ecarts = sans_double_comptage(calculer_ecarts(annee, secteur_id))
    total_realise = sum((e.realise for e in ecarts), Decimal("0"))
    total_cible = sum((e.cible for e in ecarts), Decimal("0"))
    taux_pct = float(total_realise / total_cible * 100) if total_cible else None
    return {"total_realise": total_realise, "total_cible": total_cible, "taux_pct": taux_pct}


def _mois_moins(d: date, n: int) -> date:
    total = d.year * 12 + (d.month - 1) - n
    return date(total // 12, total % 12 + 1, 1)


def recouvrement_par_secteur(nb_mois: int = 12, annee: int | None = None, secteur_id=None):
    qs = Recette.objects.all()
    if secteur_id is not None:
        qs = qs.filter(secteur_id=secteur_id)
    if annee:
        qs = qs.filter(mois__year=annee)
    dernier = qs.order_by("-mois").values_list("mois", flat=True).first()
    if dernier is None:
        return {"lignes": [], "mois_debut": None, "mois_fin": None, "total": Decimal("0")}

    mois_debut = date(annee, 1, 1) if annee else _mois_moins(dernier, max(nb_mois - 1, 0))

    totaux = {
        ligne["secteur_id"]: ligne["total"]
        for ligne in qs.filter(mois__gte=mois_debut, mois__lte=dernier)
        .values("secteur_id")
        .annotate(total=Sum("montant"))
    }
    anomalies_qs = Anomalie.objects.filter(traitee=False, brouillon=False)
    en_retard_qs = Anomalie.objects.filter(traitee=False, brouillon=False, date_echeance__lt=timezone.localdate())
    if secteur_id is not None:
        anomalies_qs = anomalies_qs.filter(secteur_id=secteur_id)
        en_retard_qs = en_retard_qs.filter(secteur_id=secteur_id)
    anomalies = {
        ligne["secteur_id"]: ligne
        for ligne in anomalies_qs
        .values("secteur_id")
        .annotate(nb=Count("id"), montant=Sum("montant"))
    }
    en_retard = {}
    for a in en_retard_qs:
        en_retard[a.secteur_id] = max(en_retard.get(a.secteur_id, 0), a.jours_retard)

    total_general = sum(totaux.values(), Decimal("0"))
    lignes = []
    secteurs = Secteur.objects.filter(Q(actif=True) | Q(id__in=list(totaux))).select_related("regisseur", "suppleant")
    if secteur_id is not None:
        secteurs = secteurs.filter(pk=secteur_id)
    for secteur in secteurs:
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
