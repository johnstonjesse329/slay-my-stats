"""Check added performance information within observed HP and difficulty strata."""
import numpy as np
import pandas as pd
import boss_readiness as b

def main():
 pred=pd.read_csv(b.OUT/'predictions.csv');pred=pred[(pred.task=='boss_sequence')&(pred.split=='forward_time')]
 q=pred.pivot(index=['run','act','tier','boss','clear','hp','maxhp'],columns='model',values='p').reset_index()
 q['hp_band']=pd.cut(q.hp/q.maxhp,[0,.5,.75,1,10],labels=['<=50%','50-75%','75-100%','>100%'])
 q['delta']=(q.performance-q.clear)**2-(q.health-q.clear)**2
 rows=[];rng=np.random.default_rng(42)
 for dim in ['hp_band','tier','act','boss']:
  for value,g in q.groupby(dim,observed=True):
   groups=g.groupby('run').delta.agg(['sum','count']);ix=rng.integers(0,len(groups),(2000,len(groups)))
   bs=groups['sum'].to_numpy()[ix].sum(axis=1)/groups['count'].to_numpy()[ix].sum(axis=1)
   rows.append(dict(dimension=dim,value=value,n=len(g),brier_health=np.mean((g.health-g.clear)**2),brier_performance=np.mean((g.performance-g.clear)**2),delta=g.delta.mean(),low=np.quantile(bs,.025),high=np.quantile(bs,.975)))
 out=pd.DataFrame(rows);out.to_csv(b.OUT/'performance_strata.csv',index=False);print(out[out.dimension!='boss'].to_string(index=False))
if __name__=='__main__':main()
