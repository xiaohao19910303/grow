"""Production UI, disposable PG and synthetic course drafts; no model requests."""
from run_isolated_checks import setup_isolation

if __name__ == '__main__':
    audit, runtime, _ = setup_isolation()
    try:
        import copy
        import action_plans as actions
        from unittest.mock import patch
        import learning_actions
        from serve_daily_arrangements_fixture import main
        from test_plans import B, D, S, content

        def customize(app, fixture):
            faults={'fail_next_link':False};original_link=learning_actions.link
            def maybe_fail(*args,**kwargs):
                if faults['fail_next_link']:
                    faults['fail_next_link']=False
                    raise RuntimeError('PRIVATE SYNTHETIC ERROR')
                return original_link(*args,**kwargs)
            mock=patch('learning_actions.link',side_effect=maybe_fail);mock.start();fixture.addCleanup(mock.stop)

            @app.post('/fixture/fail-next-learning-link')
            def fail_next():faults['fail_next_link']=True;return {'armed':True}

            with actions.connection() as c:
                c.execute('DELETE FROM action_plans')

            @app.post('/fixture/learning-draft')
            def draft():
                doc=copy.deepcopy(D);doc['stages'].append({'title':'应用','goal':'用于现实'});doc['lessons'][1]['stage']=2
                return fixture.s.draft({'brief':{**B,'title':'隔离规划验收'},'document':doc})

            @app.post('/fixture/learning-course/{pid}')
            def course(pid: str):
                fixture.s.save_sources(pid,S);ctx=fixture.s.course_context(pid)
                return fixture.s.course_draft(ctx,content(ctx),'摘要 [来源](https://example.org/lesson)')

        main(customize=customize)
    finally:
        runtime.cleanup()
        if any(audit[k] for k in ('blocked_real_database_access','blocked_workspace_writes','blocked_network_access')):
            raise RuntimeError('Learning action fixture isolation audit failed: '+str(audit))
