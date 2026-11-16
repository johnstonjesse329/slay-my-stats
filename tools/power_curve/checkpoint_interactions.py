"""Nonlinear fixed-checkpoint clearance test on copied six-character snapshot.
Boss identity/entry HP and future card gains never enter checkpoint predictors.
"""
import gzip,json,html
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
OUT=current.OUT/'checkpoint_interactions'

def extract(raw,rid,player,catalog):
 rows=[];prefix=[];asc=raw.get('ascension') or 0
 for ai,points in enumerate(raw.get('map_point_history',[])):
  bosses=[p for p in points if p.get('map_point_type')=='boss'];needed=2 if asc>=10 and ai==2 else 1
  clear=int(bool(raw.get('win') or any(raw['map_point_history'][ai+1:]) or len(bosses)>=needed and all(p['player_stats'][0].get('current_hp',0)>0 for p in bosses)))
  history=[];seen=[]
  for j,point in enumerate(points):
   seen.append(point)
   if point.get('map_point_type')=='boss':break
   s=point.get('player_stats',[{}])[0];rooms=[q for q in point.get('rooms',[]) if q.get('turns_taken') and q.get('monster_ids')]
   if len(rooms)!=1:continue
   if s.get('current_hp',0)<=0:break
   room=rooms[0];history.append(dict(run=rid,enc=room['model_id'],kind=point.get('map_point_type','unknown'),act=ai+1,tier=b.ar.tier(asc),turns=room['turns_taken'],loss=max(0,s.get('damage_taken',0)-s.get('hp_healed',0)),pool=None))
   if len(history) not in [3,6] or s.get('max_hp',0)<=0:continue
   # Snapshot ledger by appending a marker to the observed prefix only. The
   # ledger captures before this marker, whose stats contain no game outcome.
   partial={'map_point_history':prefix+[seen+[{'map_point_type':'boss','player_stats':[{}]}]]}
   ledger=dev.ledger(partial,catalog)[ai+1]
   rows.append(dict(run=rid,player=player,ts=raw['start_time'],act=ai+1,asc=asc,tier=b.ar.tier(asc),char=raw['players'][0]['character'],build=raw.get('build_id','unknown'),fight_index=len(history),rooms_completed=j+1,hp=s['current_hp'],maxhp=s['max_hp'],history=list(history),composition={k:float(ledger.get(k,0)) for k in COMPOSITION},clear=clear,reached=int(bool(bosses))))
  prefix.append(points)
 return rows

def dataset():
 accepted=set()
 for path in (current.SOURCE/'users').glob('*/*.json.gz'):
  if not path.name.startswith('_'):
   for r in json.load(gzip.open(path,'rt',encoding='utf-8')).get('runs',[]):accepted.add(b.ar.signature(r['ts'],r['char'],r.get('seed')))
 cat=json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'));roster=current.core_roster(cat);catalog={'CARD.'+c['Entry']:c for c in cat['Cards']};b.ar.g.RAW=current.SOURCE/'raw';rows=[]
 for (sid,ts),raw in b.ar.g.load().items():
  if current.eligible(raw,accepted,roster)[0]:rows.extend(extract(raw,b.ar.pseudonym(f'{sid}:{ts}'),b.ar.pseudonym(sid),catalog))
 return rows

def features(r,ref,variant):
 x=b.ar.features(r,ref,'baseline' if variant=='tree_health' else 'trend');x['rooms_completed']=r['rooms_completed'];x['healing_rule']='A2+' if r['asc']>=2 else 'A0-1'
 if variant!='tree_health':x.update(r['composition'])
 return x

def main():
 OUT.mkdir(exist_ok=True);rows=dataset();times=sorted({r['ts'] for r in rows});out=[]
 for cp in [3,6]:
  data=[r for r in rows if r['fight_index']==cp];splits={'forward_time':[],'player_holdout':[]}
  for lo,hi in [(.4,.6),(.6,.8),(.8,1.)]:
   start=times[int(len(times)*lo)];end=times[int(len(times)*hi)] if hi<1 else max(times)+1;splits['forward_time'].append(([r for r in data if r['ts']<start],[r for r in data if start<=r['ts']<end]))
  for player in sorted({r['player'] for r in data}):splits['player_holdout'].append(([r for r in data if r['player']!=player],[r for r in data if r['player']==player]))
  for split,folds in splits.items():
   for fold,(train,test) in enumerate(folds):
    assert not {r['run'] for r in train}&{r['run'] for r in test}
    fights={}
    for r in train:
     for i,f in enumerate(r['history']):fights[r['run'],r['act'],i]=f
    ref=b.ar.reference(list(fights.values()),{r['run'] for r in train})
    for variant,label in [('tree_health','clear'),('linear_composition','clear'),('tree_composition','clear'),('tree_composition','reached')]:
     vector=DictVectorizer(sparse=False);tr=vector.fit_transform([features(r,ref,variant) for r in train]);te=vector.transform([features(r,ref,variant) for r in test])
     if variant.startswith('linear'):
      scaler=StandardScaler();tr=scaler.fit_transform(tr);te=scaler.transform(te);model=LogisticRegression(C=.1,max_iter=2000)
     else:model=HistGradientBoostingClassifier(max_iter=150,max_depth=3,min_samples_leaf=30,l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=42)
     model.fit(tr,[r[label] for r in train]);probs=model.predict_proba(te)[:,1]
     for r,p in zip(test,probs):out.append({k:r[k] for k in ['run','player','act','asc','fight_index','clear','reached']}|dict(split=split,fold=fold,model=variant,endpoint=label,p=float(p)))
   print(cp,split,'done',flush=True)
 p=pd.DataFrame(out);p.to_csv(OUT/'predictions.csv',index=False);metrics=[];confidence=[];paired=[];rng=np.random.default_rng(42)
 for keys,d in p.groupby(['fight_index','split','model','endpoint']):
  cp,split,model,label=keys;common=dict(checkpoint=cp,split=split,model=model,endpoint=label)
  metrics.append(common|dict(n=len(d),brier=brier_score_loss(d[label],d.p),auc=roc_auc_score(d[label],d.p)))
  d=d.copy();d['difficulty']=d.asc.map(lambda x:'A0-1' if x<2 else 'A2-7' if x<8 else f'A{x}')
  for dim in ['all','difficulty','act','player']:
   groups=[('all',d)] if dim=='all' else d.groupby(dim)
   for value,g in groups:
    h=g[g.p>=.9];n=len(h);wins=int(h[label].sum());lo,hi=wilson(wins,n);confidence.append(common|dict(dimension=dim,value=value,eligible=len(g),selected=n,wins=wins,rate=h[label].mean(),low=lo,high=hi,predicted=h.p.mean()))
 for (cp,split),d in p[p.endpoint=='clear'].groupby(['fight_index','split']):
  q=d.pivot(index=['run','act','clear'],columns='model',values='p').reset_index()
  for base in ['tree_health','linear_composition']:
   q['delta']=(q.tree_composition-q.clear)**2-(q[base]-q.clear)**2;g=q.groupby('run').delta.agg(['sum','count']);ix=rng.integers(0,len(g),(2000,len(g)));bs=g['sum'].to_numpy()[ix].sum(axis=1)/g['count'].to_numpy()[ix].sum(axis=1)
   paired.append(dict(checkpoint=cp,split=split,comparison='tree_composition minus '+base,delta=q.delta.mean(),low=np.quantile(bs,.025),high=np.quantile(bs,.975)))
 m=pd.DataFrame(metrics);c=pd.DataFrame(confidence);u=pd.DataFrame(paired);m.to_csv(OUT/'metrics.csv',index=False);c.to_csv(OUT/'confidence.csv',index=False);u.to_csv(OUT/'paired_uncertainty.csv',index=False)
 print(m.to_string(index=False));print(u.to_string(index=False));print(c[(c.dimension=='all')&(c.model=='tree_composition')].to_string(index=False))
 notes='''# Early-checkpoint nonlinear experiment

Fixed checkpoints after completed non-boss fights 3 and 6. Endpoint: entire act boss sequence clear, including both final bosses at A10. Boss arrival is a separate endpoint. Includes pre-boss deaths occurring after the checkpoint; deaths before the checkpoint do not enter that checkpoint population. Solo published standard non-abandoned runs, catalog-derived six-character roster, copied snapshot only.

Features use current HP, context, observed completed current-act fights, and acquired-card composition from a prefix ledger ending at the checkpoint. No future boss identity, entry HP, final deck, future cards or future room count enters. Actual rooms already completed is known at prediction time. Earlier acts' development may carry into the current deck, as it does in the game. A2+ healing is cumulative. The ledger remains partial, not a full-deck reconstruction.

Fixed model settings match the preceding boss-entry experiment. Training-only vectorization and encounter references; disjoint whole-run membership; forward-time and whole-player evaluations. No tuning against the results reported here. Repeated historical exploration and seven players limit conclusions. Paired intervals resample whole runs from fixed predictions and omit refitting and player-population uncertainty. Wilson subgroup intervals are unclustered. Empty high-confidence groups mean abstention, not evidence of 100% reliability.
'''
 (OUT/'review.md').write_text(notes,encoding='utf-8');(OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Early checkpoint interactions</title><style>body{font:16px/1.6 system-ui;margin:30px}pre{white-space:pre-wrap}td,th{padding:6px;border:1px solid #ddd}table{border-collapse:collapse;font-size:13px}</style><pre>'+html.escape(notes)+'</pre>'+m.to_html(index=False)+u.to_html(index=False)+c[c.dimension=='all'].to_html(index=False),encoding='utf-8')
if __name__=='__main__':main()
