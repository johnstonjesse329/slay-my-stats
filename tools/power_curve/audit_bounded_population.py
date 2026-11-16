"""Reproduce population audit and verify bounded-goal artifacts."""
import hashlib,json,gzip
from pathlib import Path
import pandas as pd
import six_character_boss_study as c
import checkpoint_interactions as cp
from bounded_readiness_goal import FAMILIES,OUT

def main():
 rows,_=c.dataset();raw=c.b.ar.g.load();checkpoints=cp.dataset();records=[]
 for r in checkpoints:records.append(dict(run=r['run'],player=r['player'],character=r['char'],act=r['act'],asc=r['asc'],stage=f"fight{r['fight_index']}",endpoint='boss_sequence_clear',outcome=r['clear']))
 for r in rows:
  if r['task']=='boss_sequence':records.append(dict(run=r['run'],player=r['player'],character=r['char'],act=r['act'],asc=r['asc'],stage='boss_entry',endpoint='boss_sequence_clear',outcome=r['clear']))
 d=pd.DataFrame(records);d['difficulty']=d.asc.map(lambda x:'A0-1' if x<2 else 'A2-7' if x<8 else f'A{x}');lookup={}
 for (sid,ts),r in raw.items():
  rid=c.b.ar.pseudonym(f'{sid}:{ts}')
  for ai,points in enumerate(r.get('map_point_history',[])):lookup[rid,ai+1]=int(any(p.get('map_point_type')=='boss' for p in points))
 arrival=d[d.stage!='boss_entry'].copy();arrival['endpoint']='boss_arrival';arrival['outcome']=[lookup[r.run,r.act] for r in arrival.itertuples()]
 allrows=pd.concat([d,arrival]);allrows.groupby(['character','player','act','difficulty','stage','endpoint','outcome']).agg(n=('run','size'),runs=('run','nunique')).reset_index().to_csv(OUT/'eligible_population_audit.csv',index=False)
 accepted=set()
 for path in (c.SOURCE/'users').glob('*/*.json.gz'):
  if not path.name.startswith('_'):
   for item in json.load(gzip.open(path,'rt',encoding='utf-8')).get('runs',[]):accepted.add(c.b.ar.signature(item['ts'],item['char'],item.get('seed')))
 roster=c.core_roster(json.loads((c.b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8')));log_status=[]
 for path in (c.SOURCE/'telemetry').rglob('*.json.gz'):
  key=(path.parent.name,int(path.name.split('.')[0]));item=raw.get(key)
  ok,reason=c.eligible(item,accepted,roster) if item else (False,'missing_raw')
  log_status.append(dict(run=c.b.ar.pseudonym(f'{key[0]}:{key[1]}'),eligible=ok,reason=reason,abandoned=bool(item and item.get('was_abandoned')),raw_combats=sum(bool(q.get('turns_taken')) for a in (item or {}).get('map_point_history',[]) for node in a for q in node.get('rooms',[])),completed_raw_combats=sum(bool(q.get('turns_taken')) and node.get('player_stats',[{}])[0].get('current_hp',0)>0 for a in (item or {}).get('map_point_history',[]) for node in a for q in node.get('rooms',[])) ))
 pd.DataFrame(log_status).to_csv(OUT/'log_eligibility.csv',index=False)
 required=['feature_dictionary.csv','measurement_audit.csv','coverage_by_outcome_player.csv','boss_distributions.csv','matched_boss_contrasts.csv','counterexamples.csv','scores.csv','uncertainty.csv','predictions.csv','calibration_coverage_subgroups.csv','numerical_gate_audit.csv','family_gate_table.csv','prior_measurement_overlap.png','verification.json','tests.json','report.html','report.md','observations.csv','boss_diagnostics.csv','eligible_population_audit.csv','log_eligibility.csv']
 for name in required:
  if not (OUT/name).exists() or not (OUT/name).stat().st_size:raise ValueError('Missing '+name)
 manifest=json.loads((c.OUT/'snapshot-manifest.json').read_text());assert all(hashlib.sha256((c.SOURCE/name).read_bytes()).hexdigest()==sha for name,sha in manifest.items())
 tests=json.loads((OUT/'tests.json').read_text());assert tests['passed'] and tests['failures']==tests['errors']==0
 scores=pd.read_csv(OUT/'scores.csv');gates=pd.read_csv(OUT/'family_gate_table.csv');pred=pd.read_csv(OUT/'predictions.csv');dist=pd.read_csv(OUT/'boss_distributions.csv');audit=pd.read_csv(OUT/'numerical_gate_audit.csv');assert len(scores)==72;assert len(gates)==60;assert len(audit)==30
 expected={(s,p,f) for s in ['fight3','fight6','boss_entry'] for p in ['A0-1','A2-7','A8','A9','A10'] for f in FAMILIES};assert set(zip(gates.stage,gates.population,gates.family))==expected
 assert pred.p.between(0,1).all();assert not pred.duplicated(['run','act','stage','split','fold','family','model']).any();assert set(dist.family)==set(FAMILIES)
 # Every family has a documented result at every scope; no measured positive is asserted.
 assert set(gates.predictive_verdict)=={'insufficient evidence'};assert not audit.both_numerical_gates.any()
 specification=c.b.ar.ROOT/'docs/act-boss-readiness-instrumentation.md';assert specification.exists()
 result=dict(status='bounded investigation artifacts verified; negative/limited results, not universal target validation',snapshot_files_checked=len(manifest),snapshot_mismatches=0,model_comparisons=len(scores),family_scope_verdicts=len(gates),numerical_gate_rows=len(audit),tests=tests['tests_run'],tests_passed=tests['passed'],metric_family_gate_passes=0,required_artifacts={n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in required},specification_sha256=hashlib.sha256(specification.read_bytes()).hexdigest())
 (OUT/'completion-audit.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ['required_artifacts']},indent=2))
if __name__=='__main__':main()
