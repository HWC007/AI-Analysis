[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [string]$OutputPath = '.\Apify-raw-structured.csv',

    [string]$ApifyToken = '',

    [string]$TokenPath = '.\apify-api.txt',

    [int]$StartingId = 1,

    [switch]$Replace
)

$ErrorActionPreference = 'Stop'
$actorId = 'apimaestro~linkedin-profile-full-sections-scraper'

if ([string]::IsNullOrWhiteSpace($ApifyToken)) {
    $ApifyToken = $env:APIFY_TOKEN
}

if ([string]::IsNullOrWhiteSpace($ApifyToken) -and (Test-Path -LiteralPath $TokenPath -PathType Leaf)) {
    $ApifyToken = (Get-Content -LiteralPath $TokenPath -Raw).Trim()
}

if ([string]::IsNullOrWhiteSpace($ApifyToken)) {
    throw "No Apify token supplied. Set `$env:APIFY_TOKEN, pass -ApifyToken, or create $TokenPath containing only the token."
}

if (-not (Test-Path -LiteralPath $InputPath -PathType Leaf)) {
    throw "Input file not found: $InputPath"
}

$input = Get-Content -LiteralPath $InputPath -Raw | ConvertFrom-Json
if ($null -eq $input.usernames -or @($input.usernames).Count -eq 0) {
    throw 'The input JSON must contain a non-empty usernames array.'
}

# This endpoint starts the Actor, waits for completion, and returns dataset items.
$uri = "https://api.apify.com/v2/acts/$actorId/run-sync-get-dataset-items?token=$([uri]::EscapeDataString($ApifyToken))"
$rawItems = @(Invoke-RestMethod -Method Post -Uri $uri -ContentType 'application/json' -Body ($input | ConvertTo-Json -Depth 20) | ForEach-Object { $_ })

function Get-Value {
    param(
        [AllowNull()][object]$Object,
        [Parameter(Mandatory = $true)][string]$Property,
        [AllowNull()][object]$Default = ''
    )
    if ($null -eq $Object) { return $Default }
    $propertyInfo = $Object.PSObject.Properties[$Property]
    if ($null -eq $propertyInfo -or $null -eq $propertyInfo.Value) { return $Default }
    return $propertyInfo.Value
}

function Get-ArrayItem {
    param(
        [AllowNull()][object]$Array,
        [int]$Index
    )
    $items = @($Array)
    if ($Index -lt 0 -or $Index -ge $items.Count) { return $null }
    return $items[$Index]
}

function Join-Names {
    param([AllowNull()][object]$Items)
    return (@($Items) | ForEach-Object { [string](Get-Value $_ 'name') } | Where-Object { $_ }) -join ', '
}

$newProfiles = for ($i = 0; $i -lt $rawItems.Count; $i++) {
    $item = $rawItems[$i]
    $basic = Get-Value $item 'basic_info'
    $location = Get-Value $basic 'location'
    $experience = @(Get-Value $item 'experience' @())
    $current = Get-ArrayItem $experience 0
    $past1 = Get-ArrayItem $experience 1
    $past2 = Get-ArrayItem $experience 2
    $past3 = Get-ArrayItem $experience 3

    [pscustomobject][ordered]@{
        id                              = $StartingId + $i
        fullname                        = Get-Value $basic 'fullname'
        first_name                      = Get-Value $basic 'first_name'
        last_name                       = Get-Value $basic 'last_name'
        headline                        = Get-Value $basic 'headline'
        LinkedIn_URL                    = Get-Value $basic 'profile_url'
        location                        = Get-Value $location 'full'
        country                         = Get-Value $location 'country'
        city                            = Get-Value $location 'city'
        follower_count                  = Get-Value $basic 'follower_count'
        connection_count                = Get-Value $basic 'connection_count'
        about                           = Get-Value $basic 'about'
        Skills                          = Join-Names (Get-Value $item 'skills' @())
        top_skills                      = (@(Get-Value $basic 'top_skills' @()) -join ', ')
        Current_Company                 = Get-Value $current 'company'
        Current_Position                = Get-Value $current 'title'
        Current_Position_Description    = Get-Value $current 'description'
        Current_Tenure                  = Get-Value $current 'duration'
        Past_Company_1                  = Get-Value $past1 'company'
        Past_Position_1                 = Get-Value $past1 'title'
        Past_Position_1_Description     = Get-Value $past1 'description'
        Past_Position_1_Tenure           = Get-Value $past1 'duration'
        Past_Company_2                  = Get-Value $past2 'company'
        Past_Position_2                 = Get-Value $past2 'title'
        Past_Position_2_Description     = Get-Value $past2 'description'
        Past_Position_2_Tenure           = Get-Value $past2 'duration'
        Past_Company_3                  = Get-Value $past3 'company'
        Past_Position_3                 = Get-Value $past3 'title'
        Past_Position_3_Description     = Get-Value $past3 'description'
        Past_Position_3_Tenure           = Get-Value $past3 'duration'
        AI_Judgement                    = ''
        AI_Weighting                    = ''
        AI_Explanation                  = ''
        createdAt                       = (Get-Date).ToUniversalTime().ToString('o')
        updatedAt                       = (Get-Date).ToUniversalTime().ToString('o')
    }
}

$existing = @()
if ((-not $Replace) -and (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
    $existing = @(Import-Csv -LiteralPath $OutputPath)
}

# Upgrade older output files that were created before the AI columns existed.
foreach ($old in $existing) {
    foreach ($column in @('AI_Judgement', 'AI_Weighting', 'AI_Explanation')) {
        if ($null -eq $old.PSObject.Properties[$column]) {
            $old | Add-Member -NotePropertyName $column -NotePropertyValue ''
        }
    }
}

$nextId = $StartingId
if ($existing.Count -gt 0) {
    $numericIds = @($existing | ForEach-Object { $parsed = 0; if ([int]::TryParse([string]$_.id, [ref]$parsed)) { $parsed } })
    if ($numericIds.Count -gt 0) { $nextId = ([int](($numericIds | Measure-Object -Maximum).Maximum)) + 1 }
}

$existingUrls = @{}
foreach ($old in $existing) {
    $url = ([string]$old.LinkedIn_URL).Trim().TrimEnd('/')
    if ($url) { $existingUrls[$url.ToLowerInvariant()] = $true }
}

$toAdd = @()
foreach ($profile in $newProfiles) {
    $url = ([string]$profile.LinkedIn_URL).Trim().TrimEnd('/')
    if ($url -and $existingUrls.ContainsKey($url.ToLowerInvariant())) { continue }
    $profile.id = $nextId
    $nextId++
    $toAdd += $profile
    if ($url) { $existingUrls[$url.ToLowerInvariant()] = $true }
}

$structured = @($existing + $toAdd)
$structured | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding UTF8
Write-Output "Saved $($structured.Count) total profiles to $OutputPath; added $($toAdd.Count); skipped $($newProfiles.Count - $toAdd.Count) duplicates."
