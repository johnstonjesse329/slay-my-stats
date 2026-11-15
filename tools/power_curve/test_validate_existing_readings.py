import unittest
from validate_existing_readings import stages,label
import fight_demand as fd
class ExistingGradeTests(unittest.TestCase):
 def test_early_act3_snapshot_excludes_future_boss(self):
  fights=[dict(act=1,kind='boss',died=False)]+[dict(act=2,kind='monster',died=False) for _ in range(4)]+[dict(act=2,kind='boss',died=True)]
  prefix=dict(stages(fights))['act3_fight3'];self.assertEqual(len(prefix),4);self.assertFalse(any(f['act']==2 and f['kind']=='boss' for f in prefix))
 def test_fatal_third_fight_is_not_survived_checkpoint(self):
  fights=[dict(act=2,kind='monster',died=False),dict(act=2,kind='monster',died=False),dict(act=2,kind='monster',died=True)]
  self.assertNotIn('act3_fight3',dict(stages(fights)))
 def test_op_requires_both_late_acts(self):
  cuts={'run':{'guard':[.75,1.5],'pace':[.8,1.2]}}
  def act(n):return dict(act=n,turns=3,winTurns=3,taken=0,winTaken=10,verdict='ahead')
  self.assertFalse(fd.run_reading([act(0),act(1)],cuts)['op']);self.assertTrue(fd.run_reading([act(1),act(2)],cuts)['op'])
 def test_op_takes_precedence_over_hype(self):
  self.assertEqual(label({'op':True,'verdict':'ahead'}),'OP');self.assertEqual(label(None),'Unrated')
if __name__=='__main__':unittest.main()
