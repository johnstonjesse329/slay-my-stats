import unittest
from ablate_boss_development import selected_features,GROUPS
class AblationTests(unittest.TestCase):
 def test_without_upgrades_differs_only_in_upgrade_count(self):
  self.assertEqual(GROUPS['full']-GROUPS['without_upgrades'],{'upgrade_events'})
  self.assertEqual(GROUPS['without_upgrades']-GROUPS['full'],set())
 def test_cost_only_does_not_include_process_or_card_types(self):
  source={'acquired_mean_cost':2,'upgrade_events':4,'acquired_Power':3,'future_outcome':1}
  self.assertEqual(selected_features(source,'cost'),{'acquired_mean_cost':2})
 def test_baseline_ignores_all_ledger_fields(self):
  self.assertEqual(selected_features({'upgrade_events':99},'performance'),{})
if __name__=='__main__':unittest.main()
