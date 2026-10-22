# motor_asi_io.ps1 - the ASI (Tiger, COM4, 115200 8N1, CR out / CRLF in) side of tools/motor_gate.py.
#   -Mode read           : query only (W X, W Y). Prints 'FRESH X=<units> Y=<units>'. Sends no motion.
#   -Mode limits-set     : write SL/SU (ABSOLUTE mm) from the gate's -ExpectSl*/-ExpectSu*, then read them back.
#   -Mode limits-release : the same write with the release values the gate passes (+-500 mm), then read back.
#   -Mode send           : READ SL/SU FIRST, inside this same port open and BEFORE the transmit; refuse (exit 7)
#                          unless they match the gate's expectations (tools/bench/motor_limits.json) within -Tol mm;
#                          then transmit ONE absolute single-axis move 'M X=<int>' / 'M Y=<int>' (units 0.1 um).
# REWORKED 2026-09-18: the old private "within 1.0 mm of tools/bench/motor_anchor.json" check is GONE - the real
# limit is the ASI controller's SL/SU (it stops motion at the boundary, joystick and HOME included, and persists
# across power cycles). What this script now proves is that the controller really carries the file's limits at
# transmit time. No home/zero/relative/save form is transmittable from here; never SS Z.
# send mode needs the gate's one-shot token naming the exact command; guard_bash.py blocks this file by name.
param(
    [Parameter(Mandatory = $true)][ValidateSet('read', 'send', 'limits-set', 'limits-release')][string]$Mode,
    [string]$Command = '',
    [string]$TokenFile = '',
    [double]$ExpectSlX = 0.0,
    [double]$ExpectSlY = 0.0,
    [double]$ExpectSuX = 0.0,
    [double]$ExpectSuY = 0.0,
    [double]$Tol = 0.001,
    [string]$Port = 'COM4',
    [int]$Baud = 115200,
    [int]$SettleTimeoutS = 30
)
$ErrorActionPreference = 'Stop'
$axis = $null; $target = $null
if ($Mode -eq 'send') {
    if (-not $TokenFile -or -not (Test-Path -LiteralPath $TokenFile)) { Write-Output 'SEND REFUSED: no gate token'; exit 7 }
    $tok = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
    Remove-Item -LiteralPath $TokenFile -Force -Confirm:$false
    if ($tok -cne $Command) { Write-Output 'SEND REFUSED: token does not name this command'; exit 7 }
    if ($Command -cnotmatch '^M ([XY])=(-?\d+)$') { Write-Output "SEND REFUSED: only 'M X=<int>' / 'M Y=<int>' is transmittable"; exit 7 }
    $axis = $Matches[1]; $target = [double]$Matches[2]
}
$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout = 800
$sp.NewLine = "`r"
function Ask([string]$q) {
    $sp.DiscardInBuffer(); $sp.WriteLine($q)
    try { return $sp.ReadLine().Trim() } catch { return '' }
}
function Where1([string]$a) { $r = Ask "W $a"; if ($r -match ':A\s+(-?\d+(?:\.\d+)?)') { return [double]$Matches[1] } return $null }
function Pair([string]$r) {
    if ($r -match 'X=\s*(-?\d+(?:\.\d+)?)\s+Y=\s*(-?\d+(?:\.\d+)?)') { return @{ X = [double]$Matches[1]; Y = [double]$Matches[2] } }
    return $null
}
function ReadLimits() {
    $sl = Pair (Ask 'SL X? Y?'); $su = Pair (Ask 'SU X? Y?')
    if ($null -eq $sl -or $null -eq $su) { return $null }
    return @{ SL = $sl; SU = $su }
}
try {
    $sp.Open()
    if ($Mode -eq 'read') {
        $x = Where1 'X'; $y = Where1 'Y'
        if ($null -eq $x -or $null -eq $y) { Write-Output 'READ FAILED: W X / W Y gave no number'; exit 6 }
        Write-Output ("FRESH X={0} Y={1}" -f $x, $y); exit 0
    }
    if ($Mode -ne 'send') {
        Write-Output ("before SL: {0}   SU: {1}" -f (Ask 'SL X? Y?'), (Ask 'SU X? Y?'))
        Write-Output ("SL write -> {0}" -f (Ask ("SL X={0:n4} Y={1:n4}" -f $ExpectSlX, $ExpectSlY)))
        Write-Output ("SU write -> {0}" -f (Ask ("SU X={0:n4} Y={1:n4}" -f $ExpectSuX, $ExpectSuY)))
        $L = ReadLimits
        if ($null -eq $L) { Write-Output 'LIMIT READBACK FAILED: SL?/SU? gave no pair'; exit 6 }
        Write-Output ("LIMITS SL X={0} Y={1} SU X={2} Y={3}" -f $L.SL.X, $L.SL.Y, $L.SU.X, $L.SU.Y)
        Write-Output ("position after (must be unchanged): X={0} Y={1}" -f (Where1 'X'), (Where1 'Y'))
        if ([math]::Abs($L.SL.X - $ExpectSlX) -gt $Tol -or [math]::Abs($L.SL.Y - $ExpectSlY) -gt $Tol -or
            [math]::Abs($L.SU.X - $ExpectSuX) -gt $Tol -or [math]::Abs($L.SU.Y - $ExpectSuY) -gt $Tol) {
            Write-Output 'RESULT: MISMATCH - the controller did not take the limits'; exit 7
        }
        Write-Output ("RESULT: controller limits set (mode {0})" -f $Mode); exit 0
    }

    # --- send: the limit readback comes FIRST, in this same port open, before anything is transmitted ---
    $L = ReadLimits
    if ($null -eq $L) { Write-Output 'SEND REFUSED: limit readback failed (SL?/SU? gave no pair)'; exit 7 }
    Write-Output ("LIMITS SL X={0} Y={1} SU X={2} Y={3}" -f $L.SL.X, $L.SL.Y, $L.SU.X, $L.SU.Y)
    if ([math]::Abs($L.SL.X - $ExpectSlX) -gt $Tol -or [math]::Abs($L.SL.Y - $ExpectSlY) -gt $Tol -or
        [math]::Abs($L.SU.X - $ExpectSuX) -gt $Tol -or [math]::Abs($L.SU.Y - $ExpectSuY) -gt $Tol) {
        Write-Output 'SEND REFUSED: ASI controller SL/SU do not match the file - run the session-start hook'
        exit 7
    }
    $x = Where1 'X'; $y = Where1 'Y'
    if ($null -eq $x -or $null -eq $y) { Write-Output 'SEND REFUSED: position read failed'; exit 6 }
    Write-Output ("FRESH X={0} Y={1}" -f $x, $y)
    $loU = @{ X = $L.SL.X * 10000.0; Y = $L.SL.Y * 10000.0 }
    $hiU = @{ X = $L.SU.X * 10000.0; Y = $L.SU.Y * 10000.0 }
    $reply = Ask $Command
    Write-Output "SENT: $Command   reply='$reply'"
    $t0 = Get-Date; $lx = $null; $ly = $null; $still = 0
    while (((Get-Date) - $t0).TotalSeconds -lt $SettleTimeoutS) {
        Start-Sleep -Milliseconds 300
        $cx = Where1 'X'; $cy = Where1 'Y'
        if ($null -eq $cx -or $null -eq $cy) { continue }
        if ($cx -lt ($loU.X - 500) -or $cx -gt ($hiU.X + 500) -or $cy -lt ($loU.Y - 500) -or $cy -gt ($hiU.Y + 500)) {
            $sp.WriteLine('\'); Write-Output "HALT SENT: X=$cx Y=$cy is outside the controller SL/SU window"; break
        }
        if ($null -ne $lx -and [math]::Abs($cx - $lx) -lt 2 -and [math]::Abs($cy - $ly) -lt 2) { $still++ } else { $still = 0 }
        $lx = $cx; $ly = $cy
        if ($still -ge 3) { break }
    }
    $fx = Where1 'X'; $fy = Where1 'Y'; $busy = Ask '/'
    Write-Output ("after: X={0} Y={1} status='{2}' elapsed={3:n1}s" -f $fx, $fy, $busy, ((Get-Date) - $t0).TotalSeconds)
    $final = if ($axis -eq 'X') { $fx } else { $fy }
    if ($null -ne $final -and [math]::Abs($final - $target) -le 5) { Write-Output "RESULT: reached $axis=$final (target $target)"; exit 0 }
    Write-Output "RESULT: NOT at target - $axis=$final target=$target"; Write-Output "FAIL: ASI move NOT at target ($axis=$final target=$target)"; exit 8
}
finally { if ($sp.IsOpen) { $sp.Close() }; $sp.Dispose() }
# ---
# labview: none
# hardware: motor
# ---
