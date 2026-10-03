# 守岸人 Bot 外部服务一键启动（2026-10-03 全量修复批）
# 用法：右键「使用 PowerShell 运行」，或 powershell -ExecutionPolicy Bypass -File scripts\start-external-services.ps1
# 幂等：端口已在听则跳过；启动后探活并回报状态。

$ErrorActionPreference = "Stop"

function Test-PortListening([int]$Port) {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Start-Hidden([string]$Exe, [string]$Args, [string]$WorkDir) {
    Start-Process -FilePath $Exe -ArgumentList $Args -WorkingDirectory $WorkDir -WindowStyle Hidden
}

# ---- 1. meme-generator（/表情 生成腿，2233）----
if (Test-PortListening 2233) {
    Write-Host "[meme-generator] 2233 已在监听，跳过" -ForegroundColor DarkGray
} else {
    Start-Hidden "C:\Software\MemeGenerator\meme.exe" "run --host 127.0.0.1 --port 2233" "C:\Software\MemeGenerator"
    Write-Host "[meme-generator] 已启动（2233）" -ForegroundColor Green
}

# ---- 2. GPT-SoVITS api_v2（TTS，9880；cuda+fp16，读 tts_infer.yaml）----
if (Test-PortListening 9880) {
    Write-Host "[GPT-SoVITS] 9880 已在监听，跳过" -ForegroundColor DarkGray
} else {
    $GsRoot = "C:\Software\GPT-SoVITS-V2Pro"
    Start-Hidden `
        (Join-Path $GsRoot "runtime\python.exe") `
        "api_v2.py -a 127.0.0.1 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml" `
        $GsRoot
    Write-Host "[GPT-SoVITS] 已启动（9880，加载模型约 30-90 秒）" -ForegroundColor Green
}

# ---- 3. 探活（GPT-SoVITS 给足模型加载时间）----
$deadline = (Get-Date).AddSeconds(120)
foreach ($pair in @(@("meme-generator", 2233), @("GPT-SoVITS", 9880))) {
    $name = $pair[0]; $port = $pair[1]
    while ((Get-Date) -lt $deadline -and -not (Test-PortListening $port)) {
        Start-Sleep -Seconds 3
    }
    if (Test-PortListening $port) {
        Write-Host "[OK] $name 端口 $port 就绪" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $name 端口 $port 未就绪（超时 120s）" -ForegroundColor Red
    }
}
Write-Host "完成。两个窗口为隐藏态：任务管理器可见 python.exe（GPT-SoVITS）与 meme.exe。"
