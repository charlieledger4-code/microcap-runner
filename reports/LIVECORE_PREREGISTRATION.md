# Free-live 60-second prospective pre-registration

Frozen before consuming any prospective outcome labels.

## Immutable model bundle

- Historical source: `Slinky21/Pumpfun_Memecoin_Corpus`
- Training/research population: 310,111 tradeable tokens with future path data
- Historical date range: 2026-06-05 through 2026-07-14
- Decision age: 60 seconds
- Feature contract: `live_core_free_v1` (31 fields)
- Model family: median-imputation + `HistGradientBoostingClassifier`
- Training random state: 20260829
- GitHub Actions run: `33256093695`
- Artifact: `livecore60-models`
- Artifact SHA-256: `c3fbd5176639e1770282a05bfe1d4bdaa83b7f52cce9cce5ec27fcc8723cecb5`

Model SHA-256 values:

- 5x: `feb4dc7b991b6f4af26ee573256f3bebae6b2a9e14b50a4c9ca2c4e3c0d7e8e5`
- 10x: `d28a607fce93ba4320a85c41bcdb19d3a7c065aad712a005e563cbc76c78074d`
- 25x: `851c57dca4bd21327d90219c88bef0669ce7182705bb67cb1413cfc03659ea19`
- 100x: `ebd2cdd69a44558f55e09e6b8bcfb5b05a33018480c2925f8e8a474c9b8ff749`

## Historical walk-forward evidence used to choose the live rule

Across four later chronological test windows, the 31-field live-core model produced:

| Target | Aggregate top-1% hits | Selected | Population positives | Population N | Aggregate enrichment |
|---|---:|---:|---:|---:|---:|
| 5x | 122 | 1,502 | 2,411 | 150,484 | 5.07x |
| 10x | 26 | 1,502 | 855 | 150,484 | 3.05x |
| 25x | 8 | 1,502 | 260 | 150,484 | 3.08x |
| 100x | 1 | 1,502 | 52 | 150,484 | 1.93x |

For 10x, every fold had positive top-1% enrichment: 5.28x, 6.68x, 4.54x, 2.16x. The 100x live-core rank was unstable (zero top-1% hits in three of four folds), so it is not permitted to trigger a paper entry.

## Frozen operational rule v2

All score values are ranking scores, **not calibrated probabilities**.

10x frozen training thresholds:

- Q95: 0.8072107976094448
- Q99: 0.8678932396379199
- Q995: 0.8711575737756854
- Q999: 0.8754860268135511

25x frozen training thresholds:

- Q95: 0.7771384391410208
- Q99: 0.8586738451435101
- Q995: 0.8691955234871324
- Q999: 0.8791403225994675

Decision rule at exactly 60 seconds:

1. 10x score >= Q995 -> `PAPER_PRIORITY`.
2. Else 10x score >= Q99 -> `PAPER_CANDIDATE`.
3. Else 10x score >= Q95, or 25x score >= Q99 -> `WATCH`.
4. Else -> `REJECT`.
5. 5x and 100x outputs are diagnostic only and cannot promote an entry.

Q995/Q999 are priority subtiers only; no separate performance claim is attached to those narrower buckets until prospectively measured.

## Admissibility gate

A score is operationally valid only when:

- launch was observed prospectively;
- the feature timestamp is <= launch + 60 seconds;
- no post-60-second transaction contributes to any feature;
- the base token is a supported canonical Pump population member;
- quote handling is explicit (SOL/WSOL for the current historical-parity model);
- model file hash and artifact identity match this document;
- feature schema/order is exactly the frozen 31-field contract;
- collection health is sufficient to avoid knowingly incomplete trade counts.

If these conditions fail, output `DATA_INVALID` rather than imputing a candidate decision.

## Paper experiment rule

No real-money execution is authorized. All launches, including `REJECT`, are retained so prospective base rates can be measured. Candidate thresholds and feature definitions may not be changed within an open prospective batch. Any future model revision starts a new version and a new forward cohort.
