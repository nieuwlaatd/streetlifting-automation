"""Zet gelogde Hevy-sessies over naar de Google Sheet van coach Kaj.

Kaj wil de werkelijke uitvoering in zijn Sheet zien: per oefening de RPE in
kolom F, de sets in G tot en met K, en in L waar het van zijn plan afweek.
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
    "Pull Up": ["Competition Pull-Up", "Diagonal Bodyweight Pull-up", "3s Tempo Pull-Up"],
    "Incline Bench Press (Dumbbell)": ["45 degree Incline Dumbbell Press"],
    "Lateral Raise (Cable)": ["Cable Side Raise"],
    "Single Arm Lateral Raise (Cable)": ["Cable Side Raise"],
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
        delen.append(f"{len(werk)} van {gepland_sets[0]} sets")
    gepland_reps = bereik(plan["reps"])
    if gepland_reps:
        gedaan = [s.get("reps") or 0 for s in werk]
        if any(not (gepland_reps[0] <= r <= gepland_reps[1]) for r in gedaan):
            lo, hi = min(gedaan), max(gedaan)
            gepland_tekst = (f"{gepland_reps[0]}-{gepland_reps[1]}"
                             if gepland_reps[0] != gepland_reps[1] else str(gepland_reps[0]))
            delen.append((f"reps {lo}-{hi}" if lo != hi else f"reps {lo}")
                         + f" i.p.v. {gepland_tekst}")
    if "Single Arm" in hevy_titel:
        delen.append(f"variant: {hevy_titel}")
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


def opmaak_netjes(svc, blad_id, tabblad, rijen, kop_rijen):
    """Laat kolom L en M meelopen met de opmaak die de coach al gebruikt.

    Kaj kleurt zijn dagblokken: groen voor squat, blauw voor dip, grijs voor
    assistentie, goud voor de kopregel. Vanaf rij 28 zijn L en M bovendien al
    zwart, dus zonder deze stap staat de toegevoegde tekst daar zwart op zwart.
    Elke cel die wij schrijven krijgt daarom de achtergrond van kolom A op
    diezelfde rij, met een letterkleur die daar leesbaar op is.
    """
    if blad_id is None or not (rijen or kop_rijen):
        return
    alle = sorted(set(rijen) | set(kop_rijen))
    grid = svc.get(spreadsheetId=SHEET_ID, includeGridData=True,
                   ranges=[f"'{tabblad}'!A1:M{max(alle)}"],
                   fields="sheets(data(rowData(values(effectiveFormat(backgroundColor)))))"
                   ).execute()
    rijdata = grid["sheets"][0]["data"][0].get("rowData", [])

    def achtergrond(rij):
        if rij - 1 >= len(rijdata):
            return None
        waarden = rijdata[rij - 1].get("values") or []
        if not waarden:
            return None
        return (waarden[0].get("effectiveFormat") or {}).get("backgroundColor")

    verzoeken = []
    for rij in alle:
        kleur = achtergrond(rij)
        if not kleur:
            continue
        # Helderheid bepaalt of zwarte of witte letters leesbaar zijn.
        helder = (0.299 * kleur.get("red", 1) + 0.587 * kleur.get("green", 1)
                  + 0.114 * kleur.get("blue", 1))
        letter = {"red": 0, "green": 0, "blue": 0} if helder > 0.55 else {"red": 1, "green": 1, "blue": 1}
        verzoeken.append({
            "repeatCell": {
                "range": {"sheetId": blad_id, "startRowIndex": rij - 1, "endRowIndex": rij,
                          "startColumnIndex": 11, "endColumnIndex": 13},
                "cell": {"userEnteredFormat": {
                    "backgroundColor": kleur,
                    "textFormat": {"foregroundColor": letter,
                                   "bold": rij in kop_rijen, "fontSize": 10},
                    "wrapStrategy": "CLIP",
                }},
                "fields": ("userEnteredFormat(backgroundColor,textFormat.foregroundColor,"
                           "textFormat.bold,textFormat.fontSize,wrapStrategy)"),
            }})
    verzoeken.append({"updateDimensionProperties": {
        "range": {"sheetId": blad_id, "dimension": "COLUMNS",
                  "startIndex": 11, "endIndex": 13},
        "properties": {"pixelSize": 260}, "fields": "pixelSize"}})
    svc.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": verzoeken}).execute()
    print(f"opmaak van L en M gelijkgetrokken op {len(verzoeken)-1} rijen.")


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
    meta = svc.get(spreadsheetId=SHEET_ID).execute()
    blad_id = next((b["properties"]["sheetId"] for b in meta["sheets"]
                    if b["properties"]["title"] == tabblad), None)
    huidig = svc.values().get(spreadsheetId=SHEET_ID,
                              range=f"'{tabblad}'!A1:K60").execute().get("values", [])

    def cel(rij, kol):
        r = huidig[rij - 1] if len(huidig) >= rij else []
        return (r[kol - 1] if len(r) >= kol else "") or ""

    updates, opmaak_rijen, geraakte_rijen, kop_rijen = [], [], [], []
    for w in sorted(recent, key=lambda x: x["start_time"]):
        dag, reden = kies_dag(w, dagen)
        datum = w["start_time"][:10]
        if dag is None:
            print(f"  {datum} {w.get('title','')!r}: overgeslagen ({reden})")
            continue

        kop_rijen.append(dag["kop_rij"] + 1)     # de OEFENING|SETS|... regel
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
            notitie_tekst = oef.get("notes") or ""

            # De notitie draagt data die Hevy niet kwijt kan: gewicht bij een
            # oefening zonder gewichtsveld, of een RPE onder de 6. Die telt dus
            # even zwaar mee als de velden zelf.
            uit_notitie = notities.lees_setgewichten(notitie_tekst, len(werk))
            if uit_notitie and not any(s.get("weight_kg") for s in werk):
                werk = [dict(s, weight_kg=g) for s, g in zip(werk, uit_notitie)]

            # RPE per set, in dezelfde volgorde als de kolommen G tot en met K.
            # Een enkel getal zegt niets over of het opliep binnen de oefening;
            # 6, 6, 8 vertelt de coach iets anders dan 8, 8, 8.
            per_set = [s.get("rpe") for s in werk]
            notitie_rpes, gold_voor_alle = notities.lees_rpes(notitie_tekst)
            # De notitie wint van het veld als hij zegt dat het veld niet klopte.
            if notitie_rpes and (not any(x is not None for x in per_set)
                                 or notities.corrigeert_veld(notitie_tekst)):
                if gold_voor_alle:
                    per_set = [notitie_rpes[0]] * len(werk)
                else:
                    per_set = [notitie_rpes[i] if i < len(notitie_rpes) else None
                               for i in range(len(werk))]
            rpes = [x for x in per_set if x is not None]
            # Kolom F vat samen: het bereik waarbinnen de oefening viel.
            # De RPE per set staat bij de set zelf, in G tot en met K.
            if not rpes:
                rpe_tekst = ""
            elif min(rpes) == max(rpes):
                rpe_tekst = f"{min(rpes):g}"
            else:
                rpe_tekst = f"{min(rpes):g}-{max(rpes):g}"

            waarden = [zet_set(s, r) for s, r in zip(werk[:5], per_set[:5])]

            rij = doel["rij"]
            # Een eerdere versie schreef met USER_ENTERED, waardoor Google van
            # een RPE-bereik als "6-7" de datum 6 juli maakte. In plaats van te
            # raden hoe zo'n verminkte cel eruitziet, beschrijven we wat een
            # geldige RPE is: een getal of een bereik tussen 1 en 10. Alles
            # daarbuiten is geen RPE en mag overschreven worden.
            # Kolom F krijgt altijd een GETAL, nooit een bereik. Een tekst als
            # "6-7" werd door Google als datum gelezen; met een getal kan die
            # hele klasse fouten niet meer optreden. Varieerde de RPE over de
            # sets, dan staat dat in kolom L.
            bestaand_f = str(cel(rij, 6)).strip()
            # Geldig is een reeks als "6", "8.5" of "6, 6, 8"; alles anders
            # (bijvoorbeeld een datum uit een oudere versie) mag overschreven.
            # Geldig is "6", "8.5" of een bereik als "6-8". Een datum uit een
            # oudere versie heeft twee streepjes en valt dus af.
            al_ingevuld = bool(re.fullmatch(
                r"\d{1,2}([.,]\d)?(\s*-\s*\d{1,2}([.,]\d)?)?", bestaand_f))
            if rpe_tekst and (overschrijf or not al_ingevuld):
                updates.append({"range": f"'{tabblad}'!F{rij}", "values": [[rpe_tekst]]})
                opmaak_rijen.append(rij)
            for i, waarde in enumerate(waarden):
                kolom = chr(ord("G") + i)
                if waarde and (overschrijf or not cel(rij, 7 + i)):
                    updates.append({"range": f"'{tabblad}'!{kolom}{rij}", "values": [[waarde]]})
                    gevuld += 1
            # Kolom L: waar de uitvoering van het plan afweek. Kaj ziet zo in
            # een oogopslag het verschil tussen wat hij vroeg en wat er gebeurde.
            if overschrijf or not cel(rij, 12):
                updates.append({"range": f"'{tabblad}'!L{rij}",
                                "values": [[afwijking(doel, werk, titel)]]})
            if notitie_tekst and (overschrijf or not cel(rij, 13)):
                updates.append({"range": f"'{tabblad}'!M{rij}",
                                "values": [[notities.samenvatting(notitie_tekst)]]})
            geraakte_rijen.append(rij)
        print(f"  {datum} {w.get('title','')!r} -> {dag['dag']} (gekoppeld op {reden}), {gevuld} cellen")

    vandaag = dt.date.today()
    for dag in dagen:
        gepland = dag.get("datum")
        if not gepland or dt.date.fromisoformat(gepland) <= vandaag:
            continue
        rijen = [o["rij"] for o in dag["oefeningen"]]
        if any(cel(r, c) for r in rijen for c in range(6, 14)):
            print(f"  {dag['dag']} ({gepland}) ligt in de toekomst; ingevulde cellen worden gewist")
            for r in rijen:
                updates.append({"range": f"'{tabblad}'!F{r}:M{r}",
                                "values": [[""] * 8]})

    for kop in sorted(set(kop_rijen)):
        if overschrijf or not cel(kop, 12):
            updates.append({"range": f"'{tabblad}'!L{kop}:M{kop}",
                            "values": [["AFWIJKING VAN PLAN", "NOTITIE DYLAN"]]})

    if not updates:
        print("Niets in te vullen; alles stond al of er was geen match.")
        return
    svc.values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "RAW", "data": updates}).execute()
    print(f"{len(updates)} cellen bijgewerkt in de Sheet.")

    opmaak_netjes(svc, blad_id, tabblad, geraakte_rijen, kop_rijen)

    # Een cel die ooit een datum bevatte houdt die opmaak vast. Kolom F krijgt
    # daarom expliciet tekstopmaak: een reeks als "6, 6, 8" is geen getal, en zo
    # kan Google er ook nooit meer iets anders van maken.
    if opmaak_rijen and blad_id is not None:
        verzoeken = [{
            "repeatCell": {
                "range": {"sheetId": blad_id, "startRowIndex": r - 1, "endRowIndex": r,
                          "startColumnIndex": 5, "endColumnIndex": 6},
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "TEXT"}}},
                "fields": "userEnteredFormat.numberFormat",
            }} for r in sorted(set(opmaak_rijen))]
        svc.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": verzoeken}).execute()
        print(f"opmaak hersteld op {len(verzoeken)} RPE-cellen.")


if __name__ == "__main__":
    main()
