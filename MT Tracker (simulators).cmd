@echo off
rem Double-click launcher: the GUI on the simulators with TEST-ONLY limits (no terminal typing; owner 2026-10-30).
rem Requires the project's .venv next to this file (installer for other PCs: plan phase 11).
cd /d "%~dp0"
start "" "%~dp0.venv\Scripts\pythonw.exe" -m mtpy.gui --sim-dev
