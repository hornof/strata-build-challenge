# Strata

A regulatory change-intelligence workspace: turn successive versions of a regulatory
proceeding into cited, reviewable actions against a company's own obligations.

See [PRD.md](PRD.md) for the product and [TDD.md](TDD.md) for the design. Build progress
is tracked in [ROADMAP.md](ROADMAP.md) and [LOG.md](LOG.md).

## The pipeline

```
fetcher → parser → differ → judge → app        offline: golden set → harness
(plain code, deterministic)  (the model)  (screens)   (scores the judge)
```

- **`src/fetcher.py`** — downloads every version of a proceeding from the Federal
  Register API into `corpus/` (append-only).
- **`src/parser.py`** — splits each version into sections, separating regulatory text
  from amendatory instructions.
- **`src/differ.py`** — diffs the proposed → final chain into per-section change records.
- **`src/judge.py`** — the only model call: classifies each change material /
  non-material / unsure against `fixtures/company.json`, with a code citation check and
  a refuter. Records responses and **replays them by default — no API key needed.**
- **`eval/`** — the golden set of labeled cases and the harness that scores the judge.

## Tests

Zero setup — standard-library `unittest`, no third-party packages, no network:

```bash
python3 -m unittest discover -s tests
```

## Scoring the judge

Replay the recorded judge responses and score them against the golden set:

```bash
python3 eval/harness.py
```

This writes `eval/score-report.md` and exits non-zero if any change was judged
**wrong-with-confidence** (a definite answer that disagrees with the label). It needs
the recordings produced by a `--live` run.

To (re-)record against the real model — needs `anthropic` installed and
`ANTHROPIC_API_KEY` set (a `.env` at the repo root is read automatically):

```bash
python3 eval/harness.py --live      # calls the model, records to recordings/, then scores
```

## The app and the demo

Render the three screens (director weekly review, owner detail, metrics) to `app/`:

```bash
python3 src/app.py
```

Run the two-act demo — Act 1 (the week: accept, bounce, rule, overturn, sign the
coverage record) and Act 2 (the eval: judge v1 vs v2, and the correction closer):

```bash
python3 src/app.py demo
```

Everything above runs on a fresh clone with only Python's standard library — the
recorded judge responses replay deterministically, no API key or install needed.
