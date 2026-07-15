<#
Deploys dt_sales_bot to Cloud Run.

Reads secrets from your local .env (or credentials/service_account.json) and
syncs them into Secret Manager, then builds+deploys the Dockerfile via
`gcloud run deploy --source .`.

Usage:
    ./deploy.ps1 -ProjectId my-gcp-project
    ./deploy.ps1 -ProjectId my-gcp-project -Region us-central1

Prerequisites:
    - gcloud CLI installed and authenticated (`gcloud auth login`)
    - Cloud Run, Cloud Build, Artifact Registry, Secret Manager APIs enabled
      on the target project (the script enables them if missing)
    - .env filled in locally (copy from .env.example)
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,
    [string]$Region = "europe-west1",
    [string]$ServiceName = "dt-sales-bot",
    [string]$EnvFile = ".env",
    [string]$ServiceAccountFile = "credentials/service_account.json",
    [switch]$AllowUnauthenticated
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) {
    throw "$EnvFile not found. Copy .env.example to .env and fill in values first."
}

Write-Host "Enabling required APIs..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com `
    artifactregistry.googleapis.com secretmanager.googleapis.com `
    --project $ProjectId | Out-Null

# --- Parse .env (KEY=VALUE lines, ignoring comments/blank lines) ---
$envVars = @{}
foreach ($line in Get-Content $EnvFile) {
    if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
    $parts = $line.Split('=', 2)
    $envVars[$parts[0].Trim()] = $parts[1].Trim()
}

function Sync-SecretFromValue {
    param([string]$Name, [string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $false }
    $tmp = New-TemporaryFile
    # Windows PowerShell 5.1's -Encoding utf8 always prepends a UTF-8 BOM,
    # which then gets uploaded byte-for-byte as the secret's content and
    # breaks smtplib's .encode("ascii") on login. Write BOM-less UTF-8 instead.
    [System.IO.File]::WriteAllText($tmp, $Value, (New-Object System.Text.UTF8Encoding $false))
    Sync-SecretFromFile -Name $Name -FilePath $tmp
    Remove-Item $tmp
    return $true
}

function Test-SecretExists {
    param([string]$Name)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        gcloud secrets describe $Name --project $ProjectId --format="value(name)" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prevEap
    }
}

function Sync-SecretFromFile {
    param([string]$Name, [string]$FilePath)
    if (Test-SecretExists -Name $Name) {
        gcloud secrets versions add $Name --project $ProjectId --data-file $FilePath | Out-Null
    } else {
        gcloud secrets create $Name --project $ProjectId --data-file $FilePath --replication-policy automatic | Out-Null
    }
}

Write-Host "Syncing secrets to Secret Manager..."

$secretEnvFlags = @()

$required = @{
    "OPENAI_API_KEY"     = "dt-sales-bot-openai-api-key"
    "EMAIL_APP_PASSWORD" = "dt-sales-bot-email-app-password"
}
foreach ($key in $required.Keys) {
    $secretName = $required[$key]
    $ok = Sync-SecretFromValue -Name $secretName -Value $envVars[$key]
    if (-not $ok) { throw "$key is required in $EnvFile but is empty." }
    $secretEnvFlags += "$key=${secretName}:latest"
}

if (Sync-SecretFromValue -Name "dt-sales-bot-gemini-api-key" -Value $envVars["GEMINI_API_KEY"]) {
    $secretEnvFlags += "GEMINI_API_KEY=dt-sales-bot-gemini-api-key:latest"
}

if (Sync-SecretFromValue -Name "dt-sales-bot-pushover-api-token" -Value $envVars["PUSHOVER_API_TOKEN"]) {
    $secretEnvFlags += "PUSHOVER_API_TOKEN=dt-sales-bot-pushover-api-token:latest"
}
if (Sync-SecretFromValue -Name "dt-sales-bot-pushover-user-key" -Value $envVars["PUSHOVER_USER_KEY"]) {
    $secretEnvFlags += "PUSHOVER_USER_KEY=dt-sales-bot-pushover-user-key:latest"
}

$hasCrm = $false
if (Test-Path $ServiceAccountFile) {
    Sync-SecretFromFile -Name "dt-sales-bot-google-service-account" -FilePath $ServiceAccountFile
    $secretEnvFlags += "GOOGLE_SERVICE_ACCOUNT_JSON=dt-sales-bot-google-service-account:latest"
    $hasCrm = $true
} elseif (-not [string]::IsNullOrWhiteSpace($envVars["GOOGLE_SERVICE_ACCOUNT_JSON"])) {
    # Only safe for single-line JSON; multi-line values need the file path above.
    if (Sync-SecretFromValue -Name "dt-sales-bot-google-service-account" -Value $envVars["GOOGLE_SERVICE_ACCOUNT_JSON"]) {
        $secretEnvFlags += "GOOGLE_SERVICE_ACCOUNT_JSON=dt-sales-bot-google-service-account:latest"
        $hasCrm = $true
    }
} else {
    Write-Warning "No Google service account found ($ServiceAccountFile or GOOGLE_SERVICE_ACCOUNT_JSON) - CRM tools will be disabled."
}

# --- Plain (non-secret) env vars ---
function Get-EnvOrDefault {
    param([string]$Key, [string]$Default = "")
    if ($envVars.ContainsKey($Key) -and -not [string]::IsNullOrWhiteSpace($envVars[$Key])) {
        return $envVars[$Key]
    }
    return $Default
}

$plainEnv = @(
    "DEFAULT_MODEL_NAME=$(Get-EnvOrDefault 'DEFAULT_MODEL_NAME' 'gpt-4.1')",
    "GEMINI_MODEL_NAME=$(Get-EnvOrDefault 'GEMINI_MODEL_NAME' 'gemini-3.1-flash-lite')",
    "EMAIL_ADDRESS=$(Get-EnvOrDefault 'EMAIL_ADDRESS')",
    "EMAIL_SMTP_SERVER=$(Get-EnvOrDefault 'EMAIL_SMTP_SERVER' 'smtp.gmail.com')"
)
if ($hasCrm) {
    $plainEnv += "GOOGLE_APPLICATION_CREDENTIALS=credentials/service_account.json"
    $plainEnv += "GOOGLE_SHEET_ID=$(Get-EnvOrDefault 'GOOGLE_SHEET_ID')"
    $plainEnv += "GOOGLE_SHEETS_WORKSHEET_NAME=$(Get-EnvOrDefault 'GOOGLE_SHEETS_WORKSHEET_NAME' 'Leads')"
}

$deployArgs = @(
    "run", "deploy", $ServiceName,
    "--project", $ProjectId,
    "--region", $Region,
    "--source", ".",
    "--set-env-vars", ($plainEnv -join ","),
    "--set-secrets", ($secretEnvFlags -join ","),
    # Sessions live in an in-process dict + local SQLite file, so keep this at
    # a single instance to avoid splitting a user's conversation across
    # containers (Cloud Run still scales that one instance to zero when idle).
    "--min-instances", "0",
    "--max-instances", "1",
    "--memory", "1Gi",
    "--timeout", "300",
    "--quiet"
)
if ($AllowUnauthenticated) {
    $deployArgs += "--allow-unauthenticated"
}

Write-Host "Deploying $ServiceName to Cloud Run ($Region)..."
& gcloud @deployArgs
