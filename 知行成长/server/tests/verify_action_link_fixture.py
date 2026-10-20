"""Run after UI pairing in the two disposable localhost acceptance fixtures."""
import json,time,uuid
import httpx

def check(response):
    assert response.is_success, f'fixture HTTP {response.status_code}'
    return response.json()

def main():
    with httpx.Client(base_url='http://127.0.0.1:18881',headers={'X-Copilot-Request':'1'},timeout=15) as web,httpx.Client(base_url='http://127.0.0.1:18880',timeout=15) as native:
        check(web.post('/api/auth/login',json={'username':'qa_alice','password':'ISOLATED-QA-Password-1234-ONLY'}))
        session=check(native.post('/api/v1/auth/login',json={'appId':'lighttick','account':'alice@example.com','password':'Password1234','clientType':'app'}))['data']
        native.headers.update({'Authorization':'Bearer '+session['accessToken'],'X-App-Id':'lighttick'})
        base='/api/v1/lighttick/action-plans'
        state=check(web.get('/api/action-link'));assert state['phase']=='active'
        w=check(web.get('/api/action-plans'));n=check(native.get(base))['data']
        assert w['plans']==n['plans'] and w['execution']==n['execution']
        year=next(p for p in n['plans'] if p['period']=='year')
        assert year['progress']=={'minutes':27,'completed':1,'minimum':1,'interrupted':1},year['progress']
        records=check(native.get(base+'/records'))['data'];assert records==check(web.get('/api/action-plans/records'))
        assert sorted(r['outcome'] for r in records['records'])==['completed','interrupted','minimum']
        interrupted=next(p for p in n['plans'] if p['title']=='联动验收：中断恢复')
        scope={'plan_id':interrupted['id'],'start_date':interrupted['start_date'],'end_date':interrupted['end_date'],'include_notes':False,'include_review':False}
        history=check(web.get('/api/action-plans/reviews',params={'plan_id':interrupted['id']}))
        assert history['reviews'][0]['worked']=='Read five minutes first.'
        preview=check(web.post('/api/action-plans/reviews/preview',json=scope))
        assert 'note' not in preview['records'][0]
        body={**scope,'snapshot_hash':preview['snapshot_hash'],'consent':True,'key':'qa-summary-'+str(uuid.uuid4()),'ai_config':{'api_key':'TEST_ONLY_NO_EXTERNAL_MODEL','api_base_url':'https://example.invalid/v1','model_name':'fixture-summary'}}
        report=check(web.post('/api/action-plans/reviews/generate',json=body))
        assert report==check(web.post('/api/action-plans/reviews/generate',json=body))
        for _ in range(30):
            history=check(web.get('/api/action-plans/reviews',params={'plan_id':interrupted['id']}))
            if history['reports'][0]['state']=='ready':break
            time.sleep(.1)
        assert history['reports'][0]['state']=='ready'
        assert history==check(native.get(base+'/reviews',params={'plan_id':interrupted['id']}))['data']
        bob=check(native.post('/api/v1/auth/login',json={'appId':'lighttick','account':'bob@example.com','password':'Password1234','clientType':'app'}))['data']
        native.headers['Authorization']='Bearer '+bob['accessToken']
        assert check(native.get(base))['data']['plans']==[]
        print(json.dumps({'consistent':True,'plans':len(n['plans']),'records':records['total'],'aggregate':year['progress'],'review_count':history['review_total'],'ai_history':history['reports'][0]['state'],'second_account_isolated':True},ensure_ascii=False))

if __name__=='__main__':main()
