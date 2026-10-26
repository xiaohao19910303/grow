"""Self-paced conditions preserve weekly compatibility and real workload accounting."""
import copy
import unittest
from plans.store import brief, document, plan_markdown
from copilot.core import Problem
from cloud_fixtures import CloudFixture
import test_plans

B={'title':'应用表达','goal':'清晰汇报','level':'已学基础','minutes':15,'pacing':'self_paced','lesson_count':4}
def doc():
    d=copy.deepcopy(test_plans.D)
    d['lessons']=[{**d['lessons'][0],'number':n,'kind':'review' if n==4 else 'lesson','minutes':15,'requires':[]} for n in range(1,5)]
    return d
class ValidationTests(unittest.TestCase):
    def test_self_paced_count_and_last_review(self):
        b=brief(B);self.assertNotIn('weeks',b);self.assertEqual(len(document(doc(),b)['lessons']),4)
        self.assertIn('自由节奏',plan_markdown(b,doc()))
        d=doc();d['lessons'][-1]['kind']='lesson'
        with self.assertRaises(Problem):document(d,b)
        with self.assertRaises(Problem):brief({**B,'lesson_count':True})
    def test_original_weekly_shape_is_unchanged(self):
        self.assertEqual(brief(test_plans.B),test_plans.B)
        self.assertEqual(document(test_plans.D,test_plans.B),test_plans.D)
class BudgetTests(CloudFixture):
    def test_no_fake_weekly_minutes_or_adoption_budget_block(self):
        self.s.put('learning_settings','budget',{'id':'budget','weekly':0,'legacy_weekly':0})
        d=self.s.draft({'brief':B,'document':doc()})
        pid=self.s.adopt(d['id'],'self-paced-adopt')['plan_id']
        self.assertEqual(self.s.plan(pid)['brief']['lesson_count'],4)
        self.assertEqual(self.s.budget()['known_minutes'],0)
        self.assertEqual(self.s.budget()['self_paced_count'],1)
