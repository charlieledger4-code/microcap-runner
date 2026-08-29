"""Load and score an immutable live-core model bundle.

Raw classifier outputs are ranking scores, not probabilities.  The only built-in
labels correspond to frozen training-population score quantiles from the manifest.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any
import hashlib, json
import joblib
import numpy as np
import pandas as pd


def sha256(path: str | Path) -> str:
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for chunk in iter(lambda:f.read(1<<20),b''):h.update(chunk)
    return h.hexdigest()


def score_tier(score: float, thresholds: dict[str,float]) -> str:
    ordered=[(.999,'Q999'),(.995,'Q995'),(.99,'Q99'),(.95,'Q95')]
    for q,name in ordered:
        v=thresholds.get(str(q))
        if v is not None and score>=float(v):return name
    return 'BELOW_Q95'


class LiveCoreScorer:
    def __init__(self,bundle_dir: str | Path):
        self.root=Path(bundle_dir)
        self.manifest=json.loads((self.root/'LIVECORE_MANIFEST.json').read_text())
        if self.manifest.get('feature_contract')!='live_core_free_v1':
            raise ValueError('wrong model bundle feature contract')
        self.features=list(self.manifest['features']);self.models={}
        for target,spec in self.manifest['targets'].items():
            p=self.root/'models'/spec['model_file']
            if not p.exists(): p=self.root/spec['model_file']
            got=sha256(p)
            if got!=spec['model_sha256']:raise ValueError(f'model hash mismatch for {target}x: {got}')
            self.models[target]=joblib.load(p)

    def score(self,row: dict[str,Any]) -> dict[str,Any]:
        missing_keys=[x for x in self.features if x not in row]
        if missing_keys:raise ValueError(f'feature keys absent: {missing_keys}')
        vals={k:row.get(k) for k in self.features}
        frame=pd.DataFrame([vals],columns=self.features).replace([np.inf,-np.inf],np.nan)
        scores={}
        for target,model in self.models.items():
            s=float(model.predict_proba(frame)[:,1][0]);spec=self.manifest['targets'][target]
            scores[target]={'score':s,'tier':score_tier(s,spec['score_thresholds']),'thresholds':spec['score_thresholds']}
        primary=scores.get('10',{}).get('tier','BELOW_Q95')
        tail=scores.get('100',{}).get('tier','BELOW_Q95')
        # Paper-only operational flag. It intentionally does not imply expected
        # profitability or a calibrated probability.
        if primary in ('Q999','Q995'):
            decision='PAPER_PRIORITY'
        elif primary=='Q99':
            decision='PAPER_CANDIDATE'
        elif primary=='Q95' or tail in ('Q999','Q995','Q99'):
            decision='WATCH'
        else:
            decision='REJECT'
        return {'decision':decision,'primary_target':'10x','tail_target':'100x','scores':scores,'model_contract':self.manifest['feature_contract']}
