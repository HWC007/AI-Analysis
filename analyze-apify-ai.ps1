[CmdletBinding()]
param(
    [string]$InputPath = '.\Apify-raw-structured.csv',
    [string]$OutputPath = '.\Apify-raw-structured.csv',
    [string]$ApiKeyPath = '.\openai-api.txt',
    [string]$OpenAIKey = $env:OPENAI_API_KEY,
    [string]$BaseUrl = 'http://ai.moldex3d.com:4000/v1',
    [string]$Model = 'gpt-5.6-luna',
    [int]$BatchSize = 10,
    [int]$MaxRetries = 3,
    [switch]$ReanalyzeAll
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($OpenAIKey) -and (Test-Path -LiteralPath $ApiKeyPath -PathType Leaf)) {
    $OpenAIKey = (Get-Content -LiteralPath $ApiKeyPath -Raw).Trim()
}
if ([string]::IsNullOrWhiteSpace($OpenAIKey)) {
    throw "No OpenAI API key supplied. Set `$env:OPENAI_API_KEY or create $ApiKeyPath containing only the key."
}
if (-not (Test-Path -LiteralPath $InputPath -PathType Leaf)) { throw "Input file not found: $InputPath" }

$systemPrompt = @'
You are a prospect qualification specialist for injection molding manufacturers and professionals.

Evaluate EVERY prospect against ALL FIVE priorities. Do not stop after finding a match. Translate non-English text internally before analyzing it. Use all supplied tenure fields to understand the timeline. Do not invent facts. If company identity is uncertain, state that limitation clearly.

PRIORITY 1 — COMPANY ANALYSIS
Analyze Current_Company. Determine whether it is involved in the injection-molding lifecycle through: (a) service providers that design/build molds, produce molded parts for others, or make molding equipment; (b) product manufacturers/OEMs whose physical products heavily use plastic components; or (c) simulation and engineering providers for plastic parts. You MUST use web search to research the current company whenever the supplied profile does not make the classification 100% certain. Search the company name together with relevant terms such as injection molding, plastic parts, tooling, mold design, products, manufacturing, and engineering. Prefer the company’s official website and reliable industry sources. Do not guess from the company name alone. State what was searched and summarize the evidence or explain why the evidence remains inconclusive. Give a detailed company-specific explanation and identify the category, if applicable.

PRIORITY 2 — CURRENT POSITION ANALYSIS
Analyze Current_Position, Current_Position_Description, Headline, and Current_Tenure. Determine whether the current role involves injection molding. For a service provider or simulation/engineering company, apply high inference to technical/design roles. For an OEM, do not assume: require plastic-specific evidence such as plastic-part design, lightweight components, enclosures, tooling, injection molding, Moldflow, or Cadmould. Explain the exact evidence or its absence.

PRIORITY 3 — PREVIOUS POSITION AND BACKGROUND
Analyze all three past positions, descriptions, tenures, About, Skills, and top_skills. Determine whether there is ANY prior injection-molding or mold-design experience. Cover both positive and negative evidence, including the relevant company, role, timeframe, and keywords.

PRIORITY 4 — COMPETITOR / ALTERNATIVE SOFTWARE
Search case-insensitively for Moldflow, Cadmould, and Solidworks plastic. Check Skills separately from every other section, including About, Headline, current and past roles/descriptions, and top_skills. Set p4_in_skills_only true only when a keyword occurs in Skills and nowhere else. Set p4_in_other_sections true when a keyword occurs outside Skills. Explain exactly which keyword and section contained it. Priority 4 is informational and does not affect judgement.

PRIORITY 5 — MOLDEX3D FALSE-POSITIVE AVOIDANCE
Search all sections for Moldex3D or Moldex. Moldex3D is always injection-molding software. If only Moldex appears, distinguish molding software/CoreTech/CAE/plastic simulation from unrelated Moldex companies or products. Explain the context and result.

FINAL JUDGEMENT
Judgement is Yes if ANY of Priority 1, 2, 3, or 5 is true. Judgement is No only if all four are false. Priority 4 never changes judgement.

EXPLANATION QUALITY
Write a detailed, evidence-based explanation of at least 700 characters. Include a separate labeled paragraph for each Priority 1 through Priority 5. Each paragraph must state True/False, cite the relevant fields, explain the reasoning, and mention important missing evidence where applicable. Do not merely repeat the input. Return only valid JSON, with no markdown fences or extra text.
'@

$schema = @{
    type = 'object'
    additionalProperties = $false
    properties = [ordered]@{
        judgement = @{ type = 'string'; enum = @('Yes','No') }
        priority_1_satisfied = @{ type = 'boolean' }
        priority_2_satisfied = @{ type = 'boolean' }
        priority_3_satisfied = @{ type = 'boolean' }
        priority_4_satisfied = @{ type = 'boolean' }
        priority_5_satisfied = @{ type = 'boolean' }
        p4_in_skills_only = @{ type = 'boolean' }
        p4_in_other_sections = @{ type = 'boolean' }
        explanation = @{ type = 'string' }
    }
    required = @('judgement','priority_1_satisfied','priority_2_satisfied','priority_3_satisfied','priority_4_satisfied','priority_5_satisfied','p4_in_skills_only','p4_in_other_sections','explanation')
} | ConvertTo-Json -Depth 10 -Compress

function Get-AnalysisValue {
    param([AllowNull()][object]$Object, [Parameter(Mandatory = $true)][string]$Property)
    if ($null -eq $Object) { return $null }
    $p = $Object.PSObject.Properties[$Property]
    if ($null -eq $p) { return $null }
    return $p.Value
}

function Invoke-Qualification {
    param([hashtable]$Profile)
    $payload = @{
        model = $Model
        messages = @(
            @{ role = 'system'; content = $systemPrompt },
            @{ role = 'user'; content = ('Prospect data:`n' + ($Profile | ConvertTo-Json -Depth 10)) }
        )
    }
    $body = $payload | ConvertTo-Json -Depth 20
    $uri = ($BaseUrl.TrimEnd('/') + '/chat/completions')
    $headers = @{ Authorization = "Bearer $OpenAIKey" }
    for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
        try {
            $response = Invoke-RestMethod -Method Post -Uri $uri -Headers $headers -ContentType 'application/json' -Body $body
            $content = [string]$response.choices[0].message.content
            if ($content) {
                $parsed = $content | ConvertFrom-Json
                # Luna may return detailed nested priority objects instead of the
                # flat n8n-compatible schema. Flatten that response here.
                if ([string]::IsNullOrWhiteSpace([string]$parsed.explanation)) {
                    $parts = @()
                    foreach ($name in @('priority_1_company_analysis','priority_2_current_position_analysis','priority_3_previous_position_and_background','priority_4_competitor_alternative_software','priority_5_moldex3d_false_positive_avoidance')) {
                        $section = $parsed.PSObject.Properties[$name]
                        if ($null -ne $section) {
                            $value = $section.Value
                            $flag = [string](Get-AnalysisValue $value 'true')
                            $detail = [string](Get-AnalysisValue $value 'explanation')
                            if ($detail) { $parts += ("$name = $flag. $detail") }
                        }
                    }
                    foreach ($name in @('evidence_limitations','final_reasoning')) {
                        $detail = [string](Get-AnalysisValue $parsed $name)
                        if ($detail) { $parts += ("$name. $detail") }
                    }
                    if ($parts.Count -lt 5) { $parts = @($content) }
                    if ($parts.Count -gt 0) { $parsed | Add-Member -Force -NotePropertyName explanation -NotePropertyValue ($parts -join "`n`n") | Out-Null }
                }
                if ($null -eq $parsed.priority_1_satisfied) { $parsed | Add-Member -Force -NotePropertyName priority_1_satisfied -NotePropertyValue ([bool](Get-AnalysisValue (Get-AnalysisValue $parsed 'priority_1_company_analysis') 'true')) | Out-Null }
                if ($null -eq $parsed.priority_2_satisfied) { $parsed | Add-Member -Force -NotePropertyName priority_2_satisfied -NotePropertyValue ([bool](Get-AnalysisValue (Get-AnalysisValue $parsed 'priority_2_current_position_analysis') 'true')) | Out-Null }
                if ($null -eq $parsed.priority_3_satisfied) { $parsed | Add-Member -Force -NotePropertyName priority_3_satisfied -NotePropertyValue ([bool](Get-AnalysisValue (Get-AnalysisValue $parsed 'priority_3_previous_position_and_background') 'true')) | Out-Null }
                if ($null -eq $parsed.priority_4_satisfied) { $parsed | Add-Member -Force -NotePropertyName priority_4_satisfied -NotePropertyValue ([bool](Get-AnalysisValue (Get-AnalysisValue $parsed 'priority_4_competitor_alternative_software') 'true')) | Out-Null }
                if ($null -eq $parsed.priority_5_satisfied) { $parsed | Add-Member -Force -NotePropertyName priority_5_satisfied -NotePropertyValue ([bool](Get-AnalysisValue (Get-AnalysisValue $parsed 'priority_5_moldex3d_false_positive_avoidance') 'true')) | Out-Null }
                if ($null -eq $parsed.p4_in_skills_only) { $parsed | Add-Member -Force -NotePropertyName p4_in_skills_only -NotePropertyValue ([bool](Get-AnalysisValue (Get-AnalysisValue $parsed 'priority_4_competitor_alternative_software') 'p4_in_skills_only')) | Out-Null }
                if ($null -eq $parsed.p4_in_other_sections) { $parsed | Add-Member -Force -NotePropertyName p4_in_other_sections -NotePropertyValue ([bool](Get-AnalysisValue (Get-AnalysisValue $parsed 'priority_4_competitor_alternative_software') 'p4_in_other_sections')) | Out-Null }
                return $parsed
            }
            throw 'The LiteLLM endpoint returned no message content.'
        } catch {
            $detail = $_.Exception.Message
            if ($_.Exception.Response) {
                try {
                    $reader = [System.IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
                    $detail = $reader.ReadToEnd()
                    $reader.Dispose()
                } catch { }
            }
            if ($attempt -eq $MaxRetries) { throw "LiteLLM request failed: $detail" }
            Start-Sleep -Seconds ([math]::Min(30, [math]::Pow(2, $attempt)))
        }
    }
}

$rows = @(Import-Csv -LiteralPath $InputPath)
$targets = @($rows | Where-Object { $ReanalyzeAll -or [string]::IsNullOrWhiteSpace($_.AI_Judgement) -or $_.AI_Judgement -eq 'Error' })
Write-Output "Profiles to analyze: $($targets.Count)"

for ($i = 0; $i -lt $targets.Count; $i++) {
    $row = $targets[$i]
    $profile = [ordered]@{}
    foreach ($column in $row.PSObject.Properties.Name) {
        if ($column -notin @('AI_Judgement','AI_Weighting','AI_Explanation','createdAt','updatedAt')) {
            $value = [string]$row.$column
            if ($column -match 'Tenure$') { $value = $value -replace [char]0x00B7, '-' }
            $profile[$column] = $value
        }
    }
    try {
        $result = Invoke-Qualification $profile
        $p4Score = if ($result.p4_in_other_sections) { 0.05 } elseif ($result.p4_in_skills_only) { 0.025 } else { 0 }
        $p1Score = if ($result.priority_1_satisfied) { 2 } else { 0 }
        $p2Score = if ($result.priority_2_satisfied) { 2.5 } else { 0 }
        $p3Score = if ($result.priority_3_satisfied -and ($result.priority_1_satisfied -or $result.priority_2_satisfied)) { 1 } else { 0 }
        $p5Score = if ($result.priority_5_satisfied) { 5 } else { 0 }
        $row.AI_Judgement = if ($result.priority_1_satisfied -or $result.priority_2_satisfied -or $result.priority_3_satisfied -or $result.priority_5_satisfied) { 'Yes' } else { 'No' }
        $row.AI_Weighting = [math]::Round(($p1Score + $p2Score + $p3Score + $p4Score + $p5Score), 3)
        $row.AI_Explanation = [string]$result.explanation
        $row.updatedAt = (Get-Date).ToUniversalTime().ToString('o')
    } catch {
        $row.AI_Judgement = 'Error'
        $row.AI_Weighting = 0
        $row.AI_Explanation = "GPT-5 analysis failed: $($_.Exception.Message)"
    }
    if ((($i + 1) % $BatchSize) -eq 0 -or $i -eq ($targets.Count - 1)) {
        $rows | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding UTF8
        Write-Output "Processed $($i + 1) / $($targets.Count)"
    }
}

if ($targets.Count -eq 0) { $rows | Export-Csv -LiteralPath $OutputPath -NoTypeInformation -Encoding UTF8 }
Write-Output "Saved analysis to $OutputPath"
