"""Sensitivity to cumulative A2 healing rule and inherited act-entry HP.
No target-fight state is used. Frozen solo snapshot, forward-time tests.
"""
import collections
import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,roc_auc_score
import boss_readiness as b
OUT=b.OUT/'healing'

def healing_group(asc):return 'A2+' if asc>=2 else 'A0-1'

def extract_entries(raw):
 out={}
 for ai,points in enumerate(raw.get('map_point_history',[])):
  # The first room's recorded HP (usually the Ancient) is an observed act-entry
  # state. Never infer it from a later boss or assume full healing.
  if not points:continue
  first=points[0];s=first.get('player_stats',[{}])[0]
  if any(r.get('turns_taken') for r in first.get('rooms',[])):continue
  if s.get('max_hp',0)>0 and 'current_hp' in s:out[ai+1]=(s['current_hp'],s['max_hp'])
 return out

def fit(train,test,entries,model):
 fights={}
 for r in train:
  for i,f in enumerate(r['history']):fights[r['run'],r['act'],i]=f
 ref=b.ar.reference(list(fights.values()),{r['run'] for r in train})
 def features(r):
  level='health' if model=='health_rule' else 'performance'
  x=b.feats(r,ref,level)
  if model!='original':
   x['healing_rule']=healing_group(r['asc'])
   x['act_healing_rule']=f"{r['act']}/{healing_group(r['asc'])}"
  if model in ['entry_state','performance_no_current_hp']:
   entry=entries.get((r['run'],r['act']))
   x['entry_available']=int(entry is not None)
   if entry:x['act_entry_hp_fraction']=entry[0]/entry[1]
  if model=='performance_no_current_hp':
   for k in ['hp','maxhp','hp_fraction']:x.pop(k,None)
  return x
 clf=make_pipeline(DictVectorizer(),StandardScaler(with_mean=False),LogisticRegression(C=.1,max_iter=2000))
 clf.fit([features(r) for r in train],[r['clear'] for r in train])
 return clf.predict_proba([features(r) for r in test])[:,1]

def main():
 OUT.mkdir(exist_ok=True);rows,_=b.dataset();rows=[r for r in rows if r['task']=='boss_sequence'];entries={}
 for (sid,ts),raw in b.ar.g.load().items():
  rid=b.ar.pseudonym(f'{sid}:{ts}')
  for act,value in extract_entries(raw).items():entries[rid,act]=value
 times=sorted({r['ts'] for r in rows});out=[]
 for fold,(lo,hi) in enumerate([(.4,.6),(.6,.8),(.8,1.)]):
  start=times[int(len(times)*lo)];end=times[int(len(times)*hi)] if hi<1 else max(times)+1
  tr=[r for r in rows if r['ts']<start];te=[r for r in rows if start<=r['ts']<end]
  for model in ['original','health_rule','performance_rule','entry_state','performance_no_current_hp']:
   pred=fit(tr,te,entries,model)
   for r,p in zip(te,pred):out.append({k:r[k] for k in ['run','act','asc','tier','clear','hp','maxhp']}|dict(model=model,fold=fold,p=p,healing_rule=healing_group(r['asc']),entry_available=int((r['run'],r['act']) in entries)))
  print('window',fold,'done',flush=True)
 p=pd.DataFrame(out);p.to_csv(OUT/'predictions.csv',index=False);metrics=[]
 for (model,rule),d in p.groupby(['model','healing_rule']):metrics.append(dict(model=model,rule=rule,n=len(d),brier=brier_score_loss(d.clear,d.p),auc=roc_auc_score(d.clear,d.p)))
 for model,d in p.groupby('model'):metrics.append(dict(model=model,rule='all',n=len(d),brier=brier_score_loss(d.clear,d.p),auc=roc_auc_score(d.clear,d.p)))
 m=pd.DataFrame(metrics);m.to_csv(OUT/'metrics.csv',index=False);print(m.to_string(index=False));print('entry coverage',p.entry_available.mean())
 # Paired fixed-prediction run bootstrap; negative means improvement.
 q=p.pivot(index=['run','act','clear'],columns='model',values='p').reset_index();rng=np.random.default_rng(42);ci=[]
 for model,base in [('performance_rule','original'),('entry_state','performance_rule'),('performance_rule','health_rule')]:
  q['delta']=(q[model]-q.clear)**2-(q[base]-q.clear)**2;g=q.groupby('run').delta.agg(['sum','count']);ix=rng.integers(0,len(g),(2000,len(g)))
  vals=g['sum'].to_numpy()[ix].sum(axis=1)/g['count'].to_numpy()[ix].sum(axis=1)
  ci.append(dict(comparison=f'{model} minus {base}',delta=q.delta.mean(),low=np.quantile(vals,.025),high=np.quantile(vals,.975)))
 pd.DataFrame(ci).to_csv(OUT/'paired_uncertainty.csv',index=False);print(pd.DataFrame(ci).to_string(index=False))
if __name__=='__main__':main()
