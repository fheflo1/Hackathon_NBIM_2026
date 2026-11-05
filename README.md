# NBIM · Stemmeanbefalinger

En lokal arbeidsflate for å lese generalforsamlingssaker, prioritere køen og lage
begrunnede anbefalinger med kontroll og manuell oppfølging. Koden ligger under `src/`.
Ingen stemmer sendes til en generalforsamling.

## Kom i gang

Krever Python 3.11+ og Ollama for ekte lokal modellkjøring. Bibliotekene lastes ned
ved første oppsett. Senere kan inferens kjøres lokalt med en allerede nedlastet modell.

```bash
python3 run.py --setup
python3 run.py --init
python3 run.py --doctor
python3 run.py
```

Fyll inn modellnavnet i `.env` før ekte kjøring. Standardeksemplet bruker
`qwen2.5:7b`; velg en modell som finnes i `ollama list`. På denne maskinen ble
`gemma4:e4b` funnet installert og brukt til første faktiske API-test.
På Windows brukes `py run.py` i stedet for `python3 run.py`.

**[Stegvis veiledning for lokal modell](docs/GETTING_STARTED.md)** ·
[Hele workflowen i Mermaid](docs/WORKFLOW.md) ·
[Arkitektur og moduler](docs/ARCHITECTURE.md) ·
[Drift, feil og tilbakeføring](docs/OPERATIONS.md)

## Hva løsningen gjør

- CSV-validering, normalisering, deduplisering og karantene med filhash.
- Historisk fasit holdes utenfor faktaene som modellene og agentene får lese.
- TF-IDF og logistisk regresjon gir valgfri prioritering; alle saker beholdes.
- Anbefalingsagent, deterministisk kildekontroll og separat kontrollagent i LangGraph.
- Lokal Ollama med JSON-schema; OpenAI Responses er et valgfritt alternativ.
- Maks fem totale vurderingsforsøk, begrenset antall modellkall og batchstopp ved gjentatte feil.
- SQLite med historikk, atomiske saksreservasjoner, modellbruk og menneskelig vurdering.
- Versjonert modellregister med integritetskontroll og tilbakeføring til en tidligere kjøring.
- Dashboard for oppsett, data, modell, saksbehandling, manuell kø og drift.

## Reproduser og test

```bash
python3 run.py --demo
python3 run.py --check
python3 run.py --setup --dev
.venv/bin/python -m ruff check .
.venv/bin/python -m coverage run --branch -m unittest discover -s tests
.venv/bin/python -m coverage report
```

`--demo` bruker separat demo-database og demo-modellregister. Aktiv arbeidsmodell endres ikke.
Demo og tester bruker ingen ekte LLM-kall. GitHub Actions kjører kodekontroll,
formatering, tester og oppsettskontroll på Python 3.11 og 3.13 ved neste push/PR.
`requirements-lock.txt` beskriver det verifiserte Python 3.13-miljøet; normal
installasjon bruker plattformkompatible intervaller fra `requirements.txt`.

## Hva resultatene dokumenterer

De to datafilene har 66 663 rader til sammen. Sju N-PX-rader mangler forslagstekst.
N-PX-forvalterens identitet er ikke verifisert; filen blandes ikke med NBIM-fasit.
Se [datagjennomgangen](docs/DATA_REVIEW.md).

Den første logistiske modellen ble evaluert på 2026 etter trening på tidligere år.
Den fikk MOT-presisjon 18,0 % og recall 54,55 %. Dette er historisk stemmeprediksjon,
ikke en måling av LLM-begrunnelser. Se [resultatene og avgrensningene](docs/MODEL_RESULTS.md).
En ny trening lagres som en egen kjøring; rapporter må knyttes til riktig modell-ID.

Den medfølgende policyen er åtte kuraterte parafraser fra 2025, med et konservativt
datovindu 17. februar–31. desember. Saker utenfor dekningen eller uten tilstrekkelige
selskapsfakta overleveres til mennesker. Teknisk `AVSTÅ` markeres som reserveutfall.
En kontrollagents godkjenning er ikke i seg selv dokumentasjon på faktisk korrekthet.

## Kilder og AI-bruk

- [NBIM Voting](https://www.nbim.no/en/responsible-investment/voting/)
- [NBIM Global voting guidelines 2025](https://www.nbim.no/contentassets/01a7ee19b5d84a73a67a365e76a0fb01/global-voting-guildeines_2025.pdf)
- [Ollama Structured Outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Qwen2.5 7B](https://ollama.com/library/qwen2.5:7b)
- [LangGraph](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

CSV-filene ble levert av teamet; eksportmetode og råkilde per rad er ikke dokumentert.
Filhash gir sporbarhet til filen, ikke bevis på autentisitet. Demoeksemplene er syntetiske.
Codex ble brukt til datagjennomgang, kode, arkitektur, dokumentasjon og tester.
