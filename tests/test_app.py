"""F6 tests — the app. Written before src/app.py.

The app renders the three screens from dispositions + fixture and supports the
weekly-review actions. Dispositions come from replaying the committed recordings,
so these tests need no key or network.

Run with zero setup:

    python3 -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

import judge  # noqa: E402
import harness  # noqa: E402
import app  # noqa: E402

FIXTURE = judge.load_fixture()
GOLDEN = harness.load_golden(ROOT / "eval" / "golden-set.jsonl")
RECORDINGS = ROOT / "recordings"


class Routing(unittest.TestCase):

    def test_material_routes_to_the_obligations_named_owner(self):
        disp = {"classification": "material", "affected_obligations": ["O-013"]}
        r = app.route(disp, FIXTURE)
        self.assertEqual(r["owner"], "Dana Kim")
        self.assertEqual(r["owner_role"], "Permitting Lead")

    def test_material_with_no_mapped_obligation_routes_to_director_backstop(self):
        # Luke's N1 ruling: the change nobody thought to look for.
        disp = {"classification": "material", "affected_obligations": []}
        r = app.route(disp, FIXTURE)
        self.assertEqual(r["owner"], "director")
        self.assertIn("candidate new obligation", r["tag"])


class Week(unittest.TestCase):

    def setUp(self):
        self.week = app.build_week(GOLDEN, FIXTURE, RECORDINGS)

    def test_three_piles_cover_every_scored_change(self):
        c = self.week["counts"]
        self.assertEqual(c["material"] + c["unsure"] + c["non_material"], self.week["total"])
        self.assertGreater(c["material"], 0)
        self.assertGreater(c["non_material"], 0)

    def test_materials_are_routed_to_a_named_owner(self):
        for m in self.week["material"]:
            self.assertTrue(m["route"]["owner"], m["disposition"]["section"])


class DirectorScreen(unittest.TestCase):

    def test_renders_piles_owner_line_missrate_and_signoff(self):
        week = app.build_week(GOLDEN, FIXTURE, RECORDINGS)
        html = app.render_director(week, app.new_state())
        self.assertIn("Dana Kim", html)          # a routed material owner
        self.assertIn("material", html)
        self.assertIn("miss rate", html.lower())
        self.assertIn("Sign the week", html)


class OwnerScreen(unittest.TestCase):

    def test_renders_diff_verified_citations_and_actions(self):
        week = app.build_week(GOLDEN, FIXTURE, RECORDINGS)
        tep = next(m for m in week["material"] if m["disposition"]["section"] == "50.4")
        html = app.render_owner(tep, FIXTURE)
        self.assertIn("Tribal Engagement Plan", html)   # the new passage
        self.assertIn("verified", html.lower())         # citation check result
        for action in ("Accept", "Bounce", "Reassign"):
            self.assertIn(action, html)


class MetricsScreen(unittest.TestCase):

    def test_renders_two_dials(self):
        html = app.render_metrics()
        self.assertIn("Trust", html)
        self.assertIn("Automation", html)


class Actions(unittest.TestCase):

    def test_bounce_rule_overturn_append_labeled_cases(self):
        state = app.new_state()
        bounced = app.bounce(state, "35.28", "applies to Basin, not this siting scope")
        self.assertEqual(bounced["label"], "non-material")
        self.assertEqual(bounced["split"], "test")

        ruled = app.rule(state, "380.16", "non-material")
        self.assertEqual(ruled["label"], "non-material")

        overturned = app.overturn(state, "50.1", "material")
        self.assertEqual(overturned["label"], "material")

        # All three land in app state's growing golden-set additions.
        self.assertEqual(len(state["golden_additions"]), 3)


class Coverage(unittest.TestCase):

    def test_sign_the_week_records_every_change_with_who_when_basis(self):
        week = app.build_week(GOLDEN, FIXTURE, RECORDINGS)
        state = app.new_state()
        record = app.sign_week(week, state, when="2026-08-16", by="Director")
        self.assertEqual(len(record["dispositions"]), week["total"])
        for row in record["dispositions"]:
            self.assertTrue(row["by"] and row["on"] and row["basis"] and row["section"])
        self.assertEqual(record["coverage"], "100%")


class HonestyCloser(unittest.TestCase):

    def test_correction_closer_is_seen_non_material_cross_reference(self):
        week = app.build_week(GOLDEN, FIXTURE, RECORDINGS)
        closer = app.correction_closer(week)
        self.assertIn("seen, non-material", closer.lower())
        self.assertIn("cross-reference", closer.lower())


if __name__ == "__main__":
    unittest.main()
