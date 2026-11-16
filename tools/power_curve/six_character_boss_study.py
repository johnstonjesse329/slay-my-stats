"""Catalog-derived six-character sensitivity study, separate from frozen v1.
Use current confirmation snapshot; accepted solo standard non-abandoned runs.
"""
import collections,gzip,hashlib,json
from pathlib import Path
import boss_readiness as b
import ablate_boss_development as study
ROOT=b.ar.OUT
SOURCE=ROOT/'confirmation'
OUT=ROOT/'six_character'

def core_roster(catalog):return {'CHARACTER.'+pool.upper() for pool in catalog['CharacterPools']}

def eligible(raw,accepted,roster):
 players=raw.get('players') or []
 if len(players)!=1:return False,'multiplayer_or_missing_player'
 if raw.get('game_mode','standard')!='standard':return False,'other_mode'
 if raw.get('was_abandoned'):return False,'abandoned'
 char=players[0].get('character','')
 if b.ar.signature(raw['start_time'],char,raw.get('seed')) not in accepted:return False,'not_published'
 if char not in roster:return False,'not_core_catalog'
 return True,'eligible'

def dataset():
 catalog=json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'));roster=core_roster(catalog);accepted=set();published=0
 for p in (SOURCE/'users').glob('*/*.json.gz'):
  if p.name.startswith('_'):continue
  for r in json.load(gzip.open(p,'rt',encoding='utf-8')).get('runs',[]):
   accepted.add(b.ar.signature(r['ts'],r['char'],r.get('seed')));published+=1
 b.ar.g.RAW=SOURCE/'raw';raw=b.ar.g.load();audit=collections.Counter();characters=collections.Counter();rows=[]
 for (sid,ts),r in raw.items():
  ok,reason=eligible(r,accepted,roster);audit[reason]+=1
  if not ok:continue
  characters[r['players'][0]['character']]+=1
  rr,a=b.extract_run(r,b.ar.pseudonym(f'{sid}:{ts}'),b.ar.pseudonym(sid));rows.extend(rr)
 report=dict(source=str(SOURCE),raw_records=len(raw),published_records=published,roster=sorted(roster),eligibility=dict(audit),eligible_characters=dict(characters),boss_sequence_observations=sum(r['task']=='boss_sequence' for r in rows),individual_boss_observations=sum(r['task']=='next_boss' for r in rows))
 OUT.mkdir(exist_ok=True);(OUT/'audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
 return rows,report

def main():
 # Only this process uses corrected eligibility. Frozen feature source files are unchanged.
 OUT.mkdir(parents=True,exist_ok=True);b.dataset=dataset;study.OUT=OUT/'ablation';study.main()
 manifest={str(p.relative_to(SOURCE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.rglob('*.gz')}
 (OUT/'snapshot-manifest.json').write_text(json.dumps(manifest,indent=2))
if __name__=='__main__':main()

