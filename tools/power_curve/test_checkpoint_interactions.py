import copy,unittest
from checkpoint_interactions import extract,features

def point(kind,hp=70,card=None):
 s=dict(current_hp=hp,max_hp=80,damage_taken=2,hp_healed=0)
 if card:s['cards_gained']=[dict(id=card)]
 return dict(map_point_type=kind,player_stats=[s],rooms=[dict(model_id='enc_'+kind,monster_ids=['m'],turns_taken=3)])
class CheckpointTests(unittest.TestCase):
 def raw(self):return dict(start_time=1,ascension=2,players=[dict(character='CHARACTER.FOOL',deck=[{'id':'CARD.FINAL'}])],map_point_history=[[point('monster',card='CARD.X') for _ in range(7)]+[point('boss',0)]],win=False)
 def test_future_cards_outcome_and_final_deck_cannot_change_early_features(self):
  raw=self.raw();first=extract(raw,'r','p',{})[0];before=features(first,{},'tree_composition')
  raw['players'][0]['deck']=[dict(id='CARD.FUTURE')];raw['map_point_history'][0][5]['player_stats'][0]['cards_gained']=[dict(id='CARD.Y')]*10;raw['map_point_history'][0][-1]['player_stats'][0]['current_hp']=50;raw['win']=True
  second=extract(raw,'r','p',{})[0];self.assertEqual(before,features(second,{},'tree_composition'));self.assertNotEqual(first['clear'],second['clear'])
 def test_prefix_composition_does_not_include_later_gains(self):
  rows=extract(self.raw(),'r','p',{})
  self.assertEqual([r['fight_index'] for r in rows],[3,6]);self.assertEqual([r['composition']['tracked_acquired_copies'] for r in rows],[3,6])
 def test_death_before_boss_kept_after_checkpoint(self):
  raw=self.raw();raw['map_point_history'][0]=raw['map_point_history'][0][:4];raw['map_point_history'][0][-1]['player_stats'][0]['current_hp']=0
  rows=extract(raw,'r','p',{});self.assertEqual(len(rows),1);self.assertEqual((rows[0]['clear'],rows[0]['reached']),(0,0))
 def test_a10_first_boss_survival_is_not_sequence_success(self):
  raw=self.raw();raw['ascension']=10;raw['map_point_history']=[[],[],raw['map_point_history'][0]];raw['map_point_history'][2][-1]=point('boss',40);raw['map_point_history'][2].append(point('boss',0))
  rows=extract(raw,'r','p',{});self.assertTrue(all(r['reached']==1 and r['clear']==0 for r in rows))
if __name__=='__main__':unittest.main()
