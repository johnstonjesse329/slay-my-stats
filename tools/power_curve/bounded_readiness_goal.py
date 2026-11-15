"""Bounded four-family experiment from docs/act-boss-readiness-goal.md.
Existing copied snapshot only; no network, live-save inputs, tuning or deployment.
"""
import collections,gzip,json,html
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss,roc_auc_score
import six_character_boss_study as current
import boss_readiness as b
import telemetry_report as tr
import checkpoint_interactions as cp
from aligned_measured_readiness import prior_window
from act_targets import wilson
OUT=current.OUT/'bounded_goal'
FAMILIES={'damage':['damage_rate','early_damage_rate','late_damage_rate','late_available','fight_turns'], 'setup':['early_enemy_cost','worst_enemy_cost','early_zero_fraction'], 'endurance':['absorbed_rate','net_hp_per_fight','enemy_cost_rate'], 'consistency':['zero_fraction','damage_sd','enemy_cost_sd']}

def valid(f):
 return f.get('hp0') is not None and f.get('hp1') is not None and f['hp0']-f['hp1']==f['hp_in']-f['hp_out'] and f.get('enemy_unexplained',0)==0 and abs(f.get('enemy_lost',-1)-f.get('dealt_removed',-2))<1e-6 and bool(f.get('turns'))

def metrics(fs):
 if not fs or not all(valid(f) for f in fs):raise ValueError('Unvalidated measurement window')
 turns=[t for f in fs for t in f['turns']];early=[t for f in fs for t in f['turns'][:2]];late=[t for f in fs for t in f['turns'][2:]]
 # enemy_lost is a turn-level HP delta; only use when the fight has no
 # unexplained disappearance. It is not attempted/overkill damage.
 damage=np.array([t['enemy_lost'] for t in turns],dtype=float);cost=np.array([t['taken'] for t in turns],dtype=float)
 return dict(damage_rate=sum(f['dealt_removed'] for f in fs)/len(turns),early_damage_rate=float(np.mean([t['enemy_lost'] for t in early])),late_damage_rate=float(np.mean([t['enemy_lost'] for t in late])) if late else 0.,late_available=int(bool(late)),fight_turns=len(turns)/len(fs),early_enemy_cost=float(np.mean([t['taken'] for t in early])),worst_enemy_cost=float(cost.max()),early_zero_fraction=float(np.mean([t['enemy_lost']==0 for t in early])),absorbed_rate=sum(f['blocked'] for f in fs)/len(turns),net_hp_per_fight=sum(max(0,f['hp_in']-f['hp_out']) for f in fs)/len(fs),enemy_cost_rate=float(cost.mean()),zero_fraction=float(np.mean(damage==0)),damage_sd=float(damage.std()),enemy_cost_sd=float(cost.std()),late_turns=len(late))

def completed_window(logged,raw_encounters):
 if len(raw_encounters)<3:return None
 matches=[logged[i-2:i+1] for i in range(2,len(logged)) if [f['enc'] for f in logged[i-2:i+1]]==raw_encounters[-3:] and all(f.get('won') for f in logged[i-2:i+1])]
 return matches[0] if len(matches)==1 else None

def dataset():
 targets,_=current.dataset();targets={(r['run'],r['act']):r for r in targets if r['task']=='boss_sequence'};raw=b.ar.g.load();tr.TELEMETRY=current.SOURCE/'telemetry';logs,_=tr.load_logs(raw);accepted=set()
 for p in (current.SOURCE/'users').glob('*/*.json.gz'):
  if not p.name.startswith('_'):
   for r in json.load(gzip.open(p,'rt',encoding='utf-8')).get('runs',[]):accepted.add(b.ar.signature(r['ts'],r['char'],r.get('seed')))
 cat=json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'));roster=current.core_roster(cat);catalog={'CARD.'+c['Entry']:c for c in cat['Cards']};rows=[];diagnostics=[];audit=[]
 for (sid,ts),log in logs.items():
  rawrun=raw.get((sid,ts));rid=b.ar.pseudonym(f'{sid}:{ts}');player=b.ar.pseudonym(sid)
  if not rawrun or not current.eligible(rawrun,accepted,roster)[0]:continue
  checkpoints=cp.extract(rawrun,rid,player,catalog)
  for r in checkpoints:
   window=completed_window(log['fights'],[x['enc'] for x in r['history']]);reason='accepted' if window and all(valid(f) for f in window) and not log.get('truncated') else 'missing_ambiguous_or_unbalanced'
   audit.append(dict(run=rid,player=player,stage=f"fight{r['fight_index']}",act=r['act'],asc=r['asc'],clear=r['clear'],reason=reason))
   if reason=='accepted':rows.append({k:r[k] for k in ['run','player','ts','act','asc','char','build','hp','maxhp','clear']}|dict(stage=f"fight{r['fight_index']}",prior_fights=r['fight_index'],boss='unknown',**metrics(window)))
  for ai,points in enumerate(rawrun['map_point_history']):
   r=targets.get((rid,ai+1))
   if not r:continue
   prior=[]
   for p in points:
    if p.get('map_point_type')=='boss':break
    prior.extend(q['model_id'] for q in p.get('rooms',[]) if q.get('turns_taken') and q.get('monster_ids'))
   window,reason=prior_window(log['fights'],r['boss'],prior)
   if reason=='accepted' and (not all(valid(f) for f in window) or log.get('truncated')):reason='unexplained_damage_or_truncated'
   audit.append(dict(run=rid,player=player,stage='boss_entry',act=r['act'],asc=r['asc'],clear=r['clear'],reason=reason))
   if reason=='accepted':rows.append({k:r[k] for k in ['run','player','ts','act','asc','char','build','hp','maxhp','clear','boss']}|dict(stage='boss_entry',prior_fights=len(r['history']),**metrics(window)))
   bossfs=[f for f in log['fights'] if f['enc']==r['boss']]
   if len(bossfs)==1 and valid(bossfs[0]):diagnostics.append({k:r[k] for k in ['run','player','act','asc','char','hp','maxhp','clear','boss']}|metrics(bossfs))
 return pd.DataFrame(rows),pd.DataFrame(diagnostics),pd.DataFrame(audit)

def feature(r,family):
 x=dict(act=str(r['act']),asc=r['asc'],character=r['char'],build=r['build'],hp=r['hp'],maxhp=r['maxhp'],hp_fraction=r['hp']/r['maxhp'],healing_rule='A2+' if r['asc']>=2 else 'A0-1',prior_fights=r['prior_fights'])
 if r['stage']=='boss_entry':x['boss']=r['boss']
 keys=sum(FAMILIES.values(),[]) if family=='combined' else FAMILIES.get(family,[])
 x.update({k:r[k] for k in keys});return x

def main():
 OUT.mkdir(exist_ok=True);d,diag,audit=dataset();d.to_csv(OUT/'observations.csv',index=False);diag.to_csv(OUT/'boss_diagnostics.csv',index=False);audit.to_csv(OUT/'measurement_audit.csv',index=False);output=[]
 for stage,g in d.groupby('stage'):
  rows=g.to_dict('records');idx=np.arange(len(rows));ts=g.ts.to_numpy();times=sorted(set(ts));splits={'forward_time':[],'player_holdout':[]}
  for lo,hi in [(.4,.6),(.6,.8),(.8,1.)]:
   start=times[int(len(times)*lo)];end=times[int(len(times)*hi)] if hi<1 else max(times)+1;splits['forward_time'].append((idx[ts<start],idx[(ts>=start)&(ts<end)]))
  for player in sorted(g.player.unique()):
   train=idx[g.player.to_numpy()!=player];test=idx[g.player.to_numpy()==player]
   if len(train):splits['player_holdout'].append((train,test))
  for split,folds in splits.items():
   for fold,(train,test) in enumerate(folds):
    assert not set(g.iloc[train].run)&set(g.iloc[test].run)
    for family in ['baseline',*FAMILIES,'combined']:
     for kind in ['linear','tree']:
      y=g.iloc[train].clear.to_numpy();constant=len(set(y))<2
      if constant:prob=np.full(len(test),np.mean(y))
      else:
       vector=DictVectorizer(sparse=False);x=vector.fit_transform([feature(rows[i],family) for i in train]);xt=vector.transform([feature(rows[i],family) for i in test])
       if kind=='linear':
        scale=StandardScaler();x=scale.fit_transform(x);xt=scale.transform(xt);model=LogisticRegression(C=.1,max_iter=2000)
       else:model=HistGradientBoostingClassifier(max_iter=150,max_depth=3,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=42)
       model.fit(x,y);prob=model.predict_proba(xt)[:,1]
      for i,p in zip(test,prob):output.append({k:rows[i][k] for k in ['run','player','stage','act','asc','hp','maxhp','clear']}|dict(split=split,fold=fold,family=family,model=kind,p=float(p),constant=constant))
   print(stage,split,'done',flush=True)
 p=pd.DataFrame(output);p.to_csv(OUT/'predictions.csv',index=False);scores=[];uncertainty=[];rng=np.random.default_rng(42)
 for keys,g in p.groupby(['stage','split','family','model']):scores.append(dict(zip(['stage','split','family','model'],keys))|dict(n=len(g),players=g.player.nunique(),runs=g.run.nunique(),brier=brier_score_loss(g.clear,g.p),auc=roc_auc_score(g.clear,g.p) if g.clear.nunique()==2 else None,constant=int(g.constant.sum())))
 for (stage,split,model),g in p.groupby(['stage','split','model']):
  q=g.pivot(index=['run','act','clear'],columns='family',values='p').reset_index();base=(q.baseline-q.clear)**2
  for family in [*FAMILIES,'combined']:
   delta=(q[family]-q.clear)**2-base;units=delta.groupby(q.run).agg(['sum','count']);ix=rng.integers(0,len(units),(2000,len(units)));bs=units['sum'].to_numpy()[ix].sum(axis=1)/units['count'].to_numpy()[ix].sum(axis=1)
   uncertainty.append(dict(stage=stage,split=split,model=model,family=family,delta=delta.mean(),relative_reduction=-delta.mean()/base.mean(),low=np.quantile(bs,.025),high=np.quantile(bs,.975)))
 pd.DataFrame(scores).to_csv(OUT/'scores.csv',index=False);pd.DataFrame(uncertainty).to_csv(OUT/'uncertainty.csv',index=False)
 print(d.groupby('stage').agg(n=('run','size'),runs=('run','nunique'),players=('player','nunique')).to_string());print('families completed',list(FAMILIES))
if __name__=='__main__':main()
