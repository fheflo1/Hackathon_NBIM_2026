# Hele arbeidsflyten

Diagrammet viser både trening, ekte modellkjøring, gjenbruk og manuell oppfølging.
LLM-agentene kan kjøre lokalt via Ollama; OpenAI er et eksplisitt alternativ.

```mermaid
flowchart TD
    Setup[Oppsett og doctor] --> Mode{Valg av kjøring}
    Mode -->|Demo| Input
    Mode -->|LLM| Probe[Syntetisk API-test]
    Probe --> Input[CSV eller saksliste]
    Input --> Prep[Valider skjema, dato, identitet og tekst]
    Prep -->|Ugyldig eller konflikt| Quarantine[Karantene med årsak]
    Prep --> Facts[Tillatte fakta og evidence_hash]
    Prep --> Labels[Separat historisk fasit]
    Labels --> Train[Tidsdelt trening og evaluering]
    Facts --> Train
    Train --> Registry[Versjonert modellregister]
    Registry --> Priority[Valgfri prioritering av alle saker]
    Facts --> Priority
    Priority --> Cache{Samme fakta, policy og beslutningsversjon?}
    Cache -->|Ja| Reuse[Gjenbruk lagret resultat]
    Cache -->|Nei| Claim[Atomisk saksreservasjon]
    Claim --> Gates{Policydekning og dokumentkontroll}
    Gates -->|Mangler grunnlag eller mulig angrep| Manual
    Gates -->|OK| Budget{API-budsjett igjen?}
    Budget -->|Nei| Deferred[Utsett resten av batchen]
    Budget -->|Ja| Author[Agent 1 foreslår For, Mot eller Avstå]
    Author --> Sources[Kontroller format, policy-ID og eksakte datasitater]
    Sources -->|Gyldig| Reviewer[Agent 2 kontrollerer sammenheng og faktagrunnlag]
    Sources -->|Feil| Retry
    Reviewer -->|Godkjent| Result[Kontrollert anbefaling]
    Reviewer -->|Avvist| Retry{Kan rettes og færre enn fem forsøk?}
    Retry -->|Ja| Budget
    Retry -->|Nei| Manual[Avstå som reserveutfall og manuell kø]
    Author -->|API-feil| Circuit[Logg feil og vurder batchstopp]
    Reviewer -->|API-feil| Circuit
    Circuit --> Deferred
    Result --> Audit[(SQLite med versjoner, forsøk og hendelser)]
    Manual --> Audit
    Deferred --> Audit
    Reuse --> Audit
    Audit --> Human[Menneskelig vurdering med navn og begrunnelse]
    Human --> Audit
    Audit --> Dashboard[Dashboard, logger og driftsmålinger]
    Registry --> Dashboard
    Quarantine --> Dashboard
    Audit --> Evaluation[Evaluering mot separat fasit med dekning]
    Labels --> Evaluation
```

Mermaid-kilden kan også lastes ned fra Workflow-siden eller skrives ut med
`python3 run.py --cli workflow`.

En vellykket tilkoblingstest betyr ikke at stemmen er riktig. Kontrollagenten kan
avvise en teknisk gyldig anbefaling. Oppbrukt API-budsjett utsetter behandling;
manglende fakta gir en synlig manuell kø. Ingen stemme sendes eksternt.
