import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from scorer import (safe_score, composite_score, dynamic_position_pct)


def test_composite_normal():
    s = composite_score(80, 70, 60, 90)
    assert s == round(80*0.25 + 70*0.20 + 60*0.20 + 90*0.35, 1)


def test_composite_all_zero():
    assert composite_score(0, 0, 0, 0) == 0.0


def test_composite_all_max():
    assert composite_score(100, 100, 100, 100) == 100.0


def test_composite_custom_weights():
    t0 = (0.50, 0.15, 0.25, 0.10)
    s = composite_score(80, 70, 60, 90, weights=t0)
    assert s == round(80*0.50 + 70*0.15 + 60*0.25 + 90*0.10, 1)


def test_composite_single_dim():
    s = composite_score(80, 70, 60, 90, weights=(1.0, 0, 0, 0))
    assert s == 80.0


def test_position_high():
    assert dynamic_position_pct(90, '稳健') == 40


def test_position_mid():
    assert dynamic_position_pct(80, '稳健') == 25
    assert dynamic_position_pct(75, '稳健') == 25


def test_position_low():
    assert dynamic_position_pct(70, '稳健') == 15


def test_position_min():
    assert dynamic_position_pct(50, '稳健') == 0


def test_position_cap():
    assert dynamic_position_pct(90, '谨慎') == 28
    assert dynamic_position_pct(90, '观望') == 16
    assert dynamic_position_pct(90, '未知') == 28


def test_safe_normal():
    @safe_score('测试')
    def good_fn(x):
        return (x, 'ok')
    assert good_fn(42) == (42, 'ok')


def test_safe_exception():
    @safe_score('测试')
    def bad_fn(x):
        raise ValueError('bad')
    r = bad_fn(1)
    assert r[0] == 50
    assert '测试:ValueError' in r[1]


def test_safe_extras():
    @safe_score('测试', extras=([],))
    def bad_fn(x):
        raise RuntimeError('boom')
    r = bad_fn(1)
    assert r == (50, '测试:RuntimeError', [])


def test_safe_multi_extras():
    @safe_score('多值', extras=('a', 123))
    def bad_fn(x):
        raise TypeError('类型错')
    assert bad_fn(1) == (50, '多值:TypeError', 'a', 123)
