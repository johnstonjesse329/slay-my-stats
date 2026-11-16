import copy,unittest
from boss_development import ledger
class DevelopmentTests(unittest.TestCase):
 def test_final_deck_and_boss_rewards_do_not_enter_preboss_features(self):
  before=dict(map_point_type='monster',player_stats=[dict(cards_gained=[{'id':'CARD.X'}])])
  boss=dict(map_point_type='boss',player_stats=[dict(cards_gained=[{'id':'CARD.Y'}])])
  raw=dict(players=[dict(deck=[{'id':'CARD.FUTURE'}])],map_point_history=[[before,boss]])
  x=ledger(raw,{});raw['players'][0]['deck']=[{'id':'CARD.OTHER'}];boss['player_stats'][0]['cards_gained'].append({'id':'CARD.Z'})
  self.assertEqual(x,ledger(raw,{}));self.assertEqual(x[1]['tracked_acquired_copies'],1)
 def test_removal_does_not_create_negative_unknown_starter_count(self):
  raw=dict(map_point_history=[[dict(map_point_type='ancient',player_stats=[dict(cards_removed=[{'id':'CARD.STARTER'}])]),dict(map_point_type='boss',player_stats=[{}])]])
  x=ledger(raw,{})[1];self.assertEqual(x['tracked_acquired_copies'],0);self.assertEqual(x['untracked_removals'],1)
 def test_picked_choice_is_not_double_counted(self):
  raw=dict(map_point_history=[[dict(map_point_type='monster',player_stats=[dict(cards_gained=[{'id':'CARD.X'}],card_choices=[dict(card={'id':'CARD.X'},was_picked=True)])]),dict(map_point_type='boss',player_stats=[{}])]])
  self.assertEqual(ledger(raw,{})[1]['acquisitions'],1)
if __name__=='__main__':unittest.main()
