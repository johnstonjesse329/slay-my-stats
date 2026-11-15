"""Paired run-cluster bootstrap of fixed held-out predictions, plus subgroup audit."""
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
OUT=Path(__file__).resolve().parents[2]/'local_data/act_validation'
p=pd.read_csv(OUT/'predictions.csv')
results=[]
rng=np.random.default_rng(42)
for split,d in p.groupby('split'):
    q=d.pivot(index=['run','act','fight_index','clear'],columns='model',values='p').reset_index()
    for model in ['performance','trend']:
        other='baseline' if model=='performance' else 'performance'
        q['delta']=(q[model]-q.clear)**2-(q[other]-q.clear)**2
        acts=q.groupby(['run','act']).delta.mean().reset_index()
        units=acts.groupby('run').delta.agg(['sum','count'])
        samples=rng.integers(0,len(units),(2000,len(units)))
        b=units['sum'].to_numpy()[samples].sum(axis=1)/units['count'].to_numpy()[samples].sum(axis=1)
        results.append(dict(split=split,comparison=f'{model} minus {other}',delta=float(acts.delta.mean()),low=float(np.quantile(b,.025)),high=float(np.quantile(b,.975))))
ci=pd.DataFrame(results);ci.to_csv(OUT/'paired_uncertainty.csv',index=False)
sub=[]
for keys,d in p[p.split=='player_holdout'].groupby(['player','model']):
    w=1/d.groupby(['run','act'])['run'].transform('size')
    sub.append(dict(player=keys[0],model=keys[1],runs=d.run.nunique(),brier=np.average((d.p-d.clear)**2,weights=w)))
sub=pd.DataFrame(sub);sub.to_csv(OUT/'player_metrics.csv',index=False)
strata=[]
for keys,d in p[p.split=='player_holdout'].groupby(['tier','act','model']):
    w=1/d.groupby(['run','act'])['run'].transform('size')
    strata.append(dict(tier=keys[0],act=keys[1],model=keys[2],runs=d.run.nunique(),brier=np.average((d.p-d.clear)**2,weights=w),clear_rate=np.average(d.clear,weights=w)))
pd.DataFrame(strata).to_csv(OUT/'difficulty_metrics.csv',index=False)
manifest=[]
for folder in ['raw','users','telemetry']:
    for f in sorted((OUT/folder).rglob('*.gz')):
        manifest.append(dict(path=str(f.relative_to(OUT)),bytes=f.stat().st_size,sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
(OUT/'snapshot-manifest.json').write_text(json.dumps(manifest,indent=2))
print(ci.to_string(index=False))
print(sub.pivot(index='player',columns='model',values='brier').to_string())
review=OUT/'review.md'
review.write_text(review.read_text(encoding='utf-8').split('\n\n## Paired uncertainty')[0],encoding='utf-8')
with review.open('a',encoding='utf-8') as f:
    f.write('\n\n## Paired uncertainty\n\nNegative error differences favor the added features. Intervals resample whole runs (2,000 replicates) from fixed held-out predictions. They do not refit models or estimate uncertainty over a new population of players.\n\n')
    f.write(ci.to_csv(index=False))
    f.write('\nRecent performance improves average Brier error in all three validation schemes. Trend adds a substantially smaller gain. See player_metrics.csv and difficulty_metrics.csv for variation. These estimates support further investigation, not a universal damage/block target.\n')
    f.write('\n## Review decisions\n\nSolo only; multiplayer scaling and party contribution require a separate study. Held/unpublished uploads are excluded. Use the results to choose the next hypotheses: encounter-specific pace and HP-spending budgets, and boss readiness conditional on entry HP. Do not turn the current regression into a deck-power score.\n')
# A standalone report that can be opened without a notebook server.
import html
metrics=pd.read_csv(OUT/'model_metrics.csv')
text=(OUT/'review.md').read_text(encoding='utf-8')
(OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Solo act readiness review</title><style>body{font:16px/1.6 system-ui;max-width:1100px;margin:40px auto;padding:0 24px;color:#222}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ddd}img{max-width:100%}pre{white-space:pre-wrap}</style><h1>Solo act readiness: first validation</h1><p>Production snapshot · November 14, 2026 · exploratory, no site changes</p>'+metrics.to_html(index=False,float_format=lambda x:f'{x:.4f}')+'<img src="validation.png" alt="Validation error and calibration"><h2>Methods and review notes</h2><pre>'+html.escape(text)+'</pre>',encoding='utf-8')
