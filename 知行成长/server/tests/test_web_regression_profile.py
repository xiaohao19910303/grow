"""Large test groups must cover the entire original collection exactly once."""
import unittest
from run_web_regression import check_group_coverage

class GroupCoverageTests(unittest.TestCase):
    def result(self,selected,all_nodes=None):return {'node_ids':selected,'all_node_ids':all_nodes or ['a','b']}
    def test_all_collected_cases_must_run_once_without_collection_drift(self):
        self.assertTrue(check_group_coverage([self.result(['a']),self.result(['b'])]))
        self.assertFalse(check_group_coverage([self.result(['a'])]))
        self.assertFalse(check_group_coverage([self.result(['a']),self.result(['a','b'])]))
        self.assertFalse(check_group_coverage([self.result(['a']),self.result(['b'],['a','b','new_case'])]))
        self.assertFalse(check_group_coverage([]))
        self.assertFalse(check_group_coverage([{'node_ids':None,'all_node_ids':None}]))
