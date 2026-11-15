"""Render boss experiment evidence, including failed generalization checks."""
import html,json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import boss_readiness as b
from act_targets import wilson
OUT=b.OUT
p=pd.concat([pd.read_csv(OUT/'predictions.csv'),pd.read_csv(OUT/'calibrated_predictions.csv')],ignore_index=True)
m,c,s=b.summarize(p);m.to_csv(OUT/'all_metrics.csv',index=False);c.to_csv(OUT/'all_confidence.csv',index=False)
# Paired differences: same boss sequence, whole-run bootstrap, fixed fitted models.
rng=np.random.default_rng(20261114);unc=[]
for split in ['player_holdout','forward_time']:
 d=p[(p.task=='boss_sequence')&(p.split==split)]
 q=d.pivot(index=['run','act','clear'],columns='model',values='p').reset_index()
 for model,base in [('performance','health'),('calibrated','health'),('balanced','performance')]:
  q['delta']=(q[model]-q.clear)**2-(q[base]-q.clear)**2
  g=q.groupby('run').delta.agg(['sum','count']);ix=rng.integers(0,len(g),(2000,len(g)))
  vals=g['sum'].to_numpy()[ix].sum(axis=1)/g['count'].to_numpy()[ix].sum(axis=1)
  unc.append(dict(split=split,comparison=f'{model} minus {base}',delta=q.delta.mean(),low=np.quantile(vals,.025),high=np.quantile(vals,.975)))
pd.DataFrame(unc).to_csv(OUT/'paired_uncertainty.csv',index=False)
# Calibration and subgroup counts expose a pooled result's limitations.
fig,axes=plt.subplots(1,2,figsize=(12,5))
for ax,split in zip(axes,['forward_time','player_holdout']):
 for model in ['health','performance','calibrated']:
  d=p[(p.task=='boss_sequence')&(p.split==split)&(p.model==model)].copy();d['bin']=pd.cut(d.p,[0,.5,.7,.8,.9,.95,1],include_lowest=True)
  g=d.groupby('bin',observed=True).agg(pred=('p','mean'),observed=('clear','mean'),n=('clear','size'))
  ax.plot(g.pred,g.observed,'o-',label=model)
 ax.plot([0,1],[0,1],'k--',alpha=.5);ax.set(xlabel='Predicted probability',ylabel='Observed sequence-clear rate',title=split);ax.legend();ax.set_xlim(.3,1);ax.set_ylim(.3,1)
fig.tight_layout();fig.savefig(OUT/'calibration.png',dpi=160);plt.close(fig)
strata=[]
for split in ['forward_time','player_holdout']:
 d=p[(p.task=='boss_sequence')&(p.split==split)&(p.model=='calibrated')]
 for dims in [['tier','act'],['player'],['fold']]:
  for values,g in d.groupby(dims):
   h=g[g.p>=.9];k=int(h.clear.sum());lo,hi=wilson(k,len(h))
   strata.append(dict(split=split,dimension='/'.join(dims),value=str(values),eligible=len(g),selected=len(h),wins=k,rate=h.clear.mean(),low=lo,high=hi))
strata=pd.DataFrame(strata);strata.to_csv(OUT/'calibrated_subgroups.csv',index=False)
notes='''# Boss-entry validation

This experiment predicts boss outcomes directly using only information recorded before the target boss. It is conditional on reaching the boss and having at least three earlier fights in that act. It does not predict from act entry or establish an intrinsic deck-power scale.

## Findings

The calibrated model identified 528 forward-time boss entries with predicted sequence-clear probability >=90%; 493 cleared (93.4%). It selected about 31% of 1,685 evaluated entries. The three successive time windows cleared 90/97, 227/247 and 176/184. This is useful evidence of a high-success subset within the existing population.

However, when a whole player is unseen, the same calibrated threshold selected 279 entries and only 236 cleared (84.6%). This falsifies a general claim that the output is a reliable 90% estimate for a new player. Equal weighting of players worsened average prediction error. Neither adjustment resolves player transfer.

The forward-time high-confidence group is dominated by A0–7 and one prolific player. A9 has only 13 selected entries and A10's final act only three, with two wins. No high-ascension or Dread reliability claim follows from the pooled rate. See calibrated_subgroups.csv for all counts, including failures and small strata.

## Experiment design

Two endpoints: next boss survived; whole act boss sequence cleared from entry to its first boss. A10 Act 3 includes both bosses for the latter. The second boss identity and first boss outcome are not supplied to that sequence prediction. At the second boss, the already-completed first boss is legitimately available to the next-boss prediction.

Features: boss identity (assumed known on the map), act/difficulty, exact ascension, character, build; then pre-boss HP/max HP; then earlier fight duration, net HP loss, variability, encounter-normalized performance, trend, elites and rests. No final deck, target-boss damage, turns, ending HP, or future rooms enter predictors. HP comes from the preceding recorded room. In 24 encounters it differed from HP reconstructed from target-boss outcome statistics; reconstructed HP is audit-only.

Solo published standard core-character runs only; held/unpublished uploads, multiplayer, other modes and abandoned runs excluded. Frozen production snapshot in the parent folder; inherited eligibility requires at least one three-fight checkpoint. 2,747 first-boss sequences and 2,809 individual boss observations. Four regression tests cover target-outcome leakage and A10 sequencing.

All preprocessing references are trained on training runs only. Whole-run and whole-player splits keep related observations together. Forward-time evaluation trains on the earliest 40%, then 60%, then 80% of run timestamps, testing on the next 20% each time. Nested probability calibration uses inner player-group holdouts for the player test and inner forward-time windows for the time test. No outer-test labels fit the model or calibration. The underlying snapshot has been explored before: these are exploratory historical tests, not an untouched prospective trial. Player identity is never a model feature.

Logistic regression is regularized with a fixed C=.1. Calibration fits a scalar logistic correction with C=1. High-confidence thresholds (.8/.9/.95) were stated before evaluating their outcomes. Balanced training gives each training player equal total weight. Report all variants rather than just the best one.

Wilson intervals are descriptive and do not account for correlation across a player's runs. Paired error intervals resample whole runs from fixed held-out predictions and do not include model-refitting or population-of-players uncertainty. Seven players are too few to establish broad player generalization. Current build IDs adjust for some patch changes but are not a mechanistic enemy model.

## What remains

1. Test player-history adjustment using only earlier runs, with a cold-start fallback and explicit amount-of-history requirements.
2. Determine whether performance adds information within HP/boss/difficulty strata rather than merely shifting the population selected.
3. Audit high-confidence failures by boss mechanics and pre-entry state; investigate telemetry where available.
4. Separate a calibrated outcome estimate from interpretable mechanical damage/defense targets. Both still need a future-run prospective check before production adoption.

No live ratings or deployments changed. The goal remains active because reliable transfer and high-ascension evidence are incomplete.
'''
(OUT/'review.md').write_text(notes,encoding='utf-8')
metrics=m[m.task=='boss_sequence'];confidence=c[(c.task=='boss_sequence')&(c.threshold==.9)]
(OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Boss clearance evidence</title><style>body{font:16px/1.6 system-ui;max-width:1200px;margin:35px auto;padding:0 20px}pre{white-space:pre-wrap}table{border-collapse:collapse;font-size:14px}td,th{padding:6px;border:1px solid #ddd}img{max-width:100%}</style><pre>'+html.escape(notes)+'</pre><h2>Model error</h2>'+metrics.to_html(index=False,float_format=lambda x:f'{x:.4f}')+'<h2>Predicted probability at least 90%</h2>'+confidence.to_html(index=False,float_format=lambda x:f'{x:.3f}')+'<img src="calibration.png" alt="Calibration on later runs and unseen players">',encoding='utf-8')
print(pd.DataFrame(unc).to_string(index=False))
