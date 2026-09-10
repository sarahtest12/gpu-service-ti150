#!/usr/bin/env bash
set -euo pipefail
GATEWAY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_BUILD="$GATEWAY_ROOT/runtime/build"
GATEWAY_PREFIX="$GATEWAY_ROOT/runtime/nginx"
NGINX_VERSION=1.30.4
NGINX_SHA256=4261dc90e9e47c1c4041276e9aaa3d48ebe2e664f728e14fa95ae6c67d57a08b
umask 077
mkdir -p "$GATEWAY_BUILD"
if [[ -x "$GATEWAY_PREFIX/sbin/nginx" ]]; then
  "$GATEWAY_PREFIX/sbin/nginx" -v
  exit 0
fi
for dependency in gcc make curl pkg-config; do
  command -v "$dependency" >/dev/null || { printf 'Missing build tool: %s\n' "$dependency" >&2; exit 1; }
done
pkg-config --exists openssl libpcre2-8 zlib || {
  printf '%s\n' 'Install build-essential libssl-dev libpcre2-dev zlib1g-dev before building NGINX.' >&2
  exit 1
}
curl --fail --location --proto '=https' --tlsv1.2 --retry 2 \
  "https://nginx.org/download/nginx-$NGINX_VERSION.tar.gz" -o "$GATEWAY_BUILD/nginx.tar.gz"
printf '%s  %s\n' "$NGINX_SHA256" "$GATEWAY_BUILD/nginx.tar.gz" | sha256sum --check
tar -xzf "$GATEWAY_BUILD/nginx.tar.gz" -C "$GATEWAY_BUILD"
cd "$GATEWAY_BUILD/nginx-$NGINX_VERSION"
./configure --prefix="$GATEWAY_PREFIX" --with-http_ssl_module --with-http_v2_module \
  --without-http_gzip_module > "$GATEWAY_BUILD/configure.log" 2>&1
make -j2 > "$GATEWAY_BUILD/make.log" 2>&1
make install > "$GATEWAY_BUILD/install.log" 2>&1
"$GATEWAY_PREFIX/sbin/nginx" -v
printf '%s\n' 'Next: python3 gateway/service.py init --name localhost'
