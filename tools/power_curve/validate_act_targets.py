"""Exploratory act-clear analysis; reads a production raw snapshot, writes aggregates only.
Fixed bands are hypotheses, not calibrated thresholds. No boss outcomes enter features.
"""
import collections, json, statistics, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gamma_curves as g
import fight_demand as fd

def band(x):
    return '0-5' if x <= 5 else '5-10' if x <= 10 else '10+'

def rate(rows):
    n=len(rows); k=sum(r['clear'] for r in rows)
    if not n: return {'n':0}
    p=k/n; z=1.96; den=1+z*z/n
    mid=(p+z*z/(2*n))/den
    half=z*((p*(1-p)/n+z*z/(4*n*n))**.5)/den
    return {'n':n,'cleared':k,'pct':round(100*p,1),'wilson95':[round(100*(mid-half),1),round(100*(mid+half),1)]}

def main():
    root=Path(__file__).resolve().parents[2]
    g.RAW=root/'local_data/act_validation/raw'
    raw=g.load(); rows=[]; inventory=collections.Counter(); transitions=[]
    for (sid,ts),r in raw.items():
        mode=r.get('game_mode','standard'); asc=r.get('ascension') or 0
        inventory[(mode, 'solo' if len(r['players'])==1 else 'coop')]+=1
        if mode!='standard' or len(r['players'])!=1 or r.get('was_abandoned'): continue
        runs=fd.run_fights({0:r})
        if not runs: continue
        fights=runs[0]; tier='A0-7' if asc<8 else 'A8' if asc==8 else 'A9' if asc==9 else 'A10+'
        prev=None
        for act in sorted({f['act'] for f in fights}):
            fs=[f for f in fights if f['act']==act]
            bosses=[f for f in fs if f['kind']=='boss']
            clear=bool(bosses) and not any(f['died'] for f in bosses) and (act<max(f['act'] for f in fights) or bool(r.get('win')))
            before=[]
            for f in fs:
                if f['kind']=='boss' or f['died']: break
                before.append(f)
            if len(before)<3: continue
            for checkpoint,sample in [('first3',before[:3]),('preboss',before[-3:])]:
                if checkpoint=='preboss' and not bosses: continue
                loss=statistics.mean(f['taken'] for f in sample)
                row={'player':sid,'ts':ts,'act':act+1,'tier':tier,'checkpoint':checkpoint,'clear':clear,'band':band(loss),'loss':loss,'turns':statistics.mean(f['t'] for f in sample)}
                rows.append(row)
                if checkpoint=='first3':
                    if prev: transitions.append((prev['band'],row['band']))
                    prev=row
    report={'runs':len(raw),'players':len({k[0] for k in raw}), 'inventory':{str(k):v for k,v in inventory.items()},'groups':{},'transitions':{str(k):v for k,v in collections.Counter(transitions).items()}}
    for checkpoint in ['first3','preboss']:
        for tier in ['A0-7','A8','A9','A10+']:
            for act in [1,2,3]:
                subset=[r for r in rows if r['checkpoint']==checkpoint and r['tier']==tier and r['act']==act]
                if not subset: continue
                report['groups'][f'{checkpoint} {tier} act{act}']={b:rate([r for r in subset if r['band']==b]) for b in ['0-5','5-10','10+']}
    report['player_checks']={}
    for i,sid in enumerate(sorted({r['player'] for r in rows})):
        subset=[r for r in rows if r['player']==sid and r['checkpoint']=='first3' and r['tier']=='A0-7']
        report['player_checks'][f'player{i+1}']={b:rate([r for r in subset if r['band']==b]) for b in ['0-5','5-10','10+']}
    out=root/'local_data/act_validation/report.json'; out.write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
