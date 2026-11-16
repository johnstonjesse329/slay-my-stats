"""Ablation of forward development features; all variants reported.
Historical exploratory comparisons, no tuning against the test outcomes.
"""
import html,json
import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
import boss_readiness as b
import boss_development as dev
from act_targets import wilson
OUT=dev.OUT/'ablation'
PROCESS={'acquisitions','removals','untracked_removals','transformations','untracked_transformations','upgrade_events'}
COMPOSITION={'tracked_acquired_copies','acquired_Attack','acquired_Skill','acquired_Power','acquired_Curse','acquired_Status','catalog_known_fraction'}
GROUPS={'performance':set(),'process':PROCESS,'composition':COMPOSITION,'cost':{'acquired_mean_cost'},'without_upgrades':(PROCESS|COMPOSITION|{'acquired_mean_cost'})-{'upgrade_events'},'full':PROCESS|COMPOSITION|{'acquired_mean_cost'}}

def selected_features(ledger,variant):return {k:v for k,v in ledger.items() if k in GROUPS[variant]}

def main():
 OUT.mkdir(exist_ok=True);rows,_=b.dataset();rows=[r for r in rows if r['task']=='boss_sequence'];catalog={'CARD.'+c['Entry']:c for c in json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'))['Cards']};ledgers={}
 for (sid,ts),raw in b.ar.g.load().items():
  rid=b.ar.pseudonym(f'{sid}:{ts}')
  for act,x in dev.ledger(raw,catalog).items():ledgers[rid,act]=x
 times=sorted({r['ts'] for r in rows});splits={'forward_time':[],'player_holdout':[]}
 for lo,hi in [(.4,.6),(.6,.8),(.8,1.)]:
  start=times[int(len(times)*lo)];end=times[int(len(times)*hi)] if hi<1 else max(times)+1
  splits['forward_time'].append(([r for r in rows if r['ts']<start],[r for r in rows if start<=r['ts']<end]))
 for player in sorted({r['player'] for r in rows}):splits['player_holdout'].append(([r for r in rows if r['player']!=player],[r for r in rows if r['player']==player]))
 output=[]
 for split,folds in splits.items():
  for fold,(train,test) in enumerate(folds):
   assert not {r['run'] for r in train}&{r['run'] for r in test}
   fights={}
   for r in train:
    for i,f in enumerate(r['history']):fights[r['run'],r['act'],i]=f
   ref=b.ar.reference(list(fights.values()),{r['run'] for r in train})
   for model in GROUPS:
    def features(r):
     x=b.feats(r,ref,'performance');x['healing_rule']='A2+' if r['asc']>=2 else 'A0-1'
     x.update(selected_features(ledgers[r['run'],r['act']],model));return x
    clf=make_pipeline(DictVectorizer(),StandardScaler(with_mean=False),LogisticRegression(C=.1,max_iter=2000))
    clf.fit([features(r) for r in train],[r['clear'] for r in train]);prob=clf.predict_proba([features(r) for r in test])[:,1]
    for r,p in zip(test,prob):output.append({k:r[k] for k in ['run','player','act','asc','tier','boss','clear']}|dict(model=model,split=split,fold=fold,p=float(p)))
   print(split,fold,'done',flush=True)
 p=pd.DataFrame(output);p.to_csv(OUT/'predictions.csv',index=False)
 metrics=[];sub=[];rng=np.random.default_rng(42)
 for (split,model),d in p.groupby(['split','model']):metrics.append(dict(split=split,model=model,n=len(d),brier=brier_score_loss(d.clear,d.p)))
 for split,d in p[p.model.isin(['full','performance'])].groupby('split'):
  q=d.pivot(index=['run','player','act','asc','tier','clear'],columns='model',values='p').reset_index();q['delta']=(q.full-q.clear)**2-(q.performance-q.clear)**2
  q['resource_tier']=q.asc.map(lambda a:'A0-1' if a<2 else 'A2-7' if a<8 else f'A{a}')
  for dim in ['all','resource_tier','player','act']:
   groups=[('all',q)] if dim=='all' else q.groupby(dim)
   for value,g in groups:
    h=g[g.full>=.9];k=int(h.clear.sum());lo,hi=wilson(k,len(h))
    units=g.groupby('run').delta.agg(['sum','count']);ix=rng.integers(0,len(units),(2000,len(units)));bs=units['sum'].to_numpy()[ix].sum(axis=1)/units['count'].to_numpy()[ix].sum(axis=1)
    sub.append(dict(split=split,dimension=dim,value=value,n=len(g),delta=g.delta.mean(),delta_low=np.quantile(bs,.025),delta_high=np.quantile(bs,.975),selected=len(h),wins=k,rate=h.clear.mean(),low=lo,high=hi,predicted=h.full.mean(),players=h.player.nunique()))
 m=pd.DataFrame(metrics);s=pd.DataFrame(sub);m.to_csv(OUT/'metrics.csv',index=False);s.to_csv(OUT/'subgroups.csv',index=False)
 print(m.to_string(index=False));print(s[s.dimension.isin(['all','resource_tier','player'])].to_string(index=False))
 notes='''# Development feature ablation

All six fixed feature variants are reported. Performance is the health/context/recent-fight baseline with cumulative A2+ healing rule. Process adds acquisitions, removals, transformations and upgrade event counts. Composition adds partial acquired-card counts/types and coverage. Cost adds mean printed cost of acquired cards. Without-upgrades removes only the upgrade count from the full model. Full combines these groups. No final deck is read, no card identity feature is fit, and no causal importance follows from these correlated feature ablations.

Same forward-time and whole-player tests as previous experiments, using the frozen production snapshot. Whole runs never cross folds. No tuning on test outcomes; comparisons remain exploratory after repeated use of the snapshot. Seven players; bootstrap intervals resample runs from fixed predictions and omit refitting and player-population uncertainty. Multiple subgroup/ablation comparisons have not been corrected. Report effects as hypotheses for confirmation.

A0–1 and A2–7 are reported separately because player resource rules differ despite equal enemy HP/damage. A8/A9/A10 remain distinct. High-confidence groups use a fixed >=90% threshold. Counts, observed rate and mean prediction must all be considered; a pooled average cannot validate a population with poor calibration or little coverage.
'''
 (OUT/'review.md').write_text(notes,encoding='utf-8');(OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Deck development ablation</title><style>body{font:16px/1.6 system-ui;margin:30px}pre{white-space:pre-wrap}table{border-collapse:collapse;font-size:13px}td,th{padding:6px;border:1px solid #ddd}</style><pre>'+html.escape(notes)+'</pre><h2>All model variants</h2>'+m.to_html(index=False)+'<h2>Full-model subgroup evidence</h2>'+s.to_html(index=False),encoding='utf-8')
if __name__=='__main__':main()
