"""The documented end-to-end flow; no external rendering service is required."""

WORKFLOW_MERMAID = """flowchart TD
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
"""
