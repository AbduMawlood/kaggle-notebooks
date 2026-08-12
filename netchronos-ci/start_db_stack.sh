#!/usr/bin/env bash
set -euo pipefail

services=("$@")
if [ ${#services[@]} -eq 0 ]; then
  services=(timescaledb postgres)
fi

docker compose pull "${services[@]}"
docker compose up -d "${services[@]}"

for service in "${services[@]}"; do
  ready=0
  for attempt in $(seq 1 60); do
    cid="$(docker compose ps -q "$service")"
    if [ -z "$cid" ]; then
      echo "${service}: container id unavailable" >&2
      sleep 2
      continue
    fi
    state="$(docker inspect --format '{{.State.Status}}' "$cid" 2>/dev/null || true)"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || true)"
    if [ "$health" = "healthy" ]; then
      echo "${service}: healthy"
      ready=1
      break
    fi
    if [ "$state" = "exited" ] || [ "$state" = "dead" ]; then
      echo "${service}: terminated before readiness (state=${state}, health=${health})" >&2
      docker compose logs --no-color "$service" >&2 || true
      exit 1
    fi
    echo "${service}: waiting for readiness (state=${state}, health=${health}, attempt=${attempt}/60)"
    sleep 2
  done
  if [ "$ready" -ne 1 ]; then
    echo "${service}: did not become healthy within 120 s" >&2
    docker compose ps >&2 || true
    docker compose logs --no-color "$service" >&2 || true
    exit 1
  fi
done

docker compose ps
