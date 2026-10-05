#!/usr/bin/env bash
# CityPulse — one entry point for every stage of the platform.
#
#   ./run.sh setup        create .venv and install Python dependencies
#   ./run.sh ingest       batch sources once: live feeds snapshot, 7 days of traffic, DVF sales, OSM amenities
#   ./run.sh collect      live collectors (Vélib', air quality, traffic), polling every 60 s until Ctrl-C
#   ./run.sh pipeline     PySpark medallion: bronze → silver → gold
#   ./run.sh ontology     build the city ontology + JSON-LD (SOSA/SSN, schema.org) export
#   ./run.sh valuation    train the valuation model, then value the property inventory
#   ./run.sh chain        compile + deploy contracts on Anvil, tokenize, seed the market, index back
#   ./run.sh all          ingest → pipeline → ontology → valuation → chain
#   ./run.sh dashboard    Reflex dev server on http://localhost:3000
#   ./run.sh public       public demo through Tailscale Funnel (see dashboard/serve_public.sh)
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python
export PYTHONPATH=src

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
py()   { "$PY" -m "$@"; }

setup() {
    step "setup"
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
}

ingest() {
    step "ingest"
    py smartcity.ingest.runner --once
    py smartcity.ingest.traffic --hours 168
    py smartcity.ingest.dvf
    py smartcity.ingest.amenities
}

collect() {
    step "live collectors (Ctrl-C to stop)"
    py smartcity.ingest.runner --loop 60
}

pipeline() {
    step "pipeline"
    py smartcity.pipeline.bronze_to_silver
    py smartcity.pipeline.silver_to_gold
}

ontology() {
    step "ontology"
    py smartcity.ontology.build
    py smartcity.ontology.export_jsonld
}

valuation() {
    step "valuation"
    py smartcity.valuation.train
    py smartcity.valuation.listings
}

chain() {
    step "tokenization"
    command -v forge >/dev/null || { echo "Foundry not found: https://getfoundry.sh"; exit 1; }
    (cd chain && forge build)
    # Anvil persists the chain to its state file on exit.
    anvil --state data/chain/anvil-state.json --chain-id 31337 --silent &
    anvil_pid=$!
    trap 'kill "$anvil_pid" 2>/dev/null; wait "$anvil_pid" 2>/dev/null || true' EXIT
    sleep 2
    py smartcity.tokenization.deploy
    py smartcity.tokenization.tokenize --grades A B --limit 24
    py smartcity.tokenization.market --seed
    py smartcity.tokenization.index
    py smartcity.ontology.build    # chain state → ontology
    kill "$anvil_pid"; wait "$anvil_pid" 2>/dev/null || true
    trap - EXIT
}

dashboard() {
    step "dashboard → http://localhost:3000"
    cd dashboard && exec ../.venv/bin/reflex run
}

public() {
    exec dashboard/serve_public.sh "$@"
}

case "${1:-}" in
    setup|ingest|collect|pipeline|ontology|valuation|chain|dashboard) "$1" ;;
    public) shift; public "$@" ;;
    all) ingest; pipeline; ontology; valuation; chain ;;
    *) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
