"""AI-powered course summary generation."""
import json
import uuid
from .core import now, encoded, fail, MODULE, TZ
from .generation import config, event


ADVANCED_PROMPT_TEMPLATE = """你是一个个人学习助手，负责基于用户的学习反馈和总结，生成进阶课程内容。

【上一轮课程总结】
{summary_content}

【用户反馈分析】
掌握较好的领域：
{well_mastered_topics}

需要加强的领域：
{weak_topics}

用户希望深入的方向：
{next_directions}

【生成要求】
请生成8-12课进阶内容，遵循以下原则：
1. 重点覆盖用户需要加强的领域
2. 延伸到用户感兴趣的新方向
3. 课程难度可以适当提升，但要确保概念解释足够清晰
4. 每课包含：引导问题、核心概念、完整示范、练习、记忆提示
5. 课程之间要有递进关系，形成完整的学习脉络

【输出格式】
请逐课输出，每课使用以下结构：

## 第XXX课：[课程主题]

### 引导问题
（引发思考的问题）

### 核心概念
（关键知识点，清晰解释）

### 完整示范
（具体案例或应用场景）

### 练习
（巩固练习，附答案）

### 记忆提示
（帮助记忆的技巧）

---

请开始生成进阶课程。"""


SUMMARY_PROMPT_TEMPLATE = """你是一个个人学习助手。请基于以下信息，生成一份整门课程的复盘总结。

【课程信息】
模块名：{module_name}
已学课数：{completed_count}
课程列表：
{lesson_list}

【用户反馈】
{feedback_section}

【要求】
1. 总结这门课的核心知识框架（不是逐课复述，而是提炼脉络）
2. 基于用户的反馈，指出掌握得好的部分和需要加强的部分
3. 串联各课之间的关联
4. 给出进阶学习建议（参考用户填写的后续方向）
5. 用中文输出，语气像一个耐心的导师

【输出格式】
## 知识脉络
（核心框架）

## 掌握情况
（基于反馈的分析）

## 概念关联
（课与课之间的联系）

## 进阶建议
（后续学习方向）"""


class SummaryGenerator:
    def __init__(self, store, transport=None):
        self.store = store
        self.transport = transport

    def generate(self, module_id, round_id, scope='full_course'):
        lessons_data = self.store._scan()
        completed = [l for l in lessons_data['lessons'] if l['learning_state'] == 'completed']
        if not completed:
            fail('no_completed_lessons', '没有已完成的课程，无法生成总结。')

        feedback = self.store.list_feedback(module_id, round_id)
        feedback_by_lesson = {f['lesson_no']: f for f in feedback}

        lesson_list = '\n'.join(
            f"- 第{l['lesson_no']:03d}课：{l['topic']} ({l.get('completed_at', 'N/A')})"
            for l in completed
        )

        if feedback:
            fb_lines = []
            for l in completed:
                fb = feedback_by_lesson.get(l['lesson_no'])
                if fb:
                    fb_lines.append(f"- 第{l['lesson_no']:03d}课：掌握={fb['mastery_level']}, 收获={fb['value_rating']}/3, 感受={fb.get('feeling_tags', [])}, 收获={fb.get('key_learnings', '无')}, 方向={fb.get('next_direction', '无')}")
                else:
                    fb_lines.append(f"- 第{l['lesson_no']:03d}课：无反馈")
            feedback_section = '\n'.join(fb_lines)
        else:
            feedback_section = '暂无反馈数据'

        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            module_name=MODULE, completed_count=len(completed),
            lesson_list=lesson_list, feedback_section=feedback_section
        )

        messages = [
            {'role': 'system', 'content': '你是一个个人学习助手，擅长总结学习内容和生成复盘。'},
            {'role': 'user', 'content': prompt}
        ]

        cfg = config(self.store)
        if not cfg['key'] or not cfg['url']:
            fail('ai_not_configured', '请先在设置页面配置AI API。')

        full_content = ''
        if self.transport:
            stream = self.transport.stream(messages, cfg)
        else:
            from .transport import qwen_stream
            stream = qwen_stream(messages, cfg)

        async def _generate():
            nonlocal full_content
            try:
                async for packet in stream:
                    if packet.get('done'):
                        break
                    text = packet.get('text', '')
                    if text:
                        full_content += text
                        yield event('content', {'text': text})
                # Save to DB and file
                self.store.save_summary(module_id, round_id, scope, full_content, feedback)
                yield event('complete', {'content': full_content})
            except Exception as e:
                yield event('error', {'message': str(e)})

        return _generate()

    def generate_advanced(self, summary_content):
        """Generate advanced courses based on summary and feedback."""
        feedback = self.store.list_feedback()
        if not feedback:
            fail('no_feedback_data', '没有反馈数据，无法生成进阶课程。')

        # Analyze feedback to find well-mastered and weak topics
        well_mastered = []
        weak_topics = []
        next_directions = []
        for fb in feedback:
            if fb['mastery_level'] == 'fully_understood':
                well_mastered.append(f"第{fb['lesson_no']:03d}课")
            elif fb['mastery_level'] in ('partially_understood', 'not_understood'):
                weak_topics.append(f"第{fb['lesson_no']:03d}课")
            if fb.get('next_direction'):
                next_directions.append(fb['next_direction'])

        prompt = ADVANCED_PROMPT_TEMPLATE.format(
            summary_content=summary_content,
            well_mastered_topics='\n'.join(well_mastered) if well_mastered else '暂无',
            weak_topics='\n'.join(weak_topics) if weak_topics else '暂无',
            next_directions='\n'.join(set(next_directions)) if next_directions else '暂无明确方向'
        )

        messages = [
            {'role': 'system', 'content': '你是一个个人学习助手，擅长根据学生学习情况生成进阶课程内容。'},
            {'role': 'user', 'content': prompt}
        ]

        cfg = config(self.store)
        if not cfg['key'] or not cfg['url']:
            fail('ai_not_configured', '请先在设置页面配置AI API。')

        if self.transport:
            stream = self.transport.stream(messages, cfg)
        else:
            from .transport import qwen_stream
            stream = qwen_stream(messages, cfg)

        async def _generate_advanced():
            full_content = ''
            try:
                async for packet in stream:
                    if packet.get('done'):
                        break
                    text = packet.get('text', '')
                    if text:
                        full_content += text
                        yield event('content', {'text': text})
                # Save as a draft for user review
                draft_id = str(uuid.uuid4())
                lesson_no = self._get_next_lesson_no()
                data = {
                    'lesson_no': lesson_no,
                    'content': full_content,
                    'sources': '',
                    'raw': full_content,
                    'stream_completed': True,
                    'errors': [],
                    'plan_snapshot': None,
                    'source_snapshot': {'entries': []},
                    'record_hash': '',
                    'context': [],
                    'is_advanced': True
                }
                with self.store.lock():
                    with self.store.conn() as c:
                        c.execute('INSERT INTO copilot_drafts VALUES (?,?,1,?,?,?)',
                                  (draft_id, lesson_no, 'draft', encoded(data), now()))
                yield event('complete', {'content': full_content, 'draft_id': draft_id, 'lesson_no': lesson_no})
            except Exception as e:
                yield event('error', {'message': str(e)})

        return _generate_advanced()

    def _get_next_lesson_no(self):
        """Get the next available lesson number for advanced courses."""
        with self.store.conn() as c:
            row = c.execute('SELECT MAX(lesson_no) FROM copilot_drafts').fetchone()
            max_draft = row[0] if row and row[0] else 0
            row = c.execute('SELECT MAX(lesson_no) FROM copilot_learning_records WHERE module_id=\'renzhi\' AND round_id=1').fetchone()
            max_completed = row[0] if row and row[0] else 0
            return max(max_draft, max_completed) + 1
