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
        "kb-sync",
        "gscore-smoke",
        "route-demo",
        "route-smoke",
        "search-smoke",
        "memory-sanitize",
        "docs-check",
        "plugin-check",
        "sync",
        "smoke",
        "verify"
    )]
    [string]$Task = "help",
    [string]$Message = "",
    [switch]$Apply,
    # Generic knowledge-base switch list. The caller may pass either the natural
    # single-dash form (-Kb -Full -NoEmbed) or the double-dash form
    # (-Kb --kb-full --kb-no-embed). Windows PowerShell 5.1 refuses to *parse*
    # a bare '--kb-full' as an argument, so this collects the tokens and the
    # kb-sync task forwards them verbatim.
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Kb = @()
)

# This script is a generic task runner. Every concrete task lives in
# scripts/chatbot-tasks.json; nothing here hard-codes a per-task branch, so the
# task list is data rather than code. All comments in this file are English.

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeRoot = Join-Path (Split-Path -Parent $Root) "ChatBot_Runtime"
$RuntimeVenv = Join-Path $RuntimeRoot "venv"
# Keep Python bytecode caches out of the AI workspace.
$env:PYTHONDONTWRITEBYTECODE = "1"
# PYTHONDONTWRITEBYTECODE does not stop `python -m py_compile` / `compileall`
# (they still write into the source tree in practice), so also set the mirror
# prefix as a backstop: any bytecode that does get written lands under Runtime
# instead of the AI workspace (runtime-layout rule 6).
$env:PYTHONPYCACHEPREFIX = Join-Path $RuntimeRoot "pycache"
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

# --- Generic executor helpers (no per-task hard-coded branching) ----------

# The project interpreter, resolved once and cached so a task that declares
# pythonTool surfaces "Python was not found" at the same point as before.
$script:DevPythonCache = $null

function Get-ProjectPythonCached {
    if ($script:DevPythonCache) { return $script:DevPythonCache }
    $py = Get-ProjectPython
    $script:DevPythonCache = $py
    return $py
}

function Get-CacheDirPath {
    param([string]$Name)
    switch ($Name) {
        "ruffCache" { return (Join-Path $RuntimeRoot "cache\ruff") }
        "mypyCache" { return (Join-Path $RuntimeRoot "cache\mypy") }
        default { throw "Unknown cache directory name: $Name" }
    }
}

# Pytest scratch root, deliberately OUTSIDE both $Root and $RuntimeRoot: a run must
# not write caches into the source tree (workspace rule 6) or into runtime data.
# NOTE: an earlier version of this comment claimed that pinning TMP/TEMP inside
# ChatBot_Runtime\cache made 10 otherwise-green tests fail deterministically. The
# A/B on 2026-09-29 measured the identical "5 failed / 155 passed" with TMP pinned
# to a chatbot_runtime-shaped path and with it outside -- those reds were a stale
# test leg (restricted_runner helpers retired as "删优于接"), not the path. Do not
# re-add that claim. Candidates are tried in order and skipped when one lands
# inside a protected root.
function Get-PytestScratchBase {
    $candidates = @()
    if ($env:LOCALAPPDATA) { $candidates += (Join-Path $env:LOCALAPPDATA "Temp\qoder-chatbot-ci") }
    $candidates += (Join-Path ([IO.Path]::GetTempPath()) "qoder-chatbot-ci")
    foreach ($c in $candidates) {
        $full = [IO.Path]::GetFullPath($c)
        $blocked = $false
        foreach ($guard in @($Root, $RuntimeRoot)) {
            $gfull = [IO.Path]::GetFullPath($guard)
            if ($full -eq $gfull -or $full.StartsWith($gfull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                $blocked = $true
            }
        }
        if (-not $blocked) { return $full }
    }
    throw "No usable pytest scratch base outside the protected roots ($Root / $RuntimeRoot)"
}

# True when the parsed JSON object exposes the named property.
function HasProp {
    param($Object, [string]$Name)
    if ($null -eq $Object) { return $false }
    return ($Object.PSObject.Properties.Name -contains $Name)
}

# Forward the caller's knowledge-base switches. Accepts either spelling family:
# the real double-dash arguments (--kb-full / --kb-no-embed), the natural
# single-dash tokens (-Full / -NoEmbed), or the bare words (full / noembed).
# Each captured token is normalized by dropping leading dashes and hyphens and
# lower-casing, so every family maps onto the same real argument.
function Get-DevKbTokens {
    $tokens = @()
    foreach ($raw in $Kb) {
        $norm = (([string]$raw).TrimStart('-') -replace '-', '').ToLowerInvariant()
        switch ($norm) {
            "kbfull" { if ("--kb-full" -notin $tokens) { $tokens += "--kb-full" } }
            "full" { if ("--kb-full" -notin $tokens) { $tokens += "--kb-full" } }
            "kbnoembed" { if ("--kb-no-embed" -notin $tokens) { $tokens += "--kb-no-embed" } }
            "noembed" { if ("--kb-no-embed" -notin $tokens) { $tokens += "--kb-no-embed" } }
        }
    }
    return $tokens
}

# Expand a single argv element from the task definition. A plain string is used
# verbatim; an object describes a value that only resolves at run time.
function Expand-DevArg {
    param($Element)

    if ($Element -is [string]) { return $Element }
    if ($Element -isnot [System.Management.Automation.PSCustomObject]) { return [string]$Element }

    if (HasProp $Element "cacheDir") {
        return (Get-CacheDirPath $Element.cacheDir)
    }
    if (HasProp $Element "optionalMessage") {
        $spec = $Element.optionalMessage
        if ($spec.mode -eq "truthy") {
            if ($Message) { return @($spec.flag, $Message) }
            return @()
        }
        if (-not [string]::IsNullOrWhiteSpace($Message)) { return @($spec.flag, $Message) }
        return @()
    }
    if (HasProp $Element "messageOrDefault") {
        $spec = $Element.messageOrDefault
        if ($spec.mode -eq "truthy") {
            if ($Message) { return @($spec.flag, $Message) }
            return @($spec.flag, $spec.default)
        }
        if ([string]::IsNullOrWhiteSpace($Message)) { return @($spec.flag, $spec.default) }
        return @($spec.flag, $Message)
    }
    if (HasProp $Element "message") {
        return $Message
    }
    if (HasProp $Element "replaceOr") {
        $spec = $Element.replaceOr
        $on = $false
        switch ($spec.param) {
            "Apply" { $on = [bool]$Apply }
        }
        if ($on) { return $spec.onFlag }
        return $spec.offFlag
    }
    if (HasProp $Element "optionalSwitches") {
        if ($Element.optionalSwitches -eq "Kb") { return (Get-DevKbTokens) }
        return @()
    }
    throw "Unknown command argument descriptor in task JSON."
}

# Resolve the executable for a command. Commands that carry a python module or
# a python script always run through the interpreter resolved at run time (so
# the interpreter path is never a stored FilePath). Any other command resolves
# its tool by name via Get-ProjectCommand.
function Resolve-DevCommandTool {
    param($Command)
    if ((HasProp $Command "module") -or (HasProp $Command "pythonScript")) {
        return Get-ProjectPythonCached
    }
    return (Get-ProjectCommand $Command.tool)
}

function Invoke-DevCommand {
    param($Command)

    $FilePath = Resolve-DevCommandTool $Command

    $Arguments = @()
    if (HasProp $Command "args") {
        foreach ($element in @($Command.args)) {
            $expanded = Expand-DevArg $element
            if ($null -ne $expanded) {
                foreach ($item in @($expanded)) { $Arguments += $item }
            }
        }
    }
    if (HasProp $Command "module") {
        $Arguments = @("-m", $Command.module) + $Arguments
    }
    elseif (HasProp $Command "pythonScript") {
        $Arguments = @($Command.pythonScript) + $Arguments
    }

    if ($null -eq $FilePath) {
        throw "Command tool '$($Command.tool)' was not found."
    }

    if ((HasProp $Command "failMessage") -and $Command.failMessage) {
        & $FilePath @Arguments
        if ($LASTEXITCODE -ne 0) { throw $Command.failMessage }
        return
    }

    switch ($Command.runner) {
        "soft" {
            & $FilePath @Arguments
            $script:DevSoftExit = $LASTEXITCODE
        }
        "loop-plain" {
            & $FilePath @Arguments
        }
        default {
            Invoke-External $FilePath $Arguments
        }
    }
}

function Test-DevCondition {
    param(
        [string]$Condition,
        [string]$Tool
    )
    switch ($Condition) {
        "toolAvailable" { return [bool](Get-ProjectCommand $Tool) }
        "botAlreadyRunning" {
            $inUse = Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue
            return [bool]$inUse
        }
        "testsDirExists" { return (Test-Path -LiteralPath (Join-Path $Root "tests")) }
        default { throw "Unknown condition: $Condition" }
    }
}

function Invoke-DevPluginsCount {
    $pluginFiles = Get-ChildItem -LiteralPath (Join-Path $Root "plugins") -Recurse -File -Include "*.py" -ErrorAction SilentlyContinue
    if (-not $pluginFiles -or @($pluginFiles).Count -eq 0) {
        throw "No local plugin Python files exist."
    }
    Write-Step "found bot_unified_runtime and $(@($pluginFiles).Count) local plugin Python file(s)"
}

# The generic step interpreter. Control-flow steps (conditional / loop /
# subtask) recurse back into this same function; there is no per-task switch.
function Invoke-DevSteps {
    param($Steps)

    if ($null -eq $Steps) { return }
    foreach ($step in @($Steps)) {
        if ($script:DevAborted) { return }

        switch ($step.type) {
            "step" {
                if ($step.raw) {
                    Write-Host $step.message.Replace('$LASTEXITCODE', [string]$LASTEXITCODE)
                }
                else {
                    Write-Step $step.message
                }
            }
            "warn" {
                Write-Warning $step.message
            }
            "assertPath" {
                Assert-PathExists $step.path
            }
            "assertContains" {
                Assert-FileContains $step.path $step.needle
            }
            "command" {
                Invoke-DevCommand $step
            }
            "subtask" {
                Invoke-DevTask $step.task
            }
            "conditional" {
                $ok = Test-DevCondition -Condition $step.condition -Tool $step.tool
                if ($ok) {
                    Invoke-DevSteps $step.then
                }
                elseif ((HasProp $step "else") -and $step.else) {
                    Invoke-DevSteps $step.else
                }
            }
            "loop" {
                while (-not $script:DevAborted) {
                    Invoke-DevSteps $step.steps
                }
            }
            "sleep" {
                Start-Sleep -Seconds ([int]$step.seconds)
            }
            "abortWithMessage" {
                Write-Host $step.message
                $script:DevAborted = $true
            }
            "ensureTool" {
                if (-not (Get-ProjectCommand $step.tool)) { throw $step.missingMessage }
            }
            "ensureCacheDir" {
                $p = Get-CacheDirPath $step.cacheDir
                New-Item -ItemType Directory -Force -Path $p | Out-Null
            }
            "ensurePythonModule" {
                $py = Get-ProjectPythonCached
                & $py -c "import $($step.module)" *> $null
                if ($LASTEXITCODE -ne 0) { throw $step.missingMessage }
            }
            "requireMessage" {
                if ([string]::IsNullOrWhiteSpace($Message)) { throw $step.message }
            }
            "resolvePython" {
                Get-ProjectPythonCached | Out-Null
            }
            "pythonImportVersion" {
                $py = Get-ProjectPythonCached
                $pkg = $step.package
                Invoke-External $py @("-c", "from importlib.metadata import version; print('$pkg', version('$pkg'))")
            }
            "pluginsCount" {
                Invoke-DevPluginsCount
            }
            "help" {
                Write-Output $script:DevHelpLines
            }
            default {
                throw "Unknown step type: $($step.type)"
            }
        }
    }
}

# The pytest task keeps its original imperative body verbatim: the autosync
# defaulting and the per-run temp-directory handling are control flow that the
# generic step interpreter cannot express as a command list.
function Invoke-TaskTest {
    if (-not (Test-Path -LiteralPath (Join-Path $Root "tests"))) {
        throw "The pytest suite is archived outside the workspace. Restore tests/ from development-materials-2026-08-28.tar.gz before using the test task."
    }

    # autosync (2026-09-13 user ruling): the test task enables the conftest
    # resident auto-sync so that, once the run finishes, docs/hashes are already
    # in sync without any manual step. V2.1 gate-conflict fix (2026-09-17): the
    # original implementation unconditionally overwrote an outer value, so a
    # caller setting BOT_AUTOSYNC=0 was silently turned back to 1; when conftest
    # failed it then auto-rerolled the expectations (including
    # tests/render_hashes.json), washing a real regression green. Current
    # semantics: default to 1 only when the caller did not explicitly set
    # BOT_AUTOSYNC (keep the seamless experience); an explicit 0 disables the
    # automatic re-roll (V2.1 acceptance mode, where the generated baseline must
    # stay byte-for-byte unchanged).
    if (-not (Test-Path env:BOT_AUTOSYNC)) { $env:BOT_AUTOSYNC = "1" }

    $python = Get-ProjectPythonCached
    $pytest = Get-ProjectCommand "pytest"

    Push-Location $Root
    $oldTmp = $env:TMP
    $oldTemp = $env:TEMP
    $oldTmpRoot = $env:PYTEST_DEBUG_TEMPROOT
    $ciTmp = Join-Path (Get-PytestScratchBase) ("pytest_ci_" + $PID)
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

function Invoke-DevTask {
    param([string]$Name)

    $task = $script:DevTasks.$Name
    if ($null -eq $task) {
        throw "No task definition found for '$Name' in $TasksPath."
    }

    $script:DevAborted = $false
    $script:DevSoftExit = $null

    if ((HasProp $task "setUtf8") -and $task.setUtf8) {
        $env:PYTHONIOENCODING = "utf-8"
        $env:PYTHONUTF8 = "1"
    }
    if ((HasProp $task "pythonTool") -and $task.pythonTool) {
        Get-ProjectPythonCached | Out-Null
    }
    if ((HasProp $task "pytestTask") -and $task.pytestTask) {
        Invoke-TaskTest
        return
    }

    if ((HasProp $task "push") -and $task.push) {
        Push-Location $Root
        try {
            Invoke-DevSteps $task.steps
        }
        finally {
            Pop-Location
        }
    }
    else {
        Invoke-DevSteps $task.steps
    }

    if ((HasProp $task "softFailMessage") -and $task.softFailMessage) {
        if ($null -ne $script:DevSoftExit -and $script:DevSoftExit -ne 0) {
            Write-Step $task.softFailMessage
            exit $script:DevSoftExit
        }
    }
}

# Load the task definitions. Read the bytes as UTF-8 explicitly so the non-ASCII
# strings inside stay intact regardless of the active ANSI code page.
$TasksPath = Join-Path $PSScriptRoot "chatbot-tasks.json"
if (-not (Test-Path -LiteralPath $TasksPath)) {
    throw "Task definitions file not found: $TasksPath"
}
$DevTasksJsonText = [System.IO.File]::ReadAllText($TasksPath, [System.Text.Encoding]::UTF8)
$DevTasksRoot = ConvertFrom-Json $DevTasksJsonText
$script:DevTasks = $DevTasksRoot.tasks
$script:DevHelpLines = @($DevTasksRoot.help.lines)

Invoke-DevTask $Task
