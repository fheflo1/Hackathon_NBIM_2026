# Stegvis oppstart med lokal modell

## 1. Klargjør maskinen

Installer Python 3.11 eller nyere, Node.js 24 LTS og [Ollama](https://ollama.com/download).
Start Ollama-appen. En allerede kjørende Ollama-server skal ikke startes på nytt.

```bash
ollama list
```

Bruk en installert modell, eller last ned Qwen:

```bash
ollama pull qwen3:8b
```

Nedlasting og nok arbeidsminne kreves før første lokale kjøring. Ytelsen avhenger av
maskin, kontekst og modell. Appen laster ikke ned modeller eller bytter til skyen ved feil.

## 2. Installer og bygg prosjektet

Stå i `Hackathon_NBIM_2026`:

```bash
python3 run.py --setup
python3 run.py --init
```

Dette lager Python-miljøet, installerer pakken fra `src`, installerer React-biblioteker
fra låsfilen og bygger brukerflaten. `--init` lager `.env` bare hvis filen mangler.
På Windows brukes `py` i stedet for `python3`.

## 3. Kontroller modellnavnet

I `.env` må `LLM_MODEL` samsvare med `ollama list`:

```dotenv
LLM_PROVIDER=ollama
LLM_BASE_URL=http://127.0.0.1:11434
LLM_MODEL=qwen3:8b
LLM_REVIEWER_MODEL=qwen3:8b
```

Begge agentroller bruker Qwen3 8B i separate kall. Tom kontrollmodell bruker vurderingsmodellen.
Klienten slår av thinking for Qwen3 slik at JSON-svar får hele utbudsjettet. API-nøkkel er ikke nødvendig.
Driftsgrenser står i `.env.example`. De stilles av prosjektansvarlig, ikke i brukerflaten.
Terminalens miljøvariabler har prioritet over `.env`. Start appen på nytt etter endringer.

```bash
python3 run.py --doctor
python3 run.py --cli models
```

`doctor` krever ingen modelltilgang; `models` henter lokal modellmetadata uten inferens.

## 4. Start appen

```bash
python3 run.py
```

Åpne **http://127.0.0.1:8765**. Last opp sakslisten i Saksbehandling.
Behandlingen starter automatisk. Åpne en resultatlinje for å se stemme, konfidens,
retningslinje, originalt saksgrunnlag og kontrollagentens begrunnelse.

Ingen demodata er inkludert i appen. Datagrunnlag viser bare de originale NBIM- og
N-PX-filene, hver for seg. Tidligere opplastinger viser bare faktiske opplastinger.

## Filformat

- **PDF:** tekstbasert, ulåst, maks 40 sider og 24 000 teksttegn. Last opp sidene med
  selskap, møtedato og hele sakslisten. Skannede dokumenter trenger tekstgjenkjenning først.
- **TXT:** UTF-8 med selskap, faktisk møtedato og tydelig nummererte forslag.
- **CSV:** UTF-8 eller UTF-16; komma, semikolon eller tabulator. Minstekolonner er
  `meeting_date` og `proposal_text`; bruk også `company`, `meeting_id` og `item_no`.
  Norske navn som `selskap`, `møtedato`, `saksnummer`, `sak` godtas.

Maks 20 MB og 100 agendapunkter per fil. Ta med opplysninger som er nødvendige for
å vurdere forslaget, ikke bare en generell overskrift. Manglende dato gjettes ikke.
CSV valideres direkte; PDF/TXT bruker ett uttrekkskall før agentløpet. Uttrekkets
selskapsnavn, dato og sitater bindes til dokumentteksten. Dette garanterer ikke at
modellen har funnet alle punkter; kontroller listen mot originaldokumentet.

Mangelfulle eller motstridende punkter avviser hele innlesingen før stemmevurdering.
Historiske stemmer og begrunnelser i en CSV holdes utenfor agentenes saksfakta.

## Hvis en sak trenger oppfølging

Policyutvalget dekker et begrenset datovindu i 2025. For andre år eller utilstrekkelig
saksgrunnlag får saken status Manuell vurdering, uten oppdiktet konfidens eller sitater.
Reservevalget Avstå er ikke en godkjent anbefaling og holdes utenfor stemmetallene.

Lokal inferens kan ta minutter per punkt. Serveren behandler én saksliste om gangen.
Ved modellfeil stopper kjøringen og bevarer ferdige resultater. Rett årsaken og last
opp igjen. Ved et serverkrasj kan en låst sak kreve opptil ti minutter før den kan overtas.

## Utvikling

Start API-et med `python3 run.py`. For rask React-utvikling i en annen terminal:

```bash
npm --prefix frontend run dev
```

Vite på port 5173 videresender API-kall til port 8765. Produksjonskjøring bruker bare
én lokal server og krever ingen Vite-prosess. Nytt frontendbygg lages automatisk
ved endret frontendkode når `run.py` startes.

[Hele workflowen i Mermaid](WORKFLOW.md) · [Drift og feil](OPERATIONS.md)
