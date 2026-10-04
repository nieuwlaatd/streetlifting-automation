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
3. Of er tot falen is getraind.

Gehaalde sets en reps tellen niet meer mee: Dylan volgt Kajs schema, dat
andere sets en reps voorschrijft dan het referentieschema in hevy_sync.
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
    "moest laten zakken", "haalde het niet", "was zwaar", "ging niet meer",
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


def beoordeel(voorschrift, sets, notitie, schattingen=None, basis=None):
    """Was de vorige sessie te zwaar, goed, of te makkelijk?

    voorschrift: dict met sets, reps, kg
    sets:        werksets van die dag, elk met weight_kg, reps, rpe, type
    notitie:     uitkomst van lees_notitie
    schattingen: e1RM per set op basis van de RPE (None waar geen RPE is)
    basis:       het e1RM waar het voorschrift op rustte

    WAAROM NIET MEER OP SETS EN REPS
    De routines in Hevy komen uit Kajs schema, niet uit het voorschrift van
    hevy_sync. Dylan draait dus andere sets en reps dan hier staan, en kiest
    het gewicht zelf op RPE. "0 van 5 sets gehaald" betekende daardoor niets:
    het zei alleen dat hij 3x3 deed in plaats van 5x4. Tot 4 oktober 2026
    duwde dat alle drie de lifts naar de ondergrens, ook bij sets op RPE 6.

    De vraag is nu: wat zegt de zwaarste set met een RPE over het maximum?
    Een set ver onder falen telt daarbij niet als bewijs dat het te zwaar was.
    Te zwaar is alleen wat er echt op wijst: falen, RPE 9,5 of hoger, of een
    notitie die het zegt.
    """
    if not sets:
        return None, "geen vergelijkbare sessie gevonden"

    rpes = [float(s["rpe"]) for s in sets if s.get("rpe") is not None]
    if notitie["rpe"] is not None:
        rpes.append(notitie["rpe"])
    hoogste_rpe = max(rpes) if rpes else None
    falen = any(s.get("type") == "failure" for s in sets)

    # Te zwaar wint altijd: liever een week te licht dan een blessure.
    if notitie["signaal"] == "te_zwaar":
        return "te_zwaar", "notitie meldt dat het te zwaar was"
    if falen:
        return "te_zwaar", "set tot falen gelogd"
    if hoogste_rpe is not None and hoogste_rpe >= 9.5:
        return "te_zwaar", f"RPE {hoogste_rpe:g} gelogd, boven het plafond"

    if notitie["signaal"] == "te_makkelijk":
        return "te_makkelijk", "notitie meldt dat het makkelijk ging"
    beste = max((v for v in (schattingen or []) if v is not None), default=None)
    if beste is None:
        return None, "geen RPE gelogd, niets te beoordelen"
    if basis and beste >= basis * 1.03:
        return "te_makkelijk", (f"beste set rekent uit op e1RM {beste:g}, "
                                f"boven de schatting van {basis:g}")
    return "goed", f"binnen het plafond, beste set rekent uit op e1RM {beste:g}"


def nieuwe_factor(huidig, oordeel):
    if oordeel == "te_makkelijk":
        nieuw = huidig * STAP_OMHOOG
    elif oordeel == "te_zwaar":
        nieuw = huidig * STAP_OMLAAG
    else:
        nieuw = huidig
    return round(max(ONDERGRENS, min(nieuw, BOVENGRENS)), 4)
