import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile, gzip, json
import act_readiness as a

class ReadinessTests(unittest.TestCase):
    def test_reference_never_uses_held_out_fights(self):
        base=dict(enc='x',tier='A8',act=1,kind='monster',turns=3,loss=2)
        ref=a.reference([base|{'run':'train'},base|{'run':'test','loss':999}],{'train'})
        self.assertEqual(ref[('x','A8')],(1,3,2))

    def test_labels_and_future_history_cannot_enter_features(self):
        f=dict(enc='x',kind='monster',act=1,tier='A8',turns=3,loss=2,pool=90)
        r=dict(act=1,tier='A8',asc=8,char='x',build='v1',fight_index=3,hp=40,maxhp=80,clear=0,history=[f]*3)
        before=a.features(r,{},'trend');r['clear']=1
        self.assertEqual(before,a.features(r,{},'trend'))
        self.assertEqual(before['estimated_damage_per_turn'],30)

    def test_a10_second_boss_death_is_failure_and_boss_not_a_feature(self):
        def point(kind,hp):return dict(map_point_type=kind,player_stats=[dict(current_hp=hp,max_hp=80,damage_taken=2,hp_healed=0)],rooms=[dict(model_id='x',monster_ids=['m'],turns_taken=3)])
        r=dict(players=[dict(character='CHARACTER.IRONCLAD')],start_time=10,seed='s',ascension=10,win=False,map_point_history=[[],[],[point('monster',70),point('monster',68),point('monster',66),point('boss',40),point('boss',0)]])
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'users'/'sample').mkdir(parents=True)
            # Parsed character IDs retain uppercase without prefix.
            with gzip.open(root/'users'/'sample'/'month.json.gz','wt') as fp:json.dump({'runs':[dict(ts=10,char='IRONCLAD',seed='s')]},fp)
            with patch.object(a,'OUT',root),patch.object(a.g,'load',return_value={('test',10):r}),patch.object(a.fd,'body_pool',return_value=(90,100)):
                rows,_,_=a.dataset()
                self.assertEqual(len(rows),1);self.assertEqual(rows[0]['clear'],0)
                self.assertEqual(len(rows[0]['history']),3)
                r['map_point_history'][2][-1]['player_stats'][0]['current_hp']=20;r['win']=True
                rows,_,_=a.dataset();self.assertEqual(rows[0]['clear'],1)

if __name__=='__main__':unittest.main()
