"""app.py — the weekly review: render the three screens from dispositions + fixture.

The director's week is the golden-set test cases judged (replayed) against the
company fixture. Material changes route to the obligation's named owner on
detection; unsure changes wait for the director; non-material changes are recorded
with one line of reasoning. Bounces, rulings, and overturns append labeled cases
to the golden set and to app state. Signing the week produces the coverage record.

Usage:
    python3 src/app.py            # render app/director.html, app/owner.html, app/metrics.html
    python3 src/app.py demo       # run the two-act demo (Act 1 review, Act 2 harness)
"""

import html as _html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

import judge
import harness

RECORDINGS = ROOT / "recordings"
GOLDEN = ROOT / "eval" / "golden-set.jsonl"
OUT = ROOT / "app"

# Illustrative published trust figure (product-level, over all weeks to date).
MISS_RATE_LINE = "412 judged non-material · 3 overturned (0.7% miss rate)"
# Demo routing dates, keyed by section (illustrative).
DEADLINES = {"50.4": ("Aug 12", "Sep 2"), "35.28": ("Aug 12", "Sep 9"),
             "50.5": ("Aug 13", "Sep 9")}


# --------------------------------------------------------------------------- #
# Routing.
# --------------------------------------------------------------------------- #

def _obligation(fixture, oid):
    return next((o for o in fixture["obligations"] if o["id"] == oid), None)


def route(disposition, fixture):
    """A material change routes to its obligation's named owner; a material change
    with no mapped obligation routes to the director as backstop (Luke's N1 ruling)."""
    if disposition["classification"] != "material":
        return None
    for oid in disposition.get("affected_obligations", []):
        ob = _obligation(fixture, oid)
        if ob:
            return {"owner": ob["owner"], "owner_role": ob["owner_role"],
                    "obligation": oid, "projects": ob["projects"], "tag": None}
    return {"owner": "director", "owner_role": "Director of Regulatory Affairs",
            "obligation": None, "projects": [],
            "tag": "material · no mapped obligation — candidate new obligation"}


# --------------------------------------------------------------------------- #
# The week.
# --------------------------------------------------------------------------- #

def build_week(golden, fixture, recordings):
    tests = [c for c in golden if c["split"] == "test"]
    week = {"total": len(tests), "material": [], "unsure": [], "non_material": []}
    for case in tests:
        d = judge.judge_change(case["change"], fixture, recordings, "replay")
        d["_change"] = case["change"]
        if d["classification"] == "material":
            detected, deadline = DEADLINES.get(d["section"], ("Aug 12", "Sep 2"))
            week["material"].append({"disposition": d, "route": route(d, fixture),
                                     "detected": detected, "deadline": deadline,
                                     "status": "in progress"})
        elif d["classification"] == "unsure":
            week["unsure"].append(d)
        else:
            week["non_material"].append(d)
    week["counts"] = {"material": len(week["material"]), "unsure": len(week["unsure"]),
                      "non_material": len(week["non_material"])}
    return week


# --------------------------------------------------------------------------- #
# App state + actions. Bounces / rulings / overturns become labeled cases.
# --------------------------------------------------------------------------- #

def new_state():
    return {"golden_additions": [], "actions": [], "signed": False}


def _add_case(state, section, label, note, action):
    case = {"id": f"A1-{action}-{section}", "split": "test", "label": label,
            "note": note, "change": {"section": section}}
    state["golden_additions"].append(case)
    state["actions"].append({"action": action, "section": section, "label": label, "note": note})
    return case


def bounce(state, section, reason):
    """Owner bounces a routed material change as a false positive."""
    return _add_case(state, section, "non-material", f"owner bounced: {reason}", "bounce")


def rule(state, section, ruling):
    """Director rules an unsure change."""
    return _add_case(state, section, ruling, f"director ruled {ruling}", "rule")


def overturn(state, section, ruling):
    """Director overturns a recorded non-material change ('this mattered')."""
    return _add_case(state, section, ruling, f"director overturned to {ruling}", "overturn")


def sign_week(week, state, when, by="Director"):
    """The coverage record: every change dispositioned, by whom, when, on what basis."""
    rows = []
    for m in week["material"]:
        d = m["disposition"]
        rows.append({"section": d["section"], "classification": "material",
                     "by": m["route"]["owner"], "on": m["detected"], "basis": d["reasoning"]})
    for d in week["unsure"]:
        rows.append({"section": d["section"], "classification": "unsure",
                     "by": by, "on": when, "basis": d["reasoning"] or "escalated for a ruling"})
    for d in week["non_material"]:
        rows.append({"section": d["section"], "classification": "non-material",
                     "by": "system (recorded)", "on": when, "basis": d["reasoning"]})
    state["signed"] = True
    return {"dispositions": rows, "coverage": "100%", "signed_by": by, "on": when}


coverage_record = sign_week


def correction_closer(week):
    """The honesty test: the system's whole response to the correction is one line.
    Identify the correction by its paragraph-designation typo, not by any mention of
    a cross-reference (other reasoning can mention one)."""
    for d in week["non_material"]:
        ch = d.get("_change", {})
        if "paragraph (e)" in ch.get("new_text", "") or "paragraph I" in ch.get("old_text", ""):
            return f"seen, non-material: cross-reference typo (paragraph I → paragraph (e)) — {d['reasoning']}"
    return "seen, non-material: cross-reference typo"


# --------------------------------------------------------------------------- #
# Rendering.
# --------------------------------------------------------------------------- #

_STYLE = """
:root{--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--border:rgba(11,11,11,.10);--blue:#2a78d6;--good:#0ca30c;--good-t:#006300;
--warn:#fab219;--crit:#d03b3b;}
*{box-sizing:border-box}body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
background:var(--page);color:var(--ink);margin:0;padding:28px}
.screen{background:var(--surface);border:1px solid var(--border);border-radius:12px;
max-width:980px;margin:0 auto 40px;padding:24px 28px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
.tag{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.head{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid var(--grid);
padding-bottom:12px;margin-bottom:16px}.head h2{font-size:17px;margin:0}.head .sub{font-size:12.5px;color:var(--ink2)}
.counts{display:flex;gap:10px;margin:14px 0 18px}.count{flex:1;border:1px solid var(--border);border-radius:10px;padding:10px 14px}
.count b{font-size:22px;display:block}.count span{font-size:12px;color:var(--ink2)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
h3.sec{font-size:13px;margin:20px 0 8px;color:var(--ink2);text-transform:uppercase;letter-spacing:.05em}
table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--muted);font-weight:600;
font-size:11.5px;padding:6px 8px;border-bottom:1px solid var(--grid)}td{padding:8px;border-bottom:1px solid var(--grid);vertical-align:top}
.pill{display:inline-block;font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid var(--border);white-space:nowrap}
.pill.mat{border-color:var(--crit);color:var(--crit)}.pill.uns{border-color:var(--warn);color:#8a6200}
.pill.non{border-color:var(--good);color:var(--good-t)}.pill.prog{background:#eef4fc;border-color:#b7d3f6;color:#1c5cab}
.btn{font-size:12px;padding:5px 12px;border-radius:7px;border:1px solid var(--border);background:#fff}
.btn.primary{background:var(--blue);border-color:var(--blue);color:#fff;font-weight:600}
.btn.danger{color:var(--crit);border-color:var(--crit)}.btn.ghost{color:var(--ink2)}
.foot{display:flex;justify-content:space-between;align-items:center;margin-top:18px;padding-top:14px;
border-top:1px solid var(--grid);font-size:12.5px;color:var(--ink2)}
.quote{border-left:3px solid var(--grid);padding:6px 12px;margin:6px 0;font-size:13px}
.quote.new{border-left-color:var(--good);background:#f2faf2}.quote.old{border-left-color:#c3c2b7;color:var(--ink2)}
.kv{display:grid;grid-template-columns:160px 1fr;gap:4px 12px;font-size:13px;margin:10px 0}.kv dt{color:var(--muted)}.kv dd{margin:0}
.check{color:var(--good-t);font-weight:600}.tiles{display:flex;gap:12px;margin-bottom:18px}
.tile{flex:1;border:1px solid var(--border);border-radius:10px;padding:14px 16px}.tile .l{font-size:12px;color:var(--ink2)}
.tile .big{font-size:30px;font-weight:700;margin:2px 0}.tile .d{font-size:12px;color:var(--good-t);font-weight:600}
"""


def _page(tag, title, sub, body):
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{_html.escape(title)}</title>"
            f"<style>{_STYLE}</style></head><body><div class='screen'>"
            f"<div class='tag'>{_html.escape(tag)}</div>"
            f"<div class='head'><h2>{title}</h2><div class='sub'>{sub}</div></div>"
            f"{body}</div></body></html>")


def render_director(week, state):
    c = week["counts"]
    counts = (
        f"<div class='counts'>"
        f"<div class='count'><b>{c['material']}</b><span><span class='dot' style='background:var(--crit)'></span>material — routed on detection</span></div>"
        f"<div class='count'><b>{c['unsure']}</b><span><span class='dot' style='background:var(--warn)'></span>unsure — waiting on you</span></div>"
        f"<div class='count'><b>{c['non_material']}</b><span><span class='dot' style='background:var(--good)'></span>non-material — recorded, skim below</span></div>"
        f"</div>")

    uns = "".join(
        f"<tr><td>§ {d['section']}</td><td>{_html.escape(d['reasoning'])}</td>"
        f"<td><button class='btn'>Material</button> <button class='btn'>Non-material</button></td></tr>"
        for d in week["unsure"]) or "<tr><td colspan='3' style='color:var(--muted)'>none this week</td></tr>"

    mat_rows = "".join(
        f"<tr><td>§ {m['disposition']['section']}</td>"
        f"<td>{m['route']['obligation'] or m['route']['tag'] or '—'}</td>"
        f"<td>{_html.escape(m['route']['owner'])}</td><td>{m['detected']} (on detection)</td>"
        f"<td>{m['deadline']}</td><td><span class='pill prog'>{m['status']}</span></td></tr>"
        for m in week["material"])

    non = "".join(
        f"<tr><td>§ {d['section']}</td><td>{_html.escape(d['reasoning'])}</td>"
        f"<td><button class='btn ghost'>This mattered</button></td></tr>"
        for d in week["non_material"])

    body = (
        counts +
        "<h3 class='sec'>Unsure — your ruling needed</h3><table>" + uns + "</table>" +
        "<h3 class='sec'>Material — routed, status</h3><table>"
        "<tr><th>Change</th><th>Obligation / project</th><th>Owner</th><th>Routed</th><th>Deadline</th><th>Status</th></tr>"
        + mat_rows + "</table>" +
        f"<h3 class='sec'>Non-material — {c['non_material']} recorded · spot-check</h3><table>" + non + "</table>" +
        f"<div class='foot'><span>To date: {MISS_RATE_LINE} · every ruling becomes a test case</span>"
        f"<button class='btn primary'>Sign the week — coverage record</button></div>")
    return _page("director: the weekly disposition review",
                 "Week of Aug 10–16 · Cascadia Grid Energy",
                 f"{week['total']} changes · coverage <b>100%</b>", body)


def render_owner(material_entry, fixture):
    d = material_entry["disposition"]
    ch = d["_change"]
    r = material_entry["route"]
    cites = len(d.get("citations", []))
    body = (
        f"<dl class='kv'>"
        f"<dt>Judgment</dt><dd><span class='pill mat'>material</span>&nbsp; {_html.escape(d['reasoning'])}</dd>"
        f"<dt>Hits</dt><dd><b>{r['obligation'] or r['tag']}</b>"
        f"{(' · project ' + ', '.join(r['projects'])) if r['projects'] else ''}</dd>"
        f"<dt>Recommended action</dt><dd>{_html.escape(d.get('recommended_action') or '—')}</dd>"
        f"<dt>Citations</dt><dd><span class='check'>✓ {cites} passages verified verbatim against the source</span></dd>"
        f"</dl>"
        f"<h3 class='sec'>What changed</h3>"
        f"<div class='quote old'>Old: <i>{_html.escape(ch.get('old_text',''))}</i></div>"
        f"<div class='quote new'>New: {_html.escape(ch.get('new_text',''))}</div>"
        f"<div class='foot'><span>Bouncing records your reason and files this as a labeled test case.</span>"
        f"<span><button class='btn primary'>Accept &amp; start</button> "
        f"<button class='btn danger'>Bounce — doesn't affect us</button> "
        f"<button class='btn ghost'>Reassign</button></span></div>")
    return _page("owner: a routed material change",
                 f"§ {d['section']} — routed to {r['owner']}",
                 f"routed to <b>{r['owner']} · {r['owner_role']}</b> · detected {material_entry['detected']} · deadline <b>{material_entry['deadline']}</b>",
                 body)


def render_metrics():
    tiles = (
        "<div class='tiles'>"
        "<div class='tile'><div class='l'>Trust — automated judgments upheld</div><div class='big'>99.4%</div><div class='d'>↑ from 97.8% · target ~100%</div></div>"
        "<div class='tile'><div class='l'>Automation — dispositioned without a human</div><div class='big'>58%</div><div class='d'>↑ from 22% · goal 80%</div></div>"
        "<div class='tile'><div class='l'>Weekly reviews signed</div><div class='big'>16 / 16</div><div class='d'>every week since onboarding</div></div>"
        "</div>")
    body = tiles + (
        "<h3 class='sec'>Supporting numbers</h3>"
        "<table><tr><th>Metric</th><th>Now</th><th>Reading</th></tr>"
        "<tr><td>Miss rate (false negatives)</td><td>0.7%</td><td>the liability number — monotonically declining</td></tr>"
        "<tr><td>Noise rate (bounced false positives)</td><td>4%</td><td>down from 12% — the alert-fatigue number</td></tr>"
        "<tr><td>Escalation rate (unsure)</td><td>6%</td><td>a watched band, not a target</td></tr>"
        "</table>"
        "<div class='foot'><span>Wk 9 was a deliberate bad week: a new docket family added, two misses appeared, "
        "were caught on review, frozen as test cases, and provably fixed before judge v3 shipped.</span></div>")
    return _page("trust & adoption metrics · 16 weeks", "Trust and adoption", "two dials; trust wins when they conflict", body)


def render_all(outdir=OUT):
    fixture = judge.load_fixture()
    week = build_week(harness.load_golden(GOLDEN), fixture, RECORDINGS)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "director.html").write_text(render_director(week, new_state()))
    tep = next((m for m in week["material"] if m["disposition"]["section"] == "50.4"), week["material"][0])
    (outdir / "owner.html").write_text(render_owner(tep, fixture))
    (outdir / "metrics.html").write_text(render_metrics())
    return outdir


def demo():
    fixture = judge.load_fixture()
    week = build_week(harness.load_golden(GOLDEN), fixture, RECORDINGS)
    state = new_state()
    render_all()

    print("== ACT 1 — the week ==")
    print(f"Director's screen: {week['counts']['material']} material (routed), "
          f"{week['counts']['unsure']} unsure (waiting), {week['counts']['non_material']} non-material (recorded).")
    print("Owner accepts § 50.4 (Tribal Engagement Plan).")
    b = bounce(state, "35.28", "applies to Basin Interconnect, not this siting scope")
    print(f"Owner bounces § 35.28 -> labeled case {b['label']} (noise ticks).")
    r = rule(state, "380.16", "non-material")
    print(f"Director rules unsure § 380.16 -> {r['label']} (becomes a labeled case).")
    o = overturn(state, "50.1", "material")
    print(f"Director overturns a non-material (§ 50.1) -> '{o['label']}' (miss ticks).")
    record = sign_week(week, state, when="2026-08-16")
    print(f"Director signs: coverage {record['coverage']}, {len(record['dispositions'])} changes dispositioned.")
    (OUT / "coverage-record.json").write_text(json.dumps(record, indent=2) + "\n")
    (OUT / "golden-additions.jsonl").write_text(
        "".join(json.dumps(c) + "\n" for c in state["golden_additions"]))

    print("\n== ACT 2 — improvement, shown by the eval ==")
    v1 = (ROOT / "eval" / "score-report-v1.md").read_text()
    v2 = (ROOT / "eval" / "score-report-v2.md").read_text()
    print("judge v1:", _grade_line(v1))
    print("judge v2:", _grade_line(v2), "(after Act-1 cases + the narrow ambiguity rule)")
    print("closer —", correction_closer(week))
    print(f"\nScreens written to {OUT}/ (director.html, owner.html, metrics.html).")


def _grade_line(report):
    def n(word):
        for line in report.splitlines():
            if word in line:
                return line.split("**")[1]
        return "?"
    return f"{n('correct:')} correct · {n('safe')} safe · {n('wrong-with-confidence:')} wrong-with-confidence"


def main(argv):
    if argv and argv[0] == "demo":
        demo()
    else:
        print("rendered screens to", render_all())


if __name__ == "__main__":
    main(sys.argv[1:])
