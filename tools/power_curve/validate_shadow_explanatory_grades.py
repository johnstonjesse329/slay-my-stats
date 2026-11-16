"""Reconcile saved shadow outputs against raw fights and independent pandas groups."""
import hashlib
import json
import numpy as np
import pandas as pd
import shadow_explanatory_grades as s

def main():
    records = s.load_records()
    runs = pd.read_csv(s.OUT / 'ratings.csv')
    refs = pd.read_csv(s.OUT / 'references.csv')
    anchors = pd.read_csv(s.OUT / 'anchors.csv')
    acts = pd.read_csv(s.OUT / 'acts.csv')
    fights = pd.read_csv(s.OUT / 'fights.csv')
    raw = pd.DataFrame([dict(run=r['run'], player=r['player'], tier=r['tier'], won=r['won'], old=r['old'],
                             act=f['act'] + 1, encounter=f['enc'], turns=f['t'], hp_cost=f['taken'])
                        for r in records for f in r['fights'] if not f['died']])
    checked_refs = checked_anchors = checked_acts = 0
    for scheme, folds in s.splits(records):
        for fold, (tr, te) in enumerate(folds):
            train_ids = {records[i]['run'] for i in tr}
            test_ids = {records[i]['run'] for i in te}
            assert train_ids.isdisjoint(test_ids)
            saved_runs = runs[(runs.scheme == scheme) & (runs.fold == fold)]
            assert set(saved_runs.run) == test_ids
            train = raw[raw.run.isin(train_ids)]
            # Independent reconstruction from raw rows, not the fitting routine.
            ref = train.groupby(['tier', 'encounter']).agg(turns=('turns', 'mean'), cost=('hp_cost', 'mean'), n=('run', 'size'), players=('player', 'nunique'))
            ref = ref[(ref.n >= 5) & (ref.players >= 2)]
            saved = refs[(refs.scheme == scheme) & (refs.fold == fold)].set_index(['tier', 'encounter'])
            assert set(ref.index) == set(saved.index)
            for col in ['turns', 'cost', 'n', 'players']:
                assert np.allclose(ref[col], saved.loc[ref.index, col])
            checked_refs += len(ref)
            joined = train.merge(ref[['turns', 'cost']], left_on=['tier', 'encounter'], right_index=True, how='left', suffixes=('', '_ref'))
            joined['normalized_cost'] = (joined.hp_cost + 1) / (joined.cost + 1)
            joined['normalized_turns'] = joined.turns / joined.turns_ref
            ag = joined.groupby(['run', 'player', 'tier', 'act', 'won', 'old']).agg(n=('run', 'size'), matched=('cost', 'count'), cost=('normalized_cost', 'mean'), turns=('normalized_turns', 'mean'), raw_cost=('hp_cost', 'mean'), raw_turns=('turns', 'mean')).reset_index()
            ag = ag[ag.won & (ag.matched >= 3) & (ag.matched / ag.n >= .7)]
            expected = []
            for cohort, pop in [('op', ag[ag.old == 'OP']), ('strong', ag[ag.old.isin(['OP', 'Hype'])]), ('winners', ag)]:
                for (t, act), g in pop.groupby(['tier', 'act']):
                    expected.append(dict(tier=t, act=act, cohort=cohort, n=len(g), players=g.player.nunique(), cost=g.cost.median(), cost_q75=g.cost.quantile(.75), turns=g.turns.median(), raw_cost=g.raw_cost.median(), raw_turns=g.raw_turns.median()))
            exp = pd.DataFrame(expected).set_index(['tier', 'act', 'cohort'])
            saved = anchors[(anchors.scheme == scheme) & (anchors.fold == fold)].set_index(['tier', 'act', 'cohort'])
            assert set(exp.index) == set(saved.index)
            for col in ['n', 'players', 'cost', 'cost_q75', 'turns', 'raw_cost', 'raw_turns']:
                assert np.allclose(exp[col], saved.loc[exp.index, col])
            checked_anchors += len(exp)
            tf = fights[(fights.scheme == scheme) & (fights.fold == fold)]
            # All completed raw fights are present; terminal failed fights are absent.
            assert len(tf) == len(raw[raw.run.isin(test_ids)])
            actual = tf.groupby(['run', 'act']).agg(n=('run', 'size'), matched=('reference_available', 'sum'), cost=('normalized_cost', 'mean'), turns=('normalized_turns', 'mean'), raw_cost=('hp_cost', 'mean'), raw_turns=('turns', 'mean'))
            sa = acts[(acts.scheme == scheme) & (acts.fold == fold)].set_index(['run', 'act'])
            assert set(actual.index) == set(sa.index)
            for col in ['n', 'matched', 'cost', 'turns', 'raw_cost', 'raw_turns']:
                assert np.allclose(actual[col], sa.loc[actual.index, col], equal_nan=True)
            for (_, act_number), ar in sa.iterrows():
                cs = [saved.loc[(ar.tier, act_number, c)] if (ar.tier, act_number, c) in saved.index else None for c in ['op', 'strong', 'winners']]
                if ar.matched < 3 or ar.coverage < .7 or any(c is None or c['n'] < 10 or c['players'] < 3 for c in cs):
                    expected_act = 'Unknown'
                else:
                    op, strong, win = cs
                    if op.cost > strong.cost or strong.cost > win.cost_q75 or op.cost_q75 > strong.cost_q75:
                        expected_act = 'Unknown'
                    elif ar.cost <= op.cost or (ar.turns <= op.turns and ar.cost <= op.cost_q75):
                        expected_act = 'OP'
                    elif ar.cost <= strong.cost or (ar.turns <= strong.turns and ar.cost <= strong.cost_q75):
                        expected_act = 'Hype'
                    else:
                        expected_act = 'Mid' if ar.cost <= win.cost_q75 else 'Rough'
                assert ar.grade == expected_act
            checked_acts += len(sa)
            # Independent aggregation check, including abstention and the OP gate.
            for _, row in saved_runs.iterrows():
                ra = sa.loc[[row.run]] if row.run in sa.index.get_level_values('run') else sa.iloc[:0]
                ra = ra[ra.n >= 3]
                if len(ra) == 0 or (ra.grade == 'Unknown').any():
                    expected_grade = 'Unknown'
                elif {int(i[1]): g for i, g in ra.grade.items()}.get(2) == {int(i[1]): g for i, g in ra.grade.items()}.get(3) == 'OP':
                    expected_grade = 'OP'
                else:
                    mean = ra.grade.map(s.RANK).mean()
                    expected_grade = 'Hype' if mean >= 2 else 'Mid' if mean >= 1 else 'Rough'
                assert row.candidate == expected_grade
    manifest = json.loads((s.source.OUT / 'snapshot-manifest.json').read_text())
    assert all(hashlib.sha256((s.source.SOURCE / p).read_bytes()).hexdigest() == h for p, h in manifest.items())
    result = dict(passed=True, run_evaluations=len(runs), references_recomputed=checked_refs,
                  anchors_recomputed=checked_anchors, acts_recomputed=checked_acts,
                  snapshot_files_verified=len(manifest),
                  artifacts={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in s.OUT.glob('*.csv')})
    (s.OUT / 'validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'artifacts'}, indent=2))

if __name__ == '__main__':
    main()
