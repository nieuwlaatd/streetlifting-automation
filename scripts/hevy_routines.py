"""Zet de vier trainingsdagen als routines klaar in Hevy, met de juiste gewichten.

Zo hoeft er niets meer op een telefoonscherm gelezen te worden: je opent Hevy,
start de routine van vandaag, en de gewichten staan er al in. De app waarin je
toch al logt is meteen het schema.

Draait na hevy_sync.py, want die berekent het voorschrift dat hier ingevuld
wordt. Bestaat een routine al, dan wordt hij bijgewerkt (PUT) in plaats van
opnieuw aangemaakt, zodat je hem in Hevy kunt vastpinnen en hij op zijn plek
blijft staan.

Omgevingsvariabele: HEVY_API_KEY
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://api.hevyapp.com"
MAP_PREFIX = "SL"                 # herkenbaar voorvoegsel, zo vinden we ze terug
FOLDER = "Streetlifting"

# Exercise template ids uit de Hevy-bibliotheek.
EX = {
    "dip_w": "29472BE1",          # Chest Dip (Weighted)
    "dip": "6FCD7755",            # Chest Dip
    "pullup_w": "1B2B1E7C",       # Pull Up  (gewicht als extra kg)
    "squat": "D04AC939",          # Squat (Barbell)
    "bench": "79D0BB3A",          # Bench Press (Barbell)
    "skull": "68F8A292",          # Skullcrusher (Dumbbell)
    "abwheel": "99D5F10E",        # Ab Wheel
    "row": "91FAFBA3",            # Iso-Lateral Low Row
    "reardelt": "D8281C62",       # Rear Delt Reverse Fly (Machine)
    "curl": "ADA8623C",           # Bicep Curl (Cable)
    "nordic": "108D7A14",         # Nordic Hamstrings Curls
    "legraise": "F8356514",       # Hanging Leg Raise
    "latpull": "6A6C31A5",        # Lat Pulldown (Cable)
    "hipthrust": "68CE0B9B",      # Hip Thrust (Machine)
    "legcurl": "B8127AD1",        # Lying Leg Curl (Machine)
    "legext": "75A4F6C4",         # Leg Extension (Machine)
    "calf": "062AB91A",           # Seated Calf Raise
    "adduction": "8BEBFED6",      # Hip Adduction (Machine)
    "lateral": "BE289E45",        # Lateral Raise (Cable)
    "hammer": "7E3BC8B6",         # Hammer Curl (Dumbbell)
    "tricep": "94B7239B",         # Triceps Rope Pushdown
    "crunch": "23A48484",         # Cable Crunch
    "muscleup": "9F9C164B",       # Muscle Up
}


def api(pad, methode="GET", body=None, key=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + pad, data=data, method=methode,
        headers={"api-key": key, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        tekst = r.read().decode()
        return json.loads(tekst) if tekst.strip() else {}


def oef(template, sets, rust=None, notitie=None):
    return {"exercise_template_id": template, "superset_id": None,
            "rest_seconds": rust, "notes": notitie, "sets": sets}


def werksets(aantal, reps, gewicht=None, opwarming=0):
    uit = []
    for i in range(opwarming):
        deel = [0.4, 0.6, 0.8][min(i, 2)]
        uit.append({"type": "warmup", "reps": max(3, reps - 1),
                    "weight_kg": round((gewicht or 0) * deel / 2.5) * 2.5 if gewicht else 0})
    for _ in range(aantal):
        uit.append({"type": "normal", "reps": reps, "weight_kg": gewicht})
    return uit


def bouw_routines(status):
    v = status["voorschrift_deze_week"]
    pos = status["positie"]
    dip, pull, squat = v["dip"], v["pullup"], v["squat"]
    kop = f"week {pos['week']} · cyclusweek {pos['cyclusweek']}" + (" · DELOAD" if pos["deload"] else "")

    def kern_notitie(x):
        return f"KERNLIFT — RPE-plafond {x['rpe_plafond']}. Stop bij het plafond, niet bij falen."

    ma = [
        oef(EX["dip_w"], werksets(dip["sets"], dip["reps"], dip["kg"], opwarming=3), 180, kern_notitie(dip)),
        oef(EX["dip_w"], werksets(2, 8, round(dip["kg"] / 2 / 2.5) * 2.5), 120, "Back-off, helft van het kerngewicht."),
        oef(EX["squat"], werksets(4, 4, round(squat["kg"] * 0.85 / 2.5) * 2.5), 150,
            "Snelheidswerk, RPE-plafond 6. Elke rep explosief omhoog."),
        oef(EX["bench"], werksets(2, 8), 120, "Assistentie, RPE 8."),
        oef(EX["skull"], werksets(2, 10), 90),
        oef(EX["abwheel"], werksets(2, 12), 60),
    ]
    wo = [
        oef(EX["pullup_w"], werksets(pull["sets"], pull["reps"], pull["kg"], opwarming=3), 180, kern_notitie(pull)),
        oef(EX["row"], werksets(3, 8), 120, "RPE 8."),
        oef(EX["reardelt"], werksets(2, 13), 90),
        oef(EX["curl"], werksets(2, 11), 90),
        oef(EX["nordic"], werksets(2, 5), 120, "Excentrisch afremmen."),
        oef(EX["legraise"], werksets(3, 12), 60),
        oef(EX["latpull"], werksets(2, 11), 90, "Optioneel, laat vallen bij tijdnood."),
    ]
    do = [
        oef(EX["squat"], werksets(squat["sets"], squat["reps"], squat["kg"], opwarming=3), 210,
            kern_notitie(squat) + " Heupplooi onder de knie, wedstrijddiepte."),
        oef(EX["hipthrust"], werksets(2, 8), 120),
        oef(EX["legcurl"], werksets(3, 7), 90),
        oef(EX["legext"], werksets(2, 11), 90),
        oef(EX["calf"], werksets(2, 12), 60),
        oef(EX["adduction"], werksets(2, 12), 60, "Optioneel."),
    ]
    vr = [
        oef(EX["pullup_w"], werksets(5, 3), 90,
            "Muscle-upwerk. Explosieve high pull-ups: trekken tot je onderste ribben."),
        oef(EX["muscleup"], werksets(5, 2), 120,
            "Negatieve muscle-ups: spring erin, zak in 3 tot 5 seconden door de transitie terug."),
        oef(EX["dip"], werksets(3, 8), 90, "Straight-bar dips, bovenste helft van de muscle-up."),
        oef(EX["dip_w"], werksets(4, 9, round(dip["kg"] / 2 / 2.5) * 2.5), 120, "Volume, RPE 8."),
        oef(EX["pullup_w"], werksets(3, 7, round(pull["kg"] * 0.6 / 2.5) * 2.5), 120, "Volume, RPE 8."),
        oef(EX["lateral"], werksets(2, 13), 60),
        oef(EX["hammer"], werksets(2, 11), 60),
        oef(EX["tricep"], werksets(2, 11), 60),
        oef(EX["crunch"], werksets(2, 13), 60),
    ]
    wk = f"wk{pos['week']}" + ("-DELOAD" if pos["deload"] else "")
    # Het notes-veld van een routine wordt door Hevy niet bewaard, dus alles
    # wat je vooraf wilt zien staat in de titel. Terugvinden gebeurt op het
    # voorvoegsel ("SL 1"), zodat de rest van de titel mag meebewegen.
    return [
        ("SL 1", f"SL 1 · Ma — Dip +{dip['kg']:g} · {wk}", ma),
        ("SL 2", f"SL 2 · Wo — Pull-up +{pull['kg']:g} · {wk}", wo),
        ("SL 3", f"SL 3 · Do — Squat {squat['kg']:g} · {wk}", do),
        ("SL 4", f"SL 4 · Vr — Volume + muscle-up · {wk}", vr),
    ]


def main():
    key = os.environ.get("HEVY_API_KEY", "").strip()
    if not key:
        sys.exit("HEVY_API_KEY ontbreekt.")
    try:
        status = json.load(open("data/programma-status.json", encoding="utf-8"))
    except FileNotFoundError:
        sys.exit("data/programma-status.json ontbreekt; draai eerst hevy_sync.py.")

    # Map opzoeken of aanmaken.
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
        print(f"Map aanmaken overgeslagen (HTTP {e.code}); routines komen in My Routines.")

    # Bestaande routines ophalen, zodat we bijwerken in plaats van dupliceren.
    bestaand, pagina = {}, 1
    while pagina <= 10:
        blok = api(f"/v1/routines?page={pagina}&pageSize=10", key=key)
        for r in blok.get("routines") or []:
            titel = r.get("title") or ""
            if titel.startswith(MAP_PREFIX + " "):
                bestaand[" ".join(titel.split()[:2])] = r["id"]   # sleutel: "SL 1"
        if pagina >= blok.get("page_count", 1):
            break
        pagina += 1

    for sleutel, titel, oefeningen in bouw_routines(status):
        body = {"routine": {"title": titel, "exercises": oefeningen}}
        if sleutel in bestaand:
            api(f"/v1/routines/{bestaand[sleutel]}", "PUT", body, key)
            print(f"bijgewerkt: {titel}")
        else:
            body["routine"]["folder_id"] = folder_id
            api("/v1/routines", "POST", body, key)
            print(f"aangemaakt: {titel}")


if __name__ == "__main__":
    main()
