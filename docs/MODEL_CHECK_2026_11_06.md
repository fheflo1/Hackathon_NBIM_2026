# Modellkontroll og produktavgrensning – 6. november 2026

## Hva løsningen gjør

STEM gir beslutningsstøtte til gjennomgang av generalforsamlinger: last opp PDF, CSV eller TXT, gjennomgå forslagene, følg opp saker merket Manuell og eksporter CSV som underlag. Appen sender ikke stemmer og har ingen funksjon for å registrere et endelig menneskelig vedtak.

Verdien er mindre manuelt forarbeid, tydeligere prioritering, sporbare begrunnelser og gjenbruk av uendrede saksgrunnlag. Tidsbesparelsen er foreløpig ikke målt. Historiske stemmetall i toppfeltet er adskilt fra forslagene for opplastet saksliste.

## Faktisk testet i dette oppsettet

Maskinen har 16 GB minne og Apple Silicon. Aktiv vurderings- og kontrollmodell er `qwen2.5:7b` via lokal Ollama. Ingen modellinnstillinger eller vekter er endret. Kontrollsakene er syntetiske og kjørt direkte mot provider, uten å lagres som sakslister eller resultater i appen.

- Forslag om separate styreleder- og CEO-roller: For, gyldig struktur og kildehenvisning. Kontrollagenten aksepterte. To kall tok totalt 20,41 sekunder, inkludert modellinnlasting.
- Forslag om stemmerettsbegrensninger: Mot, gyldig struktur og kildehenvisning.
- Bevisst feil For-forslag for stemmerettsbegrensninger: kontrollagenten avviste. De to siste kallene tok totalt 16,01 sekunder.
- Aktiv `triage-lr-v2` lastet og scoret alle fem punkter i et eksisterende møte fra 2025 med endelige scoreverdier mellom 0 og 1. Dette er en funksjonskontroll, ikke en ny kvalitetsmåling.

Disse fire LLM-kallene bekrefter tilkobling og noen enkle egenskaper. De tester ikke hele opplastingsflyten, PDF-uttrekk, lett kontroll eller kvaliteten på et representativt datasett. Første begrunnelse inneholdt ordet «ulovlighet» i en sammenheng der det ikke var støtte for dette. Kontrollagenten aksepterte likevel. Samme modell i to roller gir ikke uavhengig etterprøving eller garanti mot felles feil. Konfidens er selvrapportert, ikke kalibrert.

## Triage: brukbar rangering, utilstrekkelig som automatisk godkjenning

Det aktive modellkortet oppgir trening til og med 2023 og validering på 1 883 saker i 2024. Med dagens terskler: 48 riktige flagg, 29 falske flagg og 50 avvik som ikke ble flagget. Presisjon er 62,3 %, recall 49,0 % og average precision 0,558. Målet er avvik fra styrets anbefaling; dette er ikke identisk med alle Mot-stemmer.

Ingen `holdout_report.json` er tilgjengelig i dette oppsettet. Det er ikke kjørt en ny evaluering av det låste testsettet. Gode samlede accuracy-tall er ikke tilstrekkelig når nesten alle saker følger styret.

Den lette veien kan lagre et resultat som `verified` uten samme kildeverifikasjon og separate kontrollagent som fullflyten. Den kan også mangle kildehenvisning. Frontenden viser derfor behandlingsvei og omtaler stemmene som forslag. Denne UI-endringen endrer ikke backendens ruting eller eksportstatus.

Policyfilen er et kuratert utdrag med åtte regler og datovindu 17. februar–31. desember 2025. Dette er prototypens avgrensning, ikke et komplett eller oppdatert regelverk for alle år. Fullflytens policyport gjelder ikke på samme måte i den lette veien. Lav risiko bør ikke alene brukes som grunnlag for ferdigbehandling.

## Modellvalg

Behold logistisk regresjon som en enkel, forklarbar baseline og Qwen 2.5 7B som fungerende LLM-baseline. Utvid policydekningen og etabler en manuelt kontrollert evaluering av 30–50 varierte saker før modellbytte. Mål stemmevalg, kildestøtte, avvisning av uriktige begrunnelser, eskalering, tidsbruk og minnebruk. Disse sakene må holdes adskilt fra triagens låste testsett.

`qwen3:8b` er en mulig sammenligningskandidat, ikke en dokumentert forbedring for dette prosjektet. Ollama oppgir 5,2 GB for Q4_K_M-vektene; faktisk minnebruk inkluderer også kontekstvindu og runtime. Thinking og tokengrenser må tilpasses og testes; dagens klient sender ingen eksplisitt `think`-innstilling. Ikke bytt begge agentroller samtidig uten målinger. Et modellbytte løser ikke manglende policydekning eller svak ruting alene.

Kilder: [Qwen 2.5 7B](https://ollama.com/library/qwen2.5:7b), [Qwen 3 8B](https://ollama.com/library/qwen3:8b), [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs), [Ollama thinking](https://docs.ollama.com/capabilities/thinking).
