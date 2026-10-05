# Registers a Windows scheduled task that backs up GitHub's scheduler from this
# computer: it takes the reading when GitHub has not, and fills in the sources
# GitHub's servers cannot reach.
#
# Usage (from PowerShell):  .\scripts\register_backfill_task.ps1
# To remove it:             Unregister-ScheduledTask -TaskName DolarTrackingBackfill
#
# The task works in its own clone of the repository so it never touches a working
# copy you are editing. Readings are taken at 07:07, 13:07 and 19:07 Bolivia time;
# the task starts once at 20 past, and backfill.ps1 itself retries every 20 minutes
# for 100 minutes while the reading is incomplete. This computer's clock must be on
# Bolivia time.

param(
    [string]$RepositoryUrl = "https://github.com/Mrdavid656/dolar_tracking.git",
    [string]$Directory = (Join-Path $env:LOCALAPPDATA "dolar_tracking"),
    [string]$TaskName = "DolarTrackingBackfill"
)

if (-not (Test-Path (Join-Path $Directory ".git"))) {
    git clone --quiet $RepositoryUrl $Directory
    if ($LASTEXITCODE -ne 0) { throw "Could not clone $RepositoryUrl" }
}

$script = Join-Path $Directory "scripts\backfill.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""

$triggers = "07:20", "13:20", "19:20" | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ }

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)  # room for every retry

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Settings $settings `
    -Description "Backfills dollar rates that GitHub's servers cannot reach." -Force | Out-Null

Write-Output "Task '$TaskName' registered. It runs from $Directory and logs to backfill.log there."
