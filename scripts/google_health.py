"""Leest gewicht en voeding uit de Google Health API.

Deze eerste versie controleert alleen of de koppeling werkt. Er wordt niets
weggeschreven en er komen geen waarden in de log: de repository is openbaar,
en de logs van een openbare repository zijn dat ook. Per onderdeel stopt het
script met exitcode 0 of 1, zodat de uitkomst in de stapstatus van GitHub
Actions te lezen is zonder dat er gezondheidsgegevens zichtbaar worden.

Gebruik:  python scripts/google_health.py check token|gewicht|voeding
Nodig:    GOOGLE_HEALTH_CLIENT_ID, GOOGLE_HEALTH_CLIENT_SECRET,
          GOOGLE_HEALTH_REFRESH_TOKEN
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://oauth2.googleapis.com/token"
BASE = "https://health.googleapis.com/v4/users/me/dataTypes"
SCOPES = {
    "gewicht": "googlehealth.health_metrics_and_measurements.readonly",
    "voeding": "googlehealth.nutrition.readonly",
}
DATATYPE = {"gewicht": "weight", "voeding": "nutrition-log"}


def toegangstoken():
    """Wisselt de refresh token in voor een kortlevend toegangstoken."""
    velden = {k: os.environ.get(v, "").strip() for k, v in (
        ("client_id", "GOOGLE_HEALTH_CLIENT_ID"),
        ("client_secret", "GOOGLE_HEALTH_CLIENT_SECRET"),
        ("refresh_token", "GOOGLE_HEALTH_REFRESH_TOKEN"))}
    ontbreekt = [k for k, v in velden.items() if not v]
    if ontbreekt:
        sys.exit(f"Secrets ontbreken of zijn leeg: {', '.join(ontbreekt)}")
    velden["grant_type"] = "refresh_token"
    req = urllib.request.Request(TOKEN_URL, data=urllib.parse.urlencode(velden).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            antwoord = json.load(r)
    except urllib.error.HTTPError as fout:
        # De foutcode van Google zegt wat er mis is (invalid_grant is een
        # verlopen of ingetrokken token, invalid_client een verkeerd id of
        # secret) en bevat zelf geen geheimen.
        try:
            code = json.loads(fout.read().decode()).get("error", "")
        except Exception:
            code = ""
        sys.exit(f"Token vernieuwen mislukt: HTTP {fout.code} {code}")
    token = antwoord.get("access_token")
    if not token:
        sys.exit("Geen toegangstoken ontvangen.")
    print(f"::add-mask::{token}")
    return token, set((antwoord.get("scope") or "").split())


def lees(datatype, token, aantal=5):
    url = f"{BASE}/{datatype}/dataPoints?page_size={aantal}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as fout:
        try:
            fout_json = json.loads(fout.read().decode()).get("error", {})
            reden = fout_json.get("status", "")
        except Exception:
            reden = ""
        sys.exit(f"{datatype}: HTTP {fout.code} {reden}")


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "check":
        sys.exit(__doc__)
    onderdeel = sys.argv[2]
    token, scopes = toegangstoken()

    if onderdeel == "token":
        mist = [naam for naam, s in SCOPES.items()
                if not any(x.endswith(s) for x in scopes)]
        if mist:
            sys.exit(f"Token werkt, maar mist rechten voor: {', '.join(mist)}")
        print("Token vernieuwd; beide rechten aanwezig.")
        return

    if onderdeel not in DATATYPE:
        sys.exit(f"Onbekend onderdeel: {onderdeel}")
    antwoord = lees(DATATYPE[onderdeel], token)
    punten = antwoord.get("dataPoints") or []
    if not punten:
        sys.exit(f"{onderdeel}: API bereikbaar, maar geen meetpunten gevonden.")
    # Alleen het aantal, nooit de waarden: deze log is openbaar.
    print(f"{onderdeel}: {len(punten)} meetpunten gelezen.")


if __name__ == "__main__":
    main()
