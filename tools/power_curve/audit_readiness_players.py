"""Player-cluster uncertainty of fixed held-out confidence subsets.
Descriptive historical robustness, not population certainty from seven players.
"""
import html,json
from pathlib import Path
import numpy as np
import pandas as pd
import six_character_boss_study as current
OUT=current.OUT/'player_robustness'

def main():
 OUT.mkdir(exist_ok=True);sources=[('boss_entry',current.OUT/'interactions/predictions.csv'),('checkpoints',current.OUT/'checkpoint_interactions/predictions.csv')];rng=np.random.default_rng(42);out=[]
 for name,path in sources:
  p=pd.read_csv(path);p=p[(p.model=='tree_composition')&(p.split=='player_holdout')]
  if name=='checkpoints':p=p[p.endpoint=='clear']
  for stage,d in ([('boss_entry',p)] if name=='boss_entry' else [(f'fight{cp}',g) for cp,g in p.groupby('fight_index')]):
   for population,g in [('all',d),('A0-8',d[d.asc<=8]),('A9-10',d[d.asc>=9])]:
    h=g[g.p>=.9];players=h.groupby('player').clear.agg(['sum','count'])
    if players.empty:continue
    rates=players['sum'].to_numpy()/players['count'].to_numpy();ix=rng.integers(0,len(players),(10000,len(players)));equal=rates[ix].mean(axis=1);weighted=players['sum'].to_numpy()[ix].sum(axis=1)/players['count'].to_numpy()[ix].sum(axis=1)
    out.append(dict(stage=stage,population=population,eligible=len(g),selected=len(h),players=len(players),pooled_rate=h.clear.mean(),equal_player_rate=rates.mean(),player_bootstrap_equal_low=np.quantile(equal,.025),player_bootstrap_equal_high=np.quantile(equal,.975),player_bootstrap_pooled_low=np.quantile(weighted,.025),player_bootstrap_pooled_high=np.quantile(weighted,.975),minimum_player_rate=rates.min(),max_player_share=players['count'].max()/len(h)))
 r=pd.DataFrame(out)
 for col in ['player_bootstrap_equal_low','player_bootstrap_equal_high','player_bootstrap_pooled_low','player_bootstrap_pooled_high']:
  r.loc[r.players<3,col]=np.nan
 r.to_csv(OUT/'cluster_summary.csv',index=False);print(r.to_string(index=False))
 notes='''# Player-level robustness

Take fixed out-of-player predictions from the nonlinear experiments and the fixed >=90% subset. Report pooled success and equal weight per represented player's success rate. Bootstrap represented players 10,000 times, retaining each player's observed counts/outcomes. No model refitting occurs. With at most seven players, these are descriptive uncertainty estimates over the observed population, not calibrated prediction intervals for a genuinely new population. Missing/small player groups, repeated acts, related model fits and selection of the candidate after earlier exploratory work limit inference. Report minimum-player rate and concentration rather than relying only on the mean.

Population A0–8 excludes unsupported high-ascension claims; A9–10 is shown separately, not silently pooled with lower levels. These populations were chosen from known mechanical distinctions and previous evidence limits. This is a scope sensitivity, not a newly independent validation.
'''
 (OUT/'review.md').write_text(notes,encoding='utf-8');(OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Player-level robustness</title><style>body{font:16px/1.6 system-ui;margin:30px}pre{white-space:pre-wrap}td,th{padding:6px;border:1px solid #ddd}table{border-collapse:collapse;font-size:13px}</style><pre>'+html.escape(notes)+'</pre>'+r.to_html(index=False),encoding='utf-8')
if __name__=='__main__':main()
