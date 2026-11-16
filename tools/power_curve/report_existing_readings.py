"""Plain-language report and physical anchors for existing readings."""
import json,html
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import validate_existing_readings as v
import six_character_boss_study as current
OUT=v.OUT

def main():
 rates=pd.read_csv(OUT/'win_rates.csv');ratings=pd.read_csv(OUT/'ratings.csv');anchors=pd.read_csv(OUT/'checkpoint_anchors.csv')
 # Anchor earlier acts using the grade already available at Act 3's third fight,
 # not the completed-run grade. Later fight outcomes do not select the prefix.
 current.b.ar.g.RAW=current.SOURCE/'raw';raw=current.b.ar.g.load();classes=ratings[(ratings.scheme=='run_holdout')&(ratings.stage=='act3_fight3')].set_index('run').grade.to_dict();obs=[]
 for (sid,ts),r in raw.items():
  rid=current.b.ar.pseudonym(f'{sid}:{ts}')
  if rid not in classes:continue
  fs=v.fd.run_fights({0:r})
  if not fs:continue
  prefix=dict(v.stages(fs[0]))['act3_fight3']
  for f in prefix:
   if f['died']:continue
   obs.append(dict(run=rid,player=current.b.ar.pseudonym(sid),character=r['players'][0]['character'],asc=r.get('ascension',0),difficulty='A0-1' if r.get('ascension',0)<2 else 'A2-7' if r.get('ascension',0)<8 else f"A{r['ascension']}",act=f['act']+1,encounter=f['enc'],grade_at_act3_fight3=classes[rid],turns=f['t'],net_hp=f['taken'],kind=f['kind']))
 data=pd.DataFrame(obs);data.to_csv(OUT/'early_grade_anchor_fights.csv',index=False)
 data.groupby(['grade_at_act3_fight3','act','difficulty','encounter','character']).agg(fights=('run','size'),runs=('run','nunique'),players=('player','nunique'),turns_q25=('turns',lambda x:x.quantile(.25)),turns_median=('turns','median'),turns_q75=('turns',lambda x:x.quantile(.75)),hp_q25=('net_hp',lambda x:x.quantile(.25)),hp_median=('net_hp','median'),hp_q75=('net_hp',lambda x:x.quantile(.75))).reset_index().to_csv(OUT/'early_class_encounter_anchors.csv',index=False)
 selected=rates[(rates.scheme=='run_holdout')&(rates.dimension=='all')&rates.stage.isin(['completed_run','act3_fight3'])&rates.grade.isin(['OP','Hype','Mid','Rough'])]
 fig,axes=plt.subplots(1,2,figsize=(10,4.5))
 for ax,stage,title in zip(axes,['completed_run','act3_fight3'],['Rating after run ends','Rating after Act 3 fight 3']):
  d=selected[selected.stage==stage].set_index('grade').reindex(['OP','Hype','Mid','Rough']);ax.bar(d.index,d.rate,color=['#58a79c','#72b780','#c3ad6a','#bf7572']);ax.set_ylim(0,1.13);ax.set_title(title);ax.set_ylabel('Fraction that won the run')
  for i,row in enumerate(d.itertuples()):ax.text(i,row.rate+.025,f'{row.rate:.0%}\n{row.wins}/{row.n}',ha='center',fontsize=10)
 fig.suptitle('Baseline rebuilt without the rated runs (historical snapshot)');fig.tight_layout();fig.savefig(OUT/'existing_readings.png',dpi=150);plt.close(fig)
 full=selected[selected.stage=='completed_run'][['grade','n','wins','rate']];early=selected[selected.stage=='act3_fight3'][['grade','n','wins','rate']]
 physical=anchors[(anchors.grade=='OP')&(anchors.stage=='act3_fight3')][['difficulty','n','players','wins','turns_median','turns_q25','turns_q75','hp_median','hp_q25','hp_q75']]
 notes='''# Can OP/Hype anchor real performance baselines?

## Answer

Yes for OP as a promising lower-ascension starting cohort. No for the blanket claim that OP and Hype are both almost certain run wins. Stage and difficulty must remain attached to the label.

On the current saved baked baseline, completed-run OP wins 83/87 (95.4%), Hype 75/173 (43.4%), Mid 206/504 (40.9%). Rebuilding references and grade cutoffs without the test runs gives OP 73/76 (96.1%), Hype 84/175 (48.0%), Mid 182/430 (42.3%). OP has much stronger outcome separation than Hype.

The more useful check is a grade already known before the ending: after Act 3's first three completed fights, OP wins 95/101 (94.1%) in run holdout, 80/88 (90.9%) in player holdout and 60/64 (93.8%) in forward-time tests. Overall run win rate among those checkpoint survivors is about 70%. Hype at that point wins about 83–86%. That is evidence of useful separation, not certainty for an individual run.

## Critical high-ascension exception

At Act 3 fight 3, OP wins 41/42 at A0–1, 30/30 at A2–7, 10/11 at A8, 3/3 at A9 and 11/15 at A10 in run holdout. Player holdout A10 is 10/15. A9 is far too small for confidence. Immediately before the first Act 3 boss, OP A10 is only 7/12 in run holdout. An apparently excellent early performance profile does not establish double-boss readiness. Existing code pools A8+ encounter reference lines; that does not distinguish A9 damage or A10 sequence demands.

## What we can anchor

The OP cohort identified at Act 3 fight 3 gives physical descriptions of earlier observed fights. At A0–1, the median average Act 3 fight takes about 2.8 turns and costs 0.7 net HP; at A2–7, about 3 turns and zero net HP. The middle half and sample sizes are in checkpoint_anchors.csv. A10 OP can post similarly fast/low-cost numbers and still lose, so these cannot be universal sufficient cutoffs.

Use early_grade_anchor_fights.csv and early_class_encounter_anchors.csv to compare the actual encounters and characters that those early-identified classes faced. Preserve boss/elite/normal kind, act, ascension/resource tier, sample size and player coverage. The encounter/character cells are often small. Anchors are descriptive candidate ranges, not validated new thresholds. Every class retains its losses; selecting winners only would make the anchor look cleaner than it is.

For act readiness, validate the act's Hype label against that act's clearance, not against winning all later acts. At lower levels, Hype immediately before an act boss is often strong, while A9/A10 remain much weaker or sparse. Exact values are in act_clear_rates.csv. A Hype Act 1 can be good for Act 1 without guaranteeing Act 3.

## How the current labels work

Hype is driven mainly by low net HP cost relative to winning encounters, with fast kills able to lift a middle defensive reading. OP requires Hype in both Acts 2 and 3. It cannot exist in Act 1 or after Act 2 alone, and it inherently selects runs that survived into Act 3. Run-level and act-level labels use different aggregated cutoffs. Completed-run descriptions use later fights; they are not predictions made in Act 1.

The existing rating intentionally omits the final fight of a lost run. We preserve that behavior to test the current feature, not redesign it. A losing run can therefore still finish with a Hype/OP description. This is one reason to inspect earlier checkpoints and failures explicitly.

## Method and scope

Existing copied six-character production snapshot; published standard solo, non-abandoned core-character runs only. No new data, live game saves or deployments. Current-baked-baseline results reproduce the local saved fight_demand.json definitions; they are not a fresh assertion about the deployed site's artifact. Run/player/time validations rebuild encounter references and winning-run cutoffs from training runs only. All acts of a run remain together. Time splits use run start time, not upload availability. Baselines normalize by encounter; grades are still relative, not intrinsic capacities. No new model or threshold tuning was performed.

Physical HP cost means max(0, room damage minus healing), not measured block. Turns are recorded fight turns, not a simulated damage capacity. Aggregate per-fight numbers are encounter/path dependent. Current-HP and character/strategy confounding remain. A2+ healing differences stay separate from enemy-tuning tiers in the tables.

Rates and intervals are descriptive historical results. Seven uploaders, correlated acts and repeated exploration of this snapshot limit generalization. Success in A0–7 cannot validate A9/A10 or Dread. This analysis supports a stage-specific OP anchor hypothesis, not a universally guaranteed baseline.

## Practical next step

Anchor candidate numbers to an OP grade already observed early enough to be useful, separately by act, encounter and difficulty. Freeze those candidate ranges, then test them as direct rules on held-out runs—including high-performing losses and Hype/Mid runs. Do not simply rename the OP-class median as a required amount of damage or block. Hype needs its own stage/act-specific validation and should not be pooled with OP as an almost-certain-win class.
'''
 (OUT/'review.md').write_text(notes,encoding='utf-8');(OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Validating OP and Hype</title><style>body{font:17px/1.6 system-ui;max-width:1150px;margin:35px auto;padding:20px}pre{white-space:pre-wrap}table{border-collapse:collapse;font-size:14px}td,th{padding:7px;border:1px solid #ddd}img{max-width:100%}</style><pre>'+html.escape(notes)+'</pre><h2>Completed-run classes, run holdout</h2>'+full.to_html(index=False)+'<h2>Classes already present at Act 3 fight 3</h2>'+early.to_html(index=False)+'<img src="existing_readings.png" alt="Run win rates by grade and checkpoint"><h2>OP cohort: actual early Act 3 performance</h2>'+physical.to_html(index=False),encoding='utf-8')
 print('Wrote',OUT/'review.html')
if __name__=='__main__':main()
