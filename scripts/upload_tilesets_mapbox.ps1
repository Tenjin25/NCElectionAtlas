param(
  [Parameter(Mandatory = $true)]
  [string]$Username,

  [Parameter(Mandatory = $true)]
  [string]$AccessToken
)

$ErrorActionPreference = "Stop"

function Invoke-Mapbox {
  param(
    [Parameter(Mandatory = $true)][string]$Method,
    [Parameter(Mandatory = $true)][string]$Url,
    [Parameter(Mandatory = $false)]$Body = $null,
    [Parameter(Mandatory = $false)]$ContentType = $null
  )

  if ($null -ne $Body -and $null -ne $ContentType) {
    return Invoke-RestMethod -Method $Method -Uri $Url -Body $Body -ContentType $ContentType
  }
  if ($null -ne $Body) {
    return Invoke-RestMethod -Method $Method -Uri $Url -Body $Body
  }
  return Invoke-RestMethod -Method $Method -Uri $Url
}

function Upload-Source {
  param(
    [Parameter(Mandatory = $true)][string]$SourceId,
    [Parameter(Mandatory = $true)][string]$FilePath
  )
  $url = "https://api.mapbox.com/tilesets/v1/sources/$Username/$SourceId?access_token=$AccessToken"
  Write-Host "Uploading source: $SourceId"
  $curlOut = & curl.exe -sS -X POST -F "file=@$FilePath" $url
  if ($LASTEXITCODE -ne 0) {
    throw "curl upload failed for $SourceId"
  }
  if ($curlOut -match '"message"\s*:') {
    throw "Mapbox upload error for ${SourceId}: $curlOut"
  }
  return $curlOut
}

function Upsert-Tileset {
  param(
    [Parameter(Mandatory = $true)][string]$TilesetId,
    [Parameter(Mandatory = $true)][string]$LayerName,
    [Parameter(Mandatory = $true)][string]$SourceId
  )

  $url = "https://api.mapbox.com/tilesets/v1/$TilesetId?access_token=$AccessToken"
  $recipe = @{
    version = 1
    layers = @{
      $LayerName = @{
        source  = "mapbox://tileset-source/$Username/$SourceId"
        minzoom = 0
        maxzoom = 12
      }
    }
  } | ConvertTo-Json -Depth 6 -Compress

  $body = @{
    recipe = $recipe
    name   = $TilesetId
  } | ConvertTo-Json -Depth 4 -Compress

  try {
    Write-Host "Creating tileset: $TilesetId"
    Invoke-Mapbox -Method Post -Url "https://api.mapbox.com/tilesets/v1/$TilesetId?access_token=$AccessToken" -Body $body -ContentType "application/json" | Out-Null
  } catch {
    Write-Host "Create failed (may already exist), trying update: $TilesetId"
    Invoke-Mapbox -Method Patch -Url $url -Body $body -ContentType "application/json" | Out-Null
  }
}

function Publish-Tileset {
  param(
    [Parameter(Mandatory = $true)][string]$TilesetId
  )
  $url = "https://api.mapbox.com/tilesets/v1/$TilesetId/publish?access_token=$AccessToken"
  Write-Host "Publishing: $TilesetId"
  return Invoke-Mapbox -Method Post -Url $url
}

if (-not $AccessToken.StartsWith("sk.")) {
  throw "AccessToken must be a Mapbox secret token (sk.*) with tilesets:read and tilesets:write scopes."
}

$root = Split-Path -Parent $PSScriptRoot
$tilesetDir = Join-Path $root "data\tileset"

$jobs = @(
  @{
    SourceId  = "nc_state_house_2022_lines_src"
    FilePath  = Join-Path $tilesetDir "nc_state_house_2022_lines_tileset.ldgeojson"
    TilesetId = "$Username.nc_state_house_2022_lines"
    LayerName = "state_house"
  },
  @{
    SourceId  = "nc_state_senate_2022_lines_src"
    FilePath  = Join-Path $tilesetDir "nc_state_senate_2022_lines_tileset.ldgeojson"
    TilesetId = "$Username.nc_state_senate_2022_lines"
    LayerName = "state_senate"
  },
  @{
    SourceId  = "nc_cd118_src"
    FilePath  = Join-Path $tilesetDir "nc_cd118_tileset.ldgeojson"
    TilesetId = "$Username.nc_cd118"
    LayerName = "cd118"
  }
)

foreach ($j in $jobs) {
  if (-not (Test-Path $j.FilePath)) {
    throw "Missing file: $($j.FilePath). Run scripts/build_tileset_sources.py first."
  }

  Upload-Source -SourceId $j.SourceId -FilePath $j.FilePath | Out-Null
  Upsert-Tileset -TilesetId $j.TilesetId -LayerName $j.LayerName -SourceId $j.SourceId
  $publish = Publish-Tileset -TilesetId $j.TilesetId
  Write-Host ("Publish job response: " + ($publish | ConvertTo-Json -Depth 5 -Compress))
}

Write-Host "Done."
