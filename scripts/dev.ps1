[CmdletBinding()]
param(
    [ValidateSet(
        "help",
        "doctor",
        "install",
        "dev",
        "run",
        "run-watch",
        "test",
        "lint",
        "typecheck",
        "readiness-smoke",
        "dialogue-smoke",
        "chat-smoke",
        "backend-smoke",
        "prompt-preview",
        "backend-base-smoke",
        "config-smoke",
        "runtime-layout",
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
        "embedding-smoke",
        "knowledge-sync",
        "gscore-smoke",
        "route-demo",
        "route-smoke",
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
$RuntimeRoot = Join-Path (Split-Path -Parent $Root) "ChatBot_Runtime"
$RuntimeVenv = Join-Path $RuntimeRoot "venv"
# Keep Python bytecode caches out of the AI workspace.
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = $utf8
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

function Write-Step {
    param([string]$Message)
    Write-Host "[dev] $Message"
}

function Get-ProjectCommand {
    param([string]$Name)

    # The runtime venv is deliberately outside the AI source workspace.
    $candidates = @(
        (Join-Path $RuntimeVenv "Scripts\$Name.exe"),
        (Join-Path $RuntimeVenv "Scripts\$Name.cmd"),
        (Join-Path $Root ".venv\Scripts\$Name.exe"),
        (Join-Path $Root ".venv\Scripts\$Name.cmd")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }

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
    Write-Step "checking minimal command and runtime documents"

    $required = @(
        "README.md",
        "COMMANDS.md",
        "pyproject.toml",
        ".env.example",
        ".env.prod",
        "plugins",
        "docs\route-matrix.md",
        "docs\workspace-archive-policy.md",
        "docs\external-runtime-access.md"
    )

    foreach ($item in $required) { Assert-PathExists $item }

    Assert-FileContains "README.md" "COMMANDS.md"
    Assert-FileContains "README.md" "ChatBot_Archive"
    Assert-FileContains "COMMANDS.md" "scripts/dev.ps1 verify"
    Assert-FileContains "pyproject.toml" 'plugin_dirs = ["plugins"]'
    Assert-FileContains "pyproject.toml" 'builtin_plugins = ["echo"]'
    Assert-FileContains "docs\workspace-archive-policy.md" "ChatBot_Archive"
    Assert-FileContains "docs\external-runtime-access.md" "LOCALSTORE_USE_CWD"
    Assert-FileContains "docs\route-matrix.md" "route"

    Write-Step "docs-check passed"
}
function Invoke-PluginCheck {
    Write-Step "checking local plugin discovery contract"

    Assert-PathExists "plugins"
    Assert-FileContains "pyproject.toml" 'plugin_dirs = ["plugins"]'
    Assert-PathExists "plugins\bot_unified_runtime\__init__.py"
    Assert-PathExists "plugins\bot_unified_runtime\contracts\runtime.py"

    $pluginFiles = Get-ChildItem -LiteralPath (Join-Path $Root "plugins") -Recurse -File -Include "*.py" -ErrorAction SilentlyContinue
    if (-not $pluginFiles -or $pluginFiles.Count -eq 0) {
        throw "No local plugin Python files exist."
    }

    Write-Step "found bot_unified_runtime and $($pluginFiles.Count) local plugin Python file(s)"
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

    $python = Get-ProjectPython

    Push-Location $Root
    try {
        $portInUse = Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue
        if ($portInUse) {
            Write-Host "[dev] NoneBot 已经在运行（8080 端口被占用）。不要重复启动；如需重启请先关闭原进程。"
            return
        }
        Write-Step "starting NoneBot ($Mode)"
        Invoke-External $python @("bot.py")
    }
    finally { Pop-Location }
}

function Invoke-RunWatch {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        while ($true) {
            $portInUse = Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue
            if ($portInUse) {
                Write-Host "[dev] NoneBot 已经在运行（8080 端口被占用）。不要重复启动；如需重启请先关闭原进程。"
                return
            }
            Write-Step "starting NoneBot (run-watch, auto-restart on exit)"
            & $python "bot.py"
            Write-Host "[dev] NoneBot 退出（exit code = $LASTEXITCODE），5 秒后自动重启。按 Ctrl+C 退出本循环。"
            Start-Sleep -Seconds 5
        }
    }
    finally { Pop-Location }
}

function Invoke-Test {
    if (-not (Test-Path -LiteralPath (Join-Path $Root "tests"))) {
        throw "The pytest suite is archived outside the workspace. Restore tests/ from development-materials-2026-08-28.tar.gz before using the test task."
    }

    $python = Get-ProjectPython
    $pytest = Get-ProjectCommand "pytest"

    Push-Location $Root
    $oldTmp = $env:TMP
    $oldTemp = $env:TEMP
    $oldTmpRoot = $env:PYTEST_DEBUG_TEMPROOT
    $ciTmp = Join-Path $RuntimeRoot ("cache\pytest_ci_" + $PID)
    New-Item -ItemType Directory -Force -Path $ciTmp | Out-Null
    $env:TMP = $ciTmp
    $env:TEMP = $ciTmp
    # Keep pytest's numbered temp root inside this per-run dir: the shared
    # %TEMP%\pytest-of-<user> root contains a corrupt cyclic pytest-current
    # symlink with a denied ACL that crashes pytest sessionfinish cleanup.
    $env:PYTEST_DEBUG_TEMPROOT = $ciTmp
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
            Invoke-External $python @("-X", "faulthandler", "-m", "pytest", "-p", "no:cacheprovider", "--basetemp", (Join-Path $ciTmp "basetemp"))
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
            Invoke-External $pytest @("-p", "no:cacheprovider", "--basetemp", (Join-Path $ciTmp "basetemp"))
        }
        finally {
            $env:PYTHONPATH = $oldPythonPath
        }
    }
    finally {
        $env:TMP = $oldTmp
        $env:TEMP = $oldTemp
        $env:PYTEST_DEBUG_TEMPROOT = $oldTmpRoot
        if (Test-Path -LiteralPath $ciTmp) {
            Remove-Item -LiteralPath $ciTmp -Recurse -Force -ErrorAction SilentlyContinue
        }
        Pop-Location
    }
}

function Invoke-Lint {
    $ruff = Get-ProjectCommand "ruff"
    if (-not $ruff) {
        throw "ruff was not found. Add/install lint dependencies before using the lint task."
    }
    $ruffCache = Join-Path $RuntimeRoot "cache\ruff"
    New-Item -ItemType Directory -Force -Path $ruffCache | Out-Null

    Push-Location $Root
    try {
        Write-Step "running ruff check (cache outside workspace)"
        Invoke-External $ruff @("check", "--cache-dir", $ruffCache, ".")
    }
    finally { Pop-Location }
}


function Invoke-Typecheck {
    # Invoke mypy through the selected Python interpreter. The Windows mypy.exe
    # launcher can retain the original venv path after the venv is moved outside
    # the source workspace; python -m mypy avoids that stale launcher metadata.
    $python = Get-ProjectPython
    & $python -c "import mypy" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "mypy was not found in the selected Python environment. Add/install typecheck dependencies before using the typecheck task."
    }
    $mypyCache = Join-Path $RuntimeRoot "cache\mypy"
    New-Item -ItemType Directory -Force -Path $mypyCache | Out-Null

    Push-Location $Root
    try {
        Write-Step "running mypy for project-owned code (cache outside workspace)"
        Invoke-External $python @(
            "-m",
            "mypy",
            "--cache-dir",
            $mypyCache,
            "--explicit-package-bases",
            "--ignore-missing-imports",
            "plugins"
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
        & $python -m plugins.bot_unified_runtime.smoke doctor
        $exitCode = $LASTEXITCODE
    }
    finally { Pop-Location }

    if ($exitCode -ne 0) {
        Write-Step "Environment doctor did not pass. See diagnostic output above."
        exit $exitCode
    }
}

function Invoke-BackendBaseSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running offline backend base smoke"
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.smoke", "nonebot")
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.smoke", "startup")
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.smoke", "transport")
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.backend_unit", "--message", $(if ($Message) { $Message } else { "测试后端底座" }))
    }
    finally { Pop-Location }
}
function Invoke-PromptPreview {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        if ([string]::IsNullOrWhiteSpace($Message)) {
            throw "prompt-preview requires -Message."
        }
        Write-Step "building redacted prompt preview without calling LLM"
        Invoke-External $python @(
            "-m",
            "plugins.bot_unified_runtime.runtime.prompt_preview",
            "--message",
            $Message,
            "--write"
        )
    }
    finally { Pop-Location }
}
function Invoke-BackendSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running one-shot offline backend core execution unit"
        $arguments = @("-m", "plugins.bot_unified_runtime.backend_unit", "--message", $(if ($Message) { $Message } else { "测试后端主链路" }))
        Invoke-External $python $arguments
    }
    finally { Pop-Location }
}
function Invoke-ChatSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local LLM chat smoke"
        $arguments = @("-m", "plugins.bot_unified_runtime.smoke", "chat")
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
        $arguments = @("-m", "plugins.bot_unified_runtime.smoke", "readiness")
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
        $arguments = @("-m", "plugins.bot_unified_runtime.smoke", "dialogue")
        if (-not [string]::IsNullOrWhiteSpace($Message)) {
            $arguments += @("--message", $Message)
        }
        Invoke-External $python $arguments
    }
    finally { Pop-Location }
}

function Invoke-RuntimeLayout {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "checking external runtime data boundary"
        Invoke-External $python @("scripts\runtime_layout_smoke.py")
    }
    finally { Pop-Location }
}

function Invoke-ConfigSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local configuration readiness smoke"
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.smoke", "config")
    }
    finally { Pop-Location }
}

function Invoke-PersonaSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local persona readiness smoke"
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.smoke", "persona")
    }
    finally { Pop-Location }
}

function Invoke-ContextSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local LLM context smoke"
        $arguments = @("-m", "plugins.bot_unified_runtime.smoke", "context")
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
        $arguments = @("-m", "plugins.bot_unified_runtime.smoke", "why")
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
        & $python -m plugins.bot_unified_runtime.smoke llm
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
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.smoke", "llm-setup")
    }
    finally { Pop-Location }
}

function Invoke-NoneBotSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running NoneBot plugin load smoke"
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.smoke", "nonebot")
    }
    finally { Pop-Location }
}

function Invoke-StartupSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running NoneBot startup dry-run smoke"
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.smoke", "startup")
    }
    finally { Pop-Location }
}

function Invoke-QueueSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local send queue worker smoke"
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.smoke", "queue")
    }
    finally { Pop-Location }
}

function Invoke-TransportSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running local OneBot/NapCat transport smoke"
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.smoke", "transport")
    }
    finally { Pop-Location }
}

function Invoke-OnlineTransportSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running read-only online transport smoke"
        Invoke-External $python @("-m", "plugins.bot_unified_runtime.smoke", "online-transport")
    }
    finally { Pop-Location }
}

function Invoke-Console {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "starting console chat REPL"
        $arguments = @("-m", "plugins.bot_unified_runtime.console_chat")
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
            "plugins.bot_unified_runtime.sources.credential_health"
        )
    }
    finally { Pop-Location }
}

function Invoke-EmbeddingSmoke {
    $python = Get-ProjectPython
    $exitCode = 0

    Push-Location $Root
    try {
        Write-Step "running OpenAI-compatible embeddings connection smoke"
        & $python -m plugins.bot_unified_runtime.smoke embedding
        $exitCode = $LASTEXITCODE
    }
    finally { Pop-Location }

    if ($exitCode -ne 0) {
        Write-Step "Embedding smoke did not pass. See diagnostic output above."
        exit $LASTEXITCODE
    }
}

function Invoke-KnowledgeSync {
    $python = Get-ProjectPython
    $exitCode = 0

    Push-Location $Root
    try {
        Write-Step "pre-warming vector knowledge base from BOT_KNOWLEDGE_FILES"
        & $python -m plugins.bot_unified_runtime.smoke knowledge-sync
        $exitCode = $LASTEXITCODE
    }
    finally { Pop-Location }

    if ($exitCode -ne 0) {
        Write-Step "Knowledge sync did not finish. See diagnostic output above."
        exit $LASTEXITCODE
    }
}

function Invoke-GscoreSmoke {
    $python = Get-ProjectPython

    Push-Location $Root
    try {
        Write-Step "running GsCore bridge readiness smoke"
        Invoke-External $python @(
            "-m",
            "plugins.bot_unified_runtime.sources.gscore_bridge"
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
        Write-Warning "Skipping tests because tests/ is intentionally archived outside the AI workspace."
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
    Write-Output @(
        'Usage:'
        '  powershell -NoProfile -ExecutionPolicy Bypass -Command "& .\scripts\dev.ps1 -Task <task>"'
        ''
        'Tasks:'
        '  help          Show this help.'
        '  doctor        Diagnose Python, NoneBot imports, OneBot adapter, APScheduler, nb CLI, and plugin import.'
        '  install       Install project dependencies with uv sync when available, otherwise pip install -e .'
        '  dev           Start NoneBot for local development.'
        '  run           Start NoneBot using the same runtime command as dev.'
        '  run-watch     Start NoneBot with auto-restart (restarts 5s after exit).'
        '  test          Run the retained regression tests; fails if tests or pytest are unavailable.'
        '  lint          Run ruff check. Fails until ruff is installed.'
        '  typecheck     Run mypy. Fails until mypy is installed.'
        '  readiness-smoke Summarize local dialogue, config, context, and next LLM action without real LLM calls.'
        '  dialogue-smoke Validate one local dialogue turn across context, LLM, review, and sender diagnostics. Use -Message to test custom text.'
        '  chat-smoke    Run a local static LLM chat smoke with Shorekeeper persona files. Use -Message to test custom text.'
        '  backend-smoke Run one offline backend core execution through RuntimePipeline.'
        '  prompt-preview Run and save a redacted LLM prompt preview without calling LLM.'
        '  backend-base-smoke Run NoneBot/startup/transport/backend offline base checks.'
        '  config-smoke  Validate local persona, knowledge, and LLM readiness config without network calls.'
        '  runtime-layout Verify Runtime/external-data boundary and ensure source has no generated state.'
        '  persona-smoke Validate loaded persona, tone, and safe source refs without calling LLM.'
        '  context-smoke Build local persona/memory/knowledge prompt diagnostics without calling LLM. Use -Message to test custom text.'
        '  why-smoke     Explain policy, reply budget, LLM status, send request, receipt, and audit for one local chat input.'
        '  llm-setup     Print a safe .env checklist and next commands for real LLM onboarding; never writes secrets or calls the provider.'
        '  llm-smoke     Validate configured OpenAI-compatible LLM connection without sending chat messages.'
        '  nonebot-smoke Validate local NoneBot/OneBot plugin import and config without connecting NapCat.'
        '  startup-smoke Initialize NoneBot in a child process, load handlers, then exit without connecting NapCat.'
        '  queue-smoke   Drain a temporary SQLite send queue with fake transport; never connects NapCat or sends QQ messages.'
        '  transport-smoke Validate OneBot/NapCat message segments and fake transport; never connects NapCat or sends QQ messages.'
        '  online-transport-smoke Read current online bot state without calling send APIs; never sends QQ messages.'
        '  console       Interactive console chat through the real runtime pipeline (offline static LLM by default). Use -Message for one-shot non-interactive mode.'
        '  credential-smoke Check cookie/credential expiry and (with --probe) availability; warns when re-login is needed. Never prints secret values.'
        '  embedding-smoke Validate configured OpenAI-compatible embeddings service without touching the knowledge DB.'
        '  knowledge-sync Pre-warm vector knowledge base and write to external Runtime data.'
        '  gscore-smoke   Read-only GsCore bridge readiness check; never connects or sends.'
        '  route-demo     Print the full phrasing routing matrix. Offline, no network, no QQ.'
        '  route-smoke    Run deterministic capabilities against real APIs/services; may use network, never sends QQ.'
        '  docs-check    Verify minimal runtime docs, archive policy, and project config pointers exist.'
        '  plugin-check  Verify plugins/ is configured and report whether local plugins exist yet.'
        '  smoke         Verify docs, plugin discovery, NoneBot import, and nb CLI availability.'
        '  verify        Verify docs, plugin discovery, retained pytest tests, lint, and typecheck.'
    )
}
function Invoke-RouteDemo {
    $python = Get-ProjectPython
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    Push-Location $Root
    Write-Step "printing full phrasing routing matrix (offline)"
    try {
        & $python -m plugins.bot_unified_runtime.route_demo
        if ($LASTEXITCODE -ne 0) { throw "route-demo failed" }
    }
    finally { Pop-Location }
}

function Invoke-RouteSmoke {
    $python = Get-ProjectPython
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    Push-Location $Root
    Write-Step "running real API smoke for deterministic capabilities"
    try {
        & $python -m plugins.bot_unified_runtime.route_demo --real
        if ($LASTEXITCODE -ne 0) { throw "route-smoke failed" }
    }
    finally { Pop-Location }
}


switch ($Task) {
    "help" { Show-Help }
    "doctor" { Invoke-Doctor }
    "install" { Invoke-Install }
    "dev" { Invoke-Run "dev" }
    "run" { Invoke-Run "run" }
    "run-watch" { Invoke-RunWatch }
    "test" { Invoke-Test }
    "lint" { Invoke-Lint }
    "typecheck" { Invoke-Typecheck }
    "readiness-smoke" { Invoke-ReadinessSmoke }
    "dialogue-smoke" { Invoke-DialogueSmoke }
    "chat-smoke" { Invoke-ChatSmoke }
    "backend-smoke" { Invoke-BackendSmoke }
    "prompt-preview" { Invoke-PromptPreview }
    "backend-base-smoke" { Invoke-BackendBaseSmoke }
    "config-smoke" { Invoke-ConfigSmoke }
    "runtime-layout" { Invoke-RuntimeLayout }
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
    "embedding-smoke" { Invoke-EmbeddingSmoke }
    "knowledge-sync" { Invoke-KnowledgeSync }
    "gscore-smoke" { Invoke-GscoreSmoke }
    "route-demo" { Invoke-RouteDemo }
    "route-smoke" { Invoke-RouteSmoke }
    "docs-check" { Invoke-DocsCheck }
    "plugin-check" { Invoke-PluginCheck }
    "smoke" { Invoke-Smoke }
    "verify" { Invoke-Verify }
}
