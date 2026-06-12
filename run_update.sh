#!/usr/bin/env bash
# Single entry point: refresh the live win-probabilities and rebuild the
# shareable Hebrew page (friends_bet/report/index.html).
#
# Runs the two-step chain in order:
#   1. wc2026_bet/scripts/run_live_pipeline.py --recalibrate
#        -> fetches live ESPN state + odds, runs 50k conditioned sims,
#           writes wc2026_bet/results/live_latest.json (+ report/live.html)
#   2. wc2026_bet/scripts/build_friends_report.py
#        -> injects the win-prob sections into the shareable page
#
# Works locally and in CI. The friends page output path resolves to
# <repo>/friends_bet/report/index.html automatically.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"

cd "$HERE/wc2026_bet"
# extra args are forwarded to the pipeline (e.g. CI passes --skip-collect after
# it has already collected the live state for the change-gate).
"$PYTHON" scripts/run_live_pipeline.py --recalibrate "$@"
"$PYTHON" scripts/build_friends_report.py

echo "Built shareable page -> $HERE/friends_bet/report/index.html"
