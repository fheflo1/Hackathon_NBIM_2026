# Datagjennomgang og anbefalt bruk

Gjennomgangen er kjørt på samtlige rader i de to medfølgende CSV-filene. Tallene nedenfor gjelder disse filene, før eventuell ny datainnhenting. Originalfilene og startpakkens skript er beholdt uendret.

## Omfang og kildestatus

| Egenskap | `real_votes.csv` | `npx_votes.csv` |
|---|---:|---:|
| Rader | 13 757 | 52 906 |
| Kolonner | 22 | 25 |
| Første møtedato | 2019-01-23 | 2023-07-02 |
| Siste møtedato | 2026-09-30 | 2026-06-30 |
| Unike selskaps-ID-er, inkludert tom verdi | 194 | 2 551 |
| Unike møte-ID-er | 1 161 | 4 568 |
| Unike forslagstekster, inkludert tom verdi | 5 110 | 43 273 |
| Unike nøkler `(meeting_id, item_no)` | 13 757 | 52 906 |

Filnavn og kolonnenavnet `nbim_vote` er ikke tilstrekkelig dokumentasjon på opphav. N-PX-filen har blant annet CUSIP-liknende selskaps-ID-er og aggregater fra flere fond. Forvalter, fond, innsending og aggregeringsregel er ikke verifisert fra en råkilde. **Ikke behandle N-PX-stemmene som NBIM-fasit.** Bruk filene separat, og dokumenter proveniens før sammenslåing eller trening mot en felles målvariabel. `real_votes.csv` har et NBIM-liknende format, men den opprinnelige uthentingen er heller ikke dokumentert her.

## Stemmer og ukjente utfall

| Normalisert verdi | Real | N-PX |
|---|---:|---:|
| FOR | 12 598 | 45 939 |
| MOT | 757 | 2 970 |
| AVSTÅ | 68 | 983 |
| Ukjent / ikke støttet | 334 | 3 014 |
| Sum kjente etiketter | 13 423 | 49 892 |
| MOT blant kjente etiketter | 5,64 % | 5,95 % |

`Against` og `Withhold` grupperes til MOT for klassifikasjon. Dette er en modelleringsforenkling: WITHHOLD har en annen juridisk betydning, og råverdien beholdes i `labels.jsonl`. `None`, `Do Not Vote`, `One Year` og `Three Years` er ikke AVSTÅ.

| Råverdi uten støttet normalisert etikett | Real | N-PX |
|---|---:|---:|
| Tom råverdi | 0 | 2 779 |
| `None` | 283 | 0 |
| `Do Not Vote` | 13 | 0 |
| `One Year` / `ONE YEAR` | 34 | 107 |
| `1 YEAR` | 0 | 128 |
| `Three Years` | 4 | 0 |

Ukjente etiketter beholdes i innkommende saksdata, slik at agenten fortsatt kan behandle saken. De utelates fra supervisert trening og fra metrikker som krever fasit.

## Mangler og kvalitetsflagg

| Felt / observasjon | Real | N-PX |
|---|---:|---:|
| Tom `proposal_text` | 0 | 7 |
| Tom `company_id` | 0 | 5 |
| Tom `country` | 0 | 18 |
| Tom `ticker` | 0 | 52 906 |
| Tom `proposal_number` | 0 | 52 906 |
| Tom normalisert `mgmt_rec` | 421 | 3 665 |
| Tom `rationale_text` | 13 130 | 52 906 |
| Tom `position_paper` | 13 390 | 52 906 |
| Tom `rationale_section` | 13 139 | 52 906 |
| `injection_flag = 1` | 0 | 141 |
| `funds_disagree = 1` | Ikke oppgitt | 4 |

De 141 flaggede N-PX-radene inkluderer tomme forslag og støy som «THE BOARD OF DIRECTORS RECOMMENDS: A». Flagget dokumenterer ikke at en rad inneholder et faktisk instruksjonsangrep. Et enkelt søk etter uttrykk som ber modellen ignorere retningslinjer fant ingen åpenbare slike angrep. Dette er heller ikke en sikkerhetsgaranti. I implementasjonen kalles flagget `source_quality_flag`, og merkede rader utelates fra trening. Motstandstesten skal bruke egne, eksplisitt konstruerte angrep og rapportere resultatet separat.

De fire radene med fondsuenighet utelates også fra trening. En aggregert flertallsstemme kan skjule relevante forskjeller mellom forvaltere eller fond.

## Datalekkasje

Historisk stemme og etterfølgende begrunnelse skal ligge i en egen evaluerings-/etikettfil, uten tilgang fra beslutningsagenten. I Real finnes begrunnelse på 627 rader: 574 MOT, 40 FOR og 13 AVSTÅ. Bare det at begrunnelsesfeltet er fylt ut gir dermed 91,5 % MOT i denne delmengden. Dette ville gi svært misvisende modellresultater.

Følgende brukes ikke som prediksjonsinput:

- `nbim_vote`, `nbim_vote_raw` og `against_board`.
- `rationale_text`, `position_paper` og `rationale_section` fra historiske avstemninger.
- `injection_flag`, `funds_disagree`, `n_funds` og `split_year`.
- Den eksisterende `proposal_type`, fordi prosessen som laget den ikke er dokumentert.

Agentinput bygges fra en eksplisitt tillatt liste med saksopplysninger. `mgmt_rec` kan brukes som en opplysning som var tilgjengelig før avstemningen. Et enkelt `topic` avledes direkte fra forslagsteksten for ruting. Det er verken en fasit eller en automatisk stemmeanbefaling.

## Identitet, duplikater og tidsrekkefølge

Bruk `(source, meeting_id, item_no)` som identitet. `proposal_number` er reserve dersom `item_no` mangler. `source` må angis eksplisitt; N-PX og Real bruker forskjellige ID-systemer.

I disse filene finnes ingen duplikater på møte og punkt. Derimot vil `(company_id, meeting_date, item_no)` gi 141 overskytende rader i Real. Det kan være ulike møter samme dag, blant annet en separat registreringssak. Denne nøkkelen må derfor ikke brukes til å slå sammen saker.

Lik forslagstekst er heller ikke en duplikatnøkkel. Mange selskaper gjentar standardforslag. De to filene deler 543 eksakte forslagstekster, men har ingen felles kildeinterne møte-/punktnøkler. Dette dokumenterer ikke at sakene er identiske.

Implementasjonen fjerner identiske gjentakelser av samme nøkkel. Dersom samme nøkkel har ulike data, inkludert ulike historiske etiketter, legges hele gruppen i karantene. Den velger ikke en vilkårlig vinner. Originalfilen beholdes; i normaliserte tekster brukes Unicode NFC og konsistent mellomrom.

Alle observerte datoer er gyldige ISO-datoer, og `year` samsvarer med kalenderåret i `meeting_date`. N-PX-feltet `split_year` følger derimot rapporteringsår: et møte i juli 2023 kan ha `split_year = 2024`. Bruk faktisk møtedato til train/validation/test, og hold hele samme møtedag på én side av en tidsgrense. Ikke bruk tilfeldig radfordeling.

## Resultatet av preprocessing

| Resultat | Real | N-PX |
|---|---:|---:|
| Godkjente saksrader for videre behandling | 13 757 | 52 899 |
| Karantene | 0 | 7 |
| Identiske duplikater fjernet | 0 | 0 |
| Konfliktgrupper | 0 | 0 |
| Treningsberettigede rader | 13 423 | 49 796 |

De sju N-PX-radene i karantene mangler forslagstekst. Antall treningsrader er lavere enn antall kjente etiketter fordi manglende saksinnhold, kildekvalitetsflagg og fondsuenighet også tas hensyn til. Manglende selskaps-ID eller land flagges, men er ikke alene grunn til karantene når møte og punkt gir entydig kildeidentitet.

For å gjenskape rapporten, kjør fra prosjektmappen:

```python
import json
from nbim_flow.data import prepare_csv, write_prepared

for source, filename in [("real", "real_votes.csv"), ("npx", "npx_votes.csv")]:
    result = prepare_csv(f"data/{filename}", source=source)
    print(json.dumps(result["report"], ensure_ascii=False, indent=2))
    write_prepared(result, f"data/processed/{source}")
```

`records.jsonl` inneholder bare tillatte saksopplysninger. `labels.jsonl` inneholder historiske utfall, råstemmer, treningsstatus og kvalitetsflagg. `quarantine.jsonl` dokumenterer avviste rader med årsak. `report.json` teller hele inputfilen, også rader som senere legges i karantene. Den inneholder også `input_sha256`, en SHA-256 av de eksakte inputbytene, og `preprocessing_version` for å identifisere kjøringen og transformasjonen. `evidence_hash` endres når saksopplysninger endres; endret historisk fasit endrer ikke agentens evidenshash.

## Baseline og realistisk evaluering

Startpakkens `baseline.py` beskriver «stem alltid som styret», men koden lager faktisk bare FOR-prediksjoner. Originalskriptet er beholdt uendret. Bruk en eksplisitt implementasjon som kopierer `mgmt_rec` når denne finnes, og oppgi nevneren. En alltid-FOR-baseline har null recall på MOT.

Følgende kontroll kopierer den normaliserte styreanbefalingen og inkluderer bare rader med både kjent historisk stemme og kjent styreanbefaling:

| Data og periode | Rader | Accuracy | MOT-presisjon | MOT-recall |
|---|---:|---:|---:|---:|
| Real, alle år | 13 325 | 94,42 % | 62,10 % | 10,43 % |
| Real, 2026 | 1 539 | 95,71 % | 57,14 % | 12,12 % |
| N-PX, alle år | 49 006 | 96,05 % | 68,07 % | 62,23 % |
| N-PX, 2026 | 15 003 | 96,08 % | 60,10 % | 63,45 % |

Dette er beskrivende beregninger på originaldataene, ikke resultatene av en trent modell. De bruker ikke de ytterligere treningsfiltrene over. Rapporter minst MOT-presisjon, MOT-recall, F1, klassestøtte og andel som sendes til manuell vurdering. Vis resultater per kilde. Den store forskjellen mellom filene understreker at en felles fasit ikke kan antas.

## Evidens som fortsatt mangler

Forslagsteksten «Elect Director X» viser hva som skal avgjøres, men dokumenterer ikke styrets uavhengighet, styremedlemmets antall verv, oppmøte eller relevante interessekonflikter. Tilsvarende dokumenterer en revisorgodkjenning ikke revisors uavhengighet eller honorarfordelingen. En modell skal ikke fylle disse hullene med historisk stemmebegrunnelse.

Policy må komme fra en eksplisitt, versjonert NBIM-kilde med referanse og gyldighetsdato. Retningslinjer som publiseres etter møtedato skal ikke brukes som om de var kjent den gangen. Ved historisk evaluering må både selskapsopplysninger og policy ha vært tilgjengelige før avstemningen.

Den medfølgende policy-pakken er en begrenset kuratert delmengde, med et konservativt tillatt datointervall fra 2025-02-17 til og med 2025-12-31. Den dekker ikke hele NBIMs regelverk eller alle historiske versjoner. Saker utenfor dette tidsintervallet eller uten en dekkende regel må markeres for manuell vurdering. Pakken gir derfor ikke grunnlag for å kalle alle historiske saker ferdigbehandlet eller for å evaluere full regelverksetterlevelse for 2019–2026.

En uavhengig kontrollagent kan kontrollere kildehenvisning, konsistens og om begrunnelsen har støtte i tilgjengelig evidens. Den kan ikke gjøre manglende fakta sanne. Etter maksimalt antall forsøk skal et teknisk fallback AVSTÅ merkes som fallback og `needs_human_review`, slik at det kan skilles fra en policybegrunnet avståelse.

## Testdata holdes utenfor produktet

Demodata er fjernet fra `data/` og fra appens datavalg. Syntetiske saker brukes kun i automatiske tester under `tests/fixtures/`. De inngår ikke i modelltrening eller i datavisningens antall.
