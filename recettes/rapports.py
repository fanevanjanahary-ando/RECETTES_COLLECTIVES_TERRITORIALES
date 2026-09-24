from datetime import date
from decimal import Decimal
from html import escape
from io import BytesIO

from django.db.models import Sum
from django.db.models.functions import ExtractYear
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .alertes import calculer_ecarts, recouvrement_par_secteur
from .formats import ar
from .models import Categorie, ParametrageSysteme, Recette
from .prevision import previsions_par_categorie

def comparaison_exercices(annees: int = 3) -> dict:
    lignes_brutes = (
        Recette.objects.annotate(annee=ExtractYear("mois"))
        .values("annee", "categorie_id", "categorie__nom", "categorie__chapitre")
        .annotate(total=Sum("montant"))
        .order_by("annee")
    )

    toutes_annees = sorted({ligne["annee"] for ligne in lignes_brutes})
    if not toutes_annees:
        return {
            "annees": [], "lignes": [], "lignes_chapitres": [], "totaux_generaux": {},
            "variations_generales": {}, "avertissement_annee_partielle": None,
            "projection_totale": None, "tendance_totale": None, "mois_saisis": 0,
            "annees_comparees": [], "cellules_totaux_generaux": [], "cellules_variations_generales": [],
        }
    annees_retenues = toutes_annees[-annees:]

    par_categorie = {}
    for ligne in lignes_brutes:
        if ligne["annee"] not in annees_retenues:
            continue
        cle = ligne["categorie_id"]
        par_categorie.setdefault(cle, {"categorie": ligne["categorie__nom"], "chapitre": ligne["categorie__chapitre"], "totaux": {}})
        par_categorie[cle]["totaux"][ligne["annee"]] = ligne["total"]

    def _variations(totaux):
        variations = {}
        for precedente, courante in zip(annees_retenues, annees_retenues[1:]):
            avant = totaux.get(precedente)
            apres = totaux.get(courante)
            if avant and avant != 0 and apres is not None:
                variations[courante] = round(float((apres - avant) / avant * 100), 1)
            else:
                variations[courante] = None
        return variations

    lignes = []
    for donnees in par_categorie.values():
        totaux = {annee: donnees["totaux"].get(annee, Decimal("0")) for annee in annees_retenues}
        variations = _variations(totaux)
        lignes.append(
            {
                "categorie": donnees["categorie"],
                "chapitre": donnees["chapitre"],
                "totaux": totaux,
                "variations": variations,
                "cellules_totaux": [totaux[a] for a in annees_retenues],
                "cellules_variations": [variations.get(a) for a in annees_retenues[1:]],
            }
        )
    lignes.sort(key=lambda l: l["categorie"])

    totaux_generaux = {
        annee: sum((l["totaux"][annee] for l in lignes), Decimal("0")) for annee in annees_retenues
    }
    variations_generales = _variations(totaux_generaux)

    annee_courante = date.today().year
    avertissement = None
    mois_saisis = 12
    if annee_courante in annees_retenues:
        mois_saisis = (
            Recette.objects.filter(mois__year=annee_courante)
            .values_list("mois", flat=True)
            .distinct()
            .count()
        )
        if mois_saisis < 12:
            avertissement = annee_courante

    derniere = annees_retenues[-1]
    facteur = Decimal(12) / Decimal(mois_saisis) if avertissement and mois_saisis else Decimal(1)
    for l in lignes:
        l["projection"] = (l["totaux"][derniere] * facteur).quantize(Decimal("1"))
        precedent = l["totaux"].get(annees_retenues[-2]) if len(annees_retenues) > 1 else None
        l["tendance"] = (
            round(float((l["projection"] - precedent) / precedent * 100), 1) if precedent else None
        )
    par_chapitre = {}
    for l in lignes:
        c = par_chapitre.setdefault(l["chapitre"], {"chapitre": l["chapitre"], "totaux": {a: Decimal("0") for a in annees_retenues}})
        for a in annees_retenues:
            c["totaux"][a] += l["totaux"][a]
    lignes_chapitres = []
    for code in sorted(par_chapitre):
        c = par_chapitre[code]
        c["variations"] = _variations(c["totaux"])
        c["projection"] = (c["totaux"][derniere] * facteur).quantize(Decimal("1"))
        prec = c["totaux"].get(annees_retenues[-2]) if len(annees_retenues) > 1 else None
        c["tendance"] = round(float((c["projection"] - prec) / prec * 100), 1) if prec else None
        lignes_chapitres.append(c)
    projection_totale = (totaux_generaux[derniere] * facteur).quantize(Decimal("1"))
    precedent_total = totaux_generaux.get(annees_retenues[-2]) if len(annees_retenues) > 1 else None
    tendance_totale = (
        round(float((projection_totale - precedent_total) / precedent_total * 100), 1)
        if precedent_total else None
    )

    return {
        "annees": annees_retenues,
        "annees_comparees": annees_retenues[1:],
        "lignes": lignes,
        "lignes_chapitres": lignes_chapitres,
        "totaux_generaux": totaux_generaux,
        "variations_generales": variations_generales,
        "cellules_totaux_generaux": [totaux_generaux[a] for a in annees_retenues],
        "cellules_variations_generales": [variations_generales.get(a) for a in annees_retenues[1:]],
        "avertissement_annee_partielle": avertissement,
        "mois_saisis": mois_saisis,
        "projection_totale": projection_totale,
        "tendance_totale": tendance_totale,
        "nb_categories": Categorie.objects.count(),
    }

def _pied_de_page(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, 1.25 * cm, A4[0] - doc.rightMargin, 1.25 * cm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(doc.leftMargin, 0.8 * cm, "PréviRecettes · Montants en Ariary (Ar)")
    canvas.drawRightString(A4[0] - doc.rightMargin, 0.8 * cm, f"Page {doc.page}")
    canvas.restoreState()

def generer_rapport_pdf(type_doc: str = "LIASSE", annee: int | None = None) -> BytesIO:
    parametres = ParametrageSysteme.charger()
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2.2 * cm, bottomMargin=1.8 * cm,
        title="Rapport des recettes",
        author="PréviRecettes",
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="PdfTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=18, leading=22, textColor=colors.HexColor("#17202A"),
        alignment=TA_LEFT, spaceAfter=5,
    ))
    styles.add(ParagraphStyle(
        name="PdfMeta", parent=styles["Normal"], fontName="Helvetica",
        fontSize=8.5, leading=11, textColor=colors.HexColor("#64748B"),
        spaceAfter=14,
    ))
    styles.add(ParagraphStyle(
        name="PdfHeading", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=11, leading=14, textColor=colors.HexColor("#047857"),
        spaceBefore=7, spaceAfter=7,
    ))
    styles.add(ParagraphStyle(
        name="PdfNote", parent=styles["Italic"], fontName="Helvetica-Oblique",
        fontSize=8, leading=10, textColor=colors.HexColor("#64748B"),
    ))
    elements = []

    titres = {"LIASSE": "Liasse mensuelle — Exécution des recettes", "SYNTHESE": "Synthèse analytique des recettes", "ANOMALIES": "État des anomalies de recouvrement"}
    elements.append(Paragraph(titres.get(type_doc, titres["LIASSE"]), styles["PdfTitle"]))
    elements.append(Paragraph(f"Repoblikan'i Madagasikara · Généré le {date.today():%d/%m/%Y}" + (f" · Exercice {annee}" if annee else ""), styles["PdfMeta"]))

    if type_doc == "ANOMALIES":
        _section_anomalies(elements, styles)
        doc.build(elements, onFirstPage=_pied_de_page, onLaterPages=_pied_de_page)
        buffer.seek(0)
        return buffer

    elements.append(Paragraph("Dernières recettes enregistrées", styles["PdfHeading"]))
    donnees = [["Mois", "Catégorie", "Secteur", "Montant (Ar)"]]
    recettes_qs = Recette.objects.select_related("categorie", "secteur").order_by("-mois", "-id")
    if annee:
        recettes_qs = recettes_qs.filter(mois__year=annee)
    for r in recettes_qs[:20]:
        donnees.append([r.mois.strftime("%m/%Y"), r.categorie.nom, r.secteur.nom, ar(r.montant)])
    if len(donnees) == 1:
        donnees.append(["—", "Aucune donnée", "—", "—"])
    table = _tableau(donnees, [2.1 * cm, 6.1 * cm, 4.1 * cm, 3.2 * cm])
    table.setStyle(_style_tableau())
    elements.append(table)
    elements.append(Spacer(1, 1 * cm))

    elements.append(Paragraph("Comparaison entre exercices budgétaires", styles["PdfHeading"]))
    comparaison = comparaison_exercices()
    if comparaison["annees"]:
        entete = ["Catégorie"] + [str(a) + " (Ar)" for a in comparaison["annees"]]
        entete += [f"Var. {a}" for a in comparaison["annees"][1:]]
        donnees = [entete]
        for ligne in comparaison["lignes"]:
            rangee = [ligne["categorie"]]
            rangee += [ar(ligne['totaux'][a]) for a in comparaison["annees"]]
            rangee += [
                "—" if ligne["variations"].get(a) is None else f"{ligne['variations'][a]:+.1f} %"
                for a in comparaison["annees"][1:]
            ]
            donnees.append(rangee)
        rangee_totale = ["TOTAL"]
        rangee_totale += [ar(comparaison['totaux_generaux'][a]) for a in comparaison["annees"]]
        rangee_totale += [
            "—" if comparaison["variations_generales"].get(a) is None
            else f"{comparaison['variations_generales'][a]:+.1f} %"
            for a in comparaison["annees"][1:]
        ]
        donnees.append(rangee_totale)
        table = _tableau(donnees, [5.2 * cm] + [2.35 * cm] * (len(donnees[0]) - 1))
        table.setStyle(_style_tableau())
        elements.append(table)
        if comparaison["avertissement_annee_partielle"]:
            elements.append(Spacer(1, 0.3 * cm))
            elements.append(Paragraph(
                f"Note : l'exercice {comparaison['avertissement_annee_partielle']} est encore incomplet ; "
                "les variations le concernant sont donc à lire avec prudence.",
                styles["PdfNote"],
            ))
    else:
        elements.append(Paragraph("Aucune donnée exploitable.", styles["PdfNote"]))
    elements.append(Spacer(1, 1 * cm))

    elements.append(Paragraph("Recouvrement par secteur (12 derniers mois)", styles["PdfHeading"]))
    suivi = recouvrement_par_secteur(annee=annee)
    donnees = [["Secteur", "Total encaissé (Ar)", "Part", "Anomalies ouvertes"]]
    for ligne in suivi["lignes"]:
        donnees.append([
            ligne["secteur"].nom, ar(ligne['total']),
            f"{ligne['part_pct']:.1f} %", str(ligne["anomalies_ouvertes"]),
        ])
    if len(donnees) == 1:
        donnees.append(["—", "Aucune donnée", "—", "—"])
    table = _tableau(donnees, [4.7 * cm, 4.2 * cm, 2.1 * cm, 4 * cm])
    table.setStyle(_style_tableau())
    elements.append(table)
    elements.append(Spacer(1, 1 * cm))

    elements.append(Paragraph("Écarts entre objectifs budgétaires votés et réalisé", styles["PdfHeading"]))
    ecarts = calculer_ecarts(annee)
    donnees = [["Mois", "Catégorie", "Objectif voté (Ar)", "Réalisé (Ar)", "Écart (%)"]]
    for e in ecarts[:20]:
        donnees.append([
            e.mois.strftime("%m/%Y"), e.categorie, ar(e.cible),
            ar(e.realise), f"{e.ecart_pct:+.1f} %",
        ])
    if len(donnees) == 1:
        donnees.append(["—", "Aucun objectif défini", "—", "—", "—"])
    table = _tableau(donnees, [2.1 * cm, 5.3 * cm, 3.3 * cm, 3.3 * cm, 2.4 * cm])
    table.setStyle(_style_tableau())
    elements.append(table)
    elements.append(Spacer(1, 1 * cm))

    elements.append(Paragraph(
        f"Prévisions statistiques à {parametres.mois_a_prevoir} mois "
        "(régression + ajustement saisonnier)", styles["Heading2"]
    ))
    elements.append(Paragraph(
        "Ces montants sont <b>calculés</b> à partir de l'historique. Ils ne doivent pas être "
        "confondus avec les objectifs budgétaires du tableau précédent, qui sont <b>votés</b> "
        "et saisis manuellement.", styles["PdfNote"]
    ))
    elements.append(Spacer(1, 0.4 * cm))
    previsions = previsions_par_categorie()
    for serie in previsions.values():
        elements.append(Paragraph(serie["label"], styles["Heading3"]))
        donnees = [
            ["Mois"] + serie["mois_prevus"],
            ["Montant prévu (Ar)"] + [ar(v) for v in serie["montants_prevus"]],
        ]
        table = _tableau(donnees, [2.3 * cm] + [1.2 * cm] * len(serie["mois_prevus"]), compact=True)
        table.setStyle(_style_tableau())
        elements.append(table)
        elements.append(Spacer(1, 0.5 * cm))

    doc.build(elements, onFirstPage=_pied_de_page, onLaterPages=_pied_de_page)
    buffer.seek(0)
    return buffer

def _section_anomalies(elements, styles):
    from .models import Anomalie

    elements.append(Paragraph("Anomalies de recouvrement", styles["PdfHeading"]))
    donnees = [["Réf.", "Secteur", "Motif", "Montant (Ar)", "Échéance", "Statut"]]
    for a in Anomalie.objects.select_related("secteur", "categorie").filter(brouillon=False):
        donnees.append([
            a.reference, a.secteur.nom, a.get_motif_display(), ar(a.montant),
            f"{a.date_echeance:%d/%m/%Y}" if a.date_echeance else "—", a.statut,
        ])
    if len(donnees) == 1:
        donnees.append(["—", "Aucune anomalie", "—", "—", "—", "—"])
    table = _tableau(donnees, [2.2 * cm, 3.5 * cm, 4.1 * cm, 2.7 * cm, 2.3 * cm, 2.4 * cm])
    table.setStyle(_style_tableau())
    elements.append(table)


def generer_rapport_xlsx(type_doc: str = "LIASSE", annee: int | None = None) -> BytesIO:
    """Version tableur (.xlsx) : recettes de l'exercice, ou anomalies."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    from .models import Anomalie

    wb = Workbook()
    ws = wb.active
    if type_doc == "ANOMALIES":
        ws.title = "Anomalies"
        ws.append(["Référence", "Secteur", "Compte", "Motif", "Montant (Ar)", "Date de constat", "Échéance", "Statut"])
        for a in Anomalie.objects.select_related("secteur", "categorie").filter(brouillon=False):
            ws.append([a.reference, a.secteur.nom, a.categorie.libelle_complet, a.get_motif_display(),
                       float(a.montant), a.date_constat, a.date_echeance, a.statut])
    else:
        ws.title = "Recettes"
        ws.append(["Référence", "Date", "Chapitre", "Compte", "Secteur", "Mode", "Montant (Ar)", "Libellé"])
        qs = Recette.objects.select_related("categorie", "secteur").order_by("date_imputation", "id")
        if annee:
            qs = qs.filter(mois__year=annee)
        for r in qs:
            ws.append([r.reference, r.date_imputation, r.categorie.chapitre, r.categorie.libelle_complet,
                       r.secteur.nom, r.get_mode_reglement_display(), float(r.montant), r.libelle])
    for cellule in ws[1]:
        cellule.font = Font(bold=True, color="FFFFFF")
        cellule.fill = PatternFill("solid", fgColor="25272C")
    for colonne in ws.columns:
        ws.column_dimensions[colonne[0].column_letter].width = max(12, min(45, max(len(str(c.value or "")) for c in colonne) + 2))
    tampon = BytesIO()
    wb.save(tampon)
    tampon.seek(0)
    return tampon

def _tableau(donnees, largeurs, compact=False):
    taille = 6.2 if compact else 7.4
    interligne = 7.4 if compact else 9
    cellules = []
    for index_ligne, ligne in enumerate(donnees):
        style = ParagraphStyle(
            name=f"PdfCell{index_ligne}{compact}",
            fontName="Helvetica-Bold" if index_ligne == 0 else "Helvetica",
            fontSize=taille,
            leading=interligne,
            textColor=colors.white if index_ligne == 0 else colors.HexColor("#25313C"),
            alignment=TA_CENTER if index_ligne == 0 else TA_LEFT,
        )
        cellules.append([
            cell if isinstance(cell, Paragraph) else Paragraph(escape(str(cell)).replace("\n", "<br/>"), style)
            for cell in ligne
        ])
    tableau = Table(cellules, colWidths=largeurs, repeatRows=1, hAlign="LEFT")
    tableau.setStyle(_style_tableau())
    return tableau

def _style_tableau():
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#25272C")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#10B981")),
            ("GRID", (0, 1), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]
    )
