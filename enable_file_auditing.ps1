<#
Turns on Windows file-access auditing for the TÜRKAK folder so that
file_access_collector.py can report who read / wrote / copied / deleted files.

Run ON THE FILE SERVER (192.168.100.3) in an elevated PowerShell:

  powershell -ExecutionPolicy Bypass -File enable_file_auditing.ps1 -CollectorAccount "ARES\eren.turan"

What it changes:
  1. Audit policy: "File System" (event 4663) and, unless -NoShareEvents,
     "Detailed File Share" (event 5145, adds the client IP) - success only.
  2. Adds an audit rule (SACL) for Everyone on the TÜRKAK folder, inherited by
     all subfolders and files: read data, write/append data, delete,
     change permissions, take ownership. Existing permissions are untouched.
  3. Grows the Security log so events aren't overwritten before collection.
  4. Optionally lets -CollectorAccount read the Security log remotely
     (Event Log Readers group + "Remote Event Log Management" firewall rules).

Subcategories and the Everyone group are addressed by GUID/SID, so this also
works on a Turkish-language Windows.
#>
param(
    [string]$ShareName = "test",
    [string]$SubFolder = "TÜRKAK",
    [string]$FolderPath,
    [string]$CollectorAccount,
    [int]$SecurityLogSizeMB = 1024,
    [switch]$NoShareEvents
)

$ErrorActionPreference = "Stop"

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this in an elevated (Run as administrator) PowerShell on the file server."
}

if (-not $FolderPath) {
    $share = Get-SmbShare -Name $ShareName
    $FolderPath = Join-Path $share.Path $SubFolder
}
if (-not (Test-Path -LiteralPath $FolderPath -PathType Container)) {
    throw "Folder not found: $FolderPath (pass -FolderPath explicitly)."
}
Write-Host "Folder: $FolderPath"

# 1. Audit policy
$FileSystem = "{0CCE921D-69AE-11D9-BED3-505054503030}"
$DetailedFileShare = "{0CCE9244-69AE-11D9-BED3-505054503030}"
auditpol /set /subcategory:$FileSystem /success:enable | Out-Null
if (-not $NoShareEvents) {
    auditpol /set /subcategory:$DetailedFileShare /success:enable | Out-Null
}
Write-Host "Audit policy:"
auditpol /get /subcategory:$FileSystem
if (-not $NoShareEvents) { auditpol /get /subcategory:$DetailedFileShare }

# 2. SACL on the folder (audit section only - access permissions are not touched)
$rights = [Security.AccessControl.FileSystemRights]"ReadData, WriteData, AppendData, Delete, ChangePermissions, TakeOwnership"
$everyone = New-Object Security.Principal.SecurityIdentifier("S-1-1-0")
$rule = New-Object Security.AccessControl.FileSystemAuditRule(
    $everyone, $rights,
    [Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit",
    [Security.AccessControl.PropagationFlags]::None,
    [Security.AccessControl.AuditFlags]::Success)
$dir = Get-Item -LiteralPath $FolderPath
$sacl = $dir.GetAccessControl([Security.AccessControl.AccessControlSections]::Audit)
$sacl.AddAuditRule($rule)
$dir.SetAccessControl($sacl)
Write-Host "Audit rule added for Everyone on $FolderPath (inherited by subfolders and files)."

# 3. Security log size
$logBytes = [int64]$SecurityLogSizeMB * 1MB
wevtutil sl Security "/ms:$logBytes"
if ($LASTEXITCODE -ne 0) { throw "wevtutil could not resize the Security log (exit $LASTEXITCODE)." }
Write-Host "Security log max size: $SecurityLogSizeMB MB"

# 4. Remote read access for the collector
if ($CollectorAccount) {
    try {
        Add-LocalGroupMember -SID "S-1-5-32-573" -Member $CollectorAccount
        Write-Host "$CollectorAccount added to Event Log Readers."
    } catch {
        if ($_.FullyQualifiedErrorId -like "MemberExists*") {
            Write-Host "$CollectorAccount is already in Event Log Readers."
        } else { throw }
    }
    $eventLogRules = Get-NetFirewallRule | Where-Object {
        ($_ | Get-NetFirewallServiceFilter).Service -eq "eventlog"
    }
    $eventLogRules | Enable-NetFirewallRule
    Write-Host "Enabled $(@($eventLogRules).Count) Remote Event Log Management firewall rule(s)."
}

Write-Host ""
Write-Host "Done. New events appear as users open or save files under $FolderPath."
Write-Host "Check with: Get-WinEvent -LogName Security -FilterXPath '*[System[EventID=4663]]' -MaxEvents 5"
