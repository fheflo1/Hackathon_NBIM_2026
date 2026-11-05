# Arkitektur og modulgrenser

```text
run.py                         Ett oppsett og én lokal produksjonsserver
app.py                         ASGI-inngang for alternativ uvicorn-start
frontend/
  src/App.tsx                  Opplasting, fremdrift og navigasjon
  src/components/Results.tsx   Stemmetall, tabell og detaljvisning med kilder
  src/components/DataView.tsx  Datakilder og preprocessing-prinsipper
  src/components/AgentView.tsx Lesbar LangGraph-flyt
  src/lib/                     API-kontrakt, typer og presentasjonsregler
  package-lock.json            Låste frontendavhengigheter
src/nbim_flow/
  web/api.py                   FastAPI, opplasting, eksport og React-filer
  web/service.py               Varig jobbstatus og én sekvensiell arbeidskø
  web/ingestion.py             CSV/PDF/TXT og kildebundet dokumentuttrekk
  web/analytics.py             Faktiske aggregater fra originalfilene
  config.py                    Validert miljøkonfigurasjon
  data.py                      Datakvalitet, identitet, fakta og separate labels
  policy.py                    Datert, eksplisitt policyutvalg
  agents.py                    Prompts, svarskjema og OpenAI-adapter
  local_model.py               Lokal Ollama og versjonsidentitet
  graph.py                     LangGraph: vurdering, kontroll og revisjon
  workflow.py                  Saksreservasjon, budsjett, gjenbruk og audit
  store.py                     SQLite, migrasjon, låser og historikk
  model.py / registry.py       Separat historisk baseline og modellregister
  diagnostics.py               Oppsettskontroll og eksplisitt modelltest
  monitoring.py / evaluation.py Driftsmålinger og historisk evaluering
  cli.py                       Analyse- og driftskommandoer
  diagrams.py                  Mermaid-kilden
policies/                      Daterte, kuraterte retningslinjer
data/                          Bare de to originale datafilene
tests/fixtures/                Testdata, aldri lastet inn i appen
artifacts/                     Lokale opplastinger, modeller og revisjonsdatabase
.github/workflows/ci.yml        Python- og React-kontroller
```

## Enkel brukerflate, separate ansvar

React presenterer tilstand fra API-et. Den lager ingen stemmeanbefalinger eller
simulert fremdrift. Modelloppsett ligger i `.env`, ikke i appens brukerflyt.
FastAPI serverer ferdigbygget React og API fra samme lokale adresse. Skrifter ligger
i bygget; eksterne fonter eller publiseringstjenester brukes ikke.

Én prosess og én bakgrunnstråd behandler opplastinger sekvensielt. Hver fil lagres
før kjøringen starter. `web_jobs` lagrer status og resultatsammendrag; `web_job_events`
lagrer operative tilstandsendringer. Per sak bruker vi eksisterende LangGraph og
revisjonslager, uten en parallell beslutningsimplementasjon i React eller API.

API-et returnerer straks etter registrering. Nettleseren henter faktisk status hvert
andre sekund. Behandlingen fortsetter når nettleseren lukkes. Ved serverkrasj merkes
uferdige jobber som avbrutt; ny opplasting gjenbruker ferdige saker. Ingen jobb regnes
som fullført bare fordi prosessen startet på nytt.

## Kildekontroll før og etter modellkall

CSV normaliseres deterministisk. PDF/TXT bruker ett ekstra strukturert uttrekkskall.
Selskap, dato og hvert forslag må kunne knyttes til originalteksten; forslagsteksten
blir et ordrett, normalisert sitat, med sidenummer for PDF. Datoer gjettes ikke.
Alle punkter valideres før første stemmevurdering, så karantene ikke blir til skjult
utelatelse av agendapunkter. Uttrekket er likevel ikke en garanti for fullstendighet.

Agentinput består av en tillatt liste av saksfakta. Historiske labels, begrunnelser,
modellscores og klustre er ikke bevis på policyetterlevelse. Kildene NBIM og N-PX
forblir adskilt. Skjev stemmefordeling og ukjente verdier vises som faktisk målt.

LangGraph kjører vurderingsagent, fast kildekontroll og separat kontrollkall. Maks fem
totale forsøk betyr maksimalt fire gjentakelser. Manglende fakta eller policydekning
sendes til oppfølging. Feil som kan rettes får konkret tilbakemelding. Modellfeil
stopper webkjøringen; ferdige saker bevares.

## Identitet og gjenbruk

- `record_id`: kilde, møte og punkt.
- `evidence_hash`: normaliserte saksfakta, uten fasit.
- `run_key`: fakta, policyhash, beslutningskode/prompts og modellkonfigurasjon.
- `batch_id`: én operativ saksbehandling, også ved gjenbruk.
- Webfingeravtrykk: filinnhold, uttrekksversjon, policy og modellkonfigurasjon.

Lokal modell-digest fanger opp endret modellinnhold under samme navn. React-endringer
utløser ingen ny vurdering. Ved endrede filrader gjenbrukes uendrede saker. Opprinnelig
kilde og vurderingshistorikk beholdes. For API-aliaser uten digest må prosjektansvarlig
bruke eksplisitte modellversjoner eller bytte `NBIM_CACHE_NAMESPACE` bevisst.

SQLite bruker atomisk saksreservasjon og ti minutters lease med eierskapstoken.
En gammel prosess kan ikke overskrive en sak som er overtatt av en annen. Sluttstatus
og slutthendelse lagres i samme transaksjon. Eksisterende audit-tabeller bevares.

## Tydelige resultater og avgrensninger

Bare `verified` teller i For/Mot/Avstå-kortene. Manuelle og tekniske reserveutfall vises
separat. Konfidens skjules ved reserveutfall; 0 % skal ikke fremstå som en sannsynlighet
for korrekt Avstå. Kildehenvisninger er parafraser med offisiell lokator, ikke sitater
fra et komplett policybibliotek. Ingen stemmer sendes videre fra appen.

Dette er en lokal teamapplikasjon uten sentral innlogging, distribuert kø eller
flerkundestøtte. Serveren binder til 127.0.0.1, avviser ukjente verter og eksterne
Origin-verdier ved endringer. Opplastingsstørrelse og agentforsøk er avgrenset;
CSV-eksport nøytraliserer regnearkformler. Modelltilgang faller ikke over til skyen.
En fungerende kontrollagent garanterer ikke generell beslutningskvalitet, særlig
når begge roller bruker samme modell. Manuell saksbehandling skjer utenfor denne
forenklede React-flaten; den gamle menneskelige revisjonshistorikken er bevart i lageret.
