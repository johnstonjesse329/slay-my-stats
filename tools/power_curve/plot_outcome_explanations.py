"""Reviewable turn profiles for the checked retrospective examples."""
import json,hashlib
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from explain_boss_outcomes import OUT

def main():
 examples=json.loads((OUT/'examples.json').read_text());turns=pd.read_csv(OUT/'turn_facts.csv');fig,axes=plt.subplots(len(examples),2,figsize=(12,3.3*len(examples)),squeeze=False)
 for i,e in enumerate(examples):
  d=turns[turns.fight==e['fight']].sort_values('turn');axes[i,0].bar(d.turn,d.enemy_hp_lost,color='#447b9b');axes[i,0].set(title=f"{e['character']} vs {e['boss']} (A{e['asc']}): {e['result']}",ylabel='Enemy HP removed',xlabel='Recorded turn')
  axes[i,1].bar(d.turn,d.damage_blocked,label='Blocked',color='#70a088');axes[i,1].bar(d.turn,d.damage_taken,bottom=d.damage_blocked,label='Received (incl. lethal excess)',color='#bd7666');axes[i,1].set(title='Observed incoming hit pressure',ylabel='Damage',xlabel='Recorded turn');axes[i,1].legend(fontsize=9)
 fig.suptitle('Actual fight profiles: different bosses, not directly comparable power scores');fig.tight_layout(rect=[0,0,1,.97]);fig.savefig(OUT/'turn_profiles.png',dpi=150);plt.close(fig)
 path=OUT/'review.html'
 text=path.read_text(encoding='utf-8');text=text.replace('<pre>','<h2>How these fights unfolded</h2><img style="max-width:100%" src="turn_profiles.png" alt="Recorded damage, block and received damage by turn"><pre>',1);path.write_text(text,encoding='utf-8')
 # Verify every displayed example reconciles and has no unexplained enemy loss.
 facts=pd.read_csv(OUT/'boss_facts.csv').set_index('fight')
 for e in examples:
  r=facts.loc[e['fight']];assert abs(r.starting_hp-r.enemy_damage_suffered-r.additional_hp_cost+r.healed-r.ending_hp)<1e-6;assert r.hp_balanced and r.damage_balanced and r.unexplained_enemy_loss==0
 (OUT/'example-verification.json').write_text(json.dumps(dict(checked_examples=len(examples),all_health_accounts_reconcile=True,unexplained_enemy_loss_in_examples=0,plot_sha256=hashlib.sha256((OUT/'turn_profiles.png').read_bytes()).hexdigest()),indent=2))
 print('Checked',len(examples),'examples; wrote turn profiles')
if __name__=='__main__':main()
