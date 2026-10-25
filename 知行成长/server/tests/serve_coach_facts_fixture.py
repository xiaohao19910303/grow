"""Real production HTML and coach API, disposable PostgreSQL and synthetic facts."""
from run_isolated_checks import setup_isolation


if __name__ == '__main__':
    audit, runtime, _ = setup_isolation()
    try:
        from datetime import date, datetime, timedelta, timezone
        from unittest.mock import patch
        import db
        from coach_facts import register
        from serve_daily_arrangements_fixture import main

        def customize(app, fixture):
            register(app)
            from behavior_report.api import register as reports
            reports(app, fixture.root, Path(fixture.tmp.name)/'runtime')
            fixed = datetime(2026, 10, 25, 4, tzinfo=timezone.utc)
            for mock in (patch('action_plans.clock',return_value=fixed),
                         patch('growth_statistics.shanghai_today',return_value=date(2026,10,25))):
                mock.start(); fixture.addCleanup(mock.stop)

            def seed(mode):
                from study_materials import initialize
                initialize()
                with db.connect() as conn:
                    for table in ('checkins','habits','predictions','study_learning_records','copilot_learning_records','learning_feedback'):
                        conn.execute('DELETE FROM ' + table)
                    today = date(2026, 10, 25)
                    if mode == 'decrease':
                        for offset, count in ((3,3),(2,2),(1,1)):
                            for n in range(count):conn.execute('INSERT INTO checkins VALUES (?,?,1)',(str(today-timedelta(days=offset)), 'module-'+str(n)))
                    elif mode == 'course':
                        conn.execute('INSERT INTO study_learning_records VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            ('biaoda','Day 001.md',1,'从事实到判断','合成私人笔记',120,'2026-10-11','2026-10-11',1,'fixture-coach-course','hash'))
                    elif mode == 'predictions':
                        for result in ('correct','correct','correct','correct','incorrect'):
                            conn.execute('INSERT INTO predictions(date,statement,probability,result) VALUES (?,?,70,?)',(str(today),'合成预测',result))
                    elif mode == 'activity':
                        conn.execute('INSERT INTO habits VALUES (?,10,?)',(str(today),'合成习惯记录'))
                    return {'mode':mode}
            seed('activity')
            app.post('/fixture/coach/{mode}')(seed)
        from pathlib import Path
        main(customize=customize)
    finally:
        runtime.cleanup()
        if any(audit[k] for k in ('blocked_real_database_access','blocked_workspace_writes','blocked_network_access')):
            raise RuntimeError('Coach fixture isolation audit failed: '+str(audit))
