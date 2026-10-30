"""Immutable archive IO, independent of suppliers and personal databases."""
import os,tempfile,json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from investments.research_files import ArchiveFiles,ArchiveFileError

KEY=('a'*32,'b'*32,'datasets','c'*64,'v1')
META={'record_id':'research-example','version':1,'record_hash':'d'*64}

class ArchiveFilesTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)/'archive';self.files=ArchiveFiles(self.root)
    def test_immutable_publish_permissions_and_verified_roundtrip(self):
        files={'record.json':b'{"price":"1.2300000001","unknown":null}'}
        first=self.files.write(KEY,META,files);self.assertEqual(self.files.write(KEY,META,files),first)
        manifest,loaded=self.files.read(KEY,first['manifest_hash']);self.assertEqual(loaded,files)
        leaf=self.root.joinpath(*KEY);self.assertEqual((leaf/'record.json').stat().st_mode&0o777,0o600)
        self.assertEqual(leaf.stat().st_mode&0o777,0o700)
        with self.assertRaises(ArchiveFileError):self.files.write(KEY,META,{'record.json':b'changed'})
        self.assertEqual(self.files.read(KEY,first['manifest_hash'])[1],files)
    def test_tamper_and_manifest_rewriting_are_detected(self):
        saved=self.files.write(KEY,META,{'record.json':b'original'});leaf=self.root.joinpath(*KEY)
        (leaf/'record.json').write_bytes(b'changed')
        with self.assertRaises(ArchiveFileError):self.files.read(KEY,saved['manifest_hash'])
        (leaf/'record.json').write_bytes(b'original');(leaf/'manifest.json').write_text('{}')
        with self.assertRaises(ArchiveFileError):self.files.read(KEY,saved['manifest_hash'])
    def test_parent_file_and_root_symlinks_are_rejected(self):
        outside=Path(self.tmp.name)/'outside';outside.mkdir();self.root.mkdir();(self.root/KEY[0]).symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ArchiveFileError):self.files.write(KEY,META,{'record.json':b'body'})
        self.assertEqual(list(outside.iterdir()),[])
        link=Path(self.tmp.name)/'link';link.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ArchiveFileError):ArchiveFiles(link).write(KEY,META,{'record.json':b'body'})
    def test_interrupted_publish_has_no_ready_partial_and_explicit_retry_recovers(self):
        with patch('investments.research_files.os.rename',side_effect=OSError('controlled')):
            with self.assertRaises(ArchiveFileError):self.files.write(KEY,META,{'record.json':b'body'})
        self.assertFalse(self.root.joinpath(*KEY).exists())
        saved=self.files.write(KEY,META,{'record.json':b'body'})
        self.assertEqual(self.files.read(KEY,saved['manifest_hash'])[1]['record.json'],b'body')
    def test_paths_cannot_escape_and_download_names_are_not_interpreted(self):
        for key in (('../escape',),('/tmp/escape',),('a','..','b')):
            with self.assertRaises(ArchiveFileError):self.files.write(key,META,{'record.json':b'body'})
        with self.assertRaises(ArchiveFileError):self.files.write(KEY,META,{'../secret':b'body'})

    def test_arbitrary_ancestor_symlink_and_fifo_are_rejected(self):
        outside=Path(self.tmp.name)/'outside';outside.mkdir();alias=Path(self.tmp.name)/'alias';alias.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ArchiveFileError):ArchiveFiles(alias/'archive').write(KEY,META,{'record.json':b'body'})
        self.assertEqual(list(outside.iterdir()),[])
        saved=self.files.write(KEY,META,{'record.json':b'body'});path=self.root.joinpath(*KEY,'record.json');path.unlink();os.mkfifo(path)
        with self.assertRaises(ArchiveFileError):self.files.read(KEY,saved['manifest_hash'])
