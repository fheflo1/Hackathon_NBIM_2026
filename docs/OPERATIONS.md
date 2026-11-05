# Drift og vedlikehold

## Daglig kjøring

```bash
python3 run.py --doctor
python3 run.py --cli models
python3 run.py --cli status --mode llm
```

`doctor` kontrollerer pakker, data, policy, lokal lagring og konfigurasjon uten å
kontakte en modell. `probe` er en eksplisitt tilkoblingstest med to syntetiske kall.
Bruk først få saker og et lavt modellkallbudsjett. Det er ingen bakgrunnsjobb som
starter modellkall eller laster ned vekter automatisk.

## Hva som overvåkes

Hver batch har ID, konfigurasjon, inputfingeravtrykk, tidsbruk, antall behandlede,
gjenbrukte, feil og utsatte saker. Per kall lagres rolle, modell, tokens når
rapportert, svartid og eventuell leverandør-/request-ID. Consolelogger er strukturert
JSON med operative ID-er og tellere. Saksinnhold finnes i den lokale revisjonsdatabasen.
API-nøkler og rå feilmeldinger fra leverandøren skrives ikke i logger.

Drift-siden skiller demo og LLM, viser siste saksversjon og oppsummerer de siste
100 batchene. Manuell kø teller bare saker som fortsatt venter på vurdering.
Temafordeling kan sammenlignes med en lagret modellreferanse; en endring er et
undersøkelsessignal, ikke en statistisk test eller et bevis på kvalitetsfall.
Modellkvalitet krever egen evaluering med fasit og representativ dekning.

## Feilsituasjoner

| Symptom | Handling |
|---|---|
| Lokal server kan ikke nås | Start Ollama-appen eller `ollama serve`; kontroller LLM_BASE_URL. |
| Modellen er ikke installert | Se `ollama list`, last ned ønsket modell eller velg en som finnes. |
| Første kall tar lang tid | Lokal modell kan lastes fra disk. Kontroller timeout og ledige ressurser. |
| Svar avbrutt eller feil JSON | Kontroller tokengrense/kontekst. Kjør probe og vurder en annen modell. |
| 401/403 | Kontroller nøkkel og tilgang ved OpenAI-kjøring; batchen stoppes. |
| 429 | Kontroller kvote/rategrense og vent før ny kjøring; ingen umiddelbar automatisk gjentakelse. |
| Tre feil etter hverandre | Batchens feilbryter stopper nye saker. Finn årsaken før gjenopptakelse. |
| Modellkallbudsjett brukt opp | Resterende sak er utsatt. Fortsett senere; brukte forsøk bevares. |
| Mye manuell oppfølging | Se policydekning og selskapsdata. Flere retries skaper ikke manglende fakta. |
| Sak står som processing etter krasj | Vent til ti minutters lease er utløpt, og kjør batchen igjen. |

Avbrutt batch kan fortsettes med samme kommando. Ferdige, uendrede saker gjenbrukes.
Et modelltag-skifte som endrer lokal digest medfører en ny vurderingsversjon.

## Modellregister og tilbakeføring

Hver trening lager en egen mappe under `artifacts/model/runs/` med modell, rapport,
testprediksjoner og manifest med filhash, treningsfingeravtrykk og programversjoner.
Eksisterende modellfiler kan tas inn i registeret uten ny trening. Første nye
trening arkiverer også eventuelle filer fra den gamle layouten. Demoen bruker
`artifacts/demo_model/` og endrer ikke den aktive arbeidsmodellen.
`active.json` er autoritativ peker. Filene som ligger direkte i `artifacts/model/`
er bekvemmelighetskopier, slik at eksisterende IDE-faner fortsatt fungerer.

Koden verifiserer registrerte filhash før lasting. Dette oppdager endring/skade,
men er ikke et signert tillitsbevis. Kun prosjektets egne lokale joblib-filer skal
lastes; modellen er ikke en trygg opplastingsfil fra en ukjent avsender.

```bash
python3 run.py --cli activate-model KJORINGS_ID
```

Samme valg finnes under Prioriteringsmodell. Endring av kømodell alene starter
ikke nye stemmevurderinger. Se riktig run-ID og terskel når tall deles; en ny
trening kan ha et annet recallmål enn den opprinnelige resultatrapporten.

## Backup

```bash
python3 run.py --cli backup --out artifacts/backups/audit-2026-11-05.sqlite
```

Backup bruker SQLite sin backupmekanisme og tar med data som ligger i WAL. Kopiering
av bare hovedfilen mens appen skriver kan gi en ufullstendig kopi. Kommandoen nekter
å overskrive en eksisterende backup. Oppbevar også uforanderlige modellkjøringer og
policyfilene. Ved tilbakelegging stoppes appen først; kontroller deretter doctor og
at riktig modell og policy er aktive. Databasen inneholder saksgrunnlag og navn på
saksbehandlere og skal behandles som et arbeidsdokument.

## Utvikling og CI

```bash
python3 run.py --setup --dev
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m coverage run --branch -m unittest discover -s tests
.venv/bin/python -m coverage report
```

Tester bruker mockede leverandører eller offline demo og trenger ikke en lokal
modellserver eller API-nøkkel. GitHub Actions er konfigurert for Python 3.11 og
3.13, uten automatiske modellkall eller utrulling. En faktisk server-/modelltest
kjøres separat og dokumenteres som en smal funksjonstest. Endringer i prompts,
policy og modeller krever dessuten et låst evalueringsutvalg før ytelsespåstander.

Les [Arkitektur](ARCHITECTURE.md) for modulgrenser og
[Workflow](WORKFLOW.md) for beslutnings- og feilstiene.
