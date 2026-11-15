"""Direct measured damage/defense at checkpoints, no target-boss telemetry features.
Small-sample exploratory test, copied snapshot only.
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
OUT=current.OUT/'measured_mechanics'

def measured_features(fs):
 turns=sum(f['turns_n'] for f in fs)
 if turns<=0:raise ValueError('No observed turns')
 blocked=sum(f['blocked'] for f in fs);taken=sum(f['taken'] for f in fs)
 return dict(measured_damage=sum(f['dealt_removed'] for f in fs)/turns,measured_blocked=blocked/turns,measured_incoming=(blocked+taken)/turns,measured_taken=taken/turns,measured_net_hp=sum(max(0,f['hp_in']-f['hp_out']) for f in fs)/len(fs),measured_block_share=blocked/max(1,blocked+taken),measured_turns=turns/len(fs))

def main():
 OUT.mkdir(exist_ok=True);current.dataset();raw=b.ar.g.load();accepted=set()
 for path in (current.SOURCE/'users').glob('*/*.json.gz'):
  if not path.name.startswith('_'):
   for item in json.load(gzip.open(path,'rt',encoding='utf-8')).get('runs',[]):accepted.add(b.ar.signature(item['ts'],item['char'],item.get('seed')))
 roster=current.core_roster(json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8')));tr.TELEMETRY=current.SOURCE/'telemetry';logs,_=tr.load_logs(raw);rows=[];audit=collections.Counter()
 for (sid,ts),log in logs.items():
  r=raw.get((sid,ts))
  if not r or not current.eligible(r,accepted,roster)[0]:audit['ineligible_logs']+=1;continue
  if log.get('truncated'):audit['truncated']+=1;continue
  combats=[]
  for ai,points in enumerate(r['map_point_history']):
   for point in points:
    for room in point.get('rooms',[]):
     if room.get('turns_taken') and room.get('monster_ids'):combats.append((ai+1,point,room))
  fs=log.get('fights',[])
  if [f.get('enc') for f in fs]!=[q.get('model_id') for _,_,q in combats]:audit['nonexact_fight_sequence_logs']+=1;continue
  audit['exact_sequence_logs']+=1
  byact=collections.defaultdict(list)
  for f,(act,p,q) in zip(fs,combats):
   balanced=f.get('hp0') is not None and f.get('hp1') is not None and f['hp0']-f['hp1']==f['hp_in']-f['hp_out']
   audit['hp_balanced_fights' if balanced else 'hp_mismatched_fights']+=1
   byact[act].append((f,p,balanced))
  for act,entries in byact.items():
   bosses=[p for _,p,_ in entries if p.get('map_point_type')=='boss'];needed=2 if r.get('ascension',0)>=10 and act==3 else 1
   clear=int(bool(r.get('win') or any(r['map_point_history'][act:]) or len(bosses)>=needed and all(p['player_stats'][0].get('current_hp',0)>0 for p in bosses)))
   previous=[]
   for f,p,valid in entries:
    kind=p.get('map_point_type');stage='boss_entry' if kind=='boss' else f'fight{len(previous)+1}'
    if kind=='boss':window=previous[-3:];hp=f['hp0'];mx=p['player_stats'][0].get('max_hp',0)
    else:
     if not f.get('won'):break
     previous.append((f,valid));window=previous[-3:];hp=p['player_stats'][0].get('current_hp',0);mx=p['player_stats'][0].get('max_hp',0)
    if stage in ['fight3','fight6','boss_entry'] and len(window)==3 and all(v for _,v in window) and hp is not None and hp>0 and mx>0:
     rows.append(dict(run=b.ar.pseudonym(f'{sid}:{ts}'),player=b.ar.pseudonym(sid),ts=ts,stage=stage,act=act,asc=r.get('ascension',0),char=r['players'][0]['character'],hp=hp,maxhp=mx,clear=clear,**measured_features([x for x,_ in window])))
    if kind=='boss':break
 d=pd.DataFrame(rows);d.to_csv(OUT/'observations.csv',index=False);(OUT/'audit.json').write_text(json.dumps(dict(audit),indent=2));print(dict(audit),flush=True)
 output=[]
 for stage,g in d.groupby('stage'):
  data=g.to_dict('records');idx=np.arange(len(data));groups=np.array([r['run'] for r in data]);splits={'run_holdout':list(GroupKFold(min(5,len(set(groups)))).split(idx,groups=groups)),'player_holdout':[]}
  for player in sorted({r['player'] for r in data}):
   train_idx=idx[np.array([r['player']!=player for r in data])];test_idx=idx[np.array([r['player']==player for r in data])]
   if len(train_idx):splits['player_holdout'].append((train_idx,test_idx))
  for split,folds in splits.items():
   for fold,(train,test) in enumerate(folds):
    assert not set(groups[train])&set(groups[test])
    for model in ['health','measured']:
     def features(r):
      x=dict(act=str(r['act']),asc=r['asc'],char=r['char'],hp=r['hp'],maxhp=r['maxhp'],hp_fraction=r['hp']/r['maxhp'],healing_rule='A2+' if r['asc']>=2 else 'A0-1')
      if model=='measured':x.update({k:v for k,v in r.items() if k.startswith('measured_')})
      return x
     y=[data[i]['clear'] for i in train]
     if len(set(y))<2:probs=np.full(len(test),np.mean(y));constant=True
     else:
      clf=make_pipeline(DictVectorizer(),StandardScaler(with_mean=False),LogisticRegression(C=.1,max_iter=2000)).fit([features(data[i]) for i in train],y);probs=clf.predict_proba([features(data[i]) for i in test])[:,1];constant=False
     for i,pred in zip(test,probs):output.append({k:data[i][k] for k in ['run','player','stage','act','asc','clear']}|dict(split=split,model=model,fold=fold,p=float(pred),constant_training_outcomes=constant))
 p=pd.DataFrame(output);p.to_csv(OUT/'predictions.csv',index=False);metrics=[]
 for keys,g in p.groupby(['stage','split','model']):metrics.append(dict(stage=keys[0],split=keys[1],model=keys[2],n=len(g),runs=g.run.nunique(),players=g.player.nunique(),brier=brier_score_loss(g.clear,g.p),auc=roc_auc_score(g.clear,g.p) if g.clear.nunique()==2 else None,constant_training_predictions=int(g.constant_training_outcomes.sum())))
 m=pd.DataFrame(metrics);m.to_csv(OUT/'metrics.csv',index=False);print(m.to_string(index=False))
 notes='''# Measured damage and defense experiment

Uses eligible solo non-abandoned copied logs with exact encounter sequence agreement between raw run and telemetry. Recent-three-fight predictor window must satisfy logged HP-flow balance. No target-boss damage, block or outcome enters features. At boss entry, HP comes from the target fight's start event, before damage. Other predictors come only from completed earlier fights. Target labels come separately from the raw run's full act outcome. Both final bosses would be required at A10, but this cohort has no high-ascension logs.

Damage measure is actual HP removed by attributed hit plus non-hit damage (dealt_removed), excluding unexplained enemy disappearance and attempted/overkill damage. Defense is damage actually absorbed by block, not block generated or hypothetical block capacity. Both are conditional on enemies and decisions; fast kills reduce the amount of block needed. Incoming is actual blocked plus taken enemy damage, not enemy theoretical intent. Net HP spent includes costs and recorded healing and is distinct from enemy damage. These cannot be treated as independent deck capacities just because they are measured.

Small regularized logistic comparisons add these observations to HP/context. Whole-run folds and whole-player folds prevent related acts crossing train/test. All measured rows in a window precede the target; full-log sequence/quality filtering is a retrospective quality restriction and could select better recordings. Model settings fixed, not tuned on the small sample. Two players cannot establish population generalization, and if a training fold contains only wins/losses, output records the constant-prediction fallback explicitly. This experiment tests evidence in the available logs; it is not a universal damage/block target calibration.
'''
 (OUT/'review.md').write_text(notes,encoding='utf-8');(OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Measured mechanics</title><style>body{font:16px/1.6 system-ui;margin:30px}pre{white-space:pre-wrap}td,th{padding:6px;border:1px solid #ddd}table{border-collapse:collapse}</style><pre>'+html.escape(notes)+'</pre>'+m.to_html(index=False),encoding='utf-8')
if __name__=='__main__':main()
