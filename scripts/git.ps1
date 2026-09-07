[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet("status", "save", "update", "history", "rollback", "revert", "tag", "help")]
    [string]$Task = "status",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest = @()
)

# Local git workflow helper. Never pushes, never force-pushes.
# Usage examples are listed in Show-Help below; historical Chinese Git notes are archived outside the AI workspace.

$ErrorActionPreference = "Stop"
# pwsh 7.3+：git 的 stderr 提示（LF/CRLF 等）默认按错误记录处理，
# 配合上面的 Stop 会中断脚本；显式关掉，让提示只走控制台显示。
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

function Invoke-Git {
    param([string[]]$Arguments)
    Push-Location $Root
    try {
        # git 的提示（LF/CRLF 等）走 stderr。ErrorActionPreference=Stop 时
        # stderr 记录会中断脚本（WinPS5.1 / pwsh 均可能触发），这里局部放宽，
        # 真正的失败仍由 $LASTEXITCODE 捕获并抛出。
        $previousEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            & git @Arguments 2>&1
        }
        finally {
            $ErrorActionPreference = $previousEap
        }
        if ($LASTEXITCODE -ne 0) {
            throw "git $($Arguments -join ' ') exited with code $LASTEXITCODE."
        }
    }
    finally { Pop-Location }
}

function Show-Help {
    @"
git.ps1 - local git workflow helper (never pushes, never force-pushes)

Usage:
  powershell -ExecutionPolicy Bypass -File scripts/git.ps1 <task> [args...]

Tasks:
  status            Show working tree status and the latest 8 commits.
  save <message>    Stage and commit all current changes in one step.
  update            Fetch, then fast-forward update (--ff-only).
                    If local commits diverge from upstream, only warn.
  history [count]   Show recent commits (default 10).
  rollback <count>  Discard the latest N commits after typing "yes".
  revert <commit>   Safely reverse one commit while keeping history.
  tag <name>        Tag the current commit as a rollback snapshot.
  help              Show this help.

Rollback examples:
  powershell -ExecutionPolicy Bypass -File scripts/git.ps1 history 20
  powershell -ExecutionPolicy Bypass -File scripts/git.ps1 tag v0.1-working
  powershell -ExecutionPolicy Bypass -File scripts/git.ps1 rollback 2
  powershell -ExecutionPolicy Bypass -File scripts/git.ps1 revert 3ea2aa4

See GIT.md for the full Chinese workflow guide.
"@
}

switch ($Task) {
    "help" { Show-Help }
    "status" {
        Write-Host "== Working tree =="
        Invoke-Git @("status", "--short", "--branch")
        Write-Host ""
        Write-Host "== Recent commits =="
        Invoke-Git @("log", "--oneline", "-8")
    }
    "save" {
        if (-not $Rest -or -not $Rest[0]) {
            throw "Usage: scripts/git.ps1 save <commit message>"
        }
        $Message = $Rest -join " "
        Invoke-Git @("add", "-A")
        Invoke-Git @("commit", "-m", $Message)
        Write-Host "Committed: $Message"
    }
    "update" {
        Invoke-Git @("fetch", "origin")
        $ahead = & git rev-list --count "@{u}..HEAD" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "No upstream branch configured (origin). Nothing to pull."
            return
        }
        if ($ahead -gt 0) {
            Write-Warning "Local branch is $ahead commit(s) ahead of upstream and has diverged. Not merging automatically. Save your work first, then decide to push or reset."
            return
        }
        $behind = & git rev-list --count "HEAD..@{u}"
        if ($behind -gt 0) {
            Write-Host "Upstream has $behind new commit(s). Fast-forwarding..."
            Invoke-Git @("pull", "--ff-only", "origin")
        }
        else {
            Write-Host "Already up to date."
        }
    }
    "history" {
        $Count = if ($Rest -and $Rest[0] -match '^\d+$') { [int]$Rest[0] } else { 10 }
        Invoke-Git @("log", "--oneline", "-$Count")
    }
    "rollback" {
        if (-not $Rest -or $Rest[0] -notmatch '^\d+$') {
            throw "Usage: scripts/git.ps1 rollback <count>, e.g. rollback 2"
        }
        $Count = [int]$Rest[0]
        Write-Host "The following $Count commit(s) will be discarded:"
        Invoke-Git @("log", "--oneline", "-$Count")
        $answer = Read-Host "Type yes to confirm rollback (cannot be undone), anything else cancels"
        if ($answer -ne "yes") {
            Write-Host "Cancelled."
            return
        }
        Invoke-Git @("reset", "--hard", "HEAD~$Count")
        Write-Host "Rolled back to:"
        Invoke-Git @("log", "--oneline", "-1")
    }
    "revert" {
        if (-not $Rest -or -not $Rest[0]) {
            throw "Usage: scripts/git.ps1 revert <commit hash>"
        }
        Invoke-Git @("revert", "--no-edit", $Rest[0])
        Write-Host "Reverted commit $($Rest[0]) while keeping history."
    }
    "tag" {
        if (-not $Rest -or -not $Rest[0]) {
            throw "Usage: scripts/git.ps1 tag <name>"
        }
        Invoke-Git @("tag", $Rest[0])
        Write-Host "Tagged: $($Rest[0])"
        Invoke-Git @("tag", "--list", $Rest[0])
    }
}
