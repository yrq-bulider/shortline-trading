"""
daily.py - 每日一键操作
====================
完成所有日常工作：扫描 + 回测 + HTML报告 + 操作计划
用法：
  python daily.py            # 默认T+1+仅扫描（快，6/8早上开盘前用这个）
  python daily.py --full     # 扫描+回测+HTML（慢，盘后回顾用）
  python daily.py --t0       # 切到T+0模式（ETF/可转债）
  python daily.py --no-dedup # 关闭智能去重
  python daily.py --days 30  # 回测看最近30天
  python daily.py --backtest # 只跑回测

性能提示：
  - scan模式 ~1-2分钟（推荐盘前用）
  - full模式 ~3-5分钟（含回测拉历史+HTML生成）
  - 数据源：baostock（技术面） + akshare（业绩/资金/消息）
  - 没装akshare会降级只用技术面，准确率会下降
"""
import subprocess
import sys
import os
import argparse

# 路径：与 daily.py 同级
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
V1_SCRIPT = os.path.join(SCRIPT_DIR, "筛选明日股票_v1.py")

# 中文字符串（Windows console兼容）
def _print(s):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('gbk', errors='replace').decode('gbk'))

def main():
    p = argparse.ArgumentParser(description='每日短线操作')
    p.add_argument('--t0', action='store_true', help='T+0模式（ETF/可转债）')
    p.add_argument('--no-dedup', action='store_true', help='关闭去重')
    p.add_argument('--days', type=int, default=20, help='回测天数')
    p.add_argument('--backtest', action='store_true', help='只跑回测')
    p.add_argument('--full', action='store_true', help='扫描+回测+HTML（盘后用）')
    args = p.parse_args()

    # 构造传给v1的参数
    v1_args = [sys.executable, V1_SCRIPT]
    if args.t0:
        v1_args += ['--trading-mode', 'T+0']
    if args.no_dedup:
        v1_args += ['--no-dedup']
    v1_args += ['--days', str(args.days)]
    # 模式优先级：--backtest > --full > 默认scan
    if args.backtest:
        mode = 'backtest'
        v1_args += ['--mode', 'backtest']
    elif args.full:
        mode = 'full'
        v1_args += ['--mode', 'full']
    else:
        mode = 'scan'
        v1_args += ['--mode', 'scan']  # 默认scan：仅扫描+生成markdown（最快）

    _print("=" * 60)
    _print(f"  启动 v1.0 扫描器")
    _print(f"  模式: {'T+0' if args.t0 else 'T+1'}")
    _print(f"  工作: {'仅回测' if mode=='backtest' else '扫描+回测+HTML' if mode=='full' else '仅扫描（推荐，6/8早盘用）'}")
    _print(f"  回测天数: {args.days}")
    _print("=" * 60)

    # 切到工作目录
    os.chdir(SCRIPT_DIR)
    # 调用v1
    ret = subprocess.run(v1_args, env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    if ret.returncode != 0:
        _print(f"\n[错误] v1 退出码 {ret.returncode}")
        return ret.returncode

    _print("\n" + "=" * 60)
    _print("  ✅ daily.py 任务完成")
    _print("=" * 60)
    if mode == 'scan':
        _print("  下一步：")
        _print("    1. 打开 '短线操作md文档/M.D短线操作.md' 看操作计划")
        _print("    2. 次日盘后可跑 'python daily.py --full' 看胜率+HTML")
    elif mode == 'full':
        _print("  下一步：")
        _print("    1. 打开 '短线工具箱/今日报告.html' 看可视化报告")
        _print("    2. 打开 '短线操作md文档/M.D短线操作.md' 看操作计划")
        _print("    3. 跑 'python daily.py --backtest --days 30' 看长期胜率")
    return 0

if __name__ == '__main__':
    sys.exit(main())
