# 在 PowerShell 终端里手动跑这个脚本，把改动提交
# 改动内容：
#   1. 筛选明日股票_v1.py - 股票池过滤(00/60开头) +4行
#   2. 短线工具箱/tests/test_scorer.py - 新文件(93行, 13 pytest用例)
#   3. 临时文件(patch_*.py) - 需要删除
Write-Host "=== 提交当前工作区改动 ===" -ForegroundColor Green

# 删除临时文件
Remove-Item -Force "\patch_filter.py" -ErrorAction SilentlyContinue
Remove-Item -Force "\patch_temp.py" -ErrorAction SilentlyContinue

cd ""
git add -A
git status
Write-Host "
如果状态正确, 跑下面这行:"
Write-Host "git commit -m "feat(filter): 股票池过滤到00/60开头 + test_scorer"" -ForegroundColor Yellow
Write-Host "
然后再合并到 main:"
Write-Host "git checkout main" -ForegroundColor Yellow
Write-Host "git merge fix/akshare-apis" -ForegroundColor Yellow
Write-Host "git push origin main" -ForegroundColor Yellow
