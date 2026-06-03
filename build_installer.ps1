param(
    [string]$InnoSetupPath = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    py -3.12 -m venv (Join-Path $Root ".venv")
}

& $VenvPython -m pip install -r (Join-Path $Root "requirements.txt")
& $VenvPython -m pip install pyinstaller

$LibMpv = Join-Path $Root "libmpv-2.dll"
if (-not (Test-Path $LibMpv)) {
    throw "Place libmpv-2.dll in the repository root before building the installer."
}

& $VenvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --name PrismPlayer `
    --icon "prism_player\assets\prism_logo.ico" `
    --paths prism_player `
    --add-binary "libmpv-2.dll;." `
    --add-data "prism_player\assets\prism_logo.ico;assets" `
    --add-data "prism_player\assets\prism_logo.svg;assets" `
    --add-data "prism_player\assets\prism_logo.png;assets" `
    prism_player\main.py

if (-not (Test-Path $InnoSetupPath)) {
    throw "Inno Setup compiler not found at $InnoSetupPath"
}

& $InnoSetupPath (Join-Path $Root "installer\prism_player.iss")
