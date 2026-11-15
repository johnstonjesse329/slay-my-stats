import unittest
from boss_healing_sensitivity import healing_group,extract_entries
class HealingTests(unittest.TestCase):
 def test_rule_accumulates(self):
  self.assertEqual([healing_group(x) for x in range(11)],['A0-1']*2+['A2+']*9)
 def test_entry_uses_observed_first_noncombat_state(self):
  raw={'map_point_history':[[{'player_stats':[{'current_hp':62,'max_hp':80}],'rooms':[]},{'player_stats':[{'current_hp':0,'max_hp':80}],'rooms':[]}]]}
  self.assertEqual(extract_entries(raw),{1:(62,80)})
 def test_first_combat_does_not_supply_postcombat_hp_as_entry(self):
  raw={'map_point_history':[[{'player_stats':[{'current_hp':30,'max_hp':80}],'rooms':[{'turns_taken':3}]}]]}
  self.assertEqual(extract_entries(raw),{})
if __name__=='__main__':unittest.main()
