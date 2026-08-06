"""harness.py — score the judge against the golden set.

Runs offline, between judge versions. Grades every test case three ways:

- correct              — the judge matched the label.
- safe                 — the judge said unsure; a human decides. Not a win, not a failure.
- wrong-with-confidence — the judge gave a definite answer that disagrees with the
                          label. The only hard failure; material -> non-material (a
                          missed material change) is the worst. The suite exits
                          non-zero on any of these.

False negatives (material judged non-material) and false positives (non-material
judged material) are reported separately. Prompt-example cases (split == "prompt")
are reserved as few-shot material and are NEVER scored — a case pasted into the
prompt can't grade the judge.

Usage:
    python3 eval/harness.py                       # replay: score judge v1 from recordings
    python3 eval/harness.py --live                # call the real model, record, then score
    python3 eval/harness.py --golden P --recordings D --report R
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import judge  # noqa: E402

GOLDEN = ROOT / "eval" / "golden-set.jsonl"
REPORT = ROOT / "eval" / "score-report-v2.md"
RECORDINGS = ROOT / "recordings"


def grade(label, judged):
    """correct / safe / wrong_with_confidence — see module docstring."""
    if judged == label:
        return "correct"
    if judged == "unsure":
        return "safe"            # escalated instead of guessing
    return "wrong_with_confidence"


def load_golden(path=GOLDEN):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def score(cases, judge_fn):
    """Score every test-split case. `judge_fn(change) -> classification`."""
    graded, excluded = [], []
    counts = {"correct": 0, "safe": 0, "wrong_with_confidence": 0}
    false_negatives, false_positives = [], []

    for case in cases:
        if case["split"] != "test":
            excluded.append(case["id"])
            continue
        judged = judge_fn(case["change"])
        g = grade(case["label"], judged)
        counts[g] += 1
        graded.append({"id": case["id"], "label": case["label"], "judged": judged, "grade": g})
        if g == "wrong_with_confidence":
            if case["label"] == "material" and judged == "non-material":
                false_negatives.append(case["id"])
            elif case["label"] == "non-material" and judged == "material":
                false_positives.append(case["id"])

    return {
        "total": len(graded),
        "correct": counts["correct"],
        "safe": counts["safe"],
        "wrong_with_confidence": counts["wrong_with_confidence"],
        "false_negatives": false_negatives,
        "false_positives": false_positives,
        "graded": graded,
        "excluded": excluded,
    }


def exit_code(report):
    """Non-zero iff any wrong-with-confidence result — the suite's fail gate."""
    return 1 if report["wrong_with_confidence"] > 0 else 0


def render(report):
    lines = [
        "# Judge score report",
        "",
        f"- test cases scored: **{report['total']}**  (excluded prompt examples: {len(report['excluded'])})",
        f"- correct: **{report['correct']}**",
        f"- safe (said unsure): **{report['safe']}**",
        f"- wrong-with-confidence: **{report['wrong_with_confidence']}**",
        f"- false negatives (material -> non-material): {report['false_negatives'] or 'none'}",
        f"- false positives (non-material -> material): {report['false_positives'] or 'none'}",
        "",
        "| case | label | judged | grade |",
        "|---|---|---|---|",
    ]
    for g in report["graded"]:
        lines.append(f"| {g['id']} | {g['label']} | {g['judged']} | {g['grade']} |")
    return "\n".join(lines) + "\n"


def main(argv):
    mode = "live" if "--live" in argv else "replay"
    golden = Path(_opt(argv, "--golden", GOLDEN))
    recordings = Path(_opt(argv, "--recordings", RECORDINGS))
    report_path = Path(_opt(argv, "--report", REPORT))

    fixture = judge.load_fixture()
    cases = load_golden(golden)

    def judge_fn(change):
        return judge.judge_change(change, fixture, recordings, mode)["classification"]

    report = score(cases, judge_fn)
    report_path.write_text(render(report))
    print(render(report))
    code = exit_code(report)
    print(f"exit {code}" + ("" if code == 0 else "  (wrong-with-confidence present)"))
    return code


def _opt(argv, flag, default):
    return argv[argv.index(flag) + 1] if flag in argv else default


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
