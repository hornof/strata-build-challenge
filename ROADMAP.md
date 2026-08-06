# ROADMAP — build

Six features, one PR each, in order. Tests before code. Checkboxes are ticked in the same commit as the work. Real commit messages, no squash. Append one line per iteration to `LOG.md`.

Decisions already made (do not re-open): app state is JSON · no live URL in this build · a material change with no mapped obligation routes to the director, tagged "material · no mapped obligation — candidate new obligation" · corpus is the three dockets below · component names are the filenames.

---

## F1 — fetcher + corpus

`src/fetcher.py`. Downloads every version of RM22-7-000, RM22-10-000, RM20-16-000 from the Federal Register API into `corpus/<docket>/<date>-<kind>/` (`raw.txt` + `metadata.json`). Append-only: an existing version is never overwritten.

- [x] Kind detection tested: proposed / final / correction — including corrections marked only by a "; Correction" title suffix (the API's `correction_of` is null on RM20-16's)
- [x] Re-running the fetcher changes nothing (append-only test)
- [x] Corpus on disk: 8 documents, 2 of them corrections; every `raw.txt` non-empty
- [x] Downstream pipeline needs no network after this point

## F2 — parser

`src/parser.py` → `sections.json` per version: sections split, regulatory text separated from amendatory instructions; corrections parse to a patch record, not sections. Regression tests written before the code:

- [x] § 50.9 contains no instruction text from § 50.11 (instruction-bleed bug)
- [x] § 380.12 is not a phantom section; its references survive inside § 380.13/380.14 instructions
- [x] An instruction spanning a GPO page break parses as one instruction (page-break bug)
- [x] RM20-16's correction resolves its base version (title/date inference; `correction_of` is null)
- [x] "[Amended]"-only sections: instructions populated, regulatory text empty
- [x] "* * * * *" elision markers preserved in regulatory text
- [x] Same section set across RM22-7's proposed and final (15 sections + authority entries)
- [x] Global guard: no section's regulatory text contains instruction language ("Amend Sec.", "add in its place", "as follows:")
- [x] Full suite green over all 8 documents

## F3 — differ

`src/differ.py` → `changes.json` per docket: per-section records (added / removed / modified / unchanged, old text, new text, similarity), corrections applied as patches to their base version.

- [x] RM22-10 final: zero changed sections, and that renders as valid output, not an error (written before the code)
- [x] added/removed tested as mirror images; modified tested for old/new symmetry
- [x] Correction invariant: applying RM22-7's correction to its base and diffing yields near-zero regulatory-text change; the patch touches instruction text only
- [x] RM22-7 sanity against known ground truth: § 50.4, § 50.5, § 380.16 modified; § 50.2 unchanged; no sections added or removed
- [x] § 50.4's new text contains "Tribal Engagement Plan"; its old text does not
- [x] Similarity in [0,1] on every record; never used as a materiality gate anywhere

## F4 — fixture + judge

`fixtures/company.json` — Cascadia Grid Energy: ~13 obligations (incl. O-013 transmission siting) with descriptions, regulatory basis, named owners; 3 projects (incl. Cascade Crossing) linked to obligations; documents (incl. Siting Playbook §3); deliberate traps — obligations nothing in the corpus touches.

`src/judge.py` — builds the prompt (materiality rules + change record + whole fixture), calls the model, parses strict JSON, runs the safeguards, writes dispositions.

- [x] Strict-JSON parse: malformed model output → unsure, never a crash
- [x] Citation check (code): an invented quote is rejected; a real quote passes after normalization (both directions tested)
- [x] Refuter: second call argues the opposite; a credible refutation flips the change to unsure (exercised via a test recording)
- [x] Record/replay wrapper: request-hash → `recordings/<hash>.json`; replay is deterministic (two runs, identical output); replay-mode miss = clear error naming the `--live` fix
- [x] Pipeline runs end-to-end in replay mode with no API key
- [x] Test recordings are synthetic and labeled as such; real recordings come from the `--live` run (F5, needs the API key)

## F5 — golden set + harness

`eval/golden-set.jsonl` — labeled cases: the nine hand-labeled § 50.4 changes, the binds-another-party traps, adjacent-section traps, the RM22-7 correction (correct answer: silence/non-material), and unsure-labeled cases where escalation IS the right answer. `eval/harness.py` — grades correct / safe / wrong-with-confidence.

- [ ] Harness exits non-zero on any wrong-with-confidence result (verified with a seeded failure)
- [ ] False negatives (material→non-material) and false positives reported separately
- [ ] A case used as a prompt example is excluded from scoring, and that exclusion is tested
- [ ] `--live` run over the corpus with the real key → committed `recordings/`; judge v1 scored on the golden set; score report saved
- [ ] Exact test command documented in README and green

## F6 — app

`src/app.py` — renders the three screens from dispositions + fixture, per `mockups/`: director weekly review (three piles, material as routed status lines, miss rate in footer, sign-the-week → coverage record), owner detail (passage diff, judgment, verified citations, accept / bounce / reassign), metrics. Bounces, rulings, overturns append to app state and the golden set.

- [ ] Two-act demo runs: Act 1 (owner accepts one + bounces one; director rules an unsure, overturns one non-material, signs the week) · Act 2 (harness: judge v1 vs v2 after adding Act-1 cases; correction closer renders "seen, non-material: cross-reference typo")
- [ ] Coverage record: every corpus change dispositioned, by whom, when, on what basis
- [ ] Exact end-to-end run command documented in README and clean on a fresh clone
- [ ] Screens match the mockups (screenshot review before human review)

---

## Halt conditions

Stop and write down why in `LOG.md` + the mailbox when: all features accepted · OR 3 consecutive iterations with no test improvement · OR a feature needs a decision not listed above (skip to the next independent feature if possible, else stop). Never weaken or delete a test to make it pass. If the API key is absent when F5 needs it, finish everything replay/synthetic, flag it, and continue — the `--live` recording run moves to the morning.
