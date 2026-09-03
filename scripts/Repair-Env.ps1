$ErrorActionPreference = "Stop"

function New-Secret([int]$Bytes) {
    $buffer = New-Object byte[] $Bytes
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    [Convert]::ToBase64String($buffer).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function Get-EnvValue([string]$Text, [string]$Key, [string]$Default = "") {
    $match = [regex]::Match($Text, "(?m)^$([regex]::Escape($Key))=(.*)$")
    if ($match.Success) {
        return $match.Groups[1].Value.Trim()
    }
    return $Default
}

function Set-EnvValue([string]$Text, [string]$Key, [string]$Value) {
    $line = "$Key=$Value"
    if ([regex]::IsMatch($Text, "(?m)^$([regex]::Escape($Key))=.*$")) {
        return [regex]::Replace($Text, "(?m)^$([regex]::Escape($Key))=.*$", $line)
    }
    return $Text.TrimEnd() + [Environment]::NewLine + $line + [Environment]::NewLine
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$envPath = Join-Path $root ".env"
$examplePath = Join-Path $root ".env.example"

if (-not (Test-Path $envPath)) {
    if (-not (Test-Path $examplePath)) {
        throw ".env.example was not found"
    }
    Copy-Item -LiteralPath $examplePath -Destination $envPath
}

$envText = Get-Content $envPath -Raw -Encoding UTF8
$postgresUser = Get-EnvValue $envText "POSTGRES_USER" "content_tracker"
$postgresDb = Get-EnvValue $envText "POSTGRES_DB" "content_tracker"
$postgresPassword = New-Secret 24
$jwtSecret = Get-EnvValue $envText "JWT_SECRET"

if ([string]::IsNullOrWhiteSpace($jwtSecret) -or $jwtSecret -eq "replace_with_a_long_random_secret") {
    $jwtSecret = New-Secret 48
}

$envText = Set-EnvValue $envText "POSTGRES_USER" $postgresUser
$envText = Set-EnvValue $envText "POSTGRES_DB" $postgresDb
$envText = Set-EnvValue $envText "POSTGRES_HOST" "postgres"
$envText = Set-EnvValue $envText "POSTGRES_PORT" "5432"
$envText = Set-EnvValue $envText "POSTGRES_PASSWORD" $postgresPassword
$envText = Set-EnvValue $envText "DATABASE_URL" "postgresql+asyncpg://$postgresUser`:$postgresPassword@postgres:5432/$postgresDb"
$envText = Set-EnvValue $envText "JWT_SECRET" $jwtSecret
$envText = Set-EnvValue $envText "ENV" "local"

Set-Content -Path $envPath -Value $envText -Encoding UTF8

Write-Host "[repair-env] .env repaired."
Write-Host "[repair-env] Starting database..."
& docker compose up -d postgres redis
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$ready = $false
for ($i = 1; $i -le 30; $i++) {
    & docker compose exec -T postgres pg_isready -h localhost -U $postgresUser | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
        break
    }
    Start-Sleep -Seconds 2
}

if (-not $ready) {
    throw "Postgres did not become ready in time"
}

Write-Host "[repair-env] Synchronizing Postgres password..."
$escapedPassword = $postgresPassword.Replace("'", "''")
$escapedUser = $postgresUser.Replace('"', '""')
$sql = "ALTER USER ""$escapedUser"" WITH PASSWORD '$escapedPassword';"
$sql | & docker compose exec -T postgres psql -U $postgresUser -d $postgresDb
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host "[repair-env] Rebuilding and restarting app..."
& docker compose up --build -d
exit $LASTEXITCODE
