[CmdletBinding(SupportsShouldProcess, DefaultParameterSetName = 'Install')]
param(
    [Parameter(ParameterSetName = 'Install')][switch]$Replace,
    [Parameter(Mandatory, ParameterSetName = 'Xml')][switch]$EmitXml,
    [Parameter(Mandatory, ParameterSetName = 'Run')][switch]$RunCollector,
    [string]$PythonPath = (Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source,
    [string]$RadarData,
    [switch]$SkipEgo
)

$ErrorActionPreference = 'Stop'
$taskName = 'ResearchRadar-ShortTerm-2030'
$repo = (Get-Item -LiteralPath $PSScriptRoot).Parent.Parent.FullName
$collector = Join-Path $PSScriptRoot 'collect_short_term.py'
$python = (Get-Item -LiteralPath $PythonPath -ErrorAction Stop).FullName
if ($RadarData) { $RadarData = (Get-Item -LiteralPath $RadarData -ErrorAction Stop).FullName }

function Beijing-Now {
    return [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTimeOffset]::UtcNow, 'China Standard Time')
}

if ($RunCollector) {
    if (-not $PSCmdlet.ShouldProcess($repo, 'Collect local market snapshot')) { return }
    $started = Beijing-Now
    $logFolder = Join-Path $env:LOCALAPPDATA 'ResearchRadar\short-term'
    New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
    $log = Join-Path $logFolder ($started.ToString('yyyy-MM') + '.log')
    $day = $started.ToString('yyyy-MM-dd')
    $rc = 0
    $state = 'before_target'
    if ($started.TimeOfDay -ge [TimeSpan]::FromMinutes(1230)) {
        $cli = @('-B', $collector, '--date', $day)
        if ($RadarData) { $cli += @('--radar-data', $RadarData) }
        if ($SkipEgo) { $cli += '--skip-ego' }
        Push-Location -LiteralPath $repo
        try {
            # Provider output stays out of scheduler logs, including native stderr.
            $ErrorActionPreference = 'Continue'
            & $python @cli *> $null
            $rc = $LASTEXITCODE
            if ($null -eq $rc) { $rc = 1 }
            $state = switch ($rc) { 0 { 'finished_or_closed' } 2 { 'stale' } default { 'failed' } }
        } finally {
            Pop-Location
            $ErrorActionPreference = 'Stop'
        }
    }
    Add-Content -LiteralPath $log -Encoding ASCII -Value (
        '{0:o} day={1} state={2} exit={3}' -f (Beijing-Now), $day, $state, $rc)
    exit $rc
}

# Only executable/file paths and the explicit opt-out flag enter the task XML.
$psExe = Join-Path $PSHOME 'pwsh.exe'
if (-not (Test-Path -LiteralPath $psExe)) { $psExe = Join-Path $PSHOME 'powershell.exe' }
$actionArgs = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -RunCollector -PythonPath "{1}"' -f $PSCommandPath, $python
if ($RadarData) { $actionArgs += ' -RadarData "{0}"' -f $RadarData }
if ($SkipEgo) { $actionArgs += ' -SkipEgo' }

$startDate = (Beijing-Now).ToString('yyyy-MM-dd') + 'T20:30:00+08:00'
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$xml = @"
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Research Radar local evening snapshot</Description></RegistrationInfo>
  <Triggers><CalendarTrigger>
    <StartBoundary>$startDate</StartBoundary>
    <Enabled>true</Enabled>
    <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
  </CalendarTrigger></Triggers>
  <Principals><Principal id="Operator">
    <UserId>$sid</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel>
  </Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT3H</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Operator"><Exec>
    <Command>$([Security.SecurityElement]::Escape($psExe))</Command>
    <Arguments>$([Security.SecurityElement]::Escape($actionArgs))</Arguments>
    <WorkingDirectory>$([Security.SecurityElement]::Escape($repo))</WorkingDirectory>
  </Exec></Actions>
</Task>
"@
if ($EmitXml) { Write-Output $xml; return }
if ($PSCmdlet.ShouldProcess($taskName, 'Register local 20:30 Beijing time scheduled task')) {
    Register-ScheduledTask -TaskName $taskName -Xml $xml -Force:$Replace -ErrorAction Stop | Out-Null
    Write-Output "Registered $taskName"
}
