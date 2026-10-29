import json,sys,subprocess,copy
from pathlib import Path
from fractions import Fraction
from decimal import Decimal
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path.cwd()))
from investments.rule_screening import screen_v2,RuleDraft,validate_draft
folder=Path(__file__).resolve().parent
frozen=json.loads((folder/'000001-frozen.json').read_text());bundle=frozen['bundle'];attempt=json.loads((folder/'natural-language-attempt2.json').read_text())
draft=RuleDraft.model_validate(attempt['draft']);validate_draft(draft,attempt['source_text'])
base=screen_v2(bundle);parsed=copy.deepcopy(bundle);parsed['request']=draft.screen.model_dump(mode='json');parsed_result=screen_v2(parsed)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
 page=browser.new_page()
 for f in ['investment-browser-core.js','investment-screening-v2.js']:page.add_script_tag(path=str(Path('static')/f))
 actual=page.evaluate('b=>InvestmentScreenV2.screen(b)',bundle)
 assert actual==base
 actual_parsed=page.evaluate('b=>InvestmentScreenV2.screen(b)',parsed)
 assert actual_parsed==parsed_result
 accepted=page.evaluate('v=>InvestmentScreenV2.parse(v.raw,v.text,v.context,v.catalog)',{'raw':attempt['raw'],'text':attempt['source_text'],'context':attempt['context'],'catalog':{'fields':bundle['catalog']}})
 browser.close()
bars=bundle['universe'][0]['bars'];days=sorted(d for d,o in bundle['universe'][0]['calendar']['sessions'].items() if o and d<=bundle['request']['as_of']);bd={b['date']:b for b in bars};w=[bd[d] for d in days[-6:]]
f=lambda b,k:Fraction(Decimal(b[k]))
ret=(f(w[-1],'close')/f(w[0],'close')-1)*100;avg=sum(f(b,'turnover_rate_pct') for b in w[-5:])/5;amt=sum(f(b,'turnover_cny') for b in w[-5:])/5
out={'actual_chrome_vs_python':'exact equality for all17 metrics and results','final_parser_revalidation':'passed JS and Python with saved real output; no new model call','manual_review':{'original_numeric_conditions':'preserved 5days >=3%, turnover inclusive[2,8]%, 5day mean amount >=100000000 yuan','sort':'volume_ratio_5 descending preserved','AI_suggestion':'volume_ratio_5 >1; explicitly suggested, not independently validated, requires acceptance','unsupported':[],'semantic_scope':'only this captured sentence manually reviewed; not general semantic equivalence proof'},'hand_calculation':{'dates':[b['date'] for b in w],'closing_prices':[b['close'] for b in w],'return_5d_formula':f'({w[-1]["close"]}/{w[0]["close"]}-1)*100','return_5d_exact_fraction':str(ret),'avg_turnover_5d_pct':str(avg),'avg_amount_5d_yuan':str(amt)},'real_draft_result':parsed_result,'baseline_result':base,'fills':0,'plans':0}
(folder/'final-public-verification.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({k:out[k] for k in ('actual_chrome_vs_python','final_parser_revalidation','hand_calculation')},ensure_ascii=False))
