"""Nested calibration: only training-run predictions fit the probability correction."""
import json
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
import boss_readiness as b

def logit(p):
 p=np.clip(p,1e-5,1-1e-5);return np.log(p/(1-p)).reshape(-1,1)

def calibrate(train,test,scheme):
 idx=np.arange(len(train));ys=[];ps=[]
 if scheme=='forward_time':
  times=sorted({r['ts'] for r in train});ts=np.array([r['ts'] for r in train]);splits=[]
  for lo,hi in [(.4,.6),(.6,.8),(.8,1.)]:
   start=times[int(len(times)*lo)];end=times[int(len(times)*hi)] if hi<1 else max(times)+1
   splits.append((idx[ts<start],idx[(ts>=start)&(ts<end)]))
 else:
  splits=GroupKFold(3).split(idx,groups=[r['player'] for r in train])
 for tr,te in splits:
  inner_train=[train[i] for i in tr];inner_test=[train[i] for i in te]
  assert not {r['run'] for r in inner_train}&{r['run'] for r in inner_test}
  pred=b.fit_predict(inner_train,inner_test,'performance');ps.extend(pred);ys.extend(r['clear'] for r in inner_test)
 cal=LogisticRegression(C=1,max_iter=1000).fit(logit(ps),ys)
 raw=b.fit_predict(train,test,'performance')
 return cal.predict_proba(logit(raw))[:,1],float(cal.coef_[0,0]),float(cal.intercept_[0])

def main():
 rows,_=b.dataset();rows=[r for r in rows if r['task']=='boss_sequence'];idx=np.arange(len(rows));out=[];params=[]
 splits={'player_holdout':[(np.array([i for i,r in enumerate(rows) if r['player']!=p]),np.array([i for i,r in enumerate(rows) if r['player']==p])) for p in sorted({r['player'] for r in rows})]}
 times=sorted({r['ts'] for r in rows});ts=np.array([r['ts'] for r in rows]);splits['forward_time']=[]
 for lo,hi in [(.4,.6),(.6,.8),(.8,1.)]:
  start=times[int(len(times)*lo)];end=times[int(len(times)*hi)] if hi<1 else max(times)+1
  splits['forward_time'].append((idx[ts<start],idx[(ts>=start)&(ts<end)]))
 for split,folds in splits.items():
  for fold,(tr,te) in enumerate(folds):
   train=[rows[i] for i in tr];test=[rows[i] for i in te]
   assert not {r['run'] for r in train}&{r['run'] for r in test}
   pred,slope,intercept=calibrate(train,test,split);params.append(dict(split=split,fold=fold,slope=slope,intercept=intercept))
   for r,p in zip(test,pred):out.append({k:r[k] for k in ['run','player','act','tier','boss','ordinal','clear','hp','maxhp']}|dict(task='boss_sequence',split=split,fold=fold,model='calibrated',p=float(p)))
   print(split,fold,'done',flush=True)
 pd.DataFrame(out).to_csv(b.OUT/'calibrated_predictions.csv',index=False);pd.DataFrame(params).to_csv(b.OUT/'calibration_parameters.csv',index=False)
if __name__=='__main__':main()
