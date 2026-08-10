"""
Runs real citation verification against the Literature Agent's output.

Parses the "Annotated Bibliography" markdown table the Literature agent
produced, verifies each entry via Crossref (existence + ISSN) then Scopus
(source-list match, or live API if a key is configured), and writes an
updated table with a REAL_VERIFICATION_STATUS column — replacing the model's
self-reported, unverifiable indexing claims.

USAGE
  python verify_references.py ../manuscript/01_literature.md \
      --scopus-source-list /path/to/scopus_source_list.csv \
      [--scopus-api-key YOUR_KEY]   # optional, uses live API instead of the CSV

Writes: ../manuscript/01_literature_VERIFIED.md
Never overwrites the original — review the verified version, then manually
merge accepted changes back before approving the stage in pipeline.py.
"""

import argparse
import re
import sys
from pathlib import Path

from crossref_check import verify_citation
from scopus_source_list import check_scopus_indexing

try:
    from scopus_api import check_scopus_live
except ImportError:
    check_scopus_live = None


def parse_bibliography_table(md_text: str) -> list[dict]:
    """
    Extracts rows from the first markdown table found after a line containing
    'Annotated Bibliography'. Expects columns roughly: Authors | Year | Venue |
    Indexing status | Summary | Relevance — but is tolerant of reordering as
    long as headers are present.
    """
    lines = md_text.splitlines()
    table_lines = []
    in_table = False
    for line in lines:
        if "|" in line and re.match(r"^\s*\|", line):
            in_table = True
            table_lines.append(line)
        elif in_table and "|" not in line:
            break
    if len(table_lines) < 2:
        return []

    header = [h.strip().lower() for h in table_lines[0].strip("|").split("|")]
    rows = []
    for line in table_lines[2:]:  # skip header + separator row
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(header):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def guess_first_author(authors_field: str) -> str | None:
    if not authors_field:
        return None
    first = re.split(r",|;|&|and", authors_field)[0].strip()
    return first or None


def guess_year(year_field: str) -> int | None:
    match = re.search(r"(19|20)\d{2}", year_field or "")
    return int(match.group()) if match else None


def verify_row(row: dict, scopus_source_list: str | None, scopus_api_key: str | None) -> dict:
    title = row.get("title") or row.get("summary") or row.get("venue", "")
    authors_field = row.get("authors", "")
    year = guess_year(row.get("year", ""))
    doi = None
    for key in row:
        if "doi" in key:
            doi = row[key]

    cr = verify_citation(doi=doi, title=title or row.get("venue"), first_author=guess_first_author(authors_field), year=year)

    scopus_result = {"status": "SKIPPED_NO_ISSN"}
    if cr.get("found") and cr.get("issn"):
        if scopus_api_key and check_scopus_live:
            scopus_result = check_scopus_live(cr["issn"][0], scopus_api_key)
        elif scopus_source_list:
            scopus_result = check_scopus_indexing(cr["issn"], scopus_source_list)
        else:
            scopus_result = {"status": "NO_SOURCE_LIST_CONFIGURED"}

    return {
        "original_row": row,
        "crossref": cr,
        "scopus": scopus_result,
        "wos": {"status": "MANUAL_CHECK_REQUIRED",
                "note": "Search https://mjl.clarivate.com — no free automated check available."},
    }


def render_verified_table(results: list[dict]) -> str:
    out = ["| Authors | Year | Venue (Crossref) | Citation status | Scopus status | WoS status |",
           "|---|---|---|---|---|---|"]
    for r in results:
        orig = r["original_row"]
        cr = r["crossref"]
        sc = r["scopus"]
        wos = r["wos"]
        authors = orig.get("authors", "")
        year = orig.get("year", "")
        venue = cr.get("container_title") or orig.get("venue", "")
        cite_status = cr.get("status", "UNKNOWN")
        scopus_status = sc.get("status", "UNKNOWN")
        if scopus_status == "SCOPUS_CONFIRMED" or scopus_status == "SCOPUS_CONFIRMED_LIVE":
            scopus_display = f"CONFIRMED (CiteScore {sc.get('citescore', 'n/a')})"
        elif scopus_status in ("NOT_IN_SCOPUS_LIST",):
            scopus_display = "NOT FOUND in Scopus list"
        else:
            scopus_display = scopus_status
        out.append(f"| {authors} | {year} | {venue} | {cite_status} | {scopus_display} | {wos['status']} |")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("literature_md", help="Path to 01_literature.md")
    parser.add_argument("--scopus-source-list", help="Path to downloaded Scopus Source List (.csv or .xlsx)")
    parser.add_argument("--scopus-api-key", help="Optional: Elsevier dev API key for live lookup instead of source list")
    args = parser.parse_args()

    md_path = Path(args.literature_md)
    if not md_path.exists():
        print(f"File not found: {md_path}")
        sys.exit(1)

    rows = parse_bibliography_table(md_path.read_text(encoding="utf-8"))
    if not rows:
        print("No bibliography table found (expected a markdown table under 'Annotated Bibliography').")
        sys.exit(1)

    print(f"Verifying {len(rows)} references via Crossref + Scopus...")
    results = []
    for i, row in enumerate(rows, 1):
        print(f"  [{i}/{len(rows)}] {row.get('authors', '?')[:40]}...")
        results.append(verify_row(row, args.scopus_source_list, args.scopus_api_key))

    table_md = render_verified_table(results)

    n_confirmed = sum(1 for r in results if r["scopus"]["status"] in ("SCOPUS_CONFIRMED", "SCOPUS_CONFIRMED_LIVE"))
    n_not_found_crossref = sum(1 for r in results if r["crossref"]["status"] == "NOT_FOUND")
    summary = (
        f"## Real Verification Summary\n\n"
        f"- References checked: {len(results)}\n"
        f"- Citation existence confirmed via Crossref: {len(results) - n_not_found_crossref}/{len(results)}\n"
        f"- Confirmed Scopus-indexed: {n_confirmed}/{len(results)}\n"
        f"- Web of Science: not automated — manual check required for all entries "
        f"(https://mjl.clarivate.com)\n\n"
        f"{table_md}\n"
    )

    out_path = md_path.with_name(md_path.stem + "_VERIFIED.md")
    out_path.write_text(summary, encoding="utf-8")
    print(f"\nWritten: {out_path}")
    print("Review this before merging into the approved literature stage.")


if __name__ == "__main__":
    main()
