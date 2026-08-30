#!/usr/bin/env python3
"""Outcome tracker entry point accepting both frozen prospective scanner lanes."""
from __future__ import annotations
import scripts.track_pending_outcomes as base

ALLOWED_SCANNERS={'stream_v4','stream_ht_v1'}

def eligible(row):
    if row.get('scanner_version') not in ALLOWED_SCANNERS or row.get('data_status')!='VALID':return False
    controls=row.get('prospective_controls') or {}
    return row.get('decision') in ('PAPER_PRIORITY','PAPER_CANDIDATE','WATCH') or bool(controls.get('random_control')) or bool(controls.get('near_miss_control'))

if __name__=='__main__':
    base.eligible=eligible
    base.main()
