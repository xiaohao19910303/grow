"""Boundary contracts: exact decimal strings, private IDs and explicit timezones."""
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, HttpUrl, model_validator


def decimal_input(value):
    if not isinstance(value, (str, Decimal)):
        raise ValueError('金额、价格和数量请使用十进制字符串。')
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('无效十进制数。') from exc
    if not result.is_finite():
        raise ValueError('不支持非有限数。')
    return result


Money = Annotated[Decimal, BeforeValidator(decimal_input), Field(ge=0, max_digits=28, decimal_places=10)]
Positive = Annotated[Decimal, BeforeValidator(decimal_input), Field(gt=0, max_digits=28, decimal_places=10)]
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')]
Text = Annotated[str, Field(max_length=12000)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class OpeningPosition(Contract):
    instrument_id: Identifier
    quantity: Positive
    cost: Money | None = None


class AccountInput(Contract):
    name: str = Field(min_length=1, max_length=100)
    currency: Literal['CNY'] = 'CNY'
    baseline_date: date
    opening_cash: Money
    opening_positions: list[OpeningPosition] = Field(default_factory=list, max_length=100)


class InstrumentInput(Contract):
    code: str = Field(min_length=1, max_length=32, pattern=r'^[A-Za-z0-9_.-]+$')
    market: Literal['SSE', 'SZSE', 'BSE', 'FUND']
    kind: Literal['stock', 'etf', 'fund']
    name: str = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def compatible_market(self):
        if (self.market=='FUND') != (self.kind=='fund'):
            raise ValueError('场外基金请选择对应市场。')
        self.code=self.code.upper()
        suffixes={'SSE':'.SH','SZSE':'.SZ','BSE':'.BJ','FUND':'.OF'}
        for market,suffix in suffixes.items():
            if self.code.endswith(suffix):
                if market!=self.market:
                    raise ValueError('证券代码后缀与市场不一致。')
                self.code=self.code[:-len(suffix)]
        return self


class FillInput(Contract):
    account_id: Identifier
    instrument_id: Identifier
    side: Literal['buy', 'sell']
    price: Positive
    quantity: Positive
    fee: Money | None = None
    tax: Money | None = None
    executed_at: AwareDatetime
    plan_id: Identifier | None = None
    external_id: str | None = Field(default=None, max_length=200)
    source: Literal['manual', 'csv', 'broker', 'fund_confirmation'] = 'manual'
    note: Text = ''


class CashInput(Contract):
    account_id: Identifier
    kind: Literal['deposit', 'withdrawal', 'dividend', 'interest', 'fee', 'fund_receivable_hold', 'fund_receivable_release']
    amount: Positive
    occurred_at: AwareDatetime
    note: Text = ''


class PolicyInput(Contract):
    account_id: Identifier
    period_start: date
    period_end: date
    purpose: Text = ''
    liquidity_needs: Text = ''
    loss_capacity: Text = ''
    planned_deposit: Money = Decimal('0')
    planned_withdrawal: Money = Decimal('0')
    cash_buffer: Money | None = None
    trade_risk_budget: Money | None = None
    max_exposure: Money | None = None
    loss_review_line: Money | None = None
    pause_new_risk: bool = False


class StrategyInput(Contract):
    title: str = Field(min_length=1, max_length=200)
    environment: Text = ''
    entry_conditions: Text = ''
    exclusions: Text = ''
    exit_conditions: Text = ''
    validation_scope: Text = ''


class PlanInput(Contract):
    account_id: Identifier
    instrument_id: Identifier
    strategy_id: Identifier | None = None
    title: str = Field(min_length=1, max_length=200)
    rationale: Text = ''
    entry_conditions: Text = ''
    invalidation: Text = ''
    contrary_evidence: Text = ''
    valid_until: AwareDatetime
    holding_sessions: int | None = Field(default=None, ge=1, le=1000)
    risk_budget: Money | None = None
    entry_price: Positive | None = None
    invalidation_price: Positive | None = None
    fee_budget: Money | None = None


class ReviewInput(Contract):
    account_id: Identifier
    campaign_id: Identifier | None = None
    period: Literal['day', 'campaign', 'week', 'month', 'quarter', 'event', 'thought'] = 'day'
    date: date
    text: str = Field(min_length=1, max_length=12000)
    judgment: Text = ''
    execution: Text = ''
    next_experiment: Text = ''
    no_trade: bool = False


class VersionCommand(Contract):
    version: int = Field(ge=1)


class StateCommand(VersionCommand):
    state: Literal['confirmed', 'declined', 'expired', 'cancelled', 'paused']


class ResearchInput(Contract):
    instrument_id: Identifier | None = None
    account_id: Identifier | None = None
    title: str = Field(min_length=1,max_length=200)
    content: str = Field(min_length=1,max_length=12000)
    source_url: HttpUrl | None = None
    locator: str = Field(max_length=1000,default='')
    available_at: AwareDatetime
    period_end: date | None = None
    contrary_evidence: Text = ''


class AnalysisInput(Contract):
    kind: Literal['capital','research','plan','review']
    account_id: Identifier | None = None
    instrument_id: Identifier | None = None
    question: str = Field(min_length=1,max_length=4000)
    evidence_ids: list[Identifier] = Field(default_factory=list,max_length=30)
    plan_ids: list[Identifier] = Field(default_factory=list,max_length=10)
    review_ids: list[Identifier] = Field(default_factory=list,max_length=10)
    include_amounts: bool = False
    decision_at: AwareDatetime


class FundOrderInput(Contract):
    account_id: Identifier
    instrument_id: Identifier
    side: Literal['subscription','redemption']
    applied_at: AwareDatetime
    amount: Positive | None = None
    quantity: Positive | None = None
    note: Text = ''


class FundConfirmation(Contract):
    price: Positive
    quantity: Positive
    fee: Money
    tax: Money
    confirmed_at: AwareDatetime
    nav_date: date


RESOURCE_MODELS = {'accounts': AccountInput, 'instruments': InstrumentInput,
                   'fills': FillInput, 'cash-events': CashInput, 'policies': PolicyInput,
                   'strategies': StrategyInput, 'trade-plans': PlanInput, 'reviews': ReviewInput,
                   'research': ResearchInput, 'fund-orders': FundOrderInput}
