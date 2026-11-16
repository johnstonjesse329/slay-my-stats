"""Boss-entry prospective experiment; no target-fight results enter predictors.
Uses the frozen solo production snapshot; outputs local_data/act_validation/boss/.
"""
import collections,json,math,statistics
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.metrics import brier_score_loss,roc_auc_score,log_loss
import act_readiness as ar
from act_targets import wilson
OUT=ar.OUT/'boss'

def extract_run(raw,rid,player):
    out=[];audit=collections.Counter();asc=raw.get('ascension') or 0
    for ai,points in enumerate(raw.get('map_point_history',[])):
        boss_points=[p for p in points if p.get('map_point_type')=='boss']
        required=2 if ai==2 and asc>=10 else 1
        sequence_clear=(len(boss_points)>=required and all(p['player_stats'][0].get('current_hp',0)>0 for p in boss_points)) or bool(raw.get('win')) or any(raw['map_point_history'][ai+1:])
        history=[];previous=None;ordinal=0;rests=smiths=0
        for point in points:
            s=point.get('player_stats',[{}])[0]
            rooms=[q for q in point.get('rooms',[]) if q.get('turns_taken') and q.get('monster_ids')]
            if point.get('map_point_type')=='rest_site':
                rests+=1
            if point.get('map_point_type')=='boss':
                ordinal+=1
                if previous is None or len(history)<3 or len(rooms)!=1:
                    audit['excluded_boss_without_prior_state_or_three_fights']+=1
                else:
                    hp=previous['current_hp'];mx=previous.get('max_hp',0)
                    if hp<=0 or mx<=0:audit['invalid_prior_hp']+=1;continue
                    reconstructed=s.get('current_hp',0)+s.get('damage_taken',0)-s.get('hp_healed',0)
                    audit['entry_hp_disagreement']+=int(reconstructed!=hp)
                    r=dict(run=rid,player=player,ts=raw['start_time'],act=ai+1,tier=ar.tier(asc),asc=asc,char=raw['players'][0]['character'],build=raw.get('build_id','unknown'),fight_index=len(history),hp=hp,maxhp=mx,history=list(history),boss=rooms[0]['model_id'],ordinal=ordinal,rests=rests)
                    out.append(r|dict(task='next_boss',clear=int(s.get('current_hp',0)>0)))
                    if ordinal==1:out.append(r|dict(task='boss_sequence',clear=int(sequence_clear)))
            if len(rooms)==1 and s.get('current_hp',0)>0:
                q=rooms[0]
                history.append(dict(run=rid,act=ai+1,tier=ar.tier(asc),kind=point.get('map_point_type','unknown'),enc=q['model_id'],turns=q['turns_taken'],loss=max(0,s.get('damage_taken',0)-s.get('hp_healed',0)),pool=None))
            if 'current_hp' in s:previous=dict(s)
    return out,audit

def dataset():
    prior,_,_=ar.dataset();eligible={r['run'] for r in prior};out=[];audit=collections.Counter()
    for (sid,ts),raw in ar.g.load().items():
        rid=ar.pseudonym(f'{sid}:{ts}')
        if rid not in eligible:continue
        rows,a=extract_run(raw,rid,ar.pseudonym(sid));out.extend(rows);audit.update(a)
    return out,dict(audit)

def feats(r,ref,model):
    x=dict(act_tier=f"{r['act']}/{r['tier']}",boss=r['boss'],ordinal=r['ordinal'],character=r['char'],asc=r['asc'],build=r['build'])
    if model=='context':return x
    x.update(hp=r['hp'],maxhp=r['maxhp'],hp_fraction=r['hp']/r['maxhp'])
    if model=='health':return x
    perf=ar.features(r,ref,'trend')
    x.update({k:v for k,v in perf.items() if k not in ['act_tier','character','asc','build','hp','maxhp','hp_fraction']})
    x['prior_elites']=sum(f['kind']=='elite' or 'ELITE' in f['enc'] for f in r['history']);x['rest_visits']=r['rests']
    return x

def fit_predict(train,test,model):
    fights={}
    for r in train:
        for i,f in enumerate(r['history']):fights[(r['run'],r['act'],i)]=f
    ref=ar.reference(list(fights.values()),{r['run'] for r in train})
    clf=make_pipeline(DictVectorizer(),StandardScaler(with_mean=False),LogisticRegression(C=.1,max_iter=2000))
    counts=collections.Counter(r['player'] for r in train)
    w=np.array([len(train)/len(counts)/counts[r['player']] for r in train]) if model=='balanced' else np.ones(len(train))
    clf.fit([feats(r,ref,model) for r in train],[r['clear'] for r in train],logisticregression__sample_weight=w)
    return clf.predict_proba([feats(r,ref,model) for r in test])[:,1]

def evaluate(rows):
    out=[]
    for task in ['next_boss','boss_sequence']:
        data=[r for r in rows if r['task']==task];idx=np.arange(len(data));groups=np.array([r['run'] for r in data]);y=np.array([r['clear'] for r in data])
        splits={'run_holdout':list(GroupKFold(5).split(idx,y,groups))}
        splits['player_holdout']=[(np.array([i for i,r in enumerate(data) if r['player']!=p]),np.array([i for i,r in enumerate(data) if r['player']==p])) for p in sorted({r['player'] for r in data})]
        times=sorted({r['ts'] for r in data});ts=np.array([r['ts'] for r in data]);splits['forward_time']=[]
        for lo,hi in [(.4,.6),(.6,.8),(.8,1.)]:
            start=times[int(len(times)*lo)];end=times[int(len(times)*hi)] if hi<1 else max(times)+1
            splits['forward_time'].append((idx[ts<start],idx[(ts>=start)&(ts<end)]))
        for split,folds in splits.items():
            for fold,(tr,te) in enumerate(folds):
                train=[data[i] for i in tr];test=[data[i] for i in te]
                assert not {r['run'] for r in train}&{r['run'] for r in test}
                if split=='forward_time':assert max(r['ts'] for r in train)<min(r['ts'] for r in test)
                for model in ['context','health','performance','balanced']:
                    probs=fit_predict(train,test,model)
                    for r,p in zip(test,probs):out.append({k:r[k] for k in ['run','player','act','tier','boss','ordinal','clear','hp','maxhp']}|dict(task=task,split=split,fold=fold,model=model,p=float(p)))
            print(task,split,'done',flush=True)
    return pd.DataFrame(out)

def summarize(pred):
    metrics=[];confidence=[];subgroups=[]
    for keys,d in pred.groupby(['task','split','model']):
        common=dict(zip(['task','split','model'],keys))
        metrics.append(common|dict(n=len(d),brier=brier_score_loss(d.clear,d.p),auc=roc_auc_score(d.clear,d.p),logloss=log_loss(d.clear,d.p)))
        for threshold in [.8,.9,.95]:
            hit=d[d.p>=threshold];k=int(hit.clear.sum());lo,hi=wilson(k,len(hit))
            confidence.append(common|dict(threshold=threshold,n=len(hit),wins=k,rate=k/len(hit) if len(hit) else None,low=lo,high=hi,players=hit.player.nunique(),mean_prediction=hit.p.mean()))
        if keys[2] in ['performance','balanced']:
            for dims in [['tier','act'],['player'],['boss'],['fold']]:
                for values,g in d.groupby(dims):
                    vals=values if isinstance(values,tuple) else (values,)
                    hit=g[g.p>=.9];k=int(hit.clear.sum());lo,hi=wilson(k,len(hit))
                    subgroups.append(common|dict(dimension='/'.join(dims),value='/'.join(map(str,vals)),n=len(g),base=g.clear.mean(),selected=len(hit),wins=k,selected_rate=hit.clear.mean(),low=lo,high=hi))
    return pd.DataFrame(metrics),pd.DataFrame(confidence),pd.DataFrame(subgroups)

def main():
    OUT.mkdir(exist_ok=True);rows,audit=dataset();(OUT/'audit.json').write_text(json.dumps(audit,indent=2))
    pd.DataFrame([{k:v for k,v in r.items() if k!='history'} for r in rows]).to_csv(OUT/'observations.csv',index=False)
    print('observations',collections.Counter(r['task'] for r in rows),audit,flush=True)
    p=evaluate(rows);p.to_csv(OUT/'predictions.csv',index=False)
    m,c,s=summarize(p);m.to_csv(OUT/'metrics.csv',index=False);c.to_csv(OUT/'confidence.csv',index=False);s.to_csv(OUT/'subgroups.csv',index=False)
    print(m.to_string(index=False));print(c[(c.model=='performance')&(c.threshold==.9)].to_string(index=False))
if __name__=='__main__':main()
