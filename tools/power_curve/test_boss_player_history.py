import unittest
from boss_player_history import history_features
class HistoryTests(unittest.TestCase):
 def test_excludes_same_run_future_and_unfinished_history(self):
  current=dict(run='now',player='p',ts=100,act=1,tier='A9')
  def event(run,ts,end,clear,player='p'):return dict(run=run,player=player,ts=ts,end=end,clear=clear,act=1,tier='A9')
  data=[event('old',1,10,1),event('now',90,95,0),event('unfinished',90,110,0),event('future',101,102,0),event('other',1,2,0,'q')]
  x=history_features(current,data)
  self.assertEqual(x['history_n'],1);self.assertEqual(x['history_recent_rate'],9/11)
 def test_future_outcomes_do_not_change_history(self):
  current=dict(run='now',player='p',ts=100,act=2,tier='A8')
  event=dict(run='future',player='p',ts=200,end=210,clear=0,act=2,tier='A8')
  before=history_features(current,[event]);event['clear']=1
  self.assertEqual(before,history_features(current,[event]))
 def test_cold_start_is_explicit(self):
  x=history_features(dict(run='now',player='p',ts=100,act=1,tier='A9'),[])
  self.assertEqual(x['history_n'],0);self.assertEqual(x['history_recent_rate'],.8)
if __name__=='__main__':unittest.main()
