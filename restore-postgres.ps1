param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile,

    [Parameter(Mandatory = $true)]
    [string]$ConfirmDatabaseName,

    [switch]$ConfirmRestore
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PostgresTools.ps1')

$databaseName = Set-GpmsPostgresEnvironment
Assert-GpmsPostgresTool 'pg_restore'

if (-not $ConfirmRestore) {
    throw 'Restore is destructive. Re-run with -ConfirmRestore after verifying the target and backup.'
}
if ($ConfirmDatabaseName -cne $databaseName) {
    throw "The confirmation must exactly match the target database name '$databaseName'."
}
$resolvedBackupFile = (Resolve-Path -LiteralPath $BackupFile -ErrorAction Stop).Path
if (-not (Test-Path -LiteralPath $resolvedBackupFile -PathType Leaf)) {
    throw 'The backup path must identify a readable backup file.'
}

# Validate the custom archive before the guarded destructive restore.
& pg_restore --list $resolvedBackupFile | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "The backup archive could not be read (pg_restore exit code $LASTEXITCODE). No restore was attempted."
}

Write-Warning "This replaces database objects in '$databaseName'. Confirm downtime, a verified backup, and an approved recovery window."
& pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error --single-transaction --no-password --dbname $databaseName $resolvedBackupFile
if ($LASTEXITCODE -ne 0) {
    throw "pg_restore failed with exit code $LASTEXITCODE. Review database state before allowing traffic."
}

Write-Output "Restore completed for database '$databaseName'. Apply/check migrations and verify the application before reopening traffic."
