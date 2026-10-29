"""Summary omission is not source incompleteness; quotes remain literal."""
import json
import unittest
from datetime import date,timedelta

from investments.market_evidence import daily_excerpt,quotation_hints
from investments.market_import import import_history
from investments.analysis import InvestmentAnalysis,validate_report
from investments.store import InvestmentStore
from investments.providers import indicators
from test_legacy_cloud_schema import PostgreSQLFixture


class MarketEvidenceTests(unittest.TestCase):
    def test_excerpt_explains_counts_without_claiming_source_completeness(self):
        bars=[{'close':str(i)} for i in range(35)]
        excerpt=daily_excerpt(bars);scope=excerpt['summary_scope']
        self.assertEqual(len(bars),35);self.assertEqual(excerpt['bars'],bars[-20:])
        self.assertEqual(excerpt['omitted_bar_count'],15)
        self.assertEqual((scope['stored_bar_count'],scope['included_bar_count'],scope['indicator_input_bar_count']),(35,20,35))
        self.assertEqual(scope['source_completeness'],'not_independently_verified')
        windows=scope['indicator_windows']
        self.assertTrue(all(windows[k]['summary_record_count_sufficient'] for k in ('ma5','ma20','volume_ratio_5','atr14')))
        self.assertFalse(windows['record_return_std20']['summary_record_count_sufficient'])
        self.assertTrue(windows['record_return_std20']['stored_record_count_sufficient'])
        short=daily_excerpt(bars[:2]);self.assertEqual(short['omitted_bar_count'],0)
        self.assertEqual(short['summary_scope']['source_completeness'],'not_independently_verified')
        self.assertFalse(short['summary_scope']['indicator_windows']['ma5']['stored_record_count_sufficient'])

    def test_short_hints_preserve_precision_basis_and_latest_close(self):
        content='{"bars":[{"close":"11.20"},{"close": "11.2"}],"indicators":{"ma5":"11.336","volume_ratio_5":"1.24774852542489596465915147108305432291277414629991224185349"},"price_basis":"unadjusted_user_declared"}'
        hints=quotation_hints(content);by_field={h['field']:h['quote'] for h in hints}
        self.assertEqual(by_field['close'],'"close": "11.2"')
        self.assertIn('unadjusted_user_declared',by_field['price_basis'])
        self.assertIn('1.24774852542489596465915147108305432291277414629991224185349',by_field['volume_ratio_5'])
        self.assertTrue(all(h['quote'] in content for h in hints));self.assertLessEqual(len(hints),6)
        for other in ('普通公告原文','[]','{"close":"11.2"}',None):self.assertEqual(quotation_hints(other),[])

    def test_equal_numeric_value_still_does_not_allow_changed_literal_quotes(self):
        content='{"bars":[{"close":"11.2"}],"indicators":{"ma5":"11.336"}}'
        snapshot={'kind':'research','plans':[],'decision_at':'2026-10-28T09:00:00+08:00',
            'evidence':[{'id':'e','content':content}]}
        report={'summary':'仅摘录原文','counterarguments':['来源尚需核对'],
            'facts':[{'evidence_id':'e','quote':'"close":"11.2"'}]}
        validate_report(json.dumps(report),snapshot)
        report['facts'][0]['quote']='"close":"11.20"'
        with self.assertRaisesRegex(ValueError,'事实引用'):validate_report(json.dumps(report),snapshot)


class MarketEvidencePreviewTests(PostgreSQLFixture):
    def test_real_import_path_preserves_all_bars_indicators_and_preview_hints(self):
        store=InvestmentStore();store.initialize()
        instrument=store.create('instruments',{'kind':'etf','market':'SZSE','code':'159001','name':'合成ETF'},'instrument')
        days=[];day=date(2026,8,3)
        while len(days)<35:
            if day.weekday()<5:days.append(day.isoformat())
            day+=timedelta(days=1)
        text='date,open,high,low,close,volume,amount\n'+''.join(d+',11.2,12,11,11.2,100,1120\n' for d in days)
        result=import_history(store,instrument['id'],text,'lots','cny','合成完整输入',True,'csv')
        original=store.get('research',result['evidence_id']);content=json.loads(original['content'])
        self.assertEqual(len(result['bars']),35);self.assertEqual(len(content['bars']),20)
        self.assertEqual(content['summary_scope']['indicator_input_bar_count'],35)
        self.assertEqual(content['indicators']['return_sample_count'],20)
        from_summary=indicators(content['bars'])
        for field in ('ma5','ma20','volume_ratio_5','atr14'):
            self.assertEqual(from_summary[field],content['indicators'][field])
        self.assertIsNone(from_summary['record_return_std20'])
        self.assertIsNotNone(content['indicators']['record_return_std20'])
        preview=InvestmentAnalysis(store).preview({'kind':'research','instrument_id':instrument['id'],
            'question':'区分摘要省略与数据缺失','evidence_ids':[result['evidence_id']],
            'decision_at':'2030-01-01T15:00:00+08:00'})
        selected=preview['snapshot']['evidence'][0]
        self.assertEqual(selected['content'],original['content'])
        self.assertTrue(selected['quotation_hints'])
        self.assertTrue(all(h['quote'] in selected['content'] for h in selected['quotation_hints']))
        self.assertEqual(store.get('research',result['evidence_id']),original)
        self.assertEqual(preview['snapshot']['prompt_version'],'investment-v5')
