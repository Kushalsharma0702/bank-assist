#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Step 1 — Build Docker image and push to Amazon ECR
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Config (edit these) ───────────────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-ap-south-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
ECR_REPO_NAME="banking-voice-agent-backend"
IMAGE_TAG="${1:-latest}"

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO_NAME}"

echo "============================================================"
echo " Building and pushing to ECR"
echo "  Region     : ${AWS_REGION}"
echo "  Account    : ${AWS_ACCOUNT_ID}"
echo "  Repository : ${ECR_REPO_NAME}"
echo "  Tag        : ${IMAGE_TAG}"
echo "============================================================"

# ── 1. Create ECR repo (idempotent) ──────────────────────────────────────────
echo ""
echo "▶ Creating ECR repository (if not exists)…"
aws ecr describe-repositories \
    --repository-names "${ECR_REPO_NAME}" \
    --region "${AWS_REGION}" > /dev/null 2>&1 \
|| aws ecr create-repository \
    --repository-name "${ECR_REPO_NAME}" \
    --region "${AWS_REGION}" \
    --image-scanning-configuration scanOnPush=true \
    --encryption-configuration encryptionType=AES256

# ── 2. Docker login to ECR ────────────────────────────────────────────────────
echo ""
echo "▶ Logging in to ECR…"
aws ecr get-login-password --region "${AWS_REGION}" \
    | docker login --username AWS --password-stdin "${ECR_URI}"

# ── 3. Build image ────────────────────────────────────────────────────────────
echo ""
echo "▶ Building Docker image…"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${SCRIPT_DIR}/../backend"

docker build \
    --platform linux/amd64 \
    -t "${ECR_REPO_NAME}:${IMAGE_TAG}" \
    "${BACKEND_DIR}"

# ── 4. Tag and push ───────────────────────────────────────────────────────────
echo ""
echo "▶ Pushing image to ECR…"
docker tag "${ECR_REPO_NAME}:${IMAGE_TAG}" "${ECR_URI}:${IMAGE_TAG}"
docker push "${ECR_URI}:${IMAGE_TAG}"

echo ""
echo "✅ Image pushed successfully:"
echo "   ${ECR_URI}:${IMAGE_TAG}"
echo ""
echo "Next step: run  ./2_apprunner.sh"
