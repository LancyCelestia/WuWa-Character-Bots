[CmdletBinding()]
param(
    [ValidateSet(
        "help",
        "install",
        "dev",
        "run",
        "test",
        "lint",
        "typecheck",
        "docs-check",
        "plugin-check",
        "smoke",
        "verify"
    )]
    [string]$Task = "help"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Write-Step {
    param([string]$Message)
    Write-Host "[dev] $Message"
}

function Get-ProjectCommand {
    param([string]$Name)

    $venvExe = Join-Path $Root ".venv\Scripts\$Name.exe"
    if (Test-Path -LiteralPath $venvExe) { return $venvExe }

    $venvCmd = Join-Path $Root ".venv\Scripts\$Name.cmd"
    if (Test-Path -LiteralPath $venvCmd) { return $venvCmd }

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }

    return $null
}

function Get-ProjectPython {
    $python = Get-ProjectCommand "python"
    if ($python) { return $python }

    $py = Get-Command "py" -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }

    throw "Python was not found. Install Python 3.10+ or activate the project virtual environment."
}

function Invoke-External {
    param(
        [string]$FilePath,
        [string[]]$Arguments = @()
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE."
    }
}

function Assert-PathExists {
    param([string]$RelativePath)

    $path = Join-Path $Root $RelativePath
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required path is missing: $RelativePath"
    }
}

function Assert-FileContains {
    param(
        [string]$RelativePath,
        [string]$Needle
    )

    $path = Join-Path $Root $RelativePath
    if (-not (Select-String -LiteralPath $path -SimpleMatch $Needle -Quiet)) {
        throw "Required text was not found in ${RelativePath}: $Needle"
    }
}

function Invoke-DocsCheck {
    Write-Step "checking command and contract documents"

    $required = @(
        "README.md",
        "COMMANDS.md",
        "pyproject.toml",
        ".env.prod",
        "plugins",
        "research\README.md",
        "research\architecture_report.md",
        "research\implementation_design_supplement.md",
        "docs\specs\runtime-parameter-flow.md",
        "docs\specs\input-output-contracts.md",
        "docs\specs\auto-send-capability.md",
        "docs\specs\character-intelligence-and-knowledge.md",
        "docs\specs\media-source-pipeline.md"
    )

    foreach ($item in $required) { Assert-PathExists $item }

    Assert-FileContains "README.md" "COMMANDS.md"
    Assert-FileContains "COMMANDS.md" "scripts/dev.ps1 verify"
    Assert-FileContains "pyproject.toml" 'plugin_dirs = ["plugins"]'
    Assert-FileContains "pyproject.toml" 'builtin_plugins = ["echo"]'
    Assert-FileContains "docs\specs\runtime-parameter-flow.md" "IncomingMessage -> PolicyEvaluation -> BotDecision -> CapabilityResult"
    Assert-FileContains "docs\specs\input-output-contracts.md" "CapabilityResult"
    Assert-FileContains "docs\specs\auto-send-capability.md" "AutoSendIntent"
    Assert-FileContains "docs\specs\character-intelligence-and-knowledge.md" "EmotionSignal"
    Assert-FileContains "docs\specs\character-intelligence-and-knowledge.md" "Knowledge Ingestion Pipeline"
    Assert-FileContains "docs\specs\media-source-pipeline.md" "SourceAdapter -> FetchRequest -> FetchResult"
    Assert-FileContains "docs\specs\media-source-pipeline.md" "ParserRegistry"
    Assert-FileContains "docs\specs\media-source-pipeline.md" "TemplateCatalog"

    Write-Step "docs-check passed"
}

function Invoke-PluginCheck {
    Write-Step "checking local plugin discovery contract"

    Assert-PathExists "plugins"
    Assert-FileContains "pyproject.toml" 'plugin_dirs = ["plugins"]'
    Assert-PathExists "plugins\wuwa_unified_runtime\__init__.py"
    Assert-PathExists "plugins\wuwa_unified_runtime\contracts\runtime.py"

    $pluginFiles = Get-ChildItem -LiteralPath (Join-Path $Root "plugins") -Recurse -File -Include "*.py" -ErrorAction SilentlyContinue
    if (-not $pluginFiles -or $pluginFiles.Count -eq 0) {
        throw "No local plugin Python files exist."
    }

    Write-Step "found wuwa_unified_runtime and $($pluginFiles.Count) local plugin Python file(s)"
}

function Invoke-Install {
    $uv = Get-ProjectCommand "uv"
    Push-Location $Root
    try {
        if ($uv) {
            Write-Step "installing dependencies with uv sync"
            Invoke-External $uv @("sync")
            return
        }

        $python = Get-ProjectPython
        Write-Step "installing dependencies with pip editable install"
        Invoke-External $python @("-m", "pip", "install", "-e", ".")
    }
    finally { Pop-Location }
}

function Invoke-Run {
    param([string]$Mode)

    $nb = Get-ProjectCommand "nb"
    if (-not $nb) {
        throw "NoneBot CLI 'nb' was not found. Run scripts/dev.ps1 install first."
    }

    Push-Location $Root
    try {
        Write-Step "starting NoneBot ($Mode)"
        Invoke-External $nb @("run")
    }
    finally { Pop-Location }
}

function Invoke-Test {
    if (-not (Test-Path -LiteralPath (Join-Path $Root "tests"))) {
        throw "No tests directory exists yet. Add tests before using the test task."
    }

    $python = Get-ProjectPython
    $pytest = Get-ProjectCommand "pytest"

    Push-Location $Root
    try {
        Write-Step "running pytest"
        $hasProjectPytest = $false
        try {
            & $python -c "import pytest" *> $null
            $hasProjectPytest = ($LASTEXITCODE -eq 0)
        }
        catch {
            $hasProjectPytest = $false
        }

        if ($hasProjectPytest) {
            Invoke-External $python @("-m", "pytest")
            return
        }

        if (-not $pytest) {
            throw "pytest was not found. Add/install test dependencies before using the test task."
        }

        $oldPythonPath = $env:PYTHONPATH
        if ($oldPythonPath) {
            $env:PYTHONPATH = "$Root;$oldPythonPath"
        }
        else {
            $env:PYTHONPATH = $Root
        }
        try {
            Invoke-External $pytest @()
        }
        finally {
            $env:PYTHONPATH = $oldPythonPath
        }
    }
    finally { Pop-Location }
}

function Invoke-Lint {
    $ruff = Get-ProjectCommand "ruff"
    if (-not $ruff) {
        throw "ruff was not found. Add/install lint dependencies before using the lint task."
    }

    Push-Location $Root
    try {
        Write-Step "running ruff check"
        Invoke-External $ruff @("check", ".")
    }
    finally { Pop-Location }
}

function Invoke-Typecheck {
    $mypy = Get-ProjectCommand "mypy"
    if (-not $mypy) {
        throw "mypy was not found. Add/install typecheck dependencies before using the typecheck task."
    }

    Push-Location $Root
    try {
        Write-Step "running mypy"
        Invoke-External $mypy @(".")
    }
    finally { Pop-Location }
}

function Invoke-Smoke {
    Invoke-DocsCheck
    Invoke-PluginCheck

    $python = Get-ProjectPython
    Write-Step "checking NoneBot import"
    Invoke-External $python @("-c", "from importlib.metadata import version; print('nonebot2', version('nonebot2'))")

    $nb = Get-ProjectCommand "nb"
    if (-not $nb) {
        throw "NoneBot CLI 'nb' was not found. Run scripts/dev.ps1 install first."
    }

    Write-Step "checking NoneBot CLI"
    Invoke-External $nb @("--version")
}

function Invoke-Verify {
    Invoke-DocsCheck
    Invoke-PluginCheck

    if (Test-Path -LiteralPath (Join-Path $Root "tests")) {
        Invoke-Test
    }
    else {
        Write-Warning "Skipping tests because no tests directory exists yet."
    }

    if (Get-ProjectCommand "ruff") {
        Invoke-Lint
    }
    else {
        Write-Warning "Skipping lint because ruff is not installed."
    }

    if (Get-ProjectCommand "mypy") {
        Invoke-Typecheck
    }
    else {
        Write-Warning "Skipping typecheck because mypy is not installed."
    }

    Write-Step "verify completed for the current documentation/spec stage"
}

function Show-Help {
    @"
Usage:
  powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 <task>

Tasks:
  help          Show this help.
  install       Install project dependencies with uv sync when available, otherwise pip install -e .
  dev           Start NoneBot for local development.
  run           Start NoneBot using the same runtime command as dev.
  test          Run pytest. Fails until tests exist and pytest is installed.
  lint          Run ruff check. Fails until ruff is installed.
  typecheck     Run mypy. Fails until mypy is installed.
  docs-check    Verify command docs, runtime specs, and project config pointers exist.
  plugin-check  Verify plugins/ is configured and report whether local plugins exist yet.
  smoke         Verify docs, plugin discovery config, NoneBot import, and nb CLI availability.
  verify        Current-stage verification: docs-check, plugin-check, pytest, then optional lint/typecheck.
"@
}

switch ($Task) {
    "help" { Show-Help }
    "install" { Invoke-Install }
    "dev" { Invoke-Run "dev" }
    "run" { Invoke-Run "run" }
    "test" { Invoke-Test }
    "lint" { Invoke-Lint }
    "typecheck" { Invoke-Typecheck }
    "docs-check" { Invoke-DocsCheck }
    "plugin-check" { Invoke-PluginCheck }
    "smoke" { Invoke-Smoke }
    "verify" { Invoke-Verify }
}

