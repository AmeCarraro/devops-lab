# Rust and the Linux libraries Tauri compiles against: enough to check and test
# the native code without installing anything on the PC (see cargo.ps1).
# The Windows app itself is built by the "desktop" workflow on GitHub.
FROM rust:1-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
        libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev \
        libayatana-appindicator3-dev librsvg2-dev \
    && rm -rf /var/lib/apt/lists/* \
    && rustup component add clippy rustfmt
