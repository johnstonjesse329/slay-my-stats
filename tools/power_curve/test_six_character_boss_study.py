import unittest
from six_character_boss_study import core_roster,eligible
class CatalogEligibilityTests(unittest.TestCase):
 def test_fool_is_core_when_catalog_says_so(self):
  self.assertEqual(core_roster({'CharacterPools':['fool','silent']}),{'CHARACTER.FOOL','CHARACTER.SILENT'})
 def test_published_core_solo_run_accepted(self):
  r=dict(start_time=1,seed='s',players=[dict(character='CHARACTER.FOOL')])
  self.assertEqual(eligible(r,{(1,'FOOL','s')},{'CHARACTER.FOOL'}),(True,'eligible'))
 def test_core_character_does_not_override_held_or_abandoned_status(self):
  r=dict(start_time=1,seed='s',players=[dict(character='CHARACTER.FOOL')])
  self.assertFalse(eligible(r,set(),{'CHARACTER.FOOL'})[0]);r['was_abandoned']=True
  self.assertFalse(eligible(r,{(1,'FOOL','s')},{'CHARACTER.FOOL'})[0])
 def test_multiplayer_and_mod_character_excluded(self):
  r=dict(start_time=1,seed='s',players=[dict(character='CHARACTER.FOOL')]*2)
  self.assertFalse(eligible(r,{(1,'FOOL','s')},{'CHARACTER.FOOL'})[0]);r['players']=[dict(character='CHARACTER.MOD')]
  self.assertFalse(eligible(r,{(1,'MOD','s')},{'CHARACTER.FOOL'})[0])
if __name__=='__main__':unittest.main()
