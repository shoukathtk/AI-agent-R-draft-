# SCI/Scopus paper drafting pipeline

A sequential, human-gated agent pipeline for drafting an academic manuscript:

```
literature → introduction → methodology → results_analysis → visualization
    → discussion → conclusion → supervisor
```

Each stage is one Claude API call. Nothing runs automatically end-to-end —
you review and `approve` each stage's output before the next stage can use
it as input. This is deliberate: a fabricated citation or an unverified
"Scopus-indexed" claim slipping through unattended is the single biggest
risk in this workflow.

## Setup

```bash
pip install -r requirements.txt --break-system-packages
export ANTHROPIC_API_KEY=sk-...
```

## Web UI (recommended)

```bash
export ANTHROPIC_API_KEY=sk-...
streamlit run app.py
```

Opens a card-grid dashboard in your browser — one card per stage, greyed out
until its dependencies are approved. Click a card to open a run/review/edit/
approve panel for that stage. This is a thin UI layer over `pipeline.py`'s
logic — the CLI below still works identically and both share the same
`manuscript/` state, so you can mix and match.

## CLI flow

```bash
# Stage 1: Literature — give it your topic and any known seed papers/keywords
echo "Topic: effect of X on Y in Z population. Seed keywords: ..." > topic.txt
python pipeline.py run literature --input topic.txt

# Read manuscript/01_literature.md. Edit it by hand if needed
# (e.g. remove a source, fix an indexing status).
# IMPORTANT: manually verify indexing status via Scopus/Web of Science —
# the model cannot reliably self-certify this from memory.
python pipeline.py approve literature

# Stage 2: Introduction — auto-pulls the approved literature output
python pipeline.py run introduction
python pipeline.py approve introduction

# Stage 3: Methodology — give it your actual research design notes
python pipeline.py run methodology --input methodology_notes.txt
python pipeline.py approve methodology

# Stage 4: Results & Analysis — give it your real data/stats output
python pipeline.py run results_analysis --input results_data.txt
python pipeline.py approve results_analysis

# Stage 5: Visualization — renders the planned tables/graphs/diagrams
python pipeline.py run visualization
python pipeline.py approve visualization

# Stage 6: Discussion — pulls literature + intro + results + visuals
python pipeline.py run discussion
python pipeline.py approve discussion

# Stage 7: Conclusion
python pipeline.py run conclusion
python pipeline.py approve conclusion

# Stage 8: Supervisor — compiles everything + runs compliance checks
# (visual count minimums, citation indexing, cross-section consistency)
python pipeline.py run supervisor
```

Check progress at any point:

```bash
python pipeline.py status
```

## Files

- `prompts.py` — the system prompt for each stage. Edit these to tune tone,
  strictness, field-specific conventions, or journal-specific requirements.
- `pipeline.py` — the CLI orchestrator (dependency tracking, API calls, file I/O).
- `manuscript/` — generated per-stage drafts (`01_literature.md`, etc.) and
  `manifest.json` tracking what's been generated/approved.

## Editing a stage after approval

If you edit an already-approved `.md` file by hand and want downstream
stages to see your edits, just leave it approved — downstream stages always
read the current file contents, not a snapshot from generation time. Only
re-run the stage via `python pipeline.py run <stage>` if you want Claude to
regenerate it; that will reset its approval flag.

## What this does NOT do for you

- **Real citation indexing verification.** The Literature agent states what
  it believes the indexing status is; it does not query Scopus or Web of
  Science. Treat every "Scopus-indexed" / "SCIE-indexed" tag as a claim to
  verify, not a fact.
- **Actual chart rendering.** The Visualization stage produces chart
  specifications and captions, not rendered image files. If you want actual
  PNG/SVG figures, that's a good next extension — e.g. a stage that takes the
  Visualization agent's chart-spec output and generates plots via
  matplotlib/Code Execution.
- **Plagiarism/similarity checking.** Run the Supervisor's compiled output
  through your institution's similarity checker before submission.
