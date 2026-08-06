"""F3 tests — differ. Written before src/differ.py.

The first test is regression case 3: RM22-10's final amends no CFR text, so the
correct diff is zero changed sections — a valid result, not an error. The rest
check mirror-image symmetry, the correction honesty invariant, the RM22-7 ground
truth, and that similarity is a hint that never gates a status.

Run with zero setup, no network:

    python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import parser  # noqa: E402
import differ  # noqa: E402

CORPUS = ROOT / "corpus"
RM227 = CORPUS / "RM22-7-000"


def sec(sid, text):
    return {"id": sid, "title": "", "regulatory_text": text, "amendatory_instructions": ""}


class ZeroSections(unittest.TestCase):
    """Regression case 3, written first."""

    def test_rm22_10_final_yields_zero_changed_sections_as_valid_output(self):
        d = differ.diff_docket(CORPUS / "RM22-10-000")
        # A dict, not an exception: this is a valid result.
        self.assertEqual(d["docket"], "RM22-10-000")
        self.assertIn("changes", d)
        # Both versions amend no CFR text — nothing added, removed, or modified.
        self.assertEqual(d["changes"], [])


class MirrorImages(unittest.TestCase):
    """added/removed are mirror images; modified swaps old/new."""

    def test_added_removed_and_modified_are_symmetric_under_swap(self):
        old = [sec("A", "x"), sec("B", "one")]
        new = [sec("B", "two"), sec("C", "y")]

        fwd = {c["section"]: c for c in differ.diff_sections(old, new)}
        self.assertEqual(fwd["A"]["status"], "removed")
        self.assertEqual(fwd["C"]["status"], "added")
        self.assertEqual(fwd["B"]["status"], "modified")
        self.assertEqual((fwd["B"]["old_text"], fwd["B"]["new_text"]), ("one", "two"))

        rev = {c["section"]: c for c in differ.diff_sections(new, old)}
        self.assertEqual(rev["A"]["status"], "added")     # mirror of removed
        self.assertEqual(rev["C"]["status"], "removed")   # mirror of added
        self.assertEqual(rev["B"]["status"], "modified")
        self.assertEqual((rev["B"]["old_text"], rev["B"]["new_text"]), ("two", "one"))


class CorrectionInvariant(unittest.TestCase):
    """RM22-7's typo correction changes instruction text, not regulatory text."""

    def test_correction_is_near_zero_regulatory_change_touching_instructions_only(self):
        base = parser.parse(RM227 / "2024-05-29-final")["sections"]
        corr = parser.parse(RM227 / "2024-06-03-correction")

        impact = differ.correction_impact(base, corr)
        # Applied to regulatory text, the patch changes nothing — the honesty test.
        self.assertEqual(impact["regulatory_text_changed_sections"], [])
        self.assertEqual(impact["applied_to"], "2024-05-29-final")

        # And it does touch instruction text (that is where "paragraph I" lives).
        self.assertTrue(corr["targets_instructions"])
        touched = any(
            differ.apply_replacements(s["amendatory_instructions"], corr["replacements"])
            != s["amendatory_instructions"]
            for s in base
        )
        self.assertTrue(touched, "the correction should change some instruction text")


class RM227Sanity(unittest.TestCase):

    def setUp(self):
        self.d = differ.diff_docket(RM227)
        self.by_id = {c["section"]: c for c in self.d["changes"]}

    def test_known_modified_and_unchanged_sections(self):
        for sid in ("50.4", "50.5", "380.16"):
            self.assertEqual(self.by_id[sid]["status"], "modified", sid)
        self.assertEqual(self.by_id["50.2"]["status"], "unchanged")

    def test_no_sections_added_or_removed(self):
        for c in self.d["changes"]:
            self.assertIn(c["status"], ("modified", "unchanged"), c["section"])

    def test_50_4_tribal_engagement_plan_new_not_old(self):
        rec = self.by_id["50.4"]
        self.assertIn("Tribal Engagement Plan", rec["new_text"])
        self.assertNotIn("Tribal Engagement Plan", rec["old_text"])


class SimilarityIsAHintNotAGate(unittest.TestCase):

    def test_similarity_in_unit_interval_and_status_follows_text_not_similarity(self):
        for docket in ("RM22-7-000", "RM22-10-000", "RM20-16-000"):
            d = differ.diff_docket(CORPUS / docket)
            for c in d["changes"]:
                self.assertGreaterEqual(c["similarity"], 0.0, c)
                self.assertLessEqual(c["similarity"], 1.0, c)
                # Status is decided by the text itself, never by the number:
                # unchanged iff the regulatory text is identical.
                self.assertEqual(
                    c["status"] == "unchanged",
                    c["old_text"] == c["new_text"],
                    c["section"],
                )


if __name__ == "__main__":
    unittest.main()
