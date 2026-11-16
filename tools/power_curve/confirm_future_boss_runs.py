"""Confirm frozen research models on genuinely future uploaded runs.
Offline scoring of outcome-blind prefixes; not proof of live capture timing.
"""
import datetime,gzip,json
from pathlib import Path
import freeze_boss_experiment as f
import boss_readiness as b
import boss_development as dev
from ablate_boss_development import COMPOSITION
ROOT=b.ar.OUT

def future_run(start_time,upload_modified,freeze_time):
 cutoff=datetime.datetime.fromisoformat(freeze_time)
 return datetime.datetime.fromtimestamp(start_time,datetime.timezone.utc)>cutoff and datetime.datetime.fromisoformat(upload_modified)>cutoff

def main(root=ROOT):
 bundle=f.load_bundle(f.DEFAULT);source=root/'confirmation';metadata=json.loads((root/'current-prod-raw-metadata.json').read_text(encoding='utf-8-sig'));modified={x['Key']:x['Modified'] for x in metadata};candidate_keys=set();objects=0
 for path in (source/'raw').rglob('*.gz'):
  key=str(path.relative_to(source)).replace('\\','/')
  if key not in modified:continue
  with gzip.open(path,'rt',encoding='utf-8') as stream:
   for line in stream:
    raw=json.loads(line)
    if not raw.get('players') or not raw.get('map_point_history'):continue
    if future_run(raw['start_time'],modified[key],bundle['created_at']):candidate_keys.add((path.parent.name,raw['start_time']))
 b.ar.g.RAW=source/'raw';raws=b.ar.g.load();accepted=set()
 for path in (source/'users').glob('*/*.json.gz'):
  if not path.name.startswith('_'):
   for item in json.load(gzip.open(path,'rt',encoding='utf-8')).get('runs',[]):accepted.add(b.ar.signature(item['ts'],item['char'],item.get('seed')))
 catalog={'CARD.'+x['Entry']:x for x in json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'))['Cards']}
 ref={tuple(x['key']):x['value'] for x in bundle['references']};out=[];exclusions={}
 roster={'CHARACTER.'+x.upper() for x in json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'))['CharacterPools']}
 for sid,ts in sorted(candidate_keys):
  raw=raws[sid,ts];rid=b.ar.pseudonym(f'{sid}:{ts}');players=raw['players']
  if len(players)!=1:
   exclusions['multiplayer']=exclusions.get('multiplayer',0)+1;continue
  if raw.get('game_mode','standard')!='standard':
   exclusions['nonstandard_mode']=exclusions.get('nonstandard_mode',0)+1;continue
  if raw.get('was_abandoned'):
   exclusions['abandoned']=exclusions.get('abandoned',0)+1;continue
  char=players[0]['character']
  if char not in roster or b.ar.signature(ts,char,raw.get('seed')) not in accepted:
   exclusions['unsupported_or_unpublished']=exclusions.get('unsupported_or_unpublished',0)+1;continue
  if rid in bundle['training_runs']:raise ValueError('Future cohort contains a training run')
  rows,_=b.extract_run(raw,rid,b.ar.pseudonym(sid));ledger=dev.ledger(raw,catalog)
  if not any(r['task']=='boss_sequence' for r in rows):exclusions['no_eligible_boss_entry']=exclusions.get('no_eligible_boss_entry',0)+1
  for r in rows:
   if r['task']!='boss_sequence':continue
   composition={k:float(ledger[r['act']].get(k,0)) for k in COMPOSITION}
   # Source outcome is deliberately kept outside the predictor call.
   probabilities={variant:f.exported_prediction(model,f.make_features(r,composition,ref,variant)) for variant,model in bundle['models'].items()}
   out.append(dict(run=rid,act=r['act'],asc=r['asc'],character=char,clear=r['clear'],probabilities=probabilities,unsupported_character=char=='CHARACTER.FOOL'))
 report=dict(artifact_id=bundle['artifact_id'],kind='frozen algorithm evaluated on future-started future-uploaded runs; not live capture validation',qualifying_new_run_records=len(candidate_keys),exclusions=exclusions,boss_sequences=len(out),rows=out,status='insufficient evidence; manual population/calibration audit required')
 target=root/'confirmation/future-cohort-evaluation.json';target.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--snapshot-root',type=Path,default=ROOT);args=parser.parse_args();main(args.snapshot_root)
