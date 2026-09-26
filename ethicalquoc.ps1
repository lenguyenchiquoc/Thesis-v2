$drive = $PSScriptRoot.Substring(0, 1).ToLower()
$rest = $PSScriptRoot.Substring(2) -replace '\\', '/'
$wslPath = "/mnt/$drive$rest"

wsl -d Ubuntu --cd $wslPath -- python3 main.py @args
