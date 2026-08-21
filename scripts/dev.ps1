[CmdletBinding()]
param(
    [ValidateSet(
        "help",
        "doctor",
        "install",
        "dev",
        "run",
        "test",
        "lint",
        "typecheck",
        "readiness-smoke",
        "dialogue-smoke",
        "chat-smoke",
        "config-smoke",
        "persona-smoke",
        "context-smoke",
        "why-smoke",
        "llm-smoke",
        "llm-setup",
        "nonebot-smoke",
        "startup-smoke",
        "queue-smoke",
        "transport-smoke",
        "online-transport-smoke",
        "console",
        "credential-smoke",
        "docs-check",
        "plugin-check",
        "smoke",
        "verify"
    )]
    [string]$Task = "help",
    [string]$Message = ""
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
        ".env.example",
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
        Write-Step "running mypy for project-owned code"
        Invoke-External $mypy @(
            "--explicit-package-bases",
            "--exclude",
            "research",
            "--ignore-missing-imports",
            "plugins",
            "tests"
        )
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

function Invoke-Doctor {
    $python = Get-ProjectPython
    $exitCode = 0

    Push-Location $Root
    try {
        Write-Step "running local environment doctor"
        & $python -m plugins.wuwa_unified_runtime.smoke doctor
        $exitCode = $LASTEXITCODE
    }
    finally { Pop-Location }

    if ($exitCode -ne 0) {
        Write-Step "Environment doctor did not pass. See diagnostic output above."
        exit $exitCode
    }
}

function Invoke-ChatSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local LLM chat smoke"
        $arguments = @("-m", "plugins.wuwa_unified_runtime.smoke", "chat")
        if (-not [string]::IsNullOrWhiteSpace($Message)) {
            $arguments += @("--message", $Message)
        }
        Invoke-External $python $arguments
    }
    finally { Pop-Location }
}

function Invoke-ReadinessSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running unified local LLM dialogue readiness smoke"
        $arguments = @("-m", "plugins.wuwa_unified_runtime.smoke", "readiness")
        if (-not [string]::IsNullOrWhiteSpace($Message)) {
            $arguments += @("--message", $Message)
        }
        Invoke-External $python $arguments
    }
    finally { Pop-Location }
}

function Invoke-DialogueSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local LLM dialogue acceptance smoke"
        $arguments = @("-m", "plugins.wuwa_unified_runtime.smoke", "dialogue")
        if (-not [string]::IsNullOrWhiteSpace($Message)) {
            $arguments += @("--message", $Message)
        }
        Invoke-External $python $arguments
    }
    finally { Pop-Location }
}

function Invoke-ConfigSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local configuration readiness smoke"
        Invoke-External $python @("-m", "plugins.wuwa_unified_runtime.smoke", "config")
    }
    finally { Pop-Location }
}

function Invoke-PersonaSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local persona readiness smoke"
        Invoke-External $python @("-m", "plugins.wuwa_unified_runtime.smoke", "persona")
    }
    finally { Pop-Location }
}

function Invoke-ContextSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local LLM context smoke"
        $arguments = @("-m", "plugins.wuwa_unified_runtime.smoke", "context")
        if (-not [string]::IsNullOrWhiteSpace($Message)) {
            $arguments += @("--message", $Message)
        }
        Invoke-External $python $arguments
    }
    finally { Pop-Location }
}

function Invoke-WhySmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local LLM decision why smoke"
        $arguments = @("-m", "plugins.wuwa_unified_runtime.smoke", "why")
        if (-not [string]::IsNullOrWhiteSpace($Message)) {
            $arguments += @("--message", $Message)
        }
        Invoke-External $python $arguments
    }
    finally { Pop-Location }
}

function Invoke-LlmSmoke {
    $python = Get-ProjectPython
    $exitCode = 0

    Push-Location $Root
    try {
        Write-Step "running OpenAI-compatible LLM connection smoke"
        & $python -m plugins.wuwa_unified_runtime.smoke llm
        $exitCode = $LASTEXITCODE
    }
    finally { Pop-Location }

    if ($exitCode -ne 0) {
        Write-Step "LLM smoke did not pass. See diagnostic output above."
        exit $LASTEXITCODE
    }
}

function Invoke-LlmSetup {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "printing safe LLM setup checklist"
        Invoke-External $python @("-m", "plugins.wuwa_unified_runtime.smoke", "llm-setup")
    }
    finally { Pop-Location }
}

function Invoke-NoneBotSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running NoneBot plugin load smoke"
        Invoke-External $python @("-m", "plugins.wuwa_unified_runtime.smoke", "nonebot")
    }
    finally { Pop-Location }
}

function Invoke-StartupSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running NoneBot startup dry-run smoke"
        Invoke-External $python @("-m", "plugins.wuwa_unified_runtime.smoke", "startup")
    }
    finally { Pop-Location }
}

function Invoke-QueueSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local send queue worker smoke"
        Invoke-External $python @("-m", "plugins.wuwa_unified_runtime.smoke", "queue")
    }
    finally { Pop-Location }
}

function Invoke-TransportSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local OneBot/NapCat transport smoke"
        Invoke-External $python @("-m", "plugins.wuwa_unified_runtime.smoke", "transport")
    }
    finally { Pop-Location }
}

function Invoke-OnlineTransportSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running read-only online transport smoke"
        Invoke-External $python @("-m", "plugins.wuwa_unified_runtime.smoke", "online-transport")
    }
    finally { Pop-Location }
}

function Invoke-Console {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "starting console chat REPL"
        $arguments = @("-m", "plugins.wuwa_unified_runtime.console_chat")
        if (-not [string]::IsNullOrWhiteSpace($Message)) {
            $arguments += @("--message", $Message)
        }
        Invoke-External $python $arguments
    }
    finally { Pop-Location }
}

function Invoke-CredentialSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running credential health smoke"
        Invoke-External $python @(
            "-m",
            "plugins.wuwa_unified_runtime.sources.credential_health"
        )
    }
    finally { Pop-Location }
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
  doctor        Diagnose Python, NoneBot imports, OneBot adapter, APScheduler, nb CLI, and plugin import.
  install       Install project dependencies with uv sync when available, otherwise pip install -e .
  dev           Start NoneBot for local development.
  run           Start NoneBot using the same runtime command as dev.
  test          Run pytest. Fails until tests exist and pytest is installed.
  lint          Run ruff check. Fails until ruff is installed.
  typecheck     Run mypy. Fails until mypy is installed.
  readiness-smoke Summarize local dialogue, config, context, and next LLM action without real LLM calls.
  dialogue-smoke Validate one local dialogue turn across context, LLM, review, and sender diagnostics. Use -Message to test custom text.
  chat-smoke    Run a local static LLM chat smoke with Shorekeeper persona files. Use -Message to test custom text.
  config-smoke  Validate local persona, knowledge, and LLM readiness config without network calls.
  persona-smoke Validate loaded persona, tone, and safe source refs without calling LLM.
  context-smoke Build local persona/memory/knowledge prompt diagnostics without calling LLM. Use -Message to test custom text.
  why-smoke     Explain policy, reply budget, LLM status, send request, receipt, and audit for one local chat input.
  llm-setup     Print a safe .env checklist and next commands for real LLM onboarding; never writes secrets or calls the provider.
  llm-smoke     Validate configured OpenAI-compatible LLM connection without sending chat messages.
  nonebot-smoke Validate local NoneBot/OneBot plugin import and config without connecting NapCat.
  startup-smoke Initialize NoneBot in a child process, load handlers, then exit without connecting NapCat.
  queue-smoke   Drain a temporary SQLite send queue with fake transport; never connects NapCat or sends QQ messages.
  transport-smoke Validate OneBot/NapCat message segments and fake transport; never connects NapCat or sends QQ messages.
  online-transport-smoke Read current online bot state without calling send APIs; never sends QQ messages.
  console       Interactive console chat through the real runtime pipeline (offline static LLM by default). Use -Message for one-shot non-interactive mode.
  credential-smoke Check cookie/credential expiry and (with --probe) availability; warns when re-login is needed. Never prints secret values.
  docs-check    Verify command docs, runtime specs, and project config pointers exist.
  plugin-check  Verify plugins/ is configured and report whether local plugins exist yet.
  smoke         Verify docs, plugin discovery config, NoneBot import, and nb CLI availability.
  verify        Current-stage verification: docs-check, plugin-check, pytest, then optional lint/typecheck.
"@
}

switch ($Task) {
    "help" { Show-Help }
    "doctor" { Invoke-Doctor }
    "install" { Invoke-Install }
    "dev" { Invoke-Run "dev" }
    "run" { Invoke-Run "run" }
    "test" { Invoke-Test }
    "lint" { Invoke-Lint }
    "typecheck" { Invoke-Typecheck }
    "readiness-smoke" { Invoke-ReadinessSmoke }
    "dialogue-smoke" { Invoke-DialogueSmoke }
    "chat-smoke" { Invoke-ChatSmoke }
    "config-smoke" { Invoke-ConfigSmoke }
    "persona-smoke" { Invoke-PersonaSmoke }
    "context-smoke" { Invoke-ContextSmoke }
    "why-smoke" { Invoke-WhySmoke }
    "llm-smoke" { Invoke-LlmSmoke }
    "llm-setup" { Invoke-LlmSetup }
    "nonebot-smoke" { Invoke-NoneBotSmoke }
    "startup-smoke" { Invoke-StartupSmoke }
    "queue-smoke" { Invoke-QueueSmoke }
    "transport-smoke" { Invoke-TransportSmoke }
    "online-transport-smoke" { Invoke-OnlineTransportSmoke }
    "console" { Invoke-Console }
    "credential-smoke" { Invoke-CredentialSmoke }
    "docs-check" { Invoke-DocsCheck }
    "plugin-check" { Invoke-PluginCheck }
    "smoke" { Invoke-Smoke }
    "verify" { Invoke-Verify }
}

