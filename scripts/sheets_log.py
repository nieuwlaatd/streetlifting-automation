"""Zet gelogde Hevy-sessies over naar de Google Sheet van coach Kaj.

Kaj wil de werkelijke uitvoering in zijn Sheet zien: per oefening de RPE in
kolom F en de sets in G tot en met K. Dit script leest de laatste sessies uit
Hevy, zoekt bij elke oefening de bijbehorende rij en vult die in.

WAT ER NIET GEBEURT
Er wordt nooit iets overschreven dat al ingevuld is. Zet Kaj of jij met de hand
iets in een cel, dan blijft dat staan. Alleen lege cellen worden gevuld, tenzij
je --overschrijf meegeeft. Zo kan dit script nooit werk van een mens wissen.

KOPPELING
Een Hevy-sessie wordt aan een dag uit het schema gekoppeld op weekdag. Traint
Dylan op een andere dag dan gepland, dan wordt gekeken welke dag qua oefeningen
het beste past. Is de overlap te klein, dan wordt de sessie overgeslagen en
gemeld in plaats van gegokt.

BENODIGD
  GOOGLE_SERVICE_ACCOUNT  de JSON-sleutel van een service-account, als tekst
  HEVY_API_KEY            voor het ophalen van de sessies
De Sheet moet gedeeld zijn met het e-mailadres van dat service-account, met
bewerkrechten.
"""

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

SHEET_ID = "1QGxPFQB17u9zDPNXMl74pcVUERlX2g7RwZBRk-Trpfo"
BASE = "https://api.hevyapp.com"
DAGEN_TERUG = 10

# Hevy-oefening terug naar de naam die Kaj gebruikt. Meerdere Kaj-oefeningen
# kunnen op dezelfde Hevy-template uitkomen (Competition Dip en 2s Paused Dip
# zijn allebei Chest Dip), dus de koppeling gaat via de dag: binnen een dag is
# de volgorde leidend.
HEVY_NAAR_KAJ = {
    "Chest Dip (Weighted)": ["Competition Dip", "2s Paused Dip", "3-1-0 Tempo Dip"],
    "Chin Up (Weighted)": ["Competition Chin-up"],
    "Pull Up": ["Competition Pull-Up", "Diagonal Bodyweight Pull-up", "3s Tempo Pull-Up"],
    "Incline Bench Press (Dumbbell)": ["45 degree Incline Dumbbell Press"],
    "Lateral Raise (Cable)": ["Cable Side Raise"],
    "Knee Raise Parallel Bars": ["Plate Loaded Knee Raise"],
    "Skullcrusher (Dumbbell)": ["Skull Crusher"],
    "Squat (Barbell)": ["3-1-0 Tempo Squat", "Competition Squat"],
    "Pause Squat (Barbell)": ["Paused Squat", "2s Paused Squat"],
    "Pullover (Machine)": ["Bar Cable Pullover"],
    "Leg Extension (Machine)": ["Leg Extension"],
    "Seated Cable Row - Bar Grip": ["Cable row"],
    "Spider Curl (Dumbbell)": ["Spider Curl"],
    "Bench Press (Barbell)": ["Close Grip Larsen Press"],
    "Cable Fly Crossovers": ["Cable Fly"],
    "Hanging Knee Raise": ["Cable Knee Tuck"],
    "Ab Wheel": ["Ab Roll Out"],
    "Muscle Up": ["Band Assisted Muscle-Up"],
    "Lying Leg Curl (Machine)": ["Leg Curl"],
    "Seated Cable Row - Bar Wide Grip": ["Wide Grip Row"],
    "Triceps Rope Pushdown": ["Tricep Extension"],
    "Side Plank": ["Side Plank Leg Raised"],
}


def _met_herhaling(doe, pogingen=5):
    import time
    for poging in range(pogingen):
        try:
            return doe()
        except urllib.error.HTTPError as fout:
            if fout.code in (429, 500, 502, 503, 504) and poging < pogingen - 1:
                time.sleep(2 ** poging * 5)
                continue
            raise


def hevy(pad, key):
    def doe():
        req = urllib.request.Request(BASE + pad, headers={"api-key": key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    return _met_herhaling(doe)


def sheets_client():
    """Bouwt een Sheets-client uit de service-accountsleutel."""
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    ruw = os.environ.get("GOOGLE_SERVICE_ACCOUNT", "").strip()
    if not ruw:
        return None
    info = json.loads(ruw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def zet_set(s):
    """Een set als leesbare tekst: gewicht x reps."""
    g, reps = s.get("weight_kg"), s.get("reps")
    if reps is None:
        return ""
    if not g:
        return f"BW x{reps}"
    return f"{g:g} x{reps}"


def kies_dag(workout, dagen):
    """Welke geplande dag hoort bij deze sessie?"""
    datum = dt.date.fromisoformat(workout["start_time"][:10])
    titels = {o.get("title") for o in workout.get("exercises", [])}

    def overlap(dag):
        verwacht = set()
        for o in dag["oefeningen"]:
            for hevy_naam, kaj_namen in HEVY_NAAR_KAJ.items():
                if o["naam"] in kaj_namen:
                    verwacht.add(hevy_naam)
        return len(titels & verwacht)

    op_weekdag = [d for d in dagen if d["weekdag"] == datum.weekday()]
    if op_weekdag and overlap(op_weekdag[0]) >= 2:
        return op_weekdag[0], "weekdag"
    beste = max(dagen, key=overlap)
    return (beste, "oefeningen") if overlap(beste) >= 3 else (None, "te weinig overlap")


def main():
    overschrijf = "--overschrijf" in sys.argv
    key = os.environ.get("HEVY_API_KEY", "").strip()
    if not key:
        sys.exit("HEVY_API_KEY ontbreekt.")
    schema = json.load(open("data/coachschema.json", encoding="utf-8"))
    dagen = [d for b in schema["blokken"] for d in b["dagen"]]
    if not dagen:
        sys.exit("Geen dagen in het coachschema.")

    grens = dt.date.today() - dt.timedelta(days=DAGEN_TERUG)
    recent = [w for w in (hevy("/v1/workouts?page=1&pageSize=10", key).get("workouts") or [])
              if dt.date.fromisoformat(w["start_time"][:10]) >= grens]
    if not recent:
        print(f"Geen sessies in de afgelopen {DAGEN_TERUG} dagen.")
        return

    client = sheets_client()
    if client is None:
        print("GOOGLE_SERVICE_ACCOUNT niet gezet; overslaan. Zie de kop van dit bestand.")
        return
    svc = client.spreadsheets()
    tabblad = dagen[0]["tabblad"]
    huidig = svc.values().get(spreadsheetId=SHEET_ID,
                              range=f"'{tabblad}'!A1:K60").execute().get("values", [])

    def cel(rij, kol):
        r = huidig[rij - 1] if len(huidig) >= rij else []
        return (r[kol - 1] if len(r) >= kol else "") or ""

    updates = []
    for w in sorted(recent, key=lambda x: x["start_time"]):
        dag, reden = kies_dag(w, dagen)
        datum = w["start_time"][:10]
        if dag is None:
            print(f"  {datum} {w.get('title','')!r}: overgeslagen ({reden})")
            continue

        gebruikt = set()
        gevuld = 0
        for oef in w.get("exercises", []):
            titel = oef.get("title") or ""
            kandidaten = HEVY_NAAR_KAJ.get(titel, [])
            doel = None
            for o in dag["oefeningen"]:
                if o["naam"] in kandidaten and o["rij"] not in gebruikt:
                    doel = o
                    break
            if doel is None:
                continue
            gebruikt.add(doel["rij"])

            werk = [s for s in oef.get("sets", []) if s.get("type") != "warmup"]
            if not werk:
                continue
            rpes = [s["rpe"] for s in werk if s.get("rpe") is not None]
            waarden = [zet_set(s) for s in werk[:5]]

            rij = doel["rij"]
            if rpes and (overschrijf or not cel(rij, 6)):
                updates.append({"range": f"'{tabblad}'!F{rij}", "values": [[max(rpes)]]})
            for i, waarde in enumerate(waarden):
                kolom = chr(ord("G") + i)
                if waarde and (overschrijf or not cel(rij, 7 + i)):
                    updates.append({"range": f"'{tabblad}'!{kolom}{rij}", "values": [[waarde]]})
                    gevuld += 1
        print(f"  {datum} {w.get('title','')!r} -> {dag['dag']} (gekoppeld op {reden}), {gevuld} cellen")

    if not updates:
        print("Niets in te vullen; alles stond al of er was geen match.")
        return
    svc.values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "USER_ENTERED", "data": updates}).execute()
    print(f"{len(updates)} cellen bijgewerkt in de Sheet.")


if __name__ == "__main__":
    main()
