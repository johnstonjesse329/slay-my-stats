"""Offline registered v1: encounter-adjusted observed efficiency, never live grades."""
import collections
import gzip
import hashlib
import html
import json
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
import six_character_boss_study as source
import fight_demand as fd

OUT = source.OUT / 'shadow_explanatory_v1'
RANK = {'Rough': 0, 'Mid': 1, 'Hype': 2, 'OP': 3}

def tier(asc):
    return 'A0-1' if asc < 2 else 'A2-7' if asc < 8 else f'A{asc}'

def load_records():
    accepted = set()
    for p in (source.SOURCE / 'users').glob('*/*.json.gz'):
        if p.name.startswith('_'):
            continue
        with gzip.open(p, 'rt', encoding='utf-8') as f:
            for r in json.load(f).get('runs', []):
                accepted.add(source.b.ar.signature(r['ts'], r['char'], r.get('seed')))
    roster = source.core_roster(json.loads((source.b.ar.ROOT / 'card_game_data.json').read_text(encoding='utf-8')))
    source.b.ar.g.RAW = source.SOURCE / 'raw'
    old = pd.read_csv(source.OUT / 'existing_grade_validation/ratings.csv')
    old = old[(old.scheme == 'current_baked_baseline') & (old.stage == 'completed_run')].set_index('run')
    assert old.index.is_unique
    records = []
    for (sid, ts), raw in source.b.ar.g.load().items():
        if not source.eligible(raw, accepted, roster)[0]:
            continue
        run = source.b.ar.pseudonym(f'{sid}:{ts}')
        if run not in old.index:
            raise ValueError('eligible run lacks frozen old grade')
        fs = fd.run_fights({0: raw})
        records.append(dict(run=run, player=source.b.ar.pseudonym(sid), ts=ts,
                            asc=raw.get('ascension', 0), tier=tier(raw.get('ascension', 0)),
                            character=raw['players'][0]['character'], won=bool(raw.get('win')),
                            old=old.loc[run, 'grade'], fights=fs[0] if fs else []))
    assert len(records) == len(old) == 1758
    return records

def references(train):
    groups = collections.defaultdict(list)
    for r in train:
        for f in r['fights']:
            if not f['died']:
                groups[(r['tier'], f['enc'])].append((r, f))
    refs = {}
    for key, rows in groups.items():
        players = {r['player'] for r, f in rows}
        if len(rows) >= 5 and len(players) >= 2:
            refs[key] = dict(turns=float(np.mean([f['t'] for r, f in rows])),
                             cost=float(np.mean([f['taken'] for r, f in rows])),
                             n=len(rows), players=len(players))
    return refs

def measure(r, refs):
    acts, details = [], []
    for act in sorted({f['act'] for f in r['fights'] if not f['died']}):
        fs = [f for f in r['fights'] if f['act'] == act and not f['died']]
        matched = []
        for i, f in enumerate(fs):
            ref = refs.get((r['tier'], f['enc']))
            d = dict(run=r['run'], act=act + 1, fight=i, encounter=f['enc'],
                     turns=f['t'], hp_cost=f['taken'], reference_available=ref is not None)
            if ref:
                d.update(reference_turns=ref['turns'], reference_cost=ref['cost'],
                         reference_n=ref['n'], reference_players=ref['players'],
                         normalized_turns=f['t'] / ref['turns'],
                         normalized_cost=(f['taken'] + 1) / (ref['cost'] + 1))
                matched.append(d)
            details.append(d)
        valid = len(matched) >= 3 and len(matched) / len(fs) >= .7
        acts.append(dict(run=r['run'], player=r['player'], act=act + 1, tier=r['tier'],
                         n=len(fs), matched=len(matched), coverage=len(matched) / len(fs),
                         valid=valid, cost=float(np.mean([x['normalized_cost'] for x in matched])) if matched else None,
                         turns=float(np.mean([x['normalized_turns'] for x in matched])) if matched else None,
                         raw_cost=float(np.mean([f['taken'] for f in fs])),
                         raw_turns=float(np.mean([f['t'] for f in fs]))))
    return acts, details

def fit(train):
    refs = references(train)
    groups = collections.defaultdict(list)
    for r in train:
        if not r['won']:
            continue
        for a in measure(r, refs)[0]:
            if not a['valid']:
                continue
            for cohort in ['op', 'strong', 'winners']:
                if cohort == 'op' and r['old'] != 'OP':
                    continue
                if cohort == 'strong' and r['old'] not in ['OP', 'Hype']:
                    continue
                groups[(r['tier'], a['act'], cohort)].append(a)
    anchors = {}
    for key, rows in groups.items():
        anchors[key] = dict(n=len(rows), players=len({a['player'] for a in rows}),
                            cost=float(np.median([a['cost'] for a in rows])),
                            cost_q75=float(np.quantile([a['cost'] for a in rows], .75)),
                            turns=float(np.median([a['turns'] for a in rows])),
                            raw_cost=float(np.median([a['raw_cost'] for a in rows])),
                            raw_turns=float(np.median([a['raw_turns'] for a in rows])))
    return refs, anchors

def grade_act(a, anchors):
    if not a['valid']:
        return 'Unknown', 'insufficient encounter coverage or fewer than three matched fights'
    cohorts = [anchors.get((a['tier'], a['act'], c)) for c in ['op', 'strong', 'winners']]
    if any(c is None or c['n'] < 10 or c['players'] < 3 for c in cohorts):
        return 'Unknown', 'unsupported anchor cohort (requires 10 runs and 3 players each)'
    op, strong, winners = cohorts
    if not (op['cost'] <= strong['cost'] <= winners['cost_q75'] and op['cost_q75'] <= strong['cost_q75']):
        return 'Unknown', 'unordered cost anchors'
    for name, c in [('OP', op), ('Hype', strong)]:
        if a['cost'] <= c['cost']:
            return name, 'low HP-cost route'
        if a['turns'] <= c['turns'] and a['cost'] <= c['cost_q75']:
            return name, 'fast pace with bounded HP cost'
    return ('Mid', 'within winner cost Q75') if a['cost'] <= winners['cost_q75'] else ('Rough', 'above winner cost Q75')

def aggregate(acts):
    relevant = [a for a in acts if a['n'] >= 3]
    if not relevant or any(a['grade'] == 'Unknown' for a in relevant):
        return 'Unknown'
    by_act = {a['act']: a['grade'] for a in relevant}
    if by_act.get(2) == by_act.get(3) == 'OP':
        return 'OP'
    score = np.mean([RANK[a['grade']] for a in relevant])
    return 'Hype' if score >= 2 else 'Mid' if score >= 1 else 'Rough'

def evaluate(r, refs, anchors):
    acts, details = measure(r, refs)
    for a in acts:
        a['grade'], a['reason'] = grade_act(a, anchors)
    return aggregate(acts), acts, details

def splits(records):
    idx = np.arange(len(records))
    yield 'run_holdout', list(GroupKFold(5).split(idx, groups=[r['run'] for r in records]))
    yield 'player_holdout', [(np.array([i for i, r in enumerate(records) if r['player'] != p]),
                              np.array([i for i, r in enumerate(records) if r['player'] == p]))
                             for p in sorted({r['player'] for r in records})]
    times = sorted({r['ts'] for r in records})
    ts = np.array([r['ts'] for r in records])
    folds = []
    for lo, hi in [(.4, .6), (.6, .8), (.8, 1.)]:
        start = times[int(len(times) * lo)]
        end = times[int(len(times) * hi)] if hi < 1 else max(times) + 1
        folds.append((idx[ts < start], idx[(ts >= start) & (ts < end)]))
    yield 'forward_time', folds

def main():
    OUT.mkdir(exist_ok=True)
    manifest = json.loads((source.OUT / 'snapshot-manifest.json').read_text())
    assert all(hashlib.sha256((source.SOURCE / p).read_bytes()).hexdigest() == h for p, h in manifest.items())
    records = load_records()
    results, act_rows, fight_rows, reference_rows, anchor_rows, fold_rows = [], [], [], [], [], []
    for scheme, folds in splits(records):
        for fold, (tr, te) in enumerate(folds):
            train, test = [records[i] for i in tr], [records[i] for i in te]
            assert not ({r['run'] for r in train} & {r['run'] for r in test})
            if scheme == 'player_holdout':
                assert not ({r['player'] for r in train} & {r['player'] for r in test})
            refs, anchors = fit(train)
            tag = dict(scheme=scheme, fold=fold)
            fold_rows.append(tag | dict(training_runs=len(train), test_runs=len(test), disjoint=True))
            reference_rows.extend(tag | dict(tier=t, encounter=e) | ref for (t, e), ref in refs.items())
            anchor_rows.extend(tag | dict(tier=t, act=a, cohort=c) | v for (t, a, c), v in anchors.items())
            for r in test:
                grade, acts, details = evaluate(r, refs, anchors)
                movement = 'unknown' if grade not in RANK or r['old'] not in RANK else 'up' if RANK[grade] > RANK[r['old']] else 'down' if RANK[grade] < RANK[r['old']] else 'same'
                results.append(tag | {k: r[k] for k in ['run', 'player', 'ts', 'asc', 'tier', 'character', 'won', 'old']} | dict(candidate=grade, movement=movement,
                               acts='; '.join(f"A{a['act']} {a['grade']}: cost={a['cost']}, turns={a['turns']}; {a['reason']}" for a in acts),
                               terminal_loss_fights=sum(f['died'] for f in r['fights'])))
                act_rows.extend(tag | a for a in acts)
                fight_rows.extend(tag | d for d in details)
        print(scheme, 'complete', flush=True)
    frames = dict(ratings=results, acts=act_rows, fights=fight_rows, references=reference_rows, anchors=anchor_rows, folds=fold_rows)
    for name, rows in frames.items():
        pd.DataFrame(rows).to_csv(OUT / f'{name}.csv', index=False)
    d = pd.DataFrame(results)
    d.groupby(['scheme', 'won', 'old', 'candidate']).size().rename('n').reset_index().to_csv(OUT / 'transitions.csv', index=False)
    for dim in ['tier', 'player']:
        d.groupby(['scheme', dim, 'won', 'old', 'candidate']).size().rename('n').reset_index().to_csv(OUT / f'transitions_by_{dim}.csv', index=False)
    coverage = d.assign(ranked=d.candidate != 'Unknown').groupby(['scheme', 'tier']).agg(runs=('run', 'size'), ranked=('ranked', 'sum')).reset_index()
    coverage['coverage'] = coverage.ranked / coverage.runs
    coverage.to_csv(OUT / 'coverage.csv', index=False)
    pair = d[d.scheme == 'run_holdout'][['run', 'candidate', 'tier']].merge(d[d.scheme == 'player_holdout'][['run', 'candidate']], on='run', suffixes=('_run', '_player'), validate='one_to_one')
    pair['joint'] = (pair.candidate_run != 'Unknown') & (pair.candidate_player != 'Unknown')
    pair['agree'] = pair.candidate_run == pair.candidate_player
    pair.to_csv(OUT / 'stability.csv', index=False)
    changed = d[(d.scheme == 'run_holdout') & d.movement.isin(['up', 'down'])]
    checked = pd.read_csv(source.OUT / 'grade_explanation_audit/paired_boss_facts.csv')
    changed.merge(checked, on='run', suffixes=('', '_boss')).to_csv(OUT / 'changed_checked_bosses.csv', index=False)
    changed.to_csv(OUT / 'changed_run_reasons.csv', index=False)
    move = d[(d.scheme == 'run_holdout') & d.won].groupby(['old', 'movement']).size().unstack(fill_value=0).reindex(['OP', 'Hype', 'Mid', 'Rough'], fill_value=0)
    move.to_csv(OUT / 'winning_movements.csv')
    agreement = float(pair.loc[pair.joint, 'agree'].mean()) if pair.joint.any() else None
    accepted_tiers = []
    for t in sorted(coverage.tier.unique()):
        c = coverage[(coverage.tier == t) & coverage.scheme.isin(['run_holdout', 'player_holdout'])]
        p = pair[(pair.tier == t) & pair.joint]
        if len(c) == 2 and c.coverage.min() >= .7 and len(p) and p.agree.mean() >= .8:
            accepted_tiers.append(t)
    summary = dict(snapshot_files_verified=len(manifest), runs=len(records), players=len({r['player'] for r in records}),
                   joint_ranked=int(pair.joint.sum()), exact_agreement=agreement, eligible_tiers_before_manual_review=accepted_tiers,
                   changed_runs=len(changed), changed_checked_runs=int(changed.run.isin(checked.run).sum()),
                   prereg_sha256=hashlib.sha256((source.b.ar.ROOT / 'docs/shadow-explanatory-grade-v1.md').read_bytes()).hexdigest())
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    notes = ('Registered retrospective v1. Source: fixed published standard solo snapshot; old labels are locally saved completed-run readings. '
             'Candidate grades observed efficiency, not intrinsic deck strength or win probability. Test-run fights never enter training references or anchors. '
             'Training old labels were baked using an existing full-history artifact, so this is not fully independent label validation. '
             'A0-1/A2-7 split respects cumulative reduced transition healing; only fight-room net costs enter, never inter-act HP changes. '
             'HP costs mix intentional spending and enemy damage. No character/build/patch stratification; these remain confounders. '
             'A lost run\'s terminal fight is excluded as in the existing reading; this limits any interpretation of loss strength. '
             'A10 includes both completed bosses but no prediction of Dread changes. '
             'Unknown means insufficient support or inconsistent anchors, not weak performance. '
             'No changes to live labels. See changed_run_reasons.csv, fights.csv and anchors.csv for every movement\'s numerical trail.')
    (OUT / 'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Shadow grade experiment</title><style>body{font:17px/1.5 system-ui;max-width:1200px;margin:30px auto}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ccc}pre{white-space:pre-wrap}</style><h1>Shadow grade experiment v1</h1><p>' + html.escape(notes) + '</p><h2>Winning run movement</h2>' + move.to_html() + '<h2>Coverage</h2>' + coverage.to_html(index=False) + '<h2>Validation</h2><pre>' + html.escape(json.dumps(summary, indent=2)) + '</pre>', encoding='utf-8')
    print(move.to_string())
    print(coverage.to_string(index=False))
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
