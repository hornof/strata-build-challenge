"""fetcher.py — download every published version of a Federal Register proceeding.

Usage:
    python3 src/fetcher.py RM22-7-000 RM22-10-000 RM20-16-000

Writes, per document:
    corpus/<docket>/<publication_date>-<kind>/raw.txt        exact API text, never edited
    corpus/<docket>/<publication_date>-<kind>/metadata.json  structured fields from the API

The corpus is append-only: an existing raw.txt is never overwritten, and a
version already on disk is not re-fetched. Once this has run, the rest of the
pipeline works entirely from the saved files — no component past the fetcher
touches the network.
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://www.federalregister.gov/api/v1/documents.json"
FIELDS = [
    "document_number", "type", "publication_date", "effective_on", "title",
    "docket_ids", "raw_text_url", "correction_of", "html_url", "citation",
]

CORPUS = Path(__file__).resolve().parent.parent / "corpus"


def kind_of(doc):
    """proposed | final | correction, from the API type plus correction markers.

    The API's correction_of field is unreliable — it is null on RM20-16's
    correction — so a leading "C" in the document number and a "; Correction"
    title suffix are checked too. Misfiling a correction as a final rule would
    corrupt the diff chain, so detection is deliberately over-inclusive.
    """
    if (
        doc.get("correction_of")
        or doc["document_number"].startswith("C")
        or "; correction" in doc["title"].lower()
    ):
        return "correction"
    if doc["type"] == "Proposed Rule":
        return "proposed"
    if doc["type"] == "Rule":
        return "final"
    return doc["type"].lower().replace(" ", "-")


def version_dirname(doc):
    """The append-only folder name for a document: <publication_date>-<kind>."""
    return f"{doc['publication_date']}-{kind_of(doc)}"


def document_metadata(doc, docket):
    """The structured fields the rest of the pipeline reads, from one API record."""
    return {
        "docket": docket,
        "kind": kind_of(doc),
        "document_number": doc["document_number"],
        "publication_date": doc["publication_date"],
        "effective_on": doc.get("effective_on"),
        "correction_of": doc.get("correction_of"),
        "title": doc["title"],
        "citation": doc.get("citation"),
        "html_url": doc.get("html_url"),
    }


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


def fetch_text(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read().decode("utf-8", errors="replace")


def list_documents(docket):
    params = {"conditions[docket_id]": docket, "per_page": "50"}
    query = urllib.parse.urlencode(params)
    query += "".join(f"&fields[]={f}" for f in FIELDS)
    data = fetch_json(f"{API}?{query}")
    return sorted(data.get("results", []), key=lambda d: d["publication_date"])


def write_document(doc, docket, corpus_root, fetch_text=fetch_text):
    """Write one document's raw.txt + metadata.json under corpus_root.

    Returns True if it wrote a new version, False if the version already existed
    (in which case nothing is fetched or changed — the append-only guarantee).
    fetch_text is injectable so this path is testable without the network.
    """
    vdir = Path(corpus_root) / docket / version_dirname(doc)
    raw = vdir / "raw.txt"
    if raw.exists():
        return False
    vdir.mkdir(parents=True, exist_ok=True)
    raw.write_text(fetch_text(doc["raw_text_url"]))
    (vdir / "metadata.json").write_text(
        json.dumps(document_metadata(doc, docket), indent=2) + "\n"
    )
    return True


def fetch_docket(docket, corpus_root=CORPUS):
    docs = list_documents(docket)
    if not docs:
        print(f"  {docket}: no documents found", file=sys.stderr)
        return 0
    written = 0
    for doc in docs:
        if write_document(doc, docket, corpus_root):
            vdir = Path(corpus_root) / docket / version_dirname(doc)
            chars = len((vdir / "raw.txt").read_text())
            print(f"  {vdir.relative_to(corpus_root)}  ({chars:,} chars)")
            written += 1
        else:
            print(f"  {docket}/{version_dirname(doc)} exists — skipping (append-only)")
    return written


def main(argv):
    dockets = argv or ["RM22-7-000", "RM22-10-000", "RM20-16-000"]
    for docket in dockets:
        print(f"{docket}:")
        fetch_docket(docket)


if __name__ == "__main__":
    main(sys.argv[1:])
