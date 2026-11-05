# STEM · NBIM voting workspace

Last opp en saksliste, og få stemmeanbefaling, konfidens og kildehenvisninger per
agendapunkt. React viser fremdriften; LangGraph styrer vurdering og kontroll.
Modellen kjører lokalt gjennom Ollama. Ingen stemmer sendes til en generalforsamling.

## Kom i gang

Krever Python 3.11+, Node.js 24 LTS og Ollama med en nedlastet modell.
Åpne terminalen i repoet:

```bash
python3 run.py --setup
python3 run.py --init
ollama pull qwen2.5:7b
python3 run.py
```

Start Ollama-appen først. Hvis modellen allerede er lastet ned, hopp over `pull`.
Bruk modellnavnet fra `ollama list` i `.env`. Eksisterende `.env` overskrives ikke.
Åpne **http://127.0.0.1:8765**. På Windows: `py run.py`.

Biblioteker og skrifter lastes ned ved første oppsett. Deretter serveres både React,
API og skrifter lokalt; ingen CDN trengs. Modellen lastes aldri automatisk ned av appen.

[Stegvis oppstart](docs/GETTING_STARTED.md) · [Workflow i Mermaid](docs/WORKFLOW.md) ·
[Moduler og arkitektur](docs/ARCHITECTURE.md) · [Drift](docs/OPERATIONS.md)

## Én handling i appen

Last opp PDF, CSV eller TXT. Appen leser punktene og starter behandlingen automatisk.
Du trenger ikke velge modellparametere eller starte agentene manuelt.

- **Saksbehandling:** løpende fremdrift, For/Mot/Avstå, konfidens og retningslinjer.
  Åpne en sak for begrunnelse, ordrette datasitater, kildehenvisning og behandlingslogg.
- **Datagrunnlag:** faktiske antall og stemmefordeling i hver kilde, samt prinsippene
  for preprocessing, fasitlekkasje og tidsdelt evaluering.
- **Agentflyt:** vurderingsagent, fast kildekontroll, separat kontrollagent og revisjonsløp.

Samme fil vises igjen uten ny kjøring. Ved nye punkter i en fil gjenbrukes uendrede
saker når fakta, policy og beslutningsversjon stemmer. Opplastinger og hendelser
lagres under `artifacts/`. Lukk nettleseren uten å stoppe serveren, og jobben fortsetter.

Demodata og eksempelkjøringer er fjernet fra produktet. Syntetiske data finnes kun
som testfixtures, og den valgfrie CLI-tilkoblingstesten lagrer ikke saker.

## Grunnlag og grenser

De to originale datafilene har 66 663 rader. NBIM-filen har 13 757 rader:
12 598 For, 757 Mot, 68 Avstå og 334 ukjente stemmer. Sju N-PX-rader mangler
forslagstekst. Forvaltertilhørigheten til N-PX er ikke verifisert; kilden holdes separat.
Se [datagjennomgangen](docs/DATA_REVIEW.md).

Policyen inneholder åtte kuraterte parafraser fra NBIM 2025, konservativt avgrenset
til 17. februar–31. desember 2025. Den er ikke et komplett eller oppdatert policybibliotek.
Andre datoer, manglende fakta eller manglende dekning krever manuell vurdering.
En teknisk Avstå vises separat og regnes ikke som en kontrollert stemme.

Konfidens er modellens egen vurdering, ikke en kalibrert sannsynlighet.
To agentroller kan bruke samme modell og dermed dele feil. Kildekontroll og en
fungerende opplastingsflyt er ikke dokumentasjon på generell stemmekvalitet.

Den logistiske tekstmodellen er en separat, evaluert prioriteringsbaseline via CLI;
den avgjør ikke stemmene og filtrerer ikke bort opplastede saker.
[Modellresultatene](docs/MODEL_RESULTS.md) gjelder historisk MOT-prediksjon,
ikke kvaliteten til LLM-agentene eller DeBERTa-målet `against_board`.

## Utvikling og kontroll

```bash
python3 run.py --setup --dev
python3 run.py --check
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
npm --prefix frontend test
npm --prefix frontend run build
```

Frontendens kildekode ligger i `frontend/src`, Python-koden i `src/nbim_flow`.
`frontend/package-lock.json` låser React-avhengigheter; `requirements-lock.txt`
dokumenterer det testede Python-miljøet. GitHub Actions tester Python 3.11/3.13,
React, formatering og produksjonsbygg uten ekte modellkall eller automatisk utrulling.
