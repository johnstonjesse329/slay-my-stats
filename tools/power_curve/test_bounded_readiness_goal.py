import unittest
from bounded_readiness_goal import metrics,valid,feature,FAMILIES
class BoundedGoalTests(unittest.TestCase):
 def fight(self):
  return dict(hp0=50,hp1=48,hp_in=2,hp_out=0,enemy_unexplained=0,enemy_lost=30,dealt_removed=30,blocked=8,turns=[dict(enemy_lost=10,taken=2),dict(enemy_lost=20,taken=0)])
 def test_unexplained_or_disagreeing_damage_is_rejected(self):
  f=self.fight();f['enemy_unexplained']=1
  with self.assertRaises(ValueError):metrics([f])
  f=self.fight();f['dealt_removed']=31;self.assertFalse(valid(f))
 def test_no_late_turns_means_missing_coverage_not_sustained_output(self):
  x=metrics([self.fight()]);self.assertEqual(x['late_available'],0);self.assertIn('late_available',FAMILIES['damage'])
 def test_metric_families_keep_absorbed_block_and_hp_cost_distinct(self):
  x=metrics([self.fight()]);self.assertEqual(x['damage_rate'],15);self.assertEqual(x['absorbed_rate'],4);self.assertEqual(x['net_hp_per_fight'],2)
 def test_early_checkpoint_does_not_receive_future_boss_or_outcome(self):
  r=dict(act=1,asc=2,char='IRONCLAD',build='test',hp=40,maxhp=80,stage='fight3',boss='future',clear=0,prior_fights=3)
  x=feature(r,'baseline');r.update(clear=1,boss='different future boss');self.assertEqual(x,feature(r,'baseline'));self.assertNotIn('boss',x)
 def test_completed_earlier_act_survives_later_abandonment(self):
  from checkpoint_interactions import extract
  def point(kind,hp):return dict(map_point_type=kind,player_stats=[dict(current_hp=hp,max_hp=80,damage_taken=2,hp_healed=0)],rooms=[dict(model_id='enc_'+kind,monster_ids=['m'],turns_taken=3)])
  raw=dict(start_time=1,ascension=2,players=[dict(character='CHARACTER.IRONCLAD')],was_abandoned=True,win=False,map_point_history=[[point('monster',70),point('monster',68),point('monster',66),point('boss',50)],[point('monster',30),point('monster',20),point('monster',10)]])
  rows=extract(raw,'r','p',{});self.assertEqual([(r['act'],r['clear']) for r in rows],[(1,1),(2,0)])
  # The second unfinished-act outcome is censored by the outer abandonment
  # policy; clear=0 here must not itself be promoted to an observed loss.
if __name__=='__main__':unittest.main()
