"""Cross-module discovery against disposable real PostgreSQL schemas."""
import json
import os
import tempfile
from unittest.mock import patch
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
import search_api
import timeline_api

import db
from platform_schema import TABLES
from study_notes import TABLES as NOTES
from search_service import SearchService
from timeline_service import TimelineService
from test_legacy_cloud_schema import PostgreSQLFixture


class SearchTimelineTests(PostgreSQLFixture):
    def setUp(self):
        super().setUp()
        self.search = SearchService(Path('/unused'))
        self.timeline = TimelineService(Path('/unused'))
        with db.connect() as c:
            c.executescript(TABLES + NOTES)
            c.executescript('''CREATE TABLE reflection_entries(id TEXT PRIMARY KEY,data TEXT);
                CREATE TABLE study_learning_records(module_id TEXT,filename TEXT,lesson_no INTEGER,topic TEXT,summary_text TEXT,completed_at TEXT);
                CREATE TABLE copilot_learning_records(id SERIAL,module_id TEXT,round_id INTEGER,lesson_no INTEGER,summary_text TEXT,review_answers TEXT,completed_at TEXT,archived INTEGER);
                CREATE TABLE reading_records(id TEXT PRIMARY KEY,data TEXT);
                CREATE TABLE cloud_documents(path TEXT PRIMARY KEY,data TEXT);
                CREATE TABLE action_plans(id TEXT PRIMARY KEY,data TEXT,revision INTEGER);
                CREATE TABLE action_executions(id TEXT PRIMARY KEY,plan_id TEXT,state TEXT,data TEXT);''')
            c.execute("INSERT INTO decisions(date,title,reason) VALUES ('2026-10-21','回归核对决策','保留证据')")
            c.execute("INSERT INTO custom_records(data) VALUES (?)", (json.dumps({'date':'2026-10-21','title':'回归核对旧记录'}),))
            c.execute("INSERT INTO study_learning_records VALUES ('yingyu','one.md',1,'回归核对英文','完成笔记','2026-10-21T23:59:59+08:00')")
            c.execute("INSERT INTO copilot_learning_records(module_id,round_id,lesson_no,summary_text,review_answers,completed_at,archived) VALUES ('renzhi',1,2,'回归核对认知','{}','2026-10-21T12:00:00+08:00',0)")
            c.execute("INSERT INTO course_study_notes VALUES ('biaoda','two.md',?,1,'request','hash','2026-10-21T12:00:00+08:00')", (json.dumps({'notes':'回归核对暂存笔记','answers':{'q':'完整答案'}}),))
            self.put(c,'reflection_entries','ref-test',{'record_date':'2026-10-21','raw_text':'回归核对日常记录','prompt_kind':'自由记录'})
            self.put(c,'reading_records','article-test',{'type':'article','title':'回归核对文章','saved_at':'2026-10-21T20:00:00+08:00','full_content':'原文'})
            c.execute('INSERT INTO cloud_documents VALUES (?,?)', ('认知阅读/阅读笔记/article-test.md',json.dumps({'storage':'database','text':'回归核对阅读笔记','updated_at':'2026-10-21T20:00:00+08:00'})))
            c.execute('INSERT INTO action_plans VALUES (?,?,1)', ('plan-test',json.dumps({'title':'回归核对行动','start_date':'2026-10-21'})))
            c.execute('INSERT INTO action_executions VALUES (?,?,?,?)', ('exec-test','plan-test','completed',json.dumps({'business_date':'2026-10-21','note':'回归核对执行'})))

    def put(self,c,table,key,data):
        c.execute(f'INSERT INTO {table} VALUES (?,?)',(key,json.dumps({'id':key,**data})))

    def test_all_matches_single_module_and_returns_actual_saved_notes(self):
        all_results=self.search.search('回归核对',start_date='2026-10-21',end_date='2026-10-21')
        decision=self.search.search('回归核对',module_types=['decision'])
        self.assertTrue(decision['results'])
        self.assertTrue({r['id'] for r in decision['results']} <= {r['id'] for r in all_results['results']})
        sources={r['source'] for r in all_results['results']}
        self.assertTrue({'custom_records','study_learning_records','copilot_learning_records','course_study_notes','reflection_entries','reading_records','cloud_documents','action_plans','action_executions'} <= sources)
        note=next(r for r in all_results['results'] if r['source']=='course_study_notes')
        self.assertIn('暂存笔记',note['summary'])
        self.assertEqual(note['target'],{'kind':'study','module':'biaoda','course':'two.md'})
        self.assertEqual(all_results['warnings'],[])

    def test_visible_course_identifiers_are_searchable_and_feedback_opens_original_lesson(self):
        with db.connect() as c:
            c.executescript('CREATE TABLE learning_feedback(plan_id TEXT,lesson_no INTEGER,data TEXT,PRIMARY KEY(plan_id,lesson_no));')
            c.execute('INSERT INTO learning_feedback VALUES (?,?,?)', ('precise-plan-identifier',17,json.dumps({'comment':'真实课程反馈','date':'2026-10-21T15:00:00+08:00'})))
        note=self.search.search('two.md',module_types=['learning'])
        self.assertEqual(note['total_count'],1)
        self.assertEqual(note['results'][0]['source'],'course_study_notes')
        self.assertEqual(self.search.search('biaoda')['results'][0]['source'],'course_study_notes')
        self.assertEqual(self.search.search('one.md')['results'][0]['source'],'study_learning_records')
        self.assertEqual(note['results'][0]['target'],{'kind':'study','module':'biaoda','course':'two.md'})
        feedback=self.search.search('precise-plan-identifier',module_types=['learning'])
        self.assertEqual(feedback['total_count'],1)
        self.assertEqual(feedback['results'][0]['source'],'learning_feedback')
        self.assertTrue(any(r['source']=='learning_feedback' for r in self.search.search('17')['results']))
        self.assertEqual(feedback['results'][0]['target'],{'kind':'study','module':'plan','course':'precise-plan-identifier/17'})
        self.assertEqual(self.search.search('真实课程反馈')['results'][0]['target'],feedback['results'][0]['target'])
        timeline=self.timeline.get_timeline('2026-10-21','2026-10-21',['learning'])
        self.assertTrue(any(r['source']=='learning_feedback' and r['target']==feedback['results'][0]['target'] for r in timeline['records']))

    def test_timeline_includes_end_date_and_has_consistent_counts(self):
        result=self.timeline.get_timeline('2026-10-21','2026-10-21')
        self.assertGreaterEqual(result['total_count'],10)
        self.assertTrue(all(r['date']=='2026-10-21' for r in result['records']))
        stats=self.timeline.get_timeline_stats()
        self.assertEqual(stats['total_records'],result['total_count'])
        self.assertEqual(stats['active_days'],1)
        self.assertTrue(stats['by_module']['learning']['count']>0)

    def test_source_failure_is_reported_without_poisoning_later_queries(self):
        with db.connect() as c:c.execute('ALTER TABLE custom_records RENAME COLUMN data TO broken_data')
        for result in (self.search.search('回归核对'),self.timeline.get_timeline('2026-10-21','2026-10-21')):
            rows=result.get('results',result.get('records'))
            self.assertTrue(any(r['module']=='decision' for r in rows))
            self.assertTrue(result['partial'])
            self.assertTrue(any(w['source']=='custom_records' for w in result['warnings']))

    def test_local_reading_note_is_searchable_and_opens_its_article(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'LEARN_ROOT':root, 'PLAN_CONTENT_BACKEND':'local'}):
            notes = Path(root) / '认知阅读' / '阅读笔记'
            notes.mkdir(parents=True)
            (notes / 'article-test.md').write_text('独立本地阅读心得',encoding='utf-8')
            result=self.search.search('独立本地阅读心得')
            self.assertEqual(result['total_count'],1)
            self.assertEqual(result['results'][0]['target'],{'kind':'article','id':'article-test'})

    def test_api_filters_and_stats_use_the_same_record_sources(self):
        app=FastAPI()
        search_api.register(app,Path('/unused'))
        timeline_api.register(app,Path('/unused'))
        with TestClient(app) as client:
            result=client.get('/api/search',params={'q':'回归核对','types':'reflection'})
            self.assertEqual(result.status_code,200)
            self.assertEqual(result.json()['results'][0]['source'],'reflection_entries')
            query={'types':'decision','start_date':'2026-10-21','end_date':'2026-10-21'}
            timeline=client.get('/api/timeline',params=query).json()
            stats=client.get('/api/timeline/stats',params=query).json()
            self.assertEqual(timeline['total_count'],1)
            self.assertEqual(stats['total_records'],timeline['total_count'])
            self.assertEqual(stats['active_days'],1)
            self.assertEqual(stats['by_module']['learning']['count'],0)

    def test_literal_wildcards_and_counts_are_not_silently_capped(self):
        with db.connect() as c:
            for index in range(205):
                c.execute("INSERT INTO insights(date,insight) VALUES ('2026-10-21',?)",(f'分页范围{index}',))
            c.execute("INSERT INTO insights(date,insight) VALUES ('2026-10-21','literal%_value')")
        result=self.search.search('分页范围',module_types=['insight'],page=11,page_size=20)
        self.assertEqual(result['total_count'],205)
        self.assertEqual(len(result['results']),5)
        self.assertEqual(self.search.search('%_')['total_count'],1)
        self.assertEqual(self.timeline.get_timeline('2026-10-21','2026-10-21',['insight'])['total_count'],206)

    def test_small_pages_and_stats_do_not_materialize_every_matching_record(self):
        import search_service
        with db.connect() as c:
            for index in range(205):
                c.execute("INSERT INTO insights(date,insight) VALUES ('2026-10-21',?)",(f'有界读取{index}',))
        with patch('search_service.normalize',wraps=search_service.normalize) as normalize:
            result=self.search.search('有界读取',module_types=['insight'],page_size=5)
            self.assertEqual(result['total_count'],205)
            self.assertEqual(len(result['results']),5)
            self.assertLessEqual(normalize.call_count,5,'Only the requested page candidates should cross the database boundary')
        with patch('search_service.normalize',wraps=search_service.normalize) as normalize:
            stats=self.timeline.get_timeline_stats('2026-10-21','2026-10-21',['insight'])
            self.assertEqual(stats['total_records'],205)
            self.assertEqual(stats['active_days'],1)
            self.assertEqual(normalize.call_count,0,'Stats must aggregate in PostgreSQL without loading record bodies')

    def test_sql_dates_and_excerpt_projection_avoid_loading_unrelated_large_bodies(self):
        import search_service
        huge='大正文' * 500000
        with db.connect() as c:
            self.put(c,'reading_records','article-huge',{'type':'article','title':'大字段命中','saved_at':'2026-10-20T17:00:00Z','full_content':huge})
            self.put(c,'reading_records','article-outside',{'type':'article','title':'大字段命中但超出日期','saved_at':'2026-10-21T17:00:00Z','full_content':huge})
        with patch('search_service.normalize',wraps=search_service.normalize) as normalize:
            result=self.search.search('大字段命中',module_types=['learning'],start_date='2026-10-21',end_date='2026-10-21')
            self.assertEqual(result['total_count'],1)
            self.assertEqual(result['results'][0]['id'],'article-huge')
            self.assertEqual(result['results'][0]['date'],'2026-10-21')
            self.assertEqual(normalize.call_count,1,'Out-of-range rows must be filtered in PostgreSQL')
            self.assertLess(len(str(normalize.call_args.args[2])),5000,'Full reading bodies must not cross the cursor boundary')

    def test_cross_source_pages_keep_exact_totals_after_candidate_limits(self):
        with db.connect() as c:
            for index in range(35):
                c.execute("INSERT INTO insights(date,insight) VALUES ('2026-10-21',?)",(f'跨来源分页{index}',))
                c.execute("INSERT INTO decisions(date,title,reason) VALUES ('2026-10-20',?,'跨来源分页')",(f'跨来源分页{index}',))
        full=self.search.search('跨来源分页',page_size=100)
        self.assertEqual(full['total_count'],70)
        for page in (1,7,10,11):
            result=self.search.search('跨来源分页',page=page,page_size=7)
            self.assertEqual(result['total_count'],70)
            self.assertEqual(result['results'],full['results'][(page-1)*7:page*7])
        stats=self.timeline.get_timeline_stats('2026-10-20','2026-10-21',['insight','decision'])
        self.assertEqual(stats['total_records'],71)
        self.assertEqual(stats['active_days'],2)

    def test_unrelated_documents_are_excluded_before_json_parsing(self):
        with db.connect() as c:
            c.execute('INSERT INTO cloud_documents VALUES (?,?)',('每日认知与通识学习/每日课程/huge.md','not valid note JSON'))
            c.execute('INSERT INTO cloud_documents VALUES (?,?)',('认知阅读/文章资料/article-test/原文.md','not valid note JSON'))
        result=self.search.search('回归核对阅读笔记',module_types=['learning'])
        self.assertEqual(result['total_count'],1)
        self.assertEqual(result['results'][0]['source'],'cloud_documents')
        self.assertFalse(result['partial'],'Unrelated document bodies must not be parsed or fetched')

    def test_no_duplicates_archived_records_or_internal_reading_jobs(self):
        with db.connect() as c:
            self.put(c,'reflection_entries','archived',{'record_date':'2026-10-21','raw_text':'回归核对已归档','archived_at':'now'})
            self.put(c,'reading_records','job-test',{'type':'job','title':'回归核对内部任务','created_at':'2026-10-21'})
        result=self.search.search('回归核对',page_size=100)
        keys=[r['source']+':'+str(r['id']) for r in result['results']]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertNotIn('archived',{r['id'] for r in result['results']})
        self.assertNotIn('job-test',{r['id'] for r in result['results']})
        self.assertEqual(self.search.search('回归核对',page=2,page_size=3)['results'],result['results'][3:6])
