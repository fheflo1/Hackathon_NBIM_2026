# Arkitektur og modulgrenser

```text
app.py                         Tynn inngang til Streamlit
run.py                         Opprett miljø, installer og start
pyproject.toml                 src-pakke, CLI og utviklerverktøy
src/nbim_flow/
  cli.py                       Kommandolinje og exit-koder
  config.py                    Validert miljøkonfigurasjon og prosjektstier
  data.py                      CSV-kvalitet, identitet, fakta og separate labels
  model.py                     Historisk tekstmodell, tidsdeling og prioritering
  registry.py                  Uforanderlige modellkjøringer og aktiv peker
  agents.py                    Prompts, outputkontrakter og OpenAI-adapter
  local_model.py               Ollama-adapter med JSON-schema og modellidentitet
  policy.py                    Datert policy og transparent henting
  graph.py                     LangGraph: anbefaling, kontroll og revisjon
  workflow.py                  Batchservice, budsjett, cache og lagring
  store.py                     SQLite, migrasjon, låser og menneskelig vurdering
  operations.py                Sikre feilkategorier og strukturerte logger
  monitoring.py                Driftsmålinger og beskrivende dataendringer
  diagnostics.py               doctor, probe og oppretting av .env
  evaluation.py                Sammenligning med separat historisk fasit
  diagrams.py                  Mermaid-kilden
  ui/                          Separate visninger; ingen egen forretningslogikk
tests/                         Offline funksjons- og regresjonstester
policies/                      Daterte, gjennomgåtte policyfiler
data/                          Rådata og syntetisk agenda
artifacts/                     Ignorerte lokale resultater, modeller og database
.github/workflows/ci.yml        Kodekontroll og tester ved push/PR
```

## Viktige grenser

UI og CLI bruker samme preprocessing og batchservice. Oppstart forutsetter ikke
at terminalens gjeldende mappe er `src`; pakken installeres eksplisitt. Prosjektets
ressurser finnes fra repoet eller `NBIM_ROOT`. Ingen absolutte personlige stier er
hardkodet i applikasjonen.

Agentinput er en tillatt liste med fakta før avstemningen. Historiske labels og
begrunnelser er separate og brukes bare til trening/evaluering. Modellscore,
fasit og klustertilordning er ikke bevis på policyetterlevelse.

LLM-adapterne har samme grensesnitt: propose, review, close og normalisert
forbruksmetadata. Ollama bruker lokal HTTP med JSON-schema og uten proxy fra
miljøet. OpenAI bruker Responses og `store=False`. Ingen adapter faller over til
annen leverandør ved feil. Nettverksoppsett og tilgang testes eksplisitt.

## Identitet og gjenbruk

- `record_id`: kilde + møte + punkt.
- `evidence_hash`: normaliserte saksopplysninger, uten historisk fasit.
- `run_key`: fakta, policyhash, beslutningskode/prompts, modellkonfigurasjon og modus.
- `batch_id`: én operativ kjøring, også når alle resultater gjenbrukes.

For lokal Ollama hentes modellens digest før batchen. Endret modellinnhold under
samme tag gir dermed en ny beslutningsversjon. UI-endringer, logger, kømodell og
endret forsøksbudsjett alene utløser ikke nye kall for ferdige saker.
For leverandøraliaser uten slik digest brukes eksplisitt modellversjon eller et
bevisst skifte av `NBIM_CACHE_NAMESPACE`.

## Tilstander og kontroll

En sak er `processing`, `verified`, `demo_checked`, `human_review`, `error` eller
`deferred`. Demo og ekte modellmodus blandes ikke i driftsoversikten.
En teknisk AVSTÅ har en eksplisitt reserveårsak og er ikke en ferdig avstemning.

Fem totale vurderingsforsøk betyr fire retries. API-budsjettet reserveres før
hvert modellkall. Oppbrukt budsjett utsetter saken; autentisering, kvote og feil
modelloppsett stopper batchen. Tre påfølgende feil stanser videre behandling.
Kall som allerede har feilet kan fortsatt ha forbrukt modellressurser; manglende
tokenbruk etter nettverksavbrudd rapporteres ikke som et bevist nullforbruk.

SQLite har atomisk reservasjon og en ti minutters lease. Et eierskapstoken hindrer
en gammel prosess i å overskrive saken etter at en ny prosess har overtatt. Brukte
forsøk beholdes etter krasj. Sluttstatus og slutthendelse lagres i samme transaksjon.
Migrasjon fra den første databasen er additiv og bevarer tidligere historikk.

Menneskelig vurdering er en separat, logget oppføring. Agentens opprinnelige
stemme og begrunnelse endres ikke. Dashboardet viser en effektiv anbefaling og
om oppfølging gjenstår. Navnet er selvoppgitt i denne lokale teamversjonen; det er
ikke en autentisert identitet eller en elektronisk signatur.

## Avgrensning

Dette er en lokal teamapplikasjon. Den har ikke flerkundestøtte, sentral innlogging,
uforanderlig revisjonsarkiv eller en distribuert jobbkø. Default binding er bare til
127.0.0.1. Før eventuell bredere drift må tilgangsstyring, lagring, datakilder,
policydekning og LLM-kvalitet vurderes for det faktiske bruksområdet.
DeBERTa-vektene og gruppas eksakte inputkode er ikke en del av denne kjøringen.
