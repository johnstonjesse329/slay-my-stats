import unittest
from path_to_boss import features
class PathTests(unittest.TestCase):
 def test_future_arrival_and_clearance_do_not_enter_predictors(self):
  f=dict(enc='x',kind='monster',act=2,tier='A9',turns=3,loss=2,pool=None)
  r=dict(run='r',player='p',ts=1,act=2,tier='A9',asc=9,char='x',build='v',fight_index=3,hp=40,maxhp=80,clear=0,reached=0,history=[f]*3)
  x=features(r,{},'performance');r.update(clear=1,reached=1)
  self.assertEqual(x,features(r,{},'performance'))
 def test_healing_rule_is_cumulative(self):
  f=dict(enc='x',kind='monster',act=1,tier='A10',turns=3,loss=0,pool=None)
  r=dict(act=1,tier='A10',asc=10,char='x',build='v',fight_index=3,hp=50,maxhp=80,history=[f]*3)
  self.assertEqual(features(r,{},'baseline')['healing_rule'],'A2+')
if __name__=='__main__':unittest.main()
