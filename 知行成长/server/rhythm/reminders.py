"""Foreground-only, local-day claim; shared with the existing reminder loop."""
from datetime import datetime
from zoneinfo import ZoneInfo
import action_plans as actions
from . import service


def claim(body):
    with actions.connection(True) as c:
        service.bootstrap(c)
        def work():
            prefs=service.preferences(c)['preferences'];local=actions.clock().astimezone(ZoneInfo(prefs['timezone']))
            if (not prefs['enabled'] or not prefs['reminder_enabled'] or not prefs['reminder_time']
                    or local.strftime('%H:%M') < prefs['reminder_time'] or not 8 <= local.hour < 22):
                return {'notify':False}
            day=str(local.date())
            # Existing task claims may use a plan's different timezone.
            for row in c.execute('SELECT claimed_at FROM action_reminder_claims'):
                if str(datetime.fromisoformat(row[0]).astimezone(ZoneInfo(prefs['timezone'])).date())==day:
                    return {'notify':False}
            row=c.execute('''INSERT INTO action_reminder_claims VALUES (?,?)
                ON CONFLICT(key) DO NOTHING RETURNING key''',('rhythm:'+day,actions.clock().isoformat())).fetchone()
            if row:
                from .events import emit
                emit(c,'rhythm_reminder_claimed','reminder:'+day,activity_date=day)
            return {'notify':bool(row)}
        return actions.operation(c,body.key,{'op':'rhythm.reminder',**body.model_dump(mode='json')},work)
