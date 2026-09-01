# Streetlifting-automatisering

Voedt twee Claude-routines met verse Hevy-data.

## Waarom deze omweg

De Claude-cloudomgeving mag `api.hevyapp.com` niet bereiken; de uitgaande proxy
weigert de verbinding. GitHub is wél bereikbaar en `git clone` werkt daar.
Dus haalt GitHub Actions de data op, en lezen de routines die uit deze repo.

    Hevy API  ->  GitHub Actions  ->  data/*.json  ->  Claude-routine  ->  bericht/mail

## Onderdelen

| Bestand | Wat het doet |
|---|---|
| `scripts/hevy_sync.py` | Haalt alle sessies op, rekent e1RM per wedstrijdlift uit, bepaalt de programmaweek en het voorschrift |
| `.github/workflows/hevy-sync.yml` | Draait dat script dagelijks om 05:15 UTC en zondag om 16:15 UTC |
| `data/programma-status.json` | Wat de routines lezen: stand, voorschrift, nalevingscijfers |
| `data/hevy-raw.json` | Alle sessies onbewerkt, voor als er dieper gekeken moet worden |

De rekenkunde staat in Python en niet in de routineprompt. Een taalmodel dat
percentages uit het hoofd vermenigvuldigt maakt fouten; Python niet. De routine
leest getallen en levert alleen de formulering en de beoordeling.

## Instellen

1. Maak een **privé** repo aan op GitHub en zet deze map erin.
2. Ga naar Settings > Secrets and variables > Actions > New repository secret.
   Naam: `HEVY_API_KEY`. Waarde: je sleutel van https://hevy.com/settings?developer
3. Tabblad Actions > Hevy synchroniseren > Run workflow. Er hoort daarna een
   commit te verschijnen met `data/programma-status.json`.

## Herstel bijhouden

De GARD PRO FIT-app draait op het GloryFit-platform en heeft geen API of
cloud-export, dus die gegevens kunnen niet automatisch opgehaald worden.
Noteer ze in plaats daarvan in het beschrijvingsveld van je Hevy-sessie:

    slaap 6u30 stappen 8500 moe 3 kcal 2700 eiwit 145

Alles is optioneel. `moe` loopt van 1 (fris) tot 5 (gesloopt). De Eetmeter
van het Voedingscentrum heeft geen API, alleen een PDF- en XML-export via
de website; twee getallen overtypen is minder werk dan wekelijks een
bestand exporteren. Eiwit onder de 110 g telt mee als herstelsignaal. Twee signalen
tegelijk, bijvoorbeeld weinig slaap en hoge vermoeidheid, levert een advies op
in je dagbericht. Het schema verlaagt zichzelf niet automatisch: een korte
nacht is normaal, pas een patroon telt.

## Programma aanpassen

Alle constanten staan bovenin `scripts/hevy_sync.py`:

- `START` — maandag van week 1
- `UITGANG` — 1RM-waarden voor als er nog geen bruikbare sets zijn
- `SCHEMA` en `SCHEMA_SQUAT_BLOK1` — sets, reps en percentage per blok en cyclusweek
- `TARGETS` — de streefwaarden per week waar het weekrapport tegen afzet

## Lokaal testen

    HEVY_API_KEY=... python scripts/hevy_sync.py
