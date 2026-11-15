"""Meaningful invariants for the registered offline candidate."""
import copy
import unittest
import shadow_explanatory_grades as s

def anchors():
    return {('A2-7', 2, c): dict(n=20, players=4, cost=cost, cost_q75=q75, turns=pace)
            for c, cost, q75, pace in [('op', .3, .5, .6), ('strong', .5, .8, .8), ('winners', .8, 1.2, 1)]}

def act(cost, turns):
    return dict(valid=True, tier='A2-7', act=2, cost=cost, turns=turns)

class Invariants(unittest.TestCase):
    def test_better_cost_or_pace_never_lowers_grade(self):
        a = anchors()
        for cost in [.1, .3, .4, .5, .7, .8, 1, 1.2, 1.5]:
            for turns in [.2, .6, .7, .8, 1, 2, 10]:
                base = s.RANK[s.grade_act(act(cost, turns), a)[0]]
                self.assertGreaterEqual(s.RANK[s.grade_act(act(cost / 2, turns), a)[0]], base)
                self.assertGreaterEqual(s.RANK[s.grade_act(act(cost, turns / 2), a)[0]], base)

    def test_slow_control_and_fast_pressure_both_qualify(self):
        self.assertEqual(s.grade_act(act(.2, 10), anchors())[0], 'OP')
        self.assertEqual(s.grade_act(act(.45, .5), anchors())[0], 'OP')
        self.assertEqual(s.grade_act(act(.45, 2), anchors())[0], 'Hype')

    def test_no_cross_tier_or_unordered_anchor_repair(self):
        self.assertEqual(s.grade_act(act(.1, .1) | {'tier': 'A8'}, anchors())[0], 'Unknown')
        a = anchors()
        a[('A2-7', 2, 'op')]['cost'] = .9
        self.assertEqual(s.grade_act(act(.1, .1), a)[0], 'Unknown')
        a = anchors()
        a[('A2-7', 2, 'op')]['players'] = 2
        self.assertEqual(s.grade_act(act(.1, .1), a)[0], 'Unknown')

    def test_op_needs_both_later_acts_and_unknown_is_not_rough(self):
        self.assertEqual(s.aggregate([dict(act=1, n=8, grade='OP')]), 'Hype')
        self.assertEqual(s.aggregate([dict(act=i, n=8, grade='OP') for i in [2, 3]]), 'OP')
        self.assertEqual(s.aggregate([dict(act=1, n=8, grade='OP'), dict(act=2, n=3, grade='Unknown')]), 'Unknown')

    def test_test_health_outcome_and_final_deck_not_evaluation_inputs(self):
        r = dict(run='test', player='p', tier='A2-7', fights=[dict(act=1, enc='e', t=3, taken=2, died=False) for _ in range(5)])
        refs = {('A2-7', 'e'): dict(turns=4, cost=5, n=8, players=3)}
        before = s.evaluate(r, refs, anchors())
        r.update(won=False, starting_hp=1, current_hp=0, final_deck=['junk'], asc=7)
        self.assertEqual(before, s.evaluate(r, refs, anchors()))
        # This applies after completed-fight scope is fixed; raw terminal-fight
        # identification itself uses recorded completion/outcome, as documented.

    def test_reference_training_population_and_tier_are_explicit(self):
        train = [dict(run=f'r{i}', player=f'p{i % 3}', tier='A0-1', fights=[dict(act=0, enc='e', t=4, taken=2, died=False)]) for i in range(6)]
        test = dict(run='heldout', player='test', tier='A0-1', fights=[dict(act=0, enc='e', t=1000, taken=1000, died=False)] * 3)
        refs = s.references(train)
        self.assertEqual(refs[('A0-1', 'e')]['n'], 6)
        self.assertEqual(refs[('A0-1', 'e')]['turns'], 4)
        self.assertEqual(s.measure(test, refs)[0][0]['turns'], 250)
        test['tier'] = 'A8'
        self.assertFalse(s.measure(test, refs)[0][0]['valid'])

    def test_partial_reference_coverage_abstains(self):
        r = dict(run='r', player='p', tier='A0-1', fights=[dict(act=0, enc='e' if i < 3 else 'missing', t=4, taken=2, died=False) for i in range(5)])
        a = s.measure(r, {('A0-1', 'e'): dict(turns=4, cost=2, n=8, players=3)})[0][0]
        self.assertEqual(a['matched'], 3)
        self.assertFalse(a['valid'])

if __name__ == '__main__':
    unittest.main()
