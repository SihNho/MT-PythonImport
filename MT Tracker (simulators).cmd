@echo off
rem Double-click launcher for DEVELOPMENT: the GUI on the simulators with TEST-ONLY limits (no terminal typing; owner
rem 2026-10-30). The Setup panel then shows the backend and the simulator fixture. Requires the project's .venv next
rem to this file (installer for other PCs: plan phase 11).
cd /d "%~dp0"
start "" "%~dp0.venv\Scripts\pythonw.exe" -m mtpy.gui --backend sim --sim-dev
