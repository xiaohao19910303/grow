"""Characterize the existing Markdown scan contract before moving its implementation."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import app
from tenancy import current_user, learning_root


class KnowledgeScanningTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'materials'
        self.root.mkdir()
        patched = patch.object(app, 'LEARN_ROOT', self.root)
        patched.start()
        self.addCleanup(patched.stop)
        token = current_user.set(None)
        self.addCleanup(current_user.reset, token)

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_index_skips_headers_and_separators_and_keeps_category_and_source(self):
        index = self.write('知识索引.md', '''| 概念 | 一句话解释 | 详细学习位置 |
| --- | :---: | ---: |
| 初始概念 | 尚未分组 | 备注 |
## 一、判断
| 贝叶斯更新 | 随证据更新 | 教程/01.md | 后续备注 |
## 二．
| 反证 | 寻找反例 |
''')
        self.assertEqual(app.parse_index(index), [
            dict(name='初始概念', category='未分类', summary='尚未分组', source='备注', kind='concept', date=''),
            dict(name='贝叶斯更新', category='判断', summary='随证据更新', source='教程/01.md', kind='concept', date=''),
            dict(name='反证', category='判断', summary='寻找反例', source='', kind='concept', date=''),
        ])

    def test_scan_preserves_file_order_titles_dates_and_relative_sources(self):
        self.write('知识索引.md', '| 概念 | 解释 | 来源 |\n| 更新判断 | 摘要 | 教程 |')
        directory = '现代思维工具教程'
        self.write(directory + '/02.md', '## 第二课: 反证（练习）\n### 第三课：不匹配\n')
        self.write(directory + '/01.md', '## 第一课：证据 (入门)\n')
        self.write('每日认知与通识学习/每日课程/2026-10-25-第001课-观察.md', '# 合成课程')
        self.write('英文阅读/每日文章/Day 002 - Evidence.md', '# 合成文章')
        self.write('结构化表达/每日练习/Day 001.md', '# 合成练习')
        self.write('英文阅读/每日文章/ignored.txt', '不扫描')
        nodes = app.scan_markdown()
        self.assertEqual([n['name'] for n in nodes], ['更新判断', '证据', '反证', '观察', 'Evidence', 'Day 001'])
        self.assertEqual([n['kind'] for n in nodes], ['concept', 'tool', 'tool', 'footprint', 'footprint', 'footprint'])
        self.assertEqual(nodes[1]['source'], directory + '/01.md')
        self.assertEqual(nodes[3]['date'], '2026-10-25')
        self.assertEqual(nodes[4]['date'], '')
        self.assertEqual(nodes[5]['category'], '结构化表达')

    def test_missing_material_folders_produce_an_empty_scan(self):
        self.assertEqual(app.scan_markdown(), [])

    def test_request_account_scans_only_its_own_learning_root(self):
        self.write('知识索引.md', '| 所有者概念 | 私有摘要 | 来源 |')
        token = current_user.set({'id': 'synthetic-reader', 'is_owner': False})
        try:
            own_root = learning_root(self.root)
            own_root.mkdir(parents=True)
            (own_root / '知识索引.md').write_text('| 本人概念 | 本人摘要 | 来源 |')
            tools = own_root / '现代思维工具教程'
            tools.mkdir()
            (tools / '01.md').write_text('## 第一课：本人方法')
            nodes = app.scan_markdown()
            self.assertEqual([n['name'] for n in nodes], ['本人概念', '本人方法'])
            self.assertEqual(nodes[1]['source'], '现代思维工具教程/01.md')
        finally:
            current_user.reset(token)
        self.assertEqual([n['name'] for n in app.scan_markdown()], ['所有者概念'])
