#!/usr/bin/env bash
# Starts three independent business agents (ports 8101-8103) and the planner (port 8000).
set -e
cd "$(dirname "$0")"
pip install -q -r requirements.txt
trap 'kill 0' EXIT
for pair in ada-photo:8101 lagos-cakes:8102 enugu-makeup:8103; do
  python -m bazaar.business "${pair%%:*}" "${pair##*:}" &
done
sleep 2
AGENT_URLS=http://localhost:8101/agents/ada-photo,http://localhost:8102/agents/lagos-cakes,http://localhost:8103/agents/enugu-makeup \
  uvicorn bazaar.app:app --port 8000
