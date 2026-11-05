import csv
import hashlib
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from nbim_flow.data import prepare_csv, write_prepared

from .common import APP_ERRORS, json_text


@st.cache_data(show_spinner=False)
def read_dataset(path, source, signature):
    return prepare_csv(path, source)


@st.cache_data(show_spinner=False)
def read_upload(raw, signature):
    # Close before reopening: NamedTemporaryFile cannot be reopened on Windows.
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "agenda.csv"
        path.write_bytes(raw)
        return prepare_csv(path, "upload")


def select_dataset(settings):
    choice = st.sidebar.selectbox(
        "Datagrunnlag",
        ["Demoeksempler", "NBIM-data", "N-PX-data", "Last opp CSV"],
        key="dataset_choice",
    )
    source = {
        "Demoeksempler": "upload",
        "NBIM-data": "real",
        "N-PX-data": "npx",
        "Last opp CSV": "upload",
    }[choice]
    try:
        if choice == "Last opp CSV":
            uploaded = st.sidebar.file_uploader("Velg saksliste", type="csv")
            if uploaded is None:
                return choice, source, None
            raw = uploaded.getvalue()
            return choice, source, read_upload(raw, hashlib.sha256(raw).hexdigest())
        name = {
            "Demoeksempler": "demo_agenda.csv",
            "NBIM-data": "real_votes.csv",
            "N-PX-data": "npx_votes.csv",
        }[choice]
        path = settings.root / "data" / name
        # File hash covers replacements even when length/mtime are retained.
        signature = hashlib.sha256(path.read_bytes()).hexdigest()
        return choice, source, read_dataset(str(path), source, signature)
    except (*APP_ERRORS, csv.Error) as exc:
        st.sidebar.error(f"Dataene kunne ikke leses: {exc}")
        return choice, source, None


def render_data(settings, dataset, source):
    st.header("Datagrunnlag")
    if dataset is None:
        st.info("Velg en tilgjengelig CSV i sidepanelet.")
        return
    report = dataset["report"]
    cols = st.columns(4)
    for col, label, key in zip(
        cols,
        ["Rader lest", "Saker klare", "Karantene", "Ukjente etiketter"],
        ["total_rows", "accepted_records", "quarantined_rows", "unknown_labels"],
    ):
        col.metric(label, report[key])
    if source == "npx":
        st.warning(
            "Forvalteren bak N-PX-filen er ikke dokumentert. Stemmene brukes ikke som NBIM-fasit."
        )
    st.caption(
        f"Periode: {report['date_range']['min']} til {report['date_range']['max']}. "
        f"Filversjon: {report['input_sha256'][:12]}."
    )
    st.write("Historiske stemmer og begrunnelser ligger separat fra faktaene agentene får lese.")
    st.dataframe(pd.DataFrame(dataset["records"][:100]), hide_index=True, width="stretch")
    with st.expander("Datakvalitet og manglende verdier"):
        counts = report.get("label_counts", {})
        if counts:
            st.bar_chart(pd.Series(counts, name="Antall"))
        st.json(report)
    if dataset["quarantine"]:
        with st.expander("Avviste rader med årsak"):
            st.json(dataset["quarantine"][:30])
    if st.button("Lagre klargjorte data"):
        path = settings.root / "artifacts/processed" / source / report["input_sha256"][:12]
        write_prepared(dataset, path)
        st.success(f"Lagret i {path.relative_to(settings.root)}.")
    st.download_button(
        "Last ned kvalitetsrapport", json_text(report), "datakvalitet.json", "application/json"
    )
