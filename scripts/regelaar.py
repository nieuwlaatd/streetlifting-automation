"""Leest terugkoppeling uit Hevy en stelt de belasting per lift bij.

Het schema schrijft gewichten voor, maar of die kloppen blijkt pas in de gym.
Deze module vergelijkt het voorschrift van vorige keer met wat er werkelijk
gebeurde, en verschuift een correctiefactor per lift. Die factor werkt door in
elk volgend voorschrift, bovenop de normale blokopbouw.

Drie bronnen van terugkoppeling, in volgorde van betrouwbaarheid:

1. Het RPE-veld per set. Aanzetten in Hevy: Profiel > tandwiel >
   Workout Settings > RPE Tracking.
2. Een notitie bij de oefening. Schrijf "RPE 8" of "RIR 2", of gewoon
   Nederlands: "te zwaar", "gedropt", "makkelijk", "kon meer".
3. Wat er objectief gebeurde: alle voorgeschreven sets en reps gehaald op het
   voorgeschreven gewicht, of niet.

Bron 3 werkt altijd, ook zonder dat je iets invult.
"""

import re

# Hoeveel de correctiefactor per beoordeling verschuift.
STAP_OMHOOG = 1.025      # te makkelijk: 2,5 procent erbij
STAP_OMLAAG = 0.95       # te zwaar: 5 procent eraf, sneller terug dan vooruit
ONDERGRENS = 0.80
BOVENGRENS = 1.15

# Losse woorden zijn te grof ("zwaar" staat ook in "dip zwaar"), dus alleen
# formuleringen die eenduidig over de zwaarte van de set gaan.
TE_ZWAAR = [
    "te zwaar", "te moeilijk", "te veel", "gedropt", "dropped", "verlaagd",
    "niet gehaald", "niet gelukt", "lukte niet", "kon niet", "gefaald",
    "moest laten zakken", "haalde het niet", "was zwaar",
]
TE_MAKKELIJK = [
    "te makkelijk", "te licht", "makkelijk", "voelde licht", "kon meer",
    "meer gekund", "had meer gekund", "ging vlot", "ging soepel", "over",
]


def lees_notitie(tekst):
    """Haalt een RPE en/of een zwaartesignaal uit een vrije notitie."""
    if not tekst:
        return {"rpe": None, "signaal": None, "tekst": ""}
    t = tekst.lower()

    rpe = None
    m = re.search(r"\brpe\s*:?\s*(\d{1,2}(?:[.,]5)?)", t)
    if m:
        rpe = float(m.group(1).replace(",", "."))
    else:
        m = re.search(r"\brir\s*:?\s*(\d)", t)          # RIR 2 == RPE 8
        if m:
            rpe = 10.0 - float(m.group(1))
        else:
            m = re.search(r"@\s*(\d{1,2}(?:[.,]5)?)\b", t)
            if m:
                kandidaat = float(m.group(1).replace(",", "."))
                if 5 <= kandidaat <= 10:
                    rpe = kandidaat
    if rpe is not None:
        rpe = max(5.0, min(rpe, 10.0))

    signaal = None
    if any(w in t for w in TE_ZWAAR):
        signaal = "te_zwaar"
    elif any(w in t for w in TE_MAKKELIJK):
        signaal = "te_makkelijk"

    return {"rpe": rpe, "signaal": signaal, "tekst": tekst.strip()[:200]}


def beoordeel(voorschrift, sets, notitie):
    """Was de vorige sessie te zwaar, goed, of te makkelijk?

    voorschrift: dict met sets, reps, kg
    sets:        werksets van die dag, elk met weight_kg, reps, rpe, type
    notitie:     uitkomst van lees_notitie
    """
    if not voorschrift or not sets:
        return None, "geen vergelijkbare sessie gevonden"

    doel_kg = float(voorschrift["kg"])
    doel_reps = int(voorschrift["reps"])
    doel_sets = int(voorschrift["sets"])

    # Een set telt als gehaald bij minstens het voorgeschreven gewicht
    # (2 procent speling voor afronding op de stang) en de volle reps.
    gehaald = sum(
        1 for s in sets
        if float(s.get("weight_kg") or 0) >= doel_kg * 0.98
        and int(s.get("reps") or 0) >= doel_reps
    )
    zwaarder = any(float(s.get("weight_kg") or 0) > doel_kg * 1.02 for s in sets)
    rpes = [float(s["rpe"]) for s in sets if s.get("rpe") is not None]
    if notitie["rpe"] is not None:
        rpes.append(notitie["rpe"])
    hoogste_rpe = max(rpes) if rpes else None
    falen = any(s.get("type") == "failure" for s in sets)

    # Te zwaar wint altijd: liever een week te licht dan een blessure.
    if notitie["signaal"] == "te_zwaar":
        return "te_zwaar", "notitie meldt dat het te zwaar was"
    if hoogste_rpe is not None and hoogste_rpe >= 9.5:
        return "te_zwaar", f"RPE {hoogste_rpe:g} gelogd, boven het plafond"
    if gehaald <= doel_sets - 2:
        return "te_zwaar", f"{gehaald} van {doel_sets} sets gehaald"

    if notitie["signaal"] == "te_makkelijk":
        return "te_makkelijk", "notitie meldt dat het makkelijk ging"
    if gehaald >= doel_sets and hoogste_rpe is not None and hoogste_rpe <= 6.5:
        return "te_makkelijk", f"alles gehaald op RPE {hoogste_rpe:g}"
    if gehaald >= doel_sets and zwaarder and not falen:
        return "te_makkelijk", "zwaarder gedraaid dan voorgeschreven en gehaald"

    if gehaald >= doel_sets:
        return "goed", "voorschrift gehaald"
    return "goed", f"{gehaald} van {doel_sets} sets, binnen de marge"


def nieuwe_factor(huidig, oordeel):
    if oordeel == "te_makkelijk":
        nieuw = huidig * STAP_OMHOOG
    elif oordeel == "te_zwaar":
        nieuw = huidig * STAP_OMLAAG
    else:
        nieuw = huidig
    return round(max(ONDERGRENS, min(nieuw, BOVENGRENS)), 4)
