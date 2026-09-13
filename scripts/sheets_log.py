"""Zet gelogde Hevy-sessies over naar de Google Sheet van coach Kaj.

Kaj wil de werkelijke uitvoering in zijn Sheet zien: per oefening de RPE in
kolom F, de sets in G tot en met K, en in L waar het van zijn plan afweek.
Die letters gelden voor week 1; elke volgende week staat 18 kolommen verder
(week 2 begint in S), en alles schuift mee.
Zijn eigen kolommen A tot en met E blijven onaangeroerd, zodat het voorschrift
en de uitvoering naast elkaar staan in plaats van door elkaar. Dit script leest de laatste sessies uit
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
import re
import sys
import urllib.error
import urllib.request

import notities

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
    "Pull Up (Weighted)": ["Competition Pull-Up", "3s Tempo Pull-Up"],
    "Pull Up": ["Diagonal Bodyweight Pull-up", "Competition Pull-Up", "3s Tempo Pull-Up"],
    "Incline Bench Press (Dumbbell)": ["45 degree Incline Dumbbell Press"],
    "Lateral Raise (Cable)": ["Cable Side Raise"],
    "Single Arm Lateral Raise (Cable)": ["Cable Side Raise"],
    "Plate Loaded Knee Raise": ["Plate Loaded Knee Raise"],
    "Knee Raise Parallel Bars": ["Plate Loaded Knee Raise"],
    "Hanging Knee Raise": ["Plate Loaded Knee Raise", "Cable Knee Tuck"],
    "Skullcrusher (Dumbbell)": ["Skull Crusher"],
    "Squat (Barbell)": ["3-1-0 Tempo Squat", "Competition Squat"],
    "Pause Squat (Barbell)": ["Paused Squat", "2s Paused Squat"],
    "Straight Arm Lat Pulldown (Cable)": ["Bar Cable Pullover"],
    "Pullover (Machine)": ["Bar Cable Pullover"],       # zo gelogd op 9 september
    "Leg Extension (Machine)": ["Leg Extension"],
    "Seated Cable Row - Bar Grip": ["Cable row"],
    "Spider Curl (Dumbbell)": ["Spider Curl"],
    "Bench Press (Barbell)": ["Close Grip Larsen Press"],
    "Cable Fly Crossovers": ["Cable Fly"],
    "Chest Fly (Machine)": ["Cable Fly"],
    "Chest Fly (Dumbbell)": ["Cable Fly"],
    "Cable Knee Tuck": ["Cable Knee Tuck"],
    "Crunch (Machine)": ["Cable Knee Tuck"],
    "Cable Crunch": ["Cable Knee Tuck"],
    "Ab Wheel": ["Ab Roll Out"],
    "Band Assisted Muscle-Up": ["Band Assisted Muscle-Up"],
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


def zet_set(s, rpe=None):
    """Een set als leesbare tekst: gewicht, reps en de RPE van die set.

    Bijvoorbeeld "10x9 @6". De RPE hoort bij de set en niet bij de oefening,
    dus die staat hier en niet alleen in de samenvattende kolom.
    """
    g, reps = s.get("weight_kg"), s.get("reps")
    if reps is None:
        return ""
    basis = f"{g:g}x{reps}" if g else f"BWx{reps}"
    return f"{basis} @{rpe:g}" if rpe is not None else basis


def bereik(tekst):
    """'6-12' wordt (6, 12); '3' wordt (3, 3); 'x' wordt None."""
    if "-" in str(tekst):
        a, b = str(tekst).split("-")[:2]
        try:
            return int(a), int(b)
        except ValueError:
            return None
    try:
        n = int(float(tekst))
        return n, n
    except (ValueError, TypeError):
        return None


def afwijking(plan, werk, hevy_titel):
    """Beschrijft in het kort hoe de uitvoering zich tot het plan verhoudt.

    Dit is de reden dat er een kolom L bijkomt: zonder zo'n regel ziet de coach
    wel de gedraaide sets, maar niet waar die van zijn voorschrift afweken.
    """
    delen = []
    gepland_sets = bereik(plan["sets"])
    if gepland_sets and len(werk) != gepland_sets[0]:
        delen.append(f"{len(werk)} sets i.p.v. {gepland_sets[0]}")
    gepland_reps = bereik(plan["reps"])
    if gepland_reps:
        gedaan = [s.get("reps") or 0 for s in werk]
        if any(not (gepland_reps[0] <= r <= gepland_reps[1]) for r in gedaan):
            lo, hi = min(gedaan), max(gedaan)
            gepland_tekst = (f"{gepland_reps[0]}-{gepland_reps[1]}"
                             if gepland_reps[0] != gepland_reps[1] else str(gepland_reps[0]))
            delen.append((f"reps {lo}-{hi}" if lo != hi else f"reps {lo}")
                         + f" i.p.v. {gepland_tekst}")
    return "; ".join(delen) if delen else "volgens plan"


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

    def plausibel(dag):
        """Kan deze sessie bij deze geplande dag horen, qua datum?

        Zonder deze grens koppelde een sessie van 4 september zich aan de
        zaterdag van 12 september, puur omdat de oefeningen leken. Een training
        kan een dag vroeg zijn of een paar dagen ingehaald worden, maar niet
        acht dagen voor het schema uit lopen.
        """
        gepland = dag.get("datum")
        if not gepland:
            return True                     # geen datum bekend: niet blokkeren
        verschil = (datum - dt.date.fromisoformat(gepland)).days
        return -1 <= verschil <= 6

    kandidaten = [d for d in dagen if plausibel(d)]
    if not kandidaten:
        return None, "valt buiten het datumbereik van elke geplande dag"

    op_weekdag = [d for d in kandidaten if d["weekdag"] == datum.weekday()]
    if op_weekdag and overlap(op_weekdag[0]) >= 2:
        return op_weekdag[0], "weekdag"
    beste = max(kandidaten, key=overlap)
    return (beste, "oefeningen") if overlap(beste) >= 3 else (None, "te weinig overlap")


def letter(n):
    """Kolomnummer (1 = A) naar kolomletters: 19 wordt S, 31 wordt AE."""
    uit = ""
    while n:
        n, rest = divmod(n - 1, 26)
        uit = chr(65 + rest) + uit
    return uit


class Blok:
    """De kolommen van een weekblok.

    Kaj zet elke week naast de vorige: week 1 begint in kolom A, week 2 in
    kolom S. Binnen een blok is de indeling steeds gelijk, dus alles volgt uit
    de beginkolom. Voorheen stonden F tot en met M hier vast, waardoor week 2
    over week 1 heen geschreven zou worden.
    """

    def __init__(self, dag):
        self.tab = dag["tabblad"]
        self.start = dag.get("kolom", 1)
        self.rpe = self.start + 5               # WERKELIJKE RPE, in week 1 kolom F
        self.eerste_set = self.start + 6        # Set 1, in week 1 kolom G
        self.afwijking = self.start + 11        # in week 1 kolom L
        self.notitie = self.start + 12          # in week 1 kolom M

    def a1(self, kolom, rij, tot=None):
        bereik = f"{letter(kolom)}{rij}" + (f":{letter(tot)}{rij}" if tot else "")
        return f"'{self.tab}'!{bereik}"


def opmaak_netjes(svc, blad_ids, doelen):
    """Laat de afwijking- en notitiekolom meelopen met Kajs opmaak.

    Kaj kleurt zijn dagblokken: groen voor squat, blauw voor dip, grijs voor
    assistentie, goud voor de kopregel. Rechts van zijn kolommen staat soms al
    een zwarte achtergrond, dus zonder deze stap staat de toegevoegde tekst
    zwart op zwart. Elke cel die wij schrijven krijgt daarom de achtergrond van
    de eerste kolom van dat blok op diezelfde rij, met een leesbare letterkleur.

    doelen: verzameling van (tabblad, beginkolom, rij, is_kopregel).
    """
    per_tab = {}
    for tab, start, rij, kop in doelen:
        per_tab.setdefault(tab, []).append((start, rij, kop))
    for tab, items in per_tab.items():
        blad_id = blad_ids.get(tab)
        if blad_id is None:
            continue
        hoogste = max(rij for _, rij, _ in items)
        grid = svc.get(spreadsheetId=SHEET_ID, includeGridData=True,
                       ranges=[f"'{tab}'!A1:AZ{hoogste}"],
                       fields="sheets(data(rowData(values(effectiveFormat(backgroundColor)))))"
                       ).execute()
        rijdata = grid["sheets"][0]["data"][0].get("rowData", [])

        def achtergrond(rij, kolom):
            if rij - 1 >= len(rijdata):
                return None
            waarden = rijdata[rij - 1].get("values") or []
            if len(waarden) < kolom:
                return None
            return (waarden[kolom - 1].get("effectiveFormat") or {}).get("backgroundColor")

        verzoeken, kolommen = [], set()
        for start, rij, kop in sorted(set(items)):
            kleur = achtergrond(rij, start)
            if not kleur:
                continue
            # Helderheid bepaalt of zwarte of witte letters leesbaar zijn.
            helder = (0.299 * kleur.get("red", 1) + 0.587 * kleur.get("green", 1)
                      + 0.114 * kleur.get("blue", 1))
            letterkleur = ({"red": 0, "green": 0, "blue": 0} if helder > 0.55
                           else {"red": 1, "green": 1, "blue": 1})
            begin = start + 10                   # 0-gebaseerd: de afwijkingkolom
            kolommen.add(begin)
            verzoeken.append({
                "repeatCell": {
                    "range": {"sheetId": blad_id, "startRowIndex": rij - 1, "endRowIndex": rij,
                              "startColumnIndex": begin, "endColumnIndex": begin + 2},
                    "cell": {"userEnteredFormat": {
                        "backgroundColor": kleur,
                        "textFormat": {"foregroundColor": letterkleur,
                                       "bold": kop, "fontSize": 10},
                        "wrapStrategy": "CLIP",
                    }},
                    "fields": ("userEnteredFormat(backgroundColor,textFormat.foregroundColor,"
                               "textFormat.bold,textFormat.fontSize,wrapStrategy)"),
                }})
        for begin in kolommen:
            verzoeken.append({"updateDimensionProperties": {
                "range": {"sheetId": blad_id, "dimension": "COLUMNS",
                          "startIndex": begin, "endIndex": begin + 2},
                "properties": {"pixelSize": 260}, "fields": "pixelSize"}})
        if verzoeken:
            svc.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": verzoeken}).execute()
            print(f"opmaak gelijkgetrokken in '{tab}': {len(verzoeken) - len(kolommen)} rijen.")


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
    meta = svc.get(spreadsheetId=SHEET_ID).execute()
    blad_ids = {b["properties"]["title"]: b["properties"]["sheetId"] for b in meta["sheets"]}

    inhoud = {}

    def cel(tab, rij, kol):
        if tab not in inhoud:
            inhoud[tab] = svc.values().get(spreadsheetId=SHEET_ID,
                                           range=f"'{tab}'!A1:AZ200").execute().get("values", [])
        waarden = inhoud[tab]
        r = waarden[rij - 1] if len(waarden) >= rij else []
        return (r[kol - 1] if len(r) >= kol else "") or ""

    updates, tekstcellen, opmaak = [], set(), set()
    for w in sorted(recent, key=lambda x: x["start_time"]):
        dag, reden = kies_dag(w, dagen)
        datum = w["start_time"][:10]
        if dag is None:
            print(f"  {datum} {w.get('title','')!r}: overgeslagen ({reden})")
            continue
        b = Blok(dag)
        kop = dag["kop_rij"] + 1                  # de OEFENING|SETS|... regel
        opmaak.add((b.tab, b.start, kop, True))

        gebruikt, gevuld, buiten = set(), 0, []
        for oef in w.get("exercises", []):
            titel = oef.get("title") or ""
            kandidaten = HEVY_NAAR_KAJ.get(titel, [])
            doel = next((o for o in dag["oefeningen"]
                         if o["naam"] in kandidaten and o["rij"] not in gebruikt), None)
            if doel is None:
                # Een oefening die niet in het plan staat. Die stil laten
                # vallen zou de coach een vertekend beeld geven: hij ziet dan
                # een lege regel en niet dat er iets anders voor in de plaats
                # kwam. Hij komt daarom onder de dagkop te staan.
                los = [s for s in oef.get("sets", []) if s.get("type") != "warmup"]
                if los:
                    buiten.append(f"{titel}: "
                                  + ", ".join(zet_set(s, s.get("rpe")) for s in los[:5]))
                continue
            gebruikt.add(doel["rij"])

            werk = [s for s in oef.get("sets", []) if s.get("type") != "warmup"]
            if not werk:
                continue
            notitie_tekst = oef.get("notes") or ""

            # De notitie draagt data die Hevy niet kwijt kan: gewicht bij een
            # oefening zonder gewichtsveld, of een RPE onder de 6. Die telt dus
            # even zwaar mee als de velden zelf.
            uit_notitie = notities.lees_setgewichten(notitie_tekst, len(werk))
            if uit_notitie and not any(s.get("weight_kg") for s in werk):
                werk = [dict(s, weight_kg=g) for s, g in zip(werk, uit_notitie)]

            # RPE per set, in dezelfde volgorde als de setkolommen. Noemt de
            # notitie een RPE, dan wint die van het gelogde veld: het RPE-veld
            # in Hevy begint bij 6, dus alles daaronder staat in de notitie.
            per_set = notities.rpe_toewijzing(notitie_tekst, len(werk),
                                              [s.get("rpe") for s in werk])
            rpes = [x for x in per_set if x is not None]
            if not rpes:
                rpe_tekst = ""
            elif min(rpes) == max(rpes):
                rpe_tekst = f"{min(rpes):g}"
            else:
                rpe_tekst = f"{min(rpes):g}-{max(rpes):g}"
            waarden = [zet_set(s, r) for s, r in zip(werk[:5], per_set[:5])]

            rij = doel["rij"]
            # Geldig is "6", "8.5" of een bereik als "6-8". Een datum uit een
            # oudere versie van dit script heeft twee streepjes en valt af.
            al_ingevuld = bool(re.fullmatch(
                r"\d{1,2}([.,]\d)?(\s*-\s*\d{1,2}([.,]\d)?)?", str(cel(b.tab, rij, b.rpe)).strip()))
            if rpe_tekst and (overschrijf or not al_ingevuld):
                updates.append({"range": b.a1(b.rpe, rij), "values": [[rpe_tekst]]})
                tekstcellen.add((b.tab, b.rpe, rij))
            for i, waarde in enumerate(waarden):
                kolom = b.eerste_set + i
                if waarde and (overschrijf or not cel(b.tab, rij, kolom)):
                    updates.append({"range": b.a1(kolom, rij), "values": [[waarde]]})
                    gevuld += 1
            # De afwijkingkolom: waar de uitvoering van het plan afweek. Kaj ziet
            # zo in een oogopslag het verschil tussen wat hij vroeg en wat er gebeurde.
            if overschrijf or not cel(b.tab, rij, b.afwijking):
                updates.append({"range": b.a1(b.afwijking, rij),
                                "values": [[afwijking(doel, werk, titel)]]})
            if notitie_tekst and (overschrijf or not cel(b.tab, rij, b.notitie)):
                updates.append({"range": b.a1(b.notitie, rij),
                                "values": [[notities.samenvatting(notitie_tekst)]]})
            opmaak.add((b.tab, b.start, rij, False))

        if buiten and (overschrijf or not cel(b.tab, dag["kop_rij"], b.notitie)):
            updates.append({"range": b.a1(b.notitie, dag["kop_rij"]),
                            "values": [["Buiten plan gedaan — " + " | ".join(buiten)]]})
            opmaak.add((b.tab, b.start, dag["kop_rij"], False))
        if overschrijf or not cel(b.tab, kop, b.afwijking):
            updates.append({"range": b.a1(b.afwijking, kop, b.notitie),
                            "values": [["AFWIJKING VAN PLAN", "NOTITIE DYLAN"]]})
        print(f"  {datum} {w.get('title','')!r} -> {dag['dag']} {dag.get('datum')} "
              f"(kolom {letter(b.start)}, gekoppeld op {reden}), {gevuld} cellen")

    # Een dag die nog moet komen hoort leeg te zijn. Staat er toch iets, dan is
    # een sessie eerder aan de verkeerde dag gekoppeld en wordt dat rechtgezet.
    vandaag = dt.date.today()
    for dag in dagen:
        gepland = dag.get("datum")
        if not gepland or dt.date.fromisoformat(gepland) <= vandaag:
            continue
        b = Blok(dag)
        rijen = [o["rij"] for o in dag["oefeningen"]]
        if any(cel(b.tab, r, k) for r in rijen for k in range(b.rpe, b.notitie + 1)):
            print(f"  {dag['dag']} ({gepland}) ligt in de toekomst; ingevulde cellen worden gewist")
            for r in rijen:
                updates.append({"range": b.a1(b.rpe, r, b.notitie),
                                "values": [[""] * (b.notitie - b.rpe + 1)]})

    if not updates:
        print("Niets in te vullen; alles stond al of er was geen match.")
        return
    svc.values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "RAW", "data": updates}).execute()
    print(f"{len(updates)} cellen bijgewerkt in de Sheet.")

    opmaak_netjes(svc, blad_ids, opmaak)

    # Een cel die ooit een datum bevatte houdt die opmaak vast. De RPE-kolom
    # krijgt daarom expliciet tekstopmaak, zodat Google er nooit meer iets
    # anders van maakt.
    verzoeken = [{
        "repeatCell": {
            "range": {"sheetId": blad_ids[tab], "startRowIndex": rij - 1, "endRowIndex": rij,
                      "startColumnIndex": kolom - 1, "endColumnIndex": kolom},
            "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
            "fields": "userEnteredFormat.numberFormat",
        }} for tab, kolom, rij in sorted(tekstcellen) if tab in blad_ids]
    if verzoeken:
        svc.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": verzoeken}).execute()
        print(f"opmaak hersteld op {len(verzoeken)} RPE-cellen.")


if __name__ == "__main__":
    main()
