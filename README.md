# Citation verification module

Replaces the Literature Agent's self-reported (unreliable) indexing claims
with real, checkable results.

## What's actually free and automated

| Check | Source | Cost | Live/cached |
|---|---|---|---|
| Citation exists (DOI resolves, title/authors match) | Crossref API | Free, no key | Live |
| Scopus indexing status | Official Scopus Source List spreadsheet | Free download | Cached snapshot (re-download every few months) |
| Scopus indexing status (alternative) | Elsevier Serial Title API | Free registered key, rate-limited | Live |
| Web of Science / SCIE indexing status | — | — | **No free automated option — manual check only** |

Be honest with yourself about that last row: anything in this pipeline
claiming automated WoS verification would be lying to you. Every WoS status
this module reports is `MANUAL_CHECK_REQUIRED` by design.

## Setup

```bash
pip install openpyxl --break-system-packages   # only needed if using the raw .xlsx source list
```

1. **Scopus Source List** (recommended, free, no signup):
   Download from https://www.elsevier.com/products/scopus/scopus-source-list
   — grab the latest "Scopus Source List" / "Source Titles" file. Export it
   to CSV (Excel: File > Save As > CSV) for fastest loading, or point the
   script at the raw `.xlsx`.

2. **(Optional) Elsevier API key** for live lookups instead of the static
   list: register free at https://dev.elsevier.com. Gives you current data
   instead of a point-in-time snapshot, at the cost of a daily quota.

## Usage

```bash
cd verification
python verify_references.py ../manuscript/01_literature.md \
    --scopus-source-list ./scopus_source_list.csv
```

or, with a live API key instead of the CSV:

```bash
python verify_references.py ../manuscript/01_literature.md \
    --scopus-api-key YOUR_KEY
```

This writes `../manuscript/01_literature_VERIFIED.md` — a table showing,
per reference: whether Crossref confirms the citation exists, whether the
journal matches an active Scopus source (with CiteScore if found), and a
reminder that WoS needs a manual check. It never overwrites your original
literature draft.

## Recommended workflow

1. `python pipeline.py run literature --input topic.txt`
2. `cd verification && python verify_references.py ../manuscript/01_literature.md --scopus-source-list ...`
3. Open the `_VERIFIED.md` file. For anything marked `NOT_FOUND`,
   `NOT_IN_SCOPUS_LIST`, or `SOURCE_LIST_UNAVAILABLE`, either remove that
   source from the manuscript or manually confirm it another way.
4. Manually check WoS/SCIE status per source at https://mjl.clarivate.com
   for any journal you plan to cite as SCI-indexed specifically.
5. Hand-edit `manuscript/01_literature.md` to reflect the confirmed statuses.
6. `python ../pipeline.py approve literature`

## Known limitations

- Crossref's title-search fallback (used when no DOI is given) is a cheap
  token-overlap match, not real semantic matching — it can miss legitimate
  matches with reworded titles, or occasionally match the wrong paper if
  titles are very similar. Spot-check anything marked `CONFIRMED_FUZZY`.
- The Scopus Source List is a snapshot — a journal added or delisted since
  your download won't be reflected. Re-download periodically for active work.
- This checks *whether a journal is indexed*, not whether the specific
  cited article is genuinely as described — that still requires a human to
  actually read the source.
