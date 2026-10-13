@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Civ6 WebReplay v0.41
cd /d "%~dp0"

REM --- 选择 Python ---------------------------------------------------------
set "PY=python"
python --version >nul 2>nul
if errorlevel 1 (
  py -3 --version >nul 2>nul
  if errorlevel 1 (
    echo [错误] 未找到 Python。请安装 Python 3.11+ 并勾选 "Add python.exe to PATH"。
    echo        下载地址: https://www.python.org/downloads/
    goto :end
  )
  set "PY=py -3"
)
echo [1/4] 正在检查 Python ...
%PY% --version

REM --- 依赖 ---------------------------------------------------------------
%PY% -c "import fastapi, uvicorn, httpx" >nul 2>nul
if errorlevel 1 (
  echo [2/4] 首次运行，正在安装依赖（需要联网，请稍候）...
  %PY% -m pip install --upgrade pip
  %PY% -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络后重试。
    goto :end
  )
) else (
  echo [2/4] 依赖已就绪。
)

REM --- 数据快照 -----------------------------------------------------------
if not exist "data\gamedb\vanilla\gamedb.sqlite" (
  echo [3/4] 生成游戏数据库快照 ...
  %PY% tools\build_gamedb.py
) else (
  echo [3/4] 游戏数据库快照已存在。
)
if not exist "data\vanilla\loc.json" (
  echo        生成本地化快照 ...
  %PY% tools\build_loc.py
)
if not exist "data\vanilla\identities.json" (
  echo        生成静态身份名录 ...
  %PY% tools\build_identities.py
)
if not exist "assets\icons\index.json" (
  echo        生成图标索引 ...
  %PY% tools\vendor_icons.py
)

REM --- 启动 ---------------------------------------------------------------
set "PYTHONPATH=%CD%\src"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
echo [4/4] 启动服务，浏览器将自动打开 http://127.0.0.1:8765/
echo        按 Ctrl+C 可停止；自定义参数示例: start.bat --port 9000 --save-dir "D:\saves"
echo        顶栏「共享」会另起一个对外监听（默认 8766，可用 --share-port 改）
echo.
%PY% -m civ6replay %*

:end
echo.
echo 程序已退出。
pause
