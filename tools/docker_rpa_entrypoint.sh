#!/bin/sh
set -eu

if [ "${RPA_CDP_PROXY:-1}" = "1" ]; then
  proxy_port="${RPA_CDP_PROXY_PORT:-9222}"
  proxy_target="${RPA_CDP_PROXY_TARGET:-host.docker.internal:9222}"
  socat "TCP-LISTEN:${proxy_port},fork,reuseaddr,bind=127.0.0.1" "TCP:${proxy_target}" &
fi

if [ "${RPA_OLLAMA_PROXY:-1}" = "1" ]; then
  proxy_port="${RPA_OLLAMA_PROXY_PORT:-11434}"
  proxy_target="${RPA_OLLAMA_PROXY_TARGET:-host.docker.internal:11434}"
  socat "TCP-LISTEN:${proxy_port},fork,reuseaddr,bind=127.0.0.1" "TCP:${proxy_target}" &
fi

exec "$@"
