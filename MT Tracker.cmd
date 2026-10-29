@echo off
rem Double-click launcher: the GUI on the shipped safety profile (phases 6 / 7 add the real devices).
cd /d "%~dp0"
start "" "%~dp0.venv\Scripts\pythonw.exe" -m mtpy.gui
