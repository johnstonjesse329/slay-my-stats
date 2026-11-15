"""Inventory measured boss evidence before attempting mechanical thresholds."""
import collections,json
import pandas as pd
import boss_readiness as b
import telemetry_report as t

def main():
 rows,_=b.dataset();eligible={r['run'] for r in rows};raw=b.ar.g.load();t.TELEMETRY=b.ar.OUT/'telemetry';logs,older=t.load_logs(raw);out=[]
 for (sid,ts),log in logs.items():
  rid=b.ar.pseudonym(f'{sid}:{ts}')
  if rid not in eligible:continue
  r=raw[sid,ts];boss_ids={room.get('model_id') for act in r.get('map_point_history',[]) for p in act if p.get('map_point_type')=='boss' for room in p.get('rooms',[])}
  for f in log.get('fights',[]):
   turns=f.get('turns',[])
   out.append(dict(run=rid,player=b.ar.pseudonym(sid),asc=r.get('ascension',0),character=r['players'][0]['character'],enc=f.get('enc'),boss=f.get('enc') in boss_ids,won=f.get('won'),truncated=log.get('truncated',False),turns=len(turns),damage=sum(x.get('dmg',0)+x.get('dmg_other',0) for x in turns),taken=sum(x.get('taken',0) for x in turns),blocked=sum(x.get('blocked',0) for x in turns)))
 d=pd.DataFrame(out);path=b.OUT/'telemetry_audit';path.mkdir(exist_ok=True);d.to_csv(path/'fights.csv',index=False)
 summary=dict(total_logs=len(logs),older=older,eligible_logged_runs=d.run.nunique(),players=d.player.nunique(),eligible_fights=len(d),boss_fights=int(d.boss.sum()),boss_wins=int(d[d.boss].won.sum()),boss_losses=int((~d[d.boss].won.astype(bool)).sum()),ascensions={str(k):int(v) for k,v in d.groupby('asc').run.nunique().items()},boss_by_asc={str(k):int(v) for k,v in d[d.boss].groupby('asc').size().items()})
 (path/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
if __name__=='__main__':main()
