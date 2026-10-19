"""A disclosed, bounded catalogue, not an unrestricted web search engine."""
import re
import html
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from html.parser import HTMLParser
import httpx

TOPICS={
 '认知':['cognition','thinking','reason','evidence','decision','思考','认知','判断','学习'],
 '科技':['technolog','science','artificial intelligence','robot','space','physics','科技','科学','人工智能','航天','物理','医疗技术'],
 '经济学':['econom','market','money','growth','inequality','经济','金融','市场','贫富','增长'],
 '社会学':['social','societ','culture','institution','community','社会','文化','制度','人口'],
 '心理':['psycholog','emotion','mind','mental','memory','心理','情绪','记忆','幸福'],
 '成长':['learn','work','career','habit','productiv','成长','职业','工作','习惯','教育','学习']}

# 默认来源推荐
DEFAULT_FEEDS=[
 {'id':'aeon','name':'Aeon','url':'https://aeon.co/feed.rss','language':'en','domains':['aeon.co'],'topics':['认知','社会学','心理'],'custom':False},
 {'id':'behavioral','name':'Behavioral Scientist','url':'https://behavioralscientist.org/feed/','language':'en','domains':['behavioralscientist.org'],'topics':['认知','心理','社会学'],'custom':False},
 {'id':'ftchinese','name':'FT中文网','url':'https://www.ftchinese.com/rss/feed','language':'zh','domains':['www.ftchinese.com','ftchinese.com'],'topics':['经济学','社会学'],'custom':False},
 {'id':'ruanyifeng','name':'阮一峰的网络日志','url':'https://www.ruanyifeng.com/blog/atom.xml','language':'zh','domains':['www.ruanyifeng.com','ruanyifeng.com'],'topics':['科技','成长','社会学'],'custom':False},
 {'id':'owid','name':'Our World in Data','url':'https://ourworldindata.org/atom.xml','language':'en','domains':['ourworldindata.org'],'topics':['经济学','社会学','认知'],'custom':False},
 {'id':'36kr','name':'36氪','url':'https://36kr.com/feed','language':'zh','domains':['36kr.com'],'topics':['科技','成长','经济学'],'custom':False},
 {'id':'sspai','name':'少数派','url':'https://sspai.com/feed','language':'zh','domains':['sspai.com'],'topics':['科技','成长','认知'],'custom':False},
 {'id':'hbr','name':'Harvard Business Review','url':'https://hbr.org/feed','language':'en','domains':['hbr.org'],'topics':['成长','认知','心理'],'custom':False},
 {'id':'psychology_today','name':'Psychology Today','url':'https://www.psychologytoday.com/us/blog/rss','language':'en','domains':['psychologytoday.com'],'topics':['心理','认知'],'custom':False},
 {'id':'waitbutwhy','name':'Wait But Why','url':'https://waitbutwhy.com/feed','language':'en','domains':['waitbutwhy.com'],'topics':['认知','成长','心理'],'custom':False},
]

# 向后兼容
FEEDS = DEFAULT_FEEDS
CLASSICS=[
 {'title':'The short history of global living conditions and why it matters that we know it','zh_title':'用长期数据理解全球生活条件的变化','url':'https://ourworldindata.org/a-history-of-global-living-conditions','author':'Max Roser','source':'Our World in Data','language':'en','published_at':'2016-12-14','topics':['经济学','社会学','认知'],'summary':'文章用贫困、教育、健康等长期指标讨论生活条件的变化，提醒读者区分即时新闻与长期趋势。阅读时应检查指标定义、历史估计的不确定性，以及总体改善是否掩盖群体差异。','access':'编辑核验原始页面；原创中文摘要，页面2024年有修订'},
 {'title':'Maps of Bounded Rationality: A Perspective on Intuitive Judgment and Choice','zh_title':'有限理性：直觉判断与选择','url':'https://www.nobelprize.org/uploads/2018/06/kahnemann-lecture.pdf','author':'Daniel Kahneman','source':'Nobel Foundation','language':'en','published_at':'2002-12-08','topics':['认知','心理','经济学'],'summary':'这份诺贝尔讲座回顾判断启发式、风险选择和框架效应，讨论快速直觉与审慎思考。适合带着具体决策例子阅读；经典研究框架不等于对每个个体行为的诊断或预测。','access':'核验官方讲座摘要；未逐页核验PDF'},
 {'title':'Why do women live longer than men?','zh_title':'如何用多因素解释寿命差异','url':'https://ourworldindata.org/why-do-women-live-longer-than-men','author':'Saloni Dattani / Lucas Rodés-Guirao','source':'Our World in Data','language':'en','published_at':'2023-11-27','topics':['社会学','认知'],'summary':'文章按年龄、地区和历史变化分析平均寿命差异，展示多种因素如何共同影响结果。可练习区分总体统计与个体情况，以及描述性数据与因果解释。此阅读不用于个人医疗判断。','access':'编辑核验原始页面；原创中文摘要'},
 {'title':'科技爱好者周刊：第82期','zh_title':'从职业环境与协作中理解成长','url':'https://ruanyifeng.com/blog/2019/11/weekly-issue-82.html','author':'阮一峰','source':'阮一峰的网络日志','language':'zh','published_at':'2019-11-15','topics':['成长'],'summary':'本期周刊包含职业成长的讨论：工作环境和协作对象可能改变一个人的学习机会。可结合自己的经历审视这个观点；文章包含个人观察与推荐链接，不代表普遍适用的因果结论。','access':'核验原始页面检索摘要；非全文核验'},
]

class Plain(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)

def plain(value,limit=600):
    parser=Plain();parser.feed(value or '')
    return re.sub(r'\s+',' ',html.unescape(' '.join(parser.parts))).strip()[:limit]

def canonical(url,domains):
    try:
        p=urlsplit(url)
        if p.scheme not in ('https','http') or p.hostname not in domains or p.username or p.password or p.port not in (None,443,80):return None
        query=urlencode([(k,v) for k,v in parse_qsl(p.query) if not k.lower().startswith(('utm_','fbclid','gclid'))])
        return urlunsplit(('https',p.hostname,p.path or '/',query,''))
    except ValueError:return None

def identify(url):return 'article-'+hashlib.sha256(url.encode()).hexdigest()[:20]

def parse_date(value):
    try:
        try:dt=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:dt=parsedate_to_datetime(value)
        if dt.tzinfo is None:dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=8))).date().isoformat()
    except (ValueError,TypeError,AttributeError,OverflowError):return None

def parse_feed(raw,source):
    if len(raw)>2_000_000 or b'\x00' in raw or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('不支持的订阅格式或内容过大')
    tree=ET.fromstring(raw);rows=[]
    for item in tree.iter():
        if item.tag.split('}')[-1] not in ('item','entry'):continue
        fields={};links=[]
        for child in item:
            k=child.tag.split('}')[-1];value=''.join(child.itertext())
            if k=='link':
                if child.attrib.get('rel','alternate')=='alternate':links.append(child.attrib.get('href') or value)
            elif k=='author':fields[k]=value
            elif k not in fields:fields[k]=value
        url=next((u for x in links if (u:=canonical(x.strip(),source['domains']))),None)
        title=plain(fields.get('title',''),300)
        if not url or not title:continue
        summary=plain(fields.get('summary') or fields.get('description') or fields.get('encoded') or fields.get('content') or '',500)
        rows.append({'id':identify(url),'title':title,'url':url,'source':source['name'],'language':source['language'],
            'author':plain(fields.get('creator') or fields.get('author') or '未提供',200),
            'published_at':parse_date(fields.get('published') or fields.get('pubDate') or fields.get('updated') or ''),
            'summary':summary,'topics':source['topics'],'access':'仅核验来源订阅与摘要；未核验原文全文', 'category':'recent'})
        if len(rows)>=80:break
    return rows

async def fetch_feed(source):
    async with httpx.AsyncClient(timeout=httpx.Timeout(20,connect=8),follow_redirects=False) as client:
        async with client.stream('GET',source['url'],headers={'User-Agent':'ZhixingReading/1.0 (personal RSS reader)'}) as response:
            response.raise_for_status();chunks=[];size=0
            async for chunk in response.aiter_bytes():
                size+=len(chunk)
                if size>2_000_000:raise ValueError('订阅内容过大')
                chunks.append(chunk)
    return parse_feed(b''.join(chunks),source)

def matches(article,prefs):
    if article['language'] not in prefs['languages']:return False
    hay=(article['title']+' '+article['summary']).lower()
    topics=prefs['topics'];matched=[t for t in topics if any(word in hay for word in TOPICS[t])]
    if not matched and not (article.get('category')=='classic' and set(topics)&set(article['topics'])):return False
    query=prefs.get('query','').strip().lower()
    if query:
        words=re.findall(r'[a-z0-9]+|[\u4e00-\u9fff]+',query)
        # Topic names expand bilingually; other words remain a transparent literal search.
        groups=[TOPICS.get(w,[w]) for w in words]
        if not groups or not any(any(w in hay for w in group) for group in groups):return False
    return True

# Keep the existing import contract for collection, URL import and readers.
from .content import fetch_article_content

def choose(candidates,prefs,seen,today,seed=None,history=(),selected=()):
    cutoff=(datetime.fromisoformat(today)-timedelta(days=30)).date().isoformat()
    eligible={}
    for a in candidates:
        if a['id'] in seen or not matches(a,prefs):continue
        if a['category']=='recent' and not (a.get('published_at') and cutoff<=a['published_at']<=today):continue
        if prefs['mode']!='mixed' and a['category']!=prefs['mode']:continue
        eligible.setdefault(a['id'],a)
    # Stable per job, but different jobs/days explore different eligible articles.
    seed=str(seed or today)
    shuffle={aid:int(hashlib.sha256((seed+':'+aid).encode()).hexdigest(),16) for aid in eligible}
    rows=sorted(eligible.values(),key=lambda a:shuffle[a['id']])
    signals={t:[] for t in prefs['topics']}
    for a in sorted(history,key=lambda a:a.get('saved_at',''),reverse=True)[:60]:
        value={'insightful':1,'neutral':0,'not_for_me':-1}.get((a.get('feedback') or {}).get('value'))
        if value is None:continue
        for t in set(a.get('topics',[])) & signals.keys():signals[t].append(value)
    weights={t:sum(v)/(len(v)+3) for t,v in signals.items()}
    result=list(selected);used={a['source'] for a in result};covered=set().union(*(set(a.get('topics',[])) for a in result));interests=set(prefs['topics'])
    categories=['recent']*max(0,prefs['count']-1)+['classic'] if prefs['mode']=='mixed' else [prefs['mode']]*prefs['count']
    for a in result:
        if a['category'] in categories:categories.remove(a['category'])
        elif categories:categories.pop()
    for category in categories:
        options=[a for a in rows if a['category']==category and a['id'] not in {x['id'] for x in result}]
        if not options and prefs['mode']=='mixed':
            options=[a for a in rows if a['id'] not in {x['id'] for x in result}]
        options.sort(key=lambda a:(-len((interests & set(a.get('topics',[])))-covered),
                                   0 if len(result)%3==2 else -sum(weights.get(t,0) for t in set(a.get('topics',[])))/max(1,len(a.get('topics',[]))),
                                   a['source'] in used, a['language'] in {x['language'] for x in result},shuffle[a['id']]))
        if options:
            result.append(options[0]);used.add(options[0]['source']);covered.update(options[0].get('topics',[]))
    return result
