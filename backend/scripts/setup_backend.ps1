<#
.SYNOPSIS
    后端一键初始化：检查 Python 版本 → 建虚拟环境 → 装锁定依赖 → 检查 .env → 按需建索引。

.DESCRIPTION
    为什么需要这个脚本：
      zvec 目前只发布 cp314-cp314-win_amd64 的预编译轮子，Python 版本不对会装不上；
      requirements.txt 没锁版本，装到"当天最新"可能和调好的环境不一致。
      这里把坑都前置成明确的检查项，避免"装到一半失败"。

.PARAMETER CheckOnly
    只做检查（Python 版本、依赖是否与锁定清单一致、.env 是否就绪），不安装任何东西。

.PARAMETER SkipIndex
    跳过首次建索引（跳过就用不了问答检索，除非已经有 data\zvec_kb）。

.PARAMETER Mirror
    pip 镜像地址。默认清华源；传空字符串则用官方 PyPI。

.PARAMETER PythonVersion
    要求的 Python 版本，默认 3.14（与 zvec 轮子匹配）。

.EXAMPLE
    .\scripts\setup_backend.ps1 -CheckOnly
    .\scripts\setup_backend.ps1
    .\scripts\setup_backend.ps1 -SkipIndex -Mirror ""
#>
[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [switch]$SkipIndex,
    [string]$Mirror = "https://pypi.tuna.tsinghua.edu.cn/simple",
    [string]$PythonVersion = "3.14"
)

$ErrorActionPreference = "Stop"

$ScriptDir = $PSScriptRoot
$Backend   = Split-Path $ScriptDir -Parent
$VenvDir   = Join-Path $Backend ".venv"
$VenvPy    = Join-Path $VenvDir "Scripts\python.exe"
$EnvFile   = Join-Path $Backend ".env"
$EnvSample = Join-Path $Backend ".env.example"
$LockFile  = Join-Path $Backend "requirements-lock.txt"
$ReqFile   = Join-Path $Backend "requirements.txt"
$IndexDir  = Join-Path $Backend "data\zvec_kb"

function Write-Step([string]$text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Write-Ok([string]$text)   { Write-Host "  [OK] $text" -ForegroundColor Green }
function Write-Warn2([string]$text){ Write-Host "  [!]  $text" -ForegroundColor Yellow }
function Write-Bad([string]$text)  { Write-Host "  [X]  $text" -ForegroundColor Red }

# ---------- 1. 找可用的 Python ----------
Write-Step "1/6 检查 Python"

function Test-PythonExe([string]$exe) {
    if (-not $exe) { return $null }
    try {
        $out = & $exe -c "import sys; print(sys.version_info[0], sys.version_info[1], sys.maxsize > 2147483647)" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $parts = ($out -join " ").Trim() -split "\s+"
        return [pscustomobject]@{
            Path     = $exe
            Major    = [int]$parts[0]
            Minor    = [int]$parts[1]
            Is64Bit  = ($parts[2] -eq "True")
        }
    } catch { return $null }
}

$candidates = @()
# py 启动器最可靠：能指定小版本，避开 PATH 里指向应用商店的伪 python
if (Get-Command py -ErrorAction SilentlyContinue) {
    try {
        $exe = & py "-$PythonVersion" -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $exe) { $candidates += ($exe | Select-Object -First 1).Trim() }
    } catch { }
}
foreach ($name in @("python", "python3")) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { $candidates += $cmd.Source }
}

$py = $null
foreach ($cand in $candidates) {
    $info = Test-PythonExe $cand
    if (-not $info) { continue }
    if ($info.Major -ne [int]($PythonVersion.Split(".")[0]) -or
        $info.Minor -ne [int]($PythonVersion.Split(".")[1])) { continue }
    $py = $info
    break
}

if (-not $py) {
    Write-Bad "没找到 Python $PythonVersion（64 位）。"
    Write-Host @"
  为什么必须是这个版本：
      zvec 只提供 cp314-cp314-win_amd64 的预编译轮子，
      Python 3.12/3.13/3.15 都装不上它。

  怎么装：
      1) 到 python.org 下载 "Windows installer (64-bit)" 3.14
      2) 安装时勾选 "Add python.exe to PATH"，或直接用 py 启动器
      3) 重新运行本脚本

  不想动系统 Python 的话，也可以用 uv 临时装一个：
      uv venv --python $PythonVersion .venv
"@
    exit 1
}
Write-Ok "Python $($py.Major).$($py.Minor) 64位: $($py.Path)"
if (-not $py.Is64Bit) { Write-Bad "这是 32 位 Python，zvec 没有对应轮子。"; exit 1 }

# ---------- 2. 虚拟环境 ----------
Write-Step "2/6 虚拟环境"
if (Test-Path $VenvPy) {
    Write-Ok "已存在：$VenvDir"
} else {
    if ($CheckOnly) {
        Write-Warn2 "还没有 .venv（-CheckOnly 模式不创建）"
    } else {
        & $py.Path -m venv $VenvDir
        if (-not (Test-Path $VenvPy)) { Write-Bad "虚拟环境创建失败"; exit 1 }
        Write-Ok "已创建：$VenvDir"
    }
}

# ---------- 3. 依赖 ----------
Write-Step "3/6 依赖"
$useLock = Test-Path $LockFile
if ($useLock) { Write-Ok "使用锁定清单 requirements-lock.txt" }
else { Write-Warn2 "没有 requirements-lock.txt，退回 requirements.txt（版本不锁定）" }

function Get-PipVersions([string]$pythonExe) {
    $map = @{}
    try {
        & $pythonExe -m pip freeze 2>$null | ForEach-Object {
            if ($_ -match "^([^=]+)==(.+)$") { $map[$matches[1].Trim().ToLower()] = $matches[2].Trim() }
        }
    } catch { }
    return $map
}

if ($CheckOnly) {
    if (-not (Test-Path $VenvPy)) {
        Write-Warn2 "没有虚拟环境，跳过依赖比对"
    } elseif ($useLock) {
        $want = @{}
        Get-Content $LockFile -Encoding utf8 | ForEach-Object {
            if ($_ -match "^([^#][^=]+)==(.+)$") { $want[$matches[1].Trim().ToLower()] = $matches[2].Trim() }
        }
        $have = Get-PipVersions $VenvPy
        $diffs = @()
        foreach ($k in $want.Keys) {
            if (-not $have.ContainsKey($k)) { $diffs += "缺少 $k==$($want[$k])" }
            elseif ($have[$k] -ne $want[$k]) { $diffs += "$k 版本不符（要求 $($want[$k])，实际 $($have[$k])）" }
        }
        if ($diffs.Count -eq 0) { Write-Ok "依赖与锁定清单完全一致（$($want.Count) 个包）" }
        else { $diffs | ForEach-Object { Write-Warn2 $_ }; Write-Warn2 "运行不带 -CheckOnly 的脚本可修正（用 pip install -r requirements-lock.txt）" }
    }
} else {
    # 调外部程序（pip）时的三点讲究：
    #   1) $ErrorActionPreference='Stop' 会让原生命令往 stderr 写一行就被当成异常，
    #      所以每次调用期间临时关掉它，自己看退出码；
    #   2) 加 --retries/--timeout：国内访问 PyPI 偶尔被重置，重试比直接失败友好；
    #   3) 输出必须 Out-Host / Out-Null 掉：否则函数会把 pip 的每一行输出
    #      一起当成返回值，调用处 `$code -ne 0` 就会把"成功"误判成失败（踩过）。
    function Invoke-Pip([string[]]$PipArgs, [switch]$Quiet) {
        $old = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $args2 = $PipArgs + @("--retries", "3", "--timeout", "30", "--disable-pip-version-check")
            if ($Quiet) {
                & $VenvPy -m pip @args2 2>&1 | Out-Null
            } else {
                & $VenvPy -m pip @args2 2>&1 | Out-Host
            }
            return [int]$LASTEXITCODE
        } finally {
            $ErrorActionPreference = $old
        }
    }

    # pip 升级只是"顺手"，失败不该中断初始化（老版本 pip 一样能装依赖）
    $upgradeArgs = @("install", "--upgrade", "pip")
    if ($Mirror) { $upgradeArgs += @("-i", $Mirror) }
    if ((Invoke-Pip $upgradeArgs -Quiet) -ne 0) {
        Write-Warn2 "pip 自身升级失败（多半是网络），跳过，继续用现有 pip"
    }

    $reqTarget = if ($useLock) { $LockFile } else { $ReqFile }
    $installArgs = @("install", "-r", $reqTarget)
    if ($Mirror) { $installArgs += @("-i", $Mirror) }

    Write-Host "  pip install -r $(Split-Path $reqTarget -Leaf) ..."
    $code = Invoke-Pip $installArgs
    if ($code -ne 0 -and $Mirror) {
        Write-Warn2 "镜像安装失败，改用官方 PyPI 重试 ..."
        $code = Invoke-Pip @("install", "-r", $reqTarget)
    }
    if ($code -ne 0) {
        Write-Bad "依赖安装失败。常见原因：网络不通/需要代理、Python 版本不是 $PythonVersion"
        Write-Warn2 "可以手动重试：.venv\Scripts\python.exe -m pip install -r $(Split-Path $reqTarget -Leaf)"
        exit 1
    }
    Write-Ok "依赖安装完成"
}

# ---------- 4. .env ----------
Write-Step "4/6 环境变量文件 backend/.env"
if (-not (Test-Path $EnvFile)) {
    if (Test-Path $EnvSample) {
        if ($CheckOnly) {
            Write-Warn2 "还没有 .env（-CheckOnly 模式不创建）"
        } else {
            Copy-Item $EnvSample $EnvFile
            Write-Warn2 "已从 .env.example 复制出 .env —— 还要手动填密钥才能问答/建索引"
        }
    } else { Write-Bad "连 .env.example 都没有，仓库不完整" }
} else {
    Write-Ok ".env 已存在"
}

if (Test-Path $EnvFile) {
    # 编码检查：必须是 UTF-8；用 PowerShell 追加或记事本存 ANSI 都会写成 GBK，直接崩
    $bytes = [System.IO.File]::ReadAllBytes($EnvFile)
    $strict = New-Object System.Text.UTF8Encoding($false, $true)
    try {
        [void]$strict.GetString($bytes)
        Write-Ok ".env 是合法 UTF-8"
    } catch {
        Write-Bad ".env 不是 UTF-8 编码（很可能是用记事本或 Add-Content 写成了 GBK）"
        Write-Warn2 "用 VS Code 选 UTF-8 重新保存，或：Get-Content .env -Encoding utf8 | Set-Content .env -Encoding utf8"
    }

    $content = Get-Content $EnvFile -Encoding utf8 -Raw
    $missing = @()
    foreach ($key in @("DEEPSEEK_API_KEY", "EMBED_API_KEY", "EMBED_BASE_URL", "EMBED_MODEL")) {
        if ($content -notmatch "(?m)^\s*$key\s*=\s*\S+") { $missing += $key }
    }
    if ($missing.Count -gt 0) {
        Write-Warn2 ("以下配置项为空或缺失：" + ($missing -join ", "))
        Write-Warn2 "不填 DEEPSEEK_API_KEY 就无法问答/语音；EMBED_* 不填则向量检索不可用（会退回关键词）"
    } else {
        Write-Ok "关键配置项都存在"
    }

    if ($content -match "你的 DeepSeek 密钥填在这里|你的火山方舟密钥填在这里|你的 SiliconFlow 密钥") {
        Write-Warn2 ".env 里还留着示例占位符，记得换成真实密钥"
    }
}

# ---------- 5. 索引 ----------
Write-Step "5/6 向量索引"
if (Test-Path $IndexDir) {
    Write-Ok "已有索引目录：data\zvec_kb"
} elseif ($CheckOnly) {
    Write-Warn2 "还没有索引（首次启动会自动建，约 40 秒，消耗 embedding 额度）"
} elseif ($SkipIndex) {
    Write-Warn2 "已跳过建索引（-SkipIndex）"
} else {
    Write-Host "  首次建索引，约 40 秒 ..."
    Push-Location $Backend
    try {
        & $VenvPy -X utf8 "scripts\build_index.py"
        if ($LASTEXITCODE -ne 0) { Write-Warn2 "建索引失败（多半是 .env 里 embedding 配置/额度问题），不影响先起服务" }
        else { Write-Ok "索引建立完成" }
    } finally { Pop-Location }
}

# ---------- 6. 下一步 ----------
Write-Step "6/6 下一步"
Write-Host @"
  启动后端（必须 --host 0.0.0.0，否则手机连不上）：
      cd backend
      .venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

  自检：
      浏览器打开 http://127.0.0.1:8000/api/health   应返回 status=ok、index.ready=true
      跑单元测试：.venv\Scripts\python.exe -m unittest discover -s tests -t .

  手机/模拟器连过来：
      真机：手机与电脑同一网络，APP 右上角 ⚙ 填 http://<电脑IP>:8000
      模拟器：adb reverse tcp:8000 tcp:8000，APP 留空地址即可
      防火墙放行（管理员 PowerShell）：
          New-NetFirewallRule -DisplayName "MuseumDocentAI Backend" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
"@

if ($CheckOnly) { Write-Host "`n（-CheckOnly 模式：只检查，没有任何改动）" -ForegroundColor DarkGray }
