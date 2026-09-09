"""Haalt gewichten en RPE uit de vrije notities bij een Hevy-oefening.

Hevy kan niet alles vastleggen. Een plate loaded knee raise heeft er geen
gewichtsveld voor, en het RPE-veld begint pas bij 6, dus RPE 5 past er niet in.
Dylan schrijft dat dan in de notitie:

    "+10 bij de eerste 0 bij de tweede +5 bij de laatste"
    "Beide rpe 5, maar kan dat niet invullen"
    "Ik deed rpe 5 -6,5 -"

Die notities zijn dus geen bijzaak maar dragen data die nergens anders staat.
Deze module leest ze uit.

UITGANGSPUNT
Vrije tekst laat zich niet betrouwbaar ontleden. Daarom geldt: wat hier met
zekerheid uit te halen is, wordt gebruikt; de rest wordt niet geraden maar
letterlijk doorgegeven, zodat de coach het zelf leest. Liever een notitie die
een mens moet interpreteren dan een getal dat verzonnen is.
"""

import re

ORDINAAL = {
    "eerste": 0, "1e": 0, "1ste": 0,
    "tweede": 1, "2e": 1, "2de": 1,
    "derde": 2, "3e": 2, "3de": 2,
    "vierde": 3, "4e": 3,
    "vijfde": 4, "5e": 4,
}
LAATSTE = ("laatste", "leste")


def lees_rpes(tekst):
    """Alle RPE-waarden die in de notitie genoemd worden, op volgorde.

    Herkent 'rpe 5', 'rpe 5 -6,5 -', 'beide rpe 5'. Geeft ook terug of het
    om alle sets ging ('beide', 'alle'), want dan geldt één waarde voor elke set.
    """
    if not tekst:
        return [], False
    t = tekst.lower()
    if "rpe" not in t:
        return [], False

    # Neem het deel vanaf het eerste 'rpe' en lees de getallen die volgen.
    staart = t[t.index("rpe"):]
    # Stop bij een zin die duidelijk over iets anders gaat.
    staart = re.split(r"\bmaar\b|\bomdat\b|\bkan dat niet\b", staart)[0]
    getallen = re.findall(r"\b(\d{1,2})(?:[.,](\d))?\b", staart)
    uit = []
    for heel, decimaal in getallen:
        waarde = float(f"{heel}.{decimaal}") if decimaal else float(heel)
        if 1 <= waarde <= 10:
            uit.append(waarde)
    alle = any(w in t for w in ("beide", "alle", "allebei", "elke set"))
    return uit, alle


def lees_setgewichten(tekst, aantal_sets):
    """Per-set gewichten uit een notitie met rangtelwoorden.

    Bijvoorbeeld: '+10 bij de eerste 0 bij de tweede +5 bij de laatste'
    geeft bij drie sets [10.0, 0.0, 5.0].

    Geeft None terug zodra het niet eenduidig is. Half raden is hier erger dan
    niets doen: een verkeerd gewicht in het logboek van de coach is stiller en
    schadelijker dan een lege cel.
    """
    if not tekst or aantal_sets < 1:
        return None
    t = tekst.lower()
    if not re.search(r"[+-]?\d", t):
        return None

    # Zoek paren van (getal, rangtelwoord) in de volgorde waarin ze staan.
    patroon = re.compile(
        r"([+-]?\d{1,3}(?:[.,]\d)?)\s*(?:kg)?\s*(?:bij|op|voor)?\s*(?:de\s+)?"
        r"(eerste|1e|1ste|tweede|2e|2de|derde|3e|3de|vierde|4e|vijfde|5e|laatste|leste)")
    treffers = patroon.findall(t)
    if len(treffers) < 2:
        return None

    gewichten = [None] * aantal_sets
    for getal, woord in treffers:
        index = aantal_sets - 1 if woord in LAATSTE else ORDINAAL.get(woord)
        if index is None or index >= aantal_sets:
            return None
        gewichten[index] = float(getal.replace(",", ".").lstrip("+"))

    if any(g is None for g in gewichten):
        return None
    return gewichten


def samenvatting(tekst, limiet=180):
    """De notitie zelf, ingekort, om letterlijk in de Sheet te zetten."""
    if not tekst:
        return ""
    schoon = " ".join(str(tekst).split())
    return schoon if len(schoon) <= limiet else schoon[:limiet - 1] + "…"
