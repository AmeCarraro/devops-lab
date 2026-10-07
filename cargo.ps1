# cargo inside a container, in web/src-tauri: Rust is not installed on the PC.
# Usage: .\cargo.ps1 test      .\cargo.ps1 clippy
# It checks and tests the native code of the desktop app on Linux.
# The Windows app itself is built by the "desktop" workflow on GitHub.
$image = 'devops-lab-rust'
$tauri = Join-Path $PSScriptRoot 'web\src-tauri'

docker image inspect $image 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    docker build -t $image -f (Join-Path $tauri 'dev.Dockerfile') $tauri
    if ($LASTEXITCODE -ne 0) { exit 1 }
}

# Tauri embeds the built page at compile time, so the folder has to exist even for a test run
$dist = Join-Path $PSScriptRoot 'web\dist'
if (-not (Test-Path $dist)) { New-Item -ItemType Directory $dist | Out-Null }

$tty = if ([Console]::IsInputRedirected) { '-i' } else { '-it' }
# compiled files and downloaded crates live in Docker volumes: faster than the Windows filesystem
docker run --rm $tty `
    -v "$PSScriptRoot\web:/app" `
    -v devops-lab-cargo-target:/app/src-tauri/target `
    -v devops-lab-cargo-registry:/usr/local/cargo/registry `
    -w /app/src-tauri $image cargo @args
