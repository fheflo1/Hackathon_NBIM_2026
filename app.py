"""Lokalt dashboard. Start med: python -m streamlit run app.py."""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import tempfile

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from nbim_flow.data import prepare_csv, write_prepared


ROOT = Path(__file__).resolve().parent
ARTIFACTS = ROOT / "artifacts"
DB_PATH = ARTIFACTS / "audit.sqlite"
MODEL_DIR = ARTIFACTS / "model"
POLICY_PATH = ROOT / "policies" / "nbim_2025.json"


@st.cache_data(show_spinner=False)
def read_dataset(path: str, source: str, size: int, modified_ns: int) -> dict:
    """The file signature invalidates the cache when a CSV is replaced."""
    del size, modified_ns
    return prepare_csv(path, source)


def serializable(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def safe_csv(rows: list[dict]) -> str:
    """Prevent spreadsheet formula execution in exported document text."""
    if not rows:
        return ""
    fields = list(dict.fromkeys(key for row in rows for key in row))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        cleaned = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                value = "'" + value
            cleaned[key] = value
        writer.writerow(cleaned)
    return stream.getvalue()


def saved_report() -> dict | None:
    path = MODEL_DIR / "report.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            st.warning(f"Kunne ikke lese modellrapporten: {exc}")
    return None


def saved_results() -> list[dict]:
    if not DB_PATH.exists():
        return []
    from nbim_flow.workflow import load_results

    return load_results(str(DB_PATH))


def display_results(results: list[dict]) -> None:
    if not results:
        st.info("Ingen saker er behandlet ennå. Kjør en begrenset batch ovenfor.")
        return
    review_count = sum(bool(row.get("needs_human_review")) for row in results)
    cols = st.columns(3)
    cols[0].metric("Lagrede resultater", len(results))
    cols[1].metric("Til manuell vurdering", review_count)
    cols[2].metric("Nye forsøk", sum(int(row.get("retries") or 0) for row in results))
    only_review = st.checkbox("Vis bare saker som trenger manuell vurdering", value=False)
    shown = [row for row in results if row.get("needs_human_review")] if only_review else results
    if not shown:
        st.info("Ingen saker i dette utvalget.")
        return
    frame = pd.DataFrame(shown)
    display_cols = [
        col for col in ["company", "meeting_date", "vote", "status", "needs_human_review",
                        "attempts", "retries", "confidence", "mode", "updated_at"]
        if col in frame.columns
    ]
    st.dataframe(frame[display_cols], hide_index=True, width="stretch")
    selected = st.selectbox(
        "Se begrunnelse, dokumentgrunnlag og referanser",
        options=range(len(shown)),
        format_func=lambda index: (
            f"{shown[index].get('company', 'Ukjent selskap')} · "
            f"{shown[index].get('meeting_date', '')} · "
            f"{shown[index].get('record_id', '')[:12]} · "
            f"{shown[index].get('run_key', '')[:8]}"
        ),
    )
    result = shown[selected]
    st.markdown("**Forslag**")
    st.text(result.get("proposal_text", ""))
    st.markdown("**Begrunnelse**")
    st.write(result.get("reason", "Ingen begrunnelse tilgjengelig."))
    if result.get("needs_human_review"):
        st.warning("Saken krever menneskelig vurdering. «Avstå» som reserveutfall er ikke en ferdig beslutning.")
    st.markdown("**Kildehenvisninger**")
    st.json(result.get("citations", []), expanded=True)
    with st.expander("Alle metadata for saken"):
        st.json(result)
    cols = st.columns(2)
    cols[0].download_button(
        "Last ned utvalget som JSON", data=serializable(shown),
        file_name="saksbehandling.json", mime="application/json",
    )
    cols[1].download_button(
        "Last ned utvalget som CSV", data=safe_csv(shown).encode("utf-8-sig"),
        file_name="saksbehandling.csv", mime="text/csv",
    )


def main() -> None:
    load_dotenv(ROOT / ".env")
    st.set_page_config(page_title="NBIM · Stemmegivningsagenten", page_icon="🗳️", layout="wide")
    st.title("Stemmegivningsagenten")
    st.caption("Fra saksliste til begrunnet anbefaling – med kontroll, historikk og manuell oppfølging.")
    st.markdown("**Data → kvalitetssjekk → prioritering → anbefaling → kontroll → resultat / manuell vurdering**")

    with st.sidebar:
        st.header("Datagrunnlag")
        choice = st.selectbox("Velg kilde", ["Demoeksempler", "NBIM-data", "N-PX-data", "Last opp CSV"])
        source = {"Demoeksempler": "upload", "NBIM-data": "real", "N-PX-data": "npx", "Last opp CSV": "upload"}[choice]
        dataset = None
        if choice == "Last opp CSV":
            uploaded = st.file_uploader("CSV med samme agendakolonner", type=["csv"])
            st.caption("Opplastede stemmeetiketter regnes ikke som bekreftede NBIM-stemmer.")
            if uploaded is not None and st.button("Les og kontroller opplastingen"):
                try:
                    with tempfile.NamedTemporaryFile(suffix=".csv") as tmp:
                        tmp.write(uploaded.getvalue())
                        tmp.flush()
                        st.session_state["uploaded_dataset"] = prepare_csv(tmp.name, "upload")
                except (OSError, ValueError, csv.Error) as exc:
                    st.error(f"Kunne ikke lese CSV-filen: {exc}")
            dataset = st.session_state.get("uploaded_dataset")
        else:
            filename = {"Demoeksempler": "demo_agenda.csv", "NBIM-data": "real_votes.csv", "N-PX-data": "npx_votes.csv"}[choice]
            path = ROOT / "data" / filename
            if path.exists():
                signature = path.stat()
                try:
                    with st.spinner("Kontrollerer dataene …"):
                        dataset = read_dataset(str(path), source, signature.st_size, signature.st_mtime_ns)
                except (OSError, ValueError, csv.Error) as exc:
                    st.error(f"Kunne ikke lese datagrunnlaget: {exc}")
            else:
                st.error(f"Mangler data/{path.name}. Se README for oppsett.")
        if source == "npx":
            st.info("Forvalteren bak N-PX-etikettene må bekreftes. Disse brukes ikke som NBIM-fasit.")
        if choice == "Demoeksempler":
            st.info("Fire syntetiske eksempler: to smale policyregler, én sak med manglende informasjon og én instruksjonsinjeksjon.")
        st.divider()
        st.caption("Demo bruker ingen API-nøkkel. Historiske stemmer og begrunnelser holdes utenfor agentens input.")

    tabs = st.tabs(["Data", "Prioritering", "Saksbehandling", "Sporbarhet"])

    with tabs[0]:
        st.subheader("Datakvalitet og preprocessing")
        if dataset is None:
            st.info("Velg en tilgjengelig CSV i sidepanelet.")
        else:
            report = dataset["report"]
            cols = st.columns(4)
            for col, title, key in zip(
                cols, ["Rader lest", "Godkjente saker", "Karantene", "Like dubletter"],
                ["total_rows", "accepted_records", "quarantined_rows", "duplicate_rows"],
            ):
                col.metric(title, report.get(key, 0))
            st.caption(f"Kilde: {source}. Datoavgrensning fra meeting_date: {report.get('date_range', 'ukjent')}.")
            st.write("Rådata beholdes. Ugyldige saker legges i karantene, mens ukjente stemmeetiketter utelates fra trening.")
            counts = report.get("label_counts", {})
            if counts:
                st.markdown("**Historiske stemmeetiketter**")
                st.bar_chart(pd.Series(counts, name="Antall"))
            with st.expander("Manglende verdier per kolonne"):
                st.json(report.get("missingness", {}))
            with st.expander("Eksempler på godkjente agendapunkter"):
                st.dataframe(pd.DataFrame(dataset["records"][:100]), hide_index=True, width="stretch")
            with st.expander("Karantene og kvalitetsrapport"):
                st.json(report)
                if dataset.get("quarantine"):
                    st.json(dataset["quarantine"][:20])
            if st.button("Lagre klargjorte data lokalt"):
                try:
                    prepared_name = "demo" if choice == "Demoeksempler" else source
                    write_prepared(dataset, ARTIFACTS / "prepared" / prepared_name)
                    st.success(f"Lagret under artifacts/prepared/{prepared_name}/.")
                except (OSError, ValueError) as exc:
                    st.error(f"Kunne ikke lagre: {exc}")
            st.download_button("Last ned kvalitetsrapport", data=serializable(report),
                               file_name=f"datakvalitet_{source}.json", mime="application/json")

    with tabs[1]:
        st.subheader("Prioriter arbeidskøen")
        st.write("TF-IDF og logistisk regresjon estimerer hvilke saker som kan få MOT-stemme. "
                 "Estimatet brukes til rekkefølgen i køen; alle saker skal fortsatt kontrolleres og begrunnes.")
        st.caption("Trening, validering og test følger møtedato. Terskelen velges på valideringssettet. "
                   "Sannsynlighetene er modellestimater, ikke dokumentert kalibrert konfidens.")
        target = st.slider("Ønsket recall på MOT i valideringssettet", 0.50, 1.0, 0.80, 0.05)
        clusters = 0
        if st.checkbox("Utforsk temaklynger (valgfritt)", value=False):
            clusters = st.number_input("Antall klynger", min_value=2, max_value=16, value=6, step=1)
            st.caption("Klynger organiserer tekst. De avgjør verken stemme eller hvilke saker som utelates.")
        can_train = dataset is not None and source == "real"
        if not can_train:
            st.info("Velg NBIM-data for å trene og evaluere mot samme forvalter.")
        if st.button("Tren prioriteringsmodellen", disabled=not can_train):
            try:
                from nbim_flow.model import train_model

                with st.spinner("Trener og evaluerer på senere møter …"):
                    report = train_model(dataset["records"], dataset["labels"], MODEL_DIR,
                                         target_recall=target, clusters=int(clusters))
                st.success("Modell og evalueringsrapport er lagret lokalt.")
                st.session_state["model_report"] = report
            except (ImportError, OSError, ValueError) as exc:
                st.error(f"Treningen kunne ikke fullføres: {exc}")
        report = st.session_state.get("model_report") or saved_report()
        if report:
            st.markdown("**Evaluering på historiske NBIM-data**")
            st.caption("Modellrapporten gjelder prioriteringsmodellen. Den måler ikke agentenes begrunnelser eller kontroll.")
            test = report.get("test", {})
            model_metrics = test.get("model", {})
            cols = st.columns(3)
            for col, title, key in zip(cols, ["Presisjon på MOT", "Recall på MOT", "F1 på MOT"],
                                       ["mot_precision", "mot_recall", "mot_f1"]):
                value = model_metrics.get(key)
                col.metric(title, f"{value:.1%}" if isinstance(value, (float, int)) else "–")
            comparisons = []
            for key, name in [("board_baseline", "Følg styret"),
                              ("model_on_board_available_subset", "Modell på samme utvalg")]:
                metrics = test.get(key)
                if metrics:
                    comparisons.append({
                        "Metode": name, "Antall": metrics.get("count"),
                        "Presisjon MOT": metrics.get("mot_precision"),
                        "Recall MOT": metrics.get("mot_recall"), "F1 MOT": metrics.get("mot_f1"),
                    })
            if comparisons:
                st.caption("Sammenligning på testforslag som har en kjent styreanbefaling.")
                st.dataframe(pd.DataFrame(comparisons), hide_index=True, width="stretch")
            threshold = report.get("routing_threshold", {})
            if threshold:
                st.markdown("**Prioriteringsterskel valgt på valideringssettet**")
                st.json(threshold, expanded=False)
            topics = report.get("cluster_topics")
            if topics:
                with st.expander("Ord som beskriver temaklyngene"):
                    st.json(topics)
            with st.expander("Full modellrapport, perioder og forvekslingsmatrise"):
                st.json(report, expanded=False)
            st.download_button("Last ned modellrapport", data=serializable(report),
                               file_name="modellrapport.json", mime="application/json")

    with tabs[2]:
        st.subheader("Behandle agendapunkter")
        st.info("Medfølgende policy dekker et avgrenset utvalg fra 2025. Saker fra andre år eller temaer "
                "utenfor utvalget går direkte til manuell vurdering, med reserveutfallet Avstå.")
        records_to_process = dataset["records"] if dataset is not None else []
        if choice != "Demoeksempler" and dataset is not None:
            period = st.selectbox("Datoperiode for behandlingen", ["2025 (policyutvalg)", "Alle år"])
            if period == "2025 (policyutvalg)":
                records_to_process = [row for row in records_to_process if row.get("meeting_date", "").startswith("2025-")]
        st.caption(f"{len(records_to_process):,} saker i valgt behandlingsutvalg.")
        mode_label = st.radio("Kjøremodus", ["Demo uten API", "LLM med ekstern API"], horizontal=True)
        mode = "demo" if mode_label == "Demo uten API" else "llm"
        configured = True
        if mode == "demo":
            st.info("Demo viser dataflyten med konservative, lokale regler. Den er ikke en språkmodell "
                    "og dokumenterer ikke kvaliteten til en LLM-basert stemmeagent.")
        else:
            st.warning("Denne kjøringen sender agendatekst og relevante policyutdrag til den konfigurerte API-leverandøren. "
                       "Historiske stemmer og begrunnelser sendes ikke.")
            configured = bool(os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL"))
            if not configured:
                st.info("Sett OPENAI_API_KEY og OPENAI_MODEL i miljøet før du starter LLM-modus. Se README.")
            else:
                st.caption(f"Anbefalingsmodell: {os.getenv('OPENAI_MODEL')}. "
                           f"Kontrollmodell: {os.getenv('OPENAI_REVIEWER_MODEL') or os.getenv('OPENAI_MODEL')}.")
        cols = st.columns(2)
        batch = cols[0].number_input("Maks nye saker i denne kjøringen", min_value=1, max_value=100, value=20, step=1)
        attempts = cols[1].number_input("Maks behandlingsforsøk per sak", min_value=1, max_value=5, value=5, step=1)
        model_available = source == "real" and (MODEL_DIR / "model.joblib").exists()
        use_priority = st.checkbox("Prioriter med lagret NBIM-modell", value=model_available, disabled=not model_available)
        st.caption("Fem forsøk betyr ett første forsøk og maksimalt fire nye forsøk. "
                   "Etter grensen blir reserveutfallet Avstå, med manuell oppfølging. "
                   "Uendret data og konfigurasjon gjenbruker lagrede resultater.")
        if st.button("Kjør saksbehandling", type="primary", disabled=not records_to_process or not configured):
            try:
                from nbim_flow.workflow import process_records

                with st.spinner("Vurderer saker og kontrollerer svar …"):
                    summary = process_records(
                        records_to_process, db_path=str(DB_PATH), mode=mode,
                        model=os.getenv("OPENAI_MODEL"),
                        reviewer_model=os.getenv("OPENAI_REVIEWER_MODEL"),
                        max_attempts=int(attempts), limit=int(batch), policy_path=str(POLICY_PATH),
                        model_path=str(MODEL_DIR / "model.joblib") if use_priority and model_available else None,
                    )
                st.success("Kjøringen er avsluttet. Resultater og hendelser er lagret.")
                st.json(summary)
            except (ImportError, OSError, ValueError, RuntimeError) as exc:
                st.error(f"Kjøringen kunne ikke fullføres: {exc}")
        st.divider()
        st.caption("Lagrede resultater fra alle datakilder og versjoner i den lokale databasen.")
        try:
            display_results(saved_results())
        except (OSError, ValueError, RuntimeError) as exc:
            st.error(f"Kunne ikke lese resultater: {exc}")

    with tabs[3]:
        st.subheader("Sporbarhet og nye forsøk")
        st.write("Hver behandling knyttes til innholdet i saken og versjonene av policy, arbeidsflyt og modell. "
                 "Endringer gir en ny behandling; uendrede saker gjenbrukes. "
                 "Hendelsesloggen viser hva som skjedde i hvert forsøk.")
        if not DB_PATH.exists():
            st.info("Hendelsesloggen blir tilgjengelig etter første saksbehandling.")
        else:
            try:
                from nbim_flow.workflow import load_events

                results = saved_results()
                keys = list(dict.fromkeys(row["run_key"] for row in results if row.get("run_key")))
                if keys:
                    key = st.selectbox("Velg behandling", options=keys)
                    events = load_events(str(DB_PATH), run_key=key)
                else:
                    events = load_events(str(DB_PATH))
                if events:
                    frame = pd.DataFrame(events)
                    if "payload" in frame:
                        frame["payload"] = frame["payload"].map(lambda value: json.dumps(value, ensure_ascii=False, default=str))
                    st.dataframe(frame, hide_index=True, width="stretch")
                    st.download_button("Last ned hendelsesloggen", data=serializable(events),
                                       file_name="hendelser.json", mime="application/json")
                else:
                    st.info("Ingen hendelser i dette utvalget.")
            except (OSError, ValueError, RuntimeError) as exc:
                st.error(f"Kunne ikke lese hendelsesloggen: {exc}")


if __name__ == "__main__":
    main()
