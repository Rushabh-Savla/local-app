# ==============================================================================
# Central Annotator Agent Launcher for Windows PowerShell
# ==============================================================================
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PYTHONPATH = $ScriptDir

# Load .env file if present
$envFile = Join-Path $ScriptDir ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $k = $parts[0].Trim()
            $v = $parts[1].Trim().Trim("'").Trim('"')
            if ($k) {
                [Environment]::SetEnvironmentVariable($k, $v, "Process")
            }
        }
    }
}

# Auto-detect virtualenv
$PythonBin = "python"
if (Test-Path "$ScriptDir\.venv\Scripts\python.exe") {
    $PythonBin = "$ScriptDir\.venv\Scripts\python.exe"
} elseif (Test-Path "$env:VIRTUAL_ENV\Scripts\python.exe") {
    $PythonBin = "$env:VIRTUAL_ENV\Scripts\python.exe"
}

Write-Host "Starting Annotator Desktop Agent using $PythonBin..."
& $PythonBin -m annotator_agent.agent --server-url $env:SERVER_URL --local-root $env:ROOT @ScriptArgs

