"""Graphiques SVG générés côté serveur, avec exactement le style du design (aucune bibliothèque JS)."""
from django.utils.safestring import mark_safe

from .formats import nombre

COULEURS_ANNEES = ["#CBD5E1", "#25272C", "#5EEAD4", "#0D9488", "#94A3B8"]


def _echelle(valeurs, y_bas, y_haut):
    valeurs = [v for v in valeurs if v is not None]
    mini, maxi = (min(valeurs), max(valeurs)) if valeurs else (0, 1)
    if maxi == mini:
        maxi, mini = maxi + 1, mini - 1
    marge = (maxi - mini) * 0.08
    mini, maxi = mini - marge, maxi + marge
    return lambda v: y_bas - (v - mini) / (maxi - mini) * (y_bas - y_haut)


def _pts(points):
    return " ".join(f"{x:.0f},{y:.0f}" for x, y in points)


def _mega(v):
    return f"{nombre(v / 1_000_000, 1)} M Ar"


def svg_trajectoire(serie: dict, max_hist: int = 12):
    """Historique réalisé + projection prédictive (viewBox 500 x 160)."""
    hist = serie["montants_historique"][-max_hist:]
    prev = serie["montants_prevus"]
    if len(hist) < 2:
        return ""
    y = _echelle(hist + prev, 130, 20)
    x0, xc, xf = 30, 340, 480
    pas = (xc - x0) / (len(hist) - 1)
    ph = [(x0 + i * pas, y(v)) for i, v in enumerate(hist)]
    pp = [(xc, y(hist[-1]))]
    if prev:
        pas_p = (xf - xc) / len(prev)
        pp += [(xc + (i + 1) * pas_p, y(v)) for i, v in enumerate(prev)]
    haut = [(px, py - (i / max(len(pp) - 1, 1)) * 14) for i, (px, py) in enumerate(pp)]
    bas = [(px, py + (i / max(len(pp) - 1, 1)) * 14) for i, (px, py) in enumerate(pp)]
    cone = _pts(haut + bas[::-1])
    d_hist = "M " + " L ".join(f"{px:.0f},{py:.0f}" for px, py in ph)
    d_prev = "M " + " L ".join(f"{px:.0f},{py:.0f}" for px, py in pp)
    fin = pp[-1]
    return mark_safe(
        '<svg class="w-full h-full" fill="none" preserveAspectRatio="none" viewBox="0 0 500 160">'
        '<line stroke="#F1F5F9" stroke-width="1" x1="20" x2="480" y1="30" y2="30"></line>'
        '<line stroke="#F1F5F9" stroke-width="1" x1="20" x2="480" y1="80" y2="80"></line>'
        '<line stroke="#F1F5F9" stroke-width="1" x1="20" x2="480" y1="130" y2="130"></line>'
        f'<polygon fill="#B8F7E4" fill-opacity="0.35" points="{cone}"></polygon>'
        f'<path d="{d_hist}" fill="none" stroke="#1E2024" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path>'
        f'<path d="{d_prev}" fill="none" stroke="#10B981" stroke-dasharray="4 4" stroke-linecap="round" stroke-width="2"></path>'
        f'<circle cx="{xc}" cy="{pp[0][1]:.0f}" fill="#1E2024" r="3.5"></circle>'
        f'<circle cx="{fin[0]:.0f}" cy="{fin[1]:.0f}" fill="#B8F7E4" r="4" stroke="#10B981" stroke-width="2"></circle>'
        "</svg>"
    )


def svg_focus(historique: list, cible: float, prevus: list, ecart_pct: float | None):
    """Zoom sur le compte au plus fort écart : historique, objectif voté, rebond estimé (500 x 160)."""
    hist = historique[-6:]
    if len(hist) < 2 or not cible:
        return ""
    y = _echelle(hist + prevus[:2] + [cible], 135, 25)
    pas = (380 - 30) / (len(hist) - 1)
    ph = [(30 + i * pas, y(v)) for i, v in enumerate(hist)]
    d_hist = "M " + " L ".join(f"{px:.0f},{py:.0f}" for px, py in ph)
    dernier = ph[-1]
    yc = y(cible)
    reb = [dernier] + [(430 + i * 50, y(v)) for i, v in enumerate(prevus[:2])]
    d_reb = "M " + " L ".join(f"{px:.0f},{py:.0f}" for px, py in reb)
    signe = f"{ecart_pct:+.1f}".replace(".", ",") if ecart_pct is not None else ""
    couleur = "#EF4444" if (ecart_pct or 0) < 0 else "#10B981"
    texte_c = "#DC2626" if (ecart_pct or 0) < 0 else "#059669"
    fin = reb[-1]
    return mark_safe(
        '<svg class="w-full h-full" fill="none" preserveAspectRatio="none" viewBox="0 0 500 160">'
        '<line stroke="#F1F5F9" stroke-width="1" x1="20" x2="480" y1="30" y2="30"></line>'
        '<line stroke="#F1F5F9" stroke-width="1" x1="20" x2="480" y1="80" y2="80"></line>'
        '<line stroke="#F1F5F9" stroke-width="1" x1="20" x2="480" y1="130" y2="130"></line>'
        f'<line stroke="#CBD5E1" stroke-dasharray="3 3" stroke-width="1.5" x1="30" x2="480" y1="{yc:.0f}" y2="{yc:.0f}"></line>'
        f'<text class="text-[10px] font-mono" fill="#9CA3AF" x="32" y="{yc - 5:.0f}">Objectif voté : {_mega(cible)}</text>'
        f'<path d="{d_hist}" fill="none" stroke="#1E2024" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path>'
        f'<circle cx="{dernier[0]:.0f}" cy="{dernier[1]:.0f}" fill="{couleur}" r="4"></circle>'
        f'<text class="text-[10px] font-mono font-bold" fill="{texte_c}" x="{min(dernier[0] + 5, 300):.0f}" y="{min(dernier[1] + 16, 152):.0f}">{_mega(hist[-1])} ({signe}%)</text>'
        f'<path d="{d_reb}" fill="none" stroke="#10B981" stroke-dasharray="4 4" stroke-linecap="round" stroke-width="2"></path>'
        f'<circle cx="{fin[0]:.0f}" cy="{fin[1]:.0f}" fill="#10B981" r="3.5"></circle>'
        "</svg>"
    )


def svg_projection(realise: list, objectif: list, prevision: list):
    """Trajectoire d'atterrissage (320 x 100). Listes de 6 valeurs (None si absent)."""
    tous = [v for v in realise + objectif + prevision if v is not None]
    if len(tous) < 2:
        return ""
    y = _echelle(tous, 88, 12)
    xs = [10 + i * 60 for i in range(6)]
    poly = lambda vals: [(x, y(v)) for x, v in zip(xs, vals) if v is not None]
    pr, ob, re_ = poly(prevision), poly(objectif), poly(realise)
    bande = ""
    if len(pr) >= 2:
        haut = [(x, py - 7) for x, py in pr]
        bas = [(x, py + 7) for x, py in pr]
        bande = f'<polygon class="fill-[#B8F7E4]/40" points="{_pts(haut + bas[::-1])}"></polygon>'
    ligne_obj = f'<polyline points="{_pts(ob)}" stroke="#717886" stroke-dasharray="3 3" stroke-width="1.5"></polyline>' if len(ob) >= 2 else ""
    ligne_re = f'<polyline points="{_pts(re_)}" stroke="#1E2024" stroke-linecap="round" stroke-width="2"></polyline>' if len(re_) >= 2 else ""
    point = f'<circle class="fill-rose-500 stroke-white" cx="{re_[-1][0]:.0f}" cy="{re_[-1][1]:.0f}" r="4" stroke-width="2"></circle>' if re_ else ""
    return mark_safe(
        f'<svg class="w-full h-full" fill="none" preserveAspectRatio="none" viewBox="0 0 320 100">{bande}{ligne_obj}{ligne_re}{point}</svg>'
    )


def svg_barres(groupes: list, nb_series: int):
    """Barres groupées (720 x 200) : chaque groupe = {"valeurs": [v_annee1, v_annee2, ...]}."""
    if not groupes:
        return ""
    maxi = max((v or 0) for g in groupes for v in g["valeurs"]) or 1
    largeur_groupe = 720 / len(groupes)
    largeur_barres = nb_series * 33 - 5
    barres = []
    for gi, g in enumerate(groupes):
        depart = gi * largeur_groupe + (largeur_groupe - largeur_barres) / 2
        for si, v in enumerate(g["valeurs"]):
            h = max(2, (v or 0) / maxi * 155)
            barres.append(
                f'<rect fill="{COULEURS_ANNEES[si % len(COULEURS_ANNEES)]}" height="{h:.0f}" rx="2" width="28" '
                f'x="{depart + si * 33:.0f}" y="{180 - h:.0f}"></rect>'
            )
    return mark_safe(
        '<svg class="w-full h-full" fill="none" preserveAspectRatio="none" viewBox="0 0 720 200" xmlns="http://www.w3.org/2000/svg">'
        '<line class="text-graphite-100" stroke="currentColor" stroke-dasharray="4 4" stroke-width="1" x1="0" x2="720" y1="20" y2="20"></line>'
        '<line class="text-graphite-100" stroke="currentColor" stroke-dasharray="4 4" stroke-width="1" x1="0" x2="720" y1="70" y2="70"></line>'
        '<line class="text-graphite-100" stroke="currentColor" stroke-dasharray="4 4" stroke-width="1" x1="0" x2="720" y1="120" y2="120"></line>'
        '<line class="text-graphite-200" stroke="currentColor" stroke-width="1" x1="0" x2="720" y1="180" y2="180"></line>'
        + "".join(barres) + "</svg>"
    )


def svg_donut(parts: list):
    """Anneau de répartition (100 x 100). parts = [(pourcentage, couleur)]."""
    perimetre = 238.76
    cercles, decalage = [], 0.0
    for pct, couleur in parts:
        longueur = max(0.0, pct) / 100 * perimetre
        cercles.append(
            f'<circle cx="50" cy="50" fill="transparent" r="38" stroke="{couleur}" '
            f'stroke-dasharray="{longueur:.1f} {perimetre}" stroke-dashoffset="-{decalage:.1f}" stroke-width="12"></circle>'
        )
        decalage += longueur
    return mark_safe(
        '<svg class="w-44 h-44 transform -rotate-90" viewBox="0 0 100 100">'
        '<circle class="text-graphite-100" cx="50" cy="50" fill="transparent" r="38" stroke="currentColor" stroke-width="12"></circle>'
        + "".join(cercles) + "</svg>"
    )


def svg_sparkline(valeurs: list):
    """Petite courbe (280 x 48) de l'historique pluriannuel."""
    if len(valeurs) < 2:
        return ""
    y = _echelle(valeurs, 42, 8)
    pas = 280 / (len(valeurs) - 1)
    pts = [(i * pas, y(v)) for i, v in enumerate(valeurs)]
    d = "M" + " L".join(f"{x:.0f} {yy:.0f}" for x, yy in pts)
    return mark_safe(
        '<svg class="w-full h-11 text-emerald-600" fill="none" preserveAspectRatio="none" viewBox="0 0 280 48">'
        f'<path d="{d}" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2"></path>'
        f'<circle cx="{pts[-1][0]:.0f}" cy="{pts[-1][1]:.0f}" fill="currentColor" r="3.5"></circle></svg>'
    )
