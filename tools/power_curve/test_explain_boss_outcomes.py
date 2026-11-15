import unittest
from explain_boss_outcomes import explain
class ExplanationTests(unittest.TestCase):
 def fight(self):return dict(hp0=49,hp1=0,won=False,taken=53,overkill=0,hp_in=67,hp_out=18,enemy_lost=408,dealt_removed=408,enemy_unexplained=0,blocked=136,spent=39,turns=[dict(played=['x'],drawn=[],enemy_lost=408)],enemy_healed=0)
 def test_health_costs_and_healing_reconcile(self):
  x=explain(self.fight());self.assertTrue(x['hp_balanced']);self.assertEqual(x['additional_hp_cost'],14);self.assertEqual(x['starting_hp']-x['enemy_damage_suffered']-x['additional_hp_cost']+x['healed'],x['ending_hp'])
 def test_missing_death_endpoint_can_be_verified_from_saved_state(self):
  f=self.fight();f['hp1']=None;x=explain(f,0);self.assertTrue(x['hp_balanced']);self.assertIn('saved run death',x['ending_hp_source'])
 def test_missing_winning_endpoint_is_not_filled_from_postfight_room(self):
  f=self.fight();f.update(won=True,hp1=None);self.assertFalse(explain(f,20)['hp_balanced'])
 def test_killing_blow_excess_is_not_double_subtracted(self):
  f=self.fight();f.update(hp0=10,hp1=None,taken=15,overkill=5,hp_in=10,hp_out=0,blocked=10)
  x=explain(f,0);self.assertEqual(x['enemy_damage_suffered'],10);self.assertEqual(x['additional_hp_cost'],0);self.assertEqual(x['blocked_share'],.4);self.assertTrue(x['hp_balanced'])
 def test_inconsistent_ledger_stays_flagged(self):
  f=self.fight();f['hp_in']=60;self.assertFalse(explain(f)['hp_balanced'])
if __name__=='__main__':unittest.main()
