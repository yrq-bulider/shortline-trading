# CI 每日盘后自动运行

## Windows 任务计划程序配置

### 前提
- Python 3.10+ 已安装并在 PATH 上
- 项目路径：C:\Users\yan\Desktop\短线操作
- pip install baostock akshare pandas numpy 已安装

### 配置步骤

1. 打开"任务计划程序"(Win+R => taskschd.msc)
2. 右侧操作 => 创建任务
3. 常规标签：名称"短线操作每日扫描"，勾选最高权限
4. 触发器标签 => 新建：每天 15:30
5. 操作标签 => 新建：启动 cmd.exe
   参数：/c "C:\Users\yan\Desktop\短线操作\短线工具箱\ci_daily_run.bat"
6. 条件标签：取消电源相关勾选项
7. 设置标签：失败时重试3次

### 手动测试

```powershell
C:\Users\yan\Desktop\短线操作\短线工具箱\ci_daily_run.bat
```

### 输出产物

| 文件 | 路径 |
|------|------|
| 扫描结果 | 短线工具箱/历史/YYYYMMDD/筛选结果.csv |
| 回测报告 | 短线工具箱/历史/YYYYMMDD/回测报告.json |
| 归因报告 | 短线工具箱/历史/YYYYMMDD/归因报告.json |
| 操作计划 | 短线工具箱/历史/YYYYMMDD/MM.DD短线操作.md |
| 运行日志 | 短线工具箱/历史/ci_YYYYMMDD.log |

### 注意事项

- 脚本只 git pull 不 git push(需用户在 chat 里点头)
- 股票池过滤(00/60开头)已在每日扫描中生效
- 资金流降级用 amount 均量比 + hsgt/lhb 代理
- 如 akshare 接口变更需手动更新 wrapper
