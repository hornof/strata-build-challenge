"""F5 tests — golden set + harness. Written before eval/harness.py.

The harness grades the judge against the golden set: correct / safe (said unsure)
/ wrong-with-confidence (the only hard failure). It exits non-zero on any
wrong-with-confidence result. Prompt-example cases are excluded from scoring.

Run with zero setup, no network:

    python3 -m unittest discover -s tests
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

import judge  # noqa: E402
import harness  # noqa: E402

GOLDEN = ROOT / "eval" / "golden-set.jsonl"
HARNESS = ROOT / "eval" / "harness.py"


class Grade(unittest.TestCase):
    """The three grades, including the two directions that are hard failures."""

    def test_grade_mapping(self):
        g = harness.grade
        self.assertEqual(g("material", "material"), "correct")
        self.assertEqual(g("unsure", "unsure"), "correct")
        self.assertEqual(g("material", "unsure"), "safe")           # escalated, not wrong
        self.assertEqual(g("non-material", "unsure"), "safe")
        self.assertEqual(g("material", "non-material"), "wrong_with_confidence")  # the miss
        self.assertEqual(g("non-material", "material"), "wrong_with_confidence")  # over-fire
        self.assertEqual(g("unsure", "material"), "wrong_with_confidence")  # confident on a toss-up


class Score(unittest.TestCase):

    def cases(self):
        return [
            {"id": "t-mat", "split": "test", "label": "material",
             "change": {"section": "1", "old_text": "", "new_text": ""}},
            {"id": "t-non", "split": "test", "label": "non-material",
             "change": {"section": "2", "old_text": "", "new_text": ""}},
            {"id": "p-ex", "split": "prompt", "label": "material",
             "change": {"section": "3", "old_text": "", "new_text": ""}},
        ]

    def test_prompt_split_is_excluded_from_scoring(self):
        # A prompt-example case, even if judged wrong, is never counted.
        report = harness.score(self.cases(), lambda change: "non-material")
        self.assertEqual(report["total"], 2)                 # only the two test cases
        self.assertIn("p-ex", report["excluded"])
        self.assertNotIn("p-ex", [g["id"] for g in report["graded"]])

    def test_false_negatives_and_positives_reported_separately(self):
        # t-mat judged non-material -> false negative; t-non judged material -> false positive.
        def judged(change):
            return {"1": "non-material", "2": "material"}[change["section"]]
        report = harness.score(self.cases(), judged)
        self.assertEqual(report["false_negatives"], ["t-mat"])
        self.assertEqual(report["false_positives"], ["t-non"])
        self.assertEqual(report["wrong_with_confidence"], 2)

    def test_exit_code_is_nonzero_only_on_wrong_with_confidence(self):
        clean = harness.score(self.cases(), lambda c: {"1": "material", "2": "non-material"}[c["section"]])
        self.assertEqual(harness.exit_code(clean), 0)
        dirty = harness.score(self.cases(), lambda c: "non-material")  # t-mat becomes a miss
        self.assertEqual(harness.exit_code(dirty), 1)


class GoldenSet(unittest.TestCase):

    def test_golden_set_is_well_formed(self):
        cases = harness.load_golden(GOLDEN)
        self.assertGreaterEqual(len(cases), 10)
        labels = {"material", "non-material", "unsure"}
        splits = {"test", "prompt"}
        for c in cases:
            self.assertEqual(set(c) >= {"id", "split", "label", "change"}, True, c.get("id"))
            self.assertIn(c["label"], labels)
            self.assertIn(c["split"], splits)
        self.assertTrue(any(c["split"] == "prompt" for c in cases), "need reserved prompt examples")
        self.assertTrue(any(c["label"] == "unsure" for c in cases), "need unsure-labeled cases")


class CliExit(unittest.TestCase):
    """The exit-non-zero guarantee, verified end-to-end with a seeded failure."""

    def _seed(self, tmp, judged_label):
        # One test case whose true label is material; seed the judge to return
        # `judged_label` with no citations (citation check passes on empty), and a
        # refuter that agrees, so the seeded classification survives to scoring.
        change = {"section": "50.4", "status": "modified",
                  "old_text": "old", "new_text": "new"}
        golden = Path(tmp) / "golden.jsonl"
        golden.write_text(json.dumps(
            {"id": "seed", "split": "test", "label": "material", "change": change}) + "\n")
        recdir = Path(tmp) / "rec"
        fixture = judge.load_fixture()
        judgment = {"classification": judged_label, "reasoning": "seed",
                    "citations": [], "affected_obligations": [], "affected_projects": []}
        judge.record_response(recdir, judge.build_judge_request(change, fixture),
                              json.dumps(judgment), synthetic=True)
        judge.record_response(recdir, judge.build_refuter_request(change, judgment, fixture),
                              json.dumps({"refutes": False, "reasoning": "agree"}), synthetic=True)
        return golden, recdir

    def _run(self, golden, recdir, report):
        return subprocess.run(
            [sys.executable, str(HARNESS), "--golden", str(golden),
             "--recordings", str(recdir), "--report", str(report)],
            capture_output=True, text=True)

    def test_seeded_wrong_with_confidence_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            golden, recdir = self._seed(tmp, "non-material")  # miss on a material case
            result = self._run(golden, recdir, Path(tmp) / "report.md")
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_correct_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            golden, recdir = self._seed(tmp, "material")  # matches the label
            result = self._run(golden, recdir, Path(tmp) / "report.md")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
