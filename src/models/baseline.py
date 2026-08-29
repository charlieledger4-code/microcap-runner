from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss
from .leakage import assert_completion_benchmark_columns


def _read_table(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix.lower() == ".csv":
        return pd.read_csv(p)
    if p.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(p)
    raise ValueError(f"unsupported table format: {p.suffix}")


DEFAULT_FEATURES = [
    "holder_count","top_10_holder_rate","creator_balance_rate","dev_team_hold_rate",
    "fresh_wallet_rate","new_wallet_volume","bundler_mhr","bundler_trader_amount_rate",
    "volume_24h","swaps_24h","buys_24h","sells_24h","sniper_count",
    "top70_sniper_hold_rate","suspected_insider_hold_rate","rat_trader_amount_rate",
    "bot_degen_count","smart_degen_count","rug_ratio","is_wash_trading","age_seconds",
    "has_twitter","has_telegram","has_website","has_fund_from_address",
    "curve_family","bucket","segment","obs_band",
]


def enrichment(y: np.ndarray, p: np.ndarray, frac: float) -> dict:
    k = max(1, int(len(y)*frac))
    idx = np.argsort(p)[::-1][:k]
    base = float(np.mean(y))
    rate = float(np.mean(y[idx]))
    return {"fraction":frac,"n":k,"base_rate":base,"selected_rate":rate,"lift":rate/base if base else None}


def train(features_path: str, labels_path: str, split_path: str, out_dir: str = "reports") -> dict:
    f = _read_table(features_path)
    l = _read_table(labels_path)[["mint","path_completed"]]
    panel = f.merge(l, on="mint", how="inner")
    split = json.loads(Path(split_path).read_text())
    train_mints = set(split["in_sample"]); test_mints = set(split["out_of_sample"])
    cols = [c for c in DEFAULT_FEATURES if c in panel.columns]
    assert_completion_benchmark_columns(cols)
    tr = panel[panel.mint.isin(train_mints)].copy(); te = panel[panel.mint.isin(test_mints)].copy()
    num = [c for c in cols if not (pd.api.types.is_object_dtype(tr[c]) or pd.api.types.is_string_dtype(tr[c]))]
    cat = [c for c in cols if c not in num]
    prep = ColumnTransformer([
        ("num", Pipeline([("imp",SimpleImputer(strategy="median",add_indicator=True)),("sc",StandardScaler())]), num),
        ("cat", Pipeline([("imp",SimpleImputer(strategy="most_frequent")),("oh",OneHotEncoder(handle_unknown="ignore"))]), cat),
    ])
    model = Pipeline([("prep",prep),("clf",LogisticRegression(max_iter=1000,class_weight="balanced",C=0.2))])
    model.fit(tr[cols], tr.path_completed.astype(int))
    p = model.predict_proba(te[cols])[:,1]; y = te.path_completed.astype(int).to_numpy()
    metrics = {
        "n_train":len(tr),"n_test":len(te),"base_rate_test":float(y.mean()),
        "average_precision":float(average_precision_score(y,p)),
        "roc_auc":float(roc_auc_score(y,p)),
        "brier":float(brier_score_loss(y,p)),
        "enrichment":[enrichment(y,p,x) for x in (0.001,0.005,0.01,0.05)],
        "features":cols,
    }
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    Path(out_dir,"baseline_metrics.json").write_text(json.dumps(metrics,indent=2))
    return metrics


if __name__ == "__main__":
    import argparse
    p=argparse.ArgumentParser(); p.add_argument("features"); p.add_argument("labels"); p.add_argument("split"); p.add_argument("--out",default="reports")
    a=p.parse_args(); print(json.dumps(train(a.features,a.labels,a.split,a.out),indent=2))
