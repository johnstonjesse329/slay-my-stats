import unittest
import pandas as pd
from act_targets import matches, select, wilson

class TargetTests(unittest.TestCase):
    def test_joint_target_requires_all_three_conditions(self):
        d=pd.DataFrame(dict(turns=[3,4,3,3],loss=[5,5,6,5],hp_fraction=[.5,.5,.5,.4]))
        self.assertEqual(list(matches(d,3,5,.5).index),[0])
    def test_no_target_from_one_players_perfect_runs(self):
        d=pd.DataFrame([dict(turns=2,loss=0,hp_fraction=1,clear=1,player='one',char=str(i%3)) for i in range(40)])
        self.assertIsNone(select(d))
    def test_supported_perfect_sample_can_produce_candidate(self):
        d=pd.DataFrame([dict(turns=2,loss=0,hp_fraction=1,clear=1,player=str(i%3),char=str(i%3)) for i in range(40)])
        self.assertIsNotNone(select(d))
    def test_interval_does_not_claim_certainty(self):
        low,high=wilson(30,30)
        self.assertLess(low,1);self.assertAlmostEqual(high,1)
if __name__=='__main__':unittest.main()
