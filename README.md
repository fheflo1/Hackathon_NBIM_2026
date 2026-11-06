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
ollama pull qwen3:8b
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

## Triagemodell foran agentflyten

Hver saksliste rangeres først av en logistisk regresjon trent på NBIMs egne stemmer
(`src/nbim_flow/triage.py`). Målet er stemme mot styrets anbefaling (`against_board`).
Personnavn og årstall maskeres, og historikk bruker bare møter før møtedatoen.

- Flaggede saker, saker en kuratert policyregel dekker og tekst som ligner et
  instruksjonsangrep går til full agentvurdering, én om gangen.
- Øvrige saker får en lett agentkontroll i parallell (`NBIM_LIGHT_WORKERS`, standard 2).
  Tvil, ugyldig svar eller konfidens under `NBIM_MIN_CONFIDENCE` eskalerer til full vurdering.
- Siden **Modellen** viser validering, testresultat og en terskel-slider.

Tidsdelt evaluering: trent 2019–2023, terskler valgt på 2023, validert på 2024, og
testsettet 2025–2026 holdt låst til modellen var frosset og deretter scoret én gang:

| 2025–2026 (3 448 saker, 169 mot-stemmer) | Average precision | Presisjon | Recall | Topp 15 % |
| --- | --- | --- | --- | --- |
| Tilfeldig rangering | 0,05 | – | – | 15 % |
| Sakstypens mot-andel | 0,16 | – | – | – |
| Triagemodell, frosset (trent til 2023) | 0,46 | 56 % | 41 % | 64 % |
| Triagemodell, trent på nytt til 2024 | 0,51 | 50 % | 46 % | 68 % |

«Alltid følg styret» gir 95 % accuracy og 0 % recall. Tallene reproduseres med:

```bash
python3 run.py --cli triage-train     # trener og validerer på 2024 (ca. 10 s)
python3 run.py --cli triage-holdout   # scorer det låste testsettet 2025–2026
```

`run.py --setup` trener triagemodellen automatisk når den mangler. Demosakslister ligger i
`tests/fixtures/` (testfiler; brukes ikke som data i appen).

## Kilder og AI-bruk

- [NBIM Voting](https://www.nbim.no/en/responsible-investment/voting/) og
  [NBIMs stemmehistorikk](https://www.nbim.no/en/responsible-investment/voting/our-voting-records/):
  grunnlaget for `data/real_votes.csv`, levert av teamet.
- [NBIM Global voting guidelines 2025](https://www.nbim.no/contentassets/01a7ee19b5d84a73a67a365e76a0fb01/global-voting-guildeines_2025.pdf):
  grunnlaget for de kuraterte policyreglene.
- [SEC Form N-PX](https://www.sec.gov/forms/formn-px.pdf): separat kilde, ikke brukt som NBIM-fasit.
- AI-verktøy: Codex ble brukt til datagjennomgang, arkitektur, kode, dokumentasjon og tester
  (fra appens første README). Claude Code ble brukt til modellarbeid, triagemodellen,
  integrasjonen i appen, testene for den og dokumentasjonen av resultatene. Eksperimentene
  med DeBERTa og LLM-varianter ble kjørt i et eget arbeidsområde og er ikke en del av dette
  repoet; tallene over reproduseres av kommandoene i repoet.

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
