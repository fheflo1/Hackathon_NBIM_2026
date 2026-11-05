import pandas as pd
import streamlit as st

from nbim_flow.model import train_model
from nbim_flow.registry import activate_run, list_runs, read_report

from .common import APP_ERRORS, json_text


def render_model(settings, dataset, source):
    st.header("Prioriteringsmodell")
    st.write(
        "Den logistiske tekstmodellen prioriterer køen. LLM-agentene vurderer selve stemmen og begrunnelsen."
    )
    directory = settings.root / "artifacts/model"
    with st.expander("Tren på historiske NBIM-data"):
        if source != "real" or dataset is None:
            st.info(
                "Velg NBIM-data i sidepanelet for å trene. Demo og andre forvaltere blandes ikke med NBIM-fasit."
            )
        target = st.slider("Ønsket MOT-recall i valideringsåret", 0.5, 1.0, 0.8, 0.05)
        clusters = st.number_input("Temaklynger (0 slår av)", 0, 16, 0)
        st.caption(
            "Trening endrer aktiv prioriteringsmodell. Tidligere kjøringer bevares og kan aktiveres igjen."
        )
        if st.button(
            "Tren og bruk prioriteringsmodell", disabled=source != "real" or dataset is None
        ):
            try:
                with st.spinner("Trener på tidligere møter og evaluerer på senere møter …"):
                    train_model(
                        dataset["records"],
                        dataset["labels"],
                        directory,
                        target_recall=target,
                        clusters=int(clusters),
                    )
                st.success("Modellen er lagret som en ny versjon og aktivert.")
            except APP_ERRORS as exc:
                st.error(f"Treningen kunne ikke fullføres: {exc}")
    try:
        report = read_report(directory)
    except APP_ERRORS:
        st.info(
            "Ingen brukbar prioriteringsmodell er lagret ennå. LLM-agentene kan kjøres uten denne."
        )
        return
    st.caption(
        f"Aktiv modell: {report['model_id'][:12]} · Kilde: {report['source']} · Kun forslagstekst som modellfeature"
    )
    metrics = report["test"]["model"]
    for col, title, key in zip(
        st.columns(3),
        ["Presisjon MOT", "Recall MOT", "F1 MOT"],
        ["mot_precision", "mot_recall", "mot_f1"],
    ):
        col.metric(title, f"{metrics[key]:.1%}")
    st.info(
        "Tallene gjelder den historiske prioriteringsmodellen. De måler ikke LLM-agentenes kildebruk eller begrunnelser."
    )
    rows = []
    for key, title in [
        ("board_baseline", "Følg styret"),
        ("model_on_board_available_subset", "Modell på samme saker"),
    ]:
        item = report["test"][key]
        rows.append(
            {
                "Metode": title,
                "Antall": item["count"],
                "Presisjon MOT": item.get("mot_precision"),
                "Recall MOT": item.get("mot_recall"),
                "F1 MOT": item.get("mot_f1"),
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.markdown("**Valgt prioriteringsterskel**")
    st.json(report["routing_threshold"], expanded=False)
    with st.expander("Full rapport og perioder"):
        st.json(report)
    st.download_button(
        "Last ned modellrapport", json_text(report), "modellrapport.json", "application/json"
    )
    runs = list_runs(directory)
    if runs:
        with st.expander("Modellregister og tilbakeføring"):
            chosen = st.selectbox(
                "Lagret kjøring",
                [r["run_id"] for r in runs],
                format_func=lambda x: (
                    x + (" · aktiv" if any(r["run_id"] == x and r["active"] for r in runs) else "")
                ),
            )
            if st.button("Aktiver valgt kjøring"):
                try:
                    activate_run(directory, chosen)
                    st.rerun()
                except APP_ERRORS as exc:
                    st.error(f"Kunne ikke aktivere modellen: {exc}")
