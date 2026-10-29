"""Source references for the single Zook practice workspace; never a second writer."""
import hashlib
from fastapi import Request
from fastapi.responses import JSONResponse
import action_plans as actions
from action_link import identity, state
from mobile_library import table


def source(module_id=None, filename=None, plan_id=None, lesson_no=None):
    identity()
    with actions.connection() as c:
        link, _ = state(c)
        reading = table(c)
    if link.get('phase') != 'active' or link.get('snapshot_version') != 2:
        return {'available': False, 'source': None,
                'message': '课程学习可继续。创建跨端实践前，请在联动设置完成行动连接；不会另建本地行动副本。'}
    if plan_id and lesson_no:
        descriptor = {'plan_id': plan_id, 'lesson_no': lesson_no}
    elif module_id == 'yingyu' and filename:
        descriptor = {'module': module_id, 'filename': filename}
    else:
        return {'available': True, 'source': None, 'message': '这类来源尚未接入跨端实践，可先独立记录应用想法。'}
    lid = 'lesson-' + hashlib.sha256(actions.encoded(descriptor).encode()).hexdigest()[:40]
    course = next((item for item in reading.get('payload', {}).get('lessons', []) if item['id'] == lid), None)
    if not reading.get('enabled') or reading.get('binding_id') != link.get('binding_id') or not course:
        return {'available': True, 'source': None, 'message': '请允许课程阅读并等待来源同步；私人笔记授权与此分开。'}
    return {'available': True, 'source': {'kind': 'lesson', 'id': lid,
            'version': course['content_version'], 'title': course['title']},
            'observed_at': reading.get('payload', {}).get('observed_at')}


def register(app):
    @app.get('/api/learning-practices/source')
    def read_source(module_id: str | None = None, filename: str | None = None,
                    plan_id: str | None = None, lesson_no: int | None = None):
        if any(value and len(value) > 300 for value in (module_id, filename, plan_id)):
            actions.fail(422, '来源标识过长。')
        return JSONResponse(source(module_id, filename, plan_id, lesson_no), headers={'Cache-Control': 'no-store'})
