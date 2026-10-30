@echo off
rem Double-click launcher: the GUI on the rig - JAI + iXon + PI / ASI / Autonics through the motion gate (backend
rem real-motors, decision 0025) - inside V6 tools/rig_session.py --no-motor-session, which takes the rig lock, polls
rem it every 30 s, and releases it after the GUI exits (owner 2026-10-30: "motor control, JAI, IXON 3가지 동시에").
rem Keep this window open while the GUI runs: it shows the lock log. Closing the GUI ends the session.
set "V6=G:\Codes\LabVIEW_Codes\MinLab\zz_LabView VI\AAA_UNIST\2. Tracking\V6_ParallelLoop"
if not exist "%V6%\tools\rig_session.py" (
    echo rig_session.py not found under "%V6%"; nothing started.
    pause
    exit /b 1
)
cd /d "%V6%"
py -u tools\rig_session.py --purpose "LabVIEW2Scr GUI: JAI + iXon + motors" --no-motor-session --max-min 240 -- "%~dp0.venv\Scripts\python.exe" -m mtpy.gui --backend real-motors --out "%~dp0runs"
echo.
echo rig session ended (see the RESULT line above: lock released?).
pause
