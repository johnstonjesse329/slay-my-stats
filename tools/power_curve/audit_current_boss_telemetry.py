"""Measured evidence inventory with catalog-derived eligibility."""
import collections,json,gzip
import pandas as pd
import six_character_boss_study as current
import telemetry_report as t
import boss_readiness as b

def main():
 rows,_=current.dataset();raw=b.ar.g.load();accepted=set()
 for file in (current.SOURCE/'users').glob('*/*.json.gz'):
  if not file.name.startswith('_'):
   for r in json.load(gzip.open(file,'rt',encoding='utf-8')).get('runs',[]):accepted.add(b.ar.signature(r['ts'],r['char'],r.get('seed')))
 roster=current.core_roster(json.loads((b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8')))
 eligible={b.ar.pseudonym(f'{sid}:{ts}') for (sid,ts),r in raw.items() if current.eligible(r,accepted,roster)[0]}
 t.TELEMETRY=current.SOURCE/'telemetry';logs,older=t.load_logs(raw);out=[]
 for (sid,ts),log in logs.items():
  rid=b.ar.pseudonym(f'{sid}:{ts}')
  if rid not in eligible:continue
  r=raw[sid,ts];bosses={q.get('model_id') for act in r.get('map_point_history',[]) for p in act if p.get('map_point_type')=='boss' for q in p.get('rooms',[])}
  for f in log.get('fights',[]):out.append(dict(run=rid,player=b.ar.pseudonym(sid),asc=r.get('ascension',0),character=r['players'][0]['character'],boss=f.get('enc') in bosses,won=bool(f.get('won')),truncated=bool(log.get('truncated'))))
 d=pd.DataFrame(out);summary=dict(derived_logs=len(logs),older=older,eligible_logged_runs=d.run.nunique(),players=d.player.nunique(),fights=len(d),boss_fights=int(d.boss.sum()),boss_wins=int(d[d.boss].won.sum()),boss_losses=int((~d[d.boss].won).sum()),runs_by_asc={str(k):int(v) for k,v in d.groupby('asc').run.nunique().items()},runs_by_character=d.groupby('character').run.nunique().to_dict(),boss_by_asc={str(k):int(v) for k,v in d[d.boss].groupby('asc').size().items()},truncated_fights=int(d.truncated.sum()))
 d.to_csv(current.OUT/'telemetry_fights.csv',index=False);(current.OUT/'telemetry_summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
