#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  deploy_all.sh — Full deploy: backend (Git pull on EC2) + frontend (S3 + CloudFront)
#
#  Usage:
#    ./deploy_all.sh [--backend-only | --frontend-only]
#
#  Prerequisites:
#    export AWS_REGION=ap-south-1     # override if needed
#    AWS CLI configured with credentials that have ECR/S3/CF/SSM access
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Hardcoded resource IDs from existing deployment ──────────────────────────
export AWS_REGION="${AWS_REGION:-ap-south-1}"

# EC2
EC2_INSTANCE_ID="i-083a2c776ad95735c"

# Backend CloudFront domain (the frontend sends WebSocket here)
BACKEND_CLOUDFRONT_URL="https://d14zu358us4jz7.cloudfront.net"

# Frontend CloudFront (look up distribution ID dynamically)
FRONTEND_CF_DOMAIN="d2zbxz7jbltqzy.cloudfront.net"

# S3 bucket (account ID embedded; look up rather than hardcode)
AWS_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
S3_BUCKET="banking-voice-agent-frontend-${AWS_ACCOUNT_ID}"

# ── Parse args ────────────────────────────────────────────────────────────────
DEPLOY_BACKEND=true
DEPLOY_FRONTEND=true

for arg in "$@"; do
    case "$arg" in
        --backend-only)  DEPLOY_FRONTEND=false ;;
        --frontend-only) DEPLOY_BACKEND=false  ;;
        *) echo "Unknown arg: $arg"; exit 1 ;;
    esac
done

echo "============================================================"
echo " Banking Voice Agent — Full Redeploy"
echo "  Region         : ${AWS_REGION}"
echo "  EC2 Instance   : ${EC2_INSTANCE_ID}"
echo "  Backend URL    : ${BACKEND_CLOUDFRONT_URL}"
echo "  Frontend S3    : ${S3_BUCKET}"
echo "  Deploy backend : ${DEPLOY_BACKEND}"
echo "  Deploy frontend: ${DEPLOY_FRONTEND}"
echo "============================================================"

# ── STEP 1 — Backend (Git pull + restart on EC2) ────────────────────────────
if [[ "${DEPLOY_BACKEND}" == "true" ]]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo " BACKEND: Git pull on EC2 → Rebuild → Restart"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    echo ""
    echo "▶ Step 1: Pulling latest git code on EC2 and restarting services…"
    chmod +x "${SCRIPT_DIR}/2_ec2_restart.sh"
    "${SCRIPT_DIR}/2_ec2_restart.sh" "${EC2_INSTANCE_ID}"
fi

# ── STEP 3 — Frontend ─────────────────────────────────────────────────────────
if [[ "${DEPLOY_FRONTEND}" == "true" ]]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo " FRONTEND: Build → S3 → CloudFront invalidation"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    FRONTEND_DIR="${SCRIPT_DIR}/../frontend"

    echo ""
    echo "▶ Step 3a: Building React app…"
    cd "${FRONTEND_DIR}"
    VITE_API_URL="${BACKEND_CLOUDFRONT_URL}" npm run build
    echo "   Build complete → dist/"

    echo ""
    echo "▶ Step 3b: Syncing to S3 (${S3_BUCKET})…"
    # All hashed assets: long-lived cache
    aws s3 sync dist/ "s3://${S3_BUCKET}" \
        --delete \
        --region "${AWS_REGION}" \
        --cache-control "public,max-age=31536000,immutable" \
        --exclude "index.html"

    # index.html: never cached (SPA routing)
    aws s3 cp dist/index.html "s3://${S3_BUCKET}/index.html" \
        --region "${AWS_REGION}" \
        --cache-control "no-cache,no-store,must-revalidate"
    echo "   ✅ S3 sync complete"

    echo ""
    echo "▶ Step 3c: Invalidating CloudFront cache…"
    # Resolve distribution ID from domain name
    CF_DIST_ID=$(aws cloudfront list-distributions \
        --query "DistributionList.Items[?DomainName=='${FRONTEND_CF_DOMAIN}'].Id" \
        --output text 2>/dev/null | tr -d '[:space:]')

    if [[ -z "${CF_DIST_ID}" ]]; then
        echo "   ⚠️  Could not find CloudFront distribution for ${FRONTEND_CF_DOMAIN}"
        echo "   Listing all distributions:"
        aws cloudfront list-distributions \
            --query "DistributionList.Items[].{Id:Id,Domain:DomainName,Comment:Comment}" \
            --output table
        echo "   Set CF_DIST_ID manually and run:"
        echo "     aws cloudfront create-invalidation --distribution-id <ID> --paths '/*'"
    else
        INVAL_ID=$(aws cloudfront create-invalidation \
            --distribution-id "${CF_DIST_ID}" \
            --paths "/*" \
            --query "Invalidation.Id" \
            --output text)
        echo "   ✅ Invalidation created: ${INVAL_ID}"
        echo "   Distribution : ${CF_DIST_ID}"
        echo "   (propagates globally in ~1–3 min)"
    fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo " ✅ Deploy complete!"
if [[ "${DEPLOY_BACKEND}" == "true" ]]; then
echo "  Backend  : ${BACKEND_CLOUDFRONT_URL}/health"
fi
if [[ "${DEPLOY_FRONTEND}" == "true" ]]; then
echo "  Frontend : https://${FRONTEND_CF_DOMAIN}"
fi
echo "============================================================"
