"""Two-stage checkpoint experiment: reach boss then clear boss sequence.
Conditional boss model uses checkpoint features, never future boss-entry state.
"""
import collections,html,json
import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,roc_auc_score
import act_readiness as a
from act_targets import wilson
OUT=a.OUT/'path_to_boss'

def features(r,ref,level):
 x=a.features(r,ref,'trend' if level=='performance' else 'baseline')
 x['healing_rule']='A2+' if r['asc']>=2 else 'A0-1'
 x['act_healing_rule']=f"{r['act']}/{x['healing_rule']}"
 return x

def predict(train,test,ref,level,label):
 y=[r[label] for r in train]
 if len(set(y))<2:return np.full(len(test),np.mean(y))
 clf=make_pipeline(DictVectorizer(),StandardScaler(with_mean=False),LogisticRegression(C=.1,max_iter=2000))
 clf.fit([features(r,ref,level) for r in train],y)
 return clf.predict_proba([features(r,ref,level) for r in test])[:,1]

def dataset():
 rows,fights,audit=a.dataset();labels={}
 for (sid,ts),raw in a.g.load().items():
  rid=a.pseudonym(f'{sid}:{ts}')
  for i,points in enumerate(raw.get('map_point_history',[])):
   labels[rid,i+1]=int(any(p.get('map_point_type')=='boss' for p in points))
 out=[r|dict(reached=labels[r['run'],r['act']]) for r in rows if r['fight_index'] in [3,6]]
 assert all(r['clear']<=r['reached'] for r in out)
 return out,fights,audit

def main():
 OUT.mkdir(exist_ok=True);rows,fights,audit=dataset();outputs=[]
 times=sorted({r['ts'] for r in rows})
 for cp in [3,6]:
  data=[r for r in rows if r['fight_index']==cp]
  splits={'forward_time':[],'player_holdout':[]}
  for lo,hi in [(.4,.6),(.6,.8),(.8,1.)]:
   start=times[int(len(times)*lo)];end=times[int(len(times)*hi)] if hi<1 else max(times)+1
   splits['forward_time'].append(([r for r in data if r['ts']<start],[r for r in data if start<=r['ts']<end]))
  for player in sorted({r['player'] for r in data}):splits['player_holdout'].append(([r for r in data if r['player']!=player],[r for r in data if r['player']==player]))
  for split,folds in splits.items():
   for fold,(train,test) in enumerate(folds):
    assert not {r['run'] for r in train}&{r['run'] for r in test}
    ref=a.reference(fights,{r['run'] for r in train})
    for level in ['baseline','performance']:
     reach=predict(train,test,ref,level,'reached')
     clear_given_reach=predict([r for r in train if r['reached']],test,ref,level,'clear')
     direct=predict(train,test,ref,level,'clear')
     for r,pr,pc,pd_ in zip(test,reach,clear_given_reach,direct):outputs.append({k:r[k] for k in ['run','player','act','asc','tier','fight_index','hp','maxhp','clear','reached']}|dict(split=split,fold=fold,model=level,reach_p=float(pr),boss_conditional_p=float(pc),product_p=float(pr*pc),direct_p=float(pd_)))
   print(cp,split,'done',flush=True)
 p=pd.DataFrame(outputs);p.to_csv(OUT/'predictions.csv',index=False);metrics=[];confidence=[]
 for keys,d in p.groupby(['fight_index','split','model']):
  common=dict(zip(['checkpoint','split','model'],keys))
  for endpoint,col,target in [('reach','reach_p','reached'),('boss_given_reach','boss_conditional_p','clear'),('sequence_product','product_p','clear'),('sequence_direct','direct_p','clear')]:
   g=d[d.reached==1] if endpoint=='boss_given_reach' else d
   metrics.append(common|dict(endpoint=endpoint,n=len(g),base_rate=g[target].mean(),brier=brier_score_loss(g[target],g[col]),auc=roc_auc_score(g[target],g[col])))
   for threshold in [.8,.9,.95]:
    h=g[g[col]>=threshold];k=int(h[target].sum());low,high=wilson(k,len(h))
    confidence.append(common|dict(endpoint=endpoint,threshold=threshold,n=len(h),wins=k,rate=h[target].mean(),low=low,high=high,players=h.player.nunique(),predicted=h[col].mean()))
 m=pd.DataFrame(metrics);c=pd.DataFrame(confidence);m.to_csv(OUT/'metrics.csv',index=False);c.to_csv(OUT/'confidence.csv',index=False)
 # Paired run bootstrap for the incremental performance and factorization claims.
 uncertainty=[];rng=np.random.default_rng(42)
 for (cp,split),d in p.groupby(['fight_index','split']):
  q=d.pivot(index=['run','act','clear','reached'],columns='model',values=['reach_p','direct_p','product_p'])
  for claim,delta in [('performance_for_clear',(q['direct_p','performance']-q.index.get_level_values('clear'))**2-(q['direct_p','baseline']-q.index.get_level_values('clear'))**2),('product_vs_direct',(q['product_p','performance']-q.index.get_level_values('clear'))**2-(q['direct_p','performance']-q.index.get_level_values('clear'))**2)]:
   g=delta.groupby(level='run').agg(['sum','count']);ix=rng.integers(0,len(g),(2000,len(g)));bs=g['sum'].to_numpy()[ix].sum(axis=1)/g['count'].to_numpy()[ix].sum(axis=1)
   uncertainty.append(dict(checkpoint=cp,split=split,claim=claim,delta=delta.mean(),low=np.quantile(bs,.025),high=np.quantile(bs,.975)))
 u=pd.DataFrame(uncertainty);u.to_csv(OUT/'paired_uncertainty.csv',index=False)
 print(m.to_string(index=False));print(c[(c.model=='performance')&(c.threshold==.9)].to_string(index=False));print(u.to_string(index=False))
 notes='''# Reaching and clearing the boss: fixed-checkpoint test

Solo accepted standard core-character runs only. Outcomes are boss arrival and full act boss-sequence clearance (both bosses at A10). At completed non-boss fight 3 and fight 6, train: (1) arrival probability; (2) clearance conditional on arrival, using the same early-checkpoint inputs; (3) direct sequence clearance. The product of 1 and 2 is compared with 3. No future boss identity, boss-entry HP, future deck, or future route enters features. Conditional-on-arrival training labels are legitimate outcomes, not features; estimates still depend on the observed player/route policy.

Each run-act contributes one observation per checkpoint. Baseline contains observed current HP, character, act/difficulty, exact ascension, build and cumulative A2+ healing indicator. Performance adds only completed current-act fight measures. Fixed chronological windows and player holdouts are exploratory historical tests. Start time is not upload availability; pausing and delayed uploads remain limitations. Only seven players. No probability calibration was fit in this experiment. A product of two imperfect models is not automatically better calibrated.

Intervals for rates are unclustered Wilson intervals. Paired error intervals resample whole runs from fixed held-out predictions and omit model-refitting and player-population uncertainty. Multiple exploratory comparisons have not been corrected. An inferred survival probability must not be displayed as objective deck power.
'''
 (OUT/'review.md').write_text(notes,encoding='utf-8')
 (OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Path to boss evidence</title><style>body{font:16px/1.6 system-ui;margin:35px}pre{white-space:pre-wrap}table{border-collapse:collapse;font-size:13px}td,th{padding:6px;border:1px solid #ddd}</style><pre>'+html.escape(notes)+'</pre><h2>Paired comparisons</h2>'+u.to_html(index=False)+'<h2>Model error</h2>'+m.to_html(index=False)+'<h2>Selected confidence at 90%</h2>'+c[(c.model=='performance')&(c.threshold==.9)].to_html(index=False),encoding='utf-8')
if __name__=='__main__':main()
