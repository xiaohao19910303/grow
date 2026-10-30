import os,sys,json,unittest
from pathlib import Path
server=Path(__file__).resolve().parents[3]/'知行成长/server';sys.path[:0]=[str(server),str(server/'tests')]
from run_isolated_checks import setup_isolation
stats,runtime,_=setup_isolation()
modules=['test_investment_archive_files','test_investment_research_archive','test_investment_research_comparison','test_investment_archive_backup','test_investment_archive_browser','test_isolation_dirfd']
suite=unittest.defaultTestLoader.loadTestsFromNames(modules)
result=unittest.TextTestRunner(verbosity=2).run(suite)
report={'python_tests':result.testsRun,'skipped':len(result.skipped),'failures':len(result.failures),'errors':len(result.errors),'isolation':stats}
print('RESEARCH_ARCHIVE_RESULT '+json.dumps(report,sort_keys=True));runtime.cleanup()
raise SystemExit(0 if result.wasSuccessful() and not result.skipped and not any(stats[k] for k in ('blocked_network_access','blocked_real_database_access','blocked_workspace_writes')) else 1)
