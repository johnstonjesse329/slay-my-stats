"""Locked-model evaluation on newly discovered, pre-freeze production uploads.
This is untouched retrospective evidence, never prospective or independent players.
"""
import collections,gzip,json
from pathlib import Path
import freeze_boss_experiment as frozen
import boss_readiness as b
import boss_development as dev
from ablate_boss_development import COMPOSITION

ROOT=b.ar.OUT;FOLDER=ROOT/'boss/frozen-v1';CURRENT=ROOT/'confirmation'

def main():
 bundle=frozen.load_bundle(FOLDER);training=set(bundle['training_runs']);known={p.replace('\\','/') for p in bundle['snapshot_files']};new_files=[p for p in (CURRENT/'raw').rglob('*.gz') if str(p.relative_to(CURRENT)).replace('\\','/') not in known];new_ids=set()
 for path in new_files:
  sid=path.parent.name
  with gzip.open(path,'rt',encoding='utf-8') as f:
   for line in f:
    if not line.strip():continue
    r=json.loads(line)
    if isinstance(r,dict) and r.get('start_time') is not None:new_ids.add(b.ar.pseudonym(f"{sid}:{r['start_time']}"))
 b.ar.g.RAW=CURRENT/'raw';raw=b.ar.g.load();rows=[]
 published=set()
 for file in (CURRENT/'users').glob('*/*.json.gz'):
  if not file.name.startswith('_'):
   for item in json.load(gzip.open(file,'rt',encoding='utf-8')).get('runs',[]):published.add(b.ar.signature(item['ts'],item['char'],item.get('seed')))
 for (sid,ts),item in raw.items():
  rid=b.ar.pseudonym(f'{sid}:{ts}')
  if rid not in new_ids or rid in training or len(item['players'])!=1 or item.get('was_abandoned') or item.get('game_mode','standard')!='standard':continue
  if b.ar.signature(ts,item['players'][0]['character'],item.get('seed')) not in published:continue
  extracted,_=b.extract_run(item,rid,b.ar.pseudonym(sid));rows.extend(extracted)
 test=[r for r in rows if r['task']=='boss_sequence'];catalog={'CARD.'+r['Entry']:r for r in json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'))['Cards']};ledgers={}
 for (sid,ts),r in raw.items():
  rid=b.ar.pseudonym(f'{sid}:{ts}')
  if rid in new_ids:
   for act,x in dev.ledger(r,catalog).items():ledgers[rid,act]={k:float(x.get(k,0)) for k in COMPOSITION}
 ref={tuple(r['key']):r['value'] for r in bundle['references']};output=[]
 for r in test:
  probs={variant:frozen.exported_prediction(model,frozen.make_features(r,ledgers[r['run'],r['act']],ref,variant)) for variant,model in bundle['models'].items()}
  output.append({k:r[k] for k in ['run','player','act','asc','boss','clear','hp','maxhp']}|dict(probabilities=probs,character=r['char'],unsupported_character=r['char']=='CHARACTER.FOOL'))
 result=dict(artifact_id=bundle['artifact_id'],kind='newly discovered pre-freeze uploads; retrospective only',new_uploads=len(new_files),new_uploaded_run_ids=len(new_ids),not_training_run_ids=len(new_ids-training),eligible_boss_sequences=len(output),players=len({r['player'] for r in output}),rows=output)
 (CURRENT/'locked-model-evaluation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
