"""differ.py — compare successive versions of a proceeding into change records.

Reads the parser's output for two versions and writes one record per section:

  { "section": "50.4", "status": "modified",   # added / removed / modified / unchanged
    "old_text": "...", "new_text": "...", "similarity": 0.68 }

Design (from the TDD):

- The diff compares REGULATORY TEXT ONLY. Amendatory instructions are bookkeeping
  and are ignored here — mixing them is what F2 spends its bugs on.
- Sections pair by number, so a renumbered or dropped section shows up as
  added/removed instead of silently vanishing.
- A correction is a patch, not a version. The chain is proposed -> final; a
  correction applies to its base version. RM22-7's typo correction touches
  instruction text only, so its regulatory-text impact is zero — the honesty test.
- similarity is a magnitude hint for the UI. It NEVER decides a status: status is
  decided by the text (unchanged iff old == new). Materiality is the judge's job.

Usage:
    python3 src/differ.py                     # every docket in corpus/
    python3 src/differ.py corpus/RM22-7-000   # one docket
"""

import difflib
import json
import sys
from pathlib import Path

import parser  # sibling module in src/

CORPUS = Path(__file__).resolve().parent.parent / "corpus"


def similarity(a, b):
    """Ratio in [0, 1]. A hint only — see module docstring."""
    return difflib.SequenceMatcher(None, a, b).ratio()


def apply_replacements(text, replacements):
    """Apply a correction's old -> new substitutions to a piece of text."""
    for r in replacements:
        text = text.replace(r["old"], r["new"])
    return text


def diff_sections(old_sections, new_sections):
    """One change record per section, pairing by id, over regulatory text."""
    old = {s["id"]: s for s in old_sections}
    new = {s["id"]: s for s in new_sections}
    # New-document order first, then any section that only existed in the old one.
    ids = [s["id"] for s in new_sections] + [s["id"] for s in old_sections if s["id"] not in new]

    records = []
    for sid in ids:
        o = old.get(sid)
        n = new.get(sid)
        old_text = o["regulatory_text"] if o else ""
        new_text = n["regulatory_text"] if n else ""
        if o is None:
            status = "added"
        elif n is None:
            status = "removed"
        elif old_text == new_text:
            status = "unchanged"
        else:
            status = "modified"
        records.append({
            "section": sid,
            "status": status,
            "old_text": old_text,
            "new_text": new_text,
            "similarity": round(similarity(old_text, new_text), 4),
        })
    return records


def correction_impact(base_sections, correction):
    """What a correction does to its base version's REGULATORY text.

    An empty `regulatory_text_changed_sections` is the honesty result: the
    correction is a cross-reference typo fix that never touches the law.
    """
    replacements = correction.get("replacements", [])
    changed = [
        s["id"] for s in base_sections
        if apply_replacements(s["regulatory_text"], replacements) != s["regulatory_text"]
    ]
    return {
        "applied_to": correction.get("base_version"),
        "targets_instructions": correction.get("targets_instructions"),
        "replacements": replacements,
        "regulatory_text_changed_sections": changed,
    }


def _versions_by_kind(docket_dir):
    by_kind = {}
    for vdir in sorted(p.parent for p in Path(docket_dir).glob("*/raw.txt")):
        kind = json.loads((vdir / "metadata.json").read_text())["kind"]
        by_kind.setdefault(kind, []).append(vdir)
    return by_kind


def diff_docket(docket_dir):
    """Diff a docket's proposed -> final chain and record any correction's patch."""
    docket_dir = Path(docket_dir)
    by_kind = _versions_by_kind(docket_dir)

    proposed = by_kind.get("proposed", [None])[0]
    final = by_kind.get("final", [None])[0]

    old_sections = parser.parse(proposed)["sections"] if proposed else []
    new_sections = parser.parse(final)["sections"] if final else []
    changes = diff_sections(old_sections, new_sections) if (proposed and final) else []

    correction = None
    if by_kind.get("correction"):
        cdir = by_kind["correction"][0]
        crec = parser.parse(cdir)
        base_name = crec.get("base_version")
        base_dir = docket_dir / base_name if base_name else None
        base_sections = parser.parse(base_dir)["sections"] if base_dir and base_dir.exists() else []
        correction = correction_impact(base_sections, crec)

    return {
        "docket": docket_dir.name,
        "base": proposed.name if proposed else None,
        "target": final.name if final else None,
        "changes": changes,
        "correction": correction,
    }


def write_changes(docket_dir):
    result = diff_docket(docket_dir)
    (Path(docket_dir) / "changes.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv):
    dockets = [Path(a) for a in argv] or sorted(p for p in CORPUS.iterdir() if p.is_dir())
    for docket in dockets:
        r = write_changes(docket)
        n = sum(1 for c in r["changes"] if c["status"] != "unchanged")
        print(f"{docket.name}: {n} changed / {len(r['changes'])} sections"
              + ("" if r["correction"] is None else " (+correction)"))


if __name__ == "__main__":
    main(sys.argv[1:])
