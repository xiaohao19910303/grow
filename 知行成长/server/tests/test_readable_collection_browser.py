"""The discovery page replaces missing bodies and saves a readable article."""
import asyncio
import os
import re
import unittest
from unittest.mock import patch
import test_reading_site_browser as browsers
from test_legacy_cloud_api import CloudHTTPFixture
from reading.sources import identify
from reading.store import DEFAULT

BODY='## A complete readable argument\n\n'+('Evidence helps readers compare explanations, check their assumptions and understand the limits of a claim.\n\n'*12)

@unittest.skipUnless(os.getenv('RUN_LEGACY_BROWSER')=='1','Opt in to Chromium acceptance')
class ReadableCollectionBrowser(CloudHTTPFixture):
    browser=browsers.ReadingSiteBrowser.browser

    def test_collection_replaces_failed_body_then_saves_and_reads_without_another_fetch(self):
        self.reader.save_preferences({**DEFAULT,'count':2,'mode':'recent','topics':['认知'],'languages':['en']})
        rows=[]
        for i in range(6):
            url=f'https://example.org/readable-{i}'
            rows.append({'id':identify(url),'title':f'Thinking with evidence {i}','url':url,'source':f'Source {i}',
                         'language':'en','author':'Writer','published_at':'2026-10-17','summary':'Evidence and thinking. '*10,
                         'topics':['认知'],'category':'recent','access':'RSS'})
        async def feed(source):return rows
        calls=[]
        async def fetch(url):
            attempt=len(calls);calls.append(url);await asyncio.sleep(.01)
            return None if attempt==0 else BODY
        self.service.fetcher=feed
        with patch('reading.service.fetch_article_content',fetch),self.browser() as (page,base):
            page.goto(base);page.evaluate('enterReading()')
            page.get_by_role('button',name='帮我找文章',exact=True).click()
            page.get_by_role('button',name=re.compile(r'^(开始搜集并预览|开始查找)$')).click()
            page.get_by_role('button',name='保存选中的文章与资料',exact=True).wait_for()
            self.assertEqual(page.locator('.reading-card').count(),2)
            self.assertGreater(len(calls),2);self.assertEqual(len(calls),len(set(calls)))
            self.assertNotIn('未取得正文',page.locator('#view-reading').inner_text())
            page.get_by_text('本站预览正文',exact=True).first.click()
            page.get_by_role('heading',name='A complete readable argument',exact=True).wait_for()
            page.get_by_role('button',name='保存选中的文章与资料',exact=True).click()
            page.get_by_role('button',name='本站阅读',exact=True).first.click()
            page.get_by_text('已保存的正文，可直接在本站阅读。',exact=True).wait_for()
            self.assertEqual(len(calls),3)
            page.get_by_role('button',name='本人确认读完',exact=True).click()
            page.get_by_role('button',name='改为尚未读完',exact=True).wait_for()
            page.reload();page.get_by_text('已保存的正文，可直接在本站阅读。',exact=True).wait_for()
            self.assertEqual(len(calls),3)
            self.assertEqual(self.reader.note(self.aid)['text'],'PRIVATE READING NOTE')
            for a in self.reader.articles():
                if a['id']!=self.aid:self.assertEqual(a['content_version'],2)
