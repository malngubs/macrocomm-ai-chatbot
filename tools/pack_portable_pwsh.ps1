<# =====================================================================
 Macrocomm Assistant — Portable ZIP Builder (PowerShell 7)
 -----------------------------------------------------------------------
 WHAT CHANGED (vs the version you pasted):
  • DEFAULT URL fixed to: http://bot.macrocomm.local:8000
  • Output ZIP is always saved to the Desktop
  • Copies ALL required runtime assets, not just app/ and static/:
      - server/, models/, startup/, chroma_db/ (if present)
      - .env and/or .env.example, requirements.txt
      - launchers (start_macrocomm_chatbot.cmd, start_bot_hidden.vbs)
 ===================================================================== #>

[CmdletBinding()]
param(
    # DEFAULT backend URL baked into the bundle (can still override with -ServerUrl)
    [string]$ServerUrl = "http://bot.macrocomm.local:8000"
)

# -----------------------------
# 0) CONSTANTS / PATHS
# -----------------------------
$RepoRoot  = (Resolve-Path ".").Path                      # repo root = current folder
$Desktop   = [Environment]::GetFolderPath('Desktop')      # output on Desktop as requested
$OutName   = "MacrocommAssistant_Portable"
$OutDir    = Join-Path $Desktop $OutName                  # bundle folder on Desktop
$ZipPath   = Join-Path $Desktop "$OutName.zip"            # zip on Desktop

# Locations in your repo (do NOT change your structure)
$WrapperDir = Join-Path $RepoRoot "desktop-wrapper"       # Electron wrapper (main.js, package.json, etc.)
$StaticDir  = Join-Path $RepoRoot "static"                # static assets (widget html/css etc.)

# Extra runtime dirs that are needed to actually run the bot backend
$ExtraDirs = @(
  "server",        # FastAPI app
  "models",        # any ML models you keep locally
  "startup",       # logs/run scripts
  "chroma_db"      # persisted vector DB (if you ship it)
) | ForEach-Object { Join-Path $RepoRoot $_ }

# Extra files required at runtime (copied if present)
$ExtraFiles = @(
  "requirements.txt",
  ".env",                # if present on your dev box (optional to ship)
  ".env.example",        # safe to ship
  "README.md",
  "start_macrocomm_chatbot.cmd",
  "start_bot_hidden.vbs"
) | ForEach-Object { Join-Path $RepoRoot $_ }

# -----------------------------
# Helper: step logger
# -----------------------------
function Write-Step([string]$msg) {
    Write-Host "`n==> $msg" -ForegroundColor Cyan
}

# -----------------------------
# Helper: stop a process if running (no error if missing)
# -----------------------------
function Stop-IfRunning([string]$name) {
    try {
        $p = Get-Process -Name $name -ErrorAction SilentlyContinue
        if ($p) {
            $p | Stop-Process -Force -ErrorAction SilentlyContinue
            Write-Host "SUCCESS: The process `"$name`" has been terminated."
        } else {
            Write-Host "ERROR: The process `"$name`" not found."
        }
    } catch {
        Write-Host "ERROR: Could not stop `"$name`": $($_.Exception.Message)"
    }
}

# =====================================================================
# 1) Pre-flight checks
# =====================================================================
Write-Step "Pre-flight checks"
Stop-IfRunning "electron"
Stop-IfRunning "macrocomm-desktop-wrapper"

# =====================================================================
# 2) Preparing output folder on Desktop
# =====================================================================
Write-Step "Preparing output folder"
if (Test-Path -LiteralPath $OutDir) { Remove-Item -LiteralPath $OutDir -Recurse -Force }
New-Item -ItemType Directory -Path $OutDir | Out-Null
if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }

# =====================================================================
# 3) Installing Electron app dependencies
# =====================================================================
Write-Step "Installing Electron app dependencies (desktop-wrapper)"
if (-not (Test-Path -LiteralPath $WrapperDir)) { throw "Wrapper directory not found: $WrapperDir" }

# call npm ci via cmd.exe for reliable PATH/quoting on Windows
$npm = (& where.exe npm 2>$null | Select-Object -First 1); if (-not $npm) { $npm = (& where.exe npm.cmd 2>$null | Select-Object -First 1) }
if (-not $npm) { throw "npm not found. Please install Node.js LTS and ensure npm is on PATH." }

$cmdArgs = "/c `"$npm`" ci --no-audit --no-fund"
Write-Host "  > cmd.exe $cmdArgs  (in $WrapperDir)"
$p = Start-Process -FilePath "cmd.exe" -ArgumentList $cmdArgs -WorkingDirectory $WrapperDir -NoNewWindow -PassThru -Wait
if ($p.ExitCode -ne 0) { throw "npm ci failed with exit code $($p.ExitCode)" }

# =====================================================================
# 4) Copying Electron app into output  =>  <Desktop>\MacrocommAssistant_Portable\app\
# =====================================================================
Write-Step "Copying Electron app into output"
$appDst = Join-Path $OutDir "app"
New-Item -ItemType Directory -Path $appDst | Out-Null
Copy-Item -Path (Join-Path $WrapperDir '*') -Destination $appDst -Recurse -Force

# =====================================================================
# 5) Copying static assets  =>  <Desktop>\MacrocommAssistant_Portable\static\
# =====================================================================
Write-Step "Copying static assets"
if (Test-Path -LiteralPath $StaticDir) {
    Copy-Item -Path $StaticDir -Destination (Join-Path $OutDir "static") -Recurse -Force
} else {
    Write-Host "WARN: static folder not found at $StaticDir — skipping." -ForegroundColor Yellow
}

# =====================================================================
# 6) Copying backend/runtime assets (server, models, startup, chroma_db, etc.)
# =====================================================================
Write-Step "Copying backend/runtime assets"
foreach ($d in $ExtraDirs) {
    if (Test-Path -LiteralPath $d) {
        $name = Split-Path $d -Leaf
        Copy-Item -Path $d -Destination (Join-Path $OutDir $name) -Recurse -Force
        Write-Host "  + dir: $name"
    }
}
foreach ($f in $ExtraFiles) {
    if (Test-Path -LiteralPath $f) {
        Copy-Item -Path $f -Destination (Join-Path $OutDir (Split-Path $f -Leaf)) -Force
        Write-Host "  + file: $(Split-Path $f -Leaf)"
    }
}

# =====================================================================
# 7) Writing server URL (what the wrapper reads)
# =====================================================================
Write-Step "Writing server URL"
$ServerUrlFile = Join-Path $OutDir "static\server-url.txt"
Set-Content -Path $ServerUrlFile -Value "$ServerUrl`r`n" -Encoding UTF8
Write-Host "    $ServerUrlFile => $ServerUrl"

# Also drop a runtime-editable copy in config\server_url.txt (optional but handy)
$configDir = Join-Path $OutDir "config"
New-Item -ItemType Directory -Path $configDir -Force | Out-Null
Set-Content -Path (Join-Path $configDir 'server_url.txt') -Value "$ServerUrl`r`n" -Encoding UTF8

# =====================================================================
# 8) Creating ZIP (on Desktop)
# =====================================================================
Write-Step "Creating ZIP"
Compress-Archive -Path (Join-Path $OutDir '*') -DestinationPath $ZipPath -CompressionLevel Optimal

# =====================================================================
# 9) Summary
# =====================================================================
$zipItem = Get-Item $ZipPath
$sizeMB  = '{0:n1}' -f ($zipItem.Length / 1MB)
Write-Host "`nOK: Portable ZIP ready:" -ForegroundColor Green
Write-Host "  $($zipItem.FullName)  ($sizeMB MB)"
Write-Host "  Open folder: $OutDir"


