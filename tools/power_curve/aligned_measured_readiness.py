"""Conservative local alignment for measured pre-boss windows.
No target-boss result or future combat is a predictor.
"""
import collections,gzip,json,html
import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.metrics import brier_score_loss,roc_auc_score
import six_character_boss_study as current
import boss_readiness as b
import telemetry_report as tr
from measured_boss_readiness import measured_features
OUT=current.OUT/'aligned_measurements'

def prior_window(logged,target_enc,raw_predecessors):
 positions=[i for i,f in enumerate(logged) if f.get('enc')==target_enc]
 if len(positions)!=1:return None,'ambiguous_or_missing_boss'
 index=positions[0]
 if index<3 or len(raw_predecessors)<3:return None,'insufficient_predecessors'
 window=logged[index-3:index]
 if [f['enc'] for f in window]!=raw_predecessors[-3:]:return None,'predecessor_mismatch'
 if not all(f.get('won') for f in window):return None,'prior_fight_not_won'
 for f in window:
  if f.get('hp0') is None or f.get('hp1') is None or f['hp0']-f['hp1']!=f['hp_in']-f['hp_out']:return None,'hp_flow_mismatch'
 return window,'accepted'

def main():
 OUT.mkdir(exist_ok=True);rows,_=current.dataset();rows=[r for r in rows if r['task']=='boss_sequence'];targets={(r['run'],r['act']):r for r in rows};raw=b.ar.g.load();tr.TELEMETRY=current.SOURCE/'telemetry';logs,_=tr.load_logs(raw);observations=[];audit=collections.Counter()
 for (sid,ts),log in logs.items():
  if log.get('truncated'):audit['truncated_logs']+=1;continue
  rid=b.ar.pseudonym(f'{sid}:{ts}');r=raw.get((sid,ts),{})
  for ai,points in enumerate(r.get('map_point_history',[])):
   target=targets.get((rid,ai+1))
   if not target:continue
   predecessors=[]
   for point in points:
    if point.get('map_point_type')=='boss':break
    predecessors.extend(room['model_id'] for room in point.get('rooms',[]) if room.get('turns_taken') and room.get('monster_ids'))
   window,reason=prior_window(log.get('fights',[]),target['boss'],predecessors);audit[reason]+=1
   if window is None:continue
   observations.append({k:target[k] for k in ['run','player','ts','act','asc','char','boss','hp','maxhp','clear']}|measured_features(window))
 d=pd.DataFrame(observations);d.to_csv(OUT/'observations.csv',index=False);(OUT/'audit.json').write_text(json.dumps(dict(audit),indent=2));print(dict(audit),flush=True);data=d.to_dict('records');idx=np.arange(len(data));groups=d.run.to_numpy();splits={'run_holdout':list(GroupKFold(min(5,len(set(groups)))).split(idx,groups=groups)),'player_holdout':[]}
 for player in sorted(d.player.unique()):
  train=idx[d.player.to_numpy()!=player];test=idx[d.player.to_numpy()==player]
  if len(train):splits['player_holdout'].append((train,test))
 output=[]
 for split,folds in splits.items():
  for fold,(train,test) in enumerate(folds):
   assert not set(groups[train])&set(groups[test])
   for variant in ['health','measured']:
    def features(r):
     x=dict(act=str(r['act']),asc=r['asc'],character=r['char'],boss=r['boss'],hp=r['hp'],maxhp=r['maxhp'],hp_fraction=r['hp']/r['maxhp'],healing_rule='A2+' if r['asc']>=2 else 'A0-1')
     if variant=='measured':x.update({k:v for k,v in r.items() if k.startswith('measured_')})
     return x
    y=[data[i]['clear'] for i in train];constant=len(set(y))<2
    if constant:probs=np.full(len(test),np.mean(y))
    else:
     clf=make_pipeline(DictVectorizer(),StandardScaler(with_mean=False),LogisticRegression(C=.1,max_iter=2000)).fit([features(data[i]) for i in train],y);probs=clf.predict_proba([features(data[i]) for i in test])[:,1]
    for i,p in zip(test,probs):output.append({k:data[i][k] for k in ['run','player','act','asc','clear']}|dict(split=split,fold=fold,model=variant,p=float(p),constant_training_outcomes=constant))
 p=pd.DataFrame(output);p.to_csv(OUT/'predictions.csv',index=False);metrics=[]
 for (split,variant),g in p.groupby(['split','model']):metrics.append(dict(split=split,model=variant,n=len(g),runs=g.run.nunique(),players=g.player.nunique(),brier=brier_score_loss(g.clear,g.p),auc=roc_auc_score(g.clear,g.p) if g.clear.nunique()==2 else None,constant_predictions=int(g.constant_training_outcomes.sum())))
 m=pd.DataFrame(metrics);m.to_csv(OUT/'metrics.csv',index=False);print(m.to_string(index=False));print('by player',d.groupby('player').clear.agg(['count','sum']).to_dict())
 notes='''# Local pre-boss measurement alignment

Uses a unique target-boss start in the log and exact ordered matching of the preceding three logged encounters to the saved run's preceding three encounters. All predecessor fights must be won and satisfy HP-flow balance. Truncated logs, duplicate target-boss encounters, missing windows and mismatched predecessors are rejected. Nothing after target-boss start is used as a predictor, including its turns, damage or outcome. Target identity is known at boss entry. Raw preceding-room HP supplies current survival state.

This allows a locally complete pre-boss window from an otherwise partial log. It does not resolve retries with duplicate target encounters, merge attempts, or claim complete run recording. Selection can still depend on recording quality. Both exact and local alignment studies are exploratory sensitivity tests, not independent datasets.

Same small regularized logistic settings as the strict measured test. Boss identity is included here in both baseline and measured variants. No full-deck features enter. Only two players are available in the broader measured snapshot; whole-player folds may have one-class training outcomes, reported as constant predictions rather than pretending a model learned a distinction. No universal mechanical damage/block target follows from these metrics.
'''
 (OUT/'review.md').write_text(notes,encoding='utf-8');(OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Aligned pre-boss measurements</title><style>body{font:16px/1.6 system-ui;margin:30px}pre{white-space:pre-wrap}td,th{padding:6px;border:1px solid #ddd}table{border-collapse:collapse}</style><pre>'+html.escape(notes)+'</pre>'+m.to_html(index=False),encoding='utf-8')
if __name__=='__main__':main()
