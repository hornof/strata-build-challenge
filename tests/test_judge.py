"""F4 tests — fixture + judge. Written before src/judge.py.

All model calls are replayed from synthetic recordings the tests write, so the
suite runs with no API key and no network (the anthropic SDK is never imported).
Recordings are keyed by a hash of the full request, so they stay valid when the
prompt text changes — the test rebuilds the request and re-derives the key.

Run with zero setup:

    python3 -m unittest discover -s tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import judge  # noqa: E402

FIXTURE = judge.load_fixture(ROOT / "fixtures" / "company.json")

# A change whose new text contains a real, quotable passage.
CHANGE = {
    "section": "50.4",
    "status": "modified",
    "old_text": "The application must include a Project Participation Plan.",
    "new_text": "The application must include a Tribal Engagement Plan that summarizes "
                "comments received from Indian Tribes contacted prior to filing.",
    "similarity": 0.5,
}
REAL_QUOTE = "Tribal Engagement Plan that summarizes comments received"

MATERIAL = {
    "classification": "material",
    "reasoning": "creates a new filing obligation",
    "citations": [REAL_QUOTE],
    "affected_obligations": ["O-013"],
    "affected_projects": ["Cascade Crossing"],
    "recommended_action": "Add the Tribal Engagement Plan to the pre-filing checklist.",
    "owner": "Dana Kim",
}


def rec(recordings_dir, request, response_text):
    """Write a synthetic recording the judge will replay for this request."""
    judge.record_response(recordings_dir, request, response_text, synthetic=True)


def judge_material(recordings_dir, refuter_response):
    """Set up a material judge recording + a refuter recording, then judge."""
    jreq = judge.build_judge_request(CHANGE, FIXTURE)
    rec(recordings_dir, jreq, json.dumps(MATERIAL))
    rreq = judge.build_refuter_request(CHANGE, MATERIAL, FIXTURE)
    rec(recordings_dir, rreq, json.dumps(refuter_response))
    return judge.judge_change(CHANGE, FIXTURE, recordings_dir)


class CitationCheck(unittest.TestCase):
    """Code, not model: quotes are matched against the source verbatim."""

    SOURCE = 'The applicant must include a “Tribal Engagement Plan” that  summarizes comments.'

    def test_real_quote_passes_after_normalization(self):
        # Straight quotes vs the source's curly quotes; collapsed whitespace.
        ok, unverified = judge.verify_citations(
            ['a "Tribal Engagement Plan" that summarizes comments'], self.SOURCE
        )
        self.assertTrue(ok)
        self.assertEqual(unverified, [])

    def test_invented_quote_is_rejected(self):
        ok, unverified = judge.verify_citations(["a Carbon Capture Plan"], self.SOURCE)
        self.assertFalse(ok)
        self.assertEqual(unverified, ["a Carbon Capture Plan"])


class StrictJsonParse(unittest.TestCase):

    def test_malformed_model_output_becomes_unsure_never_crashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            jreq = judge.build_judge_request(CHANGE, FIXTURE)
            rec(tmp, jreq, "this is not valid json {{{")
            disp = judge.judge_change(CHANGE, FIXTURE, tmp)
            self.assertEqual(disp["classification"], "unsure")


class CitationSafeguard(unittest.TestCase):

    def test_invented_citation_downgrades_material_to_unsure(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = {**MATERIAL, "citations": ["a Carbon Capture Plan (not in the text)"]}
            jreq = judge.build_judge_request(CHANGE, FIXTURE)
            rec(tmp, jreq, json.dumps(bad))
            disp = judge.judge_change(CHANGE, FIXTURE, tmp)
            self.assertEqual(disp["classification"], "unsure")
            self.assertFalse(disp["safeguards"]["citations_ok"])

    def test_verified_citation_keeps_material_when_refuter_agrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = judge_material(tmp, {"refutes": False, "reasoning": "agree"})
            self.assertEqual(disp["classification"], "material")
            self.assertTrue(disp["safeguards"]["citations_ok"])
            self.assertFalse(disp["safeguards"]["refuter_refuted"])


class Refuter(unittest.TestCase):

    def test_credible_refutation_flips_material_to_unsure(self):
        with tempfile.TemporaryDirectory() as tmp:
            disp = judge_material(
                tmp, {"refutes": True, "reasoning": "this binds a different party"}
            )
            self.assertEqual(disp["classification"], "unsure")
            self.assertTrue(disp["safeguards"]["refuter_refuted"])


class RecordReplay(unittest.TestCase):

    def test_request_hash_is_stable(self):
        a = judge.request_hash(judge.build_judge_request(CHANGE, FIXTURE))
        b = judge.request_hash(judge.build_judge_request(CHANGE, FIXTURE))
        self.assertEqual(a, b)

    def test_replay_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            d1 = judge_material(tmp, {"refutes": False, "reasoning": "agree"})
            d2 = judge.judge_change(CHANGE, FIXTURE, tmp)
            self.assertEqual(d1, d2)

    def test_replay_miss_names_the_live_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(judge.RecordingNotFound) as ctx:
                judge.judge_change(CHANGE, FIXTURE, tmp)  # nothing recorded
            self.assertIn("--live", str(ctx.exception))

    def test_test_recordings_are_labeled_synthetic(self):
        with tempfile.TemporaryDirectory() as tmp:
            jreq = judge.build_judge_request(CHANGE, FIXTURE)
            judge.record_response(tmp, jreq, json.dumps(MATERIAL), synthetic=True)
            path = Path(tmp) / f"{judge.request_hash(jreq)}.json"
            saved = json.loads(path.read_text())
            self.assertTrue(saved["synthetic"])


class ReplayNeedsNoSdk(unittest.TestCase):

    def test_pipeline_runs_end_to_end_without_importing_anthropic(self):
        sys.modules.pop("anthropic", None)
        with tempfile.TemporaryDirectory() as tmp:
            disp = judge_material(tmp, {"refutes": False, "reasoning": "agree"})
            self.assertIn(disp["classification"], ("material", "non-material", "unsure"))
            self.assertEqual(disp["section"], "50.4")
            self.assertNotIn("anthropic", sys.modules, "replay must not touch the SDK")


if __name__ == "__main__":
    unittest.main()
