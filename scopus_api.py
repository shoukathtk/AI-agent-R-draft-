"""
Optional: live Scopus Serial Title API lookup, for users who have registered
a free Elsevier developer API key at https://dev.elsevier.com.

The free tier key gives limited daily quota and works fully outside an
institutional network only for a subset of endpoints — the Serial Title API
(checking whether a given ISSN is an active Scopus source) is one of the
endpoints that does work with just a registered key, no institutional IP
required, last verified against Elsevier's public API docs.

If you don't have a key, skip this file entirely — scopus_source_list.py's
offline source-list match is the free path and is equally authoritative for
"is this ISSN currently Scopus-indexed", just not live/quarterly-cached.

---
WOS_NOTE — Web of Science:
Clarivate does not offer a free public API. The Web of Science Starter API /
Expanded API require a paid institutional subscription with API access
provisioned separately from normal WoS access — check with your library.
Without that, the only way to check WoS/SCIE status is a manual search at
https://mjl.clarivate.com (Master Journal List) per journal. This module
has no automated WoS function for that reason; verify_references.py surfaces
WoS status as "MANUAL_CHECK_REQUIRED" rather than guessing.
"""

import json
import urllib.request
import urllib.parse

SERIAL_TITLE_API = "https://api.elsevier.com/content/serial/title/issn/{issn}"


def check_scopus_live(issn: str, api_key: str) -> dict:
    issn_clean = issn.replace("-", "")
    url = SERIAL_TITLE_API.format(issn=issn_clean)
    req = urllib.request.Request(url, headers={
        "X-ELS-APIKey": api_key,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"status": "NOT_IN_SCOPUS_LIST", "issn": issn}
        return {"status": "API_ERROR", "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"status": "API_ERROR", "error": str(e)}

    entry = data.get("serial-metadata-response", {}).get("entry", [{}])[0]
    if not entry or entry.get("error"):
        return {"status": "NOT_IN_SCOPUS_LIST", "issn": issn}

    coverage = entry.get("coverageStartYear"), entry.get("coverageEndYear")
    return {
        "status": "SCOPUS_CONFIRMED_LIVE",
        "journal_title": entry.get("dc:title"),
        "issn": issn,
        "coverage_years": coverage,
        "citescore": entry.get("citeScoreYearInfoList", {}).get("citeScoreCurrentMetric"),
        "subject_area": [c.get("$") for c in entry.get("subject-area", [])] if entry.get("subject-area") else None,
    }
