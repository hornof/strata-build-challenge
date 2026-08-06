"""F1 tests — fetcher + corpus.

Run with zero setup (stdlib unittest, no network):

    python3 -m unittest discover -s tests

These are written before src/fetcher.py and the corpus exist; they fail until
F1 lands. Kind detection and append-only are exercised as pure/offline logic;
the corpus checks read the committed files on disk. Nothing here touches the
network.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import fetcher  # noqa: E402  (path set above)

CORPUS = ROOT / "corpus"

# The three dockets the corpus is built from, and how many published versions
# each has. Ground truth, asserted so a dropped or duplicated version is loud.
EXPECTED_VERSIONS = {
    "RM22-7-000": 3,   # proposed, final, correction
    "RM22-10-000": 2,  # proposed, final
    "RM20-16-000": 3,  # proposed, correction, final
}
EXPECTED_DOCS = sum(EXPECTED_VERSIONS.values())      # 8
EXPECTED_CORRECTIONS = 2                              # RM22-7 + RM20-16


class KindDetection(unittest.TestCase):
    """kind_of maps an API document to proposed / final / correction."""

    def _doc(self, **over):
        base = {
            "type": "Rule",
            "document_number": "2024-11111",
            "title": "Managing Transmission Line Ratings",
            "correction_of": None,
        }
        base.update(over)
        return base

    def test_proposed(self):
        self.assertEqual(fetcher.kind_of(self._doc(type="Proposed Rule")), "proposed")

    def test_final(self):
        self.assertEqual(fetcher.kind_of(self._doc(type="Rule")), "final")

    def test_correction_via_correction_of(self):
        self.assertEqual(
            fetcher.kind_of(self._doc(correction_of="2024-00001")), "correction"
        )

    def test_correction_via_document_number_prefix(self):
        self.assertEqual(
            fetcher.kind_of(self._doc(document_number="C1-2021-00001")), "correction"
        )

    def test_correction_via_title_suffix_when_correction_of_null(self):
        # The RM20-16 case: the API's correction_of is null and the type is Rule;
        # only the "; Correction" title suffix marks it. Missing this would file
        # a correction as a final rule and corrupt the diff chain.
        doc = self._doc(
            type="Rule",
            correction_of=None,
            title="Managing Transmission Line Ratings; Correction",
        )
        self.assertEqual(fetcher.kind_of(doc), "correction")


class AppendOnly(unittest.TestCase):
    """A fetched version is never overwritten; re-running changes nothing."""

    def test_existing_raw_is_not_overwritten_and_not_refetched(self):
        doc = {
            "type": "Rule",
            "document_number": "2024-11111",
            "publication_date": "2024-05-29",
            "effective_on": "2024-07-29",
            "correction_of": None,
            "title": "Managing Transmission Line Ratings",
            "citation": "89 FR 12345",
            "html_url": "https://example.gov/doc",
            "raw_text_url": "https://example.gov/doc/raw",
        }
        calls = []

        def fake_fetch_text(url):
            calls.append(url)
            return f"VERSION-{len(calls)}"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # First write: fetches and writes VERSION-1.
            wrote_first = fetcher.write_document(doc, "RM22-7-000", root, fake_fetch_text)
            self.assertTrue(wrote_first)
            raw = root / "RM22-7-000" / "2024-05-29-final" / "raw.txt"
            self.assertEqual(raw.read_text(), "VERSION-1")

            # Second write: must skip — no overwrite, no second network call.
            wrote_second = fetcher.write_document(doc, "RM22-7-000", root, fake_fetch_text)
            self.assertFalse(wrote_second)
            self.assertEqual(raw.read_text(), "VERSION-1")
            self.assertEqual(len(calls), 1, "append-only fetcher re-fetched an existing version")


class CorpusOnDisk(unittest.TestCase):
    """The committed corpus is complete and downstream needs no network."""

    def version_dirs(self):
        return sorted(p for p in CORPUS.glob("*/*") if p.is_dir())

    def test_eight_documents_every_raw_non_empty(self):
        dirs = self.version_dirs()
        self.assertEqual(len(dirs), EXPECTED_DOCS, "expected 8 published documents")
        for d in dirs:
            raw = d / "raw.txt"
            self.assertTrue(raw.is_file(), f"{d} missing raw.txt")
            self.assertGreater(raw.stat().st_size, 0, f"{d}/raw.txt is empty")

    def test_two_corrections(self):
        corrections = [
            d for d in self.version_dirs()
            if json.loads((d / "metadata.json").read_text())["kind"] == "correction"
        ]
        self.assertEqual(len(corrections), EXPECTED_CORRECTIONS)

    def test_expected_dockets_and_version_counts(self):
        for docket, n in EXPECTED_VERSIONS.items():
            got = sorted((CORPUS / docket).glob("*"))
            got = [p for p in got if p.is_dir()]
            self.assertEqual(len(got), n, f"{docket}: expected {n} versions")

    def test_metadata_matches_folder_and_is_downstream_complete(self):
        # Folder name is <publication_date>-<kind>, and metadata carries every
        # field the rest of the pipeline reads — so nothing downstream re-fetches.
        needed = {"docket", "kind", "publication_date", "effective_on", "correction_of"}
        for d in self.version_dirs():
            meta = json.loads((d / "metadata.json").read_text())
            self.assertTrue(needed.issubset(meta), f"{d} metadata missing {needed - set(meta)}")
            self.assertEqual(d.name, f"{meta['publication_date']}-{meta['kind']}")

    def test_rm20_16_correction_has_null_correction_of(self):
        # The tricky one: this correction is only identifiable by its title suffix.
        meta = json.loads(
            (CORPUS / "RM20-16-000" / "2021-04-22-correction" / "metadata.json").read_text()
        )
        self.assertEqual(meta["kind"], "correction")
        self.assertIsNone(meta["correction_of"])


if __name__ == "__main__":
    unittest.main()
