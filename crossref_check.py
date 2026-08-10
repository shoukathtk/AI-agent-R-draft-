"""
Crossref lookup — verifies a citation actually exists and pulls its ISSN(s).

Crossref (https://api.crossref.org) is free, requires no API key, and covers
~150M+ scholarly records with DOIs. It does NOT tell you if a journal is
Scopus/WoS-indexed — it only confirms the work exists and lets us extract the
ISSN needed for the Scopus source-list match in scopus_source_list.py.
"""

import time
import urllib.parse
import urllib.request
import json


CROSSREF_API = "https://api.crossref.org/works"
# Crossref asks polite-pool users to identify themselves via a mailto param —
# improves rate limits, no registration needed. Replace with your own email.
POLITE_EMAIL = "researcher@example.com"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": f"citation-verifier/1.0 (mailto:{POLITE_EMAIL})"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def lookup_by_doi(doi: str) -> dict | None:
    """Fetch a work directly by DOI. Returns None if not found."""
    doi = doi.strip().replace("https://doi.org/", "")
    url = f"{CROSSREF_API}/{urllib.parse.quote(doi)}"
    try:
        data = _get(url)
    except Exception as e:
        return {"error": str(e)}
    msg = data.get("message", {})
    return _extract(msg)


def search_by_title_author(title: str, first_author: str | None = None, year: int | None = None) -> dict | None:
    """
    Fuzzy search when no DOI is given. Returns the best-matching candidate,
    or None if nothing plausible was found. Caller should sanity-check the
    returned title against the citation before trusting it.
    """
    query_parts = [title]
    if first_author:
        query_parts.append(first_author)
    query = " ".join(query_parts)
    params = {"query": query, "rows": "3"}
    url = f"{CROSSREF_API}?{urllib.parse.urlencode(params)}"
    try:
        data = _get(url)
    except Exception as e:
        return {"error": str(e)}
    items = data.get("message", {}).get("items", [])
    if not items:
        return None

    def title_of(item):
        t = item.get("title", [])
        return t[0].lower() if t else ""

    best = max(items, key=lambda it: _title_similarity(title.lower(), title_of(it)))
    if _title_similarity(title.lower(), title_of(best)) < 0.5:
        return None  # nothing close enough to trust
    return _extract(best)


def _title_similarity(a: str, b: str) -> float:
    """Cheap token-overlap similarity — good enough to reject wrong matches, not a real NLP metric."""
    a_tokens, b_tokens = set(a.split()), set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)


def _extract(msg: dict) -> dict:
    return {
        "found": True,
        "title": (msg.get("title") or [""])[0],
        "doi": msg.get("DOI"),
        "authors": [f"{a.get('given', '')} {a.get('family', '')}".strip() for a in msg.get("author", [])],
        "year": (msg.get("published") or msg.get("published-print") or msg.get("published-online") or {})
                 .get("date-parts", [[None]])[0][0],
        "container_title": (msg.get("container-title") or [""])[0],
        "issn": msg.get("ISSN", []),
        "publisher": msg.get("publisher"),
        "type": msg.get("type"),
    }


def verify_citation(doi: str | None, title: str | None, first_author: str | None, year: int | None,
                     rate_limit_sec: float = 1.0) -> dict:
    """Top-level entry point used by verify_references.py."""
    time.sleep(rate_limit_sec)  # be polite to the free API
    if doi:
        result = lookup_by_doi(doi)
        if result and result.get("found"):
            return {"status": "CONFIRMED", "method": "doi", **result}
    if title:
        result = search_by_title_author(title, first_author, year)
        if result and result.get("found"):
            return {"status": "CONFIRMED_FUZZY", "method": "title_search", **result}
    return {"status": "NOT_FOUND", "found": False}
