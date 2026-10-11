<#
Awake: keep this PC from sleeping while a long AgentAPP run is going.

It asks Windows not to sleep the system, checks once a minute whether the run is still going, and releases the
request as soon as the run ends (or after -MaxHours). No power settings are changed. The screen may still turn
off; closing the lid or choosing Sleep by hand still puts the PC to sleep.

    .\Awake.ps1                                  # while any "python main.py" of AgentAPP is running
    .\Awake.ps1 -Match "*main.py*--stage hrce*"  # while that stage is running
    .\Awake.ps1 -MaxHours 6

Start it in its own window (or in the background) after starting the run.
#>
param(
    [string]$Match = "*main.py*",   # wildcard matched against the command line of running python processes
    [double]$MaxHours = 3
)

$signature = '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$kernel = Add-Type -MemberDefinition $signature -Name Awake -Namespace Win32 -PassThru
$CONTINUOUS = [uint32]"0x80000000"
$SYSTEM_REQUIRED = [uint32]"0x00000001"

function Get-Run {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like $Match }
}

if (-not (Get-Run)) {
    "No running python process matches '$Match'. Start the run first."
    exit 1
}

$null = $kernel::SetThreadExecutionState($CONTINUOUS -bor $SYSTEM_REQUIRED)
"Keeping the PC awake while '$Match' runs (at most $MaxHours hours)."
$deadline = (Get-Date).AddHours($MaxHours)
try {
    do {
        Start-Sleep -Seconds 60
    } while ((Get-Run) -and (Get-Date) -lt $deadline)
}
finally {
    $null = $kernel::SetThreadExecutionState($CONTINUOUS)   # release, also when the script is stopped
}
"Released: the run has ended (or $MaxHours hours passed)."
