# Frozen free-live 60-second policy

- Decision age: 60 seconds after observed launch.
- Inputs: only launch metadata, Pump TradeEvent data obtainable from Solana, and UTC decision time.
- No holder API, creator-history vendor feed, social data, or prospective outcomes are required.
- Targets: 5x, 10x, 25x, 100x before -50% drawdown.
- Primary rank: 10x live-core score. Secondary tail rank: 100x live-core score.
- Candidate thresholds come only from LIVECORE_MANIFEST.json and may not be tuned on an open prospective batch.
- Full 41-feature frozen model remains a separate research reference; it must not be silently mixed with this model.
- Paper-only. No real-money execution is authorized.
