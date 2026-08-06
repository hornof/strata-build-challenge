"""F2 tests — parser. Frozen regression cases, written before the code.

Rule: every parser bug found on a real document becomes a test here BEFORE the
code that fixes it, so a later change can't silently re-break a document that
used to work. The first cases are the investigation bugs named in the roadmap.

Run with zero setup, no network:

    python3 -m unittest discover -s tests
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import parser  # noqa: E402

CORPUS = ROOT / "corpus"
RM227 = CORPUS / "RM22-7-000"
RM2016 = CORPUS / "RM20-16-000"
RM2210 = CORPUS / "RM22-10-000"

INSTRUCTION_MARKERS = ("Amend Sec.", "add in its place", "as follows:")


def norm(text):
    """Collapse all whitespace to single spaces — for matching across line wraps."""
    return " ".join(text.split())


def sections(vdir):
    r = parser.parse(vdir)
    return {s["id"]: s for s in r["sections"]}


class InstructionBleed(unittest.TestCase):
    """The two kinds of text must never cross a section boundary."""

    def test_50_9_does_not_absorb_50_11_instruction(self):
        # Investigation bug: Sec. 50.11's instruction header bled across the
        # heading into Sec. 50.9's text, faking a 105-word change to notice rules.
        s = sections(RM227 / "2024-05-29-final")
        self.assertNotIn("Amend", s["50.9"]["regulatory_text"])
        self.assertNotIn("50.11", s["50.9"]["regulatory_text"])
        self.assertTrue(s["50.11"]["regulatory_text"], "50.11 should still have its own text")

    def test_no_regulatory_text_contains_instruction_language(self):
        # Global guard for the whole bug class, over both RM22-7 versions.
        for vdir in (RM227 / "2023-01-17-proposed", RM227 / "2024-05-29-final"):
            for sid, s in sections(vdir).items():
                for marker in INSTRUCTION_MARKERS:
                    self.assertNotIn(
                        marker, s["regulatory_text"], f"{vdir.name} {sid} leaked {marker!r}"
                    )


class PhantomSection(unittest.TestCase):
    """§ 380.12 is referenced but never amended in this proceeding."""

    def test_380_12_is_a_reference_not_a_section(self):
        s = sections(RM227 / "2024-05-29-final")
        self.assertNotIn("380.12", s)  # not a phantom section
        # Its references survive inside the sections that DO amend around it.
        self.assertIn("380.12", s["380.13"]["amendatory_instructions"])
        self.assertIn("380.12", s["380.14"]["amendatory_instructions"])


class PageBreak(unittest.TestCase):
    """A GPO page break landing mid-instruction must not split it.

    In RM22-7's final, instruction 17.c ("Amend Sec. 380.16 ... Revise
    paragraphs (e)(2) and (3) ... paragraph (e)(5), and revise paragraph
    (e)(6)") is cut by `[[Page 46735]]`. Left unstitched, the tail falls out of
    the instruction and leaks into the previous section's (380.14) regulatory
    text, because the section pointer is stale. The instruction belongs whole to
    380.16, and nothing may leak.
    """

    def test_split_instruction_stays_one_instruction_in_correct_section(self):
        s = sections(RM227 / "2024-05-29-final")
        self.assertIn(
            "the first and third sentences of paragraph (e)(5), and revise paragraph (e)(6)",
            norm(s["380.16"]["amendatory_instructions"]),
        )

    def test_no_instruction_tail_leaks_into_regulatory_text(self):
        for sid, s in sections(RM227 / "2024-05-29-final").items():
            self.assertNotIn(
                "revise paragraph (e)(6)", s["regulatory_text"], f"leak into {sid}"
            )


class AmendedOnlyAndElision(unittest.TestCase):

    def test_amended_only_section_has_instructions_but_no_law_text(self):
        # Sec. 50.2 "[Amended]" is word-replacement instructions only.
        s = sections(RM227 / "2024-05-29-final")
        self.assertEqual(s["50.2"]["title"], "[Amended]")
        self.assertIn("Tribes", s["50.2"]["amendatory_instructions"])
        self.assertEqual(s["50.2"]["regulatory_text"], "")

    def test_elision_markers_preserved(self):
        # "* * * * *" means "unchanged text omitted" and must reach the differ.
        s = sections(RM227 / "2024-05-29-final")
        self.assertIn("* * * * *", s["50.4"]["regulatory_text"])

    def test_tribal_engagement_plan_is_new_in_final_50_4(self):
        final = sections(RM227 / "2024-05-29-final")
        proposed = sections(RM227 / "2023-01-17-proposed")
        self.assertIn("Tribal Engagement Plan", final["50.4"]["regulatory_text"])
        self.assertNotIn("Tribal Engagement Plan", proposed["50.4"]["regulatory_text"])


class SectionSet(unittest.TestCase):

    def test_same_section_set_across_versions_15_plus_authority(self):
        a = set(sections(RM227 / "2023-01-17-proposed"))
        b = set(sections(RM227 / "2024-05-29-final"))
        self.assertEqual(a, b, "a section was added or dropped between versions")
        self.assertEqual(len([x for x in a if "authority" not in x]), 15)


class Corrections(unittest.TestCase):

    def test_rm22_7_correction_parses_to_patch_not_sections(self):
        r = parser.parse(RM227 / "2024-06-03-correction")
        self.assertEqual(r["kind"], "correction")
        self.assertTrue(r["targets_instructions"])
        self.assertEqual(r["replacements"], [{"old": "paragraph I", "new": "paragraph (e)"}])

    def test_rm22_7_correction_base_version_from_correction_of(self):
        r = parser.parse(RM227 / "2024-06-03-correction")
        self.assertEqual(r["base_version"], "2024-05-29-final")

    def test_rm20_16_correction_base_version_inferred_when_correction_of_null(self):
        # correction_of is null; the base is resolved by date — the most recent
        # non-correction version published on or before the correction. That is
        # the proposed rule (2021-01-21), not the later final (2022-01-13).
        meta = json.loads((RM2016 / "2021-04-22-correction" / "metadata.json").read_text())
        self.assertIsNone(meta["correction_of"])
        r = parser.parse(RM2016 / "2021-04-22-correction")
        self.assertEqual(r["kind"], "correction")
        self.assertEqual(r["base_version"], "2021-01-21-proposed")


class WholeCorpus(unittest.TestCase):

    def test_rm22_10_final_amends_no_cfr_text(self):
        # A real case: this final rule approves a standard by reference and
        # amends no CFR text. Zero sections is correct; inventing sections fails.
        r = parser.parse(RM2210 / "2023-06-23-final")
        self.assertEqual(r["sections"], [])

    def test_parse_runs_over_all_eight_documents(self):
        vdirs = sorted(p.parent for p in CORPUS.glob("*/*/raw.txt"))
        self.assertEqual(len(vdirs), 8)
        for vdir in vdirs:
            r = parser.parse(vdir)
            if r["kind"] == "correction":
                self.assertIn("base_version", r)
            else:
                self.assertIsInstance(r["sections"], list)
                for s in r["sections"]:
                    self.assertEqual(
                        set(s), {"id", "title", "regulatory_text", "amendatory_instructions"}
                    )


if __name__ == "__main__":
    unittest.main()
