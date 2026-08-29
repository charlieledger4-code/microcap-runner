# Phase 2 — 60-Second Falsification / Robustness Result

Date: 2026-08-29

## Purpose

This suite was designed to try to break the initial 60-second result rather than optimize it. The core model was evaluated in four later, non-overlapping chronological windows with expanding historical training data. Additional checks removed price/market-cap features, restricted the model to flow features, evaluated unseen creators, and changed the effective entry path through delays/adverse fills.

This remains a historical price-path study. It is not an executable P&L claim.

## Universe

- 310,111 60-second-eligible tokens with future path data in the stress reconstruction.
- Full source corpus remains the Slinky21 Pump.fun lifecycle corpus.
- Post-graduation price paths use relative USD return anchored to the last pre-graduation price to avoid quote-unit discontinuities.
- System Program/accounting rows are excluded from human-flow features.
- Invalid/inconsistent SOL amounts are excluded from volume features.

## Walk-forward folds

| Fold | Train through | Test through | Test n | Unseen-creator n |
|---|---|---|---:|---:|
| A | 2026-06-25 23:44 UTC | 2026-06-29 11:34 UTC | 30,087 | 14,643 |
| B | 2026-06-29 11:34 UTC | 2026-07-02 11:24 UTC | 29,864 | 14,999 |
| C | 2026-07-02 11:24 UTC | 2026-07-07 15:49 UTC | 30,589 | 16,178 |
| D | 2026-07-07 15:49 UTC | 2026-07-14 15:01 UTC | 59,944 | 27,847 |

Each test begins after a three-hour embargo following its training cutoff.

## Main HGB model: top-1% enrichment by fold

| Target | Fold A | Fold B | Fold C | Fold D | Median lift |
|---|---:|---:|---:|---:|---:|
| 5x | 11.85x | 47.99x | 4.46x | 7.09x | 9.47x |
| 10x | 15.84x | 13.36x | 2.27x | 7.20x | 10.28x |
| 25x | 16.72x | 40.09x | 11.88x | 4.63x | 14.30x |
| 50x | 16.72x | 25.05x | 8.85x | 1.15x | 12.78x |
| 100x | 25.07x | 66.81x | 23.14x | 6.25x | 24.11x |

The lift varies heavily by regime, especially for the rarest targets, but the main 10x and 100x HGB top-1% buckets remained above baseline in all four test windows.

## Aggregated disjoint walk-forward diagnostics

Aggregating the four non-overlapping test windows for descriptive purposes:

| Target | Test population n | Population hits | Top-1% n | Top-1% hits | Population rate | Top-1% rate | Aggregate lift |
|---|---:|---:|---:|---:|---:|---:|---:|
| 5x | 150,484 | 2,411 | 1,502 | 217 | 1.602% | 14.447% | 9.02x |
| 10x | 150,484 | 855 | 1,502 | 51 | 0.568% | 3.395% | 5.98x |
| 25x | 150,484 | 260 | 1,502 | 20 | 0.173% | 1.332% | 7.71x |
| 50x | 150,484 | 131 | 1,502 | 6 | 0.0871% | 0.399% | 4.59x |
| 100x | 150,484 | 52 | 1,502 | 8 | 0.0346% | 0.533% | 15.41x |

A simple fold-aware null calculation for the 100x top-1% result gives about 0.52 expected hits under random ranking versus 8 observed. The nominal tail probability is ~8.1e-8. This is only a diagnostic: token outcomes and market regimes are not guaranteed independent, so this must not be interpreted as a clean iid hypothesis-test p-value.

## Critical downgrade: top-100 instability

The initial held-out split contained 3 future 100x events in the model's top 100. That observation did **not** replicate consistently across the four walk-forward windows.

100x top-100 hits by fold for the main HGB model:

- A: 0 / 100
- B: 2 / 100
- C: 0 / 100
- D: 0 / 100

Therefore the project must **not** use “3/100 hit 100x” as an expected live hit rate. The robust finding is broader top-tail enrichment, especially top 1%, not a stable exact top-100 moonshot frequency.

## Feature ablation

### 10x target

Top-1% lift by fold:

| Model | A | B | C | D | Median |
|---|---:|---:|---:|---:|---:|
| All features HGB | 15.84x | 13.36x | 2.27x | 7.20x | 10.28x |
| No price / market cap HGB | 5.28x | 13.36x | 4.92x | 9.00x | 7.14x |
| Flow-only HGB | 0.00x | 0.00x | 1.51x | 1.98x | 0.76x |
| Unseen-creator all-features HGB | 8.36x | 12.58x | 3.81x | 7.43x | 7.90x |

Interpretation:

- Removing current price/market-cap does **not** destroy the 10x signal. This is important evidence against the edge being only a price-threshold proxy.
- Pure trade-flow features are weak on their own in the early folds. The useful signal appears to require structural/creator/concentration/context features in addition to raw flow.
- The 10x signal survives restriction to creators never seen in the training history in every fold tested.

### 100x target

Top-1% lift by fold:

| Model | A | B | C | D | Median |
|---|---:|---:|---:|---:|---:|
| All features HGB | 25.07x | 66.81x | 23.14x | 6.25x | 24.11x |
| No price / market cap HGB | 25.07x | 0.00x | 23.14x | 6.25x | 14.70x |
| Flow-only HGB | 0.00x | 0.00x | 7.71x | 6.25x | 3.13x |
| Unseen-creator all-features HGB | 33.43x | 0.00x | 37.68x | 7.71x | 20.57x |

Interpretation:

- The full HGB model produced >1x 100x lift in all four folds.
- No-price/no-market-cap and unseen-creator tests each have one zero-hit fold. With only 52 total 100x events across all four test windows, this tail is statistically sparse and must be treated cautiously.
- Flow alone is not sufficient for a reliable 100x detector.
- Logistic regression is materially less stable on the 100x tail than HGB, which is evidence that nonlinear interactions matter or that the tail is too sparse for a simple linear separator.

## Entry-delay stress for 100x path labels

The execution-delay scenario chooses an actual later observable entry price and recomputes the future 100x-before-50%-drawdown label. The model is still trained on the historical 60-second feature panel.

| Scenario | Test n | 100x positives | Base rate | Top-1% rate | Top-1% lift |
|---|---:|---:|---:|---:|---:|
| 0s extra delay | 68,618 | 44 | 0.0641% | 0.5831% | 9.09x |
| +15s delay | 57,418 | 33 | 0.0575% | 0.6969% | 12.13x |
| +30s delay | 49,998 | 32 | 0.0640% | 0.8016% | 12.52x |
| +60s delay | 39,770 | 26 | 0.0654% | 0.2519% | 3.85x |

The non-monotonic 15s/30s lift is caused by sparse outcomes and a changing eligible population, not evidence that intentional delay improves the strategy. The important result is that a full additional minute materially weakens ranking lift.

## Adverse-entry stress for 100x path labels

| Entry penalty | Test n | 100x positives | Base rate | Top-1% rate | Top-1% lift |
|---|---:|---:|---:|---:|---:|
| +5% worse entry | 68,618 | 38 | 0.0554% | 0.5831% | 10.53x |
| +10% worse entry | 68,618 | 35 | 0.0510% | 0.5831% | 11.43x |
| +20% worse entry | 68,618 | 27 | 0.0393% | 0.4373% | 11.11x |

The absolute number of attainable 100x outcomes declines as entry worsens, as expected. Ranking enrichment remains, but this does not yet include real liquidity/fill failure or transaction costs.

## Current fee implication

Pump's documented bonding-curve total fee is 1.25% per trade. Ignoring fixed network/Jito costs, two 1.25% fee haircuts mean the approximate gross chart multiple required merely to realize each net multiple is:

- net 2x -> gross 2.051x
- net 5x -> gross 5.127x
- net 10x -> gross 10.255x
- net 25x -> gross 25.637x
- net 50x -> gross 51.274x
- net 100x -> gross 102.548x

Network/priority fees, Jito tips, slippage, failed transactions and exit impact push these thresholds further upward. Fixed costs matter disproportionately for £1-scale tickets.

## Decision

### What survived

- 10x top-1% enrichment survived all four chronological folds.
- 100x full-feature HGB top-1% enrichment survived all four chronological folds, despite severe sparsity.
- 10x signal survived removing price/market-cap features.
- 10x signal survived unseen-creator restriction.
- moderate execution delay/adverse-entry assumptions did not erase broad 100x ranking enrichment.

### What did not survive strongly enough

- Exact top-100 100x hit counts are unstable.
- Flow-only models are too weak to use alone.
- 100x ablations are sparse enough to have zero-hit folds.
- A 60-second additional delay materially degrades the 100x ranking signal.

## Project status

**The edge is not falsified. It is materially more credible than after the first split, but its reliable form is top-tail enrichment rather than a stable 3%-per-ticket 100x hit rate.**

Next gates:

1. fully fee/slippage/failure-aware execution simulation;
2. freeze a 60-second model/threshold;
3. prospective paper-only candidate logging with no retrospective edits;
4. wallet-cluster and insider-risk enrichment;
5. compare prospective results to matched random controls.
