"""Pair existing run grades with retrospective boss facts; no replacement grade invented."""
import html,json
import pandas as pd
from pathlib import Path
import six_character_boss_study as current
OUT=current.OUT/'grade_explanation_audit'

def main():
 OUT.mkdir(exist_ok=True);facts=pd.read_csv(current.OUT/'outcome_explanations/boss_facts.csv');ratings=pd.read_csv(current.OUT/'existing_grade_validation/ratings.csv');old=ratings[(ratings.scheme=='current_baked_baseline')&(ratings.stage=='completed_run')][['run','grade','won']].rename(columns={'grade':'current_run_grade','won':'run_won'})
 population=old.groupby('current_run_grade').agg(runs=('run','size'),wins=('run_won','sum')).reset_index();population.to_csv(OUT/'all_current_classes.csv',index=False)
 d=facts.merge(old,on='run',validate='many_to_one');d=d[d.hp_balanced&d.damage_balanced&(~d.truncated)&(d.unexplained_enemy_loss==0)&(d.additional_hp_cost>=0)&(d.won==d.raw_won)].copy()
 d['net_hp_spent']=d.starting_hp-d.ending_hp;d['retained_entry_hp']=d.ending_hp/d.starting_hp;d['energy_per_turn']=d.energy_spent/d.turns;d['cards_per_turn']=d.cards_played/d.turns;d['new_grade']='not assigned: no replacement ranking rule has been validated'
 d.to_csv(OUT/'paired_boss_facts.csv',index=False)
 summary=d.groupby('current_run_grade').agg(runs=('run','nunique'),boss_fights=('fight','size'),boss_wins=('won','sum'),ending_hp_min=('ending_hp','min'),ending_hp_median=('ending_hp','median'),ending_hp_max=('ending_hp','max'),turns_median=('turns','median'),damage_per_turn_median=('damage_per_turn','median'),net_hp_spent_median=('net_hp_spent','median'),players=('player','nunique')).reset_index();summary.to_csv(OUT/'grade_summary.csv',index=False)
 winners=d[d.run_won==1];winning_summary=winners.groupby('current_run_grade').agg(winning_runs=('run','nunique'),boss_fights=('fight','size'),minimum_end_hp=('ending_hp','min'),median_end_hp=('ending_hp','median'),maximum_end_hp=('ending_hp','max'),median_turns=('turns','median'),players=('player','nunique')).reset_index();winning_summary.to_csv(OUT/'winning_run_summary.csv',index=False)
 # Examples expose facts, not upward/downward grade assignments. Selection is
 # explicitly illustrative: extremes of recorded health margin in each old grade.
 examples=[]
 for grade,g in winners.groupby('current_run_grade'):
  for kind,r in [('smallest ending HP',g.sort_values('ending_hp').iloc[0]),('largest ending HP',g.sort_values('ending_hp',ascending=False).iloc[0])]:
   examples.append(dict(current_grade=grade,selection=kind,run=r.run,boss=r.boss,act=int(r.act),asc=int(r.asc),character=r.character,turns=int(r.turns),starting_hp=float(r.starting_hp),ending_hp=float(r.ending_hp),net_hp_spent=float(r.net_hp_spent),actual_damage=float(r.enemy_hp_removed),player_block=float(r.blocked),other_hp_cost=float(r.additional_hp_cost),healing=float(r.healed),energy_spent=float(r.energy_spent),new_grade='not assigned'))
 pd.DataFrame(examples).to_csv(OUT/'illustrative_disagreements.csv',index=False)
 notes='''# Existing grades versus recorded explanations

Current locally saved run grades are joined to accounting-checked boss fights from the copied snapshot. No live grades or ranking rules are changed. The comparison uses completed-run grades, not claims made before the outcome. A run's grade summarizes its whole history; one boss fight cannot by itself promote or demote the entire run. The new explanatory framing does not logically imply any particular replacement cutoff.

Winning runs are reported separately. Boss-level ending HP, damage and resources vary within a run class. Different encounters, characters, starting health and mechanics remain confounders: these aggregates and deliberately selected extremes are not power rankings or validated thresholds. Low ending HP is a health-margin fact, not automatically weak deck performance. HP paid intentionally by cards can be productive; a slow fight can be controlled. High block is not automatically stronger defense when the player faced more incoming attacks.

Instrumentation should first retain the old grade and record a separate explanation for each fight: observed damage/pace; actual player block and HP costs/healing; energy/cards used; and remaining health. Include recording completeness, endpoint provenance and unaccounted effects such as pet absorption. The candidate-grade column stays unassigned until a meaning and cutoff for a replacement are stated and tested.

The full raw-data population includes winning Rough runs; absence of a checked logged Rough winner here is a measurement-coverage limitation. Existing Mid/Rough are comparative performance labels, not declarations that a run must lose. See all_current_classes.csv for the complete saved-rating counts.

A later rank-change experiment must compare the same scope: boss grade versus boss grade, act versus act, run versus run. Fix rules before counting movements. Produce a transition table (old grade to candidate grade), then inspect every promotion/demotion against its event account. Keep A2+ health rules and A8/A9/A10 demands separate, and treat unknown as unknown. Historical outcome explains an observed win/loss; do not reward a run merely for having won or call resource margin a shuffle-win probability.
'''
 (OUT/'review.md').write_text(notes,encoding='utf-8');(OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Grade and explanation comparison</title><style>body{font:17px/1.6 system-ui;max-width:1250px;margin:30px auto;padding:20px}pre{white-space:pre-wrap}table{border-collapse:collapse;font-size:13px}td,th{padding:6px;border:1px solid #ddd}</style><pre>'+html.escape(notes)+'</pre><h2>Winning-run coverage and observed health margins</h2>'+winning_summary.to_html(index=False)+'<h2>All matched run classes</h2>'+summary.to_html(index=False)+'<h2>Illustrative facts, not new grades</h2>'+pd.DataFrame(examples).to_html(index=False),encoding='utf-8')
 print(winning_summary.to_string(index=False));print(pd.DataFrame(examples).to_string(index=False))
if __name__=='__main__':main()
