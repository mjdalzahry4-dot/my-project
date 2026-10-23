param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PostgresTools.ps1')

$databaseName = Set-GpmsPostgresEnvironment
Assert-GpmsPostgresTool 'pg_dump'

$resolvedOutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
if (-not (Test-Path -LiteralPath $resolvedOutputDirectory -PathType Container)) {
    throw 'The backup directory must already exist. Choose a protected directory outside the web root.'
}

$timestamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$backupPath = Join-Path $resolvedOutputDirectory "gpms-$databaseName-$timestamp.dump"
if (Test-Path -LiteralPath $backupPath) {
    throw "Refusing to overwrite an existing backup: $backupPath"
}

& pg_dump --format=custom --no-owner --no-privileges --no-password --file $backupPath
if ($LASTEXITCODE -ne 0) {
    throw "pg_dump failed with exit code $LASTEXITCODE. Inspect the partial file before removing it: $backupPath"
}

Get-Item -LiteralPath $backupPath | Select-Object FullName, Length, LastWriteTimeUtc
