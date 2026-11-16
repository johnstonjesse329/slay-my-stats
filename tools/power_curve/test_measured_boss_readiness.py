import unittest
from measured_boss_readiness import measured_features
class MeasuredFeatureTests(unittest.TestCase):
 def test_actual_removed_hp_used_instead_of_attempted_damage(self):
  f=dict(turns_n=2,dealt_removed=30,dmg=999,blocked=8,taken=2,hp_in=2,hp_out=0)
  x=measured_features([f]);self.assertEqual(x['measured_damage'],15);self.assertEqual(x['measured_blocked'],4)
 def test_block_generated_is_not_block_absorbed(self):
  f=dict(turns_n=1,dealt_removed=10,blocked=3,bgn=100,taken=1,hp_in=1,hp_out=0)
  self.assertEqual(measured_features([f])['measured_block_share'],.75)
 def test_hp_cost_and_enemy_damage_stay_distinct(self):
  f=dict(turns_n=2,dealt_removed=10,blocked=4,taken=2,hp_in=8,hp_out=3)
  x=measured_features([f]);self.assertEqual(x['measured_net_hp'],5);self.assertEqual(x['measured_taken'],1)
 def test_zero_turn_window_is_rejected(self):
  with self.assertRaises(ValueError):measured_features([dict(turns_n=0)])
if __name__=='__main__':unittest.main()
