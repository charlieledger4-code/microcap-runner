# Microcap Early-Runner Research System

Research-first Solana microcap/memecoin discovery stack. The project objective is **extreme-tail enrichment**: rank very young launches so the top fraction contains materially more future large runners than a matched random population, after execution costs and failure/rug risk.

This repository is intentionally **paper-only**. It contains no private-key handling and no automatic real-money execution.

## What exists now

- Raw Solana `logsSubscribe` collectors for Pump, PumpSwap and Meteora DBC program activity.
- Signature-to-`getTransaction` enrichment plus minimal Pump Anchor instruction classification (`create`, `create_v2`, `buy`, `buy_v2`, `sell`, `sell_v2`, `migrate`).
- Optional PumpPortal new-token/migration mirror for low-friction discovery redundancy.
- DEX Screener and Birdeye enrichment clients.
- SQLite research schema covering tokens, pools, trades, snapshots, wallet graph, predictions, outcomes, paper trades and ingestion health.
- Rolling microstructure/acceleration features.
- Wallet concentration and Bayesian skill primitives.
- First-passage labels such as target-before-drawdown.
- Constant-product execution primitives and equal-ticket paper-basket accounting.
- Extreme-tail evaluation: precision@K, enrichment, tail recall and matched-random intervals.
- Leakage guards, including separate completion-benchmark proxy exclusions and economic-model rules.
- Explicit quality guards for known Slinky21 corpus issues.
- Historical dataset acquisition scripts.
- Chronological logistic-regression baseline for the recent point-in-time completion benchmark.

## Architecture

```text
Solana program logs / provider tx stream
              |                 optional discovery mirror
              |                         |
              +------ raw append-only event store <------ PumpPortal
                               |
                         deterministic decoder
                               |
                 tokens / trades / curve state
                               |
              +----------------+----------------+
              |                                 |
      wallet/creator graph                 vendor enrichment
              |                         Birdeye / DEX Screener
              +----------------+----------------+
                               |
                    point-in-time snapshots
                               |
                feature + admissibility engine
                               |
             Moonshot / Ignition / Runner models
                               |
                  calibrated probability layer
                               |
                 execution-aware EV ranking
                               |
                    paper-trade experiments
                               |
             matched random + heuristic controls
```

Raw chain is the truth layer. Vendor fields are enrichment/audit inputs and must retain source/timestamp lineage. Pump v2 fields such as token program, quote mint, quote token program and launch mode are preserved rather than assuming every launch is legacy SPL/SOL-only.

## Three model regimes

- **Moonshot:** 0–120 seconds. Maximum convexity, maximum uncertainty.
- **Ignition:** 120–600 seconds. Priority regime; detect organic acceleration before broad repricing.
- **Runner:** 600–3600 seconds. More confirmation, less remaining convexity.

## Initial economic labels

For each decision timestamp and horizon, derive executable-path labels including:

- 2x before -25%
- 2x before -50%
- 5x before -50%
- 10x before -50%
- 25x before -50%
- 50x before -50%
- 100x before -50%

The eventual economic labels must be generated from **execution-adjusted paths**, not theoretical candle highs.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
make init
make test
```

Start a raw standard-RPC log collector:

```bash
SOLANA_WSS_URL=wss://YOUR_ENDPOINT PYTHONPATH=. \
python -m src.ingest.solana_ws --out data/raw/solana_logs.jsonl
```

Optional PumpPortal discovery mirror:

```bash
PYTHONPATH=. python -m src.ingest.pumpportal --out data/raw/pumpportal_events.jsonl
```

Fetch the recent point-in-time benchmark when network access is available:

```bash
make fetch-forward
PYTHONPATH=. python -m src.models.baseline \
  data/raw/trenches_forward_2026_08/features.parquet \
  data/raw/trenches_forward_2026_08/labels.parquet \
  data/raw/trenches_forward_2026_08/split.json
```

That baseline predicts **bonding-curve completion**, not trading return. It exists to validate chronology, leakage controls and ranking methodology before economic labels are built.

## £1 x 100 experiment

The live experiment is not launched until the selection rule and exit rule are pre-registered. At minimum it compares:

1. Model top-ranked 100 launches × £1 paper tickets.
2. 100 matched-random launches × £1.
3. 100 simple-momentum-screen launches × £1.

All three use identical entry latency, fees, slippage and exit machinery.

## Non-negotiable rules

- No future-derived features.
- Every feature has a derivability timestamp or explicit source cutoff.
- Chronological validation only.
- Dead/rugged launches stay in the dataset.
- No market-wide claim from a curated vendor feed.
- No peak-return claim without executable-liquidity simulation.
- Wallet counts are not assumed to equal independent actors.
- Vendor insider/sniper/smart-wallet tags are hypotheses until audited against chain data.
- Negative results are retained.

See `reports/PHASE1_RESEARCH.md` and `reports/DATA_INVENTORY.md`.
