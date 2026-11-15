@echo off
chcp 65001 >nul
cd /d "C:\Users\alper\Desktop\VİOP"

set "PYTHON_EXE=C:\Program Files\Python312\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

"%PYTHON_EXE%" scripts\service_manager.py
