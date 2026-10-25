import unittest
from mobile_learning_questions import questions
class NativeQuestionTests(unittest.TestCase):
    def test_h5_keys_and_reference_answers_are_separate(self):
        body='## 练习\n\n1. Why?\n2. How?\n\n## 参考答案\n\n### 练习\n\n- Secret solution\n\n## 思考题\n\n- Explain\n'
        self.assertEqual([q['id'] for q in questions(body)],['练习:1','练习:2','思考题:1'])
    def test_hidden_code_and_checklists_are_not_answer_prompts(self):
        self.assertEqual(len(questions('<details>\n## 练习\n- Hidden\n</details>\n```md\n## 练习\n- Code\n```\n## 完成练习\n- [x] Done\n')),1)
        self.assertEqual(questions('## 完成练习\n- [x] Done\n')[0]['id'],'我的练习:1')
    def test_numbered_exercise_has_one_stable_answer(self):
        self.assertEqual([q['id'] for q in questions('## 练习一\n- step A\n- step B\n')],['练习一:1'])
