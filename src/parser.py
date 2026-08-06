"""parser.py — split a Federal Register document into sections.

Reads corpus/<docket>/<version>/raw.txt; `parse()` returns the structure,
`python3 src/parser.py` writes sections.json alongside each raw.txt.

The one hard problem (found during investigation, frozen in tests/test_parser.py):
Federal Register rules interleave two kinds of text under the same headings —

  amendatory instructions   "16. Amend Sec. 380.14 ... a. Remove the reference"
                            (instructions TO the CFR; bookkeeping)
  regulatory text           the words that become law

Diffing them together produces confident nonsense (a bookkeeping header bleeding
into Sec. 50.9 once looked like a 105-word change to notice rules). So each
section carries the two separately:

  { "id": "50.4", "title": "Stakeholder participation.",
    "regulatory_text": "...", "amendatory_instructions": "..." }

Corrections are not section-structured; they parse to a patch record with the
base version they apply to resolved (even when the API's correction_of is null):

  { "kind": "correction", "base_version": "2021-01-21-proposed",
    "replacements": [{"old": ..., "new": ...}], ... }
"""

import html
import json
import re
import sys
from pathlib import Path

CORPUS = Path(__file__).resolve().parent.parent / "corpus"

# GPO plain-text markers
RE_PRE = re.compile(r"<pre>(.*)</pre>", re.S)
RE_TAG = re.compile(r"<[^>]+>")
RE_PAGE = re.compile(r"^\[\[Page \d+\]\]\s*$")
RE_FRDOC_END = re.compile(r"^\[FR Doc\.")
RE_PART = re.compile(r"^PART (\d+)--")
RE_HEADING = re.compile(r"^Sec\.\s+(\d+\.\d+[a-z]?)\s{2,}(.+?)\s*$")
RE_INSTR_NUM = re.compile(
    r"^\s*(?:\d+|[a-z])\.\s+(?:Amend|Revise|Add|Remove|Redesignate|Designate|"
    r"Republish|The authority citation)"
)
RE_INSTR_TARGET = re.compile(r"(?:Amend|Revise|Add|Remove|Redesignate)\s+Sec\.\s+(\d+\.\d+[a-z]?)")
RE_AUTHORITY = re.compile(r"The authority citation for part (\d+)")
RE_BOILER = re.compile(r"^\s*The (?:addition|revision|amendment)s?(?: and (?:addition|revision)s?)? read as follows:")
RE_CORRECTION_PAIR = re.compile(r"``(.+?)''\s+should read\s+``(.+?)''", re.S)


def clean(raw):
    """Strip the HTML wrapper and stitch GPO page breaks; exact text otherwise.

    A page break is `blank line · [[Page N]] · blank line`. Removing only the
    marker leaves the two blanks, which the section splitter reads as a false
    paragraph boundary — cutting any instruction or sentence that spans the
    break. So the marker AND one adjacent blank on each side are removed, letting
    the split text rejoin.
    """
    m = RE_PRE.search(raw)
    text = m.group(1) if m else raw
    text = html.unescape(RE_TAG.sub("", text))
    lines = text.splitlines()
    out = []
    i, n = 0, len(lines)
    while i < n:
        if RE_PAGE.match(lines[i]):
            if out and out[-1].strip() == "":
                out.pop()
            i += 1
            if i < n and lines[i].strip() == "":
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def parse_correction(text, meta):
    replacements = [{"old": o.strip(), "new": n.strip()}
                    for o, n in RE_CORRECTION_PAIR.findall(text)]
    return {
        "kind": "correction",
        "corrects": meta.get("correction_of"),
        "targets_instructions": bool(re.search(r"amendatory instruction", text)),
        "replacements": replacements,
        "text": text.strip(),
    }


def resolve_base_version(vdir, meta):
    """The version dir a correction applies to.

    Prefer the API's correction_of (a URL ending in the base document number).
    When it is null — as on RM20-16's correction — infer the base as the most
    recent non-correction version published on or before the correction, which
    for RM20-16 is the proposed rule, not the later final.
    """
    vdir = Path(vdir)
    siblings = []
    for d in vdir.parent.iterdir():
        meta_path = d / "metadata.json"
        if d == vdir or not meta_path.exists():
            continue
        siblings.append({**json.loads(meta_path.read_text()), "_dir": d.name})

    corrects = meta.get("correction_of")
    if corrects:
        target = corrects.rstrip("/").split("/")[-1]
        for s in siblings:
            if s.get("document_number") == target:
                return s["_dir"]

    date = meta["publication_date"]
    prior = [s for s in siblings
             if s.get("kind") != "correction" and s["publication_date"] <= date]
    if prior:
        return max(prior, key=lambda s: s["publication_date"])["_dir"]
    return None


def parse_rule(text):
    """Section-split the amendatory region of a proposed or final rule."""
    lines = text.splitlines()

    # Region: from "List of Subjects" (or first PART header) to [FR Doc.
    start = None
    for i, line in enumerate(lines):
        if line.startswith("List of Subjects"):
            start = i
            break
    if start is None:
        for i, line in enumerate(lines):
            if RE_PART.match(line):
                start = i
                break
    if start is None:
        return []
    end = len(lines)
    for i in range(start, len(lines)):
        if RE_FRDOC_END.match(lines[i]):
            end = i
            break

    sections = {}          # id -> {"title", "regulatory_text": [], "amendatory_instructions": []}
    order = []

    def entry(sid, title=""):
        if sid not in sections:
            sections[sid] = {"title": title, "regulatory_text": [],
                             "amendatory_instructions": []}
            order.append(sid)
        elif title and not sections[sid]["title"]:
            sections[sid]["title"] = title
        return sections[sid]

    current = None          # section id whose regulatory text is open
    instr_target = None     # section id the current instruction block amends
    in_instruction = False  # set by a lone "0" marker line
    part = None

    for line in lines[start:end]:
        stripped = line.strip()

        m = RE_PART.match(line)
        if m:
            part = m.group(1)
            current = None
            in_instruction = False
            continue

        if stripped == "0":
            in_instruction = True
            continue

        m = RE_HEADING.match(line)
        if m:
            current = m.group(1)
            entry(current, m.group(2))
            in_instruction = False
            continue

        if in_instruction and not stripped:
            in_instruction = False
            continue

        is_instr_line = bool(RE_INSTR_NUM.match(line))
        if is_instr_line:
            in_instruction = True
        if in_instruction or RE_BOILER.match(line):
            m = RE_INSTR_TARGET.search(line)
            if m:
                instr_target = m.group(1)
            else:
                m = RE_AUTHORITY.search(line)
                if m:
                    instr_target = f"{m.group(1)}-authority"
            if instr_target:
                entry(instr_target)["amendatory_instructions"].append(stripped)
            continue

        if stripped.startswith("Authority:") and instr_target:
            entry(instr_target)["regulatory_text"].append(stripped)
            continue

        if current is not None:
            sections[current]["regulatory_text"].append(line.rstrip())
        elif instr_target and stripped:
            entry(instr_target)["amendatory_instructions"].append(stripped)

    out = []
    for sid in order:
        s = sections[sid]
        out.append({
            "id": sid,
            "title": s["title"],
            "regulatory_text": "\n".join(s["regulatory_text"]).strip(),
            "amendatory_instructions": "\n".join(s["amendatory_instructions"]).strip(),
        })
    return out


def parse(vdir):
    """Parse one version directory into its structure (no files written)."""
    vdir = Path(vdir)
    meta = json.loads((vdir / "metadata.json").read_text())
    text = clean((vdir / "raw.txt").read_text())
    if meta["kind"] == "correction":
        result = parse_correction(text, meta)
        result["base_version"] = resolve_base_version(vdir, meta)
        return result
    return {"kind": meta["kind"], "sections": parse_rule(text)}


def write_sections(vdir):
    result = parse(vdir)
    (Path(vdir) / "sections.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main(argv):
    targets = [Path(a) for a in argv] or sorted(
        p.parent for p in CORPUS.glob("*/*/raw.txt"))
    for vdir in targets:
        r = write_sections(vdir)
        n = "correction" if r["kind"] == "correction" else len(r["sections"])
        print(f"{vdir.relative_to(CORPUS.parent)}: {n}")


if __name__ == "__main__":
    main(sys.argv[1:])
