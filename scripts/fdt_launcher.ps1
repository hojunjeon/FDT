#Requires -Version 5.1
<#
  FDT 통합 실행기 본체.
  하나의 콘솔에서 서버를 띄우고, 로그를 그 자리에 출력하며, Ctrl+C 로 전체를 종료한다.
#>
[CmdletBinding()]
param(
    [string]$ServerHost = '127.0.0.1',
    [int]$Port = 8787,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$python = Join-Path $root '.venv\Scripts\python.exe'
$logDir = Join-Path $root 'log'
$turnLogDir = Join-Path $logDir 'turns'
$healthUrl = "http://${ServerHost}:${Port}/api/health"
$dashboardUrl = "http://${ServerHost}:${Port}"
$ollamaTags = 'http://127.0.0.1:11434/api/tags'

if (-not $env:FDT_OLLAMA_URL) { $env:FDT_OLLAMA_URL = 'http://127.0.0.1:11434' }
if (-not $env:FDT_LLM_MODEL) { $env:FDT_LLM_MODEL = 'qwen2.5:7b-instruct-q4_K_M' }

function Test-HttpMarker {
    param([string]$Url, [string]$Marker, [int]$TimeoutSec = 5)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec $TimeoutSec -ErrorAction Stop
        $body = [string]$response.Content
    } catch {
        $body = ''
        if ($_.Exception.Response) {
            try {
                $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $body = $reader.ReadToEnd()
            } catch { }
        }
    }
    if ([string]::IsNullOrEmpty($body)) { return $false }
    return ($body.IndexOf($Marker, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
}

function Test-PortListening {
    param([int]$TcpPort)
    try {
        $listeners = [Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
        return [bool]($listeners | Where-Object { $_.Port -eq $TcpPort })
    } catch { return $false }
}

function New-LogFilePath {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $stamp = Get-Date -Format 'yyMMdd-HHmm'
    $candidate = Join-Path $logDir "$stamp.log"
    $index = 1
    while (Test-Path -LiteralPath $candidate) {
        $candidate = Join-Path $logDir ("{0}-{1}.log" -f $stamp, $index)
        $index++
    }
    return $candidate
}

Write-Host '======================================================'
Write-Host '  FDT 통합 실행기 - 로컬 대시보드'
Write-Host '======================================================'
Write-Host ''

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "[오류] Python 가상환경을 찾을 수 없습니다: $python"
    Write-Host '       먼저 .venv 를 만든 뒤 다시 실행하세요.'
    exit 1
}

if (Test-HttpMarker -Url $healthUrl -Marker 'fdt-local-dashboard' -TimeoutSec 5) {
    Write-Host '[안내] FDT 서버가 이미 실행 중입니다. 새 서버를 띄우지 않습니다.'
    if (-not $NoBrowser) { Start-Process $dashboardUrl | Out-Null }
    exit 0
}

if (Test-PortListening -TcpPort $Port) {
    Write-Host "[오류] 포트 $Port 가 다른 프로세스에 의해 사용 중입니다."
    Write-Host '       기존 프로세스를 종료하지 않았습니다. 확인한 뒤 다시 실행하세요.'
    exit 2
}

$ollamaProcess = $null
Write-Host '[확인] Ollama 상태 확인 중...'
if (Test-HttpMarker -Url $ollamaTags -Marker 'models' -TimeoutSec 2) {
    Write-Host '[확인] Ollama 가 이미 실행 중입니다. 이 실행기는 종료 시 건드리지 않습니다.'
} elseif (Test-PortListening -TcpPort 11434) {
    Write-Host '[경고] 11434 포트를 Ollama 가 아닌 다른 프로세스가 쓰고 있습니다. template fallback 으로 계속합니다.'
} elseif (-not (Get-Command 'ollama.exe' -ErrorAction SilentlyContinue)) {
    Write-Host '[경고] Ollama 를 찾지 못했습니다. template fallback 으로 계속합니다.'
} else {
    Write-Host '[안내] Ollama 가 꺼져 있어 함께 시작합니다. 이 창을 종료하면 같이 종료됩니다.'
    try {
        $ollamaProcess = Start-Process -FilePath 'ollama.exe' -ArgumentList 'serve' -WindowStyle Hidden -PassThru
    } catch {
        Write-Host "[경고] Ollama 시작에 실패했습니다: $($_.Exception.Message)"
    }
    $ready = $false
    for ($i = 0; $i -lt 15; $i++) {
        if (Test-HttpMarker -Url $ollamaTags -Marker 'models' -TimeoutSec 2) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if ($ready) { Write-Host '[확인] Ollama 가 준비되었습니다.' }
    else { Write-Host '[경고] Ollama 준비 대기 시간이 지났습니다. template fallback 으로 계속합니다.' }
}

if (Test-HttpMarker -Url $ollamaTags -Marker 'models' -TimeoutSec 2) {
    $hasModel = $false
    try {
        $tags = Invoke-WebRequest -UseBasicParsing -Uri $ollamaTags -TimeoutSec 2 -ErrorAction Stop
        $names = ($tags.Content | ConvertFrom-Json).models | ForEach-Object { [string]$_.name }
        $hasModel = ($names -contains $env:FDT_LLM_MODEL)
    } catch { }
    if (-not $hasModel) {
        Write-Host "[경고] 모델 '$($env:FDT_LLM_MODEL)' 이 없어 template fallback 으로 동작할 수 있습니다. 자동 pull 은 하지 않습니다."
    }
}

$logFile = New-LogFilePath
Write-Host ''
Write-Host "[시작] FDT 서버: $dashboardUrl"
Write-Host "[로그] 이 창에 실시간 출력, 파일 저장: $logFile"
Write-Host "[로그] 턴 JSONL 디렉터리: $turnLogDir"
Write-Host '[안내] 종료하려면 이 창에서 Ctrl+C 를 누르세요.'
Write-Host ''

if (-not $NoBrowser) {
    $openerScript = @"
`$ErrorActionPreference='SilentlyContinue'
for (`$i=0; `$i -lt 40; `$i++) {
    try {
        `$r = Invoke-WebRequest -UseBasicParsing -Uri '$healthUrl' -TimeoutSec 2 -ErrorAction Stop
        if (([string]`$r.Content).IndexOf('fdt-local-dashboard') -ge 0) { Start-Process '$dashboardUrl'; break }
    } catch { }
    Start-Sleep -Seconds 1
}
"@
    Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -ArgumentList @(
        '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', $openerScript) | Out-Null
}

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $python
$startInfo.Arguments = "-u -m fdt.cli serve --host $ServerHost --port $Port"
$startInfo.WorkingDirectory = $root
$startInfo.UseShellExecute = $false
$startInfo.CreateNoWindow = $true
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$startInfo.StandardOutputEncoding = [System.Text.Encoding]::UTF8
$startInfo.StandardErrorEncoding = [System.Text.Encoding]::UTF8
$startInfo.EnvironmentVariables['PYTHONIOENCODING'] = 'utf-8'
$startInfo.EnvironmentVariables['PYTHONUTF8'] = '1'

$queue = New-Object 'System.Collections.Concurrent.ConcurrentQueue[string]'
$server = New-Object System.Diagnostics.Process
$server.StartInfo = $startInfo
$sink = { if ($null -ne $EventArgs.Data) { $Event.MessageData.Enqueue([string]$EventArgs.Data) } }
$subscriptions = @()
$writer = $null
$treatCtrlC = $false
$exitCode = 0

try {
    $writer = New-Object System.IO.StreamWriter($logFile, $true, (New-Object System.Text.UTF8Encoding($false)))
    $writer.AutoFlush = $true

    $subscriptions += Register-ObjectEvent -InputObject $server -EventName OutputDataReceived -Action $sink -MessageData $queue
    $subscriptions += Register-ObjectEvent -InputObject $server -EventName ErrorDataReceived -Action $sink -MessageData $queue

    [void]$server.Start()
    $server.BeginOutputReadLine()
    $server.BeginErrorReadLine()

    try { [Console]::TreatControlCAsInput = $true; $treatCtrlC = $true } catch { $treatCtrlC = $false }

    $stopRequested = $false
    while (-not $server.HasExited) {
        $line = $null
        while ($queue.TryDequeue([ref]$line)) {
            Write-Host $line
            $writer.WriteLine($line)
        }
        if ($treatCtrlC) {
            try {
                while ([Console]::KeyAvailable) {
                    $key = [Console]::ReadKey($true)
                    if ($key.Key -eq [ConsoleKey]::C -and ($key.Modifiers -band [ConsoleModifiers]::Control)) {
                        $stopRequested = $true
                    }
                }
            } catch { $treatCtrlC = $false }
        }
        if ($stopRequested) { break }
        Start-Sleep -Milliseconds 120
    }

    if ($stopRequested) {
        Write-Host ''
        Write-Host '[종료] Ctrl+C 를 받았습니다. 서버를 종료합니다...'
        if (-not $server.HasExited) {
            try { Stop-Process -Id $server.Id -Force -ErrorAction Stop } catch { }
        }
    }
    [void]$server.WaitForExit(5000)

    $line = $null
    while ($queue.TryDequeue([ref]$line)) {
        Write-Host $line
        $writer.WriteLine($line)
    }
    if ($server.HasExited) { $exitCode = $server.ExitCode }
    if ($stopRequested) { $exitCode = 0 }
} finally {
    if ($treatCtrlC) { try { [Console]::TreatControlCAsInput = $false } catch { } }
    foreach ($subscription in $subscriptions) {
        try { Unregister-Event -SubscriptionId $subscription.Id -ErrorAction SilentlyContinue } catch { }
    }
    if ($null -ne $ollamaProcess) {
        try {
            if (-not $ollamaProcess.HasExited) {
                Write-Host '[종료] 함께 시작한 Ollama 를 종료합니다...'
                Stop-Process -Id $ollamaProcess.Id -Force -ErrorAction SilentlyContinue
            }
        } catch { }
    }
    if ($null -ne $writer) { try { $writer.Dispose() } catch { } }
    try { $server.Dispose() } catch { }
}

Write-Host "[완료] 종료했습니다. 서버 로그: $logFile"
exit $exitCode
