# ULTIMATE MODE — Forward Evidence Configuration

Status: enabled for paper/research evidence production. No signing or real-money execution is authorized.

## Frozen prediction policy

- Decision age: observer receipt + 60 seconds.
- Champion: `models/livecore60_v1`.
- Primary target/rank: 10x score.
- Frozen Q95/Q99/Q99.5/Q99.9 thresholds remain unchanged during the forward batch.
- Champion model hashes are verified before every scanner run.
- No adaptive retraining, threshold movement, or retrospective veto is permitted from prospective outcomes.
- The failed hard adversarial veto remains diagnostic-only.

## High-throughput production lane

Workflow: `prospective-highthroughput-live60`.

- Schedule: every two hours at minute 05.
- Scheduled capture window: 3,000 seconds.
- Maximum launches per run: 5,000.
- Every observed launch is scored at the immutable 60-second boundary from the direct Solana Pump event stream.
- Full action-time normalized tapes and raw decoded Pump events are retained in the 90-day forensic artifact.
- Permanent ledger stores compact population scores for every launch and full details only for the outcome-independent audited subset.

### Audit subset

Selected before RPC truth lookup and before outcomes:

- all champion PAPER_CANDIDATE / PAPER_PRIORITY names up to the declared per-run cap;
- deterministic random controls sampled from the entire population independent of score;
- deterministic near-miss controls below Q95;
- sampled WATCH names;
- a small deterministic reject-quality sample.

Audit version: `ht_signature_index_missing_only_v2`.

- Confirmed Solana signature history is the completeness index.
- Raw Pump events already seen live are reused only when their signatures appear in confirmed history.
- `getTransaction` is requested only for missing signatures.
- Repeated signature sweeps must stabilize.
- Signature-index cap hits fail closed.
- Accounting fraction must be >= 98%.
- Failed/incomplete rows are `DATA_INVALID` and cannot enter performance claims.

## Drift monitor

- Uses all action-time population scores, not only candidates.
- Frozen-threshold occupancy is diagnostic only.
- Zero-human-trade price/path missingness is classified as structural, not pipeline drift.
- No regime call is made before the declared minimum sample.
- Drift can stop/degrade trust in the experiment; it cannot retrain the model or move thresholds automatically.

## Outcome lane

Workflow: `prospective-executable-outcomes`.

- Alternates with the high-throughput capture hours under the shared append-only ledger lock.
- Tracks 1h / 6h / 24h executable outcomes for preselected candidates, WATCH names and controls.
- Solana transaction requests overlap with bounded concurrency while a shared pacer limits request starts.
- Pump and PumpSwap observed prices remain separate from executable exit values.
- Incomplete history is retained explicitly as `OUTCOME_INCOMPLETE`, never silently deleted.
- Invalid historical zero-fee entry quotes remain quarantined.

## Reference sentinel

The smaller v4 scanner remains enabled on a reduced six-hour cadence as an independent reference lane. It is not allowed to overwrite or replace the high-throughput evidence population.

## Forward gates

The experiment is sample-gated rather than anecdote-gated.

- Interim evidence gate: 10,000 prospective launches plus sufficient matured audited candidates/controls.
- Primary evidence gate: 50,000 prospective launches plus a substantial matured Q99 candidate/control population.
- Results are evaluated on executable outcomes, candidate-vs-random enrichment, confidence intervals, incomplete-rate, liquidity limits, latency and regime stability.
- Individual spectacular winners or losers cannot promote/kill the policy by themselves.
- Passing a gate does not automatically authorize real-money execution.

## Change control

During the forward batch, permitted changes are limited to versioned collection/execution bug fixes and infrastructure improvements that do not use future outcomes to alter selection. Any affected historical prospective records are preserved and quarantined/version-labelled rather than rewritten.
