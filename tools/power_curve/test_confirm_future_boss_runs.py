import unittest
from confirm_future_boss_runs import future_run
class FutureCohortTests(unittest.TestCase):
 def test_old_run_uploaded_later_is_not_confirmation(self):
  self.assertFalse(future_run(1,'2026-11-15T03:00:00+00:00','2026-11-15T02:00:00+00:00'))
 def test_both_run_and_upload_must_follow_freeze(self):
  from datetime import datetime
  ts=datetime.fromisoformat('2026-11-15T03:00:00+00:00').timestamp()
  self.assertTrue(future_run(ts,'2026-11-15T04:00:00+00:00','2026-11-15T02:00:00+00:00'))
  self.assertFalse(future_run(ts,'2026-11-15T01:00:00+00:00','2026-11-15T02:00:00+00:00'))
if __name__=='__main__':unittest.main()
