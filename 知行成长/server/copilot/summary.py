"""AI-powered course summary generation."""
import json
from .core import now, encoded, fail, MODULE, TZ
from .generation import config, event


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
