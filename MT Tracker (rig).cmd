@echo off
rem Double-click launcher: the GUI on the rig - JAI + iXon + PI / ASI / Autonics through the motion gate (backend
rem real-motors, decision 0025). The program takes the shared rig lock itself when you press Connect and releases it
rem after the shutdown sequence (decision 0026); no wrapper. Refused while LabVIEW runs or the rig is in experiment.
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -m mtpy.gui --backend real-motors --out "%~dp0runs"
if errorlevel 1 pause
