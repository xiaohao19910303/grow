"""Shared, bounded checks for observable investment-plan conditions."""
import re
import unicodedata


class UnverifiableCondition(ValueError):
    """A fixed, public-safe explanation for a rejected plan condition."""


CONDITION_DESCRIPTION=('写明可由公开资料、行情或本人记录核对的对象、判据与时点；'
    '缺资料时等待补齐，不要求确认非公开信息不存在、猜测他人意图或保证未来收益。')

_NONPUBLIC=re.compile(
    r'(?:尚未|还未|未经|未曾|未|不)(?:对外)?(?:公开|披露|公告)(?:的)?(?:重大)?(?:事项|信息|事件|风险|消息|利空)|'
    r'非公开(?:的)?(?:重大)?(?:事项|信息|事件|风险|消息)|内幕|内部消息|'
    r'(?:undisclosed|nonpublic|unpublished|insider)(?:material)?(?:information|events?|matters?|risks?|news)')
_INTENT=re.compile(r'(?:主力|庄家)(?:的)?(?:真实)?(?:意图|意愿|动机|目的|计划)|机构(?:的)?真实(?:意图|动机)')
_GUARANTEE=re.compile(
    r'(?<!不)(?<!无法)(?<!不能)(?<!不得)(?:保证|确保)(?:未来|后续|持续|稳定)?(?:绝不|不会|一定|必然|必定)?'
    r'(?:盈利|获利|赚钱|上涨|不亏损|不亏|零风险|无风险)|稳赚不赔|绝对无风险|'
    r'(?<!not)(?:guaranteed?(?:profit|returns)|riskfree(?:return|profit))|'
    r'(?:确认|确保|保证|证明)(?:不存在|没有|无)(?:任何|一切|所有)?(?:重大)?(?:风险|利空|负面消息)|'
    r'(?:排除|消除)(?:全部|所有|一切)(?:潜在)?风险')


def validate_condition_text(value):
    # 可核验计划条件：报告终稿、采用、草稿编辑和确认复用；不改写原话或历史事实。
    if not isinstance(value,str):
        raise UnverifiableCondition('请使用文字说明可核对的触发和失效条件。')
    text=unicodedata.normalize('NFKC',value).casefold()
    text=''.join(c for c in text if not c.isspace() and unicodedata.category(c)!='Cf' and c not in '-‐‑')
    if _NONPUBLIC.search(text):
        raise UnverifiableCondition('条件不能要求确认或排除非公开事项；请改为核对指定时点的已公开公告，缺项保持未知并等待。')
    if _INTENT.search(text):
        raise UnverifiableCondition('条件不能要求核实主力或机构真实意图；请改用可观察行情或已公开披露记录。')
    if _GUARANTEE.search(text):
        raise UnverifiableCondition('条件不能保证未来盈利或零风险；请改为可核对的触发、失效与停止研究标准。')
    return value


def validate_conditions(trigger,invalidation):
    validate_condition_text(trigger)
    validate_condition_text(invalidation)
