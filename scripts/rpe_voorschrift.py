"""Een set zonder RPE is gedaan op de RPE die Kaj voorschreef.

Dat is Dylans eigen regel (18 oktober 2026). Het RPE-veld in Hevy begint bij
6, en Kaj schrijft vanaf Blok 1.1 veel RPE 5 voor. Die kan Dylan niet invullen;
een leeg veld betekent dus "zoals voorgeschreven", niet "onbekend".

VOLGORDE
  1. RPE in de notitie (notities.rpe_toewijzing) wint altijd;
  2. dan het RPE-veld in Hevy;
  3. dan Kajs voorschrift, via deze module.
Een set tot falen krijgt niets: die zegt zelf al hoe zwaar hij was.

HOE HET VOORSCHRIFT GEVONDEN WORDT
De sessie wordt aan een dag van Kaj gekoppeld en elke oefening aan een regel
van die dag, met dezelfde koppeling als de Sheet (sheets_log). Een vervangende
oefening krijgt niets: Kajs RPE hoort bij wat hij voorschreef.

VERTALING VAN KAJS NOTATIE
  "5"         elke set 5
  "7->8->9"   per set oplopend; extra sets houden de laatste waarde
  "6,5-7"     een bereik: de bovenkant, zodat het geschatte maximum niet
              rooskleuriger wordt dan wat er gedaan is
  "" of "x"   geen voorschrift, de set blijft zonder RPE

Wat hier wordt ingevuld krijgt "rpe_bron": "voorschrift", zodat het in de
cijfers te onderscheiden blijft van wat Dylan zelf logde.
"""

import json
import pathlib
import re


def per_set(voorschrift, aantal):
    """Kajs RPE-tekst naar een RPE per set, of None per set als er niets staat."""
    tekst = (voorschrift or "").strip().replace(",", ".")
    getallen = [float(g) for g in re.findall(r"\d+(?:\.\d+)?", tekst)]
    getallen = [g for g in getallen if 1 <= g <= 10]
    if not getallen:
        return [None] * aantal
    if ">" in tekst:
        return [getallen[min(i, len(getallen) - 1)] for i in range(aantal)]
    return [max(getallen)] * aantal


def lees_dagen(pad="data/coachschema.json"):
    try:
        schema = json.loads(pathlib.Path(pad).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []
    return [d for b in schema.get("blokken", []) for d in b.get("dagen", [])]


def vul_aan(workouts, dagen):
    """Vult lege RPE-velden in met Kajs voorschrift. Past de sets ter plekke aan.

    Geeft het aantal ingevulde sets terug.
    """
    import sheets_log      # hier, zodat de koppeling niet bij elke import meekomt
    if not dagen:
        return 0
    gevuld = 0
    for w in workouts:
        if not w.get("start_time"):
            continue
        dag, _ = sheets_log.kies_dag(w, dagen)
        if dag is None:
            continue
        toewijzing, vervangen, _ = sheets_log.koppel(w, dag)
        for i, oef in toewijzing.items():
            if i in vervangen:
                continue
            werk = [s for s in oef.get("sets", []) if s.get("type") not in ("warmup", "failure")]
            for s, rpe in zip(werk, per_set(dag["oefeningen"][i].get("rpe"), len(werk))):
                if s.get("rpe") is None and rpe is not None:
                    s["rpe"] = rpe
                    s["rpe_bron"] = "voorschrift"
                    gevuld += 1
    return gevuld
