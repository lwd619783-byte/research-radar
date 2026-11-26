[CmdletBinding(SupportsShouldProcess, DefaultParameterSetName = 'Install')]
param(
    [Parameter(ParameterSetName = 'Install')][switch]$Replace,
    [Parameter(Mandatory, ParameterSetName = 'Xml')][switch]$EmitXml,
    [Parameter(Mandatory, ParameterSetName = 'Run')][switch]$RunCollector,
    [string]$PythonPath = (Get-Command python.exe -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source,
    [string]$RadarData,
    [switch]$SkipEgo,
    [string]$ShadowDirectory,
    [datetime]$Through
)

$ErrorActionPreference = 'Stop'
$taskName = 'ResearchRadar-ShortTerm-2030'
$repo = (Get-Item -LiteralPath $PSScriptRoot).Parent.Parent.FullName
$collector = Join-Path $PSScriptRoot 'collect_short_term.py'
$python = (Get-Item -LiteralPath $PythonPath -ErrorAction Stop).FullName
if ($RadarData) { $RadarData = (Get-Item -LiteralPath $RadarData -ErrorAction Stop).FullName }
if ($ShadowDirectory) {
    $ShadowDirectory = [IO.Path]::GetFullPath($ShadowDirectory)
    $checkoutPrefix = $repo.TrimEnd('\') + '\'
    if ($ShadowDirectory -eq $repo -or $ShadowDirectory.StartsWith($checkoutPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The shadow directory must be outside the source checkout.'
    }
    $taskName = 'ResearchRadar-ShortTerm-Shadow'
}
if ($Through -and -not $ShadowDirectory) { throw 'A finite end date is only supported for the shadow task.' }

function Beijing-Now {
    return [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTimeOffset]::UtcNow, 'China Standard Time')
}

function Invoke-LocalCollector([string]$Executable, [string]$WorkingDirectory, [string[]]$CliArguments) {
    $startInfo = [Diagnostics.ProcessStartInfo]::new($Executable)
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    if ($startInfo.PSObject.Properties['ArgumentList']) {
        foreach ($arg in $CliArguments) { $startInfo.ArgumentList.Add($arg) }
    } else {
        # Scheduled arguments are switches, dates and Windows paths. The
        # latter cannot contain a literal quote and may contain spaces.
        $startInfo.Arguments = ($CliArguments.ForEach({ '"' + ($_ -replace '(\\+)$', '$1$1') + '"' })) -join ' '
    }
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) { throw 'Could not start the local collector.' }
        # Drain both anonymous pipes without saving any provider output.
        $stdout = $process.StandardOutput.BaseStream.CopyToAsync([IO.Stream]::Null)
        $stderr = $process.StandardError.BaseStream.CopyToAsync([IO.Stream]::Null)
        $process.WaitForExit()
        [void]$stdout.GetAwaiter().GetResult()
        [void]$stderr.GetAwaiter().GetResult()
        return $process.ExitCode
    } finally {
        $process.Dispose()
    }
}

if ($RunCollector) {
    if (-not $PSCmdlet.ShouldProcess($repo, 'Collect local market snapshot')) { return }
    $started = Beijing-Now
    $logFolder = if ($ShadowDirectory) { $ShadowDirectory } else { Join-Path $env:LOCALAPPDATA 'ResearchRadar\short-term' }
    New-Item -ItemType Directory -Path $logFolder -Force | Out-Null
    $log = Join-Path $logFolder ($started.ToString('yyyy-MM') + '.log')
    $day = $started.ToString('yyyy-MM-dd')
    $rc = 0
    $state = 'before_target'
    if ($Through -and $started.Date -gt $Through.Date) { return }
    if ($started.TimeOfDay -ge [TimeSpan]::FromMinutes(1050)) {
        $cli = @('-B', $collector, '--date', $day, '--evening', '--receipt-dir', (Join-Path $logFolder 'runs'))
        if ($RadarData) { $cli += @('--radar-data', $RadarData) }
        if ($SkipEgo) { $cli += '--skip-ego' }
        if ($ShadowDirectory) {
            $cli += @('--output', (Join-Path $ShadowDirectory 'history.json'), '--preview-dir', (Join-Path $ShadowDirectory 'pages'))
            $whitelist = Join-Path $ShadowDirectory 'kol.toml'
            $calendar = Join-Path $ShadowDirectory 'jin10-week.json'
            if (Test-Path -LiteralPath $whitelist -PathType Leaf) { $env:SHORT_TERM_KOL_WHITELIST_FILE = $whitelist }
            if (-not $env:JIN10_MCP_TOKEN -and (Test-Path -LiteralPath $calendar -PathType Leaf)) {
                $env:SHORT_TERM_JIN10_CALENDAR_FILE = $calendar
            }
        }
        try {
            $rc = Invoke-LocalCollector $python $repo $cli
            $state = switch ($rc) { 0 { 'read_receipt' } 2 { 'stale' } 3 { 'kept_better_same_day' } default { 'failed' } }
        } catch {
            $state = 'launcher_failed'
            $rc = 1
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
if ($ShadowDirectory) { $actionArgs += ' -ShadowDirectory "{0}"' -f $ShadowDirectory }
if ($Through) { $actionArgs += ' -Through {0:yyyy-MM-dd}' -f $Through }

$startDate = (Beijing-Now).ToString('yyyy-MM-dd') + 'T18:15:00+08:00'
$endBoundary = if ($Through) { '<EndBoundary>{0:yyyy-MM-dd}T00:00:00+08:00</EndBoundary>' -f $Through.AddDays(1) } else { '' }
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$xml = @"
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Research Radar local preparation and 20:30 snapshot</Description></RegistrationInfo>
  <Triggers><CalendarTrigger>
    <StartBoundary>$startDate</StartBoundary>
    $endBoundary
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
if ($PSCmdlet.ShouldProcess($taskName, 'Register local preparation for the 20:30 Beijing snapshot')) {
    Register-ScheduledTask -TaskName $taskName -Xml $xml -Force:$Replace -ErrorAction Stop | Out-Null
    Write-Output "Registered $taskName"
}
