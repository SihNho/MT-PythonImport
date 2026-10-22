# motor_rotor_io.ps1 - the ROTOR (Autonics PMC-2HS, X axis, COM5 9600 8N1, CR out / CR in) side of tools/motor_gate.py.
#   -Mode read : query only (POS). Prints "FRESH RAW='<reply>' POS=<signed pulses>". Sends no motion.
#   -Mode send : needs the gate's one-shot token naming the exact command ('PAB <int>' or 'PIC <int>', X only).
#                Inside ONE port open: POS twice (must be identical = stationary), target = PAB value or FRESH POS +
#                PIC value, REFUSE (exit 7) unless -Lo <= target <= -Hi (the session window the gate passes);
#                'SPD <Speed>' (the gate's cap), the move, then POS every 300 ms - 'STO X' and exit 8 if the position
#                leaves the window; final POS must equal the target (exit 0) else exit 8.
# Protocol: Autonics PMC-1HS/2HS manual DRW170814AB ch. 8 (docs/rotor-protocol.md). Writes have NO response. The POS
# reply is 'POS hhhhhhhh,hhhhhhhh' (8 hex digits per axis, two's complement; 'FFFFFFF6' = -10 pulses).
# The first read after opening the port times out (docs/instrument-libraries.md:320) - one dummy POS is discarded.
# NEVER sends CLL/CLR/HOM/IHS/IXS/RST/PRG/JOG (they would move the fence or bypass it).
# Created 2026-10-19 and NOT YET RUN ON HARDWARE; guard_bash.py does not yet block this file by name (see
# docs/rotor-protocol.md "Open").
param(
    [Parameter(Mandatory = $true)][ValidateSet('read', 'send')][string]$Mode,
    [string]$Command = '',
    [string]$TokenFile = '',
    [long]$Lo = 0,
    [long]$Hi = 0,
    [int]$Speed = 0,
    [string]$Port = 'COM5',
    [int]$Baud = 9600,
    [int]$SettleTimeoutS = 120
)
$ErrorActionPreference = 'Stop'
$verb = $null; $val = $null
if ($Mode -eq 'send') {
    if (-not $TokenFile -or -not (Test-Path -LiteralPath $TokenFile)) { Write-Output 'SEND REFUSED: no gate token'; exit 7 }
    $tok = (Get-Content -LiteralPath $TokenFile -Raw).Trim()
    Remove-Item -LiteralPath $TokenFile -Force -Confirm:$false
    if ($tok -cne $Command) { Write-Output 'SEND REFUSED: token does not name this command'; exit 7 }
    if ($Command -cnotmatch '^(PAB|PIC) (-?\d{1,8})$') { Write-Output "SEND REFUSED: only 'PAB <int>' / 'PIC <int>' is transmittable"; exit 7 }
    $verb = $Matches[1]; $val = [long]$Matches[2]
    if ($Speed -lt 1 -or $Speed -gt 100) { Write-Output "SEND REFUSED: speed $Speed outside 1..100"; exit 7 }
    if ($Hi -le $Lo -or ($Hi - $Lo) -gt 5000) { Write-Output "SEND REFUSED: window $Lo..$Hi is not a valid <= 10-turn window"; exit 7 }
}
$sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, ([System.IO.Ports.Parity]::None), 8, ([System.IO.Ports.StopBits]::One)
$sp.ReadTimeout = 1500
$sp.NewLine = "`r"
function Ask([string]$q) {
    $sp.DiscardInBuffer(); $sp.WriteLine($q)
    try { return $sp.ReadLine().Trim() } catch { return '' }
}
function Say([string]$q) { $sp.DiscardInBuffer(); $sp.WriteLine($q) }   # writes have no response (manual ch. 8)
function PosOf([string]$r) {
    if ($r -match '^POS\s+([0-9A-Fa-f]{8})(?:\s*,\s*[0-9A-Fa-f]{8})?$') { return [long][Convert]::ToInt32($Matches[1], 16) }
    return $null
}
try {
    $sp.Open()
    $null = Ask 'POS'; Start-Sleep -Milliseconds 200; $sp.DiscardInBuffer()   # first-read timeout artefact
    if ($Mode -eq 'read') {
        $r = Ask 'POS'; $p = PosOf $r
        if ($null -eq $p) { Write-Output "READ FAILED: POS reply '$r'"; exit 6 }
        Write-Output ("FRESH RAW='{0}' POS={1}" -f $r, $p); exit 0
    }

    # --- send: the fresh read and the window check come FIRST, in this same port open, before anything moves ---
    $r1 = Ask 'POS'; $p1 = PosOf $r1
    Start-Sleep -Milliseconds 150
    $r2 = Ask 'POS'; $p2 = PosOf $r2
    if ($null -eq $p1 -or $null -eq $p2) { Write-Output "SEND REFUSED: position read failed ('$r1' / '$r2')"; exit 6 }
    if ($p1 -ne $p2) { Write-Output "SEND REFUSED: rotor is moving ($p1 -> $p2)"; exit 7 }
    Write-Output ("FRESH RAW='{0}' POS={1}" -f $r2, $p2)
    $target = if ($verb -eq 'PAB') { $val } else { $p2 + $val }
    Write-Output ("TARGET={0} window={1}..{2}" -f $target, $Lo, $Hi)
    if ($target -lt $Lo -or $target -gt $Hi) { Write-Output "SEND REFUSED: target $target outside the session window $Lo..$Hi"; exit 7 }
    Say ("SPD {0}" -f $Speed)
    Start-Sleep -Milliseconds 100
    Say $Command
    Write-Output "SENT: SPD $Speed ; $Command"
    $t0 = Get-Date; $last = $null; $still = 0
    while (((Get-Date) - $t0).TotalSeconds -lt $SettleTimeoutS) {
        Start-Sleep -Milliseconds 300
        $c = PosOf (Ask 'POS')
        if ($null -eq $c) { continue }
        if ($c -lt ($Lo - 25) -or $c -gt ($Hi + 25)) {
            Say 'STO X'; Write-Output "STOP SENT: POS=$c is outside the session window $Lo..$Hi"
            Write-Output "FAIL: rotor left the window"; exit 8
        }
        if ($null -ne $last -and $c -eq $last) { $still++ } else { $still = 0 }
        $last = $c
        if ($still -ge 2) { break }
    }
    $rf = Ask 'POS'; $pf = PosOf $rf
    Write-Output ("after: RAW='{0}' POS={1} elapsed={2:n1}s" -f $rf, $pf, ((Get-Date) - $t0).TotalSeconds)
    if ($null -ne $pf -and $pf -eq $target) { Write-Output "RESULT: reached $pf (target $target)"; exit 0 }
    Write-Output "RESULT: NOT at target - POS=$pf target=$target"; Write-Output "FAIL: rotor move NOT at target (POS=$pf target=$target)"; exit 8
}
finally { if ($sp.IsOpen) { $sp.Close() }; $sp.Dispose() }
# ---
# labview: none
# hardware: motor
# ---
