import pandas as pd
import streamlit as st

from nbim_flow.monitoring import input_shift, operational_snapshot
from nbim_flow.registry import read_report

from .common import APP_ERRORS, json_text


def render_operations(settings, dataset):
    st.header("Drift og overvåkning")
    selected = st.radio("Modus", ["LLM", "Demo"], horizontal=True, key="ops_mode")
    snapshot = operational_snapshot(settings.database_path, "llm" if selected == "LLM" else "demo")
    cols = st.columns(4)
    cols[0].metric("Siste saksversjoner", snapshot["current_case_count"])
    cols[1].metric("Til manuell vurdering", snapshot["human_review_pending"])
    cols[2].metric("Modellkall", snapshot["api_calls"])
    cols[3].metric("Gjenbrukte resultater", snapshot["cache_hits"])
    st.caption(
        f"Tokens: {snapshot['input_tokens']:,} inn / {snapshot['output_tokens']:,} ut. "
        "Antall tokens er målt for fullførte svar; avbrutte leverandørkall kan mangle forbrukstall."
    )
    for alert in snapshot["alerts"]:
        (st.warning if alert["level"] == "warning" else st.info)(alert["message"])
    rows = []
    for item in snapshot["recent_batches"]:
        summary = item.get("summary") or {}
        rows.append(
            {
                "Batch": item["batch_id"][:12],
                "Start": item["started_at"],
                "Status": item["status"],
                "Behandlet": summary.get("processed"),
                "Feil": summary.get("errors"),
                "Kall": summary.get("api_calls"),
                "Stoppårsak": summary.get("stopped_reason"),
            }
        )
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("Ingen batcher er registrert i denne modusen ennå.")
    if dataset:
        try:
            report = read_report(settings.root / "artifacts/model")
            shift = input_shift(dataset["records"], report.get("input_profile"))
            with st.expander("Endringer i innkommende data"):
                st.caption(
                    "Temafordeling sammenlignes med en lagret referanse. Dette er ikke en statistisk test eller dokumentasjon på modellforverring."
                )
                if shift.get("warning"):
                    st.warning(
                        "Temafordelingen er endret. Vurder om modellen fortsatt er relevant for disse sakene."
                    )
                st.json(shift)
        except APP_ERRORS:
            pass
    with st.expander("Alle driftsmetadata"):
        st.json(snapshot, expanded=False)
    st.download_button(
        "Last ned driftsrapport", json_text(snapshot), "driftsrapport.json", "application/json"
    )
