"""Controleert of je Hevy API-sleutel werkt en toont je laatste sessie.

Gebruik:  python test-hevy.py
"""
import json, os, sys, urllib.request, urllib.error

BASE = "https://api.hevyapp.com"

def lees_env(pad=".env"):
    if not os.path.exists(pad):
        sys.exit("Geen .env gevonden. Draai dit script vanuit de map 'automation'.")
    waarden = {}
    for regel in open(pad, encoding="utf-8"):
        regel = regel.strip()
        if regel and not regel.startswith("#") and "=" in regel:
            sleutel, _, waarde = regel.partition("=")
            waarden[sleutel.strip()] = waarde.strip()
    return waarden

def haal(pad, key):
    verzoek = urllib.request.Request(BASE + pad, headers={"api-key": key, "Accept": "application/json"})
    with urllib.request.urlopen(verzoek, timeout=30) as antwoord:
        return json.load(antwoord)

def main():
    key = lees_env().get("HEVY_API_KEY", "")
    if not key:
        sys.exit("HEVY_API_KEY is leeg. Zet je sleutel in .env en probeer opnieuw.")

    try:
        aantal = haal("/v1/workouts/count", key)
        laatste = haal("/v1/workouts?page=1&pageSize=1", key)
    except urllib.error.HTTPError as fout:
        if fout.code == 401:
            sys.exit("401 — de sleutel wordt geweigerd. Controleer of je hem volledig hebt geplakt.")
        sys.exit(f"HTTP {fout.code} van de Hevy API: {fout.reason}")
    except urllib.error.URLError as fout:
        sys.exit(f"Geen verbinding met de Hevy API: {fout.reason}")

    print("Sleutel werkt.")
    print("Sessies op je account:", aantal.get("workout_count", "?"))

    workouts = laatste.get("workouts") or []
    if not workouts:
        print("Nog geen sessies gevonden.")
        return

    w = workouts[0]
    print(f"\nLaatste sessie: {w.get('title')}  ({w.get('start_time', '')[:10]})")
    zonder_rpe = 0
    totaal = 0
    for oef in w.get("exercises", []):
        werksets = [s for s in oef.get("sets", []) if s.get("type") != "warmup"]
        if not werksets:
            continue
        stukken = []
        for s in werksets:
            totaal += 1
            if s.get("rpe") is None:
                zonder_rpe += 1
            rpe = f" @RPE{s['rpe']}" if s.get("rpe") is not None else ""
            stukken.append(f"{s.get('weight_kg') or 0:g}x{s.get('reps') or 0}{rpe}")
        print(f"  {oef.get('title'):40s} {' | '.join(stukken)}")

    if totaal:
        print(f"\nWerksets zonder RPE: {zonder_rpe} van {totaal}.")
        if zonder_rpe:
            print("Vul RPE in op je kernlifts — zonder die waarden kan het programma")
            print("zichzelf niet herberekenen en raadt het bij elk nieuw blok.")

if __name__ == "__main__":
    main()
