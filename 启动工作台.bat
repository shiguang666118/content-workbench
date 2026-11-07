@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set "RAYS_BRAIN=%~dp0vault"
set "RAYS_BRAIN_CONFIG=%~dp0config.json"
set "RAYS_BRAIN_STATE=%~dp0state"
where python >nul 2>nul
if errorlevel 1 (
  echo 没找到 Python。先装 Python 3.10 以上版本，安装时勾选 Add to PATH。
  pause
  exit /b 1
)
echo 正在启动工作台，浏览器会自动打开 http://localhost:8771
python -X utf8 "%~dp050-系统\40-自动化\知识仪表盘\server.py" --port 8771
pause