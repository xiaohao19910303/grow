"""Grow references expose neutral metadata; copying review text is never implicit."""
import json
from datetime import date
import db
from copilot.core import digest, encoded, fail, now


def overview(store,as_of):
    with db.connect() as c:
        rows=c.execute("""SELECT kind,count(*) FROM investment_objects WHERE
            (kind IN ('trade-plans','period-plans') AND data::jsonb->>'state'='draft') OR
            (kind='ledger-notices' AND data::jsonb->>'status'='open') OR
            (kind='reviews' AND data::jsonb->>'date'=?) GROUP BY kind""",(as_of,)).fetchall()
        return {'date':as_of,'counts':{r[0]:r[1] for r in rows},'metadata_only':True,'scope':'仅计数；不含金额、证券名称或私人正文'}


def create_action(store,review_id,payload,key):
    from action_plans import connection, create_in, NewPlan
    fingerprint=digest(encoded({'review_action':review_id,'data':payload}))
    # Respect the existing single-writer and LightTick takeover guard.
    with connection(True) as c:
        store.lock(c)
        replay=store.replay(c,key,fingerprint)
        if replay is not None:return replay
        review=store._get(c,'reviews',review_id)
        if review['version']!=payload['source_version']:fail('version_conflict','复盘已更新，请重新核对。')
        action_key='investment-action-'+fingerprint
        body=NewPlan(key=action_key,title=payload['title'],period='day',start_date=date.fromisoformat(payload['date']),
            end_date=date.fromisoformat(payload['date']),completion_mode='check',reminder=False,
            reason='来自本人投资复盘；私有详情请回到投资工作台核对。')
        result=create_in(c,body);action=result['plans'][0]
        reference_id='action-reference-'+digest(encoded([review_id,action['id']]))
        row=c.execute("SELECT data FROM investment_objects WHERE id=? AND kind='action-references'",(reference_id,)).fetchone()
        if row:reference=json.loads(row[0])
        else:
            stamp=now();reference={'id':reference_id,'version':1,'created_at':stamp,'updated_at':stamp,
                'account_id':review['account_id'],'review_id':review_id,'source_version':review['version'],
                'source_hash':digest(encoded(review)),'action_id':action['id'],'disclosure':'user_title_and_date_only'}
            store.save(c,'action-references',reference,fresh=True)
        store.remember(c,key,fingerprint,reference);return reference


def references(store,review_id):
    with db.connect() as c:
        store._get(c,'reviews',review_id)
        rows=c.execute("SELECT data FROM investment_objects WHERE kind='action-references' AND data::jsonb->>'review_id'=?",(review_id,))
        records=[json.loads(r[0]) for r in rows]
        has_actions=c.execute("SELECT to_regclass('action_plans')").fetchone()[0]
        return {'items':[{**r,'availability':'available' if has_actions and c.execute('SELECT 1 FROM action_plans WHERE id=?',(r['action_id'],)).fetchone() else 'unavailable'} for r in records]}


def private_search(store,account_id,query,page=1):
    """Explicit workbench search may read private text; general discovery never does."""
    if not query.strip() or len(query)>200:fail('invalid_search','请填写200字以内的关键词。',422)
    with db.connect() as c:
        store._get(c,'accounts',account_id)
        where="""o.kind IN ('reviews','trade-plans','period-plans','dossiers','principles','research','policies')
            AND o.data::jsonb->>'account_id'=? AND strpos(lower(o.data || COALESCE(i.data,'')),lower(?))>0"""
        source=" FROM investment_objects o LEFT JOIN investment_objects i ON i.id=o.data::jsonb->>'instrument_id' AND i.kind='instruments' WHERE "+where
        args=(account_id,query)
        total=c.execute('SELECT count(*)'+source,args).fetchone()[0]
        rows=c.execute('SELECT o.kind,o.data'+source+' ORDER BY o.updated_at DESC,o.id DESC LIMIT 50 OFFSET ?',(*args,(page-1)*50))
        items=[]
        for row in rows:
            record=json.loads(row[1]);items.append({'id':record['id'],'resource':row[0],'account_id':account_id,
                'title':record.get('title') or ('投资复盘' if row[0]=='reviews' else '资金政策'),
                'summary':str(record.get('text') or record.get('rationale') or record.get('content') or record.get('purpose') or record.get('focus') or record.get('rule') or record.get('technical_case') or '')[:200],
                'updated_at':record['updated_at']})
        return {'items':items,'total':total,'page':page,'page_size':50,'scope':'本人显式查询的当前投资账户；不会自动发送给AI或通用成长报告。'}
