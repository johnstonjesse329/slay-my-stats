"""Reproducible, local act-clear experiment. Outputs contain pseudonymous IDs.
Run: infra/.venv/Scripts/python.exe tools/power_curve/act_readiness.py
Dependencies: pandas, numpy, scikit-learn, matplotlib. No production writes.
"""
import collections, gzip, hashlib, json, statistics, sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.metrics import brier_score_loss, roc_auc_score, log_loss
import gamma_curves as g
import fight_demand as fd

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'local_data/act_validation'

def tier(asc): return 'A0-7' if asc<8 else f'A{asc}'
def signature(ts,char,seed): return (int(ts),char.replace('CHARACTER.',''),str(seed))
def pseudonym(value): return hashlib.sha256(value.encode()).hexdigest()[:12]

def dataset():
    g.RAW=OUT/'raw'; raw=g.load()
    published=[]
    for p in (OUT/'users').glob('*/*.json.gz'):
        if not p.name.startswith('_'):
            published.extend(json.load(gzip.open(p,'rt')).get('runs',[]))
    accepted={signature(r['ts'],r['char'],r.get('seed')) for r in published}
    audit=collections.Counter(raw_records=len(raw),published_records=len(published))
    rows=[]; fight_rows=[]
    for (sid,ts),r in raw.items():
        if len(r['players'])!=1: audit['excluded_coop']+=1;continue
        char=r['players'][0]['character']
        if signature(ts,char,r.get('seed')) not in accepted: audit['excluded_not_in_published_profiles']+=1;continue
        if r.get('game_mode','standard')!='standard': audit['excluded_other_modes']+=1;continue
        if r.get('was_abandoned'): audit['excluded_abandoned']+=1;continue
        if char not in {'CHARACTER.IRONCLAD','CHARACTER.SILENT','CHARACTER.DEFECT','CHARACTER.NECROBINDER','CHARACTER.REGENT'}: audit['excluded_noncore_character']+=1;continue
        audit['eligible_runs']+=1
        rid=pseudonym(f'{sid}:{ts}'); player=pseudonym(sid)
        asc=r.get('ascension') or 0
        acts=r.get('map_point_history') or []
        for ai,points in enumerate(acts):
            combats=[]
            for point in points:
                rooms=[q for q in point.get('rooms',[]) if q.get('turns_taken') and q.get('monster_ids')]
                if not rooms:continue
                if len(rooms)!=1: audit['ambiguous_multi_combat_points']+=1;continue
                room=rooms[0]; stats=point['player_stats'][0]
                kind=point.get('map_point_type','unknown')
                hp=stats.get('current_hp',0); mx=stats.get('max_hp',0)
                ids=[m for m in room['monster_ids'] if m not in fd.PETS]
                pools=[fd.body_pool(m)[int(asc>=8)] for m in ids]
                pool=sum(pools) if pools and all(pools) else None
                combats.append(dict(enc=room['model_id'],kind=kind,turns=room['turns_taken'],loss=max(0,stats.get('damage_taken',0)-stats.get('hp_healed',0)),hp=hp,maxhp=mx,pool=pool,act=ai+1,tier=tier(asc),run=rid))
            if not combats:continue
            # Later act or run win is direct evidence of act completion. A survived
            # terminal boss also proves this act cleared, except A10's double boss.
            bosses=[f for f in combats if f['kind']=='boss']
            advanced=any(acts[ai+1:])
            required=2 if asc>=10 and ai==2 else 1
            clear=bool(advanced or r.get('win') or (len(bosses)>=required and all(f['hp']>0 for f in bosses)))
            history=[]
            for f in combats:
                if f['hp']<=0:break
                if f['kind']=='boss':break
                history.append(f); fight_rows.append(f)
                if len(history)<3:continue
                rows.append(dict(run=rid,player=player,ts=ts,act=ai+1,tier=tier(asc),asc=asc,char=char,build=r.get('build_id','unknown'),fight_index=len(history),hp=f['hp'],maxhp=f['maxhp'],clear=int(clear),history=list(history)))
    audit['checkpoints']=len(rows);audit['modeled_runs']=len({r['run'] for r in rows})
    audit['modeled_players']=len({r['player'] for r in rows})
    audit['telemetry_objects']=len(list((OUT/'telemetry').rglob('*.gz')))
    return rows,fight_rows,dict(audit)

def reference(fights,train_runs):
    groups=collections.defaultdict(list)
    for f in fights:
        if f['run'] not in train_runs:continue
        groups[(f['enc'],f['tier'])].append(f)
        groups[(f['act'],f['kind'],f['tier'])].append(f)
    return {k: (len(v), statistics.mean(f['turns'] for f in v), statistics.mean(f['loss'] for f in v)) for k,v in groups.items()}

def features(r,ref,level):
    x={'act_tier':f"{r['act']}/{r['tier']}",'asc':r['asc'],'character':r['char'],'build':r['build'],'fight_index':r['fight_index'],'hp':r['hp'],'maxhp':r['maxhp'],'hp_fraction':r['hp']/max(1,r['maxhp'])}
    if level=='baseline':return x
    recent=r['history'][-3:]
    def adjusted(f):
        peers=ref.get((f['enc'],f['tier']))
        if not peers or peers[0]<5:peers=ref.get((f['act'],f['kind'],f['tier']))
        if not peers:return None
        return (f['turns']/peers[1], f['loss']-peers[2])
    vals=[v for f in recent if (v:=adjusted(f)) is not None]
    x.update(recent_turns=statistics.mean(f['turns'] for f in recent),recent_loss=statistics.mean(f['loss'] for f in recent),worst_loss=max(f['loss'] for f in recent),loss_sd=statistics.pstdev(f['loss'] for f in recent),reference_coverage=len(vals)/3)
    if vals:x.update(relative_turns=statistics.mean(v[0] for v in vals),excess_loss=statistics.mean(v[1] for v in vals))
    damage=[f['pool']/f['turns'] for f in recent if f['pool'] is not None]
    x['hp_pool_coverage']=len(damage)/3
    if damage:x['estimated_damage_per_turn']=statistics.mean(damage)
    if level=='trend':
        old=[v for f in r['history'][-6:-3] if (v:=adjusted(f)) is not None]
        x['trend_available']=int(bool(old and vals))
        if old and vals:
            x['loss_change']=statistics.mean(v[1] for v in vals)-statistics.mean(v[1] for v in old)
            x['pace_change']=statistics.mean(v[0] for v in vals)-statistics.mean(v[0] for v in old)
    return x

def weights(rows):
    counts=collections.Counter((r['run'],r['act']) for r in rows)
    return np.array([1/counts[(r['run'],r['act'])] for r in rows])

def evaluate(rows,fights):
    n=len(rows); indices=np.arange(n); y=np.array([r['clear'] for r in rows]); output=[]
    groups=np.array([r['run'] for r in rows])
    splits={'run_holdout':list(GroupKFold(5).split(indices,y,groups))}
    splits['player_holdout']=[(indices[np.array([r['player']!=p for r in rows])],indices[np.array([r['player']==p for r in rows])]) for p in sorted({r['player'] for r in rows})]
    times=sorted({r['ts'] for r in rows}); boundary=times[int(len(times)*.8)]
    splits['later_runs']=[(indices[np.array([r['ts']<boundary for r in rows])],indices[np.array([r['ts']>=boundary for r in rows])])]
    for split,folds in splits.items():
        for fold,(tr,te) in enumerate(folds):
            train=[rows[i] for i in tr]; test=[rows[i] for i in te]
            assert not {r['run'] for r in train}&{r['run'] for r in test}
            ref=reference(fights,{r['run'] for r in train})
            for level in ['baseline','performance','trend']:
                model=make_pipeline(DictVectorizer(),StandardScaler(with_mean=False),LogisticRegression(C=.1,max_iter=1500))
                model.fit([features(r,ref,level) for r in train],y[tr],logisticregression__sample_weight=weights(train))
                pred=model.predict_proba([features(r,ref,level) for r in test])[:,1]
                for r,p in zip(test,pred):output.append({k:r[k] for k in ['run','player','act','tier','fight_index','clear']}|dict(split=split,fold=fold,model=level,p=float(p)))
        print('Evaluated',split,flush=True)
    return pd.DataFrame(output)

def summarize(pred):
    metrics=[]
    for (split,model),d in pred.groupby(['split','model']):
        w=1/d.groupby(['run','act'])['run'].transform('size')
        metrics.append(dict(split=split,model=model,n=len(d),brier=brier_score_loss(d.clear,d.p,sample_weight=w),auc=roc_auc_score(d.clear,d.p,sample_weight=w),logloss=log_loss(d.clear,d.p,sample_weight=w)))
    return pd.DataFrame(metrics)

def artifacts(rows,audit,pred,metrics):
    pred.to_csv(OUT/'predictions.csv',index=False)
    flat=[{k:v for k,v in r.items() if k!='history'} for r in rows]
    pd.DataFrame(flat).to_csv(OUT/'checkpoints.csv',index=False)
    (OUT/'audit.json').write_text(json.dumps(audit,indent=2))
    metrics.to_csv(OUT/'model_metrics.csv',index=False)
    fig,axes=plt.subplots(1,2,figsize=(12,4.6))
    for model,d in metrics.groupby('model'):axes[0].plot(d.split,d.brier,'o-',label=model)
    axes[0].set(title='Prediction error on held-out runs (lower is better)',ylabel='Brier score');axes[0].legend()
    for model in ['baseline','performance','trend']:
        d=pred[(pred.split=='player_holdout')&(pred.model==model)].copy()
        d['w']=1/d.groupby(['run','act'])['run'].transform('size');d['bin']=(d.p*5).astype(int).clip(0,4)
        pts=[]
        for _,b in d.groupby('bin'):pts.append((np.average(b.p,weights=b.w),np.average(b.clear,weights=b.w)))
        axes[1].plot(*zip(*pts),'o-',label=model)
    axes[1].plot([0,1],[0,1],'k--',alpha=.5);axes[1].set(title='Calibration on unseen players',xlabel='Predicted act-clear probability',ylabel='Observed act-clear fraction');axes[1].legend()
    fig.tight_layout();fig.savefig(OUT/'validation.png',dpi=160);plt.close(fig)
    lines=['# Act readiness: first model experiment','',f"Data: {audit['raw_records']} raw records; {audit['published_records']} published records. {audit['modeled_runs']} solo standard non-abandoned runs from {audit['modeled_players']} players yield {audit['checkpoints']} checkpoints.",'','Each checkpoint follows at least three completed non-boss fights in an act. Outcome: clearing that act, including both final bosses at A10. Terminal deaths and post-boss checkpoints are excluded. Results therefore apply to surviving checkpoints, not act entry.','', 'Baseline: act/difficulty, exact ascension, character, build, fights completed, current/max HP. Performance adds recent turns, HP loss, variability, inferred damage output and encounter-adjusted performance. Trend adds changes from the preceding three fights. Encounter references are fitted only on training runs, with act/kind/difficulty fallback; no winner filtering. Each run-act receives equal total weight.','', '| Validation | Model | Brier ↓ | AUC ↑ | Log loss ↓ |','|---|---|---:|---:|---:|']
    for r in metrics.to_dict('records'):lines.append(f"| {r['split']} | {r['model']} | {r['brier']:.4f} | {r['auc']:.3f} | {r['logloss']:.4f} |")
    lines+=['','![Held-out evaluation](validation.png)','','## Interpretation limits','This is a predictive association study, not a deck simulator or causal analysis of card choices. HP pools use current game data and may mismatch older patches, summons and encounter variants. Damage output is inferred, not measured block or damage. Telemetry is inventoried but not used in this model. There are only seven players. No threshold search or hyperparameter tuning was performed. Repeated checkpoints are correlated; do not treat their count as an independent sample size. Build and ascension adjustment do not remove all player/route confounding. A0–7 pools encounter references but exact ascension remains a baseline feature. No Dread calibration is available.','', 'Raw versus published reconciliation uses timestamp, character and seed signatures for solo runs; exclusions are in audit.json. Published profiles can contain legacy no-raw records. The earlier exploratory report used raw runs directly; this experiment restricts to published core-character runs.','', 'Review model_metrics.csv, audit.json, and the notebook. Models are exploratory and have not changed any site ratings.']
    (OUT/'review.md').write_text('\n'.join(lines),encoding='utf-8')
    cells=[]
    def cell(kind,text):cells.append(dict(cell_type=kind,metadata={},source=text.splitlines(True),**({'execution_count':None,'outputs':[]} if kind=='code' else {})))
    cell('markdown','# Act readiness review\nLocal production snapshot; run the script to rebuild outputs. See review.md for assumptions.')
    cell('code',"from pathlib import Path\nimport pandas as pd\nfrom IPython.display import display, Markdown, Image\nbase = Path.cwd()\nif not (base / 'model_metrics.csv').exists():\n    base = base / 'local_data' / 'act_validation'\ndisplay(Markdown((base / 'review.md').read_text(encoding='utf-8')))\ndisplay(Image(filename=str(base / 'validation.png')))")
    cell('code',"metrics = pd.read_csv(base / 'model_metrics.csv')\nmetrics")
    cell('code',"import json\njson.loads((base / 'audit.json').read_text())")
    cell('code',"p = pd.read_csv(base / 'predictions.csv')\n# Each run-act gets equal weight within its model and validation split.\np['weight'] = 1 / p.groupby(['split','model','run','act'])['run'].transform('size')\np.groupby(['split','model','tier','act']).agg(checkpoints=('clear','size'), runs=('run','nunique'))")
    (OUT/'review.ipynb').write_text(json.dumps(dict(nbformat=4,nbformat_minor=5,metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'}},cells=cells),indent=2))

def main():
    rows,fights,audit=dataset();print(json.dumps(audit),flush=True)
    pred=evaluate(rows,fights);metrics=summarize(pred);artifacts(rows,audit,pred,metrics);print(metrics.to_string(index=False))
if __name__=='__main__':main()
