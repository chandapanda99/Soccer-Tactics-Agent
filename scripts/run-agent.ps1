[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("run", "build", "test")]
    [string]$Action = "run",

    [string]$ListenAddress = "127.0.0.1",

    [ValidateRange(1, 65535)]
    [int]$Port = 8766,

    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendRoot = Join-Path $ProjectRoot "frontend"

function Assert-Command {
    param([Parameter(Mandatory)][string]$Name)

    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH."
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory)][string]$Command,
        [Parameter(ValueFromRemainingArguments)][string[]]$Arguments
    )

    Write-Host "> $Command $($Arguments -join ' ')" -ForegroundColor Cyan
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command $($Arguments -join ' ')"
    }
}

function Sync-Dependencies {
    $UvArguments = @("sync", "--upgrade", "--prerelease", "allow")
    if ($Action -eq "test") {
        $UvArguments += @("--extra", "test")
    }
    Invoke-Checked uv @UvArguments

    Push-Location $FrontendRoot
    try {
        Invoke-Checked npm ci
    }
    finally {
        Pop-Location
    }
}

function Build-Frontend {
    Push-Location $FrontendRoot
    try {
        Invoke-Checked npm run check
        Invoke-Checked npm run build
    }
    finally {
        Pop-Location
    }
}

Assert-Command uv
Assert-Command npm

Push-Location $ProjectRoot
try {
    if (-not $SkipInstall) {
        Sync-Dependencies
    }

    switch ($Action) {
        "build" {
            Build-Frontend
            Invoke-Checked uv build
            Write-Host "Build Complete: frontend/dist and dist" -ForegroundColor DarkGreen
        }
        "test" {
            Invoke-Checked uv run ruff check .
            Invoke-Checked uv run pytest
            Push-Location $FrontendRoot
            try {
                Invoke-Checked npm run check
                Invoke-Checked npm run test
                Invoke-Checked npm run build
            }
            finally {
                Pop-Location
            }
            Write-Host "All checks passed!" -ForegroundColor DarkGreen
        }
        "run" {
            Build-Frontend
            Write-Host "Starting Soccer Tactics Agent at http://${ListenAddress}:$Port ..." -ForegroundColor Green
            Invoke-Checked uv run soccer-tactics serve --host $ListenAddress --port $Port
        }
    }
}
finally {
    Pop-Location
}
