"""Explicit references to legacy estimates; never auto-create verified ledger facts."""
import json
import db
from copilot.core import digest, encoded, fail, now


def original(c,object_id):
    if not c.execute("SELECT to_regclass('stock_records')").fetchone()[0]:fail('not_found','旧记录不存在。',404)
    row=c.execute('SELECT data FROM stock_records WHERE id=?',(object_id,)).fetchone()
    if not row:fail('not_found','旧记录不存在。',404)
    return json.loads(row[0])


def list_legacy(store):
    with db.connect() as c:
        if not c.execute("SELECT to_regclass('stock_records')").fetchone()[0]:return {'items':[],'total':0}
        rows=c.execute('SELECT data FROM stock_records ORDER BY id LIMIT 100').fetchall()
        links=[json.loads(r[0]) for r in c.execute("SELECT data FROM investment_objects WHERE kind='legacy-links'")]
        return {'items':[{'original':json.loads(r[0]),'classification':'historical_estimate',
            'links':[l for l in links if l['legacy_id']==json.loads(r[0])['id']]} for r in rows],
            'total':c.execute('SELECT count(*) FROM stock_records').fetchone()[0],
            'limitations':['旧盈亏属于历史估算，不自动计入真实账本。列表最多100条，原入口保留全部历史。']}


def link_record(store,legacy_id,target_kind,target_id,note,reconciled,key):
    if target_kind not in ('fills','reviews') or not reconciled or not note.strip() or len(note)>2000:
        fail('reconciliation_required','请先核对成交或复盘，并填写关联说明。',422)
    fingerprint=digest(encoded({'legacy_id':legacy_id,'kind':target_kind,'id':target_id,'note':note}))
    with db.connect() as c:
        store.lock(c)
        replay=store.replay(c,key,fingerprint)
        if replay is not None:return replay
        source=original(c,legacy_id);target=store._get(c,target_kind,target_id)
        if target_kind=='fills':
            instrument=store._get(c,'instruments',target['instrument_id'])
            code=str(source.get('stock_code','')).upper().split('.')[0]
            if source.get('action')!=target['side'] or code!=instrument['code']:
                fail('legacy_mismatch','旧记录与成交的方向或证券代码不一致，请核对。',422)
        object_id='legacy-link-'+digest(encoded([legacy_id,target_kind,target_id]))
        existing=c.execute("SELECT data FROM investment_objects WHERE id=? AND kind='legacy-links'",(object_id,)).fetchone()
        if existing:
            result=json.loads(existing[0])
            if result['note']!=note:fail('conflict','该关联已保留不同核对说明，请查看原记录。')
        else:
            stamp=now();result={'id':object_id,'version':1,'created_at':stamp,'updated_at':stamp,'account_id':target['account_id'],
                'legacy_id':legacy_id,'target_kind':target_kind,'target_id':target_id,'target_version':target['version'],
                'source_snapshot':source,'source_hash':digest(encoded(source)),'note':note,'classification':'historical_estimate'}
            store.save(c,'legacy-links',result,fresh=True)
        store.remember(c,key,fingerprint,result);return result
