@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ============================================================
REM ci_daily_run.bat - 每日盘后自动扫描
REM Windows 任务计划程序: 每个交易日 15:30 自动运行
REM ============================================================

set "PROJECT_DIR=%~dp0.."
cd /d "%PROJECT_DIR%"

set "DATE_TAG=%date:~0,4%%date:~5,2%%date:~8,2%"
set "HISTORY_DIR=短线工具箱\历史\%DATE_TAG%"
set "LOG_FILE=短线工具箱\历史\ci_%DATE_TAG%.log"

echo [%date% %time%] === 每日扫描开始 === > "%LOG_FILE%" 2>&1

REM Step 1: 拉取最新代码
echo [%date% %time%] git pull ... >> "%LOG_FILE%" 2>&1
git pull >> "%LOG_FILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo [%date% %time%] ERROR: git pull failed >> "%LOG_FILE%" 2>&1
    exit /b 1
)

REM Step 2: 跑扫描 + 回测
echo [%date% %time%] daily.py --backtest --days 30 ... >> "%LOG_FILE%" 2>&1
python daily.py --backtest --days 30 >> "%LOG_FILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo [%date% %time%] ERROR: daily.py failed >> "%LOG_FILE%" 2>&1
    exit /b 1
)

REM Step 3: 复制当日产物到历史目录
echo [%date% %time%] 备份结果到 %HISTORY_DIR% ... >> "%LOG_FILE%" 2>&1
if not exist "%HISTORY_DIR%" mkdir "%HISTORY_DIR%"

for %%i in (
    "短线工具箱\筛选结果.csv"
    "短线工具箱\回测报告.json"
    "短线工具箱\归因报告.json"
    "短线工具箱\历史评分.jsonl"
) do (
    if exist "%%i" (
        copy "%%i" "%HISTORY_DIR%\" >> "%LOG_FILE%" 2>&1
        echo  copied %%i >> "%LOG_FILE%" 2>&1
    )
)

REM Step 4: 复制当日操作计划(如果有)
for %%f in (短线操作md文档\*.md) do (
    copy "%%f" "%HISTORY_DIR%\" >> "%LOG_FILE%" 2>&1
)

echo [%date% %time%] === 完成 === >> "%LOG_FILE%" 2>&1
echo 日志: %LOG_FILE%
exit /b 0
