import functools

# Mode configs
MODE_CONFIGS = {
    'T+1': {
        'weights': (0.25, 0.20, 0.20, 0.35),
        'risk': {
            'NEXT_DAY_STOP_LOSS_PCT': -0.05,
            'NEXT_DAY_TAKE_PROFIT_PCT': 0.05,
            'FORCE_CLEAR_PCT': -0.03,
            'OPEN_GAP_HIGH': 0.02,
            'OPEN_GAP_LOW': -0.02,
            'HOLD_PERIOD_DESC': '次日9:25-9:45分情景应对',
        },
    },
    'T+0': {
        'weights': (0.50, 0.15, 0.25, 0.10),
        'risk': {
            'INTRADAY_STOP_LOSS_PCT': -0.015,
            'INTRADAY_TAKE_PROFIT_PCT': 0.02,
            'FORCE_CLEAR_TIME': '14:30',
            'TRAILING_STOP_PCT': 0.01,
            'HOLD_PERIOD_DESC': '当日9:30-14:30分时波段',
        },
    },
}

# Weight globals (init_mode_config sets these)
WEIGHT_TECH = 0.25
WEIGHT_EARN = 0.20
WEIGHT_FLOW = 0.20
WEIGHT_NEWS = 0.35


def init_mode_config(mode):
    cfg = MODE_CONFIGS[mode]
    global WEIGHT_TECH, WEIGHT_EARN, WEIGHT_FLOW, WEIGHT_NEWS
    WEIGHT_TECH, WEIGHT_EARN, WEIGHT_FLOW, WEIGHT_NEWS = cfg['weights']
    return cfg['risk']


# Position sizing
POSITION_TIERS = [(85, 40), (75, 25), (65, 15), (55, 10), (0, 0)]
MARKET_POSITION_CAP = {'积极': 1.0, '稳健': 1.0, '谨慎': 0.7, '观望': 0.4}


def safe_score(label, extras=()):
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                err = f'{label}:{type(e).__name__}'
                return (50, err) + tuple(extras)
        return wrap
    return deco


def composite_score(tech, earn, flow, news, weights=None):
    if weights is None:
        weights = (WEIGHT_TECH, WEIGHT_EARN, WEIGHT_FLOW, WEIGHT_NEWS)
    return round(tech * weights[0] + earn * weights[1]
                 + flow * weights[2] + news * weights[3], 1)


def dynamic_position_pct(score, market_level):
    base = next(pct for threshold, pct in POSITION_TIERS if score >= threshold)
    cap = MARKET_POSITION_CAP.get(market_level, 0.7)
    return round(base * cap)
