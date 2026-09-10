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


def corrigeert_veld(tekst):
    """Zegt de notitie expliciet dat het veld in Hevy niet klopte?

    'Beide rpe 5, maar kan dat niet invullen' is geen aanvulling maar een
    correctie: het RPE-veld begint bij 6, dus wat er staat is niet wat hij
    voelde. In dat geval wint de notitie van het veld.
    """
    if not tekst:
        return False
    t = tekst.lower()
    return any(z in t for z in (
        "kan dat niet invullen", "kan ik niet invullen", "kon dat niet",
        "kon ik niet", "kan niet invullen", "gaat niet in hevy", "past niet"))


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


TELWOORD = {"een": 1, "één": 1, "1": 1, "twee": 2, "2": 2, "drie": 3, "3": 3,
            "vier": 4, "4": 4, "vijf": 5, "5": 5}


def rpe_toewijzing(tekst, aantal_sets, gelogd):
    """Welke RPE hoort bij welke set, gelezen uit de notitie.

    Het RPE-veld in Hevy begint bij 6, dus alles daaronder schrijft Dylan in de
    notitie. Die notitie wint dan van het veld. Maar waar hij het over heeft
    verschilt per zin, en dat verschil is niet cosmetisch:

        "Rpe 5 bij beide"                -> elke set 5
        "Laatste twee sets waren op rpe 5" -> alleen de laatste twee
        "Ik deed rpe 5 -6,5 -"           -> set 1 op 5, set 2 op 6,5, rest blijft
        "Rpe 5"                          -> de hele oefening op 5

    Eerder werd alles vanaf set 1 geteld. Bij "laatste twee" belandde de 5 dus
    op de eerste set, precies de sets waar hij het niet over had. Posities die
    de notitie niet noemt houden hun gelogde waarde.
    """
    uit = list(gelogd)
    if not tekst or aantal_sets < 1:
        return uit
    rpes, _ = lees_rpes(tekst)
    if not rpes:
        return uit
    t = tekst.lower()

    # "+10 bij de eerste ... bij de laatste": expliciet per set.
    paren = re.findall(
        r"(\d{1,2}(?:[.,]\d)?)\s*(?:bij|op|voor)?\s*(?:de\s+)?"
        r"(eerste|1e|1ste|tweede|2e|2de|derde|3e|3de|vierde|4e|vijfde|5e|laatste|leste)", t)
    if len(paren) >= 2 and "rpe" in t:
        for getal, woord in paren:
            i = aantal_sets - 1 if woord in LAATSTE else ORDINAAL.get(woord)
            waarde = float(getal.replace(",", "."))
            if i is not None and i < aantal_sets and 1 <= waarde <= 10:
                uit[i] = waarde
        return uit

    # "laatste twee", "eerste drie": een aaneengesloten staart of kop.
    staart = re.search(r"\blaatste\s+(\w+)", t)
    kop = re.search(r"\beerste\s+(\w+)", t)
    for m, vanaf_achter in ((staart, True), (kop, False)):
        if not m:
            continue
        n = TELWOORD.get(m.group(1))
        if not n:
            continue
        n = min(n, aantal_sets)
        posities = range(aantal_sets - n, aantal_sets) if vanaf_achter else range(n)
        for j, i in enumerate(posities):
            uit[i] = rpes[j] if j < len(rpes) else rpes[0]
        return uit

    # "beide", "alle", of één waarde zonder verdere aanduiding: geldt overal.
    if any(w in t for w in ("beide", "alle", "allebei", "elke set")) or len(rpes) == 1:
        return [rpes[0]] * aantal_sets

    # Anders op volgorde, vanaf de eerste set.
    for i in range(min(len(rpes), aantal_sets)):
        uit[i] = rpes[i]
    return uit
