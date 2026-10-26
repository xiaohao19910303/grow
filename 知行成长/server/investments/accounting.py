"""Deterministic long-only moving-average accounting; unknown costs stay unknown."""
from decimal import Decimal, localcontext

D = Decimal
ZERO = D('0')


def number(value):
    if value is None:
        return None
    return format(value, 'f').rstrip('0').rstrip('.') if '.' in format(value, 'f') else format(value, 'f')


def reconcile(opening_cash, cash_events, fills, *, opening_positions=(), marks=None):
    with localcontext() as context:
        context.prec = 60
        return _reconcile(opening_cash, cash_events, fills, opening_positions, marks or {})


def _reconcile(opening_cash, cash_events, fills, opening_positions, marks):
    positions = {}
    cash = D(opening_cash)
    fees_complete = True

    def position(instrument_id):
        return positions.setdefault(instrument_id, {'quantity': ZERO, 'cost': ZERO,
            'realized': ZERO, 'fees_complete': True})

    for opening in opening_positions:
        item = position(opening['instrument_id'])
        item['quantity'] += D(opening['quantity'])
        cost = opening.get('cost')
        item['cost'] = None if cost is None or item['cost'] is None else item['cost'] + D(cost)
    for event in cash_events:
        amount = D(event['amount'])
        cash += -amount if event['kind'] in ('withdrawal', 'fee') else amount
    for fill in fills:
        item = position(fill['instrument_id'])
        quantity, price = D(fill['quantity']), D(fill['price'])
        if quantity <= 0 or price <= 0:
            raise ValueError('成交价格和数量必须大于零。')
        known = fill.get('fee') is not None and fill.get('tax') is not None
        fees_complete = fees_complete and known
        item['fees_complete'] = item['fees_complete'] and known
        costs = D(fill.get('fee') or '0') + D(fill.get('tax') or '0')
        value = quantity * price
        if fill['side'] == 'buy':
            cash -= value + costs
            # A fully closed unknown-cost opening position must not contaminate a new cycle.
            if item['quantity'] == 0:
                item['cost'] = ZERO
            if item['cost'] is not None:
                item['cost'] += value + costs
            item['quantity'] += quantity
        elif fill['side'] == 'sell':
            if quantity > item['quantity']:
                raise ValueError('卖出数量超过已核对持仓；请先补齐期初或成交。')
            allocated = None if item['cost'] is None else item['cost'] * quantity / item['quantity']
            cash += value - costs
            item['realized'] = None if allocated is None or item['realized'] is None else item['realized'] + value - costs - allocated
            item['quantity'] -= quantity
            if item['cost'] is not None:
                item['cost'] -= allocated
            if item['quantity'] == 0:
                item['cost'] = ZERO
        else:
            raise ValueError('不支持的成交方向。')
    output = []
    realized = ZERO
    equity = cash
    for instrument_id, item in positions.items():
        realized = None if realized is None or item['realized'] is None else realized + item['realized']
        mark = marks.get(instrument_id)
        value = ZERO if item['quantity'] == 0 else (D(mark) * item['quantity'] if mark is not None else None)
        equity = None if equity is None or value is None else equity + value
        unrealized = None if value is None or item['cost'] is None else value - item['cost']
        output.append({'instrument_id': instrument_id, **{k:number(item[k]) for k in ('quantity','cost','realized')},
            'fees_complete': item['fees_complete'], 'market_value': number(value),
            'unrealized': number(unrealized) if item['fees_complete'] else None,
            'mark': mark})
    return {'cash': number(cash), 'cash_verified': fees_complete,
            'positions': output, 'realized': number(realized), 'fees_complete': fees_complete,
            'net_realized': number(realized) if fees_complete else None,
            'equity': number(equity) if fees_complete else None,
            'warnings': ([] if fees_complete else ['费用未齐，现金和成本为暂估，不能作为精确净收益。'])}
