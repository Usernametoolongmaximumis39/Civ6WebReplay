@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title Civ6 WebReplay v0.43
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
%PY% -c "import fastapi, uvicorn, httpx, python_multipart" >nul 2>nul
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

REM --- 随附运行数据 -------------------------------------------------------
echo [3/4] 正在检查随附运行数据 ...
for %%F in ("data\gamedb\vanilla\gamedb.sqlite" "data\vanilla\loc.json" "data\vanilla\identities.json" "data\vanilla\mapwrap.json" "data\shared\identities.json" "data\shared\player-colors.json" "data\mods\governor_promotions.json" "data\ui\strings.json" "data\ui\game-text.json" "assets\icons\index.json") do (
  if not exist "%%~F" (
    echo [错误] 缺少运行数据：%%~F。请重新下载完整程序包。
    goto :end
  )
)
for %%P in (vanilla bbg ccb) do (
  for %%F in (adjacency.json tileyields.json rule-text.json) do (
    if not exist "data\gamedb\%%P\%%F" (
      echo [错误] 缺少运行数据：data\gamedb\%%P\%%F。请重新下载完整程序包。
      goto :end
    )
  )
)

REM --- 启动 ---------------------------------------------------------------
set "PYTHONPATH=%CD%\src"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
echo [4/4] 启动服务，默认端口 8765；若被占用则自动选择可用端口。
echo        按 Ctrl+C 可停止；自定义参数示例: start.bat --port 9000 --save-dir "D:\saves"
echo        顶栏「共享」会另起一个对外监听（默认 8766，可用 --share-port 改）
echo.
%PY% -m civ6replay --auto-port %*

:end
echo.
echo 程序已退出。
pause
