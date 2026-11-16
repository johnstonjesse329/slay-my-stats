"""Freeze research candidates; score prefix inputs and join outcomes separately.
All commands local. No AWS writes, site changes or production confidence claim.
"""
import argparse,datetime,hashlib,json,math
from pathlib import Path
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
import boss_readiness as b
import boss_development as dev
from ablate_boss_development import COMPOSITION
from act_targets import wilson

DEFAULT=b.OUT/'frozen-v1'
CHECKPOINT_FIELDS={'act','asc','char','build','fight_index','hp','maxhp','history','boss','ordinal','rests'}
FIGHT_FIELDS={'enc','kind','act','tier','turns','loss','pool'}

def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(x):return hashlib.sha256(canonical(x).encode()).hexdigest()
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def encode(x):
 return {(f'{k}={v}' if isinstance(v,str) else k):(1. if isinstance(v,str) else float(v)) for k,v in x.items()}

def exported_prediction(model,x):
 z=model['intercept'];values=encode(x)
 for key,coef,scale in zip(model['names'],model['coefficients'],model['scales']):z+=values.get(key,0.)*coef/scale
 return 1/(1+math.exp(-max(-700,min(700,z))))

def make_features(checkpoint,composition,ref,variant):
 r=dict(checkpoint);r['tier']=b.ar.tier(r['asc'])
 x=b.feats(r,ref,'health' if variant=='health' else 'performance')
 x['healing_rule']='A2+' if r['asc']>=2 else 'A0-1'
 if variant=='composition':x.update(composition)
 return x

def validate_prefix(payload):
 if set(payload)!={'run','player','observed_at','mode','solo','checkpoint','composition'}:raise ValueError('Unexpected prefix fields; labels and future-state fields are forbidden')
 if payload['mode']!='standard' or payload['solo'] is not True:raise ValueError('Only standard solo inputs supported')
 stamp=datetime.datetime.fromisoformat(payload['observed_at'])
 if stamp.tzinfo is None:raise ValueError('observed_at must include timezone')
 r=payload['checkpoint']
 if set(r)!=CHECKPOINT_FIELDS:raise ValueError('Unexpected checkpoint fields')
 if r['ordinal']!=1:raise ValueError('Only first-boss sequence entry supported')
 if not isinstance(r['asc'],int) or not 0<=r['asc']<=10:raise ValueError('Unsupported ascension')
 if r['act'] not in [1,2,3] or not 0<r['hp']<=r['maxhp']:raise ValueError('Invalid act or HP')
 if len(r['history'])<3 or r['fight_index']!=len(r['history']):raise ValueError('Need at least three completed current-act fights')
 for f in r['history']:
  if set(f)!=FIGHT_FIELDS or f['act']!=r['act'] or f['kind']=='boss' or f['turns']<=0 or f['loss']<0:raise ValueError('Invalid prior fight')
 if set(payload['composition'])!=COMPOSITION:raise ValueError('Composition requires the frozen feature set')
 # Reject NaN/Infinity anywhere before numeric evaluation.
 canonical(payload)
 return stamp

def load_bundle(folder):
 bundle=json.loads((folder/'bundle.json').read_text())
 expected=bundle.pop('artifact_id')
 if digest(bundle)!=expected:raise ValueError('Artifact integrity failure')
 bundle['artifact_id']=expected
 for name,sha in bundle['source_hashes'].items():
  if hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()!=sha:raise ValueError(f'Frozen feature code changed: {name}')
 return bundle

def freeze(folder):
 if folder.exists():raise ValueError('Freeze destination already exists; never overwrite a frozen experiment')
 rows,audit=b.dataset();rows=[r for r in rows if r['task']=='boss_sequence']
 catalog={'CARD.'+c['Entry']:c for c in json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'))['Cards']};ledgers={}
 for (sid,ts),raw in b.ar.g.load().items():
  rid=b.ar.pseudonym(f'{sid}:{ts}')
  for act,x in dev.ledger(raw,catalog).items():ledgers[rid,act]={k:float(x.get(k,0)) for k in COMPOSITION}
 fights={}
 for r in rows:
  for i,f in enumerate(r['history']):fights[r['run'],r['act'],i]=f
 ref=b.ar.reference(list(fights.values()),{r['run'] for r in rows});models={};parity={}
 for variant in ['health','performance','composition']:
  xs=[make_features(r,ledgers[r['run'],r['act']],ref,variant) for r in rows]
  clf=make_pipeline(DictVectorizer(),StandardScaler(with_mean=False),LogisticRegression(C=.1,max_iter=2000)).fit(xs,[r['clear'] for r in rows])
  vector,scaler,lr=clf.steps[0][1],clf.steps[1][1],clf.steps[2][1]
  model=dict(names=vector.get_feature_names_out().tolist(),scales=scaler.scale_.tolist(),coefficients=lr.coef_[0].tolist(),intercept=float(lr.intercept_[0]))
  errors=[abs(p-exported_prediction(model,x)) for p,x in zip(clf.predict_proba(xs)[:,1],xs)]
  if max(errors)>1e-10:raise ValueError('Exported predictor differs from training implementation')
  models[variant]=model;parity[variant]=max(errors)
 files={}
 for category in ['raw','users','telemetry']:
  for file in sorted((b.ar.OUT/category).rglob('*.gz')):files[str(file.relative_to(b.ar.OUT))]=hashlib.sha256(file.read_bytes()).hexdigest()
 names=['freeze_boss_experiment.py','boss_readiness.py','act_readiness.py','boss_development.py','ablate_boss_development.py']
 bundle=dict(version=1,created_at=now(),purpose='research shadow only; uncalibrated candidates',endpoint='entire act boss sequence from first-boss entry',thresholds=[.8,.9,.95],models=models,references=[dict(key=list(k),value=list(v)) for k,v in ref.items()],training_runs=sorted({r['run'] for r in rows}),training_players=sorted({r['player'] for r in rows}),audit=audit,source_hashes={n:hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in names},snapshot_hash=digest(files),snapshot_files=files,export_max_error=parity,catalog_hash=hashlib.sha256((b.ar.ROOT/'card_game_data.json').read_bytes()).hexdigest())
 bundle['artifact_id']=digest(bundle);folder.mkdir(parents=True);(folder/'bundle.json').write_text(canonical(bundle),encoding='utf-8')
 # Explicitly synthetic/in-sample example, not admissible prospective evidence.
 r=rows[0];cp={k:r[k] for k in CHECKPOINT_FIELDS};cp['history']=[{k:f[k] for k in FIGHT_FIELDS} for f in r['history']]
 example=dict(run=r['run'],player=r['player'],observed_at=now(),mode='standard',solo=True,checkpoint=cp,composition=ledgers[r['run'],r['act']])
 (folder/'example-prefix.json').write_text(json.dumps(example,indent=2),encoding='utf-8')
 print('Frozen',bundle['artifact_id'],'training sequences',len(rows),'export max errors',parity)

def score(folder,prefix_file,output):
 bundle=load_bundle(folder);payload=json.loads(prefix_file.read_text());observed=validate_prefix(payload)
 if output.exists():raise ValueError('Prediction exists; refusing to overwrite')
 ref={tuple(r['key']):r['value'] for r in bundle['references']}
 probabilities={v:exported_prediction(m,make_features(payload['checkpoint'],payload['composition'],ref,v)) for v,m in bundle['models'].items()}
 result=dict(artifact_id=bundle['artifact_id'],scored_at=now(),observed_at=payload['observed_at'],run=payload['run'],player=payload['player'],act=payload['checkpoint']['act'],asc=payload['checkpoint']['asc'],prefix_hash=digest(payload),probabilities=probabilities,in_training=payload['run'] in bundle['training_runs'],new_player=payload['player'] not in bundle['training_players'],after_freeze=observed>datetime.datetime.fromisoformat(bundle['created_at']),provenance='caller-supplied prefix timestamp; not independently attested')
 output.write_text(canonical(result),encoding='utf-8');print(json.dumps(result,indent=2))

def evaluate(folder,prediction_dir,outcome_file,output):
 bundle=load_bundle(folder);outcomes=json.loads(outcome_file.read_text());out=[];excluded=[];seen=set()
 for file in sorted(prediction_dir.glob('*.json')):
  p=json.loads(file.read_text());key=f"{p['run']}:{p['act']}"
  if p['artifact_id']!=bundle['artifact_id']:raise ValueError('Mixed artifact versions')
  if key in seen:raise ValueError('Duplicate run-act prediction')
  seen.add(key)
  if p['in_training'] or not p['after_freeze']:excluded.append(key);continue
  if key not in outcomes:continue
  o=outcomes[key]
  if o['status'] not in ['clear','death','abandoned','unknown']:raise ValueError('Invalid outcome status')
  if o['status'] in ['abandoned','unknown']:continue
  resolved=datetime.datetime.fromisoformat(o['resolved_at']);scored=datetime.datetime.fromisoformat(p['scored_at'])
  if resolved<=scored:raise ValueError('Outcome resolved before prediction; not prospective evidence')
  out.append((p,int(o['status']=='clear')))
 report=dict(artifact_id=bundle['artifact_id'],matched=len(out),excluded_training_or_pre_freeze=len(excluded),status='insufficient evidence; no automated approval gate',results=[])
 for variant in bundle['models']:
  for threshold in bundle['thresholds']:
   hits=[(p,y) for p,y in out if p['probabilities'][variant]>=threshold];n=len(hits);wins=sum(y for _,y in hits);low,high=wilson(wins,n)
   report['results'].append(dict(model=variant,threshold=threshold,n=n,wins=wins,rate=wins/n if n else None,low=low,high=high,players=len({p['player'] for p,_ in hits})))
 if output.exists():raise ValueError('Evaluation output already exists')
 output.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['freeze','score','evaluate']);parser.add_argument('--folder',type=Path,default=DEFAULT);parser.add_argument('--prefix',type=Path);parser.add_argument('--output',type=Path);parser.add_argument('--predictions',type=Path);parser.add_argument('--outcomes',type=Path);args=parser.parse_args()
 if args.command=='freeze':freeze(args.folder)
 elif args.command=='score':score(args.folder,args.prefix,args.output)
 else:evaluate(args.folder,args.predictions,args.outcomes,args.output)
if __name__=='__main__':main()

