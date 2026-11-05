# Resultater fra den første prioriteringsmodellen

Reproduser fra repoets rot etter installasjon:

```bash
python -m nbim_flow train --source real
```

Maskinlesbare resultater lagres i `artifacts/model/report.json`, og hver
testprediksjon i `artifacts/model/test_predictions.csv`. Tallene under er fra
de medfølgende dataene, kjørt 5. november 2026. De gjelder historisk
stemmeklassifisering og prioritering, ikke kvaliteten på LLM-agentens begrunnelser.

## Data og tidsdeling

Modellen bruker bare `proposal_text` fra `data/real_votes.csv`. Historiske
stemmer kobles på separat som målvariabel. Begrunnelser, policyreferanser,
historiske kategorier og kildenes kvalitetsflagg er utelatt som modellfeatures.
Ukjente stemmeverdier inngår ikke i trening eller evaluering.

| Del | Møtedato fra–til | Antall | FOR | MOT | AVSTÅ |
|---|---|---:|---:|---:|---:|
| Trening | 2019-01-23–2024-12-11 | 9 954 | 9 318 | 577 | 59 |
| Validering | 2025-01-15–2025-12-02 | 1 927 | 1 809 | 114 | 4 |
| Holdout | 2026-01-22–2026-09-30 | 1 542 | 1 471 | 66 | 5 |

TF-IDF med en- og toordsuttrykk tilpasses bare treningsdata. Deretter trenes
logistisk regresjon med `class_weight="balanced"`, `random_state=42` og
`max_iter=1000`. Modellen refittes ikke på validerings- eller testdata.

2026 er et ufullstendig år i datagrunnlaget: siste møtedato er 30. september.
Rapporten må derfor ikke omtales som et resultat for hele stemmeåret 2026.

## Prediksjon av historisk stemme

Her velges den av de tre klassene som har høyest modellscore.

| Metode og evalueringsgrunnlag | N | Presisjon MOT | Recall MOT | F1 MOT | Accuracy |
|---|---:|---:|---:|---:|---:|
| Logistisk regresjon, hele holdout | 1 542 | 18,00 % | 54,55 % | 0,2707 | 81,52 % |
| Alltid FOR, hele holdout | 1 542 | 0,00 % | 0,00 % | 0,0000 | 95,40 % |
| Følg faktisk styreanbefaling, der den er kjent | 1 539 | 57,14 % | 12,12 % | 0,2000 | 95,71 % |
| Logistisk regresjon, samme styretilgjengelige utvalg | 1 539 | 18,18 % | 54,55 % | 0,2727 | 81,61 % |

Styrebaselinen kopierer faktisk `mgmt_rec`. Tre testpunkter uten støttet
styreanbefaling er utelatt bare fra denne sammenligningen. Dette skiller en
reell styrebaseline fra «alltid FOR».

Modellen finner 36 av 66 MOT-stemmer, men 164 av dens 200 MOT-prediksjoner
er falske positive. Den forbedrer recall og F1 på det sammenlignbare utvalget,
mens presisjonen faller tydelig. Dette er en avveining, ikke en forbedring
på alle kvalitetsmål. Average precision for MOT er 0,3025 på hele holdout;
MOT-andelen er 4,28 %. Average precision er rapportert som diskret PR-oppsummering,
ikke trapesintegrert areal.

Forvekslingsmatrise for modellen, hele holdout:

| Faktisk stemme / Predikert stemme | FOR | MOT | AVSTÅ |
|---|---:|---:|---:|
| FOR | 1 221 | 162 | 88 |
| MOT | 28 | 36 | 2 |
| AVSTÅ | 3 | 2 | 0 |

Radene er faktiske klasser og kolonnene predikerte klasser. De fem faktiske
AVSTÅ-stemmene blir ikke truffet. Sjeldne AVSTÅ-eksempler og manglende selskapsfakta
gjør treklassers stemmeprediksjon utilstrekkelig som automatisk beslutningsgrunnlag.

## Prioritering av køen

Køprioritering er en separat bruk av modellens MOT-score. Vi velger den høyeste
terskelen som gir minst 80 % MOT-recall på valideringsdata. Terskelen velges
uten å bruke testlabels og blir `0.1366637709244659`. På valideringssettet gir
den recall 80,70 % og presisjon 11,53 %.

På holdout gir samme terskel:

| Mål | Verdi |
|---|---:|
| MOT funnet i prioritert kø | 52 av 66 |
| MOT-recall | 78,79 % |
| MOT-presisjon i prioritert kø | 7,89 % |
| F1 for prioritetsflagget | 0,1434 |
| Punkter i prioritert kø | 659 av 1 542 (42,74 %) |
| Falske positive i prioritert kø | 607 |
| MOT utenfor prioritert kø | 14 |

Dette betyr at 42,74 % av testpunktene kan behandles først, og at denne delen
inneholder 78,79 % av de historiske MOT-stemmene. Alle punkter beholdes i
dataflyten. Resultatet dokumenterer ingen reduksjon i antall nødvendige
agentkjøringer, og en lav score gir aldri automatisk FOR eller godkjenning.

## Begrensninger og neste målinger

- Scorene er ukalibrerte. Klassevekting gjør at de ikke uten videre kan leses
  som faktiske sannsynligheter for at NBIM stemmer MOT.
- Resultatet gjelder medfølgende `real`-data. Kildens autentisitet er ikke
  uavhengig revidert. N-PX-forvalterens identitet er uavklart; kildene trenes
  og evalueres separat og blandes ikke.
- Samme standardformulering kan forekomme på tvers av år. Møtedatoene er
  adskilt, men dette er ingen test på helt nye forslagstyper eller selskaper.
- Målvariabelen er historisk stemme, ikke «mot styret». Disse oppgavene er
  forskjellige, særlig for aksjonærforslag som styret anbefaler MOT.
- En regelreferanse og en LLM-kontroll må evalueres separat fra klassifikatoren.
  Man trenger sakspapirer og selskapsfakta tilgjengelige før møtet for å
  begrunne flere beslutninger enn forslagsteksten alene tillater.
- Eventuelle klynger er utforskende tekstgrupper. De tilpasses bare treningstekst
  og endrer verken stemme, kontroll eller hvilke punkter som behandles.

Før score brukes til å redusere faktisk arbeidsmengde, bør teamet måle
kalibrering, kostnad per sak, feilrate blant ferdigbehandlede saker og
andel saker som må vurderes av et menneske. En eventuell terskel for å hoppe
over agentbehandling må vurderes i en ny tidsdelt test; den finnes ikke i
denne versjonen.
