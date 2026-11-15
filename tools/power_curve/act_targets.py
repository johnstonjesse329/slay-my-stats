"""Select concrete act targets on older runs; evaluate unchanged on newer runs.

All thresholds are exploratory hypotheses. Outputs are local only.

"""

import collections, html, itertools, json, math, statistics

from pathlib import Path

import numpy as np

import pandas as pd

import matplotlib

matplotlib.use('Agg')

import matplotlib.pyplot as plt

import act_readiness as ar



OUT=ar.OUT



def wilson(k,n):

    if not n:return (0.,1.)

    z=1.96;p=k/n;den=1+z*z/n

    mid=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den

    return mid-half,mid+half



def stats(d):

    n=len(d);k=int(d.clear.sum()) if n else 0;lo,hi=wilson(k,n)

    return dict(n=n,wins=k,rate=k/n if n else None,low=lo,high=hi,players=d.player.nunique(),characters=d.char.nunique())



def matches(d,t,l,h):return d[(d.turns<=t)&(d.loss<=l)&(d.hp_fraction>=h)]



def select(d):

    choices=[]

    for t,l,h in itertools.product([2,3,4,5,6,99],[0,2,5,8,10,15],[0,.25,.5,.75]):

        s=stats(matches(d,t,l,h))

        if s['n']>=30 and s['players']>=3 and s['characters']>=3 and s['low']>=.8:

            choices.append((s['n'], -h, t, l, h, s))

    if not choices:return None

    best=max(choices,key=lambda c:c[:4]);return best[2:]



def build():

    rows,_,audit=ar.dataset()

    # One observation per run-act at each known checkpoint, never last-N selected

    # by future run length. Sixth-fight estimates condition on reaching six fights.

    data=[]

    for r in rows:

        if r['fight_index'] not in [3,6]:continue

        recent=r['history'][-3:]

        data.append({k:v for k,v in r.items() if k!='history'}|dict(turns=statistics.mean(f['turns'] for f in recent),loss=statistics.mean(f['loss'] for f in recent),hp_fraction=r['hp']/r['maxhp'],elite_count=sum('ELITE' in f['enc'] or f['kind']=='elite' for f in recent),encounters='|'.join(f['enc'] for f in recent)))

    d=pd.DataFrame(data)

    # Global run-time boundary is independent of outcomes and consistent across acts.

    times=sorted({r['ts'] for r in rows});boundary=times[int(len(times)*.8)]

    d['period']=np.where(d.ts<boundary,'older','later')

    raw=ar.g.load();outcomes={}

    for (sid,ts),r in raw.items():

        rid=ar.pseudonym(f'{sid}:{ts}')

        for ai,points in enumerate(r.get('map_point_history',[])):

            bosses=[p for p in points if p.get('map_point_type')=='boss']

            hp=None

            if bosses:

                s=bosses[0]['player_stats'][0];hp=s.get('current_hp',0)+s.get('damage_taken',0)-s.get('hp_healed',0)

            outcomes[(rid,ai+1)]=dict(reached_boss=bool(bosses),boss_entry_hp=hp,death_encounter=r.get('killed_by_encounter') or r.get('killed_by_event') or 'unknown',bosses_seen=len(bosses))

    for key in ['reached_boss','boss_entry_hp','death_encounter','bosses_seen']:d[key]=[outcomes.get((r.run,r.act),{}).get(key) for r in d.itertuples()]

    return d,audit,boundary



def main():

    d,audit,boundary=build();selected=[];fixed=[];failures=[];loo=[]

    for (checkpoint,tier,act),group in d.groupby(['fight_index','tier','act']):

        train=group[group.period=='older'];test=group[group.period=='later']

        common=dict(checkpoint=checkpoint,tier=tier,act=act)

        rule=select(train)

        if rule:

            t,l,h,s=rule;hit=matches(test,t,l,h)

            selected.append(common|dict(max_turns=t,max_loss=l,min_hp_fraction=h,train_n=s['n'],train_rate=s['rate'],train_low=s['low'],test_baseline=stats(test)['rate'])|{f'test_{k}':v for k,v in stats(hit).items()})

            for r in hit[hit.clear==0].to_dict('records'):failures.append(r|dict(rule=f'turns <= {t}, loss <= {l}, HP >= {h:.0%}'))

        else:selected.append(common|dict(status='No training rule met evidence requirement',train_total=len(train),test_total=len(test)))

        # Prespecified complementary styles, no optimization on test outcomes.

        for name,t,l in [('fast_low_cost',3,5),('moderate_low_cost',5,5),('any_speed_low_cost',99,5),('fast_spending_hp',3,15)]:

            for period,part in group.groupby('period'):

                hit=matches(part,t,l,0)

                fixed.append(common|dict(rule=name,period=period,max_turns=t,max_loss=l)|stats(hit))

        # Leave one player out: learn a rule on other players, then test it.

        for player in sorted(group.player.unique()):

            tr=group[group.player!=player];te=group[group.player==player];rule=select(tr)

            if rule:

                t,l,h,s=rule

                loo.append(common|dict(player=player,max_turns=t,max_loss=l,min_hp_fraction=h,baseline=stats(te)['rate'])|stats(matches(te,t,l,h)))

            else:loo.append(common|dict(player=player,n=0,status='No eligible training rule'))

    sel=pd.DataFrame(selected);fix=pd.DataFrame(fixed);lo=pd.DataFrame(loo)

    sel.to_csv(OUT/'candidate_targets.csv',index=False);fix.to_csv(OUT/'fixed_target_rates.csv',index=False);lo.to_csv(OUT/'target_player_holdout.csv',index=False)

    pd.DataFrame(failures).to_csv(OUT/'target_failures.csv',index=False);d.to_csv(OUT/'target_checkpoints.csv',index=False)

    # Stratification audits of selected rules on later runs, using only checkpoint state.

    strata=[]

    for rule in selected:

        if 'max_turns' not in rule:continue

        group=d[(d.period=='later')&(d.fight_index==rule['checkpoint'])&(d.tier==rule['tier'])&(d.act==rule['act'])]

        group=group.copy();group['meets']=((group.turns<=rule['max_turns'])&(group.loss<=rule['max_loss'])&(group.hp_fraction>=rule['min_hp_fraction']))

        group['hp_band']=pd.cut(group.hp_fraction,[-1,.5,.75,2],labels=['<=50%','50-75%','>75%'])

        for dimension in ['hp_band','char','player','elite_count']:

            for (value,meets),part in group.groupby([dimension,'meets'],observed=True):strata.append(dict(checkpoint=rule['checkpoint'],tier=rule['tier'],act=rule['act'],dimension=dimension,value=str(value),meets=meets)|stats(part))

    pd.DataFrame(strata).to_csv(OUT/'target_strata.csv',index=False)

    # Absolute turns/loss grid, fixed bands, all data for descriptive visualization only.

    fig,axes=plt.subplots(3,4,figsize=(15,10))

    for i,act in enumerate([1,2,3]):

        for j,tier in enumerate(['A0-7','A8','A9','A10']):

            ax=axes[i,j];part=d[(d.fight_index==3)&(d.act==act)&(d.tier==tier)].copy()

            part['speed']=pd.cut(part.turns,[0,3,5,np.inf],labels=['<=3','3-5','>5'])

            part['cost']=pd.cut(part.loss,[-1,5,10,np.inf],labels=['<=5','5-10','>10'])

            table=part.pivot_table(index='cost',columns='speed',values='clear',aggfunc='mean',observed=False).reindex(index=['<=5','5-10','>10'],columns=['<=3','3-5','>5'])

            counts=part.pivot_table(index='cost',columns='speed',values='clear',aggfunc='size',observed=False).reindex(index=['<=5','5-10','>10'],columns=['<=3','3-5','>5']).fillna(0)

            cmap=plt.get_cmap('RdYlGn').copy();cmap.set_bad('#e5e5e5')

            ax.imshow(np.ma.masked_where(counts.to_numpy()<10,table.to_numpy()),vmin=0,vmax=1,cmap=cmap)

            for y in range(3):

                for x in range(3):

                    n=int(counts.iloc[y,x]);v=table.iloc[y,x]

                    ax.text(x,y,f'{v:.0%}\nn={n}' if n else 'no data',ha='center',va='center',fontsize=9)

            ax.set(title=f'{tier}, Act {act}',xticks=range(3),xticklabels=['<=3','3-5','>5'],yticks=range(3),yticklabels=['<=5','5-10','>10'],xlabel='Mean fight turns',ylabel='Net HP lost / fight')

    fig.suptitle('Act clear after first 3 fights â€” descriptive; gray cells have fewer than 10 runs; not validation',fontsize=14);fig.tight_layout(rect=[0,0,1,.96]);fig.savefig(OUT/'target_grid.png',dpi=150);plt.close(fig)

    intro='''# Concrete act-target investigation



Solo, published core-character standard runs only. Held uploads and multiplayer excluded.



## Method



Each observation uses the last three completed fights at fight 3 or fight 6 of an act. These are fixed checkpoints, not a retrospectively chosen final window. Outcome is clearing the act through its final boss (both Act 3 bosses at A10).



Rules combine maximum average turns, maximum net HP lost per fight, and minimum current HP fraction. The search uses older 80% of run timestamps only. A candidate needs at least 30 training observations, three players, three characters, and a 95% Wilson lower bound of at least 80% act-clear rate. Among qualifying rules, choose greatest coverage. These are exploratory evidence requirements, not user-approved product cutoffs. Report later 20% outcomes without changing the rule. Leave-one-player-out evaluates the selection procedure separately; it does not validate the exact same fixed rule. Training confidence bounds are optimistic after searching many candidates; the later-run results are the relevant check. Later-run data was already examined in the preceding model experiment, so truly fresh future runs are still needed for final confirmation.



Net HP loss includes healing; it is not block output. Mean turns is an absolute observed kill-speed measure. It does not adjust for encounter composition; elite, HP, character and player strata audit that limitation. Game-data damage estimates are deliberately not used to choose these targets. These rules describe demonstrated performance, not guaranteed future deck capability. Only seven players contribute, and repeated acts within a run are correlated. Wilson intervals within each act/checkpoint do not account for player clustering. A0â€“7 still combines ascensions; A8, A9 and A10 stay distinct. No Dread calibration.



## Candidates selected on older runs, evaluated on later runs

'''

    text=intro+'\n'+sel.to_csv(index=False)+'\n## Failure audit\n\n'+f'{len(failures)} failed checkpoint observations met selected targets on later runs. See target_failures.csv for boss arrival, boss-entry HP, death encounter, character and checkpoint state. A failure may appear at both checkpoints; these are not distinct runs.\n'

    text+='\n## Review files\n\n- fixed_target_rates.csv: fixed speed/cost combinations by act, tier and time split.\n- target_player_holdout.csv: cross-player stability of rule selection.\n- target_strata.csv: HP, character, player and elite-exposure checks.\n- target_checkpoints.csv: pseudonymous local observations.\n\n![Descriptive target grid](target_grid.png)\n'

    (OUT/'targets.md').write_text(text,encoding='utf-8')

    (OUT/'targets.html').write_text('<!doctype html><meta charset="utf-8"><title>Concrete solo act targets</title><style>body{font:16px/1.6 system-ui;margin:30px;padding:0 20px}table{border-collapse:collapse;font-size:13px}td,th{padding:6px;border:1px solid #ddd}pre{white-space:pre-wrap}img{max-width:100%}</style><h1>Concrete solo act targets</h1><pre>'+html.escape(intro)+'</pre>'+sel.to_html(index=False,float_format=lambda x:f'{x:.3f}')+'<img src="target_grid.png"><pre>'+html.escape(text[text.index('## Failure audit'):])+'</pre>',encoding='utf-8')

    print(sel.to_string(index=False));print('Failed checkpoint observations:',len(failures));print('Written',OUT/'targets.html')

if __name__=='__main__':main()

