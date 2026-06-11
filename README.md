# WC 2026 — live win-probability pool tracker

Automatically re-runs a Monte-Carlo simulation of the World Cup twice a day and
publishes a shareable Hebrew report with each pool entry's live win / in-the-money
probabilities, conditioned on results that have already happened.

- **Live page:** deployed to GitHub Pages (`index.html`).
- **History:** every run is archived under `published/winprob_<TS>.html` and listed
  at `…/history/`.

## How it works

Two steps, chained by [`run_update.sh`](run_update.sh):

1. `wc2026_bet/scripts/run_live_pipeline.py --recalibrate`
   fetches the live tournament state from ESPN's keyless feed and refreshes market
   odds, then runs 50,000 conditioned simulations (past results fixed, only the
   remainder sampled), scores all 53 entries and ranks them — writing
   `wc2026_bet/results/live_latest.json`.
2. `wc2026_bet/scripts/build_friends_report.py`
   injects the win-probability sections + champion-conditional matrix +
   data-coverage banner into the shareable page `friends_bet/report/index.html`.

A scheduled [GitHub Actions workflow](.github/workflows/update.yml) runs this at
**22:30, 01:30 and 06:30 UTC** — each just after a daily cluster of matches
finishes (group-stage kickoffs span 16:00–04:00 UTC) — archives the result, and
deploys the latest page to Pages.

## Run it locally

```bash
pip install -r requirements.txt
bash run_update.sh
open friends_bet/report/index.html
```

## Data & privacy notes

- No API keys required for the scheduled job. ESPN's `fifa.world` feed and the
  committed roster CSV are public.
- The Supabase **anon read key** (a public client key) is **not** stored in the
  repo. It is read from the `POOL_SUPABASE_ANON_KEY` environment variable and is
  only needed when re-pulling the roster (`--entries`). To run that locally:
  `export POOL_SUPABASE_ANON_KEY='eyJ...'`. The scheduled win-probability job
  never uses it. (If you ever want `--entries` to run in CI, add it as a GitHub
  Actions secret and expose it via `env:`.)
- The page intentionally shows participants' pool nicknames and their picks.
- Market odds pages are bot-blocked from CI; the pipeline falls back to the
  committed `wc2026_bet/data/raw/*.md` snapshots. Drop in an updated markdown table
  to genuinely move a line.

## Relationship to the source project

This repo is a self-contained, deployable copy of the live-tracker subset of a
larger local analysis project. It deliberately excludes that project's third-party
model repos and any unrelated/private material.

## Maintenance

If the roster changes, re-pull entries locally with
`POOL_SUPABASE_ANON_KEY='eyJ...' python3 wc2026_bet/scripts/run_live_pipeline.py --entries --recalibrate`
and commit the updated `data/live/*.csv`.
