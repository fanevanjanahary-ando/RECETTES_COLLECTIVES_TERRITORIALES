"""Formats d'affichage en Ariary (Ar) — utilisés par les gabarits, les PDF, les CSV et les e-mails."""
from decimal import Decimal

NBSP = "\u202f"


def nombre(valeur, decimales: int = 0) -> str:
    if valeur is None or valeur == "":
        return "—"
    try:
        v = Decimal(str(valeur))
    except Exception:
        return str(valeur)
    texte = f"{abs(v):,.{decimales}f}".replace(",", NBSP).replace(".", ",")
    return ("-" if v < 0 and float(abs(v)) >= 0.5 * 10 ** (-decimales) else "") + texte


def ar(valeur, decimales: int = 0) -> str:
    return "—" if valeur is None else f"{nombre(valeur, decimales)} Ar"


def kar(valeur) -> str:
    if valeur is None:
        return "—"
    return f"{nombre(Decimal(str(valeur)) / 1000)} kAr"


def pct(valeur, decimales: int = 1, signe: bool = False) -> str:
    if valeur is None:
        return "—"
    texte = f"{abs(float(valeur)):.{decimales}f}".replace(".", ",")
    prefixe = "-" if float(valeur) < 0 else ("+" if signe else "")
    return f"{prefixe}{texte} %"
