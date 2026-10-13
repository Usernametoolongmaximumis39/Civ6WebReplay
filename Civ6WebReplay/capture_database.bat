@echo off
chcp 65001 >nul
setlocal
title Civ6 WebReplay - BBG / CCB 数据库采集与回档
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PY=python"
python -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
if errorlevel 1 (
  py -3 -c "import sys; assert sys.version_info >= (3,11)" >nul 2>nul
  if errorlevel 1 (
    echo [错误] 请安装 Python 3.11 或更新版本，并将 Python 添加到 PATH。
    goto :end
  )
  set "PY=py -3"
)
%PY% tools\capture_database.py %*
:end
echo.
pause
