#!/usr/bin/env python3
"""Internet-connected Phase-2 bridge for GitHub Actions.

Real source data is kept outside the artifact directory (normally RUNNER_TEMP).
Only compact reports are uploaded back to ChatGPT.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys
from pathlib import Path
from huggingface_hub import hf_hub_download, HfApi
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.models.baseline import train as train_completion

FORWARD_REPO = "Tr4m0ryp/trenches-pumpfun-forward-2026-08"
SLINKY_REPO = "Slinky21/Pumpfun_Memecoin_Corpus"


def sha256(path: Path, chunk=1024*1024):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(chunk), b''):
            h.update(b)
    return h.hexdigest()


def download(repo: str, filename: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    p=hf_hub_download(repo_id=repo, repo_type="dataset", filename=filename, local_dir=str(dest))
    return Path(p)


def parquet_meta(path: Path) -> dict:
    pf=pq.ParquetFile(path)
    return {
        "bytes": path.stat().st_size,
        "rows": pf.metadata.num_rows,
        "row_groups": pf.metadata.num_row_groups,
        "columns": pf.schema_arrow.names,
        "sha256": sha256(path),
    }


def forward(out: Path, cache: Path):
    data=cache/"forward"; rep=out/"forward_report"; rep.mkdir(parents=True,exist_ok=True)
    paths={n:download(FORWARD_REPO,n,data) for n in ("features.parquet","labels.parquet","split.json")}
    metrics=train_completion(str(paths["features.parquet"]),str(paths["labels.parquet"]),str(paths["split.json"]),str(rep))
    manifest={k:{"bytes":v.stat().st_size,"sha256":sha256(v)} for k,v in paths.items()}
    (rep/"source_manifest.json").write_text(json.dumps(manifest,indent=2))
    f=pd.read_parquet(paths["features.parquet"])
    l=pd.read_parquet(paths["labels.parquet"])
    audit={
      "features_rows":len(f),"features_columns":list(f.columns),"labels_rows":len(l),"labels_columns":list(l.columns),
      "path_completed_positive":int(l["path_completed"].fillna(False).astype(bool).sum()) if "path_completed" in l else None,
      "important_caveat":"vendor-curated completion benchmark; not a market-wide economic return estimate"
    }
    (rep/"schema_audit.json").write_text(json.dumps(audit,indent=2,default=str))
    return metrics


def list_slinky_files():
    return HfApi().list_repo_files(SLINKY_REPO, repo_type="dataset")


def slinky_audit(out: Path, cache: Path, download_core: bool=False):
    rep=out/"slinky_audit"; rep.mkdir(parents=True,exist_ok=True)
    files=list_slinky_files()
    wanted_names={"tokens.parquet","postgard_snapshots.parquet","postgard_outcomes.parquet","migrations.parquet","KNOWN_ISSUES.md","quickstart.py"}
    trade_files=[x for x in files if x.startswith("trades/") and x.endswith(".parquet")]
    interesting=[x for x in files if Path(x).name in wanted_names or x in trade_files]
    (rep/"repo_files.json").write_text(json.dumps({"repo":SLINKY_REPO,"files":files,"interesting":interesting,"trade_shards":trade_files},indent=2))
    manifests={}
    if download_core:
        data=cache/"slinky"
        names=("tokens.parquet","postgard_outcomes.parquet","postgard_snapshots.parquet","migrations.parquet","KNOWN_ISSUES.md","quickstart.py")
        for name in names:
            matches=[x for x in files if Path(x).name==name]
            if not matches:
                continue
            p=download(SLINKY_REPO,matches[0],data)
            manifests[name]={"repo_path":matches[0],"bytes":p.stat().st_size,"sha256":sha256(p)}
            if p.suffix==".parquet":
                manifests[name].update(parquet_meta(p))
        if trade_files:
            p=download(SLINKY_REPO,trade_files[0],data)
            manifests["trade_probe"]={"repo_path":trade_files[0], **parquet_meta(p)}
            sample=pq.read_table(p).slice(0,5).to_pandas().astype(object).where(pd.notna, None).to_dict(orient="records")
            manifests["trade_probe"]["sample_rows"]=sample
        (rep/"core_manifest_schema.json").write_text(json.dumps(manifests,indent=2,default=str))
    return {"repo_file_count":len(files),"trade_shards":len(trade_files),"interesting":interesting,"downloaded":manifests}


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--mode",choices=["forward","slinky-audit","both"],default="both")
    ap.add_argument("--out",default="reports/github_phase2"); ap.add_argument("--download-slinky-core",action="store_true")
    a=ap.parse_args(); out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    cache=Path(os.environ.get("RUNNER_TEMP", str(ROOT/"data"/"tmp")))/"microcap_phase2"; cache.mkdir(parents=True,exist_ok=True)
    summary={}
    if a.mode in {"forward","both"}:
        summary["forward"]=forward(out,cache)
    if a.mode in {"slinky-audit","both"}:
        summary["slinky"]=slinky_audit(out,cache,a.download_slinky_core)
    (out/"SUMMARY.json").write_text(json.dumps(summary,indent=2,default=str))
    print(json.dumps(summary,indent=2,default=str))


if __name__=="__main__":
    main()
