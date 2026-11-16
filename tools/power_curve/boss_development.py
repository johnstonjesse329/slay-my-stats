"""Forward-only development features before bosses; never read final deck/relics.
Not a full-deck reconstruction. Evaluates added information over recent performance.
"""
import collections,json
import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,roc_auc_score
import boss_readiness as b
OUT=b.OUT/'development'

def cid(card):return card.get('id') if isinstance(card,dict) else card

def ledger(raw,catalog):
 held=collections.Counter();totals=collections.Counter();out={}
 for ai,points in enumerate(raw.get('map_point_history',[])):
  ordinal=0
  for point in points:
   if point.get('map_point_type')=='boss':
    ordinal+=1
    if ordinal==1:
     x=dict(totals);x['tracked_acquired_copies']=sum(held.values())
     for name in ['Attack','Skill','Power','Curse','Status']:x['acquired_'+name]=sum(n for c,n in held.items() if catalog.get(c,{}).get('Type')==name)
     known=[catalog[c].get('Cost') for c,n in held.items() for _ in range(n) if c in catalog and isinstance(catalog[c].get('Cost'),(int,float)) and catalog[c]['Cost']>=0]
     x['catalog_known_fraction']=sum(n for c,n in held.items() if c in catalog)/max(1,sum(held.values()))
     x['acquired_mean_cost']=float(np.mean(known)) if known else 0
     out[ai+1]=x
   s=point.get('player_stats',[{}])[0]
   # cards_gained is the canonical acquisition field; do not also count picked choices.
   for c in s.get('cards_gained',[]):
    key=cid(c)
    if key:held[key]+=1;totals['acquisitions']+=1
   for c in s.get('cards_removed',[]):
    key=cid(c);totals['removals']+=1
    if held[key]>0:held[key]-=1
    else:totals['untracked_removals']+=1
   for t in s.get('cards_transformed',[]):
    key=cid(t.get('original_card',{}));totals['transformations']+=1
    if held[key]>0:held[key]-=1
    else:totals['untracked_transformations']+=1
    # New card is deliberately not inferred here; cards_gained may carry it.
   totals['upgrade_events']+=len(s.get('upgraded_cards',[]))
 return out

def main():
 OUT.mkdir(exist_ok=True);rows,_=b.dataset();rows=[r for r in rows if r['task']=='boss_sequence'];catalog={'CARD.'+c['Entry']:c for c in json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'))['Cards']};ledgers={}
 for (sid,ts),raw in b.ar.g.load().items():
  rid=b.ar.pseudonym(f'{sid}:{ts}')
  for act,x in ledger(raw,catalog).items():ledgers[rid,act]=x
 times=sorted({r['ts'] for r in rows});predictions=[]
 splits={'forward_time':[],'player_holdout':[]}
 for lo,hi in [(.4,.6),(.6,.8),(.8,1.)]:
  start=times[int(len(times)*lo)];end=times[int(len(times)*hi)] if hi<1 else max(times)+1
  splits['forward_time'].append(([r for r in rows if r['ts']<start],[r for r in rows if start<=r['ts']<end]))
 for player in sorted({r['player'] for r in rows}):splits['player_holdout'].append(([r for r in rows if r['player']!=player],[r for r in rows if r['player']==player]))
 for split,folds in splits.items():
  for fold,(train,test) in enumerate(folds):
   fights={}
   for r in train:
    for i,f in enumerate(r['history']):fights[r['run'],r['act'],i]=f
   ref=b.ar.reference(list(fights.values()),{r['run'] for r in train})
   for model in ['performance','development']:
    def feats(r):
     x=b.feats(r,ref,'performance');x['healing_rule']='A2+' if r['asc']>=2 else 'A0-1'
     if model=='development':x.update(ledgers.get((r['run'],r['act']),{}))
     return x
    clf=make_pipeline(DictVectorizer(),StandardScaler(with_mean=False),LogisticRegression(C=.1,max_iter=2000))
    clf.fit([feats(r) for r in train],[r['clear'] for r in train]);probs=clf.predict_proba([feats(r) for r in test])[:,1]
    for r,p in zip(test,probs):predictions.append({k:r[k] for k in ['run','player','act','tier','clear']}|dict(split=split,fold=fold,model=model,p=float(p)))
  print(split,'done',flush=True)
 p=pd.DataFrame(predictions);p.to_csv(OUT/'predictions.csv',index=False);metrics=[];cis=[];rng=np.random.default_rng(42)
 for (split,model),d in p.groupby(['split','model']):metrics.append(dict(split=split,model=model,n=len(d),brier=brier_score_loss(d.clear,d.p),auc=roc_auc_score(d.clear,d.p)))
 for split,d in p.groupby('split'):
  q=d.pivot(index=['run','act','clear'],columns='model',values='p').reset_index();q['delta']=(q.development-q.clear)**2-(q.performance-q.clear)**2
  g=q.groupby('run').delta.agg(['sum','count']);ix=rng.integers(0,len(g),(2000,len(g)));vals=g['sum'].to_numpy()[ix].sum(axis=1)/g['count'].to_numpy()[ix].sum(axis=1)
  cis.append(dict(split=split,delta=q.delta.mean(),low=np.quantile(vals,.025),high=np.quantile(vals,.975)))
 pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False);pd.DataFrame(cis).to_csv(OUT/'paired_uncertainty.csv',index=False)
 print(pd.DataFrame(metrics).to_string(index=False));print(pd.DataFrame(cis).to_string(index=False))
 audit=pd.DataFrame([dict(run=run,act=act,**x) for (run,act),x in ledgers.items()]);audit.to_csv(OUT/'ledger_audit.csv',index=False)
if __name__=='__main__':main()
