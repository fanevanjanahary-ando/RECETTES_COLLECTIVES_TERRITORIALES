import csv
from io import StringIO

from django.http import HttpResponse

from .alertes import calculer_ecarts, recouvrement_par_secteur
from .models import ObjectifBudgetaire, Recette
from .prevision import previsions_par_categorie
from .rapports import comparaison_exercices

SEPARATEUR = ";"

def _nombre(valeur) -> str:
    if valeur is None:
        return ""
    return f"{float(valeur):.2f}".replace(".", ",")

def _reponse_csv(nom_fichier: str, entetes, lignes) -> HttpResponse:
    tampon = StringIO()
    redacteur = csv.writer(tampon, delimiter=SEPARATEUR, quoting=csv.QUOTE_MINIMAL)
    redacteur.writerow(entetes)
    redacteur.writerows(lignes)
    reponse = HttpResponse(
        tampon.getvalue().encode("utf-8-sig"), content_type="text/csv; charset=utf-8"
    )
    reponse["Content-Disposition"] = f'attachment; filename="{nom_fichier}"'
    return reponse

def export_recettes_csv() -> HttpResponse:
    lignes = [
        [
            r.reference,
            r.date_imputation.strftime("%d/%m/%Y") if r.date_imputation else r.mois.strftime("%Y-%m"),
            r.categorie.chapitre,
            r.categorie.libelle_complet,
            r.secteur.nom,
            r.get_mode_reglement_display(),
            _nombre(r.montant),
            r.libelle,
            r.saisie_par.username if r.saisie_par else "",
            r.date_saisie.strftime("%d/%m/%Y %H:%M"),
        ]
        for r in Recette.objects.select_related("categorie", "secteur", "saisie_par").order_by("mois", "id")
    ]
    return _reponse_csv(
        "recettes.csv",
        ["Référence", "Date", "Chapitre", "Compte", "Secteur", "Mode de règlement", "Montant (Ar)", "Libellé", "Saisie par", "Date de saisie"],
        lignes,
    )

def export_objectifs_csv() -> HttpResponse:
    lignes = [
        [o.mois.strftime("%Y-%m"), o.categorie.nom, _nombre(o.montant_cible),
         o.fixe_par.username if o.fixe_par else ""]
        for o in ObjectifBudgetaire.objects.select_related("categorie", "fixe_par").order_by("mois")
    ]
    return _reponse_csv(
        "objectifs_budgetaires.csv",
        ["Mois", "Catégorie", "Objectif voté (Ar)", "Fixé par"],
        lignes,
    )

def export_ecarts_csv() -> HttpResponse:
    lignes = [
        [
            e.mois.strftime("%Y-%m"), e.categorie, _nombre(e.cible), _nombre(e.realise),
            _nombre(e.ecart_pct), "OUI" if e.significatif else "non",
        ]
        for e in calculer_ecarts()
    ]
    return _reponse_csv(
        "ecarts_budgetaires.csv",
        ["Mois", "Catégorie", "Objectif voté (Ar)", "Réalisé (Ar)", "Écart (%)", "Alerte"],
        lignes,
    )

def export_previsions_csv() -> HttpResponse:
    lignes = []
    for serie in previsions_par_categorie().values():
        for mois, valeur in zip(serie["mois_prevus"], serie["montants_prevus"]):
            lignes.append([mois, serie["label"], _nombre(valeur)])
    return _reponse_csv(
        "previsions.csv",
        ["Mois", "Catégorie", "Prévision statistique (Ar)"],
        lignes,
    )

def export_comparaison_exercices_csv() -> HttpResponse:
    comparaison = comparaison_exercices()
    annees = comparaison["annees"]
    entetes = ["Catégorie"] + [f"Exercice {a} (Ar)" for a in annees]
    entetes += [f"Variation {a} (%)" for a in annees[1:]]

    lignes = []
    for ligne in comparaison["lignes"]:
        rangee = [ligne["categorie"]] + [_nombre(ligne["totaux"][a]) for a in annees]
        rangee += [_nombre(ligne["variations"].get(a)) for a in annees[1:]]
        lignes.append(rangee)
    if annees:
        rangee = ["TOTAL"] + [_nombre(comparaison["totaux_generaux"][a]) for a in annees]
        rangee += [_nombre(comparaison["variations_generales"].get(a)) for a in annees[1:]]
        lignes.append(rangee)
    return _reponse_csv("comparaison_exercices.csv", entetes, lignes)

def export_secteurs_csv() -> HttpResponse:
    suivi = recouvrement_par_secteur()
    lignes = [
        [l["secteur"].nom, _nombre(l["total"]), _nombre(l["part_pct"]), l["anomalies_ouvertes"]]
        for l in suivi["lignes"]
    ]
    return _reponse_csv(
        "recouvrement_par_secteur.csv",
        ["Secteur", "Total encaissé (Ar)", "Part (%)", "Anomalies ouvertes"],
        lignes,
    )


def export_anomalies_csv() -> HttpResponse:
    from .models import Anomalie

    lignes = [
        [a.reference, a.secteur.nom, a.categorie.libelle_complet, a.get_motif_display(), _nombre(a.montant),
         a.date_constat.strftime("%d/%m/%Y") if a.date_constat else "",
         a.date_echeance.strftime("%d/%m/%Y") if a.date_echeance else "", a.statut]
        for a in Anomalie.objects.select_related("secteur", "categorie").filter(brouillon=False)
    ]
    return _reponse_csv(
        "anomalies.csv",
        ["Référence", "Secteur", "Compte", "Motif", "Montant (Ar)", "Date de constat", "Échéance", "Statut"],
        lignes,
    )


def export_categories_csv() -> HttpResponse:
    from .models import Categorie

    lignes = [
        [c.code, c.chapitre, c.nom, c.get_type_perception_display(), c.get_regime_tva_display(),
         "Actif" if c.actif and not c.en_revision else ("En révision" if c.actif else "Désactivé")]
        for c in Categorie.objects.all()
    ]
    return _reponse_csv("categories.csv", ["Code", "Chapitre", "Libellé", "Perception", "TVA", "Statut"], lignes)
