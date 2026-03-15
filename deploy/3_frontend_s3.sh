#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
#  Step 3 — Build React frontend and deploy to S3 + CloudFront
#
#  Usage:
#    ./3_frontend_s3.sh https://abc123.ap-southeast-1.awsapprunner.com
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

BACKEND_URL="${1:-}"
if [[ -z "${BACKEND_URL}" ]]; then
    echo "❌ Usage: $0 <backend-url>"
    echo "   Example: $0 https://abc123.ap-southeast-1.awsapprunner.com"
    exit 1
fi

# ── Config (edit these) ───────────────────────────────────────────────────────
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"
BUCKET_NAME="banking-voice-agent-frontend-${AWS_ACCOUNT_ID}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="${SCRIPT_DIR}/../frontend"

echo "============================================================"
echo " Deploying frontend to S3 + CloudFront"
echo "  Backend URL : ${BACKEND_URL}"
echo "  S3 Bucket   : ${BUCKET_NAME}"
echo "  Region      : ${AWS_REGION}"
echo "============================================================"

# ── 1. Build React app ────────────────────────────────────────────────────────
echo ""
echo "▶ Building React app…"
cd "${FRONTEND_DIR}"
VITE_API_URL="${BACKEND_URL}" npm run build
echo "   Build complete: ${FRONTEND_DIR}/dist"

# ── 2. Create S3 bucket ───────────────────────────────────────────────────────
echo ""
echo "▶ Creating S3 bucket…"
if aws s3api head-bucket --bucket "${BUCKET_NAME}" 2>/dev/null; then
    echo "   Bucket already exists."
else
    if [[ "${AWS_REGION}" == "us-east-1" ]]; then
        aws s3api create-bucket \
            --bucket "${BUCKET_NAME}" \
            --region "${AWS_REGION}"
    else
        aws s3api create-bucket \
            --bucket "${BUCKET_NAME}" \
            --region "${AWS_REGION}" \
            --create-bucket-configuration LocationConstraint="${AWS_REGION}"
    fi
    # Block all public access (CloudFront will serve via OAC)
    aws s3api put-public-access-block \
        --bucket "${BUCKET_NAME}" \
        --public-access-block-configuration \
            "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
fi

# ── 3. Upload dist/ to S3 ─────────────────────────────────────────────────────
echo ""
echo "▶ Uploading files to S3…"
aws s3 sync "${FRONTEND_DIR}/dist" "s3://${BUCKET_NAME}" \
    --delete \
    --cache-control "public,max-age=31536000,immutable" \
    --exclude "index.html"

# index.html must not be cached (SPA routing)
aws s3 cp "${FRONTEND_DIR}/dist/index.html" "s3://${BUCKET_NAME}/index.html" \
    --cache-control "no-cache,no-store,must-revalidate"

# ── 4. Create CloudFront distribution ────────────────────────────────────────
echo ""
echo "▶ Checking CloudFront distribution…"

EXISTING_CF=$(aws cloudfront list-distributions \
    --query "DistributionList.Items[?Comment=='banking-voice-agent-frontend'].Id" \
    --output text 2>/dev/null || true)

if [[ -n "${EXISTING_CF}" ]]; then
    echo "   CloudFront distribution already exists: ${EXISTING_CF}"
    CF_DOMAIN=$(aws cloudfront get-distribution \
        --id "${EXISTING_CF}" \
        --query "Distribution.DomainName" --output text)
else
    echo "   Creating CloudFront distribution…"

    # Origin Access Control
    OAC_ID=$(aws cloudfront create-origin-access-control \
        --origin-access-control-config "{
          \"Name\": \"banking-voice-agent-oac\",
          \"OriginAccessControlOriginType\": \"s3\",
          \"SigningBehavior\": \"always\",
          \"SigningProtocol\": \"sigv4\"
        }" \
        --query "OriginAccessControl.Id" --output text 2>/dev/null || \
        aws cloudfront list-origin-access-controls \
            --query "OriginAccessControlList.Items[?Name=='banking-voice-agent-oac'].Id" \
            --output text)

    CF_RESULT=$(aws cloudfront create-distribution --distribution-config "{
      \"Comment\": \"banking-voice-agent-frontend\",
      \"Enabled\": true,
      \"DefaultRootObject\": \"index.html\",
      \"Origins\": {
        \"Quantity\": 1,
        \"Items\": [{
          \"Id\": \"s3-origin\",
          \"DomainName\": \"${BUCKET_NAME}.s3.${AWS_REGION}.amazonaws.com\",
          \"OriginAccessControlId\": \"${OAC_ID}\",
          \"S3OriginConfig\": {\"OriginAccessIdentity\": \"\"}
        }]
      },
      \"DefaultCacheBehavior\": {
        \"ViewerProtocolPolicy\": \"redirect-to-https\",
        \"TargetOriginId\": \"s3-origin\",
        \"CachePolicyId\": \"658327ea-f89d-4fab-a63d-7e88639e58f6\",
        \"Compress\": true,
        \"AllowedMethods\": {\"Quantity\": 2, \"Items\": [\"GET\",\"HEAD\"]},
        \"CachedMethods\":  {\"Quantity\": 2, \"Items\": [\"GET\",\"HEAD\"]}
      },
      \"CustomErrorResponses\": {
        \"Quantity\": 1,
        \"Items\": [{
          \"ErrorCode\": 403,
          \"ResponseCode\": \"200\",
          \"ResponsePagePath\": \"/index.html\"
        }]
      },
      \"CallerReference\": \"banking-voice-agent-$(date +%s)\",
      \"PriceClass\": \"PriceClass_All\"
    }")

    EXISTING_CF=$(echo "${CF_RESULT}" | python3 -c "import sys,json; print(json.load(sys.stdin)['Distribution']['Id'])")
    CF_DOMAIN=$(echo "${CF_RESULT}"   | python3 -c "import sys,json; print(json.load(sys.stdin)['Distribution']['DomainName'])")

    # Attach S3 bucket policy for CloudFront OAC
    ACCOUNT_ID="${AWS_ACCOUNT_ID}"
    aws s3api put-bucket-policy --bucket "${BUCKET_NAME}" --policy "{
      \"Version\": \"2012-10-17\",
      \"Statement\": [{
        \"Sid\": \"AllowCloudFront\",
        \"Effect\": \"Allow\",
        \"Principal\": {\"Service\": \"cloudfront.amazonaws.com\"},
        \"Action\": \"s3:GetObject\",
        \"Resource\": \"arn:aws:s3:::${BUCKET_NAME}/*\",
        \"Condition\": {
          \"StringEquals\": {\"AWS:SourceArn\": \"arn:aws:cloudfront::${ACCOUNT_ID}:distribution/${EXISTING_CF}\"}
        }
      }]
    }"
fi

echo ""
echo "✅ Frontend deployed!"
echo ""
echo "   S3 Bucket      : s3://${BUCKET_NAME}"
echo "   CloudFront URL : https://${CF_DOMAIN}"
echo "   Backend URL    : ${BACKEND_URL}"
echo ""
echo "⏳ CloudFront takes ~5–10 min to propagate globally."
echo ""
echo "   To invalidate cache after re-deploying:"
echo "   aws cloudfront create-invalidation --distribution-id ${EXISTING_CF} --paths '/*'"
