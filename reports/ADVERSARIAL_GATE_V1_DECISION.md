# Adversarial gate v1 — historical decision

Policy: `adv_gate_v1_20260829`

Historical workflow: GitHub Actions run `33261646892`.

The gate was specified after the first production PAPER_PRIORITY candidate exposed strong buyer concentration/round-tripping, but before using that candidate's future outcome. It was then evaluated on the same four chronological walk-forward folds used for the live-core research.

## Predeclared promotion result

**REJECTED FOR OPERATIONAL VETO.**

Across the champion model's top-1% 10x candidates:

- original candidates: 1,502
- original 10x winners: 26
- retained after veto: 1,030 (68.6%)
- retained winners: 15 (57.7%)
- original hit rate: 1.731%
- retained hit rate: 1.456%
- precision ratio after gate: 0.841x

The rule removed 31.4% of candidates but 42.3% of the actual 10x winners. It therefore failed the winner-retention, precision-improvement and fold-stability requirements.

## Operational consequence

The champion decision remains authoritative for the ongoing prospective paper experiment. `adv_gate_v1_20260829` is permanently diagnostic-only and is prohibited from changing `operational_paper_decision`.

The concentration/round-trip features remain useful for:

- descriptive risk stratification;
- execution-stress analysis;
- prospective subgroup analysis;
- future challenger research under fresh validation.

They must not be interpreted as a proven rug/manipulation veto. Early genuine runners can also be highly concentrated and reflexive.
