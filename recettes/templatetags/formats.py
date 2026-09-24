import json
from datetime import date, datetime

from django import template
from django.utils.safestring import mark_safe

from .. import formats

register = template.Library()

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
        "septembre", "octobre", "novembre", "décembre"]
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]


@register.filter
def ariary(valeur, decimales=0):
    return formats.ar(valeur, int(decimales))


@register.filter
def nombre(valeur, decimales=0):
    return formats.nombre(valeur, int(decimales))


@register.filter
def kariary(valeur):
    return formats.kar(valeur)


@register.filter
def pourcent(valeur, decimales=1):
    return formats.pct(valeur, int(decimales))


@register.filter
def pourcent_signe(valeur, decimales=1):
    return formats.pct(valeur, int(decimales), signe=True)


@register.filter
def mois_fr(valeur):
    if isinstance(valeur, str) and len(valeur) >= 7:
        valeur = date(int(valeur[:4]), int(valeur[5:7]), 1)
    return f"{MOIS[valeur.month - 1]} {valeur.year}" if valeur else ""


@register.filter
def mois_court(valeur):
    return f"{MOIS_COURTS[valeur.month - 1]} {valeur.year}" if valeur else ""


@register.filter
def date_fr(valeur):
    if isinstance(valeur, datetime):
        valeur = valeur.date()
    return f"{valeur.day:02d} {MOIS[valeur.month - 1]} {valeur.year}" if valeur else ""


@register.filter
def date_num(valeur):
    return f"{valeur:%d/%m/%Y}" if valeur else ""


@register.filter
def jour_heure(valeur):
    return f"{valeur:%d/%m %H:%M}" if valeur else ""


@register.filter
def json_script_safe(valeur):
    return mark_safe(json.dumps(valeur, default=str).replace("<", "\\u003c"))


@register.filter
def get_item(dico, cle):
    try:
        return dico.get(cle)
    except AttributeError:
        return None


@register.filter
def signe_classe(valeur):
    try:
        return "neg" if float(valeur) < 0 else "pos"
    except (TypeError, ValueError):
        return ""


@register.simple_tag
def largeur(valeur, total=100):
    try:
        return f"{max(0, min(100, float(valeur) / float(total) * 100)):.1f}".replace(",", ".")
    except (TypeError, ValueError, ZeroDivisionError):
        return "0"


@register.simple_tag(takes_context=True)
def est_actif(context, noms):
    match = getattr(context.get("request"), "resolver_match", None)
    return bool(match and match.url_name in noms.split())


@register.filter
def duree(valeur):
    """Écart depuis une date/heure, en une seule unité : « 8 min », « 4 h », « 3 j »."""
    from django.utils import timezone

    if not valeur:
        return ""
    secondes = int((timezone.now() - valeur).total_seconds())
    if secondes < 90:
        return "1 min"
    if secondes < 3600:
        return f"{secondes // 60} min"
    if secondes < 86400:
        return f"{secondes // 3600} h"
    return f"{secondes // 86400} j"
