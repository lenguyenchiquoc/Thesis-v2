Write-Host "[*] Checking WSL..."
wsl --status 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] WSL is not installed on this machine."
    Write-Host "    Run this in an ADMINISTRATOR PowerShell, then restart your machine:"
    Write-Host "        wsl --install"
    Write-Host "    Then re-run this script."
    exit 1
}

Write-Host "[*] Checking for Ubuntu WSL distro..."
wsl -d Ubuntu -- true 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[*] Installing Ubuntu (downloads ~500MB, may take a few minutes)..."
    wsl --install -d Ubuntu --no-launch
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[!] Failed to install Ubuntu. See error above."
        exit 1
    }
} else {
    Write-Host "[+] Ubuntu already installed."
}

$drive = $PSScriptRoot.Substring(0, 1).ToLower()
$rest = $PSScriptRoot.Substring(2) -replace '\\', '/'
$wslPath = "/mnt/$drive$rest"

Write-Host "[*] Installing java/php/ruby/python3 inside Ubuntu (safe to re-run; skips what's already installed)..."
wsl -d Ubuntu -- bash "$wslPath/setup-wsl.sh"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Setup script failed. See error above."
    exit 1
}

Write-Host ""
Write-Host "[+] Done. Use .\ethicalquoc.ps1 <command> to run the tool, e.g.:"
Write-Host "        .\ethicalquoc.ps1 analyze -i results/scan_output.json -o results/analyze_output.json"
