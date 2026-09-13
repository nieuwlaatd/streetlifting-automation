"""Haalt gewicht, vetpercentage en voeding uit de Google Health API.

Dylan houdt zijn eten en gewicht bij in de Google Health-app. Dit script zet
daar dagtotalen van in data/gezondheid.json, zodat het weekrapport kan zien of
de cut naar 73 kg in een verantwoord tempo gaat en of het eiwit klopt.

WAT ER WORDT OPGESLAGEN
Per dag: gemiddeld gewicht, vetpercentage, kcal, eiwit, koolhydraten en vet,
en daarnaast slaap, verbrande calorieën en stappen.
Geen losse maaltijden en geen productnamen. Het weekrapport heeft die niet
nodig, en wat niet is opgeslagen kan ook niet uitlekken.

OPENBAAR, BEWUST
De repository is openbaar, en alles in data/ is dus voor iedereen leesbaar.
Dylan heeft op 13 september 2026 besloten dat dat voor deze dagtotalen geen
bezwaar is; een privérepository vroeg extra koppelingen voor de routines.
Die keuze staat hieronder als OPENBAAR_TOEGESTAAN. Zet je die op False, dan
schrijft het script alleen nog weg in een privérepository.

VERLOPEN TOKEN
Staat de Google-app nog op "Testing", dan verloopt de refresh token na zeven
dagen. Het script schrijft dat dan als status weg, zodat het weekrapport het
meldt in plaats van stil verouderde cijfers te tonen.

Gebruik:  python scripts/google_health.py haal
          python scripts/google_health.py check token|gewicht|voeding
Nodig:    GOOGLE_HEALTH_CLIENT_ID, GOOGLE_HEALTH_CLIENT_SECRET,
          GOOGLE_HEALTH_REFRESH_TOKEN; voor 'haal' ook GITHUB_TOKEN en
          GITHUB_REPOSITORY (die zet GitHub Actions zelf)
"""

import datetime as dt
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
BASE = "https://health.googleapis.com/v4/users/me/dataTypes"
SCOPES = {
    "gewicht": "googlehealth.health_metrics_and_measurements.readonly",
    "voeding": "googlehealth.nutrition.readonly",
    "slaap": "googlehealth.sleep.readonly",
    "activiteit": "googlehealth.activity_and_fitness.readonly",
}
# Zonder deze twee heeft het rapport niets om op te sturen; slaap en activiteit
# zijn aanvulling. Ontbreekt alleen een aanvulling, dan blijft de status "ok".
KERN = ("gewicht", "voeding")
DATATYPE = {"gewicht": "weight", "voeding": "nutrition-log", "slaap": "sleep"}
PAGINAGROOTTE = {"sleep": 25}      # de API staat voor slaap niet meer toe
UITVOER = pathlib.Path("data") / "gezondheid.json"
OPENBAAR_TOEGESTAAN = True   # besluit van Dylan, 13 september 2026
DAGEN_TERUG = 42          # zes weken: genoeg voor een trend, niet meer dan nodig
MAX_PAGINAS = 20


class TokenFout(Exception):
    pass


def stop(melding):
    """Stopt met een foutmelding die als annotatie in GitHub verschijnt.

    De meldingen bevatten alleen foutcodes, nooit tokens of meetwaarden.
    """
    print(f"::error::{melding}")
    sys.exit(1)


# ---------------------------------------------------------------- toegang

def toegangstoken():
    """Wisselt de refresh token in voor een kortlevend toegangstoken."""
    velden = {k: os.environ.get(v, "").strip() for k, v in (
        ("client_id", "GOOGLE_HEALTH_CLIENT_ID"),
        ("client_secret", "GOOGLE_HEALTH_CLIENT_SECRET"),
        ("refresh_token", "GOOGLE_HEALTH_REFRESH_TOKEN"))}
    ontbreekt = [k for k, v in velden.items() if not v]
    if ontbreekt:
        raise TokenFout(f"secrets ontbreken: {', '.join(ontbreekt)}")
    velden["grant_type"] = "refresh_token"
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(velden).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            antwoord = json.load(r)
    except urllib.error.HTTPError as fout:
        try:
            fj = json.loads(fout.read().decode())
            code = f"{fj.get('error', '')} ({fj.get('error_description', '')})"
        except Exception:
            code = ""
        raise TokenFout(f"token vernieuwen mislukt: HTTP {fout.code} {code}")
    token = antwoord.get("access_token")
    if not token:
        raise TokenFout("geen toegangstoken ontvangen")
    print(f"::add-mask::{token}")
    return token, set((antwoord.get("scope") or "").split())


def repo_is_prive():
    """Vraagt GitHub of deze repository privé is. Bij twijfel: nee."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not repo:
        return False
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}",
                                 headers={"Accept": "application/vnd.github+json",
                                          **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("private") is True
    except Exception:
        return False


# ---------------------------------------------------------------- ophalen

def foutuitleg(fout):
    """De uitleg die Google bij een foutcode meestuurt. Bevat geen meetwaarden."""
    try:
        return json.loads(fout.read().decode()).get("error", {}).get("message", "")[:300]
    except Exception:
        return ""


def _get(url, token):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def haal_punten(datatype, token, sinds):
    """Alle meetpunten van een datatype vanaf een datum.

    De API filtert op tijd, maar het veld verschilt per soort meting en staat
    niet overal gedocumenteerd. Werkt het filter niet, dan pagineren we zonder
    filter en sorteren we zelf; dat is trager, maar geeft hetzelfde resultaat.
    """
    snake = datatype.replace("-", "_")
    filters = [f'{snake}.interval.start_time >= "{sinds}T00:00:00Z"',
               f'{snake}.sample_time.physical_time >= "{sinds}T00:00:00Z"',
               None]
    for filt in filters:
        punten, pagina_token = [], None
        try:
            for _ in range(MAX_PAGINAS):
                params = {"page_size": PAGINAGROOTTE.get(datatype, 1000)}
                if filt:
                    params["filter"] = filt
                if pagina_token:
                    params["page_token"] = pagina_token
                antwoord = _get(f"{BASE}/{datatype}/dataPoints?{urllib.parse.urlencode(params)}", token)
                punten += antwoord.get("dataPoints") or []
                pagina_token = antwoord.get("nextPageToken")
                if not pagina_token:
                    break
            return punten
        except urllib.error.HTTPError as fout:
            if fout.code == 400 and filt:
                continue                      # dit filter kent de API niet
            raise
    return []


def dagtotalen(datatype, veld, token, vandaag):
    """Dagtotalen via dailyRollUp, voor metingen die per minuut binnenkomen.

    Verbrande calorieën en stappen staan niet als losse meetpunten in de API
    maar alleen als optelling. De API accepteert voor total-calories maximaal
    veertien dagen per verzoek, dus we vragen de periode in blokken op.

    Drie dingen die de API streng controleert, alle drie gevonden via een
    HTTP 400: de datum hoort in een "date"-object, de tijd moet erbij staan,
    en het bereik loopt tot en met gisteren. Vandaag is nog niet af en telt
    in de gemiddelden toch al niet mee.
    """
    uit = {}
    laatste = vandaag - dt.timedelta(days=1)
    eerste = vandaag - dt.timedelta(days=DAGEN_TERUG)
    blok_eind = laatste
    while blok_eind >= eerste:
        blok_begin = max(eerste, blok_eind - dt.timedelta(days=12))   # 13 dagen per blok
        body = {"range": {
                    "start": {"date": {"year": blok_begin.year, "month": blok_begin.month,
                                       "day": blok_begin.day},
                              "time": {"hours": 0, "minutes": 0, "seconds": 0, "nanos": 0}},
                    "end": {"date": {"year": blok_eind.year, "month": blok_eind.month,
                                     "day": blok_eind.day},
                            "time": {"hours": 23, "minutes": 59, "seconds": 59, "nanos": 0}}},
                "windowSizeDays": 1}
        req = urllib.request.Request(f"{BASE}/{datatype}/dataPoints:dailyRollUp",
                                     data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {token}",
                                              "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            antwoord = json.load(r)
        for punt in antwoord.get("rollupDataPoints") or []:
            datum = civiele_datum(punt.get("civilStartTime"))
            waarde = rollup_waarde(punt, veld)
            if datum and waarde is not None:
                uit[datum] = waarde
        if antwoord.get("rollupDataPoints"):
            DIAGNOSE[datatype] = sleutels(antwoord["rollupDataPoints"][0])
        blok_eind = blok_begin - dt.timedelta(days=1)
    return uit


DIAGNOSE = {}


def rollup_waarde(punt, veld):
    """Het getal uit een rollup-punt. De API geeft grote getallen als tekst.

    Voorbeeld uit de documentatie: {"steps": {"countSum": "3822"}}. Staat het
    verwachte veld er niet, dan pakken we het eerste veld dat op Sum eindigt.
    """
    for sleutel, inhoud in punt.items():
        if not isinstance(inhoud, dict) or sleutel.startswith("civil"):
            continue
        kandidaten = [inhoud.get(veld)] + [v for k, v in inhoud.items() if k.endswith("Sum")]
        for waarde in kandidaten:
            try:
                return float(waarde)
            except (TypeError, ValueError):
                continue
    return None


# ---------------------------------------------------------------- ontleden

def civiele_datum(obj):
    """Een datum uit {"date": {"year": .., "month": .., "day": ..}} of een variant."""
    if not isinstance(obj, dict):
        return None
    d = obj.get("date", obj)
    try:
        return dt.date(int(d["year"]), int(d["month"]), int(d["day"])).isoformat()
    except (KeyError, TypeError, ValueError):
        return None


ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def eerste_tijd(obj):
    """Het eerste ISO-tijdstip in een geneste structuur, als datum."""
    if isinstance(obj, str) and ISO.match(obj):
        return obj[:10]
    if isinstance(obj, dict):
        # Voorkeur voor begin- of meettijd boven eindtijd.
        for sleutel in ("startTime", "physicalTime", "time", "civilTime"):
            if sleutel in obj:
                gevonden = eerste_tijd(obj[sleutel])
                if gevonden:
                    return gevonden
        for waarde in obj.values():
            gevonden = eerste_tijd(waarde)
            if gevonden:
                return gevonden
    if isinstance(obj, list):
        for waarde in obj:
            gevonden = eerste_tijd(waarde)
            if gevonden:
                return gevonden
    return None


def getal(obj, voorkeur):
    """Eerste getal in een hoeveelheid, omgerekend naar de gewenste eenheid.

    De API geeft hoeveelheden als objecten, bijvoorbeeld {"kcal": 165} of
    {"grams": 20}. Welke sleutel precies gebruikt wordt, verschilt per veld;
    daarom zoeken we op eenheid in plaats van op vaste namen.
    """
    if isinstance(obj, (int, float)):
        return float(obj)
    if not isinstance(obj, dict):
        return None
    omrekening = {"gram": {"grams": 1, "gram": 1, "milligrams": 0.001, "micrograms": 1e-6,
                           "kilograms": 1000},
                  "kcal": {"kcal": 1, "kilocalories": 1, "calories": 1, "joules": 1 / 4184,
                           "kilojoules": 1 / 4.184}}[voorkeur]
    for sleutel, factor in omrekening.items():
        for k, v in obj.items():
            if k.lower() == sleutel and isinstance(v, (int, float)):
                return float(v) * factor
    for v in obj.values():
        if isinstance(v, (int, float)):
            return float(v)
    return None


def eiwit_uit(log):
    """Eiwit staat in de lijst 'nutrients' als een van de voedingsstoffen."""
    for n in log.get("nutrients") or []:
        naam = json.dumps({k: v for k, v in n.items() if isinstance(v, str)}).lower()
        if "protein" in naam:
            for k, v in n.items():
                if isinstance(v, dict):
                    waarde = getal(v, "gram")
                    if waarde is not None:
                        return waarde
    return None


def slaap_per_nacht(slaap):
    """Minuten slaap per nacht, toegekend aan de dag waarop hij wakker werd.

    Een nacht van zondag op maandag hoort bij maandag: dat is de dag waarop die
    slaap zijn effect heeft op de training. Dutjes tellen mee bij die dag.
    """
    uit = {}
    for p in slaap:
        s = p.get("sleep") or {}
        interval = s.get("interval") or {}
        datum = (civiele_datum(interval.get("civilEndTime"))
                 or lokale_datum(interval.get("endTime"), interval.get("endUtcOffset")))
        # De API geeft minuten als tekst: {"minutesAsleep": "402"}.
        try:
            minuten = float((s.get("summary") or {}).get("minutesAsleep"))
        except (TypeError, ValueError):
            continue
        if datum and 0 < minuten < 24 * 60:
            uit[datum] = uit.get(datum, 0) + minuten
    return uit


def lokale_datum(tijd, offset):
    """UTC-tijd plus offset ("7200s") naar de datum in Dylans eigen tijdzone.

    Wakker om 00:30 in Nederland is 22:30 UTC de dag ervoor; zonder de offset
    zou die nacht bij de verkeerde dag horen.
    """
    if not isinstance(tijd, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(tijd.replace("Z", "+00:00"))
        seconden = float(str(offset or "0").rstrip("s"))
        return (moment + dt.timedelta(seconds=seconden)).date().isoformat()
    except ValueError:
        return tijd[:10] if ISO.match(tijd) else None


def per_dag(gewicht, vet, voeding, slaap=None, verbrand=None, stappen=None):
    slaap, verbrand, stappen = slaap or {}, verbrand or {}, stappen or {}
    dagen = {}

    def dag(datum):
        return dagen.setdefault(datum, {"gewicht": [], "vet": [], "kcal": 0.0, "eiwit": 0.0,
                                        "koolhydraten": 0.0, "vetgram": 0.0, "logs": 0,
                                        "eiwit_bekend": False})

    for datum in set(slaap) | set(verbrand) | set(stappen):
        dag(datum)

    for p in gewicht:
        w = p.get("weight") or {}
        datum, gram = eerste_tijd(w.get("sampleTime") or p), w.get("weightGrams")
        if datum and isinstance(gram, (int, float)) and 30000 < gram < 200000:
            dag(datum)["gewicht"].append(gram / 1000)
    for p in vet:
        b = p.get("bodyFat") or {}
        datum, pct = eerste_tijd(b.get("sampleTime") or p), b.get("percentage")
        if datum and isinstance(pct, (int, float)) and 2 < pct < 60:
            dag(datum)["vet"].append(pct)
    for p in voeding:
        log = p.get("nutritionLog") or {}
        datum = eerste_tijd(log.get("interval") or p)
        if not datum:
            continue
        d = dag(datum)
        d["logs"] += 1
        d["kcal"] += getal(log.get("energy"), "kcal") or 0
        d["koolhydraten"] += getal(log.get("totalCarbohydrate"), "gram") or 0
        d["vetgram"] += getal(log.get("totalFat"), "gram") or 0
        eiwit = eiwit_uit(log)
        if eiwit is not None:
            d["eiwit"] += eiwit
            d["eiwit_bekend"] = True

    uit = []
    for datum in sorted(dagen):
        d = dagen[datum]
        uit.append({
            "datum": datum,
            "gewicht_kg": round(sum(d["gewicht"]) / len(d["gewicht"]), 2) if d["gewicht"] else None,
            "vet_pct": round(sum(d["vet"]) / len(d["vet"]), 1) if d["vet"] else None,
            "kcal": round(d["kcal"]) if d["logs"] else None,
            "eiwit_g": round(d["eiwit"]) if d["eiwit_bekend"] else None,
            "koolhydraten_g": round(d["koolhydraten"]) if d["logs"] else None,
            "vet_g": round(d["vetgram"]) if d["logs"] else None,
            "voedingslogs": d["logs"],
            "slaap_uur": round(slaap[datum] / 60, 2) if datum in slaap else None,
            "verbrand_kcal": round(verbrand[datum]) if datum in verbrand else None,
            "stappen": round(stappen[datum]) if datum in stappen else None,
        })
    return uit


def gemiddelde(rijen, veld):
    waarden = [r[veld] for r in rijen if r.get(veld) is not None]
    return round(sum(waarden) / len(waarden), 2) if waarden else None


def samenvatting(dagen, vandaag):
    """Wat het weekrapport nodig heeft, al uitgerekend."""
    def venster(van, tot):
        return [r for r in dagen
                if van <= (vandaag - dt.date.fromisoformat(r["datum"])).days < tot]

    deze, vorige = venster(0, 7), venster(7, 14)
    # Voeding van vandaag is nog niet af: om 07:15 staat alleen het ontbijt
    # erin. Die dag telt daarom niet mee in de voedingsgemiddelden.
    eten = venster(1, 8)
    gew_nu, gew_vorig = gemiddelde(deze, "gewicht_kg"), gemiddelde(vorige, "gewicht_kg")
    eiwit = gemiddelde(eten, "eiwit_g")
    return {
        "gewicht_7d_kg": gew_nu,
        "gewicht_vorige_7d_kg": gew_vorig,
        "verandering_per_week_kg": round(gew_nu - gew_vorig, 2)
        if gew_nu is not None and gew_vorig is not None else None,
        "nog_af_tot_73_kg": round(gew_nu - 73, 1) if gew_nu is not None else None,
        "vet_pct_7d": gemiddelde(deze, "vet_pct"),
        "kcal_7d": gemiddelde(eten, "kcal"),
        "eiwit_7d_g": eiwit,
        "eiwit_per_kg": round(eiwit / gew_nu, 2) if eiwit and gew_nu else None,
        "dagen_met_voeding_7d": sum(1 for r in eten if r["voedingslogs"]),
        "dagen_met_gewicht_7d": sum(1 for r in deze if r["gewicht_kg"] is not None),
        # Slaap van vandaag is de afgelopen nacht en dus compleet; calorieën en
        # stappen van vandaag zijn dat niet en tellen daarom niet mee.
        "slaap_7d_uur": gemiddelde(deze, "slaap_uur"),
        "kortste_nacht_7d_uur": min((r["slaap_uur"] for r in deze if r.get("slaap_uur")),
                                    default=None),
        "nachten_onder_6u_7d": sum(1 for r in deze if r.get("slaap_uur") and r["slaap_uur"] < 6),
        "verbrand_7d_kcal": gemiddelde(eten, "verbrand_kcal"),
        "stappen_7d": gemiddelde(eten, "stappen"),
        # Alleen dagen waarop zowel eten als verbranding bekend is, anders zou
        # een vergeten eetlog een fictief groot tekort opleveren.
        "energiebalans_7d_kcal": gemiddelde(
            [{"b": r["kcal"] - r["verbrand_kcal"]} for r in eten
             if r.get("kcal") and r.get("verbrand_kcal")], "b"),
    }


def sleutels(obj):
    """De structuur van een object zonder de waarden erin."""
    if isinstance(obj, dict):
        return {k: sleutels(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sleutels(obj[0])] if obj else []
    return type(obj).__name__


def schrijf(inhoud):
    UITVOER.parent.mkdir(exist_ok=True)
    UITVOER.write_text(json.dumps(inhoud, indent=1, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- modi

def haal():
    if not OPENBAAR_TOEGESTAAN and not repo_is_prive():
        print("::warning::Repository is niet privé en OPENBAAR_TOEGESTAAN staat uit; "
              "gezondheidsgegevens worden niet opgeslagen.")
        return
    nu = dt.datetime.now(dt.timezone.utc)
    vandaag = nu.date()
    sinds = (vandaag - dt.timedelta(days=DAGEN_TERUG)).isoformat()
    try:
        token, scopes = toegangstoken()
    except TokenFout as fout:
        # Wel wegschrijven dat het misging: zonder die regel toont het
        # weekrapport de cijfers van vorige week alsof ze vers zijn.
        vorig = json.loads(UITVOER.read_text(encoding="utf-8")) if UITVOER.exists() else {}
        vorig.update({"status": "token_verlopen_of_ongeldig", "fout": str(fout),
                      "gecontroleerd": nu.isoformat(timespec="seconds")})
        schrijf(vorig)
        stop(f"Google Health: {fout}")

    ontbreekt = [n for n, s in SCOPES.items() if not any(x.endswith(s) for x in scopes)]
    try:
        gewicht = haal_punten("weight", token, sinds) if "gewicht" not in ontbreekt else []
        vet = haal_punten("body-fat", token, sinds) if "gewicht" not in ontbreekt else []
        voeding = haal_punten("nutrition-log", token, sinds) if "voeding" not in ontbreekt else []
    except urllib.error.HTTPError as fout:
        stop(f"Google Health: HTTP {fout.code} bij ophalen")

    # Aanvullingen: een fout hier mag gewicht en voeding niet tegenhouden.
    slaap, verbrand, stappen, fouten = [], {}, {}, []
    if "slaap" not in ontbreekt:
        try:
            slaap = haal_punten("sleep", token, sinds)
        except urllib.error.HTTPError as fout:
            fouten.append(f"slaap: HTTP {fout.code}")
    if "activiteit" not in ontbreekt:
        for naam, datatype, veld, doel in (("verbrand", "total-calories", "kcalSum", verbrand),
                                            ("stappen", "steps", "countSum", stappen)):
            try:
                doel.update(dagtotalen(datatype, veld, token, vandaag))
            except urllib.error.HTTPError as fout:
                fouten.append(f"{naam}: HTTP {fout.code} {foutuitleg(fout)}")
    for f in fouten:
        print(f"::warning::Google Health {f}")

    dagen = per_dag(gewicht, vet, voeding, slaap_per_nacht(slaap), verbrand, stappen)
    schrijf({
        "status": "ok" if not any(k in ontbreekt for k in KERN) else "rechten_ontbreken",
        "fouten_aanvulling": fouten,
        "rechten_ontbreken": ontbreekt,
        "opgehaald": nu.isoformat(timespec="seconds"),
        "bron": "Google Health API",
        "streefgewicht_kg": 73,
        "samenvatting": samenvatting(dagen, vandaag),
        # Alleen de veldnamen van het eerste meetpunt, geen waarden. Geeft de
        # API een andere structuur dan gedocumenteerd, dan is hieraan te zien
        # waarom een kolom leeg blijft.
        "_veldnamen": {naam: sleutels(punten[0]) if punten else None
                       for naam, punten in (("weight", gewicht), ("body-fat", vet),
                                            ("nutrition-log", voeding), ("sleep", slaap))},
        "_veldnamen_rollup": DIAGNOSE,
        "dagen": dagen,
    })
    # Alleen aantallen in de log; de waarden staan in het privébestand.
    print(f"{len(dagen)} dagen weggeschreven ({len(gewicht)} wegingen, "
          f"{len(voeding)} voedingslogs, {len(slaap)} slaapsessies, "
          f"{len(verbrand)} dagen verbranding).")


def check(onderdeel):
    try:
        token, scopes = toegangstoken()
    except TokenFout as fout:
        stop(str(fout))
    if onderdeel == "token":
        mist = [n for n, s in SCOPES.items() if not any(x.endswith(s) for x in scopes)]
        if mist:
            stop(f"Token werkt, maar mist rechten voor: {', '.join(mist)}")
        print("Token vernieuwd; alle rechten aanwezig.")
        return
    if onderdeel == "activiteit":
        # Verbrande calorieën bestaan alleen als dagtotaal, niet als lijst.
        try:
            totalen = dagtotalen("total-calories", "kcalSum", token, dt.date.today())
        except urllib.error.HTTPError as fout:
            stop(f"total-calories: HTTP {fout.code} {foutuitleg(fout)}")
        if not totalen:
            stop("activiteit: API bereikbaar, maar geen verbrande calorieën gevonden. "
                 f"Structuur: {json.dumps(DIAGNOSE)[:400]}")
        print(f"activiteit: {len(totalen)} dagen met verbrande calorieën.")
        return
    if onderdeel not in DATATYPE:
        stop(f"Onbekend onderdeel: {onderdeel}")
    try:
        antwoord = _get(f"{BASE}/{DATATYPE[onderdeel]}/dataPoints?page_size=5", token)
    except urllib.error.HTTPError as fout:
        stop(f"{DATATYPE[onderdeel]}: HTTP {fout.code}")
    punten = antwoord.get("dataPoints") or []
    if not punten:
        stop(f"{onderdeel}: API bereikbaar, maar geen meetpunten gevonden.")
    print(f"{onderdeel}: {len(punten)} meetpunten gelezen.")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "haal":
        haal()
    elif len(sys.argv) == 3 and sys.argv[1] == "check":
        check(sys.argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
