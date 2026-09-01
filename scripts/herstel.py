"""Leest herstelgegevens uit wat je in Hevy noteert.

Slaap, stappen en vermoeidheid zeggen of een zware dag verstandig is: het
schema schrijft een gewicht voor, maar op vijf uur slaap is dat gewicht een
ander gewicht.

WAAROM HANDMATIG EN NIET UIT DE WATCH
De GARD PRO FIT-app draait op het GloryFit-platform (pakketnaam
com.yc.gloryfitpro.gardpro). Dat is een white-label basis achter veel
budget-smartwatches, zonder publieke API en zonder cloud-export. Er is dus
geen weg waarlangs een server die gegevens kan ophalen, hoe graag ook.

Wat wel werkt: je typt het in het beschrijvingsveld van je Hevy-sessie, of in
een notitie bij de eerste oefening. Dat veld komt via de Hevy API gewoon mee.
Vier tekens werk, en het voedt zowel het dagbericht als het weekrapport.

SCHRIJFWIJZE  (alles optioneel, volgorde maakt niet uit)

    slaap 6.5        uren, ook 6u30 of 6:30 mag
    stappen 8500     ook 8.5k
    moe 4            hoe vermoeid je je voelt, 1 = fris, 5 = gesloopt
    rust 52          rustpols
    kcal 2600        energie over de dag
    eiwit 150        gram eiwit

Bijvoorbeeld:  slaap 5u45 stappen 12000 moe 4 kcal 2700 eiwit 145

De Eetmeter van het Voedingscentrum heeft geen API, alleen een PDF- en
XML-export via de website. Twee getallen overtypen is minder werk dan wekelijks
een bestand exporteren, en voor dit doel is het genoeg: wat telt is of je
eiwit haalt en of je gewicht de goede kant op beweegt.

Staat er niets, dan gebeurt er niets. Herstelgegevens zijn een aanvulling,
geen voorwaarde.
"""

import re


def _uren(tekst):
    m = re.search(r"\bslaap\s*:?\s*(\d{1,2})[u:.,](\d{2})\b", tekst)
    if m:
        return round(int(m.group(1)) + int(m.group(2)) / 60, 2)
    m = re.search(r"\bslaap\s*:?\s*(\d{1,2}(?:[.,]\d)?)\s*(?:u|uur|h)?\b", tekst)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _stappen(tekst):
    m = re.search(r"\bstappen\s*:?\s*(\d{1,2}(?:[.,]\d)?)\s*k\b", tekst)
    if m:
        return int(float(m.group(1).replace(",", ".")) * 1000)
    m = re.search(r"\bstappen\s*:?\s*(\d{3,6})\b", tekst)
    return int(m.group(1)) if m else None


def lees(tekst):
    """Haalt slaap, stappen, vermoeidheid en rustpols uit een vrije tekst."""
    if not tekst:
        return {}
    t = tekst.lower()
    uit = {}

    slaap = _uren(t)
    if slaap is not None and 0 < slaap <= 14:
        uit["slaap_uren"] = slaap

    stappen = _stappen(t)
    if stappen is not None and stappen <= 100000:
        uit["stappen"] = stappen

    m = re.search(r"\b(?:moe|vermoeid|vermoeidheid)\s*:?\s*([1-5])\b", t)
    if m:
        uit["vermoeidheid"] = int(m.group(1))

    m = re.search(r"\b(?:rust|rustpols|rhr)\s*:?\s*(\d{2,3})\b", t)
    if m and 30 <= int(m.group(1)) <= 120:
        uit["rustpols"] = int(m.group(1))

    m = re.search(r"\b(?:kcal|calorieen|calorieën|energie)\s*:?\s*(\d{3,5})\b", t)
    if m and 800 <= int(m.group(1)) <= 8000:
        uit["kcal"] = int(m.group(1))

    m = re.search(r"\b(?:eiwit|eiwitten|protein)\s*:?\s*(\d{2,3})\b", t)
    if m and 20 <= int(m.group(1)) <= 400:
        uit["eiwit_gram"] = int(m.group(1))

    return uit


def uit_workout(workout):
    """Zoekt herstelgegevens in de beschrijving en anders in de notities."""
    gevonden = lees(workout.get("description") or "")
    if gevonden:
        return gevonden
    for oef in workout.get("exercises", []):
        gevonden = lees(oef.get("notes") or "")
        if gevonden:
            return gevonden
    return {}


def beoordeel(recent):
    """Vertaalt de recentste gegevens naar een advies over de belasting.

    Bewust adviserend en niet automatisch: het schema verlaagt zichzelf niet
    op een slechte nacht. Een korte nacht is normaal, pas een patroon telt.
    Twee signalen tegelijk is het omslagpunt.
    """
    if not recent:
        return {"signaal": "onbekend", "advies": None, "gebaseerd_op": None}

    redenen = []
    slaap = recent.get("slaap_uren")
    moe = recent.get("vermoeidheid")
    stappen = recent.get("stappen")

    if slaap is not None and slaap < 6:
        redenen.append(f"{slaap:g} uur slaap")
    if moe is not None and moe >= 4:
        redenen.append(f"vermoeidheid {moe} van 5")
    if stappen is not None and stappen > 15000:
        redenen.append(f"{stappen} stappen gisteren")
    eiwit = recent.get("eiwit_gram")
    if eiwit is not None and eiwit < 110:
        redenen.append(f"{eiwit} g eiwit, onder de ondergrens van 125")

    if len(redenen) >= 2:
        return {
            "signaal": "laag",
            "advies": "Behandel het RPE-plafond als bovengrens, niet als doel. "
                      "Voelt set drie al zwaarder dan gepland, laat de laatste vallen.",
            "gebaseerd_op": ", ".join(redenen),
        }
    if redenen:
        return {"signaal": "matig",
                "advies": "Neem een minuut extra rust tussen de kernsets.",
                "gebaseerd_op": ", ".join(redenen)}
    return {"signaal": "goed", "advies": None, "gebaseerd_op": None}
