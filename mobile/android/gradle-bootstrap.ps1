param([Parameter(ValueFromRemainingArguments=$true)][string[]]$GradleArgs)
$ErrorActionPreference = 'Stop'
$version = '9.3.1'
$root = if ($env:GRADLE_USER_HOME) { $env:GRADLE_USER_HOME } else { Join-Path $HOME '.gradle' }
$cache = Join-Path $root 'subway-bootstrap'
$gradle = Join-Path $cache "gradle-$version\bin\gradle.bat"
if (-not (Test-Path $gradle)) {
    New-Item -ItemType Directory -Force $cache | Out-Null
    $temp = Join-Path $cache ([Guid]::NewGuid().ToString())
    New-Item -ItemType Directory $temp | Out-Null
    try {
        $zip = Join-Path $temp 'gradle.zip'
        Invoke-WebRequest -UseBasicParsing "https://services.gradle.org/distributions/gradle-$version-bin.zip" -OutFile $zip
        $checksum = (Invoke-WebRequest -UseBasicParsing "https://services.gradle.org/distributions/gradle-$version-bin.zip.sha256").Content.Trim().ToLowerInvariant()
        if ((Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $checksum) { throw 'Gradle checksum mismatch' }
        Expand-Archive $zip $temp
        Move-Item (Join-Path $temp "gradle-$version") $cache
    } finally { Remove-Item -Recurse -Force $temp }
}
& $gradle @GradleArgs
exit $LASTEXITCODE
