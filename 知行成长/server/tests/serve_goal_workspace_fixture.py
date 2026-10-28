"""Isolated workspace browser fixture with deterministic AI responses."""
from datetime import timedelta
from unittest.mock import patch
from serve_daily_arrangements_fixture import main
import action_plans as a


def customize(app,fixture):
    async def generate(snapshot,cfg):
        today=snapshot['today']
        return [dict(ref='stage',title='完成第一篇结构化文章',entity_type='plan',period='custom',start_date=today,end_date=str(__import__('datetime').date.fromisoformat(today)+timedelta(days=6)),selected=True),dict(ref='step',parent_ref='stage',title='写出三个核心论点',entity_type='action',period='day',start_date=None,end_date=None,estimated_minutes=20,selected=True)]
    model=patch('goal_planning.generate_items',side_effect=generate);model.start();fixture.addCleanup(model.stop)


if __name__=='__main__':main(customize)
