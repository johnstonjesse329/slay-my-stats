import copy,unittest
import boss_readiness as b

def point(kind,hp,turns=3):
 return dict(map_point_type=kind,player_stats=[dict(current_hp=hp,max_hp=80,damage_taken=2,hp_healed=0)],rooms=[dict(model_id='enc_'+kind,monster_ids=['m'],turns_taken=turns)])
def raw():
 return dict(start_time=123,ascension=10,players=[dict(character='CHARACTER.IRONCLAD')],build_id='test',win=False,map_point_history=[[],[],[point('monster',70),point('monster',65),point('monster',60),point('rest_site',78,0),point('boss',40),point('boss',0)]])
class BossTests(unittest.TestCase):
 def test_target_damage_turns_and_outcome_never_enter_first_boss_features(self):
  r=raw();a,_=b.extract_run(r,'run','player');first=next(x for x in a if x['task']=='boss_sequence');x=b.feats(first,{},'performance')
  r['map_point_history'][2][-2]['player_stats'][0].update(current_hp=0,damage_taken=999,hp_healed=80)
  r['map_point_history'][2][-2]['rooms'][0]['turns_taken']=999
  r['win']=True
  a,_=b.extract_run(r,'run','player');second=next(x for x in a if x['task']=='boss_sequence')
  self.assertEqual(x,b.feats(second,{},'performance'));self.assertEqual(first['hp'],78)
 def test_a10_separates_first_boss_win_from_sequence_loss(self):
  rows,_=b.extract_run(raw(),'run','player')
  self.assertEqual([(r['task'],r['ordinal'],r['clear']) for r in rows],[('next_boss',1,1),('boss_sequence',1,0),('next_boss',2,0)])
 def test_second_boss_uses_first_boss_result_only_after_it_happens(self):
  rows,_=b.extract_run(raw(),'run','player');second=rows[-1]
  self.assertEqual(second['hp'],40);self.assertEqual(len(second['history']),4)
 def test_regular_act_sequence_survives_later_run_loss(self):
  r=raw();r['ascension']=9;r['map_point_history'][2].pop()
  rows,_=b.extract_run(r,'run','player');self.assertEqual(rows[1]['clear'],1)
if __name__=='__main__':unittest.main()
