#!/usr/bin/env bash

# ─────────────────────────────────────────────────────────────────────────────

# Step 2 — Pull latest code on EC2 and restart services

# Uses AWS SSM Run Command — no SSH key required.

# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

AWS_REGION="${AWS_REGION:-ap-south-1}"
INSTANCE_ID="${1:-i-083a2c776ad95735c}"
GIT_REPO_URL="${GIT_REPO_URL:-https://github.com/Kushalsharma0702/bank-assist.git}"

# Remove optional wrapping quotes in .env values (KEY="value" -> KEY=value).
sed -i -E 's/^([A-Za-z_][A-Za-z0-9_]*)="(.*)"$/\1=\2/' "$APP_DIR/.env"
sed -i -E "s/^([A-Za-z_][A-Za-z0-9_]*)='(.*)'$/\1=\2/" "$APP_DIR/.env"
GIT_BRANCH="${GIT_BRANCH:-main}"
APP_DIR="${APP_DIR:-/opt/banking-voice-agent}"
BACKEND_PUBLIC_URL="${BACKEND_PUBLIC_URL:-https://d14zu358us4jz7.cloudfront.net}"
LOCAL_ENV_FILE="${LOCAL_ENV_FILE:-${SCRIPT_DIR}/../backend/.env}"
LOCAL_ENV_B64=""

if [[ -f "${LOCAL_ENV_FILE}" ]]; then
<<<<<<< HEAD
LOCAL_ENV_B64="$(base64 -w 0 "${LOCAL_ENV_FILE}" 2>/dev/null || base64 "${LOCAL_ENV_FILE}" | tr -d '\n')"
=======
  LOCAL_ENV_B64="$(base64 -w 0 "${LOCAL_ENV_FILE}" 2>/dev/null || base64 "${LOCAL_ENV_FILE}" | tr -d '\n')"
>>>>>>> 1d4a2ae (preserve and bootstrap EC2 env file during git deploy)
fi

echo "============================================================"
echo " EC2 Git Deploy via SSM"
echo "  Region        : ${AWS_REGION}"
echo "  Instance      : ${INSTANCE_ID}"
echo "  Repo          : ${GIT_REPO_URL}"
echo "  Branch        : ${GIT_BRANCH}"
echo "  App Directory : ${APP_DIR}"
echo "============================================================"

echo ""
echo "▶ Checking SSM connectivity…"
SSM_STATUS=$(aws ssm describe-instance-information 
--filters "Key=InstanceIds,Values=${INSTANCE_ID}" 
--region "${AWS_REGION}" 
--query "InstanceInformationList[0].PingStatus" 
--output text 2>/dev/null || echo "Unknown")

if [[ "${SSM_STATUS}" != "Online" ]]; then
echo "⚠️  SSM agent status: ${SSM_STATUS}"
echo "   Add AmazonSSMManagedInstanceCore to EC2 role and retry."
exit 1
fi
echo "   ✅ SSM Online"

SSM_PARAMS_FILE="$(mktemp /tmp/ssm_params_XXXXXX.json)"
trap 'rm -f "${SSM_PARAMS_FILE}"' EXIT

python3 - "${GIT_REPO_URL}" "${GIT_BRANCH}" "${APP_DIR}" "${BACKEND_PUBLIC_URL}" "${LOCAL_ENV_B64}" "${SSM_PARAMS_FILE}" << 'PYEOF'
<<<<<<< HEAD
import json, sys
=======
import json
import sys
>>>>>>> 1d4a2ae (preserve and bootstrap EC2 env file during git deploy)

repo_url, branch, app_dir, backend_public_url, local_env_b64, out_file = sys.argv[1:]

script = r"""#!/bin/bash
set -euo pipefail

<<<<<<< HEAD
REPO_URL=**REPO_URL**
BRANCH=**BRANCH**
APP_DIR=**APP_DIR**
BACKEND_PUBLIC_URL=**BACKEND_PUBLIC_URL**
LOCAL_ENV_B64=**LOCAL_ENV_B64**

echo "[INFO] Starting deployment..."
=======
REPO_URL=__REPO_URL__
BRANCH=__BRANCH__
APP_DIR=__APP_DIR__
BACKEND_PUBLIC_URL=__BACKEND_PUBLIC_URL__
LOCAL_ENV_B64=__LOCAL_ENV_B64__
>>>>>>> 1d4a2ae (preserve and bootstrap EC2 env file during git deploy)

if ! command -v docker >/dev/null 2>&1; then
echo "Docker is not installed on EC2."
exit 1
fi

COMPOSE_CMD=""
if docker compose version >/dev/null 2>&1; then
COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then

COMPOSE_CMD="docker-compose"
else
echo "Docker Compose not found."
exit 1

  COMPOSE_CMD="docker-compose"

fi

mkdir -p "$APP_DIR"

<<<<<<< HEAD
# Clone or update repo
=======
if [ ! -d "$APP_DIR/.git" ]; then
  if [ -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env" /tmp/banking-voice-agent.env.bak
  fi

  rm -rf "$APP_DIR"
  mkdir -p "$(dirname \"$APP_DIR\")"
>>>>>>> 1d4a2ae (preserve and bootstrap EC2 env file during git deploy)

if [ ! -d "$APP_DIR/.git" ]; then
echo "[INFO] Cloning repo..."
rm -rf "$APP_DIR"
mkdir -p "$(dirname "$APP_DIR")"

if ! git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"; then
if echo "$REPO_URL" | grep -q '^[git@github.com](mailto:git@github.com):'; then
HTTPS_URL="https://github.com/${REPO_URL#git@github.com:}"
git clone --branch "$BRANCH" "$HTTPS_URL" "$APP_DIR"
else
exit 1
fi
fi
else
echo "[INFO] Updating repo..."
cd "$APP_DIR"
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"
fi

cd "$APP_DIR"

# Setup .env

if [ ! -f "$APP_DIR/.env" ] && [ -n "$LOCAL_ENV_B64" ]; then
echo "$LOCAL_ENV_B64" | base64 -d > "$APP_DIR/.env"
if [ ! -f "$APP_DIR/.env" ] && [ -f /tmp/banking-voice-agent.env.bak ]; then
  cp /tmp/banking-voice-agent.env.bak "$APP_DIR/.env"
fi

if [ ! -f "$APP_DIR/.env" ] && [ -n "$LOCAL_ENV_B64" ]; then
  echo "$LOCAL_ENV_B64" | base64 -d > "$APP_DIR/.env"
fi

git remote set-url origin "$REPO_URL" || true
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

if [ ! -f "$APP_DIR/.env" ]; then
  echo "ERROR: $APP_DIR/.env is missing."
  exit 1
fi

# Clean quotes

if [ -f "$APP_DIR/.env" ]; then
sed -i -E 's/^([A-Za-z_][A-Za-z0-9_]*)="(.*)"$/\1=\2/' "$APP_DIR/.env"
sed -i -E "s/^([A-Za-z_][A-Za-z0-9_]*)='(.*)'$/\1=\2/" "$APP_DIR/.env"
fi

# Create docker compose

cat > "$APP_DIR/docker-compose.ec2.yml" <<EOF
services:
backend:
build: ./backend
image: banking-backend:latest
container_name: banking-backend
restart: unless-stopped
env_file:
- .env
ports:
- "8080:8080"

frontend:
build:
context: ./frontend
args:
VITE_API_URL: ${BACKEND_PUBLIC_URL}
image: banking-frontend:latest
container_name: banking-frontend
restart: unless-stopped
depends_on:
- backend
ports:
- "80:80"
EOF


docker image prune -f >/dev/null 2>&1 || true

echo "[INFO] Deploying containers..."
$COMPOSE_CMD -f docker-compose.ec2.yml down || true
$COMPOSE_CMD -f docker-compose.ec2.yml up -d --build --remove-orphans

OLD_IMAGES=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E 'banking-voice-agent-(backend|frontend)|844605843483.dkr.ecr.ap-south-1.amazonaws.com/banking-voice-agent-' || true)
if [ -n "$OLD_IMAGES" ]; then
  echo "Removing old images:"
  echo "$OLD_IMAGES"
  docker rmi -f $OLD_IMAGES >/dev/null 2>&1 || true
fi

docker image prune -f >/dev/null 2>&1 || true

if [ -n "$COMPOSE_CMD" ]; then
  $COMPOSE_CMD -f docker-compose.ec2.yml down || true
  $COMPOSE_CMD -f docker-compose.ec2.yml up -d --build --remove-orphans
else
  echo "Docker Compose not found. Using docker build/run fallback."

  docker rm -f banking-frontend banking-backend >/dev/null 2>&1 || true
  for PORT in 8080 80; do
    CONFLICT_IDS=$(docker ps -q --filter "publish=${PORT}")
    if [ -n "$CONFLICT_IDS" ]; then
      docker rm -f $CONFLICT_IDS >/dev/null 2>&1 || true
    fi
  done

  docker build -t banking-voice-agent-backend:git ./backend
  docker build --build-arg VITE_API_URL="$BACKEND_PUBLIC_URL" \
    -t banking-voice-agent-frontend:git ./frontend

  docker network create banking-net >/dev/null 2>&1 || true

  docker run -d \
    --name banking-backend \
    --restart unless-stopped \
    --network banking-net \
    --network-alias backend \
    --env-file .env \
    -p 8080:8080 \
    banking-voice-agent-backend:git

  docker run -d \
    --name banking-frontend \
    --restart unless-stopped \
    --network banking-net \
    -p 80:80 \
    banking-voice-agent-frontend:git
fi


echo "--- Running containers ---"
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'

echo "--- Revision ---"
git rev-parse --short HEAD
"""

script = (

script.replace("**REPO_URL**", repo_url)
.replace("**BRANCH**", branch)
.replace("**APP_DIR**", app_dir)
.replace("**BACKEND_PUBLIC_URL**", backend_public_url)
.replace("**LOCAL_ENV_B64**", local_env_b64)

    script.replace("__REPO_URL__", repo_url)
    .replace("__BRANCH__", branch)
    .replace("__APP_DIR__", app_dir)
    .replace("__BACKEND_PUBLIC_URL__", backend_public_url)
  .replace("__LOCAL_ENV_B64__", local_env_b64)

)

with open(out_file, "w") as f:
json.dump({"commands": [script]}, f)

print("SSM params written:", out_file)
PYEOF

echo "▶ Sending command via SSM…"

CMD_ID=$(aws ssm send-command 
--region "${AWS_REGION}" 
--instance-ids "${INSTANCE_ID}" 
--document-name "AWS-RunShellScript" 
--parameters "file://${SSM_PARAMS_FILE}" 
--query "Command.CommandId" 
--output text)

echo "Command ID: ${CMD_ID}"

for i in $(seq 1 40); do
sleep 5
STATUS=$(aws ssm get-command-invocation 
--region "${AWS_REGION}" 
--command-id "${CMD_ID}" 
--instance-id "${INSTANCE_ID}" 
--query "Status" --output text 2>/dev/null || echo "Pending")

echo "[${i}/40] ${STATUS}"

if [[ "${STATUS}" == "Success" ]]; then
echo "✅ Deployment successful"
exit 0
elif [[ "${STATUS}" =~ ^(Failed|Cancelled|TimedOut) ]]; then
echo "❌ Deployment failed"
exit 1
fi
done

echo "❌ Timeout"
exit 1
