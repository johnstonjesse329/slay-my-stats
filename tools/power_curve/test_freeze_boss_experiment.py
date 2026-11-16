import datetime,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import freeze_boss_experiment as f
class FreezeTests(unittest.TestCase):
 def test_exported_numeric_and_categorical_score(self):
  model=dict(names=['hp','char=X'],coefficients=[.5,1],scales=[10,1],intercept=-1)
  self.assertAlmostEqual(f.exported_prediction(model,dict(hp=20,char='X')),1/(1+__import__('math').exp(-1)))
 def test_outcome_join_rejects_past_outcome(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);pred=root/'pred';pred.mkdir();outcomes=root/'outcomes.json'
   (pred/'one.json').write_text(json.dumps(dict(artifact_id='id',run='r',act=1,in_training=False,after_freeze=True,scored_at='2026-11-14T12:00:00+00:00')))
   outcomes.write_text(json.dumps({'r:1':dict(status='clear',resolved_at='2026-11-14T11:00:00+00:00')}))
   with patch.object(f,'load_bundle',return_value={'artifact_id':'id'}):
    with self.assertRaisesRegex(ValueError,'before prediction'):f.evaluate(root,pred,outcomes,root/'report.json')
 def test_training_examples_cannot_be_confirmation_evidence(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);pred=root/'pred';pred.mkdir();outcomes=root/'outcomes.json';outcomes.write_text('{}')
   (pred/'one.json').write_text(json.dumps(dict(artifact_id='id',run='r',act=1,in_training=True,after_freeze=True)))
   with patch.object(f,'load_bundle',return_value={'artifact_id':'id','models':{},'thresholds':[]}):f.evaluate(root,pred,outcomes,root/'report.json')
   result=json.loads((root/'report.json').read_text());self.assertEqual(result['matched'],0);self.assertEqual(result['excluded_training_or_pre_freeze'],1)
 def test_unknown_outcome_fields_rejected_in_prefix(self):
  with self.assertRaises(ValueError):f.validate_prefix({'clear':1})
if __name__=='__main__':unittest.main()
