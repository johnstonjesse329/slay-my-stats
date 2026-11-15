"""Fixed nonlinear-interaction sensitivity on existing snapshot only.
No tuning of hyperparameters against the reported held-out results.
"""
import json,html
import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss,roc_auc_score
import six_character_boss_study as current
import boss_readiness as b
import boss_development as dev
from ablate_boss_development import COMPOSITION
from act_targets import wilson
OUT=current.OUT/'interactions'

def main():
 OUT.mkdir(exist_ok=True);rows,_=current.dataset();rows=[r for r in rows if r['task']=='boss_sequence'];catalog={'CARD.'+c['Entry']:c for c in json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'))['Cards']};ledgers={}
 for (sid,ts),raw in b.ar.g.load().items():
  for act,x in dev.ledger(raw,catalog).items():ledgers[b.ar.pseudonym(f'{sid}:{ts}'),act]={k:float(x.get(k,0)) for k in COMPOSITION}
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
   for variant in ['linear_composition','tree_health','tree_composition']:
    def features(r):
     x=b.feats(r,ref,'health' if variant=='tree_health' else 'performance');x['healing_rule']='A2+' if r['asc']>=2 else 'A0-1'
     if variant!='tree_health':x.update(ledgers[r['run'],r['act']])
     return x
    vector=DictVectorizer(sparse=False);tr=vector.fit_transform([features(r) for r in train]);te=vector.transform([features(r) for r in test]);y=[r['clear'] for r in train]
    if variant.startswith('linear'):
     scaler=StandardScaler();tr=scaler.fit_transform(tr);te=scaler.transform(te);model=LogisticRegression(C=.1,max_iter=2000)
    else:model=HistGradientBoostingClassifier(max_iter=150,max_depth=3,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=42)
    model.fit(tr,y);probs=model.predict_proba(te)[:,1]
    for r,p in zip(test,probs):output.append({k:r[k] for k in ['run','player','act','asc','char','clear']}|dict(split=split,fold=fold,model=variant,p=float(p)))
   print(split,fold,'done',flush=True)
 p=pd.DataFrame(output);p.to_csv(OUT/'predictions.csv',index=False);metrics=[];confidence=[];rng=np.random.default_rng(42);paired=[]
 for keys,d in p.groupby(['split','model']):
  metrics.append(dict(split=keys[0],model=keys[1],n=len(d),brier=brier_score_loss(d.clear,d.p),auc=roc_auc_score(d.clear,d.p)))
  d=d.copy();d['difficulty']=d.asc.map(lambda x:'A0-1' if x<2 else 'A2-7' if x<8 else f'A{x}')
  for dim in ['all','difficulty','player']:
   groups=[('all',d)] if dim=='all' else d.groupby(dim)
   for value,g in groups:
    h=g[g.p>=.9];n=len(h);k=int(h.clear.sum());lo,hi=wilson(k,n)
    confidence.append(dict(split=keys[0],model=keys[1],dimension=dim,value=value,eligible=len(g),selected=n,wins=k,rate=h.clear.mean(),low=lo,high=hi,mean_prediction=h.p.mean()))
 for split,d in p.groupby('split'):
  q=d.pivot(index=['run','act','clear'],columns='model',values='p').reset_index()
  for model,baseline in [('tree_composition','linear_composition'),('tree_composition','tree_health')]:
   q['delta']=(q[model]-q.clear)**2-(q[baseline]-q.clear)**2;g=q.groupby('run').delta.agg(['sum','count']);ix=rng.integers(0,len(g),(2000,len(g)));bs=g['sum'].to_numpy()[ix].sum(axis=1)/g['count'].to_numpy()[ix].sum(axis=1)
   paired.append(dict(split=split,comparison=f'{model} minus {baseline}',delta=q.delta.mean(),low=np.quantile(bs,.025),high=np.quantile(bs,.975)))
 m=pd.DataFrame(metrics);c=pd.DataFrame(confidence);u=pd.DataFrame(paired);m.to_csv(OUT/'metrics.csv',index=False);c.to_csv(OUT/'confidence.csv',index=False);u.to_csv(OUT/'paired_uncertainty.csv',index=False)
 print(m.to_string(index=False));print(u.to_string(index=False));print(c[(c.dimension=='all')|(c.model=='tree_composition')&(c.dimension=='difficulty')].to_string(index=False))
 notes='''# Nonlinear interaction sensitivity

Existing six-character solo snapshot only. Fixed regularized shallow boosted trees test interactions the earlier linear model cannot express. Health/context and composition/performance tree variants are compared with linear composition. Settings fixed before this run: depth 3, 150 iterations, learning rate .05, minimum leaf 30, L2 10, no early-stopping row split or parameter search. Preprocessing and encounter references fit on training runs only; whole-run membership is disjoint. Same forward-time and player-holdout definitions as earlier work. Player identity and future state are not features.

This remains exploratory historical evidence, not an untouched prospective test. Confidence subsets use fixed >=90% threshold. Wilson intervals ignore player clustering; paired intervals resample whole runs from fixed predictions and omit model-refitting uncertainty. Correlated repeated model comparisons do not prove that the best observed family will generalize. This test can identify model limitations using available data; it cannot manufacture sample diversity or measured high-ascension damage/block evidence.
'''
 (OUT/'review.md').write_text(notes,encoding='utf-8');(OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Interaction sensitivity</title><style>body{font:16px/1.6 system-ui;margin:30px}pre{white-space:pre-wrap}td,th{border:1px solid #ddd;padding:6px}table{border-collapse:collapse;font-size:13px}</style><pre>'+html.escape(notes)+'</pre>'+m.to_html(index=False)+u.to_html(index=False)+c.to_html(index=False),encoding='utf-8')
if __name__=='__main__':main()
