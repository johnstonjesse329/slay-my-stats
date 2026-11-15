"""Abandonment sensitivity, using existing snapshot only.
Train on non-abandoned other-player runs; unfinished acts have unknown outcomes.
"""
import gzip,json,html
import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.ensemble import HistGradientBoostingClassifier
import checkpoint_interactions as cp
import six_character_boss_study as current
import boss_readiness as b
import boss_development as dev
from ablate_boss_development import COMPOSITION
OUT=current.OUT/'abandonment'

def main():
 OUT.mkdir(exist_ok=True);checkpoint_train=cp.dataset();boss_train,_=current.dataset();boss_train=[r for r in boss_train if r['task']=='boss_sequence'];raw=b.ar.g.load();cat=json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'));catalog={'CARD.'+x['Entry']:x for x in cat['Cards']};roster=current.core_roster(cat);accepted=set()
 for path in (current.SOURCE/'users').glob('*/*.json.gz'):
  if not path.name.startswith('_'):
   for r in json.load(gzip.open(path,'rt',encoding='utf-8')).get('runs',[]):accepted.add(b.ar.signature(r['ts'],r['char'],r.get('seed')))
 stress=[];ledgers={};abandoned_runs=0
 for (sid,ts),r in raw.items():
  rid=b.ar.pseudonym(f'{sid}:{ts}');player=b.ar.pseudonym(sid)
  for act,x in dev.ledger(r,catalog).items():ledgers[rid,act]={k:float(x.get(k,0)) for k in COMPOSITION}
  if not r.get('was_abandoned') or not current.eligible(dict(r,was_abandoned=False),accepted,roster)[0]:continue
  abandoned_runs+=1
  for x in cp.extract(r,rid,player,catalog):stress.append(x|dict(stage=f"fight{x['fight_index']}"))
  rr,_=b.extract_run(r,rid,player)
  for x in rr:
   if x['task']=='boss_sequence':stress.append(x|dict(stage='boss_entry'))
 outputs=[]
 for stage in ['fight3','fight6','boss_entry']:
  base=boss_train if stage=='boss_entry' else [r for r in checkpoint_train if r['fight_index']==int(stage[-1])]
  tests=[r for r in stress if r['stage']==stage]
  for player in sorted({r['player'] for r in tests}):
   train=[r for r in base if r['player']!=player];test=[r for r in tests if r['player']==player]
   assert not {r['run'] for r in train}&{r['run'] for r in test}
   fights={}
   for r in train:
    for i,f in enumerate(r['history']):fights[r['run'],r['act'],i]=f
   ref=b.ar.reference(list(fights.values()),{r['run'] for r in train})
   def features(r):
    if stage!='boss_entry':return cp.features(r,ref,'tree_composition')
    x=b.feats(r,ref,'performance');x['healing_rule']='A2+' if r['asc']>=2 else 'A0-1';x.update(ledgers[r['run'],r['act']]);return x
   vector=DictVectorizer(sparse=False);tr=vector.fit_transform([features(r) for r in train]);te=vector.transform([features(r) for r in test])
   model=HistGradientBoostingClassifier(max_iter=150,max_depth=3,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=42).fit(tr,[r['clear'] for r in train])
   probs=model.predict_proba(te)[:,1]
   for r,p in zip(test,probs):outputs.append(dict(stage=stage,run=r['run'],player=player,act=r['act'],asc=r['asc'],confirmed_clear=r['clear'],p=float(p)))
  print(stage,'done',flush=True)
 stress=pd.DataFrame(outputs);stress.to_csv(OUT/'stress_predictions.csv',index=False);summary=[]
 for stage in ['fight3','fight6','boss_entry']:
  file=current.OUT/('interactions/predictions.csv' if stage=='boss_entry' else 'checkpoint_interactions/predictions.csv');base=pd.read_csv(file);base=base[(base.split=='player_holdout')&(base.model=='tree_composition')]
  if stage!='boss_entry':base=base[(base.fight_index==int(stage[-1]))&(base.endpoint=='clear')]
  hits=base[base.p>=.9];extra=stress[(stress.stage==stage)&(stress.p>=.9)];n=len(hits)+len(extra);known=int(hits.clear.sum()+extra.confirmed_clear.sum());unknown=int((extra.confirmed_clear==0).sum())
  summary.append(dict(stage=stage,original_selected=len(hits),original_wins=int(hits.clear.sum()),abandoned_observations=int((stress.stage==stage).sum()),abandoned_selected=len(extra),abandoned_confirmed_clear=int(extra.confirmed_clear.sum()),unknown_outcomes=unknown,combined_selected=n,worst_case_clearance=known/n if n else None,best_case_clearance=(known+unknown)/n if n else None))
 result=pd.DataFrame(summary);result.to_csv(OUT/'bounds.csv',index=False);print('eligible abandoned runs',abandoned_runs);print(result.to_string(index=False))
 notes=f'''# Abandonment sensitivity

{abandoned_runs} accepted standard solo catalog-character runs marked abandoned were eligible for this stress test. The original train set remains non-abandoned. Each abandoned observation is scored by a model trained without that player's runs, using the same fixed tree settings and pre-checkpoint feature definitions. No current/future abandon flag enters predictors. The candidate is not retrained to classify abandonment as a loss.

Cleared earlier acts have known successful outcomes. Any abandoned act without demonstrated clearance has an unknown counterfactual outcome. Worst-case bounds count every such selected observation as a failure; best-case bounds count each as a success. These are sensitivity bounds, not estimates of what the player would have done. Missing observations before a checkpoint cannot be used to validate that checkpoint. Boss-entry eligibility still requires three earlier completed fights.

The original high-confidence group comes from the previously saved non-abandoned player-holdout predictions. New stress scores use training on the same non-abandoned other-player population. Counts are act observations, not independent players. Seven players and repeated historical analysis remain limitations. Passing this sensitivity check does not prove calibration or objective deck strength.
'''
 (OUT/'review.md').write_text(notes,encoding='utf-8');(OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Abandonment sensitivity</title><style>body{font:16px/1.6 system-ui;margin:30px}pre{white-space:pre-wrap}table{border-collapse:collapse}td,th{padding:6px;border:1px solid #ddd}</style><pre>'+html.escape(notes)+'</pre>'+result.to_html(index=False),encoding='utf-8')
if __name__=='__main__':main()
