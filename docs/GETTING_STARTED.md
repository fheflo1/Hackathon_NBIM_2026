# Kjør med en lokal modell

To ulike modeller har ulike oppgaver:

- **LLM-en** leser saken, foreslår For/Mot/Avstå og gir en kildebelagt begrunnelse.
  Et separat kall kontrollerer svaret. Det er dette Ollama, Qwen eller Gemma brukes til.
- **Den logistiske modellen** prioriterer køen. Den er valgfri og trenger ingen LLM-server.

## 1. Installer prosjektet

Åpne en terminal i `Hackathon_NBIM_2026`:

```bash
python3 run.py --setup
python3 run.py --init
```

Oppsettet lager `.venv` og installerer pakken fra `src`. `--init` lager en lokal
`.env` uten å overskrive en eksisterende fil. På Windows: bruk `py` i stedet for
`python3`; det lokale Python-programmet heter `.venv\Scripts\python.exe`.

## 2. Start Ollama

Installer ved behov fra [ollama.com](https://ollama.com/download). Start Ollama-appen,
eller kjør `ollama serve` i en egen terminal. Hvis appen allerede kjører, skal du
ikke starte en ekstra server på samme port.

```bash
ollama list
```

Hvis en egnet modell allerede finnes, kan den brukes direkte. På denne maskinen
fantes `gemma4:e4b`. Første reelle prøve med denne modellen leverte strukturerte svar
fra begge agentrollene. Dette dokumenterer tilkoblingen, ikke generell stemmekvalitet.

For Qwen-alternativet:

```bash
ollama pull qwen2.5:7b
```

Den standardkvantiserte modellen er omtrent 4,7 GB å laste ned. Modellfilen krever
i tillegg arbeidsminne og kontekstbuffer ved kjøring. Faktisk hastighet avhenger
av maskinen og tekstlengden. Se [modellkortet](https://ollama.com/library/qwen2.5:7b).

Ingen modell lastes automatisk ned av prosjektkoden.

## 3. Velg modell i .env

Bruk nøyaktig navnet fra `ollama list`. For den allerede installerte modellen:

```dotenv
LLM_PROVIDER=ollama
LLM_BASE_URL=http://127.0.0.1:11434
LLM_MODEL=gemma4:e4b
LLM_REVIEWER_MODEL=
```

Etter nedlasting av Qwen kan `LLM_MODEL` endres til `qwen2.5:7b`.
Tom `LLM_REVIEWER_MODEL` bruker samme modell i et separat kall.
Anbefalings- og kontrollmodellen kjører sekvensielt.

Lokal modus trenger ingen API-nøkkel. Koden bruker Ollamas native `/api/chat`
med JSON-schema. Modusvalget tillater bare lokal server og blokkerer eksplisitte
cloud-modellnavn. Kjøring har ingen automatisk reserveleverandør i skyen.
Oppstart av Ollama og nedlasting av modell er de eneste eksterne forberedelsene.

Start med innstillingene fra `.env.example`. `NBIM_API_TIMEOUT=120` gir tid til
første lasting. `NBIM_MAX_OUTPUT_TOKENS=1500` begrenser hvert svar, og
`NBIM_CONTEXT_TOKENS=16384` setter kontekstvinduet. Ved endring av `.env` må
terminalmiljøvariabler som overstyrer samme navn fjernes eller endres; de har prioritet.

## 4. Kontroller oppsett og tilkobling

```bash
python3 run.py --doctor
python3 run.py --cli models
python3 run.py --probe
```

- `doctor` er lokal oppsettskontroll uten nettverk eller modellkall.
- `models` kontakter lokal Ollama og viser installerte navn og modellversjoner.
- `probe` gjør to faktiske modellkall på et syntetisk forslag om å skille CEO og styreleder.

I probe-resultatet skal `connected` og `structured_outputs_ok` være `true`.
Kontrollagenten kan fortsatt avvise anbefalingen. Det betyr at transporten fungerer,
men at selve vurderingen krever oppfølging. En probe er ikke en evaluering av modellkvalitet.

## 5. Start dashboardet

```bash
python3 run.py
```

Følg sidene i denne rekkefølgen:

1. **Oppsett:** kontroller modellnavn og prøv et syntetisk eksempel.
2. **Data:** velg Demoeksempler for en første gjennomkjøring, deretter NBIM-data.
3. **Saksbehandling:** velg «LLM med konfigurert modell» og start med én til fem nye saker.
4. **Drift:** se batchstatus, kall, tokens og stoppårsaker.
5. **Manuell oppfølging:** åpne usikre saker og registrer vurdering med navn og begrunnelse.
6. **Workflow:** se diagrammet eller last ned Mermaid-kilden.

Ved første kjøring lastes modellen inn i minnet. Det kan ta vesentlig lengre tid
enn senere kall. Ikke start mange samtidige batcher på samme lokale modellserver.

## 6. Kjør en liten ekte batch fra terminalen

```bash
python3 run.py --cli process --source real --year 2025 --mode llm --limit 5 --max-api-calls 20
python3 run.py --cli status --mode llm
python3 run.py --cli evaluate --source real --mode llm
```

Alle agendapunkter beholdes. Saker utenfor policyutvalget rutes til mennesker uten
modellkall. Generiske valg- og revisorsaker trenger ofte flere selskapsopplysninger.
Evalueringen oppgir både dekning og utfall; fem valgte saker er ikke en holdout-test.

Vil du prioritere køen først:

```bash
python3 run.py --cli train --source real
python3 run.py --cli process --source real --year 2025 --mode llm --limit 5 --priority-model artifacts/model
```

Modellen estimerer foreløpig MOT-stemme, ikke nødvendigvis avvik fra styret.
Dette er en annen målvariabel enn DeBERTa-rapportens `against_board`.

## Valgfritt: OpenAI i stedet for egen modell

Sett følgende lokalt i `.env`, og velg et modellnavn kontoen har tilgang til:

```dotenv
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=modellnavn-fra-kontoen
OPENAI_API_KEY=din-private-nokkel
NBIM_MAX_OUTPUT_TOKENS=4000
NBIM_API_TIMEOUT=45
```

Dette sender saksgrunnlag og policyutvalg til OpenAI når du eksplisitt starter
probe eller LLM-batch. API-nøkkelen skal ikke sendes i chat eller legges i Git.
Se [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).
