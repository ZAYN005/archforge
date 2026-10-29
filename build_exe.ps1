<#
Build ArchForge.exe for Windows.

    powershell -ExecutionPolicy Bypass -File build_exe.ps1            # China mirrors (default)
    powershell -ExecutionPolicy Bypass -File build_exe.ps1 -NoMirror  # official sources (GitHub Actions)

Steps
  1. install build dependencies (PyInstaller + requirements)
  2. run the test suite (skip with -SkipTests)
  3. PyInstaller -> dist\ArchForge\ArchForge.exe  (Python + PySide6 inside: no Python needed on target)
  4. add portable Node.js -> dist\ArchForge\node\  (no Node needed on target)
  5. smoke test with Python and Node REMOVED from PATH (simulates a clean PC)
  6. zip -> release\ArchForge-win64.zip  + SHA-256
#>
param(
    [string]$NodeVersion = "22.12.0",
    [switch]$NoMirror,
    [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }

$pipIndex = @()
if (-not $NoMirror) { $pipIndex = @("-i", "https://pypi.tuna.tsinghua.edu.cn/simple") }

Step "1/6 Build dependencies"
python -m pip install --upgrade pyinstaller -r requirements.txt @pipIndex
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not $SkipTests) {
    Step "2/6 Test suite"
    $env:QT_QPA_PLATFORM = "offscreen"
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "tests failed - not building" }
    Remove-Item Env:QT_QPA_PLATFORM
} else { Step "2/6 Tests skipped" }

Step "3/6 PyInstaller"
python -m PyInstaller ArchForge.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$app = Join-Path $PSScriptRoot "dist\ArchForge"

Step "4/6 Portable Node.js $NodeVersion"
New-Item -ItemType Directory -Force -Path build | Out-Null
$zip = "build\node-v$NodeVersion-win-x64.zip"
$base = if ($NoMirror) { "https://nodejs.org/dist" } else { "https://npmmirror.com/mirrors/node" }
if (-not (Test-Path $zip)) {
    $url = "$base/v$NodeVersion/node-v$NodeVersion-win-x64.zip"
    Write-Host "downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
}
$tmp = "build\node-extract"
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
Expand-Archive -Path $zip -DestinationPath $tmp
$nodeDir = Join-Path $app "node"
if (Test-Path $nodeDir) { Remove-Item -Recurse -Force $nodeDir }
Move-Item (Join-Path $tmp "node-v$NodeVersion-win-x64") $nodeDir
Write-Host "node.exe -> $nodeDir"

@"
ArchForge - Architecture-to-Code Agent
======================================
1. Double-click ArchForge.exe
2. Paste your DeepSeek API key (or set the DEEPSEEK_API_KEY environment variable)
3. Choose the two architecture files (defaults are included), an output folder, and click Generate.

Nothing else needs to be installed: Python and Node.js are bundled.
Offline self-check:  ArchForge.exe --smoke   (report in %TEMP%\archforge_smoke.txt)
"@ | Set-Content -Encoding UTF8 (Join-Path $app "READ_ME_FIRST.txt")

Step "5/6 Smoke test on a 'clean' PATH (no Python, no system Node)"
$oldPath = $env:PATH
$env:PATH = "$env:SystemRoot\system32;$env:SystemRoot;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
$report = Join-Path $env:TEMP "archforge_smoke.txt"
if (Test-Path $report) { Remove-Item $report }
$p = Start-Process -FilePath (Join-Path $app "ArchForge.exe") -ArgumentList "--smoke" -Wait -PassThru
$env:PATH = $oldPath
Get-Content $report
if ($p.ExitCode -ne 0) { throw "smoke test failed (exit $($p.ExitCode))" }

Step "6/6 Zip"
New-Item -ItemType Directory -Force -Path release | Out-Null
$out = "release\ArchForge-win64.zip"
if (Test-Path $out) { Remove-Item $out }
Compress-Archive -Path $app -DestinationPath $out -CompressionLevel Optimal
$size = [math]::Round((Get-Item $out).Length / 1MB, 1)
$hash = (Get-FileHash $out -Algorithm SHA256).Hash
Write-Host "`nDONE: $out  ($size MB)" -ForegroundColor Green
Write-Host "SHA-256: $hash"
Write-Host "Run:     $app\ArchForge.exe"
