# motor_send_pi.ps1 - the PI (C-863.11, COM3) side of tools/motor_gate.py. THREE modes, one port open each:
#   -Mode limits-set     : SPA 1 0x15 <ExpectHi> + SPA 1 0x30 <ExpectLo>, then read TMN?/TMX?/SPA? back.
#   -Mode limits-release : the same write with the release values the gate passes (0 .. 52), then read back.
#   -Mode send           : READ THE CONTROLLER LIMITS FIRST, inside this same port open and BEFORE the transmit;
#                          refuse (exit 7) unless they match -ExpectLo/-ExpectHi (from tools/bench/motor_limits.json)
#                          within -Tol; then transmit ONE 'MOV 1 <n>' and poll POS? until the axis settles.
# REWORKED 2026-09-18: the old private 0..39 re-check is GONE - the real limit is the controller's (TMN/TMX), and
# what this script now proves is that the controller is really carrying the file's limits at transmit time.
# Never WPA (the soft limits are RAM by design). Every mode prints one machine-readable 'LIMITS TMN=.. TMX=..' line
# AFTER the write; the limits-set/limits-release modes ALSO print 'PRELIMITS TMN=<n> TMX=<n>' BEFORE it (2026-09-18,
# STATUS.md OPEN 55) - that is the only line that says what the controller held on arrival.
# send mode refuses to run unless the gate's one-shot token file names this exact command (the gate writes it after
# an ALLOW decision and this script deletes it before opening the port), so running this file by hand sends nothing.
# guard_bash.py also blocks it by name.
param(
    [ValidateSet('send', 'limits-set', 'limits-release', 'reference')][string]$Mode = 'send',
    [string]$Command = '',
    [string]$TokenFile = '',
    [double]$ExpectLo = 0.0,
    [double]$ExpectHi = 39.0,
    [double]$Tol = 0.001,
    [string]$Port = 'COM3',
    [int]$Baud = 115200,
    [int]$SettleTimeoutS = 90
)
$ErrorActionPreference = 'Stop'
if ($Mode -eq 'send') {
    if (-not (Test-Path -LiteralPath $TokenFile)) { Write-Output 'SEND REFUSED: no gate token'; exit 7 }
    $tok = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
    Remove-Item -LiteralPath $TokenFile -Force -Confirm:$false
    if ($tok -ne $Command) { Write-Output 'SEND REFUSED: token does not name this command'; exit 7 }
    if ($Command -notmatch '^MOV 1 (\d+(?:\.\d+)?)$') { Write-Output "SEND REFUSED: only 'MOV 1 <n>' is transmittable"; exit 7 }
    $target = [double]$Matches[1]
}

$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout = 600
$sp.NewLine = "`n"
function Ask([string]$q) {
    $sp.DiscardInBuffer(); $sp.WriteLine($q)
    try { return $sp.ReadLine().Trim() } catch { return '' }
}
function Num([string]$r) { if ($r -match '=\s*([-+0-9.eE]+)') { return [double]$Matches[1] } return $null }
function ReadLimits() {
    $tmn = Num (Ask 'TMN?'); $tmx = Num (Ask 'TMX?')
    $s15 = Num (Ask 'SPA? 1 0x15'); $s30 = Num (Ask 'SPA? 1 0x30')
    if ($null -eq $tmn -or $null -eq $tmx) { return $null }
    if ($null -eq $s15) { $s15 = $tmx }; if ($null -eq $s30) { $s30 = $tmn }
    return @{ TMN = $tmn; TMX = $tmx; S15 = $s15; S30 = $s30 }
}
try {
    $sp.Open()
    if ($Mode -eq 'reference') {
        # USER-ORDERED REFERENCE MOVE (2026-09-23 "원점 다시 돌려"): after a controller power-cycle the C-863 restarts
        # with POS 0 at whatever physical spot the stage was in, so "0" is no longer the negative end of travel. FNL 1
        # drives the axis to the NEGATIVE LIMIT SWITCH and sets 0 there - the convention the file's limits (TMN 0)
        # assume. Only reachable through `motor_gate.py --reference`, which the user must order; never automatic.
        Write-Output ("before: POS?={0} FRF?={1} SVO?={2} ERR?={3}" -f (Ask 'POS?'), (Ask 'FRF?'), (Ask 'SVO?'), (Ask 'ERR?'))
        $sp.WriteLine('SVO 1 1'); Start-Sleep -Milliseconds 300
        $sp.WriteLine('RON 1 1'); Start-Sleep -Milliseconds 300
        Write-Output ("prep: SVO?={0} RON?={1} ERR?={2}" -f (Ask 'SVO?'), (Ask 'RON?'), (Ask 'ERR?'))
        $sp.WriteLine('FNL 1')
        Write-Output 'SENT: FNL 1 (reference to the negative limit switch)'
        $t0 = Get-Date; $done = $false
        while (((Get-Date) - $t0).TotalSeconds -lt $SettleTimeoutS) {
            Start-Sleep -Milliseconds 500
            $frf = Num (Ask 'FRF?'); $p = Num (Ask 'POS?'); $ont = Num (Ask 'ONT?')
            Write-Output ("poll: FRF?={0} POS?={1} ONT?={2}" -f $frf, $p, $ont)
            if ($frf -eq 1 -and $ont -eq 1) { $done = $true; break }
        }
        $err = Ask 'ERR?'
        Write-Output ("after: POS?={0} FRF?={1} ONT?={2} ERR?={3} elapsed={4:N1}s" -f (Ask 'POS?'), (Ask 'FRF?'), (Ask 'ONT?'), $err, (((Get-Date) - $t0).TotalSeconds))
        if ($done) { Write-Output 'RESULT: REFERENCED - 0 is now the negative limit switch'; exit 0 }
        Write-Output 'RESULT: reference move did NOT complete within the timeout'; exit 9
    }
    if ($Mode -ne 'send') {
        # The four raw replies are captured ONCE, so the human-readable `before:` line and the
        # machine-readable `PRELIMITS` line below are built from the SAME strings - no extra serial
        # traffic, and the two lines cannot disagree.
        $rPos = Ask 'POS?'; $rTmn = Ask 'TMN?'; $rTmx = Ask 'TMX?'; $rErr = Ask 'ERR?'
        Write-Output ("before: POS?={0} TMN?={1} TMX?={2} ERR?={3}" -f $rPos, $rTmn, $rTmx, $rErr)
        # PRELIMITS = the PRE-WRITE limits, normalised by THIS script's own `Num` parser (:41), so no
        # downstream reader has to know the controller answers `<cmd>=<axis>=<value>` (`TMX?=1=39.00000`).
        # It is printed BEFORE the SPA write, which is the only line that can answer "what did the
        # controller hold when we got here"; the `LIMITS` lines at :58/:78 are printed AFTER the write and
        # answer "did we just set it". Reading the wrong one is a SILENT FALSE GREEN on a motor-limit
        # check (STATUS.md OPEN 55; archive/peer/2026-09-18-tmx-lastfield-parse.md Q2/Q3).
        # If a reply is unreadable `Num` returns $null and the field prints EMPTY, so the downstream
        # anchored regex fails LOUDLY instead of falling through to some other line.
        Write-Output ("PRELIMITS TMN={0} TMX={1}" -f (Num $rTmn), (Num $rTmx))
        $sp.WriteLine(("SPA 1 0x15 {0}" -f $ExpectHi)); Start-Sleep -Milliseconds 250
        $sp.WriteLine(("SPA 1 0x30 {0}" -f $ExpectLo)); Start-Sleep -Milliseconds 250
        Write-Output ("ERR? after SPA = {0}" -f (Ask 'ERR?'))
        $L = ReadLimits
        if ($null -eq $L) { Write-Output 'LIMIT READBACK FAILED: TMN?/TMX? gave no number'; exit 6 }
        Write-Output ("LIMITS TMN={0} TMX={1} SPA15={2} SPA30={3}" -f $L.TMN, $L.TMX, $L.S15, $L.S30)
        if ([math]::Abs($L.TMN - $ExpectLo) -gt $Tol -or [math]::Abs($L.TMX - $ExpectHi) -gt $Tol) {
            Write-Output ("RESULT: MISMATCH - wanted TMN={0} TMX={1}" -f $ExpectLo, $ExpectHi); exit 7
        }
        if ($Mode -eq 'limits-set') {
            # MEASURED 2026-09-18 15:5x: writing SPA 0x15/0x30 leaves the axis UNREFERENCED (FRF? 0), and every MOV
            # then answers ERR 5 before the soft limit is ever consulted (tools/bench/motor_gate2_live.log L2/L3).
            # So the session-start hook restores the reference the ONE way that moves nothing and shifts no zero:
            # RON 1 0 (referencing off - it already is) and POS 1 <the value POS? just returned>, i.e. the SAME
            # number. Never FRF/FNL/FPL/GOH (those MOVE the axis). Nothing else in the fleet may send POS.
            # REPLACED 2026-09-23 (user: "반드시 싸이클 시작할 때는 PI 모터 원점 복귀 반드시 시킨 후에 실제 좌표와 아웃풋
            # 좌표 비교하는거 반드시 만들어" · "훅으로 고정해"). The old restore (RON 1 0 + POS 1 <current>) DECLARED the
            # current counter to be zero; after a controller power-cycle that counter is 0 wherever the stage sits,
            # so it cemented a false zero and a MOV +30 ran into the hard limit (ERR 216, tools/bench/pi_testmove_20260923e.log).
            # Now: a REAL reference move (FNL 1 -> 0 = negative limit switch), then a commanded-vs-readback check.
            $p0 = Num (Ask 'POS?')
            if ($null -eq $p0) { Write-Output 'REF FAILED: POS? gave no number'; exit 6 }
            $sp.WriteLine('SVO 1 1'); Start-Sleep -Milliseconds 300
            $sp.WriteLine('RON 1 1'); Start-Sleep -Milliseconds 300
            $sp.WriteLine('FNL 1')
            Write-Output ("REFERENCE: POS before={0} -> SENT FNL 1 (to the negative limit switch)" -f $p0)
            $t0 = Get-Date; $refDone = $false
            while (((Get-Date) - $t0).TotalSeconds -lt 120) {
                Start-Sleep -Milliseconds 500
                $frf = Num (Ask 'FRF?'); $ont = Num (Ask 'ONT?')
                if ($frf -eq 1 -and $ont -eq 1) { $refDone = $true; break }
            }
            $ron = Num (Ask 'RON?'); $frf = Num (Ask 'FRF?'); $p1 = Num (Ask 'POS?')
            Write-Output ("REFSTATE RON={0} FRF={1} POS={2} POS_BEFORE={3} ERR={4} travelled={5:0.000}" -f $ron, $frf, $p1, $p0, (Ask 'ERR?'), ($p0 - $p1))
            if (-not $refDone -or $frf -ne 1) { Write-Output 'RESULT: REFERENCE MOVE DID NOT COMPLETE - no session'; exit 7 }
            if ([math]::Abs($p1) -gt $Tol) { Write-Output ("RESULT: after FNL the counter reads {0}, not 0 - no session" -f $p1); exit 7 }
            # VERIFY: commanded vs read-back on two small moves inside the envelope. Position must follow the
            # command within $VerifyTol; ERR? must stay 0. A stage that does not follow is not trusted.
            $VerifyTol = 0.05; $verifyOk = $true; $vlines = @()
            foreach ($tgt in @(2, 0)) {
                $sp.WriteLine(("MOV 1 {0}" -f $tgt)); $t1 = Get-Date; $pv = $null
                while (((Get-Date) - $t1).TotalSeconds -lt 20) {
                    Start-Sleep -Milliseconds 300
                    if ((Num (Ask 'ONT?')) -eq 1) { break }
                }
                $pv = Num (Ask 'POS?'); $ev = Ask 'ERR?'
                $d = if ($null -ne $pv) { [math]::Abs($pv - $tgt) } else { 999 }
                $ok = ($d -le $VerifyTol) -and ($ev -match '(^|=)0$')
                if (-not $ok) { $verifyOk = $false }
                $vlines += ("VERIFY: commanded={0} readback={1} delta={2:0.0000} err={3} -> {4}" -f $tgt, $pv, $d, $ev, $(if ($ok) { 'OK' } else { 'MISMATCH' }))
            }
            $vlines | ForEach-Object { Write-Output $_ }
            if (-not $verifyOk) { Write-Output 'RESULT: COMMANDED vs READBACK MISMATCH after referencing - no session'; exit 7 }
            Write-Output 'VERIFY-RESULT: OK - reference move done and the stage follows commands'
            $L2 = ReadLimits
            if ($null -eq $L2) { Write-Output 'RESULT: limit re-readback failed after the reference restore'; exit 7 }
            Write-Output ("LIMITS TMN={0} TMX={1} SPA15={2} SPA30={3}" -f $L2.TMN, $L2.TMX, $L2.S15, $L2.S30)
            if ([math]::Abs($L2.TMN - $ExpectLo) -gt $Tol -or [math]::Abs($L2.TMX - $ExpectHi) -gt $Tol) {
                Write-Output 'RESULT: MISMATCH - the limits did not survive the reference restore'; exit 7
            }
            $L = $L2
        }
        Write-Output ("RESULT: controller limits are TMN={0} TMX={1} (mode {2})" -f $L.TMN, $L.TMX, $Mode); exit 0
    }

    # --- send: the readback comes FIRST, in this same port open, before anything is transmitted ---
    $L = ReadLimits
    if ($null -eq $L) { Write-Output 'SEND REFUSED: limit readback failed (TMN?/TMX? gave no number)'; exit 7 }
    Write-Output ("LIMITS TMN={0} TMX={1} SPA15={2} SPA30={3}" -f $L.TMN, $L.TMX, $L.S15, $L.S30)
    if ([math]::Abs($L.TMN - $ExpectLo) -gt $Tol -or [math]::Abs($L.TMX - $ExpectHi) -gt $Tol) {
        Write-Output ("SEND REFUSED: controller limits TMN={0} TMX={1} do not match the file ({2}..{3}) - run the session-start hook" -f $L.TMN, $L.TMX, $ExpectLo, $ExpectHi)
        exit 7
    }
    $frf = Num (Ask 'FRF?')
    Write-Output ("before: POS?={0}  SVO?={1}  FRF?={2}  VEL?={3}  ERR?={4}" -f (Ask 'POS?'), (Ask 'SVO?'), $frf, (Ask 'VEL?'), (Ask 'ERR?'))
    if ($frf -ne 1) {
        Write-Output 'SEND REFUSED: the axis is NOT REFERENCED (FRF? 0) - every MOV would answer ERR 5 without ever reaching the soft limit. Run the session-start hook (motor_gate.py --session start), which does a real reference move (FNL 1, negative limit switch), requires FRF? 1 and POS 0, then verifies commanded vs readback.'
        exit 7
    }
    # SERVO ON before a move (2026-09-23): after a controller power-cycle the C-863 comes up with SVO 0 and every MOV
    # answers ERR 5 ("move attempted with servo off") without moving - the user saw it as "PI does not respond".
    # 'SVO 1 1' enables the servo loop and moves nothing; it is re-read before the MOV is sent.
    $svo = Num (Ask 'SVO?')
    if ($svo -ne 1) {
        $sp.WriteLine('SVO 1 1'); Start-Sleep -Milliseconds 300
        $svo2 = Num (Ask 'SVO?'); $errSvo = Ask 'ERR?'
        Write-Output ("SERVO: SVO? was {0} -> sent 'SVO 1 1' -> SVO? now {1}, ERR? {2}" -f $svo, $svo2, $errSvo)
        if ($svo2 -ne 1) { Write-Output 'SEND REFUSED: servo could not be enabled (SVO? still 0) - the MOV would answer ERR 5'; exit 7 }
    }
    $sp.WriteLine($Command)
    Write-Output "SENT: $Command"
    $err = Ask 'ERR?'
    Write-Output "ERR? right after send = $err"
    $t0 = Get-Date; $last = $null; $still = 0
    while (((Get-Date) - $t0).TotalSeconds -lt $SettleTimeoutS) {
        Start-Sleep -Milliseconds 500
        $p = Num (Ask 'POS?')
        if ($null -ne $p) {
            if ($p -gt ($ExpectHi + 0.5) -or $p -lt ($ExpectLo - 0.5)) {
                $sp.WriteLine('HLT'); Write-Output "HALT SENT: position $p outside the controller limits $ExpectLo..$ExpectHi"; break
            }
            if ($null -ne $last -and [math]::Abs($p - $last) -lt 0.0005) { $still++ } else { $still = 0 }
            $last = $p
            if ($still -ge 3) { break }
        }
    }
    Write-Output ("after:  POS?={0}  ONT?={1}  ERR?={2}  elapsed={3:n1}s" -f (Ask 'POS?'), (Ask 'ONT?'), (Ask 'ERR?'), ((Get-Date) - $t0).TotalSeconds)
    $final = Num (Ask 'POS?')
    # SUCCESS NEEDS BOTH: the controller accepted the command (ERR? 0 right after the send) AND the axis is at the
    # target. Position alone is not enough - `MOV 1 0` while already at 0 was REJECTED with ERR 5 on 2026-09-18
    # and still printed "reached 0" and exited 0, writing a false position belief into every downstream record
    # (both arms of archive/peer/2026-09-18-pi-err5-unreferenced-*.md, finding D1).
    # `FAIL:` lines (2026-09-24, cycle 69, device-failed repair): pi_testmove_20260923e.log:23/34 printed these two
    # RESULT lines and the chained run still ended `BGRUN END rc=0`. A `FAIL:` line is what bgrun/audit_cycle scan for.
    if ($err -ne '0') { Write-Output "RESULT: REJECTED BY THE CONTROLLER - ERR $err right after send, POS=$final (target $target)"; Write-Output "FAIL: PI MOV rejected by the controller (ERR $err, target $target, POS=$final)"; exit 9 }
    if ($null -ne $final -and [math]::Abs($final - $target) -lt 0.01) { Write-Output "RESULT: reached $final (target $target)"; exit 0 }
    Write-Output "RESULT: NOT at target - final=$final target=$target  (ERR right after send was $err)"; Write-Output "FAIL: PI MOV NOT at target (final=$final target=$target)"; exit 8
}
finally { if ($sp.IsOpen) { $sp.Close() }; $sp.Dispose() }
# ---
# labview: none
# hardware: motor
# ---
