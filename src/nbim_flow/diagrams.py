"""Documented React + local-model workflow, rendered without an external service."""

WORKFLOW_MERMAID = """flowchart TD
    Upload[Last opp saksliste i React] --> FileCache{Samme fil og behandlingsversjon?}
    FileCache -->|Ja| Existing[Vis eksisterende kjøring]
    FileCache -->|Nei| Queue[FastAPI lagrer fil og oppretter jobb]
    Queue --> Format{Filformat}
    Format -->|CSV| CSV[Normaliser kolonner, tekst og dato]
    Format -->|PDF eller TXT| Extract[Lokal modell trekker ut agendapunkter]
    Extract --> Anchors[Kontroller møtedato, selskap og eksakte sitater mot dokumentet]
    CSV --> Prep
    Anchors --> Prep[Valider identitet, dato og alle agendapunkter]
    Prep -->|Feil| Invalid[Vis feil uten å stemme på deler av filen]
    Prep --> Facts[Tillatte saksfakta uten historisk fasit]
    Facts --> Cache{Samme fakta, policy, prompts og modellinnhold?}
    Cache -->|Ja| Reuse[Gjenbruk lagret resultat]
    Cache -->|Nei| Claim[Reserver saken atomisk]
    Claim --> Gates{Policydekning og dokumentkontroll}
    Gates -->|Manglende dekning eller mistenkelig innhold| Manual
    Gates -->|OK| Budget{Modellbudsjett igjen?}
    Budget -->|Nei| Stop[Stopp kjøringen og bevar ferdige saker]
    Budget -->|Ja| Author[LangGraph: agent 1 anbefaler stemme med konfidens og sitater]
    Author --> Sources[Kontroller format, konfidens, policy-ID og ordrette sitater]
    Sources -->|Gyldig| Reviewer[Agent 2 etterprøver valget og alle påstander]
    Sources -->|Feil| Retry
    Reviewer -->|Godkjent| Result[Kontrollert For, Mot eller Avstå]
    Reviewer -->|Avvist| Retry{Kan rettes uten nye fakta og innen fem forsøk?}
    Retry -->|Ja, med tilbakemelding| Budget
    Retry -->|Nei| Manual[Manuell oppfølging med Avstå som teknisk reservevalg]
    Author -->|Modellfeil| Stop
    Reviewer -->|Modellfeil| Stop
    Result --> Audit[(SQLite: kilder, versjoner, forsøk og hendelser)]
    Manual --> Audit
    Reuse --> Audit
    Stop --> Audit
    Audit --> UI[React: fremdrift, stemmetall, detaljer og CSV-eksport]
    Existing --> UI
    subgraph Historisk analyse - separat fra agentenes bevis
        Raw[NBIM og N-PX i separate kilder] --> Clean[Preprocessing og kvalitetskontroll]
        Clean --> Analysis[Datagrunnlag og faktisk stemmefordeling i React]
        Clean --> Labels[Separat historisk fasit]
        Labels --> Train[Tidsdelt logistisk baseline via CLI]
        Train --> Registry[Versjonert modellregister og evaluering]
    end
"""
