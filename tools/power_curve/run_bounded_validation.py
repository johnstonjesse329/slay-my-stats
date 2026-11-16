"""Run the bounded investigation's targeted regression checks, without network."""
import json,unittest
from pathlib import Path
NAMES=['test_act_readiness','test_boss_readiness','test_boss_development','test_checkpoint_interactions','test_boss_healing_sensitivity','test_boss_player_history','test_six_character_boss_study','test_measured_boss_readiness','test_aligned_measured_readiness','test_ablate_boss_development','test_path_to_boss','test_bounded_readiness_goal']
def main():
 suite=unittest.defaultTestLoader.loadTestsFromNames(NAMES);result=unittest.TextTestRunner(verbosity=1).run(suite)
 output=Path(__file__).resolve().parents[2]/'local_data/act_validation/six_character/bounded_goal/tests.json';report=dict(modules=NAMES,tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),passed=result.wasSuccessful());output.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
 if not result.wasSuccessful():raise SystemExit(1)
if __name__=='__main__':main()
