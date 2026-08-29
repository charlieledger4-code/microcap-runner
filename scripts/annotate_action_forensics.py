#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
from src.live.action_forensics import summarize_action_tape, FORENSICS_VERSION


def main():
    p=argparse.ArgumentParser();p.add_argument('--rows',required=True);p.add_argument('--tapes',required=True);a=p.parse_args()
    rp=Path(a.rows);tp=Path(a.tapes)
    rows=[json.loads(x) for x in rp.read_text().splitlines() if x.strip()]
    tapes={x['mint']:x for x in (json.loads(line) for line in tp.read_text().splitlines() if line.strip())}
    missing=0
    for r in rows:
        tape=tapes.get(r.get('mint'))
        if tape is None:
            r['action_forensics']={'forensics_version':FORENSICS_VERSION,'status':'MISSING_ACTION_TAPE'};missing+=1
        else:
            r['action_forensics']={'status':'OK',**summarize_action_tape(tape.get('trades') or [])}
    rp.write_text(''.join(json.dumps(r,separators=(',',':'))+'\n' for r in rows))
    print(json.dumps({'rows':len(rows),'tapes':len(tapes),'missing':missing,'forensics_version':FORENSICS_VERSION},indent=2))

if __name__=='__main__':main()
