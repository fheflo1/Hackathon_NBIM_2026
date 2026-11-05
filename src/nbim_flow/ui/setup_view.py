import streamlit as st

from nbim_flow.diagnostics import doctor, probe
from nbim_flow.local_model import local_models

from .common import APP_ERRORS


def render_setup(settings):
    st.header("Kom i gang med egen modell")
    st.write(
        "Start med lokal oppsettskontroll, prøv en syntetisk sak, og gå deretter videre til en liten batch."
    )
    checks = doctor(settings)
    st.subheader("1. Kontroller oppsettet")
    for item in checks["checks"]:
        mark = "✅" if item["ok"] else "⚠️"
        st.write(f"{mark} **{item['name']}** — {item['detail']}")
    st.caption("Oppsettskontrollen bruker ingen modellkall og tester ikke nettverkstilkoblingen.")
    if settings.provider == "ollama":
        st.subheader("2. Start Ollama og velg en lokal modell")
        st.code("ollama serve\nollama list\nollama pull qwen2.5:7b", language="bash")
        st.caption(
            "Hvis Ollama-appen allerede kjører, trenger du ikke starte en ny server. Modellnedlasting gjøres én gang."
        )
        st.code(
            "LLM_PROVIDER=ollama\nLLM_BASE_URL=http://127.0.0.1:11434\nLLM_MODEL=qwen2.5:7b",
            language="dotenv",
        )
        st.write(
            f"Aktiv modell: **{settings.model}**. Endre LLM_MODEL i .env hvis du vil bruke en annen installert modell."
        )
        if st.button("Se installerte lokale modeller"):
            try:
                st.session_state["local_models"] = local_models(settings)
            except APP_ERRORS as exc:
                st.error(
                    f"Kunne ikke kontakte lokal Ollama. Start appen eller kjør ollama serve. ({type(exc).__name__})"
                )
        if st.session_state.get("local_models"):
            st.dataframe(st.session_state["local_models"], hide_index=True, width="stretch")
    else:
        st.subheader("2. Velg OpenAI-modell")
        st.write(
            "Fyll inn API-nøkkel og et modellnavn kontoen har tilgang til i .env. Bruk en modell med Responses og Structured Outputs."
        )
    st.subheader("3. Prøv forbindelsen")
    st.write(
        "Testen sender ett syntetisk forslag til anbefalingsagenten og deretter til kontrollagenten. Den bruker to modellkall."
    )
    if st.button(
        "Test modellen med et syntetisk eksempel",
        type="primary",
        disabled=not checks["llm_configured"],
    ):
        try:
            with st.spinner(
                "Kontakter modellen. Første lokale kjøring kan bruke tid på å laste vektene …"
            ):
                report = probe(settings)
            st.session_state["probe_report"] = report
        except APP_ERRORS as exc:
            st.error(f"Kontroller konfigurasjonen: {exc}")
    report = st.session_state.get("probe_report")
    if report:
        if report["connected"] and report["structured_outputs_ok"]:
            st.success(
                "Begge modellrollene svarte med gyldige strukturerte svar. Du kan prøve en liten batch."
            )
        else:
            st.warning("Modellen er ikke klar til saksbehandling. Se feilen under.")
        st.json(report)
    st.subheader("4. Behandle noen få saker")
    st.write(
        "Velg Saksbehandling, bytt til LLM, og start med én til fem saker. Resultatene og eventuelle feil vises i Drift. Usikre saker går til Manuell oppfølging."
    )
    st.info(
        "Medfølgende policy er et begrenset 2025-utvalg. Saker uten tilstrekkelig policy eller selskapsfakta blir ikke automatisk godkjent."
    )
