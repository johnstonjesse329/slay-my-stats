"""Warm-history experiment: player identity excluded; only completed prior runs.
Forward tests are retrospective by game time, not by upload availability.
"""
import collections,html,json,math
import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,roc_auc_score,log_loss
import boss_readiness as b
from act_targets import wilson

OUT=b.OUT/'history'

def history_features(current,events):
    # Conservative availability: require end of prior run before current run starts.
    prior=[r for r in events if r['player']==current['player'] and r['run']!=current['run'] and r['end']<current['ts']]
    recent=sorted(prior,key=lambda r:r['ts'])[-30:]
    same=[r for r in prior if r['act']==current['act'] and r['tier']==current['tier']][-20:]
    def smooth(xs):return (sum(x['clear'] for x in xs)+8)/(len(xs)+10)
    return dict(history_n=min(len(prior),100),history_recent_rate=smooth(recent),history_matched_n=len(same),history_matched_rate=smooth(same))

def fit(train,test,history,with_history):
    fights={}
    for r in train:
        for i,f in enumerate(r['history']):fights[(r['run'],r['act'],i)]=f
    ref=b.ar.reference(list(fights.values()),{r['run'] for r in train})
    def features(r):
        x=b.feats(r,ref,'performance')
        if with_history:x.update(history[r['run'],r['act']])
        return x
    clf=make_pipeline(DictVectorizer(),StandardScaler(with_mean=False),LogisticRegression(C=.1,max_iter=2000))
    clf.fit([features(r) for r in train],[r['clear'] for r in train])
    return clf.predict_proba([features(r) for r in test])[:,1]

def main():
    OUT.mkdir(exist_ok=True);rows,_=b.dataset();rows=sorted([r for r in rows if r['task']=='boss_sequence'],key=lambda r:r['ts'])
    raw=b.ar.g.load();ends={b.ar.pseudonym(f'{sid}:{ts}'):ts+max(0,r.get('run_time') or 0) for (sid,ts),r in raw.items()}
    events=[{k:r[k] for k in ['run','player','ts','act','tier','clear']}|dict(end=ends[r['run']]) for r in rows]
    history={(r['run'],r['act']):history_features(r,events) for r in rows}
    times=sorted({r['ts'] for r in rows});outputs=[]
    for fold,(lo,hi) in enumerate([(.4,.6),(.6,.8),(.8,1.)]):
        start=times[int(len(times)*lo)];end=times[int(len(times)*hi)] if hi<1 else max(times)+1
        # Do not train on runs still underway at time-test entry.
        train=[r for r in rows if ends[r['run']]<start];test=[r for r in rows if start<=r['ts']<end]
        for model,enabled in [('performance',False),('prior_history',True)]:
            probs=fit(train,test,history,enabled)
            for r,p in zip(test,probs):outputs.append({k:r[k] for k in ['run','player','ts','act','tier','boss','hp','maxhp','clear']}|history[r['run'],r['act']]|dict(fold=fold,model=model,p=float(p)))
        print('forward window',fold,'done',flush=True)
    pred=pd.DataFrame(outputs);pred.to_csv(OUT/'predictions.csv',index=False)
    metrics=[];confidence=[]
    for model,d in pred.groupby('model'):
        metrics.append(dict(model=model,n=len(d),brier=brier_score_loss(d.clear,d.p),auc=roc_auc_score(d.clear,d.p),logloss=log_loss(d.clear,d.p)))
        for dim in ['all','player','tier','fold']:
            groups=[('all',d)] if dim=='all' else d.groupby(dim)
            for value,g in groups:
                for threshold in [.8,.9,.95]:
                    hit=g[g.p>=threshold];k=int(hit.clear.sum());low,high=wilson(k,len(hit))
                    confidence.append(dict(model=model,dimension=dim,value=value,threshold=threshold,n=len(hit),wins=k,rate=hit.clear.mean(),mean_prediction=hit.p.mean(),low=low,high=high))
    metrics=pd.DataFrame(metrics);conf=pd.DataFrame(confidence);metrics.to_csv(OUT/'metrics.csv',index=False);conf.to_csv(OUT/'confidence.csv',index=False)
    print(metrics.to_string(index=False));print(conf[(conf.dimension=='all')].to_string(index=False))
    # Paired uncertainty, whole-run resampling of fixed out-of-time predictions.
    q=pred.pivot(index=['run','act','clear'],columns='model',values='p').reset_index();q['delta']=(q.prior_history-q.clear)**2-(q.performance-q.clear)**2
    g=q.groupby('run').delta.agg(['sum','count']);rng=np.random.default_rng(20261114);ix=rng.integers(0,len(g),(2000,len(g)))
    bs=g['sum'].to_numpy()[ix].sum(axis=1)/g['count'].to_numpy()[ix].sum(axis=1)
    uncertainty=dict(delta=q.delta.mean(),low=float(np.quantile(bs,.025)),high=float(np.quantile(bs,.975)))
    (OUT/'paired_uncertainty.json').write_text(json.dumps(uncertainty,indent=2));print(uncertainty)
    # Failure comparison includes boss base rate: common bosses aren't necessarily riskier.
    failures=[]
    for (model,boss,tier),d in pred.groupby(['model','boss','tier']):
        hit=d[d.p>=.9]
        if len(hit):failures.append(dict(model=model,boss=boss,tier=tier,eligible=len(d),base_rate=d.clear.mean(),selected=len(hit),failures=int((1-hit.clear).sum()),selected_rate=hit.clear.mean(),mean_prediction=hit.p.mean()))
    pd.DataFrame(failures).to_csv(OUT/'boss_failure_audit.csv',index=False)
    notes='''# Prior-player-history experiment

Solo, accepted, standard core-character runs only. Predict the full act boss sequence at entry to its first boss, including both bosses at A10. Three forward-time windows. The comparison is recent-performance model versus the same model plus prior player outcomes. No player identifier is a feature.

History uses only other runs whose start time plus recorded play duration precedes the current run start. No earlier act from the same run is used. Features are number of earlier boss entries, smoothed recent-30 clearance rate, and smoothed same-act/same-tier history (up to 20). Smoothing prior is 8 wins / 10 entries, fixed before evaluation. Training excludes runs unfinished at the start of the test window. References fit on training runs only.

Important: recorded duration omits time spent paused; it does not prove wall-clock completion or upload availability. Historical upload availability is not reconstructed. These are retrospective experiments in game-time order, not a live prospective trial. The prior experiment also split by start time; its historical confidence claim has this limitation. Rates are evidence for hypotheses, not deployable calibrated guarantees.

Prior history can confound player decisions with deck capability. Even if it improves outcome prediction, it must not silently change an objective deck-strength rating. Model coefficients and results are exploratory; seven uploaders cannot establish population generalization. Repeated acts are correlated. The bootstrap resamples runs from fixed predictions; it does not refit the model or account for player-population uncertainty. Wilson intervals in confidence.csv do not account for that clustering.

## Results
'''
    text=notes+'\n'+metrics.to_csv(index=False)+'\nPaired error difference (negative favors history): '+json.dumps(uncertainty)+'\n\n'+conf[conf.dimension=='all'].to_csv(index=False)
    (OUT/'review.md').write_text(text,encoding='utf-8')
    (OUT/'review.html').write_text('<!doctype html><meta charset="utf-8"><title>Boss readiness: prior history</title><style>body{font:16px/1.6 system-ui;max-width:1200px;margin:30px auto;padding:20px}pre{white-space:pre-wrap}table{border-collapse:collapse}td,th{padding:6px;border:1px solid #ddd}</style><pre>'+html.escape(notes)+'</pre>'+metrics.to_html(index=False)+'<h2>High-confidence subsets</h2>'+conf[conf.dimension=='all'].to_html(index=False)+'<h2>By player at 90%</h2>'+conf[(conf.dimension=='player')&(conf.threshold==.9)].to_html(index=False)+'<pre>'+html.escape(str(uncertainty))+'</pre>',encoding='utf-8')
if __name__=='__main__':main()
