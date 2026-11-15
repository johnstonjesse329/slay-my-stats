"""Retrospective fight explanations from copied raw runs and measured event logs.
Explains recorded accounting and observed consistency; no win-prediction fitting.
"""
import collections,gzip,json,html,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import six_character_boss_study as current
import telemetry_report as tr
OUT=current.OUT/'outcome_explanations'

def explain(f, saved_ending_hp=None):
 hp0,hp1=f.get('hp0'),f.get('hp1');end_source='logged combat end'
 if hp1 is None and not f.get('won') and saved_ending_hp==0:hp1=0;end_source='saved run death state (no logged combat end)'
 actual_enemy=max(0,f['taken']-f.get('overkill',0));other=f['hp_in']-actual_enemy
 hp_balanced=hp0 is not None and hp1 is not None and hp0-hp1==f['hp_in']-f['hp_out']
 damage_balance=abs(f['enemy_lost']-(f['dealt_removed']+f.get('enemy_unexplained',0)))<1e-6
 turns=f.get('turns',[]);n=len(turns)
 return dict(ending_hp_source=end_source,won=bool(f['won']),turns=n,starting_hp=hp0,ending_hp=hp1,enemy_hp_removed=f['dealt_removed'],enemy_healed=f.get('enemy_healed',0),unexplained_enemy_loss=f.get('enemy_unexplained',0),damage_per_turn=f['dealt_removed']/n if n else None,blocked=f['blocked'],enemy_damage_suffered=actual_enemy,killing_blow_excess=f.get('overkill',0),additional_hp_cost=other,healed=f['hp_out'],hp_balanced=hp_balanced,damage_balanced=damage_balance,energy_spent=f['spent'],cards_played=sum(len(t['played']) for t in turns),draw_events=sum(len(t['drawn']) for t in turns),zero_output_turns=sum(t['enemy_lost']==0 for t in turns),blocked_share=f['blocked']/max(1,f['blocked']+f['taken']),observed_damage_sd=float(np.std([t['enemy_lost'] for t in turns])) if n and f.get('enemy_unexplained',0)==0 else None,opening_enemy_pool=f.get('pool'))

def main():
 OUT.mkdir(exist_ok=True);all_records,eligibility=current.dataset();raw=current.b.ar.g.load();accepted=set()
 for path in (current.SOURCE/'users').glob('*/*.json.gz'):
  if not path.name.startswith('_'):
   for r in json.load(gzip.open(path,'rt',encoding='utf-8')).get('runs',[]):accepted.add(current.b.ar.signature(r['ts'],r['char'],r.get('seed')))
 catalog=json.loads((current.b.ar.ROOT/'card_game_data.json').read_text(encoding='utf-8'));roster=current.core_roster(catalog);tr.TELEMETRY=current.SOURCE/'telemetry';logs,_=tr.load_logs(raw);rows=[];turn_rows=[]
 for (sid,ts),log in logs.items():
  r=raw.get((sid,ts))
  if not r or not current.eligible(r,accepted,roster)[0]:continue
  rid=current.b.ar.pseudonym(f'{sid}:{ts}');bosses=[]
  for ai,points in enumerate(r['map_point_history']):
   for point in points:
    if point.get('map_point_type')=='boss':
     bosses.extend((ai+1,q['model_id'],point['player_stats'][0]) for q in point.get('rooms',[]) if q.get('turns_taken'))
  for act,enc,stats in bosses:
   matches=[f for f in log['fights'] if f['enc']==enc]
   if len(matches)!=1:continue
   f=matches[0];x=explain(f,stats.get('current_hp'));key=f'{rid}:{act}:{enc}'
   row=dict(fight=key,run=rid,player=current.b.ar.pseudonym(sid),act=act,asc=r.get('ascension',0),character=r['players'][0]['character'],boss=enc,raw_won=stats.get('current_hp',0)>0,raw_ending_hp=stats.get('current_hp'),truncated=log.get('truncated'),**x);rows.append(row)
   for i,t in enumerate(f['turns']):turn_rows.append(dict(fight=key,turn=i+1,enemy_hp_lost=t['enemy_lost'],damage_taken=t['taken'],damage_blocked=t['blocked'],energy_spent=t['spent'],cards_played=len(t['played']),draw_events=len(t['drawn']),enemy_phase=bool(t['enemy_side'])))
 field_counts=collections.Counter();raw_bosses=0
 for (sid,ts),r in raw.items():
  if not current.eligible(r,accepted,roster)[0]:continue
  for points in r['map_point_history']:
   for point in points:
    if point.get('map_point_type')!='boss':continue
    stats=point.get('player_stats',[{}])[0]
    for room in point.get('rooms',[]):
     if not room.get('turns_taken'):continue
     raw_bosses+=1
     for key in ['current_hp','max_hp','damage_taken','hp_healed']:field_counts[key]+=int(key in stats)
     field_counts['turns_taken']+=1
 (OUT/'raw_field_coverage.json').write_text(json.dumps(dict(raw_boss_fights=raw_bosses,fields_present=dict(field_counts)),indent=2))
 d=pd.DataFrame(rows);turns=pd.DataFrame(turn_rows);d.to_csv(OUT/'boss_facts.csv',index=False);turns.to_csv(OUT/'turn_facts.csv',index=False)
 clean=d[d.hp_balanced&d.damage_balanced&(~d.truncated)&(d.won==d.raw_won)&(d.additional_hp_cost>=0)&(d.unexplained_enemy_loss==0)]
 # Transparent illustrative selection: high-HP finish, narrow-HP finish, damage-cost loss.
 choices=[]
 wins=clean[clean.won];losses=clean[~clean.won]
 if len(wins):choices.append(('Win with a large recorded health margin',wins.sort_values(['ending_hp','turns'],ascending=[False,True]).iloc[0]))
 if len(wins):choices.append(('Win with a narrow recorded health margin',wins.sort_values(['ending_hp','turns']).iloc[0]))
 if len(losses):choices.append(('Loss with recorded incoming pressure',losses.sort_values('enemy_damage_suffered',ascending=False).iloc[0]))
 examples=[]
 from act_targets import wilson
 def tier(asc):return 'A0-1' if asc<2 else 'A2-7' if asc<8 else f'A{asc}'
 for title,r in choices:
  name=r.boss.replace('ENCOUNTER.','').replace('_BOSS','').replace('_',' ').title();result='Won' if r.won else 'Lost'
  hp=f"Started at {r.starting_hp:g} HP; enemy damage removed {r.enemy_damage_suffered:g}, additional HP costs removed {r.additional_hp_cost:g}, and healing restored {r.healed:g}. Ended at {r.ending_hp:g} HP."
  damage=f"Removed {r.enemy_hp_removed:g} enemy HP in {r.turns:g} recorded turns ({r.damage_per_turn:.1f} HP/turn)."
  defense=f"Player block absorbed {r.blocked:g} damage; {r.enemy_damage_suffered:g} enemy damage reached HP."
  engine=f"Recorded {r.energy_spent:g} energy spent and {r.cards_played:g} cards played."
  comparison=[x for x in all_records if x['task']=='next_boss' and x['boss']==r.boss and x['char']==r.character and tier(x['asc'])==tier(r.asc)]
  cw=sum(x['clear'] for x in comparison);cn=len(comparison);cl,ch=wilson(cw,cn)
  context=f"In this saved sample, {cw} of {cn} {r.character.replace('CHARACTER.','').title()} entries beat this boss at {tier(r.asc)}. This is encounter history, not this deck's replay probability."
  examples.append(dict(historical_comparison=context,historical_n=cn,historical_wins=cw,historical_interval=[cl,ch],historical_players=len({x['player'] for x in comparison}),title=title,boss=name,asc=int(r.asc),character=r.character.replace('CHARACTER.','').title(),result=result,hp_account=hp,damage=damage,defense=defense,engine=engine,fight=r.fight,extra_enemy_recovery=float(r.enemy_healed),unexplained_enemy_loss=float(r.unexplained_enemy_loss),killing_blow_excess=float(r.killing_blow_excess),ending_hp_source=r.ending_hp_source))
 (OUT/'examples.json').write_text(json.dumps(examples,indent=2));inventory=dict(raw_records=eligibility['raw_records'],published_records=eligibility['published_records'],eligible_solo_standard_runs=eligibility['eligibility']['eligible'],logged_runs=len({r['run'] for r in rows}),unique_matched_boss_fights=len(d),accounting_checked_boss_fights=len(clean),accounting_mismatch_fights=int((~d.hp_balanced).sum()),raw_end_hp_disagreement=int((d.ending_hp!=d.raw_ending_hp).sum()),damage_accounting_mismatches=int((~d.damage_balanced).sum()),measured_ascensions=sorted(d.asc.unique().tolist()),measured_players=d.player.nunique())
 (OUT/'inventory.json').write_text(json.dumps(inventory,indent=2));print(json.dumps(inventory,indent=2));print(json.dumps(examples,indent=2))
 # Link each explanatory number to a turn ledger; do not invent a cause or probability.
 notes='''# Explaining completed fights: what the snapshot supports

We can explain the recorded arithmetic of a win or loss, and inspect how the output developed. This is a different and better-supported task than forecasting boss clearance from earlier fights.

The raw run records usually provide fight turns, damage taken, healing, HP and acquisitions. They do not provide actual damage dealt, block absorbed, energy use, draw order or a chance of winning. Event logs provide much of that detail for a smaller low-ascension subset. Detailed examples below are selected for illustration, not to estimate a population win rate.

## Supported explanations

- Damage: actual attributed HP removed, recorded turns and observed output profile. Enemy recovery and unexplained disappearance are flagged separately.
- Defense: incoming enemy damage that block actually absorbed and damage that reached HP. This is player-hit accounting, not all mitigation. Pet absorption is not included in this block total. Damage avoided by killing early, Weak or other prevention is not quantified here; exact causal prevention requires additional evidence or a counterfactual model.
- Engine use: actual energy spent and cards played. These show what was used, not how much more the deck could have done or which card caused a win.
- Margin: recorded HP balance and ending HP. A low ending margin means a close observed finish, not an independently estimated probability of losing.
- Consistency: turn-level output and variability. Zero-output turns can be setup/defense turns, not necessarily bad draws. No single-fight variability statistic establishes a repeat-win probability.

Loss logs often lack a combat-end event. When the saved fight records death, this retrospective view may use its 0 HP endpoint; the recorded HP movements must still reconcile independently. That fallback is explicitly marked and is not an input for predicting the fight. Examples exclude any unexplained enemy HP removal.

HP accounting: starting HP - actual enemy HP loss - additional HP costs + actual healing = ending HP. Excess damage on the killing blow is not subtracted from HP twice. Block prevents enemy damage, so do not subtract absorbed block from HP. Additional HP costs aggregate all HP outflow not explained by enemy hits and are not automatically attributed to a particular card.

Log-end HP can differ from saved room-end HP because recording/room boundaries differ. The discrepancy is exposed in boss_facts.csv; explanation uses one consistent logged interval rather than mixing endpoints. HP-flow balance is necessary but not sufficient proof of perfect recording. Target-boss stats are allowed here precisely because this is a retrospective explanation, not a prediction.

## What probability can mean

A recorded win has an observed outcome, not a new computed chance that it happened. We can report the historical clear fraction among comparable encounters/characters/difficulties, with counts and uncertainty, where the sample supports it. That describes the recorded population under its actual player choices and paths. It is not the chance this same deck wins under different shuffles.

Same-deck repeatability, damage prevented by a faster kill, and the causal contribution of a card need counterfactual evidence or a separately validated simulator. We do not currently have validated probabilities for those claims. We can display observed swing/low-output turns and the health cushion without calling them a win probability.

No live saves, fresh production fetches or site changes were used. Existing copied six-character snapshot only. Raw outcomes cover far more runs than detailed measured explanations. The current measured subset does not validate high-ascension mechanics or Dread.
'''
 text=notes+'\n## Checked examples\n'
 for e in examples:text+='\n### '+e['title']+'\n\n'+f"{e['character']} A{e['asc']} vs {e['boss']}: {e['result']}. "+e['damage']+' '+e['defense']+' '+e['hp_account']+' '+e['engine']+' '+e['historical_comparison']+f" HP endpoint source: {e['ending_hp_source']}. Enemy HP restored: {e['extra_enemy_recovery']:g}; unexplained enemy HP loss: {e['unexplained_enemy_loss']:g}; killing-blow excess: {e['killing_blow_excess']:g}.\n"
 (OUT/'review.md').write_text(text,encoding='utf-8');cards=''.join('<article><h2>'+html.escape(e['title'])+'</h2><p><b>'+html.escape(f"{e['character']} A{e['asc']} vs {e['boss']}: {e['result']}")+'</b></p><p>'+html.escape(e['damage']+' '+e['defense'])+'</p><p>'+html.escape(e['hp_account']+' Endpoint: '+e['ending_hp_source']+'.')+'</p><p>'+html.escape(e['engine'])+'</p><p>'+html.escape(e['historical_comparison'])+'</p></article>' for e in examples)
 (OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Why this fight ended this way</title><style>body{font:17px/1.6 system-ui;max-width:1000px;margin:35px auto;padding:20px}pre{white-space:pre-wrap}article{border:1px solid #ccc;border-radius:8px;padding:20px;margin:20px 0}</style><h1>Explain the result using recorded numbers</h1>'+cards+'<pre>'+html.escape(notes)+'</pre><h2>Snapshot coverage</h2><pre>'+html.escape(json.dumps(inventory,indent=2))+'</pre>',encoding='utf-8')
if __name__=='__main__':main()
