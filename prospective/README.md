# Prospective evidence ledger

This branch is an append-only evidence store for observations generated **after** model/policy freeze.

Rules:

- No model training reads this branch.
- Every scan records all observed launches, including REJECT and DATA_INVALID rows.
- Scores remain raw ranking scores, not calibrated probabilities.
- Decision timestamp, model hash, feature contract, RPC completeness and scanner version are retained.
- Outcomes are attached later without rewriting the original decision record.
- Touched reserve-price targets are not called executable fills.
- Real-money execution is not authorized by this ledger.

Scheduled scanners write one immutable directory per GitHub run under `prospective/scans/`. Outcome tracking writes separate records under `prospective/outcomes/` so the original scan cannot be retrospectively altered.
