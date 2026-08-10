"""
Assembles the Supervisor stage's compiled manuscript + rendered figures
(from render_figures.py) into a real, downloadable academic-style PDF.

Parses simple markdown: '#'/'##' headers, plain paragraphs, pipe tables,
and [FIGURE: Figure N] placeholder lines that get replaced with the actual
rendered PNG. Not a full markdown engine — built specifically for the
structure our agent prompts produce.

USAGE:
  python export_pdf.py manuscript/08_supervisor.md manuscript/figures/ manuscript/paper.pdf
"""

import re
import sys
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak, KeepTogether
)

STYLES = getSampleStyleSheet()
STYLES.add(ParagraphStyle(name="PaperTitle", fontSize=16, leading=20, spaceAfter=14, alignment=1))
STYLES.add(ParagraphStyle(name="SectionHead", fontSize=13, leading=16, spaceBefore=16, spaceAfter=8, fontName="Helvetica-Bold"))
STYLES.add(ParagraphStyle(name="SubHead", fontSize=11, leading=14, spaceBefore=10, spaceAfter=6, fontName="Helvetica-Bold"))
STYLES.add(ParagraphStyle(name="Body", fontSize=10.5, leading=15, spaceAfter=8, alignment=4))  # justified
STYLES.add(ParagraphStyle(name="Caption", fontSize=9, leading=12, spaceAfter=12, textColor=colors.HexColor("#444444")))
STYLES.add(ParagraphStyle(name="RefEntry", fontSize=9.5, leading=13, spaceAfter=6, leftIndent=18, firstLineIndent=-18))


def clean_inline(text: str) -> str:
    """Minimal inline markdown -> reportlab-safe markup: bold/italic, escape special chars."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"\[CHECK\]", '<font color="#B45309">[CHECK]</font>', text)
    text = re.sub(r"\[VERIFY\]", '<font color="#B45309">[VERIFY]</font>', text)
    text = re.sub(r"\[MISSING[^\]]*\]", lambda m: f'<font color="#B91C1C">{m.group(0)}</font>', text)
    return text


def parse_markdown_table(lines: list[str]) -> list[list[str]]:
    rows = []
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(re.match(r"^:?-+:?$", c) for c in cells if c):
            continue  # separator row
        rows.append(cells)
    return rows


def figure_lookup(figures_dir: Path) -> dict:
    """Maps 'figure 1', 'figure_1' etc. -> actual PNG path, tolerant of naming variation."""
    lookup = {}
    if figures_dir.exists():
        for png in figures_dir.glob("*.png"):
            key = png.stem.lower().replace("_", " ").replace("-", " ")
            lookup[key] = png
    return lookup


FIGURE_REF_RE = re.compile(r"^\s*!?\[?FIGURE:?\s*(Figure\s*\d+)\]?\s*$", re.IGNORECASE)
INLINE_FIGURE_RE = re.compile(r"\b(Figure\s*\d+)\b", re.IGNORECASE)


def build_story(md_text: str, figures: dict) -> list:
    story = []
    lines = md_text.splitlines()
    i = 0
    used_figures = set()
    in_references = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Headers
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            in_references = title.lower().startswith("reference")
            story.append(Paragraph(clean_inline(title), STYLES["SectionHead"]))
            i += 1
            continue
        if stripped.startswith("# "):
            story.append(Paragraph(clean_inline(stripped[2:].strip()), STYLES["PaperTitle"]))
            i += 1
            continue
        if stripped.startswith("### "):
            story.append(Paragraph(clean_inline(stripped[4:].strip()), STYLES["SubHead"]))
            i += 1
            continue

        # Tables
        if stripped.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            rows = parse_markdown_table(table_lines)
            if rows:
                tbl_data = [[Paragraph(clean_inline(c), STYLES["Caption"]) for c in row] for row in rows]
                tbl = Table(tbl_data, hAlign="LEFT", repeatRows=1)
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F7")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CCCCCC")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(KeepTogether([tbl, Spacer(1, 10)]))
            continue

        # Explicit figure placeholder line
        fig_match = FIGURE_REF_RE.match(stripped)
        if fig_match:
            key = fig_match.group(1).lower()
            png = figures.get(key)
            if png:
                used_figures.add(key)
                story.append(Image(str(png), width=5.0 * inch, height=3.2 * inch, kind="proportional"))
                story.append(Spacer(1, 4))
            i += 1
            continue

        # Reference list entries (in References section, keep as hanging-indent paragraphs)
        if in_references:
            story.append(Paragraph(clean_inline(stripped), STYLES["RefEntry"]))
            i += 1
            continue

        # Plain paragraph
        story.append(Paragraph(clean_inline(stripped), STYLES["Body"]))
        i += 1

    # Any rendered figures never referenced in text — append at the end so nothing is lost
    unused = [k for k in figures if k not in used_figures]
    if unused:
        story.append(Paragraph("Additional Figures", STYLES["SectionHead"]))
        for key in unused:
            story.append(Image(str(figures[key]), width=5.0 * inch, height=3.2 * inch, kind="proportional"))
            story.append(Spacer(1, 8))

    return story


def export_pdf(md_path: Path, figures_dir: Path, out_path: Path, title: str = "Manuscript Draft") -> None:
    md_text = md_path.read_text(encoding="utf-8")
    figures = figure_lookup(figures_dir)

    doc = SimpleDocTemplate(
        str(out_path), pagesize=LETTER,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        leftMargin=1.0 * inch, rightMargin=1.0 * inch,
    )
    story = [Paragraph(title, STYLES["PaperTitle"]), Spacer(1, 6)]
    story.extend(build_story(md_text, figures))
    doc.build(story)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python export_pdf.py <compiled.md> <figures_dir> <output.pdf> [title]")
        sys.exit(1)
    title = sys.argv[4] if len(sys.argv) > 4 else "Manuscript Draft"
    export_pdf(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), title)
    print(f"Written: {sys.argv[3]}")
