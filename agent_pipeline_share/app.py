"""
Streamlit web UI for the AI Agent.

Wraps pipeline.py's logic in a card-grid dashboard (similar to the
agent-marketplace screenshot): one card per stage, greyed out until its
dependencies are approved, click to open a run/review/approve panel.

RUN:
  export ANTHROPIC_API_KEY=sk-...
  streamlit run app.py
"""

import os
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))
from prompts import STAGES, STAGE_ORDER
import pipeline as pl
import render_figures
import export_pdf

# On Streamlit Community Cloud, the API key comes from st.secrets, not env vars.
# Locally, $env:ANTHROPIC_API_KEY / export still works as before. This makes
# both paths work without changing how you run it locally.
try:
    if "ANTHROPIC_API_KEY" in st.secrets and not os.environ.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass  # no secrets.toml locally — fine, env var path still works

st.set_page_config(page_title="SCI Paper Agent Pipeline", layout="wide")

STAGE_LABELS = {
    "literature": "Literature",
    "introduction": "Introduction",
    "methodology": "Methodology",
    "results_analysis": "Results & Analysis",
    "visualization": "Visualization",
    "discussion": "Discussion",
    "conclusion": "Conclusion",
    "supervisor": "Supervisor (compile)",
}
STAGE_DESC = {
    "literature": "Search, summarize prior work, gap analysis. Scopus/SCI-indexed sources only.",
    "introduction": "Background, problem, gap, objective — tied to the literature stage.",
    "methodology": "Reproducible methods section from your research design notes.",
    "results_analysis": "Objective findings + statistical analysis + planned tables/graphs/diagrams.",
    "visualization": "Renders the planned tables/graphs/diagrams (6+ tables, 2-4 graphs, 2+ diagrams).",
    "discussion": "Interprets results against the literature. States limitations.",
    "conclusion": "Synthesizes contribution and future work.",
    "supervisor": "Compiles everything + runs visual-count and citation compliance checks.",
}

if "manifest" not in st.session_state:
    st.session_state.manifest = pl.load_manifest()
if "open_stage" not in st.session_state:
    st.session_state.open_stage = None


def refresh():
    st.session_state.manifest = pl.load_manifest()


def stage_state(stage: str) -> str:
    m = st.session_state.manifest
    if m["approved"].get(stage):
        return "approved"
    if m["generated"].get(stage):
        return "drafted"
    unmet = pl.check_deps(stage, m)
    if unmet:
        return "locked"
    return "ready"


STATE_STYLE = {
    "locked": ("#9ca3af", "Locked", False),
    "ready": ("#2563eb", "Ready", True),
    "drafted": ("#d97706", "Drafted — review needed", True),
    "approved": ("#16a34a", "Approved", True),
}


def render_card(stage: str):
    state = stage_state(stage)
    color, label, clickable = STATE_STYLE[state]
    with st.container(border=True):
        st.markdown(f"**{STAGE_LABELS[stage]}**")
        st.caption(STAGE_DESC[stage])
        st.markdown(f"<span style='color:{color};font-size:0.85em'>● {label}</span>", unsafe_allow_html=True)
        if clickable:
            if st.button("Open", key=f"open_{stage}", use_container_width=True):
                st.session_state.open_stage = stage
        else:
            deps = pl.check_deps(stage, st.session_state.manifest)
            st.caption(f"Needs approved: {', '.join(deps)}")


def render_stage_panel(stage: str):
    st.subheader(STAGE_LABELS[stage])
    st.caption(STAGE_DESC[stage])
    state = stage_state(stage)
    out_file = pl.stage_filename(stage)

    if st.session_state.get("truncation_warning") == stage:
        st.warning(
            "⚠️ This draft hit the token limit and was cut off mid-way — it is "
            "INCOMPLETE (e.g. Conclusion and/or References may be missing entirely "
            "if this was the Supervisor stage). Do not approve this draft as-is. "
            "Consider shortening your inputs or reducing target word counts, then re-run."
        )
        del st.session_state["truncation_warning"]

    needs_input = stage in ("literature", "methodology", "results_analysis", "visualization")
    extra_input_text = ""
    if needs_input:
        prompts_hint = {
            "literature": "Your research topic, objective, and any known seed papers/keywords.",
            "methodology": "Your actual research design: sample, procedure, tools, analysis method used.",
            "results_analysis": "Your real data/statistical output — numbers, tables, test results.",
            "visualization": "Optional — request specific graphs, tables, or diagrams you want included "
                              "beyond the standard set (e.g. \"add a scatter plot of engagement vs "
                              "productivity\" or \"include a table breaking results down by department\"). "
                              "Leave blank to use only the standard planned visuals.",
        }
        extra_input_text = st.text_area(
            f"Input for this stage — {prompts_hint[stage]}",
            height=150,
            key=f"input_{stage}",
        )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Run stage", type="primary", disabled=(state == "locked")):
            if not os.environ.get("ANTHROPIC_API_KEY"):
                st.error("ANTHROPIC_API_KEY is not set in the environment.")
            else:
                with st.spinner("Hold tight — your agent is getting things ready..."):
                    unmet = pl.check_deps(stage, st.session_state.manifest)
                    if unmet:
                        st.error(f"Missing approved dependencies: {', '.join(unmet)}")
                    else:
                        try:
                            client = pl.anthropic.Anthropic()
                            system_prompt = STAGES[stage]["prompt"]
                            user_message = pl.build_user_message(
                                stage, st.session_state.manifest,
                                extra_input_text.strip() or None,
                            )
                            response = client.messages.create(
                                model=pl.MODEL,
                                max_tokens=pl.max_tokens_for(stage),
                                system=system_prompt,
                                messages=[{"role": "user", "content": user_message}],
                            )
                            text = "".join(b.text for b in response.content if b.type == "text")
                            if not text.strip():
                                st.error(
                                    f"Claude returned an empty response (stop_reason: "
                                    f"{getattr(response, 'stop_reason', 'unknown')}). "
                                    f"Try again, or shorten your input if it was very long."
                                )
                            else:
                                pl.MANUSCRIPT_DIR.mkdir(exist_ok=True)
                                out_file.write_text(text, encoding="utf-8")
                                m = st.session_state.manifest
                                m["generated"][stage] = True
                                m["approved"][stage] = False
                                pl.save_manifest(m)
                                if getattr(response, "stop_reason", None) == "max_tokens":
                                    st.session_state["truncation_warning"] = stage
                                refresh()
                                st.rerun()
                        except pl.anthropic.APIError as e:
                            st.error(f"Anthropic API error: {e}")
                        except Exception as e:
                            st.error(f"Unexpected error while running this stage: {e}")
    with col2:
        if state == "drafted":
            if st.button("Approve", type="secondary"):
                pl.approve_stage(stage)
                refresh()
                st.rerun()

    if out_file.exists():
        st.markdown("---")
        st.markdown("**Draft output** (edit below, then re-save if you make changes):")
        edited = st.text_area("output", value=out_file.read_text(encoding="utf-8"), height=400,
                               key=f"editor_{stage}", label_visibility="collapsed")
        if st.button("Save edits", key=f"save_{stage}"):
            out_file.write_text(edited, encoding="utf-8")
            st.success("Saved.")

        # --- Visualization stage: render real chart/diagram PNGs from the JSON spec ---
        if stage == "visualization":
            figures_dir = pl.MANUSCRIPT_DIR / "figures"
            if st.button("Render figures (create real PNG images)", key="render_figs"):
                with st.spinner("Rendering charts and diagrams..."):
                    result = render_figures.render_all(out_file, figures_dir)
                if result["errors"]:
                    for e in result["errors"]:
                        st.error(e)
                if result["rendered"]:
                    st.success(f"Rendered {len(result['rendered'])} figure(s).")
                if result["skipped"]:
                    st.warning(f"Skipped (no data): {', '.join(result['skipped'])}")
            if figures_dir.exists():
                pngs = sorted(figures_dir.glob("*.png"))
                if pngs:
                    st.caption(f"{len(pngs)} rendered figure(s):")
                    cols = st.columns(min(3, len(pngs)))
                    for i, png in enumerate(pngs):
                        with cols[i % len(cols)]:
                            st.image(str(png), caption=png.stem, use_container_width=True)

        # --- Supervisor stage: export the compiled manuscript as a real PDF ---
        if stage == "supervisor":
            figures_dir = pl.MANUSCRIPT_DIR / "figures"
            pdf_path = pl.MANUSCRIPT_DIR / "paper.pdf"
            paper_title = st.text_input("Paper title (for the PDF cover)", value="Manuscript Draft", key="pdf_title")
            if st.button("Generate downloadable PDF", key="gen_pdf"):
                with st.spinner("Assembling PDF..."):
                    try:
                        export_pdf.export_pdf(out_file, figures_dir, pdf_path, title=paper_title)
                        st.success("PDF generated.")
                    except Exception as e:
                        st.error(f"PDF export failed: {e}")
            if pdf_path.exists():
                st.download_button(
                    "Download PDF",
                    data=pdf_path.read_bytes(),
                    file_name="manuscript_draft.pdf",
                    mime="application/pdf",
                )

    if st.button("← Back to dashboard"):
        st.session_state.open_stage = None
        st.rerun()


# ---- Layout ----
st.title("SCI / Scopus paper drafting pipeline")

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.warning("ANTHROPIC_API_KEY is not set. Export it before running stages: `export ANTHROPIC_API_KEY=sk-...`")

if st.session_state.open_stage:
    render_stage_panel(st.session_state.open_stage)
else:
    st.caption("Click a card to run, review, and approve that stage. Locked cards need their dependencies approved first.")
    cols = st.columns(4)
    for i, stage in enumerate(STAGE_ORDER):
        with cols[i % 4]:
            render_card(stage)

    st.markdown("---")
    approved_count = sum(1 for s in STAGE_ORDER if st.session_state.manifest["approved"].get(s))
    st.progress(approved_count / len(STAGE_ORDER), text=f"{approved_count}/{len(STAGE_ORDER)} stages approved")

    with st.expander("Verify citations (Crossref + Scopus)"):
        st.caption("Run after the Literature stage is drafted, before approving it.")
        st.code(
            "cd verification\n"
            "python verify_references.py ../manuscript/01_literature.md "
            "--scopus-source-list ./scopus_source_list.csv",
            language="bash",
        )
        st.caption("See verification/README.md for setup (free Scopus Source List download, no WoS automation exists).")
