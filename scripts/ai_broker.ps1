param(
    [ValidateSet("Monitor", "RunOnce", "Preview", "Export", "CheckEdges")]
    [string]$Mode = "Monitor",
    [int]$IntervalMinutes = 0
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectDir = Split-Path -Parent $scriptDir

function Initialize-Environment {
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $script:OutputEncoding = [System.Text.Encoding]::UTF8
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUNBUFFERED = "1"
    foreach ($name in @("FEISHU_TABLE_WEBHOOK_URL", "WECHAT_SUMMARY_WEBHOOK_URL")) {
        $value = [Environment]::GetEnvironmentVariable($name, "Process")
        if ([string]::IsNullOrWhiteSpace($value)) {
            $value = [Environment]::GetEnvironmentVariable($name, "User")
        }
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            Set-Item -Path "Env:$name" -Value $value.Trim()
        }
    }
}

function Get-Config {
    $path = Join-Path $projectDir "analysis_config.json"
    return Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Resolve-ProjectPath {
    param([string]$PathText)
    if ([System.IO.Path]::IsPathRooted($PathText)) {
        return $PathText
    }
    return [System.IO.Path]::GetFullPath((Join-Path $projectDir $PathText))
}

function Get-IntervalMinutes {
    if ($IntervalMinutes -gt 0) {
        return $IntervalMinutes
    }
    $minutes = [double](Get-Config).runtime.monitor_interval_minutes
    if ($minutes -gt 0) {
        return [int][Math]::Round($minutes)
    }
    return 10
}

function Ensure-ArkApiKey {
    $key = [Environment]::GetEnvironmentVariable("ARK_API_KEY", "Process")
    if ([string]::IsNullOrWhiteSpace($key)) {
        $key = [Environment]::GetEnvironmentVariable("ARK_API_KEY", "User")
    }
    if ([string]::IsNullOrWhiteSpace($key)) {
        $key = [Environment]::GetEnvironmentVariable("ARK_API_KEY", "Machine")
    }
    if ([string]::IsNullOrWhiteSpace($key)) {
        throw "ARK_API_KEY is not set."
    }
    $env:ARK_API_KEY = $key.Trim()
}

function Test-EdgeDebugPort {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri ($Url.TrimEnd("/") + "/json/version") -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Ensure-Edges {
    $config = Get-Config
    $browsers = @($config.browsers.PSObject.Properties)
    if ($browsers.Count -eq 0) {
        throw "No browsers configured in analysis_config.json."
    }
    foreach ($browser in $browsers) {
        $url = [string]$browser.Value.cdp_url
        if (-not (Test-EdgeDebugPort -Url $url)) {
            throw "$($browser.Name) Edge is not ready: $url. Start it from the live data export project first."
        }
        Write-Host "$($browser.Name) Edge is ready: $url"
    }
}

function New-LogFile {
    param([string]$Prefix)
    $config = Get-Config
    $dataRoot = Resolve-ProjectPath ([string]$config.data_root)
    $today = Get-Date -Format "yyyyMMdd"
    $now = Get-Date -Format "HHmmss"
    $logDir = Join-Path $dataRoot "$today\logs"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    return Join-Path $logDir "$Prefix-$today-$now.log"
}

function Invoke-LoggedPython {
    param([string[]]$Arguments, [string]$LogPrefix)
    $logFile = New-LogFile -Prefix $LogPrefix
    Write-Host ("Log file: " + $logFile)
    Push-Location $projectDir
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & python -u -m ai_broker.main @Arguments 2>&1 | Tee-Object -FilePath $logFile
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
        Pop-Location
    }
    if ($exitCode -ne 0) {
        throw "Python failed with exit code $exitCode. See log: $logFile"
    }
}

function Invoke-RunOnce {
    Ensure-ArkApiKey
    Ensure-Edges
    Invoke-LoggedPython -LogPrefix "run_once" -Arguments @("--refresh-export", "--call-ai", "--write-table", "--send-table-webhook")
}

function Invoke-Preview {
    Ensure-Edges
    Invoke-LoggedPython -LogPrefix "preview" -Arguments @("--refresh-export", "--limit", "1")
}

function Invoke-Export {
    Ensure-Edges
    Invoke-LoggedPython -LogPrefix "export" -Arguments @("--export-only")
}

function Format-Duration {
    param([TimeSpan]$Duration)
    return "{0:00}:{1:00}:{2:00}" -f [int]$Duration.TotalHours, $Duration.Minutes, $Duration.Seconds
}

function Invoke-Monitor {
    Ensure-ArkApiKey
    Ensure-Edges
    Write-Host "AI broker monitor is running. Close this window or press Ctrl+C to stop." -ForegroundColor Green
    while ($true) {
        $started = Get-Date
        Write-Host ""
        Write-Host ("===== Run started at " + $started.ToString("yyyy-MM-dd HH:mm:ss") + " =====") -ForegroundColor Cyan
        try {
            Invoke-RunOnce
        } catch {
            Write-Host ("Run failed: " + $_.Exception.Message) -ForegroundColor Red
        }
        $intervalSeconds = [Math]::Max(1, (Get-IntervalMinutes) * 60)
        $finished = Get-Date
        Write-Host ("===== Run finished at " + $finished.ToString("yyyy-MM-dd HH:mm:ss") + " =====") -ForegroundColor Green
        Write-Host ("Task runtime: " + (Format-Duration -Duration ($finished - $started)))
        while ((Get-Date) -lt $finished.AddSeconds($intervalSeconds)) {
            $remaining = $finished.AddSeconds($intervalSeconds) - (Get-Date)
            Write-Host -NoNewline ("`rNext run countdown: " + (Format-Duration -Duration $remaining) + " | Close window to stop.   ")
            Start-Sleep -Seconds 1
        }
        Write-Host ""
    }
}

Initialize-Environment
switch ($Mode) {
    "Monitor" { Invoke-Monitor }
    "RunOnce" { Invoke-RunOnce }
    "Preview" { Invoke-Preview }
    "Export" { Invoke-Export }
    "CheckEdges" { Ensure-Edges }
}
