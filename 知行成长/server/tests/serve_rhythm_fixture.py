"""Real app HTML/APIs on a disposable PG schema and synthetic content only."""
from run_isolated_checks import setup_isolation


if __name__=='__main__':
    audit,runtime,_=setup_isolation()
    try:
        from serve_daily_arrangements_fixture import main
        def report_fixture(app,fixture):
            from datetime import timedelta
            from zoneinfo import ZoneInfo
            import action_plans as actions
            @app.get('/api/report')
            def report(range: str = 'week'):
                day=actions.clock().astimezone(ZoneInfo('Asia/Shanghai')).date()
                start=day-timedelta(days=day.weekday())
                return dict(range=range,start=str(start),end=str(day),days=(day-start).days+1,
                    active_days=0,total_minutes=0,avg_minutes=0,streak=0,decisions=0,predictions=0,
                    reviews=0,insights=0,knowledge_count=0,modules=[],duration_sources={})
        main(customize=report_fixture)
    finally:
        runtime.cleanup()
        if any(audit[k] for k in ('blocked_real_database_access','blocked_workspace_writes','blocked_network_access')):
            raise RuntimeError('Rhythm fixture isolation audit failed: '+str(audit))
