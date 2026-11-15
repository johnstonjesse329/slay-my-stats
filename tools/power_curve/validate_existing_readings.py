"""Validate existing OP/Hype/Mid/Rough readings on the saved solo snapshot.
Separate completed-run descriptions from earlier, outcome-blind checkpoints.
"""
import json,html
import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold
import six_character_boss_study as current
import fight_demand as fd
from act_targets import wilson
OUT=current.OUT/'existing_grade_validation'

def label(reading):return 'Unrated' if not reading else 'OP' if reading['op'] else {'ahead':'Hype','meeting':'Mid','behind':'Rough'}[reading['verdict']]

def stages(fights):
 yield 'completed_run',fights
 for act in [0,1]:
  indices=[i for i,f in enumerate(fights) if f['act']==act and f['kind']=='boss' and not f['died']]
  if indices:yield f'after_act{act+1}_boss',fights[:indices[-1]+1]
 for act in [1,2]:
  indices=[i for i,f in enumerate(fights) if f['act']==act and f['kind']!='boss' and not f['died']]
  if len(indices)>=3:yield f'act{act+1}_fight3',fights[:indices[2]+1]
  bosses=[i for i,f in enumerate(fights) if f['act']==act and f['kind']=='boss']
  if bosses:yield f'before_act{act+1}_boss',fights[:bosses[0]]

def evaluate_record(record,demand,cuts,scheme,fold):
 out=[]
 for stage,fs in stages(record['fights']):
  acts=fd.act_readings(fs,demand,cuts);reading=fd.run_reading(acts,cuts)
  act=fs[-1]['act'] if fs else 0;part=[f for f in fs if f['act']==act and not f['died']];act_reading=next((a for a in acts if a['act']==act),None)
  out.append({k:record[k] for k in ['run','player','ts','asc','character','won']}|dict(scheme=scheme,fold=fold,stage=stage,grade=label(reading),covered_fights=sum(a['fights'] for a in acts),observed_fights=len(fs),pace=reading['pace'] if reading else None,guard=reading['guard'] if reading else None,act=act+1,act_grade='Unrated' if act_reading is None else {'ahead':'Hype','meeting':'Mid','behind':'Rough'}[act_reading['verdict']],act_clear=record['act_clears'].get(act,0),act_turns_per_fight=float(np.mean([f['t'] for f in part])) if part else None,act_hp_per_fight=float(np.mean([f['taken'] for f in part])) if part else None,act_hp_per_enemy_turn=sum(f['taken'] for f in part)/sum(max(1,f['t']-1) for f in part) if part else None))
 return out

def main():
 OUT.mkdir(exist_ok=True);current.dataset();raw=current.b.ar.g.load();accepted=set()
 import gzip
 for p in (current.SOURCE/'users').glob('*/*.json.gz'):
  if not p.name.startswith('_'):
   for r in json.load(gzip.open(p,'rt',encoding='utf-8')).get('runs',[]):accepted.add(current.b.ar.signature(r['ts'],r['char'],r.get('seed')))
 catalog=json.loads((current.b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'));roster=current.core_roster(catalog);records=[]
 for (sid,ts),r in raw.items():
  if not current.eligible(r,accepted,roster)[0]:continue
  fs=fd.run_fights({0:r})
  act_clears={}
  for act,points in enumerate(r.get('map_point_history',[])):
   bosses=[p for p in points if p.get('map_point_type')=='boss'];needed=2 if r.get('ascension',0)>=10 and act==2 else 1
   act_clears[act]=int(bool(r.get('win') or any(r['map_point_history'][act+1:]) or len(bosses)>=needed and all(p['player_stats'][0].get('current_hp',0)>0 for p in bosses)))
  if fs:records.append(dict(act_clears=act_clears,run=current.b.ar.pseudonym(f'{sid}:{ts}'),player=current.b.ar.pseudonym(sid),ts=ts,asc=r.get('ascension',0),character=r['players'][0]['character'],won=int(bool(r.get('win'))),fights=fs[0]))
 baked=json.loads((current.b.ar.ROOT/'fight_demand.json').read_text());out=[]
 for r in records:out.extend(evaluate_record(r,baked['encounters'],baked['cuts'],'current_baked_baseline',0))
 idx=np.arange(len(records));schemes={'run_holdout':list(GroupKFold(5).split(idx,groups=[r['run'] for r in records])),'player_holdout':[],'forward_time':[]}
 for player in sorted({r['player'] for r in records}):schemes['player_holdout'].append((np.array([i for i,r in enumerate(records) if r['player']!=player]),np.array([i for i,r in enumerate(records) if r['player']==player])))
 times=sorted({r['ts'] for r in records});ts=np.array([r['ts'] for r in records])
 for lo,hi in [(.4,.6),(.6,.8),(.8,1.)]:
  start=times[int(len(times)*lo)];end=times[int(len(times)*hi)] if hi<1 else max(times)+1;schemes['forward_time'].append((idx[ts<start],idx[(ts>=start)&(ts<end)]))
 for scheme,folds in schemes.items():
  for fold,(tr,te) in enumerate(folds):
   train=[records[i]['fights'] for i in tr];demand=fd.table(train);cuts=fd.cuts_of(train,demand)
   for i in te:out.extend(evaluate_record(records[i],demand,cuts,scheme,fold))
  print(scheme,'done',flush=True)
 p=pd.DataFrame(out);p['difficulty']=p.asc.map(lambda x:'A0-1' if x<2 else 'A2-7' if x<8 else f'A{x}');p.to_csv(OUT/'ratings.csv',index=False);summary=[]
 for (scheme,stage),d in p.groupby(['scheme','stage']):
  for dim in ['all','difficulty','player']:
   groups=[('all',d)] if dim=='all' else d.groupby(dim)
   for value,g in groups:
    for grade in ['OP','Hype','Mid','Rough','Unrated','OP+Hype']:
     h=g[g.grade.isin(['OP','Hype'])] if grade=='OP+Hype' else g[g.grade==grade]
     n=len(h);wins=int(h.won.sum());lo,hi=wilson(wins,n)
     summary.append(dict(scheme=scheme,stage=stage,dimension=dim,value=value,grade=grade,n=n,wins=wins,rate=wins/n if n else None,low=lo,high=hi,players=h.player.nunique(),cohort_baseline=g.won.mean(),coverage=n/len(g)))
 s=pd.DataFrame(summary);s.to_csv(OUT/'win_rates.csv',index=False)
 act_rates=[]
 for (scheme,stage,act,difficulty,grade),g in p.groupby(['scheme','stage','act','difficulty','act_grade']):
  n=len(g);wins=int(g.act_clear.sum());lo,hi=wilson(wins,n);act_rates.append(dict(scheme=scheme,stage=stage,act=act,difficulty=difficulty,act_grade=grade,n=n,cleared=wins,rate=wins/n,low=lo,high=hi,players=g.player.nunique()))
 pd.DataFrame(act_rates).to_csv(OUT/'act_clear_rates.csv',index=False)
 p[p.scheme=='run_holdout'].groupby(['stage','act','difficulty','grade']).agg(n=('run','size'),players=('player','nunique'),wins=('won','sum'),turns_q25=('act_turns_per_fight',lambda x:x.quantile(.25)),turns_median=('act_turns_per_fight','median'),turns_q75=('act_turns_per_fight',lambda x:x.quantile(.75)),hp_q25=('act_hp_per_fight',lambda x:x.quantile(.25)),hp_median=('act_hp_per_fight','median'),hp_q75=('act_hp_per_fight',lambda x:x.quantile(.75))).reset_index().to_csv(OUT/'checkpoint_anchors.csv',index=False)
 # Descriptive anchors from actual classes, retaining losers and separating wins.
 grades=p[(p.scheme=='run_holdout')&(p.stage=='completed_run')].set_index('run').grade.to_dict();anchors=[]
 for r in records:
  for act in sorted({f['act'] for f in r['fights']}):
   fs=[f for f in r['fights'] if f['act']==act and not f['died']]
   if not fs:continue
   anchors.append(dict(run=r['run'],player=r['player'],act=act+1,asc=r['asc'],difficulty='A0-1' if r['asc']<2 else 'A2-7' if r['asc']<8 else f"A{r['asc']}",grade=grades.get(r['run'],'Unrated'),won=r['won'],fights=len(fs),turns_per_fight=np.mean([f['t'] for f in fs]),net_hp_per_fight=np.mean([f['taken'] for f in fs]),net_hp_per_enemy_turn=sum(f['taken'] for f in fs)/sum(max(1,f['t']-1) for f in fs)))
 a=pd.DataFrame(anchors);a.to_csv(OUT/'class_observations.csv',index=False);a.groupby(['act','difficulty','grade','won']).agg(n=('run','size'),players=('player','nunique'),turns_q25=('turns_per_fight',lambda x:x.quantile(.25)),turns_median=('turns_per_fight','median'),turns_q75=('turns_per_fight',lambda x:x.quantile(.75)),hp_q25=('net_hp_per_fight',lambda x:x.quantile(.25)),hp_median=('net_hp_per_fight','median'),hp_q75=('net_hp_per_fight',lambda x:x.quantile(.75))).reset_index().to_csv(OUT/'class_anchors.csv',index=False)
 print(s[(s.dimension=='all')&(s.scheme.isin(['current_baked_baseline','run_holdout']))&(s.stage.isin(['completed_run','after_act1_boss','act3_fight3','before_act3_boss']))].to_string(index=False))
if __name__=='__main__':main()
