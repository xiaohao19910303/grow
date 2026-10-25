"""Production settings/help with disposable PG and an injected model transport."""
from run_isolated_checks import setup_isolation

if __name__ == '__main__':
    audit,runtime,_=setup_isolation()
    try:
        import asyncio
        from unittest.mock import patch
        from serve_daily_arrangements_fixture import main
        def customize(app,fixture):
            state={'mode':'success','tests':0}
            async def model(messages,cfg):
                assert cfg['key'].startswith('TEST_SETUP_')
                state['tests']+=1
                if state['mode']=='slow':await asyncio.sleep(1)
                if state['mode']=='error':raise RuntimeError('PRIVATE SYNTHETIC PROVIDER ERROR')
                yield {'text':'连接成功'};yield {'done':True}
            mock=patch('copilot.transport.qwen_stream',model);mock.start();fixture.addCleanup(mock.stop)
            @app.post('/fixture/setup-mode/{mode}')
            def mode(mode:str):state['mode']=mode;return {'ok':True}
            @app.get('/fixture/setup-status')
            def status():return state
        main(customize=customize)
    finally:
        runtime.cleanup()
        if any(audit[k] for k in ('blocked_real_database_access','blocked_workspace_writes','blocked_network_access')):
            raise RuntimeError('Settings fixture isolation failed: '+str(audit))
