"""A new installation receives teaching files, never an old owner's progress."""
import json
from pathlib import Path
import tempfile
import unittest
from prepare_materials import prepare, MaterialError

class PackagedMaterials(unittest.TestCase):
    def test_teaching_whitelist_excludes_private_files_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'source';source.mkdir()
            for name in ('英文阅读/每日文章/Day 001.md','结构化表达/每日练习/Day 001.md','现代思维工具教程/01.md','英文阅读/学习记录.md','执行复盘/日常记录/private.md','学习计划/private/学习记录.md'):
                file=source/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('PUBLIC TEACHING' if '每日文章' in name or '每日练习' in name or name.startswith('现代思维') else 'PRIVATE STATE')
            result=prepare(source,root/'release')
            self.assertEqual(result['copied_files'],3)
            manifest=json.loads((root/'release/materials-manifest.json').read_text())
            self.assertEqual(len(manifest['files']),3)
            self.assertNotIn('PRIVATE STATE',''.join(p.read_text() for p in (root/'release').rglob('*') if p.is_file()))
            self.assertEqual((source/'英文阅读/学习记录.md').read_text(),'PRIVATE STATE')
            with self.assertRaises(MaterialError):prepare(source,root/'release')
    def test_symlinked_material_cannot_export_a_private_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);directory=root/'source/英文阅读/每日文章';directory.mkdir(parents=True)
            private=root/'private.md';private.write_text('PRIVATE OUTSIDE SOURCE');(directory/'Day 001.md').symlink_to(private)
            with self.assertRaises(MaterialError):prepare(root/'source',root/'release')
            self.assertFalse((root/'release').exists())
