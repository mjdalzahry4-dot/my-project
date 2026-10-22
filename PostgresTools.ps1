function Set-GpmsPostgresEnvironment {
    if ([string]::IsNullOrWhiteSpace($env:DATABASE_URL)) {
        throw 'Set DATABASE_URL in the process environment before calling this script.'
    }
    if ([string]::IsNullOrWhiteSpace($env:PGPASSFILE) -or -not (Test-Path -LiteralPath $env:PGPASSFILE -PathType Leaf)) {
        throw 'Set PGPASSFILE to a protected PostgreSQL password file. Do not put the database password on a command line.'
    }

    $databaseUri = $null
    if (-not [System.Uri]::TryCreate($env:DATABASE_URL, [System.UriKind]::Absolute, [ref]$databaseUri)) {
        throw 'DATABASE_URL is not a valid absolute PostgreSQL URL.'
    }
    if ($databaseUri.Scheme -notin @('postgres', 'postgresql') -or -not $databaseUri.Host) {
        throw 'DATABASE_URL must use postgres:// or postgresql:// and include a host.'
    }
    $databaseName = [System.Uri]::UnescapeDataString($databaseUri.AbsolutePath.TrimStart('/'))
    if ([string]::IsNullOrWhiteSpace($databaseName)) {
        throw 'DATABASE_URL must include a database name.'
    }
    $userInfo = [System.Uri]::UnescapeDataString($databaseUri.UserInfo)
    $separator = $userInfo.IndexOf(':')
    if ($separator -lt 1) {
        throw 'DATABASE_URL must include a database username.'
    }

    $sslMode = if ($env:DATABASE_SSLMODE) { $env:DATABASE_SSLMODE } else { 'verify-full' }
    if ($sslMode -notin @('verify-full', 'verify-ca')) {
        throw 'DATABASE_SSLMODE must be verify-full or verify-ca for these operations.'
    }
    if ($env:DATABASE_SSLROOTCERT -and -not (Test-Path -LiteralPath $env:DATABASE_SSLROOTCERT -PathType Leaf)) {
        throw 'DATABASE_SSLROOTCERT points to a file that does not exist.'
    }

    $env:PGHOST = $databaseUri.Host
    $env:PGPORT = if ($databaseUri.IsDefaultPort) { '5432' } else { [string]$databaseUri.Port }
    $env:PGDATABASE = $databaseName
    $env:PGUSER = $userInfo.Substring(0, $separator)
    $env:PGPASSFILE = (Resolve-Path -LiteralPath $env:PGPASSFILE).Path
    $env:PGSSLMODE = $sslMode
    if ($env:DATABASE_SSLROOTCERT) {
        $env:PGSSLROOTCERT = (Resolve-Path -LiteralPath $env:DATABASE_SSLROOTCERT).Path
    }

    return $databaseName
}

function Assert-GpmsPostgresTool([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "PostgreSQL client tool '$Name' was not found. Install the matching PostgreSQL client utilities first."
    }
}
