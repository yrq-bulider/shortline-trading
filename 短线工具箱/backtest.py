import numpy as np


def print_backtest_report(report):
    """打印回测报告"""
    if report is None:
        print("\n[回测] 暂无历史数据（需要先跑几次扫描积累评分）")
        return
    print("\n" + "=" * 70)
    print(f"  [回测] 4维评分体系回测报告（近{report['days_back']}天）")
    print("=" * 70)
    print(f"  样本数:        {report['total_trades']} 笔")
    print(f"  胜率:          {report['win_rate']}%")
    print(f"  平均收益:      {report['avg_return']}%")
    print(f"  平均跳空:      {report['avg_gap']:+.2f}%")
    print(f"  最大盈利:      +{report['max_win']}%")
    print(f"  最大亏损:      {report['max_loss']}%")
    print()
    print(f"  {'分桶':<10}{'样本':<6}{'胜率':<8}{'均收益':<10}{'最大盈利':<10}{'最大亏损':<10}")
    print("  " + "-" * 60)
    for bucket, s in report['bucket_stats'].items():
        print(f"  {bucket:<10}{s['count']:<6}{s['win_rate']}%{'':<3}{s['avg_ret']:+}%{'':<6}+{s['max_win']}%{'':<5}{s['max_loss']}%")
    print()
    if report['recommendations']:
        print("  [建议] 调参建议：")
        for r in report['recommendations']:
            print(f"     - {r}")
    print("=" * 70)

def dim_name_cn(d):
    return {'tech': '技术', 'earn': '业绩', 'flow': '资金', 'news': '消息'}.get(d, d)

def win_diff_cn(c):
    if c['win_diff'] > 0:
        return f"高分组胜率高{c['win_diff']}%"
    elif c['win_diff'] < 0:
        return f"高分组胜率反低{abs(c['win_diff'])}%（反向！）"
    else:
        return "无差异"

def print_attribution_report(attr):
    """打印归因报告"""
    if attr is None:
        print("\n[归因] 暂无回测数据")
        return
    if 'note' in attr:
        print(f"\n[归因] {attr['note']}")
        return

    print("\n" + "=" * 75)
    print(f"  [归因] 4维评分归因分析（样本{attr['sample_size']}笔）")
    print("=" * 75)

    # 相关性表
    print("\n  【1】子分 vs 次日收益 相关性 + 胜率区分度")
    print(f"  {'维度':<8}{'相关性':<10}{'高分组胜率':<14}{'低分组胜率':<14}{'胜率差':<10}{'评价':<10}")
    print("  " + "-" * 70)
    for dim in ['tech', 'earn', 'flow', 'news']:
        c = attr['correlations'][dim]
        print(f"  {dim_name_cn(dim):<8}{c['corr']:+.3f}    "
              f"{c['high_win']}%{'':<8}{c['low_win']}%{'':<8}"
              f"{c['win_diff']:+}%{'':<6}{c['practical']}")

    # 消融
    print("\n  【2】消融实验：4维 vs 单维策略（前1/3样本的胜率）")
    print(f"  {'策略':<14}{'样本':<6}{'胜率':<10}{'均收益':<10}")
    print("  " + "-" * 40)
    for name, s in attr['ablation'].items():
        marker = ' ←' if name == '4维综合' else ''
        print(f"  {name:<14}{s['chosen']:<6}{s['win_rate']}%{'':<5}{s['avg_ret']:+}%{marker}")

    # 建议
    print("\n  [建议] 自动调参建议：")
    for r in attr['recommendations']:
        print(f"     * {r}")
    print("=" * 75)


def print_dabang_pool_report(candidates, emotion_tier):
    """打印涨停板候选池 CLI 报告(v1.3)。candidates 来自 compute_dabang_candidates。"""
    print("\n" + "=" * 70)
    print(f"  [打板池] 首板小盘候选(主板 + 4维≥60 + 业绩雷区已过)")
    print(f"  [情绪] {emotion_tier['reason']} | 仓位乘数 {emotion_tier['multiplier']}")
    print("=" * 70)
    if not candidates:
        print("  (空)今日无符合条件的首板小盘 — 涨停池可能为空或全被过滤")
        print("=" * 70)
        return
    print(f"  {'代码':<8}{'名称':<10}{'综合':<6}{'价格':<8}{'流通(亿)':<10}{'封板':<8}{'炸板':<6}")
    print("  " + "-" * 60)
    for c in candidates:
        print(f"  {c['code']:<8}{c['name']:<10}{c['composite']:<6}"
              f"{c['price']:<8.2f}{(c['mv_yi'] or 0):<10.1f}"
              f"{c['feng_time']:<8}{c['zhaban']:<6}")
    print("=" * 70)

