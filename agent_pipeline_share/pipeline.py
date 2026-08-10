#!/usr/bin/env python3
"""
SCI/Scopus paper drafting pipeline orchestrator.

Sequential, human-gated: each stage is a separate Claude API call. A stage's
output is written to manuscript/<NN>_<stage>.md for you to read and edit by
hand. Nothing downstream runs until you explicitly `approve` that stage.

USAGE
  export ANTHROPIC_API_KEY=sk-...

  # 1. Run the first stage (no dependencies needed yet)
  python pipeline.py run literature --input topic.txt

  # 2. Read/edit manuscript/01_literature.md by hand, then:
  python pipeline.py approve literature

  # 3. Run the next stage — it auto-loads the approved literature output.
  #    Some stages need extra author-supplied input (raw data notes, etc.)
  python pipeline.py run introduction

  python pipeline.py run methodology --input methodology_notes.txt
  python pipeline.py approve methodology

  python pipeline.py run results_analysis --input results_data.txt
  python pipeline.py approve results_analysis

  python pipeline.py run visualization
  python pipeline.py approve visualization

  python pipeline.py run discussion
  python pipeline.py approve discussion

  python pipeline.py run conclusion
  python pipeline.py approve conclusion

  python pipeline.py run supervisor      # final compile + compliance check

  # Check where you are at any point:
  python pipeline.py status
"""

import argparse
import json
import os
import sys
from pathlib import Path

from prompts import STAGES, STAGE_ORDER

try:
    import anthropic
except ImportError:
    print("Missing dependency. Run: pip install anthropic --break-system-packages")
    sys.exit(1)

ROOT = Path(__file__).parent
MANUSCRIPT_DIR = ROOT / "manuscript"
MANIFEST_PATH = MANUSCRIPT_DIR / "manifest.json"
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 8000


def load_manifest() -> dict:
    if MANIFEST_PATH.exists():
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"approved": {}, "generated": {}}


def save_manifest(manifest: dict) -> None:
    MANUSCRIPT_DIR.mkdir(exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def stage_filename(stage: str) -> Path:
    idx = STAGE_ORDER.index(stage) + 1
    return MANUSCRIPT_DIR / f"{idx:02d}_{stage}.md"


def check_deps(stage: str, manifest: dict) -> list[str]:
    """Return list of unmet dependency stage names."""
    deps = STAGES[stage]["deps"]
    return [d for d in deps if not manifest["approved"].get(d)]


def build_user_message(stage: str, manifest: dict, extra_input: str | None) -> str:
    parts = []
    for dep in STAGES[stage]["deps"]:
        dep_file = stage_filename(dep)
        if dep_file.exists():
            parts.append(f"--- APPROVED OUTPUT: {dep.upper()} ---\n{dep_file.read_text(encoding='utf-8')}")
    if extra_input:
        label = "AUTHOR-REQUESTED VISUAL" if stage == "visualization" else "AUTHOR-SUPPLIED INPUT FOR THIS STAGE"
        parts.append(f"--- {label} ---\n{extra_input}")
    if not parts:
        parts.append("No prior stage outputs yet. Use the author-supplied input above, "
                      "or if none was given, ask a single clarifying question instead of guessing.")
    return "\n\n".join(parts)


def run_stage(stage: str, input_path: str | None) -> None:
    manifest = load_manifest()

    unmet = check_deps(stage, manifest)
    if unmet:
        print(f"Cannot run '{stage}' — dependency stage(s) not yet approved: {', '.join(unmet)}")
        print("Run and approve those stages first (see: python pipeline.py status).")
        sys.exit(1)

    extra_input = None
    if input_path:
        p = Path(input_path)
        if not p.exists():
            print(f"Input file not found: {input_path}")
            sys.exit(1)
        extra_input = p.read_text(encoding="utf-8")

    system_prompt = STAGES[stage]["prompt"]
    user_message = build_user_message(stage, manifest, extra_input)

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    print(f"Calling Claude for stage '{stage}'...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    output_text = "".join(block.text for block in response.content if block.type == "text")

    out_file = stage_filename(stage)
    MANUSCRIPT_DIR.mkdir(exist_ok=True)
    out_file.write_text(output_text, encoding="utf-8")

    manifest["generated"][stage] = True
    manifest["approved"][stage] = False  # any re-run resets approval
    save_manifest(manifest)

    print(f"\nDraft written to: {out_file}")
    print("Read it, edit it directly if needed, then run:")
    print(f"  python pipeline.py approve {stage}")


def approve_stage(stage: str) -> None:
    manifest = load_manifest()
    if not manifest["generated"].get(stage):
        print(f"Stage '{stage}' hasn't been run yet.")
        sys.exit(1)
    manifest["approved"][stage] = True
    save_manifest(manifest)
    print(f"'{stage}' approved. Downstream stages can now use it as input.")


def show_status() -> None:
    manifest = load_manifest()
    print(f"{'STAGE':<20} {'GENERATED':<12} {'APPROVED':<10} DEPENDS ON")
    for stage in STAGE_ORDER:
        gen = "yes" if manifest["generated"].get(stage) else "-"
        appr = "yes" if manifest["approved"].get(stage) else "-"
        deps = ", ".join(STAGES[stage]["deps"]) or "(none)"
        print(f"{stage:<20} {gen:<12} {appr:<10} {deps}")


def main():
    parser = argparse.ArgumentParser(description="SCI/Scopus paper drafting pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run a stage")
    run_p.add_argument("stage", choices=STAGE_ORDER)
    run_p.add_argument("--input", help="Path to a text file with author-supplied notes/data for this stage")

    appr_p = sub.add_parser("approve", help="Approve a generated stage so downstream stages can use it")
    appr_p.add_argument("stage", choices=STAGE_ORDER)

    sub.add_parser("status", help="Show pipeline progress")

    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY") and args.command == "run":
        print("Set ANTHROPIC_API_KEY in your environment first.")
        sys.exit(1)

    if args.command == "run":
        run_stage(args.stage, args.input)
    elif args.command == "approve":
        approve_stage(args.stage)
    elif args.command == "status":
        show_status()


if __name__ == "__main__":
    main()
