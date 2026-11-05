import pandas as pd
import streamlit as st

from nbim_flow.policy import load_policy, retrieve
from nbim_flow.store import AuditStore, load_events, load_results
from nbim_flow.workflow import process_records

from .common import APP_ERRORS, download


def render_processing(settings, dataset, source, choice):
    st.header("Behandle saker")
    policy = load_policy(settings.policy_path)
    st.caption(
        f"Policyutvalg: {policy['version']} · {policy['valid_from']} til {policy['valid_through']}"
    )
    records = dataset["records"] if dataset else []
    if choice != "Demoeksempler" and records:
        years = sorted({r["meeting_date"][:4] for r in records}, reverse=True)
        choices = ["Policyens år", "Alle år", *years]
        period = st.selectbox("Periode", choices)
        if period == "Policyens år":
            records = [
                r
                for r in records
                if policy["valid_from"] <= r["meeting_date"] <= policy["valid_through"]
            ]
        elif period != "Alle år":
            records = [r for r in records if r["meeting_date"].startswith(period + "-")]
    mode_label = st.radio(
        "Kjøremodus",
        ["Demo uten modellkall", "LLM med konfigurert modell"],
        horizontal=True,
        key="processing_mode",
    )
    mode = "demo" if mode_label == "Demo uten modellkall" else "llm"
    eligible = sum(bool(retrieve(r, policy)) for r in records)
    st.write(f"{len(records):,} saker i utvalget · {eligible:,} med et relevant policyavsnitt.")
    configured = bool(settings.model and (settings.provider == "ollama" or settings.api_key))
    if mode == "llm":
        destination = (
            "lokal Ollama på denne maskinen" if settings.provider == "ollama" else "OpenAI"
        )
        st.info(f"Sakstekst og policyutvalg sendes til {destination}. Historisk fasit sendes ikke.")
        st.caption(f"Anbefaling: {settings.model} · Kontroll: {settings.reviewer_model}")
        if not configured:
            st.warning("Modellen er ikke konfigurert. Følg Oppsett-siden først.")
        if not eligible:
            st.warning(
                "Ingen saker i dette utvalget har dekkende policy. Behandlingen vil gi manuell oppfølging uten modellkall."
            )
    else:
        st.info("Demoen viser mekanikken med lokale regler. Den er ikke en måling av LLM-kvalitet.")
    cols = st.columns(3)
    limit = cols[0].number_input("Maks nye saker", 1, 100, 5)
    attempts = cols[1].number_input("Maks totale forsøk", 1, 5, settings.max_attempts)
    calls = cols[2].number_input("Maks modellkall i batchen", 1, 1000, settings.max_api_calls)
    available = source == "real" and (settings.root / "artifacts/model/model.joblib").exists()
    prioritize = st.checkbox(
        "Bruk lagret prioriteringsmodell", value=available, disabled=not available
    )
    st.caption(
        "Fem forsøk betyr ett første forsøk og fire retries. Budsjett og API-feil holdes adskilt fra manglende saksgrunnlag."
    )
    if st.button(
        "Kjør saksbehandling",
        type="primary",
        disabled=not records or (mode == "llm" and not configured),
    ):
        try:
            with st.spinner("Vurderer saker og kontrollerer kildene …"):
                result = process_records(
                    records,
                    settings=settings,
                    mode=mode,
                    limit=int(limit),
                    max_attempts=int(attempts),
                    max_api_calls=int(calls),
                    model_path=settings.root / "artifacts/model"
                    if prioritize and available
                    else None,
                )
            st.session_state["last_batch"] = result
        except APP_ERRORS as exc:
            st.error(f"Behandlingen kunne ikke fullføres: {exc}")
    result = st.session_state.get("last_batch")
    if result:
        if result.get("stopped_reason") or result["errors"]:
            st.warning(
                "Batchen har saker som ikke ble ferdige. Se årsaken i Drift før du starter igjen."
            )
        else:
            st.success("Batchen er avsluttet og lagret.")
        cols = st.columns(4)
        for col, title, key in zip(
            cols,
            ["Behandlet", "Gjenbrukt", "Feil", "Modellkall"],
            ["processed", "skipped", "errors", "api_calls"],
        ):
            col.metric(title, result[key])
        with st.expander("Batchdetaljer"):
            st.json(result)
    st.divider()
    render_results(settings, mode, review_only=False)


def render_results(settings, mode="llm", review_only=False):
    all_versions = st.checkbox(
        "Vis også eldre saksversjoner", value=False, key=f"versions_{review_only}"
    )
    results = [
        r
        for r in load_results(settings.database_path, latest=not all_versions)
        if r.get("mode") == mode
    ]
    if review_only:
        results = [r for r in results if r.get("review_pending")]
    if not results:
        st.info("Ingen saker i dette utvalget ennå.")
        return
    cols = st.columns(3)
    cols[0].metric("Saker", len(results))
    cols[1].metric("Avventer menneske", sum(bool(r.get("review_pending")) for r in results))
    cols[2].metric("Retries", sum(r["retries"] for r in results))
    columns = [
        "company",
        "meeting_date",
        "effective_vote",
        "status",
        "review_pending",
        "attempts",
        "retries",
    ]
    st.dataframe(pd.DataFrame(results)[columns], hide_index=True, width="stretch")
    selected = st.selectbox(
        "Åpne en sak",
        list(range(len(results))),
        format_func=lambda i: (
            f"{results[i]['company']} · {results[i]['meeting_date']} · punkt {results[i]['item_no']}"
        ),
        key=f"case_{review_only}",
    )
    item = results[selected]
    st.markdown("**Forslag**")
    st.text(item["proposal_text"])
    st.markdown("**Agentens begrunnelse**")
    st.write(item["reason"])
    if item.get("fallback_type"):
        st.caption(
            f"Reserveutfall: {item['fallback_type']}. Dette er ikke en policybegrunnet avståelse."
        )
    for citation in item.get("citations", []):
        st.markdown(f"**{citation['policy_id']} · {citation['locator']}**")
        st.write(citation["policy_excerpt"])
        st.caption("Kuraterte parafraser av policy; datasitatet under er fra forslagsteksten.")
        st.text(citation["evidence_quote"])
        st.link_button("Åpne offisiell policy", citation["source_url"])
    if item.get("human_review"):
        review = item["human_review"]
        st.success(f"Vurdert av {review['reviewer']}: {review['vote']}")
        st.write(review["reason"])
    if item["status"] != "processing":
        with st.expander("Registrer menneskelig vurdering"):
            st.caption(
                "Vurderingen lagres med navn og begrunnelse. Ingen stemme sendes til en generalforsamling."
            )
            with st.form(f"review_{item['run_key']}"):
                name = st.text_input("Navn på saksbehandler")
                vote = st.selectbox("Endelig anbefaling", ["FOR", "MOT", "AVSTÅ"])
                reason = st.text_area(
                    "Begrunnelse og vurderte kilder",
                    placeholder="Minst 10 tegn. Oppgi også eventuelle nye dokumentkilder.",
                )
                submitted = st.form_submit_button("Lagre vurdering")
            if submitted:
                store = AuditStore(settings.database_path)
                try:
                    store.review(item["run_key"], name, vote, reason)
                    st.rerun()
                except APP_ERRORS as exc:
                    st.error(str(exc))
                finally:
                    store.close()
    with st.expander("Hendelser og metadata"):
        st.json(item, expanded=False)
        st.json(load_events(settings.database_path, item["run_key"]), expanded=False)
    download(results, prefix="manuell_ko" if review_only else "saksresultater")


def render_review(settings):
    st.header("Manuell oppfølging")
    mode = st.radio("Vis saker fra", ["LLM", "Demo"], horizontal=True, key="review_mode")
    render_results(settings, "llm" if mode == "LLM" else "demo", review_only=True)
