#!/bin/sh
set -eu

wait_for_http() {
  url="$1"
  label="$2"
  attempts="${3:-10}"
  delay_seconds="${4:-1}"
  count=1
  while [ "$count" -le "$attempts" ]; do
    if curl -fsS -m 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay_seconds"
    count=$((count + 1))
  done
  echo "WARNING: ${label} is not reachable at ${url}" >&2
  return 1
}

if [ "${RPA_CDP_PROXY:-1}" = "1" ]; then
  proxy_port="${RPA_CDP_PROXY_PORT:-9222}"
  proxy_target="${RPA_CDP_PROXY_TARGET:-host.docker.internal:9222}"
  if ! wait_for_http "http://${proxy_target}/json/version" "host Chrome CDP" 3 1; then
    cat >&2 <<'EOF'
WARNING: Docker cannot reach the host Chrome DevTools endpoint.
Start Chrome on the host with remote debugging bound to every interface, for example from PowerShell:
powershell.exe -NoProfile -Command "Start-Process chrome.exe '--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0 --remote-allow-origins=* --user-data-dir=$env:LOCALAPPDATA\Google\Chrome\User Data'"
EOF
  fi
  socat "TCP-LISTEN:${proxy_port},fork,reuseaddr,bind=127.0.0.1" "TCP:${proxy_target}" &
  wait_for_http "http://127.0.0.1:${proxy_port}/json/version" "local Chrome CDP proxy" 5 1 || true
fi

if [ "${RPA_OLLAMA_PROXY:-1}" = "1" ]; then
  proxy_port="${RPA_OLLAMA_PROXY_PORT:-11434}"
  proxy_target="${RPA_OLLAMA_PROXY_TARGET:-host.docker.internal:11434}"
  socat "TCP-LISTEN:${proxy_port},fork,reuseaddr,bind=127.0.0.1" "TCP:${proxy_target}" &
fi

exec "$@"
