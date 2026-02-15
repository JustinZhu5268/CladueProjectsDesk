@echo off
chcp 65001 >nul
title ClaudeStation
cd /d "%~dp0"
call venv\Scripts\activate.bat 2>nul
python main.py
