"""Render bounded goal deliverables and audit tables from saved experiment results."""
import hashlib,json,html
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from bounded_readiness_goal import OUT,FAMILIES
import six_character_boss_study as current

SPECS={
'damage_rate':('Damage and pace','sum attributed enemy HP removed / observed player turns','HP/turn'),
'early_damage_rate':('Damage and pace','mean enemy HP delta over first two observed turns per fight','HP/turn'),
'late_damage_rate':('Damage and pace','mean enemy HP delta over observed turns after turn two; unknown if none','HP/turn'),
'late_available':('Damage and pace','whether any turn after turn two was observed','flag'),
'fight_turns':('Damage and pace','sum observed turns / completed fights in window','turns/fight'),
'early_enemy_cost':('Setup and burst safety','mean enemy damage taken over first two turns per fight','HP/turn'),
'worst_enemy_cost':('Setup and burst safety','maximum enemy damage taken on one observed turn','HP/turn'),
'early_zero_fraction':('Setup and burst safety','fraction of first two turns with zero enemy HP removed','fraction'),
'absorbed_rate':('Defense and endurance','sum enemy damage actually absorbed by block / observed turns','HP/turn'),
'net_hp_per_fight':('Defense and endurance','sum max(0, logged HP outflow minus inflow) / fights','HP/fight'),
'enemy_cost_rate':('Defense and endurance','sum enemy damage taken / observed turns','HP/turn'),
'zero_fraction':('Consistency','fraction of observed turns with zero enemy HP removed','fraction'),
'damage_sd':('Consistency','population SD of enemy HP removed over observed turns','HP/turn'),
'enemy_cost_sd':('Consistency','population SD of enemy damage taken over observed turns','HP/turn')}

def difficulty(asc):return 'A0-1' if asc<2 else 'A2-7' if asc<8 else f'A{asc}'

def main():
 d=pd.read_csv(OUT/'observations.csv');diag=pd.read_csv(OUT/'boss_diagnostics.csv');audit=pd.read_csv(OUT/'measurement_audit.csv');scores=pd.read_csv(OUT/'scores.csv');unc=pd.read_csv(OUT/'uncertainty.csv');p=pd.read_csv(OUT/'predictions.csv')
 for frame in [d,diag,audit,p]:frame['difficulty']=frame.asc.map(difficulty)
 coverage=audit.groupby(['stage','difficulty','player','clear','reason']).size().reset_index(name='n');coverage.to_csv(OUT/'coverage_by_outcome_player.csv',index=False)
 dictionary=pd.DataFrame([dict(metric=k,family=v[0],formula=v[1],units=v[2],required='aligned three completed prior fights, complete turns, HP balance, no unexplained HP disappearance',quality='unknown when absent/ambiguous; late output requires late_available',interpretation='observed performance; no intrinsic capability or sufficiency grade') for k,v in SPECS.items()]);dictionary.to_csv(OUT/'feature_dictionary.csv',index=False)
 # Side-by-side distributions at comparable contexts; no causal claims or forced pooling.
 distributions=[];contrasts=[];counterexamples=[]
 for kind,frame in [('prior_fights',d[d.stage=='boss_entry'].copy()),('target_boss_diagnostic',diag.copy())]:
  frame['hp_band']=pd.cut(frame.hp/frame.maxhp,[0,.5,.75,1,10],labels=['<=50%','50-75%','75-100%','>100%'])
  for keys,g in frame.groupby(['boss','act','difficulty','char','hp_band'],observed=True):
   context=dict(zip(['boss','act','difficulty','character','entry_hp_band'],map(str,keys)))
   matched=g.clear.nunique()==2
   for outcome,part in g.groupby('clear'):
    for family,metrics in FAMILIES.items():
     for metric in metrics:
      if metric=='late_available':continue
      x=part[metric]
      if metric=='late_damage_rate':x=x[part.late_available==1]
      distributions.append(context|dict(kind=kind,family=family,metric=metric,clear=outcome,n=len(x),runs=part.run.nunique(),players=part.player.nunique(),q25=x.quantile(.25),median=x.median(),q75=x.quantile(.75),min=x.min(),max=x.max(),matched_outcomes=matched))
   if matched:
    for family,metrics in FAMILIES.items():
     metric=metrics[0];wins=g[g.clear==1];losses=g[g.clear==0]
     contrasts.append(context|dict(kind=kind,family=family,metric=metric,wins=len(wins),losses=len(losses),players=g.player.nunique(),winner_median=wins[metric].median(),loser_median=losses[metric].median(),status='descriptive small matched context; no causal test'))
     # Predeclared counterexample direction: high output/block or low cost/variability
     # may still lose. This is an illustration, not optimized threshold evidence.
     for _,loss in losses.iterrows():
      metric={'damage':'damage_rate','setup':'early_enemy_cost','endurance':'absorbed_rate','consistency':'damage_sd'}[family]
      candidate=wins[wins[metric]<=loss[metric]] if family in ['damage','endurance'] else wins[wins[metric]>=loss[metric]]
      if len(candidate):
       win=candidate.iloc[0];counterexamples.append(context|dict(kind=kind,family=family,metric=metric,failed_run=loss.run,cleared_run=win.run,failed_value=loss[metric],cleared_value=win[metric],note='same observed context; not proof of same deck/route or causal mechanism'))
 pd.DataFrame(distributions).to_csv(OUT/'boss_distributions.csv',index=False);pd.DataFrame(contrasts).to_csv(OUT/'matched_boss_contrasts.csv',index=False);pd.DataFrame(counterexamples).to_csv(OUT/'counterexamples.csv',index=False)
 # Explicit grid, including absent populations.
 gates=[]
 for stage in ['fight3','fight6','boss_entry']:
  for population in ['A0-1','A2-7','A8','A9','A10']:
   cohort=d[(d.stage==stage)&(d.difficulty==population)]
   for family in FAMILIES:
    missing='no validated measurements in this population' if len(cohort)==0 else 'too few independent players and outcome contrasts; inspect constant-fold counts; no supported cross-population borrowing'
    gates.append(dict(stage=stage,population=population,family=family,n=len(cohort),runs=cohort.run.nunique(),players=cohort.player.nunique(),clears=int(cohort.clear.sum()),losses=int((1-cohort.clear).sum()),measurement_verdict='descriptive' if len(cohort) else 'unavailable',predictive_verdict='insufficient evidence',reason=missing))
 gate=pd.DataFrame(gates);gate.to_csv(OUT/'family_gate_table.csv',index=False)
 # Apply numerical performance gates to the actually evaluated measured cohort.
 numeric=[]
 for (stage,model,family),g in unc.groupby(['stage','model','family']):
  ss=scores[(scores.stage==stage)&(scores.model==model)&(scores.family==family)]
  pass_numeric=set(g.split)=={'forward_time','player_holdout'} and bool(((g.relative_reduction>=.05)&(g.high<0)).all())
  numeric.append(dict(stage=stage,model=model,family=family,both_numerical_gates=pass_numeric,constant_training_predictions=int(ss.constant.sum()),interpretation='insufficient evidence' if int(ss.constant.sum()) or not pass_numeric else 'numeric signal only; scope/player/HP checks still required'))
 num=pd.DataFrame(numeric);num.to_csv(OUT/'numerical_gate_audit.csv',index=False)
 # Calibration / rates / coverage for all planned variants and subgroup audits.
 prediction_audit=[]
 for keys,g in p.groupby(['stage','split','model','family']):
  common=dict(zip(['stage','split','model','family'],keys))
  for dim in ['all','difficulty','player','hp_band']:
   frame=g.copy();frame['hp_band']=pd.cut(frame.hp/frame.maxhp,[0,.5,.75,1,10],labels=['<=50%','50-75%','75-100%','>100%'])
   groups=[('all',frame)] if dim=='all' else frame.groupby(dim,observed=True)
   for value,z in groups:
    hit=z[z.p>=.9];k=int(hit.clear.sum());lo,hi=__import__('act_targets').wilson(k,len(hit))
    prediction_audit.append(common|dict(dimension=dim,value=str(value),eligible=len(z),selected=len(hit),wins=k,players=hit.player.nunique(),distinct_runs=hit.run.nunique(),observed_rate=hit.clear.mean(),average_prediction=hit.p.mean(),low=lo,high=hi,coverage=len(hit)/len(z)))
 pd.DataFrame(prediction_audit).to_csv(OUT/'calibration_coverage_subgroups.csv',index=False)
 fig,axes=plt.subplots(2,2,figsize=(11,9))
 for ax,(family,metric) in zip(axes.ravel(),[('damage','damage_rate'),('setup','worst_enemy_cost'),('endurance','net_hp_per_fight'),('consistency','damage_sd')]):
  for outcome,color,label in [(1,'#247856','clear'),(0,'#ba5542','loss')]:
   z=d[(d.stage=='boss_entry')&(d.clear==outcome)];ax.scatter(z.hp/z.maxhp,z[metric],alpha=.6,label=label,color=color)
  ax.set(xlabel='Boss-entry HP / max HP',ylabel=SPECS[metric][2],title=family+' (prior fights)');ax.legend()
 fig.suptitle('Observed overlap; different bosses/characters remain confounders');fig.tight_layout();fig.savefig(OUT/'prior_measurement_overlap.png',dpi=150);plt.close(fig)
 # Input verification is independent of model outputs and required to finish.
 manifest=json.loads((current.OUT/'snapshot-manifest.json').read_text());bad=[name for name,sha in manifest.items() if hashlib.sha256((current.SOURCE/name).read_bytes()).hexdigest()!=sha]
 if bad:raise ValueError('Snapshot changed')
 verification=dict(snapshot_files=len(manifest),mismatches=len(bad),feature_families=list(FAMILIES),gate_cells=len(gate),diagnostic_matched_context_rows=len(contrasts),illustrative_counterexamples=len(counterexamples),source_hashes={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in ['bounded_readiness_goal.py','report_bounded_readiness.py']})
 (OUT/'verification.json').write_text(json.dumps(verification,indent=2));print(json.dumps(verification,indent=2));print(num.groupby('interpretation').size().to_string())
 report='''# Objective act-boss readiness: bounded snapshot investigation

## Decision

None of the four measured capability families has met the written predictive gates in the supported snapshot population. Use validated observations as descriptive metrics; keep readiness unknown where the claim is not supported. This is a completed negative/limited research result, not proof that combat capability is irrelevant. The broader HP/composition survival model is separate and must not be presented as an objective damage/block sufficiency target.

## What was tested

Damage/pace, setup/burst safety, defense/endurance and consistency, separately and combined, against matched health/context baselines. Fixed regularized logistic and shallow tree settings, training-only preprocessing, whole-player and forward-time windows. Checkpoints: after completed fights 3 and 6 and first-boss entry. A10 requires both bosses. No target fight result, target damage, future cards/final deck or future route enters earlier predictors. Boss identity is available only in the boss-entry baseline.

All measurements use copied, hashed six-character accepted solo standard data. Held/modded/multiplayer are excluded. A2+ healing is cumulative; current HP is survival state, inherited missing HP is not weak current-act performance. Abandonment bounds from the prior broad-candidate study are linked separately. The one abandoned telemetry run has one lost fight, no completed fights and no boss: it contributes no eligible measured checkpoint and therefore cannot change measured-window bounds. This is audited in log_eligibility.csv; it does not validate predictions before fight 3.

## Findings and limits

See scores.csv for every model, including worse variants; uncertainty.csv for paired fixed-prediction run-bootstrap differences; numerical_gate_audit.csv for exact gate tests. The family_gate_table.csv covers every family/checkpoint/difficulty cell, including missing A8/A9/A10 measurements. Small two-player cohorts and one-class player-holdout training prevent reliable capability generalization. A numeric change from a constant fallback is not a validated player-transfer gain. Tree leaves/settings are fixed even when small samples make them uninformative; no settings were loosened to chase a pass.

Boss distributions and comparisons use the same boss, act, difficulty group, character and entry-HP band, reporting quantiles and overlap. Sparse or absent clear/loss contrasts remain insufficient rather than being pooled across incompatible contexts. Counterexamples illustrate high damage/block or low early cost/variability that still lose; they do not attribute causes. Target-boss diagnostics are separated from predictive prior-fight observations. Fatal fights are censored by death; their observed cost is not the total hypothetical HP needed to win. Exact HP within a band, deck mechanics, player choices and route remain confounders.

Early/sustained turn profiles use enemy HP deltas only when the entire prior fight has matching attributed removal and no unexplained disappearance. No late turns means late output unknown, with a missingness flag, not a zero-capability claim. Setup measurements observe enemy damage taken and idle output; they do not measure unobserved net turn HP costs or prove a specific setup turn is lethal. Single-value block averages are demand-capped and do not establish maximal defense. These limitations are part of the instrumentation contract.

The predeclared families are exhausted for this investigation. No further model-family search, production polling or request for new gameplay is needed to finish. The verdicts are descriptive or insufficient, not a universal positive score. Historical reused outcomes do not become independent confirmation through cross-validation.

## Reproduction and review files

Run `bounded_readiness_goal.py`, then `report_bounded_readiness.py` with the repository Python and analysis-requirements.txt. `run_bounded_validation.py` executes the targeted regression suite. Input/coverage audits, feature dictionary, matched distributions, counterexamples, all predictions and model comparisons, numerical gates, 60-cell verdict grid and verification hashes are colocated with this report. The source instrumentation specification is docs/act-boss-readiness-instrumentation.md.

Prior broad-model evidence, abandonment bounds and equal-player analyses are linked below for context. They support limited survival associations and do not override the measured-family gate outcomes. Descriptive Wilson intervals ignore player clustering. Bootstrap intervals do not refit models or establish a new-player population from two observed players. All comparisons are exploratory and not multiplicity-adjusted.
'''
 (OUT/'report.md').write_text(report,encoding='utf-8');(OUT/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>Bounded boss-readiness investigation</title><style>body{font:16px/1.6 system-ui;max-width:1250px;margin:35px auto;padding:20px}pre{white-space:pre-wrap}table{border-collapse:collapse;font-size:12px}td,th{padding:6px;border:1px solid #ddd}img{max-width:100%}</style><pre>'+html.escape(report)+'</pre><h2>All planned model comparisons</h2>'+scores.to_html(index=False)+'<h2>Numerical gate audit</h2>'+num.to_html(index=False)+'<h2>Family-by-scope verdicts</h2>'+gate.to_html(index=False)+'<h2>Measurement overlap</h2><img src="prior_measurement_overlap.png"><p><a href="../abandonment/review.html">Abandonment bounds (prior candidate)</a> | <a href="../player_robustness/review.html">Equal-player analysis (prior candidate)</a></p>',encoding='utf-8')
if __name__=='__main__':main()
