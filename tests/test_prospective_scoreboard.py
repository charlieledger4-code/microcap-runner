from scripts.build_prospective_scoreboard import groups,summarize


def row(decision,hit10=False,random=False,gate=None):
    return {
        'decision':decision,
        'prospective_controls':{'random_control':random,'near_miss_control':False},
        'adversarial_gate':{'status':gate} if gate else {},
        'outcome':{
            'max_executable_multiple':12 if hit10 else 1.2,
            'terminal_executable_multiple':2 if hit10 else .8,
            'liquidity_limited_points':0,
            'executable_targets':{
                '2':{'hit':hit10},'5':{'hit':hit10},'10':{'hit':hit10},
                '25':{'hit':False},'50':{'hit':False},'100':{'hit':False},
            },
        },
    }


def test_groups_can_overlap_random_and_candidate():
    g=groups(row('PAPER_PRIORITY',True,random=True,gate='VETO'))
    assert 'champion_candidate' in g
    assert 'champion_priority' in g
    assert 'random_control' in g
    assert 'candidate_gate_veto_counterfactual' in g


def test_summary_uses_executable_target_hits():
    s=summarize([row('WATCH',True),row('WATCH',False)])
    assert s['n']==2
    assert s['targets']['10']['hits']==1
    assert s['targets']['10']['rate']==.5
    assert s['max_executable_multiple']==12
