"""Zet het schema van coach Kaj als routines in Hevy.

Bron is data/coachschema.json, dat rechtstreeks uit Kaj's Google Sheet komt.
Deze code verzint niets: sets, reps en RPE worden overgenomen zoals ze in de
Sheet staan. Voegt Kaj een week toe, dan volgt Hevy de ochtend erna vanzelf.

WAAROM ER GEEN GEWICHTEN IN STAAN
Kaj programmeert op RPE, niet op kilo's. "Competition Dip 3x3 @ RPE 6" betekent
dat jij op de dag zelf het gewicht kiest dat op RPE 6 uitkomt. Een vooraf
ingevuld gewicht zou dat oordeel overschrijven, en daarmee het schema kapot
maken. Hevy toont bij een leeg gewichtsveld vanzelf wat je vorige keer deed.

Omgevingsvariabele: HEVY_API_KEY
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = "https://api.hevyapp.com"
MAP_PREFIX = "SL"
FOLDER = "Streetlifting"

# Kaj's oefeningnamen naar Hevy-templates.
#
# TWEE REGELS
# Waar geladen kan worden hoort een variant met gewichtsveld. Een competition
# pull-up op de gewone "Pull Up" heeft geen plek voor de kilo's, en dan moet
# Dylan tijdens het trainen zelf een andere oefening opzoeken.
# Bestaat een oefening niet in Hevy, dan is er een eigen template aangemaakt
# onder Kaj's eigen naam, zodat het gewicht wel kwijt kan en de naam in het
# logboek klopt met het schema.
MAP = {
    "Competition Dip": ("29472BE1", None),
    "Competition Chin-up": ("023943F1", None),
    "Competition Pull-Up": ("729237D1", None),          # Pull Up (Weighted)
    "45 degree Incline Dumbbell Press": ("07B38369", "45 graden"),
    "Cable Side Raise": ("BE289E45", None),
    "Plate Loaded Knee Raise": ("e625db58-286f-40a5-855a-f1ef4f5f2a82", None),
    "Skull Crusher": ("68F8A292", None),
    "3-1-0 Tempo Squat": ("D04AC939", "Tempo 3-1-0: 3 sec zakken, 1 sec pauze, normaal omhoog"),
    "Paused Squat": ("CE1054CE", None),
    "Diagonal Bodyweight Pull-up": ("1B2B1E7C", "Diagonaal, lichaamsgewicht"),
    "Bar Cable Pullover": ("B123DD01", "Met stang aan de kabel"),
    "Leg Extension": ("75A4F6C4", None),
    "Cable row": ("F1D60854", None),
    "Spider Curl": ("90427D4A", None),
    "2s Paused Dip": ("29472BE1", "2 seconden pauze onderin"),
    "Close Grip Larsen Press": ("79D0BB3A", "Larsen press, benen van de grond"),
    "2s Paused Squat": ("CE1054CE", "2 seconden pauze onderin"),
    "Cable Fly": ("651F844C", None),
    "Cable Knee Tuck": ("daa1345e-d274-4b11-b584-c4b8472d876d", None),
    "Ab Roll Out": ("99D5F10E", None),
    "Competition Squat": ("D04AC939", None),
    "Band Assisted Muscle-Up": ("f2734cb1-6a7a-4801-80c5-6d948b342c49", None),
    "3-1-0 Tempo Dip": ("29472BE1", "Tempo 3-1-0"),
    "3s Tempo Pull-Up": ("729237D1", "3 sec zakken"),   # gewogen: gewicht kan erbij
    "Leg Curl": ("B8127AD1", None),
    "Wide Grip Row": ("C3BCABB3", None),
    "Tricep Extension": ("94B7239B", None),
    "Side Plank Leg Raised": ("E3EDA509", "Been geheven"),
}

KORT = {"maandag": "Ma", "dinsdag": "Di", "woensdag": "Wo",
        "donderdag": "Do", "vrijdag": "Vr", "zaterdag": "Za", "zondag": "Zo"}


def _met_herhaling(doe, pogingen=5):
    """Vangt 429 en tijdelijke serverfouten op met oplopende wachttijd."""
    import time
    for poging in range(pogingen):
        try:
            return doe()
        except urllib.error.HTTPError as fout:
            if fout.code in (429, 500, 502, 503, 504) and poging < pogingen - 1:
                wacht = 2 ** poging * 5
                print(f"  HTTP {fout.code}, opnieuw over {wacht}s")
                time.sleep(wacht)
                continue
            raise


def api(pad, methode="GET", body=None, key=None):
    def doe():
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            BASE + pad, data=data, method=methode,
            headers={"api-key": key, "Content-Type": "application/json",
                     "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            tekst = r.read().decode()
            return json.loads(tekst) if tekst.strip() else {}
    return _met_herhaling(doe)


# Oefeningen die Hevy in seconden meet in plaats van reps. Zonder deze lijst
# leest 'reps' als "30 sec" nergens op uit en blijft de set leeg.
DUUR = {"E3EDA509"}


def maak_sets(oefening, template=None):
    """Bouwt de sets. Reps kan een getal, een bereik, 'x' of '30 sec' zijn."""
    try:
        aantal = int(float(oefening["sets"] or 1))
    except ValueError:
        aantal = 1
    aantal = max(1, min(aantal, 10))

    reps_tekst = (oefening["reps"] or "").strip()
    reps, bereik = None, None
    if "-" in reps_tekst:
        stukken = reps_tekst.split("-")
        try:
            bereik = (int(stukken[0]), int(stukken[1]))
            reps = bereik[0]
        except ValueError:
            pass
    else:
        try:
            reps = int(float(reps_tekst))
        except ValueError:
            reps = None            # bijvoorbeeld 'x' of '30 sec'

    seconden = None
    if template in DUUR:
        m = re.search(r"(\d+)", reps_tekst)
        seconden = int(m.group(1)) if m else 30
        reps, bereik = None, None

    sets = []
    for _ in range(aantal):
        s = {"type": "normal", "reps": reps, "weight_kg": None}
        if seconden is not None:
            s["duration_seconds"] = seconden
        elif bereik:
            s["rep_range"] = {"start": bereik[0], "end": bereik[1]}
        sets.append(s)
    return sets


def notitie(oefening, hevy_titel_afwijkend):
    delen = []
    if hevy_titel_afwijkend:
        delen.append(f"Kaj: {oefening['naam']}")
    if hevy_titel_afwijkend is None and oefening["naam"]:
        pass
    rl = (oefening["rpe_load"] or "").strip()
    if rl and rl.lower() != "x":
        delen.append(f"RPE {rl}" if not rl.lower().startswith("rpe") else rl)
    reps = (oefening["reps"] or "").strip()
    if reps and not reps.replace("-", "").isdigit():
        delen.append(f"Reps: {reps}")
    if oefening["opmerking"]:
        delen.append(oefening["opmerking"])
    return " · ".join(delen) or None


def bouw_routines(schema):
    uit = []
    for blok in schema["blokken"]:
        for i, dag in enumerate(blok["dagen"], start=1):
            oefeningen = []
            for o in dag["oefeningen"]:
                gevonden = MAP.get(o["naam"])
                if not gevonden:
                    print(f"  LET OP: geen Hevy-oefening voor {o['naam']!r}, overgeslagen")
                    continue
                template, extra = gevonden
                stukken = [f"Kaj: {o['naam']}"]
                rl = (o["rpe_load"] or "").strip()
                if rl and rl.lower() != "x":
                    stukken.append(f"RPE {rl}")
                if extra:
                    stukken.append(extra)
                if o["opmerking"]:
                    stukken.append(o["opmerking"])
                reps = (o["reps"] or "").strip()
                if reps and not reps.replace("-", "").isdigit():
                    stukken.append(f"Reps: {reps}")
                oefeningen.append({
                    "exercise_template_id": template,
                    "superset_id": None,
                    "rest_seconds": 180 if "Competition" in o["naam"] else 90,
                    "notes": " · ".join(stukken),
                    "sets": maak_sets(o, template),
                })
            thema = dag["thema"] or dag["dag"].capitalize()
            titel = f"{MAP_PREFIX} {i} · {KORT[dag['dag']]} — {thema}"
            uit.append((f"{MAP_PREFIX} {i}", titel[:95], oefeningen))
    return uit


def main():
    key = os.environ.get("HEVY_API_KEY", "").strip()
    if not key:
        sys.exit("HEVY_API_KEY ontbreekt.")
    try:
        schema = json.load(open("data/coachschema.json", encoding="utf-8"))
    except FileNotFoundError:
        sys.exit("data/coachschema.json ontbreekt; draai eerst coach_schema.py.")

    folder_id = None
    try:
        mappen = (api("/v1/routine_folders?page=1&pageSize=10", key=key) or {}).get("routine_folders") or []
        for m in mappen:
            if m.get("title") == FOLDER:
                folder_id = m.get("id")
        if folder_id is None:
            nieuw = api("/v1/routine_folders", "POST", {"routine_folder": {"title": FOLDER}}, key)
            folder_id = (nieuw.get("routine_folder") or {}).get("id")
    except urllib.error.HTTPError as e:
        print(f"Map overgeslagen (HTTP {e.code}); routines komen in My Routines.")

    bestaand, pagina = {}, 1
    while pagina <= 10:
        blok = api(f"/v1/routines?page={pagina}&pageSize=10", key=key)
        for r in blok.get("routines") or []:
            titel = r.get("title") or ""
            if titel.startswith(MAP_PREFIX + " "):
                bestaand[" ".join(titel.split()[:2])] = r["id"]
        if pagina >= blok.get("page_count", 1):
            break
        pagina += 1

    for sleutel, titel, oefeningen in bouw_routines(schema):
        body = {"routine": {"title": titel, "exercises": oefeningen}}
        if sleutel in bestaand:
            api(f"/v1/routines/{bestaand[sleutel]}", "PUT", body, key)
            print(f"bijgewerkt: {titel}  ({len(oefeningen)} oefeningen)")
        else:
            body["routine"]["folder_id"] = folder_id
            api("/v1/routines", "POST", body, key)
            print(f"aangemaakt: {titel}  ({len(oefeningen)} oefeningen)")


if __name__ == "__main__":
    main()
