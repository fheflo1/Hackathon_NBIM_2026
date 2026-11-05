# Drift og vedlikehold

## Start og stopp

```bash
python3 run.py --setup
python3 run.py --doctor
python3 run.py
```

Åpne http://127.0.0.1:8765. Stopp serveren med Ctrl+C. En lukket nettleser stopper ikke
agentene, men en stoppet server avbryter kjøringen. Bruk én API-prosess; dette er en
sekvensiell lokal arbeidskø, ikke et distribuert system.

React bygges ved endringer i frontendkoden. Et kildefingeravtrykk gjør at normal start
ikke bygger eller installerer på nytt. Python-avhengigheter oppdateres bare ved endret
pakkeoppsett. `npm ci` bruker låsfilen. Ingen modeller lastes automatisk ned.

## Sporbarhet

`artifacts/audit.sqlite` inneholder både tidligere saksresultater og webjobber.
`web_jobs`/`web_job_events` lagrer filhash, status, fremdrift og operative endringer.
`results`/`events` lagrer policyversjon, modellversjon, forsøk, sitatkontroller, agentenes
vurderinger, tokens når tilgjengelig og resultat. `batches` inneholder saksbatcher med
modellkall og tidsbruk. Opplastet originalfil ligger i `artifacts/uploads/<jobb-id>/`.

```bash
python3 run.py --cli status --mode llm
python3 run.py --cli models
```

Per sak viser React godkjente henvisninger og behandlingslogg. Datagrunnlag viser
stemmefordeling og kvalitet fra de originale filene. Ingen syntetisk demo vises.
Konfidens er selvrapportert; modellkvalitet krever en egen representativ evaluering.

## Feil og gjenopptakelse

| Symptom | Handling |
|---|---|
| Modellen er ikke klar | Start Ollama. Kontroller at navnet i `.env` finnes i `ollama list`. |
| Første kall tar lang tid | Modellen lastes fra disk; lokal kjøring kan ta minutter per sak. |
| Tom eller skannet PDF | Kjør tekstgjenkjenning først eller last opp en strukturert CSV. |
| Dokumentet er for langt | Last opp selve agendadelene med selskap, møtedato og relevante fakta. |
| Dato eller sitater kan ikke kontrolleres | Rett dokumentet eller bruk CSV. Appen gjetter ikke dato. |
| Mange manuelle saker | Kontroller policyår, dekning og om selskapsopplysninger mangler. |
| Modellfeil eller budsjettstopp | Rett oppsett eller servergrenser, og last opp samme fil igjen. |
| Serveren ble stoppet | Last opp igjen. Uferdige jobber markeres avbrutt; ferdige saker gjenbrukes. |
| Saken er låst etter krasj | Vent opptil ti minutter til saksreservasjonen utløper. |
| Endret modell men gammelt resultat | Lokal digest fanger modellendringer; ved API-aliaser endres cache-namespace bevisst. |

Servergrensene styres i `.env`, uten brukerparametere i React. Standardverdien er
100 modellkall per opplasting, inkludert ett uttrekkskall for PDF/TXT. Hver vurdering
kan bruke opptil to kall per forsøk, maks fem forsøk. Større sakslister eller mange
revisjoner kan derfor nå budsjettet. Ingen ubehandlede punkter telles som ferdige.
Gjenta opplastingen etter å ha justert budsjettet for å gjenbruke ferdige saker.

Ikke logg API-nøkler eller rå leverandørfeil. Nettverksfeil vises som sikre feilkategorier.
Saksinnholdet i databasen og opplastingsmappen må behandles som arbeidsdokumenter.
Lokal modus bruker bare lokal Ollama. Valgfri API-modus sender saksfakta til den
konfigurerte API-leverandøren når brukeren laster opp; den er aldri en automatisk reserve.

## Backup og tilbakeføring

```bash
python3 run.py --cli backup --out artifacts/backups/audit-YYYY-MM-DD.sqlite
```

SQLite-backup tar med WAL-innhold; ikke kopier bare hovedfilen mens appen skriver.
Kommandoen overskriver ikke en eksisterende backup. Ta også vare på opplastinger,
policyfiler og modellregister. Stopp serveren før tilbakelegging.

Modellregisteret under `artifacts/model/runs` er uforanderlig per kjøring, og
`active.json` er autoritativ peker. CLI-kommandoen `activate-model KJORINGS_ID`
velger tidligere versjon av den historiske prioriteringsmodellen. Dette påvirker
ikke React-agentløpet, som behandler alle opplastede saker uten slik prioritering.

## Kvalitetskontroll og CI

```bash
python3 run.py --setup --dev
python3 run.py --check
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m coverage run --branch -m unittest discover -s tests
.venv/bin/python -m coverage report
npm --prefix frontend test
npm --prefix frontend run build
```

GitHub Actions tester Python 3.11/3.13 og et eget React-produksjonsbygg, uten modellserver,
API-nøkler eller utrulling. Modellkall er erstattet med kontrollerte testadaptere.
Syntetiske fixtures ligger kun under `tests/`. Ekte lokale modelltester er separate,
smale funksjonstester og må ikke omtales som presisjonsmålinger.
