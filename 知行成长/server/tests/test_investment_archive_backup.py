"""Real whole-DB restore to a new archive directory with frozen comparison references."""
import json,os
from pathlib import Path
from unittest.mock import patch
import test_standalone_backup as backup_fixture

# Inherit fixture helpers only, not all unrelated backup cases.
class ResearchArchiveBackupTests(backup_fixture.StandaloneBackupTests):
    def test_archive_backup_restores_exact_comparison_and_dependencies(self):
        import db
        from investments.store import InvestmentStore
        from investments.research_tools import ResearchTools,DatasetInput,ScreenInput
        from investments.research_archive import ResearchArchive
        from investments.research_comparison import compare,ComparisonInput
        from standalone_backup import restore,verify,BackupError,create
        original=db.connect;source_root=self.root/'research';self.env['INVESTMENT_RESEARCH_ARCHIVE_ROOT']=str(source_root)
        def connect_to(dsn):return patch('db.connect',lambda *a,**kw:original(dsn+' options=-csearch_path=tenant_fixture',tenant=False))
        with patch.dict(os.environ,{'INVESTMENT_RESEARCH_ARCHIVE_ROOT':str(source_root)}),connect_to(self.source):
            store=InvestmentStore();store.initialize();tools=ResearchTools(store);archive=ResearchArchive(tools)
            account=store.create('accounts',{'name':'PRIVATE RESEARCH','baseline_date':'2026-10-19','opening_cash':'1000'},'archive-restore-account')
            runs=[]
            for n,price in enumerate(('11.0000000001','11.0000000002')):
                data=tools.dataset(DatasetInput(account_id=account['id'],source_label='CSV authorized',use_confirmed=True,market_date='2026-10-2'+str(8+n),rows=[{'code':'000001','name':'PRIVATE NAME','values':{'close':price,'pe':None}}]),'archive-data-'+str(n))
                runs.append(tools.screen(ScreenInput(account_id=account['id'],dataset_id=data['id'],conditions=[{'field':'close','op':'gt','value':'10'}]),'archive-screen-'+str(n)))
            receipt=compare(tools,ComparisonInput(account_id=account['id'],left_id=runs[0]['id'],left_version=1,right_id=runs[1]['id'],right_version=1),'archive-compare')
            state=archive.verify(receipt['id'],1,account['id'])
        # Missing root must not silently create an incomplete full backup.
        missing=dict(self.env);missing.pop('INVESTMENT_RESEARCH_ARCHIVE_ROOT')
        with self.assertRaises(BackupError):create(self.source,self.root/'incomplete',{'other-owner/content':self.git},env=missing,writers_stopped=True)
        manifest=self.create();self.assertEqual(manifest['research_archives']['count'],5)
        self.assertNotIn('PRIVATE NAME',json.dumps(manifest));verify(self.backup)
        from investments import research_archive_backup
        from investments.research_files import ArchiveFileError
        outside=self.root/'outside';outside.mkdir();alias=self.root/'alias';alias.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ArchiveFileError):research_archive_backup.restore(self.backup/'research-archives.zip',alias/'escaped',5)
        self.assertFalse((outside/'escaped').exists())

        with self.assertRaises(BackupError):restore(self.target,self.backup,self.root/'no-root',env=self.env,writers_stopped=True)
        # Even if a damaged manifest omits archive metadata and its ZIP, DB ready
        # references must prevent a falsely successful restore.
        original_manifest=(self.backup/'manifest.json').read_text();raw=json.loads(original_manifest)
        raw.pop('research_archives');raw['files'].pop('research-archives.zip')
        package=self.backup/'research-archives.zip';held=self.root/'held.zip';package.rename(held)
        (self.backup/'manifest.json').write_text(json.dumps(raw))
        with self.assertRaises(BackupError):restore(self.database(),self.backup,self.root/'missing-index-content',env=self.env,writers_stopped=True)
        held.rename(package);(self.backup/'manifest.json').write_text(original_manifest)
        restored=self.root/'restored-research';restore(self.target,self.backup,self.root/'restored-content',env=self.env,writers_stopped=True,archive_directory=restored)
        with patch.dict(os.environ,{'INVESTMENT_RESEARCH_ARCHIVE_ROOT':str(restored)}),connect_to(self.target):
            archive=ResearchArchive(tools);self.assertEqual(archive.read_record(receipt['id'],1,account['id']),receipt)
            self.assertEqual(archive.verify(receipt['id'],1,account['id'])['manifest_hash'],state['manifest_hash'])
            self.assertEqual(compare(tools,ComparisonInput(account_id=account['id'],left_id=runs[0]['id'],left_version=1,right_id=runs[1]['id'],right_version=1),'archive-compare'),receipt)
            self.assertEqual(store.balance(account['id'])['cash'],'1000')

# Avoid re-running inherited cases; retain shared setup/helpers.
for _name in list(vars(backup_fixture.StandaloneBackupTests)):
    if _name.startswith('test_'):setattr(ResearchArchiveBackupTests,_name,None)
