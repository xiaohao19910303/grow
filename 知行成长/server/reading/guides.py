"""A source-bounded Chinese reading guide; private reflection is never model input."""
import re

from copilot.core import digest, fail

SECTIONS=('中文导读','核心观点','证据与边界','英文阅读提示','联系实际')
INSTRUCTION=('用简体中文写一份方便直接阅读的导读。以 # 中文标题 开头，按顺序使用下列二级标题，标题不加其他文字：'
             '## 中文导读\n## 核心观点\n## 证据与边界\n## 英文阅读提示\n## 联系实际\n'
             '中文导读约150字说明问题和背景。核心观点写3至5个条目，讲清理由。'
             '证据与边界区分作者观点、证据和你的解释，说明不能推出什么。'
             '英文阅读提示给3至5个重要词语及中文释义、1个不超过20词的原文短句、中文解释及阅读方法。'
             '联系实际给一个可用于生活或工作的思考问题和一个小行动。'
             '只依据给定资料，不编造研究、数据、例子或引用；仅有摘要时明确说明。不要添加链接或HTML。')


def source_context(store,article):
    text=article.get('full_content') or ''
    if len(text.strip())<100 or text.strip()=='内容获取失败':
        file=store.path(f'认知阅读/文章资料/{article["id"]}/原文.md')
        text=file.read_text() if file.exists() else ''
    basis='saved_text'
    if len(text.strip())<100 or ('内容获取失败' in text and len(text)<300):
        text=article.get('summary') or '';basis='summary'
    if len(text.strip())<50:fail('invalid','现有内容太少，请先获取原文再生成导读。',422)
    text=text[:12000]
    return {'source_text':text,'source_basis':basis,'source_hash':digest(text)}


def validate_guide(text):
    title=re.search(r'^#\s+([^\n]{2,160})\s*$',text,re.M)
    if not title or not re.search(r'[\u4e00-\u9fff]',title[1]):fail('incomplete','中文导读缺少有效标题，原资料保留。')
    if len(re.findall(r'[\u4e00-\u9fff]',text))<80:fail('incomplete','中文导读不完整，原资料保留。')
    for section in SECTIONS:
        if not re.search(r'^##\s+'+section+r'\s*$',text,re.M):fail('incomplete','中文导读缺少'+section+'，原资料保留。')
    points=re.split(r'^##\s+核心观点\s*$',text,flags=re.M)[1].split('\n## ',1)[0]
    if len(re.findall(r'^\s*(?:[-*]|\d+[.、])\s*\S',points,re.M))<3:
        fail('incomplete','核心观点不足三条，请重新生成；原资料保留。')
    if re.search(r'<|javascript:|data:',text,re.I):fail('invalid','导读包含不支持的内容，原资料保留。')
    return title[1].strip()
