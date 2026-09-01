"""Haalt de Hevy-historie op en rekent de programmastand uit.

Draait in GitHub Actions, waar wel internettoegang naar Hevy is. Schrijft twee
bestanden weg die de Claude-routines lezen nadat ze de repo hebben gecloond:

    data/hevy-raw.json          alle sessies, onbewerkt
    data/programma-status.json  berekende stand: e1RM per lift, week, voorschrift

De rekenkunde staat bewust hier en niet in de routineprompt. Een model dat
percentages uit het hoofd vermenigvuldigt maakt fouten; Python niet.

Omgevingsvariabele: HEVY_API_KEY
"""

import datetime as dt
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

import herstel
import regelaar

BASE = "https://api.hevyapp.com"
START = dt.date(2026, 9, 7)          # week 1, dag 1
LICHAAMSGEWICHT_TERUGVAL = 77.0
UITGANG = {"dip": 52.5, "pullup": 60.0, "squat": 100.0, "muscleup": None}

LIFTS = {
    "dip": ("Chest Dip (Weighted)",),
    "pullup": ("Pull Up (Weighted)", "Chin Up (Weighted)"),
    "squat": ("Squat (Barbell)",),
    "muscleup": ("Muscle Up", "Muscle Up (Weighted)", "Bar Muscle Up"),
}
LICHAAMSGEBONDEN = {"dip", "pullup", "muscleup"}   # percentage over systeembelasting

# reps -> {rpe: percentage van 1RM}
RPE_TABEL = {
    1: {6: .86, 7: .89, 8: .92, 9: .96, 10: 1.00},
    2: {6: .84, 7: .86, 8: .89, 9: .92, 10: .96},
    3: {6: .81, 7: .84, 8: .86, 9: .89, 10: .92},
    4: {6: .79, 7: .81, 8: .84, 9: .86, 10: .89},
    5: {6: .76, 7: .79, 8: .81, 9: .84, 10: .86},
    6: {6: .74, 7: .76, 8: .79, 9: .81, 10: .84},
    7: {6: .72, 7: .735, 8: .765, 9: .785, 10: .815},
    8: {6: .70, 7: .71, 8: .74, 9: .76, 10: .79},
}

# blok -> cyclusweek -> (sets, reps, percentage)
#
# De percentages zijn VERMOEIDHEIDSGECORRIGEERD. Een RPE-tabel geeft de waarde
# voor EEN set; bij meerdere sets op hetzelfde gewicht loopt de RPE per set op,
# ongeveer 2 procentpunt per extra set. De eerste versie van dit schema paste de
# eenzetswaarde toe op vier sets, waardoor set 4 op RPE 9 a 10 uitkwam. Deze
# tabellen liggen daarom 4 tot 6 punten lager, zodat de LAATSTE set op het
# RPE-plafond uitkomt en niet de eerste.
SCHEMA = {
    1: {  # dip en pull-up; squat heeft een eigen tabel
        1: (4, 5, .74), 2: (4, 5, .76), 3: (4, 5, .78),
        4: (5, 4, .81), 5: (4, 4, .84), 6: (2, 5, .62),
    },
    2: {1: (5, 3, .78), 2: (5, 3, .80), 3: (4, 3, .83),
        4: (4, 2, .86), 5: (3, 2, .89), 6: (2, 3, .66)},
    3: {1: (4, 2, .83), 2: (4, 2, .86), 3: (3, 2, .88),
        4: (4, 1, .92), 5: (2, 1, .95), 6: (2, 3, .66)},
    4: {1: (3, 2, .86), 2: (3, 1, .90), 3: (3, 1, .92),
        4: (2, 1, .95), 5: (1, 1, 1.00), 6: (2, 3, .62)},
}
SCHEMA_SQUAT_BLOK1 = {
    1: (5, 5, .72), 2: (5, 5, .74), 3: (5, 5, .76),
    4: (5, 5, .78), 5: (5, 5, .80), 6: (2, 5, .58),
}
RPE_PLAFOND = {1: 7, 2: 7.5, 3: 8, 4: 8, 5: 8.5, 6: 5}

DAGEN = {0: "Dip zwaar", 2: "Pull zwaar", 3: "Squat zwaar", 4: "Volume + muscle-up"}
DAG_KERNLIFT = {0: "dip", 2: "pullup", 3: "squat", 4: None}

# Streefwaarden per week, voor het weekrapport
TARGETS = {
    "dip":      [(12, 65), (24, 80), (36, 92), (48, 102), (52, 105)],
    "squat":    [(12, 120), (24, 135), (36, 148), (48, 157), (52, 160)],
    "pullup":   [(12, 65), (24, 70), (36, 75), (48, 79), (52, 80)],
    "muscleup": [(12, 0), (24, 10), (36, 16), (48, 21), (52, 22)],
}


def api(pad, key):
    req = urllib.request.Request(BASE + pad, headers={"api-key": key, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def alle_workouts(key):
    uit, pagina = [], 1
    while True:
        blok = api(f"/v1/workouts?page={pagina}&pageSize=10", key)
        rijen = blok.get("workouts") or []
        uit.extend(rijen)
        if not rijen or pagina >= blok.get("page_count", 1) or pagina > 60:
            return uit
        pagina += 1


def percentage(reps, rpe, falen):
    """Welk aandeel van het 1RM was deze set."""
    reps = max(1, min(int(reps or 1), 8))
    if rpe is None:
        rpe = 10 if falen else None
    if rpe is None:                       # geen RPE: Epley
        return 1.0 / (1.0 + reps / 30.0)
    rpe = max(6.0, min(float(rpe), 10.0))
    rij = RPE_TABEL[reps]
    onder = int(rpe)
    if onder >= 10:
        return rij[10]
    return rij[onder] + (rij[onder + 1] - rij[onder]) * (rpe - onder)


def e1rm(set_, bw, gebonden):
    gewicht = float(set_.get("weight_kg") or 0)
    reps = set_.get("reps")
    if not reps:
        return None
    pct = percentage(reps, set_.get("rpe"), set_.get("type") == "failure")
    schatting = (bw + gewicht) / pct if gebonden else gewicht / pct
    # Extrapolatie vanaf hoge reps overschat structureel: een set van 7 of 8
    # zegt meer over je uithoudingsvermogen dan over je maximum. Afwaarderen.
    if reps >= 7:
        schatting *= 0.96
    elif reps == 6:
        schatting *= 0.98
    if gebonden:
        return round(schatting - bw, 1)
    return round(schatting, 1)


def robuuste_e1rm(waarden):
    """Mediaan van de drie hoogste, zodat een enkele uitschieter niet bepaalt.

    Een losse zware single (of een set die te optimistisch als falen is
    gelogd) trok het geschatte maximum eerder omhoog, en daarmee elk
    voorgeschreven gewicht van die week.
    """
    if not waarden:
        return None
    top = sorted(waarden, reverse=True)[:3]
    return top[len(top) // 2] if len(top) >= 3 else top[-1]


def afronden(x):
    return round(x * 2) / 2 if x < 5 else round(x / 2.5) * 2.5


def programma_positie(vandaag):
    dagen = (vandaag - START).days
    week = dagen // 7 + 1
    if week < 1:
        return {"week": 0, "cyclusweek": 1, "blok": 1, "voor_start": True,
                "deload": False, "startdatum": START.isoformat()}
    blok = 1 if week <= 12 else 2 if week <= 24 else 3 if week <= 36 else 4 if week <= 48 else 5
    cw = (week - 1) % 6 + 1
    return {"week": week, "cyclusweek": cw, "blok": blok, "voor_start": False,
            "deload": cw == 6, "startdatum": START.isoformat()}


def target_op_week(lift, week):
    punten = TARGETS[lift]
    start = UITGANG[lift] or 0
    vorige_wk, vorige_val = 0, start
    for wk, val in punten:
        if week <= wk:
            deel = (week - vorige_wk) / (wk - vorige_wk) if wk > vorige_wk else 1
            return round(vorige_val + (val - vorige_val) * deel, 1)
        vorige_wk, vorige_val = wk, val
    return punten[-1][1]


STATE_PAD = pathlib.Path("data") / "regelaar.json"


def lees_state():
    if STATE_PAD.exists():
        try:
            return json.loads(STATE_PAD.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def schrijf_state(state):
    STATE_PAD.parent.mkdir(exist_ok=True)
    STATE_PAD.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")


def _matcht(titel, titels):
    titel = titel or ""
    return titel in titels or any(t.lower() in titel.lower() for t in titels)


def sessie_na(workouts, titels, na_datum):
    """Datum, werksets en notitie van de eerste sessie met deze lift vanaf na_datum."""
    kandidaten = []
    for w in workouts:
        datum = (w.get("start_time") or "")[:10]
        if not datum or datum < na_datum:
            continue
        for oef in w.get("exercises", []):
            if not _matcht(oef.get("title"), titels):
                continue
            werk = [s for s in oef.get("sets", []) if s.get("type") != "warmup"]
            if werk:
                kandidaten.append((datum, werk, oef.get("notes") or ""))
    if not kandidaten:
        return "", [], ""
    kandidaten.sort(key=lambda r: r[0])
    return kandidaten[0]


def laatste_notitie(workouts, titels):
    """De meest recente notitie bij deze oefening, voor het weekrapport."""
    beste = ("", "")
    for w in workouts:
        datum = (w.get("start_time") or "")[:10]
        for oef in w.get("exercises", []):
            if _matcht(oef.get("title"), titels) and (oef.get("notes") or "").strip():
                if datum > beste[0]:
                    beste = (datum, oef["notes"].strip()[:300])
    return {"datum": beste[0], "tekst": beste[1]} if beste[0] else None


def main():
    key = os.environ.get("HEVY_API_KEY", "").strip()
    if not key:
        sys.exit("HEVY_API_KEY ontbreekt in de omgeving.")

    try:
        workouts = alle_workouts(key)
        metingen = (api("/v1/body_measurements?page=1&pageSize=10", key) or {}).get("body_measurements") or []
    except urllib.error.HTTPError as e:
        sys.exit(f"Hevy API gaf HTTP {e.code}: {e.reason}")

    bw = LICHAAMSGEWICHT_TERUGVAL
    gewichten = [(m.get("date"), m.get("weight_kg")) for m in metingen if m.get("weight_kg")]
    gewichten.sort()
    if gewichten:
        bw = float(gewichten[-1][1])

    vandaag = dt.date.today()
    pos = programma_positie(vandaag)
    grens = vandaag - dt.timedelta(weeks=6)

    stand = {}
    for lift, titels in LIFTS.items():
        gebonden = lift in LICHAAMSGEBONDEN
        sessies, recente_waarden = [], []
        for w in workouts:
            datum = (w.get("start_time") or "")[:10]
            if not datum:
                continue
            d = dt.date.fromisoformat(datum)
            for oef in w.get("exercises", []):
                if oef.get("title") not in titels and not any(
                        t.lower() in (oef.get("title") or "").lower() for t in titels):
                    continue
                for s in oef.get("sets", []):
                    if s.get("type") == "warmup":
                        continue
                    v = e1rm(s, bw, gebonden)
                    if v is None:
                        continue
                    sessies.append({"datum": datum, "gewicht": s.get("weight_kg"),
                                    "reps": s.get("reps"), "rpe": s.get("rpe"),
                                    "type": s.get("type"), "e1rm": v})
                    if d >= grens:
                        recente_waarden.append(v)
        beste_recent = robuuste_e1rm(recente_waarden)
        if beste_recent is None:
            beste_recent = UITGANG[lift]
        sessies.sort(key=lambda r: r["datum"])
        stand[lift] = {
            "e1rm": beste_recent,
            "bron": "hevy" if sessies else "uitgangswaarde",
            "target_nu": target_op_week(lift, max(pos["week"], 1)),
            "aantal_werksets_totaal": len(sessies),
            "laatste_sets": sessies[-8:],
            "laatste_notitie": laatste_notitie(workouts, titels),
        }

    # ---- Terugkoppeling: was het vorige voorschrift te zwaar of te licht? ----
    state = lees_state()
    terugkoppeling = {}
    for lift, titels in LIFTS.items():
        if lift == "muscleup":
            continue
        eerder = state.get(lift, {})
        factor = float(eerder.get("factor", 1.0))
        vorig = eerder.get("laatste_voorschrift")
        al_beoordeeld = eerder.get("laatste_beoordeelde_sessie", "")
        oordeel = reden = None
        if vorig:
            datum_na, sets_na, notitie_tekst = sessie_na(workouts, titels, vorig["datum"])
            # Elke sessie telt maar een keer mee. Zonder deze grendel zou een
            # tweede run op dezelfde dag de correctie dubbel toepassen.
            if sets_na and datum_na > al_beoordeeld:
                notitie = regelaar.lees_notitie(notitie_tekst)
                oordeel, reden = regelaar.beoordeel(vorig, sets_na, notitie)
                if oordeel:
                    factor = regelaar.nieuwe_factor(factor, oordeel)
                    state.setdefault(lift, {})["laatste_beoordeelde_sessie"] = datum_na
        terugkoppeling[lift] = {
            "factor": factor,
            "oordeel_vorige_sessie": oordeel,
            "reden": reden,
            "vorig_voorschrift": vorig,
        }

    # ---- Voorschrift per kernlift voor deze cyclusweek ----
    cw, blok = pos["cyclusweek"], min(pos["blok"], 4)
    voorschrift = {}
    for lift in ("dip", "pullup", "squat"):
        tabel = SCHEMA_SQUAT_BLOK1 if (lift == "squat" and blok == 1) else SCHEMA[blok]
        sets, reps, pct = tabel[cw]
        basis = stand[lift]["e1rm"] or UITGANG[lift]
        factor = terugkoppeling[lift]["factor"]
        if lift in LICHAAMSGEBONDEN:
            kg = afronden(((bw + basis) * pct - bw) * factor)
        else:
            kg = afronden(basis * pct * factor)
        voorschrift[lift] = {
            "sets": sets, "reps": reps, "percentage": round(pct * 100, 1),
            "kg": kg, "rpe_plafond": RPE_PLAFOND[cw],
            "correctiefactor": factor,
            "bijgesteld_omdat": terugkoppeling[lift]["reden"] if terugkoppeling[lift]["oordeel_vorige_sessie"] else None,
        }
        state.setdefault(lift, {})["factor"] = factor
        state[lift]["laatste_voorschrift"] = {
            "datum": vandaag.isoformat(), "sets": sets, "reps": reps, "kg": kg,
        }
        log = state[lift].setdefault("log", [])
        if terugkoppeling[lift]["oordeel_vorige_sessie"]:
            log.append({"datum": vandaag.isoformat(),
                        "oordeel": terugkoppeling[lift]["oordeel_vorige_sessie"],
                        "reden": terugkoppeling[lift]["reden"],
                        "nieuwe_factor": factor})
            del log[:-20]
    schrijf_state(state)

    # Nalevingscijfers over de afgelopen 7 dagen
    week_grens = vandaag - dt.timedelta(days=7)
    dipsets = pullsets = kern_totaal = kern_met_rpe = kern_falen = 0
    sessiedagen = set()
    for w in workouts:
        datum = (w.get("start_time") or "")[:10]
        if not datum or dt.date.fromisoformat(datum) < week_grens:
            continue
        sessiedagen.add(datum)
        for oef in w.get("exercises", []):
            titel = oef.get("title") or ""
            werk = [s for s in oef.get("sets", []) if s.get("type") != "warmup"]
            if titel in LIFTS["dip"] or titel == "Chest Dip":
                dipsets += len(werk)
            if titel in LIFTS["pullup"] or titel == "Pull Up":
                pullsets += len(werk)
            if any(titel in t for t in LIFTS.values()):
                kern_totaal += len(werk)
                kern_met_rpe += sum(1 for s in werk if s.get("rpe") is not None)
                kern_falen += sum(1 for s in werk if s.get("type") == "failure")

    # ---- Herstel: slaap, stappen en vermoeidheid uit je Hevy-notities ----
    herstel_dagen = []
    for w in sorted(workouts, key=lambda x: x.get("start_time") or "", reverse=True)[:14]:
        gevonden = herstel.uit_workout(w)
        if gevonden:
            gevonden["datum"] = (w.get("start_time") or "")[:10]
            herstel_dagen.append(gevonden)
    herstel_oordeel = herstel.beoordeel(herstel_dagen[0] if herstel_dagen else {})

    status = {
        "gegenereerd_op": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "vandaag": vandaag.isoformat(),
        "weekdag": vandaag.weekday(),
        "dagthema": DAGEN.get(vandaag.weekday()),
        "kernlift_vandaag": DAG_KERNLIFT.get(vandaag.weekday()),
        "positie": pos,
        "lichaamsgewicht": bw,
        "lichaamsgewicht_bron": "hevy" if gewichten else "terugval 77 kg",
        "stand": stand,
        "voorschrift_deze_week": voorschrift,
        "terugkoppeling": terugkoppeling,
        "herstel": {"recent": herstel_dagen[:7], "oordeel": herstel_oordeel},
        "afgelopen_7_dagen": {
            "sessies": len(sessiedagen),
            "dipwerksets": dipsets, "dipdoel": 10,
            "pullupwerksets": pullsets, "pullupdoel": 7,
            "kernsets": kern_totaal,
            "kernsets_met_rpe": kern_met_rpe,
            "kernsets_tot_falen": kern_falen,
        },
        "totaal_nu": round(sum(
            (stand[l]["e1rm"] or 0) for l in ("dip", "pullup", "squat", "muscleup")), 1),
        "totaal_doel": 367,
    }

    uit = pathlib.Path("data")
    uit.mkdir(exist_ok=True)
    (uit / "hevy-raw.json").write_text(
        json.dumps({"lichaamsmetingen": metingen, "workouts": workouts}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    (uit / "programma-status.json").write_text(
        json.dumps(status, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"{len(workouts)} sessies opgehaald, lichaamsgewicht {bw} kg")
    print(f"week {pos['week']}, cyclusweek {pos['cyclusweek']}, blok {pos['blok']}")
    for lift in ("dip", "pullup", "squat"):
        v = voorschrift[lift]
        print(f"  {lift:8s} e1RM {stand[lift]['e1rm']:>6} -> {v['sets']}x{v['reps']} @ {v['kg']} kg")


if __name__ == "__main__":
    main()
