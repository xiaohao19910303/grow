"""Read-only projections: decode complete JSON values, never repair partial output."""
import json
from datetime import datetime
from copilot.core import now
from copilot.generation import SEPARATOR


def complete_items(raw, array_keys):
    decoder = json.JSONDecoder()
    result = {k: [] for k in array_keys}
    pos = 0
    def space(i):
        while i < len(raw) and raw[i].isspace(): i += 1
        return i
    try:
        pos = space(pos)
        if raw[pos] != '{': return result
        pos += 1
        while True:
            pos = space(pos)
            key, pos = decoder.raw_decode(raw, pos)
            if not isinstance(key, str): return result
            pos = space(pos)
            if raw[pos] != ':': return result
            pos = space(pos + 1)
            if key in result:
                if raw[pos] != '[': return result
                pos = space(pos + 1)
                while raw[pos] != ']':
                    value, end = decoder.raw_decode(raw, pos)
                    if not isinstance(value, dict): return result
                    result[key].append(value)
                    pos = space(end)
                    if raw[pos] == ']': break
                    if raw[pos] != ',': return result
                    pos = space(pos + 1)
                pos += 1
            else:
                _, pos = decoder.raw_decode(raw, pos)
            pos = space(pos)
            if raw[pos] != ',': return result
            pos += 1
    except (ValueError, IndexError):
        return result


def preview(attempt):
    raw = attempt.get('raw', '')
    if attempt.get('operation') == 'refine':
        scope = attempt['context']['scope']
        if scope['mode'] == 'selected':
            key = 'updates' if attempt['kind'] == 'plan' else 'sections'
            return {'type': 'changes', 'items': complete_items(raw, [key])[key]}
    if attempt['kind'] == 'plan':
        items = complete_items(raw, ['stages', 'lessons'])
        stages = [x for x in items['stages'] if all(isinstance(x.get(k), str) and x[k].strip() for k in ('title','goal'))]
        lessons = [x for x in items['lessons'] if type(x.get('number')) is int and x['number'] > 0
                   and all(isinstance(x.get(k), str) and x[k].strip() for k in ('topic','goal','exercise','assessment'))
                   and type(x.get('stage')) is int and x['stage'] > 0
                   and type(x.get('minutes')) is int and 5 <= x['minutes'] <= 120
                   and x.get('kind') in ('lesson','review') and isinstance(x.get('requires'),list)
                   and all(type(n) is int and 0 < n < x['number'] for n in x['requires'])]
        return {'type': 'plan', 'stages': stages, 'lessons': lessons}
    # Hide a delimiter prefix arriving across packets. Pending text is rendered as textContent.
    body, sep, notes = raw.partition(SEPARATOR)
    if not sep:
        for n in range(min(len(body), len(SEPARATOR)-1), 0, -1):
            if body.endswith(SEPARATOR[:n]): body=body[:-n];break
    return {'type': 'course', 'content': body, 'sources': notes}


def projection(a, after_revision=None):
    current = now()
    def seconds(start, end):
        try: return max(0, int((datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()))
        except (ValueError, TypeError): return 0
    revision = a.get('revision', len(a.get('raw','')))
    result = {k:a.get(k) for k in ('id','kind','state','model','cost','error','draft_id','created_at','finished_at',
                                  'first_content_at','last_content_at','deadline_at','started_at')}
    result.update(server_time=current, revision=revision, phase=a.get('phase', a['state']),
                  elapsed_seconds=seconds(a['created_at'], a.get('finished_at') or current),
                  idle_seconds=seconds(a.get('last_content_at') or a['created_at'], a.get('finished_at') or current),
                  unchanged=after_revision == revision)
    result['actions']={'cancel':a['state'] in ('queued','generating'),'preview':bool(a.get('draft_id'))}
    if after_revision != revision: result['preview']=preview(a)
    return result
