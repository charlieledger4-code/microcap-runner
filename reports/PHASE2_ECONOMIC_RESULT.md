# Phase 2 — First Held-Out Economic Tail Result

Date: 2026-08-29

## Status

This is the first real historical economic-tail result from the Slinky21 Pump.fun lifecycle corpus. It is **not** yet a claim of executable profit. It is a leakage-aware historical price-path ranking test.

Dataset scale used by the hardened v2 run:

- 33,581,765 trade rows
- 622,870 traded mints
- fixed decision ages: 30s, 60s, 120s, 180s, 300s, 600s
- targets: 2x, 5x, 10x, 25x, 50x, 100x before a 50% drawdown
- chronological train/test separation with a three-hour embargo
- dead/failing tokens retained
- System Program/accounting rows excluded from human-flow features
- invalid/inconsistent SOL amount rows excluded from volume features
- post-graduation returns stitched using USD-relative return anchored to the last valid pre-graduation price, avoiding quote-unit discontinuity artifacts

## 60-second headline

Held-out test population at 60 seconds: 191,770 eligible tokens.

| Target | Population rate | Top 1% rate | Top 1% lift | Top 100 hits |
|---|---:|---:|---:|---:|
| 2x | 5.4795% | 41.2624% | 7.53x | 69 |
| 5x | 1.2009% | 10.0678% | 8.38x | 35 |
| 10x | 0.4406% | 3.9124% | 8.88x | 2 |
| 25x | 0.1351% | 1.5128% | 11.20x | 3 |
| 50x | 0.0667% | 0.8868% | 13.29x | 2 |
| 100x | 0.0250% | 0.4695% | 18.76x | 3 |

For the 100x target specifically:

- 48 / 191,770 held-out eligible tokens hit 100x before -50%.
- HGB top 1% contained 9 / 1,917 hits: 18.76x enrichment.
- HGB top 0.1% contained 3 / 191 hits: 62.75x enrichment.
- Logistic regression top 1% contained 5 / 1,917 hits: 10.42x enrichment.
- The simple hand heuristic failed on the 100x tail; its top 1% contained zero 100x hits. This is useful evidence that the ML result is not merely the hand score in disguise.

Approximate 95% Wilson intervals:

- population 100x rate: 0.0189%–0.0332%
- HGB top-1% 100x rate: 0.2472%–0.8899%
- HGB top-0.1% 100x rate: 0.5356%–4.5154%

The extreme-tail confidence interval is wide because there are few 100x events. Therefore the exact 3/100 observation must not be treated as a stable hit-rate estimate.

## £1 x 100 path diagnostic

The historical top-100 path policy for the 60-second / 100x model produced:

- start: 100 stake units
- end: 369.06 units
- mean terminal multiple under the simplified policy: 3.6906x

This diagnostic excludes fill failures, true quote depth, protocol/network fees, priority fees, Jito tips, adverse selection and real exit liquidity. It is a research signal only.

## Execution costs that must be modeled next

Pump.fun currently states a 1.25% total fee on bonding-curve trades. Canonical PumpSwap fees vary by market-cap tier and can also begin around 1.25% for the lowest SOL-denominated tier. Source: https://pump.fun/docs/fees

Solana transactions also pay a base fee plus optional priority fee. The priority fee depends on requested compute-unit limit and compute-unit price. Source: https://solana.com/docs/core/fees/fee-structure

Jito low-latency submission may additionally require/benefit from a tip; bundle auctions are competitive and a submitted bundle is not guaranteed to land. Source: https://docs.jito.wtf/lowlatencytxnsend/

Accordingly, the next execution-aware simulator must include at least:

1. protocol fee on entry and exit;
2. observed/estimated priority fee;
3. Jito tip where applicable;
4. quote-to-fill delay;
5. adverse fill / slippage;
6. failed transaction probability and wasted fees;
7. exit liquidity and price impact at the chosen ticket size.

## Robustness gate

The first chronological holdout is encouraging but not sufficient. A separate 60-second falsification suite is being used to test:

- expanding chronological folds;
- unseen creators;
- removal of price/market-cap features;
- flow-only models;
- logistic vs gradient boosting;
- 15/30/60-second execution delays;
- 5/10/20% adverse entry fills.

The project should be downgraded if the 10x/100x lift vanishes on later folds, unseen creators, or no-price/no-market-cap ablations.

## Decision

**Continue research. Do not enable real-money execution.**

The first held-out result is strong enough to justify stress testing, execution modeling and prospective paper trading, but the extreme 100x tail remains sparse and must survive independent robustness checks before any trading claim is made.
