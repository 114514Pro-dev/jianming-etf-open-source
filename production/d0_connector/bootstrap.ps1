param([switch]$VerifyDownloadOnly)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility\Microsoft.PowerShell.Utility.psd1')
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1')
$version = '3.13.17'
$installerSha256 = '5DA012101BA2E17113A9A1CD901E9CE1441086F2B7ECB5DE06EC94163899A190'
$installerUrl = "https://www.python.org/ftp/python/$version/python-$version-amd64.exe"
$probe = 'import struct,sys,tkinter,venv; sys.exit(0 if sys.version_info[:2] == (3,13) and struct.calcsize("P") == 8 else 1)'
$runtime = Join-Path $env:LOCALAPPDATA 'JianmingETF\Python313'
$localPython = Join-Path $runtime 'python.exe'
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

function Test-Python([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try {
        & $Path -I -c $probe 2>$null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Get-RegisteredPython {
    if (-not (Get-Command py.exe -ErrorAction SilentlyContinue)) { return $null }
    # Do not let the Python launcher invoke a Store install on our behalf.
    $saved = $env:PYLAUNCHER_ALLOW_INSTALL
    Remove-Item Env:PYLAUNCHER_ALLOW_INSTALL -ErrorAction SilentlyContinue
    try {
        $found = & py.exe -3.13 -I -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $found -is [string] -and (Test-Python $found)) { return $found }
        return $null
    } catch { return $null } finally {
        if ($null -ne $saved) { $env:PYLAUNCHER_ALLOW_INSTALL = $saved }
    }
}

function Install-PrivatePython {
    $temp = Join-Path ([IO.Path]::GetTempPath()) ('JianmingETF-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $temp | Out-Null
    $installer = Join-Path $temp "python-$version-amd64.exe"
    try {
        Write-Host "Downloading Python $version x64 from python.org..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $installerUrl -OutFile $installer -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 90
        if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash -ne $installerSha256) {
            throw 'Python installer hash did not match. Nothing was installed.'
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '^CN=Python Software Foundation,') {
            throw 'Python installer signature could not be verified. Nothing was installed.'
        }
        if ($VerifyDownloadOnly) {
            Write-Host 'Official installer hash and signature verified. No install performed.'
            return
        }
        $answer = Read-Host 'Install this verified Python for your Windows user only? (Y/N)'
        if ($answer -notmatch '^[Yy]$') { throw 'Installation cancelled.' }
        $arguments = @('/passive', 'InstallAllUsers=0', 'Include_launcher=0', 'Include_test=0', 'Include_doc=0',
                       'Include_tcltk=1', 'Include_pip=1', 'PrependPath=0', 'AssociateFiles=0', 'Shortcuts=0',
                       ('TargetDir="{0}"' -f $runtime))
        $install = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
        if ($install.ExitCode -ne 0 -or -not (Test-Python $localPython)) {
            throw "Python setup did not provide a usable interpreter (exit $($install.ExitCode))."
        }
    } finally {
        Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

try {
    $arch = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
    if ($arch -ne 'AMD64') { throw 'This package requires Windows x64.' }
    if ($VerifyDownloadOnly) { Install-PrivatePython; exit 0 }
    if (-not (Test-Python $venvPython)) {
        $base = if (Test-Python $localPython) { $localPython } else { Get-RegisteredPython }
        if (-not $base) { Install-PrivatePython; $base = $localPython }
        if (-not (Test-Python $base)) { throw 'Python 3.13 x64 with Tcl/Tk is still unavailable.' }
        & $base -I -m venv (Join-Path $PSScriptRoot '.venv')
        if ($LASTEXITCODE -ne 0 -or -not (Test-Python $venvPython)) { throw 'Could not create the tool virtual environment.' }
    }
    & $venvPython -I -m pip install --no-input --disable-pip-version-check --only-binary=:all: --require-hashes -r (Join-Path $PSScriptRoot 'requirements-win.lock')
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the locked tool dependencies. Check the network and retry.' }
    & $venvPython -I (Join-Path $PSScriptRoot 'pilot.py')
    if ($LASTEXITCODE -ne 0) { throw "Connector exited with status $LASTEXITCODE." }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
