"""judge.py — the only model call: classify one change against the company.

For each change record (from the differ) the judge asks the model to classify it
material / non-material / unsure against the whole company fixture, quoting the
passages it relies on. Three safeguards wrap the raw call:

- Citation check (code, not model): every quoted passage is string-matched against
  the source text. A quote not found verbatim means the judgment isn't trusted, so
  the change is downgraded to unsure. Kills hallucinated citations mechanically.
- Refuter (a second model call): argues the first judgment is wrong. A credible
  refutation on the material/non-material axis downgrades to unsure. Trust wins:
  a genuine disagreement escalates rather than passing silently.
- Record / replay: every model response is recorded to disk, keyed by a hash of the
  full request. Replay (the default) is deterministic and needs no API key — the
  demo and the eval suite run with zero setup. `--live` calls the real model and
  records. A replay miss is a clear error naming the --live fix.

Strict JSON only: model output that doesn't parse becomes unsure, never a crash.

Usage:
    python3 src/judge.py                 # replay every docket's changes
    python3 src/judge.py --live          # call the real model and record
"""

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
FIXTURE_PATH = ROOT / "fixtures" / "company.json"
RECORDINGS = ROOT / "recordings"

# Model-agnostic by construction (replay records the response); the demo pins the
# latest Claude for its --live run. Swapping the model is a recorded change, not
# an architecture change.
MODEL = "claude-opus-5"
MAX_TOKENS = 1024

MATERIALITY_RULES = (
    "A regulatory change is MATERIAL to this company if it alters what someone must "
    "do, by when, who is covered, or a threshold number: a new or removed obligation, "
    "a deadline created or moved, a scope change, a threshold change — AND it touches "
    "one of this company's obligations, projects, or documents. It is NON-MATERIAL if "
    "it is rewording, renumbering, a cross-reference or typography fix, or if it binds "
    "a different party and none of this company's obligations. Answer UNSURE when the "
    "evidence does not decide."
)


class RecordingNotFound(Exception):
    """Raised in replay mode when no recording exists for a request."""


# --------------------------------------------------------------------------- #
# Citation verification — code, not model.
# --------------------------------------------------------------------------- #

def normalize(text):
    """Canonicalize for verbatim matching: unify quotes/dashes, collapse whitespace."""
    text = (text.replace("“", '"').replace("”", '"')
                .replace("‘", "'").replace("’", "'")
                .replace("–", "-").replace("—", "-")
                .replace("``", '"').replace("''", '"'))
    return re.sub(r"\s+", " ", text).strip()


def verify_citations(citations, source_text):
    """Return (all_found, [unverified]). A quote counts only if it appears verbatim
    in the source after normalization — in either direction, an invented quote fails."""
    source = normalize(source_text)
    unverified = [c for c in citations if normalize(c) not in source]
    return (not unverified, unverified)


# --------------------------------------------------------------------------- #
# Record / replay wrapper.
# --------------------------------------------------------------------------- #

def request_hash(request):
    """Stable hash of the full request — the record/replay key."""
    blob = json.dumps(request, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def record_response(recordings_dir, request, response_text, synthetic=False):
    """Persist a response keyed by the request hash. `synthetic` labels test fixtures
    as such; real recordings from the --live run are synthetic=False."""
    recordings_dir = Path(recordings_dir)
    recordings_dir.mkdir(parents=True, exist_ok=True)
    path = recordings_dir / f"{request_hash(request)}.json"
    path.write_text(json.dumps(
        {"request": request, "response": response_text, "synthetic": synthetic},
        indent=2,
    ) + "\n")
    return path


def _live_call(request):
    """Call the real model and return its text. Imported lazily so replay never
    needs the SDK or a key."""
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        env = ROOT / ".env"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip()
    import anthropic
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=request["model"],
        max_tokens=request["max_tokens"],
        system=request["system"],
        messages=request["messages"],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def call_model(request, mode, recordings_dir):
    """Return the model's text for a request — from disk in replay, live otherwise."""
    recordings_dir = Path(recordings_dir)
    path = recordings_dir / f"{request_hash(request)}.json"
    if mode == "replay":
        if not path.exists():
            raise RecordingNotFound(
                f"No recording for this request at {path.name}. "
                f"Re-run with --live to record it (needs ANTHROPIC_API_KEY)."
            )
        return json.loads(path.read_text())["response"]
    text = _live_call(request)
    record_response(recordings_dir, request, text, synthetic=False)
    return text


# --------------------------------------------------------------------------- #
# Prompt construction — deterministic (no timestamps), so replay keys are stable.
# --------------------------------------------------------------------------- #

def _change_block(change):
    return (
        f"SECTION: {change['section']}\n"
        f"STATUS: {change['status']}\n"
        f"OLD TEXT:\n{change.get('old_text', '')}\n\n"
        f"NEW TEXT:\n{change.get('new_text', '')}"
    )


def build_judge_request(change, fixture):
    system = (
        "You are a regulatory-change judge for one utility. " + MATERIALITY_RULES +
        " Quote only exact passages from the change text as citations — never invent. "
        "Respond with STRICT JSON ONLY, no prose, matching: "
        '{"classification": "material|non-material|unsure", "reasoning": "one line", '
        '"citations": ["exact quoted passages"], "affected_obligations": ["O-###"], '
        '"affected_projects": ["..."], "recommended_action": "material only", '
        '"owner": "material only"}.'
    )
    user = (
        "COMPANY:\n" + json.dumps(fixture, sort_keys=True) +
        "\n\nCHANGE:\n" + _change_block(change)
    )
    return {"model": MODEL, "max_tokens": MAX_TOKENS,
            "system": system, "messages": [{"role": "user", "content": user}]}


def build_refuter_request(change, judgment, fixture):
    system = (
        "You are a skeptical reviewer. Argue that the judgment below is WRONG. " +
        MATERIALITY_RULES +
        " Lean toward refuting when uncertain. Respond with STRICT JSON ONLY: "
        '{"refutes": true|false, "reasoning": "one line"}.'
    )
    user = (
        "COMPANY:\n" + json.dumps(fixture, sort_keys=True) +
        "\n\nCHANGE:\n" + _change_block(change) +
        "\n\nJUDGMENT TO REFUTE:\n" + json.dumps(judgment, sort_keys=True)
    )
    return {"model": MODEL, "max_tokens": MAX_TOKENS,
            "system": system, "messages": [{"role": "user", "content": user}]}


def _parse(text):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# The judged disposition.
# --------------------------------------------------------------------------- #

def judge_change(change, fixture, recordings_dir, mode="replay"):
    """Classify one change, applying the citation check and the refuter."""
    raw = _parse(call_model(build_judge_request(change, fixture), mode, recordings_dir))

    disposition = {
        "section": change["section"],
        "status": change["status"],
        "classification": "unsure",
        "reasoning": "",
        "citations": [],
        "affected_obligations": [],
        "affected_projects": [],
        "recommended_action": None,
        "owner": None,
        "safeguards": {"json_ok": raw is not None, "citations_ok": True,
                       "unverified_citations": [], "refuter_refuted": False},
    }

    if raw is None:
        disposition["reasoning"] = "model output was not valid JSON"
        return disposition

    disposition.update({
        "classification": raw.get("classification", "unsure"),
        "reasoning": raw.get("reasoning", ""),
        "citations": raw.get("citations", []),
        "affected_obligations": raw.get("affected_obligations", []),
        "affected_projects": raw.get("affected_projects", []),
        "recommended_action": raw.get("recommended_action"),
        "owner": raw.get("owner"),
    })

    # Safeguard 1: citation check (code). Unverified quote -> not trusted -> unsure.
    source = f"{change.get('old_text', '')}\n{change.get('new_text', '')}"
    ok, unverified = verify_citations(disposition["citations"], source)
    disposition["safeguards"]["citations_ok"] = ok
    disposition["safeguards"]["unverified_citations"] = unverified
    if not ok:
        disposition["classification"] = "unsure"
        disposition["reasoning"] = "citation not found in source text; not trusted"
        return disposition

    # Safeguard 2: refuter (second model call), only for a definite call.
    if disposition["classification"] in ("material", "non-material"):
        refutation = _parse(call_model(
            build_refuter_request(change, raw, fixture), mode, recordings_dir))
        refuted = bool(refutation and refutation.get("refutes"))
        disposition["safeguards"]["refuter_refuted"] = refuted
        if refuted:
            disposition["classification"] = "unsure"
            disposition["reasoning"] = (
                f"refuter disagreed: {refutation.get('reasoning', '')}".strip()
            )

    return disposition


# --------------------------------------------------------------------------- #
# Fixture loading + CLI.
# --------------------------------------------------------------------------- #

def load_fixture(path=FIXTURE_PATH):
    return json.loads(Path(path).read_text())


def main(argv):
    import differ  # sibling module; only needed by the CLI
    mode = "live" if "--live" in argv else "replay"
    fixture = load_fixture()
    for docket_dir in sorted(p for p in CORPUS.iterdir() if p.is_dir()):
        result = differ.diff_docket(docket_dir)
        changes = [c for c in result["changes"] if c["status"] != "unchanged"]
        dispositions = [judge_change(c, fixture, RECORDINGS, mode) for c in changes]
        counts = {}
        for d in dispositions:
            counts[d["classification"]] = counts.get(d["classification"], 0) + 1
        print(f"{docket_dir.name}: {counts or 'no changes'}")


if __name__ == "__main__":
    main(sys.argv[1:])
