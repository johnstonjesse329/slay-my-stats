import unittest
from aligned_measured_readiness import prior_window

def fight(enc,won=True):return dict(enc=enc,won=won,hp0=50,hp1=48,hp_in=2,hp_out=0,turns_n=3,dealt_removed=30,blocked=10,taken=2)
class LocalAlignmentTests(unittest.TestCase):
 def test_partial_log_can_supply_local_window(self):
  logs=[fight('a'),fight('b'),fight('c'),fight('boss')]
  window,reason=prior_window(logs,'boss',['unlogged','a','b','c']);self.assertEqual(reason,'accepted');self.assertEqual([x['enc'] for x in window],['a','b','c'])
 def test_duplicate_boss_attempts_are_not_silently_selected(self):
  logs=[fight('a'),fight('b'),fight('c'),fight('boss'),fight('boss')]
  self.assertEqual(prior_window(logs,'boss',['a','b','c'])[1],'ambiguous_or_missing_boss')
 def test_target_result_does_not_affect_prior_window(self):
  logs=[fight('a'),fight('b'),fight('c'),fight('boss')];before=prior_window(logs,'boss',['a','b','c'])
  logs[-1].update(won=False,hp1=0,taken=999,dealt_removed=999);self.assertEqual(before,prior_window(logs,'boss',['a','b','c']))
 def test_reordered_or_unbalanced_window_rejected(self):
  logs=[fight('a'),fight('c'),fight('b'),fight('boss')]
  self.assertEqual(prior_window(logs,'boss',['a','b','c'])[1],'predecessor_mismatch')
  logs=[fight('a'),fight('b'),fight('c'),fight('boss')];logs[1]['hp_in']=999
  self.assertEqual(prior_window(logs,'boss',['a','b','c'])[1],'hp_flow_mismatch')
if __name__=='__main__':unittest.main()
