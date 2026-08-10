"""
Renders real PNG chart/diagram images from the Visualization agent's output.

The Visualization agent (prompts.VISUALIZATION) is instructed to end its
output with a fenced ```json block containing a "charts" and "diagrams"
list built from real data. This module extracts that block and turns it
into actual matplotlib PNG files — the piece that was missing before:
previously the agent only wrote text descriptions of charts, never images.

USAGE (called from app.py, or standalone):
  python render_figures.py manuscript/05_visualization.md manuscript/figures/
"""

import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # no display needed, just file output
import matplotlib.pyplot as plt

# Journal-style defaults: no clutter gridlines, legible fonts, colorblind-safe palette
COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
plt.rcParams.update({
    "font.size": 11,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 150,
})


def extract_json_block(md_text: str) -> dict | None:
    match = re.search(r"```json\s*(\{.*?\})\s*```", md_text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        print(f"Warning: found a json block but couldn't parse it: {e}")
        return None


def safe_filename(label: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", label.strip()).strip("_").lower() or "figure"


def render_chart(spec: dict, out_dir: Path) -> Path | None:
    chart_type = spec.get("type", "bar")
    fig, ax = plt.subplots(figsize=(6, 4))

    series_list = spec.get("series", [])
    if not series_list:
        plt.close(fig)
        return None

    for i, series in enumerate(series_list):
        x = series.get("x", [])
        y = series.get("y", [])
        name = series.get("name", f"series {i+1}")
        color = COLORS[i % len(COLORS)]
        if chart_type == "bar":
            width = 0.8 / max(len(series_list), 1)
            offsets = [j + i * width for j in range(len(x))]
            ax.bar(offsets, y, width=width, label=name, color=color)
            ax.set_xticks([j + width * (len(series_list) - 1) / 2 for j in range(len(x))])
            ax.set_xticklabels(x, rotation=30, ha="right")
        elif chart_type == "line":
            ax.plot(x, y, marker="o", label=name, color=color)
        elif chart_type == "scatter":
            ax.scatter(x, y, label=name, color=color)
        elif chart_type == "box":
            ax.boxplot(y, positions=[i], widths=0.5)
            ax.set_xticks(range(len(series_list)))
            ax.set_xticklabels([s.get("name", "") for s in series_list])
        else:
            ax.bar(x, y, label=name, color=color)

    ax.set_xlabel(spec.get("x_label", ""))
    ax.set_ylabel(spec.get("y_label", ""))
    ax.set_title(spec.get("title", ""))
    if len(series_list) > 1 and chart_type != "box":
        ax.legend(frameon=False)
    fig.tight_layout()

    out_path = out_dir / f"{safe_filename(spec.get('id', 'figure'))}.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def render_diagram(spec: dict, out_dir: Path) -> Path | None:
    """Simple labeled-box flow/cycle diagram — not fancy, but real and accurate to the steps given."""
    import textwrap

    steps = spec.get("steps", [])
    if not steps:
        return None
    layout = spec.get("layout", "flow")

    # Keep labels short and hard-wrap them ourselves — matplotlib's wrap=True
    # does NOT respect box boundaries and was causing long labels to overlap
    # neighboring boxes illegibly. Truncate absurdly long labels outright;
    # the Visualization prompt is also instructed to keep these short, but
    # this is a hard safety net regardless of what the model sends.
    MAX_CHARS = 70
    WRAP_WIDTH = 16
    wrapped_steps = []
    for step in steps:
        s = step if len(step) <= MAX_CHARS else step[:MAX_CHARS - 1].rstrip() + "…"
        lines = textwrap.wrap(s, width=WRAP_WIDTH) or [s]
        wrapped_steps.append(lines)

    n = len(steps)
    max_lines = max(len(lines) for lines in wrapped_steps)
    max_line_len = max((len(line) for lines in wrapped_steps for line in lines), default=10)

    box_w = max(1.6, max_line_len * 0.11)
    box_h = max(0.8, 0.32 * max_lines + 0.3)
    gap = 0.5
    total_w = n * box_w + (n - 1) * gap
    start_x = -total_w / 2

    fig, ax = plt.subplots(figsize=(max(6, (box_w + gap) * n), box_h + 1.6))
    ax.axis("off")

    for i, lines in enumerate(wrapped_steps):
        x = start_x + i * (box_w + gap)
        ax.add_patch(plt.Rectangle((x, -box_h / 2), box_w, box_h,
                                     facecolor="#E6F0F7", edgecolor="#0072B2", linewidth=1.5))
        ax.text(x + box_w / 2, 0, "\n".join(lines), ha="center", va="center",
                 fontsize=9, linespacing=1.3)
        if i < n - 1:
            arrow_start = x + box_w
            arrow_end = arrow_start + gap
            ax.annotate("", xy=(arrow_end, 0), xytext=(arrow_start, 0),
                        arrowprops=dict(arrowstyle="->", color="#333333", lw=1.5))

    if layout == "cycle" and n > 1:
        # loop-back arrow from last box to first, drawn below
        last_x = start_x + (n - 1) * (box_w + gap) + box_w / 2
        first_x = start_x + box_w / 2
        ax.annotate("", xy=(first_x, -box_h), xytext=(last_x, -box_h),
                    arrowprops=dict(arrowstyle="->", color="#888888", lw=1.2,
                                     connectionstyle="arc3,rad=0.3"))

    ax.set_xlim(start_x - 0.5, start_x + total_w + 0.5)
    ax.set_ylim(-box_h - 0.8, box_h / 2 + 0.6)
    ax.set_title(spec.get("title", ""), fontsize=11)
    fig.tight_layout()

    out_path = out_dir / f"{safe_filename(spec.get('id', 'diagram'))}.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path


def render_all(md_path: Path, out_dir: Path) -> dict:
    """Returns {"rendered": [...], "skipped": [...], "errors": [...]}"""
    out_dir.mkdir(parents=True, exist_ok=True)
    md_text = md_path.read_text(encoding="utf-8")
    data = extract_json_block(md_text)

    result = {"rendered": [], "skipped": [], "errors": []}
    if not data:
        result["errors"].append("No valid ```json block found in the visualization draft.")
        return result

    for chart in data.get("charts", []):
        try:
            path = render_chart(chart, out_dir)
            if path:
                result["rendered"].append({"id": chart.get("id"), "path": str(path), "caption": chart.get("caption", "")})
            else:
                result["skipped"].append(chart.get("id", "unnamed chart"))
        except Exception as e:
            result["errors"].append(f"{chart.get('id', 'unnamed chart')}: {e}")

    for diagram in data.get("diagrams", []):
        try:
            path = render_diagram(diagram, out_dir)
            if path:
                result["rendered"].append({"id": diagram.get("id"), "path": str(path), "caption": diagram.get("caption", "")})
            else:
                result["skipped"].append(diagram.get("id", "unnamed diagram"))
        except Exception as e:
            result["errors"].append(f"{diagram.get('id', 'unnamed diagram')}: {e}")

    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python render_figures.py <visualization.md> <output_dir>")
        sys.exit(1)
    res = render_all(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"Rendered: {len(res['rendered'])}, skipped: {len(res['skipped'])}, errors: {len(res['errors'])}")
    for r in res["rendered"]:
        print(f"  OK  {r['id']} -> {r['path']}")
    for s in res["skipped"]:
        print(f"  SKIP {s}")
    for e in res["errors"]:
        print(f"  ERROR {e}")
