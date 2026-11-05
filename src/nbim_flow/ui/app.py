"""Dashboard composition and navigation; services are shared with the CLI."""

import streamlit as st

from nbim_flow.config import Settings
from nbim_flow.diagrams import WORKFLOW_MERMAID

from .common import APP_ERRORS
from .data_view import select_dataset

PAGES = [
    "Oppsett",
    "Data",
    "Prioriteringsmodell",
    "Saksbehandling",
    "Manuell oppfølging",
    "Drift",
    "Workflow",
]


def render_workflow():
    st.header("Hele arbeidsflyten")
    st.write(
        "Modellen prioriterer saker; agentene begrunner stemmene; kontroll og mennesker følger opp usikkerhet."
    )
    # Graphviz is rendered by Streamlit without a third-party CDN.
    st.graphviz_chart(
        """digraph {
        rankdir=TB; node [shape=box,style="rounded",fontname="sans-serif"];
        CSV -> Preprocessing; Preprocessing -> Karantene; Preprocessing -> Fakta;
        Preprocessing -> Fasit; Fasit -> Trening; Fakta -> Trening;
        Trening -> Modellregister; Modellregister -> Prioritering; Fakta -> Prioritering;
        Prioritering -> Watermark; Watermark -> Gjenbruk; Watermark -> Policykontroll;
        Policykontroll -> Anbefalingsagent; Policykontroll -> Manuell;
        Anbefalingsagent -> Kildekontroll; Kildekontroll -> Kontrollagent;
        Kontrollagent -> Resultat; Kontrollagent -> Anbefalingsagent [label="revisjon, maks 5 forsøk"];
        Kontrollagent -> Manuell; Anbefalingsagent -> APIfeil; APIfeil -> Utsett;
        Resultat -> Revisjonslogg; Manuell -> Revisjonslogg; Utsett -> Revisjonslogg;
        Gjenbruk -> Revisjonslogg; Revisjonslogg -> Dashboard;
    }""",
        width="stretch",
    )
    with st.expander("Mermaid-kilde for dokumentasjon", expanded=False):
        st.code(WORKFLOW_MERMAID, language="mermaid")
    st.download_button("Last ned Mermaid-diagram", WORKFLOW_MERMAID, "workflow.mmd", "text/plain")


def main():
    st.set_page_config(page_title="NBIM · Stemmeanbefalinger", page_icon="🗳️", layout="wide")
    st.title("Stemmegivning")
    st.caption(
        "Sporbar vurdering av generalforsamlingssaker · Lokal modell, kildekontroll og menneskelig oppfølging"
    )
    try:
        settings = Settings.from_env()
    except APP_ERRORS as exc:
        st.error(f"Oppsettet må korrigeres: {exc}")
        st.code("python3 run.py --doctor", language="bash")
        st.stop()
    st.sidebar.title("NBIM · Arbeidsflate")
    page = st.sidebar.radio("Navigasjon", PAGES, key="page")
    st.sidebar.divider()
    choice, source, dataset = select_dataset(settings)
    st.sidebar.divider()
    st.sidebar.caption(
        f"Leverandør: {settings.provider}\n\nModell: {settings.model or 'ikke valgt'}"
    )
    st.sidebar.caption("Ingen stemmer sendes til en generalforsamling.")
    try:
        if page == "Oppsett":
            from .setup_view import render_setup

            render_setup(settings)
        elif page == "Data":
            from .data_view import render_data

            render_data(settings, dataset, source)
        elif page == "Prioriteringsmodell":
            from .model_view import render_model

            render_model(settings, dataset, source)
        elif page == "Saksbehandling":
            from .cases_view import render_processing

            render_processing(settings, dataset, source, choice)
        elif page == "Manuell oppfølging":
            from .cases_view import render_review

            render_review(settings)
        elif page == "Drift":
            from .operations_view import render_operations

            render_operations(settings, dataset)
        else:
            render_workflow()
    except APP_ERRORS as exc:
        st.error(f"Siden kunne ikke fullføres: {exc}")
        st.info("Se Oppsett for konfigurasjon eller Drift for tidligere registrerte feil.")
