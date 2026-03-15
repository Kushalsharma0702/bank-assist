# Deploy Banking Voice Agent to AWS

## EC2 One-Command Deploy (Backend + Frontend)

Use this when your team deploys both services to one EC2 host with Docker.

### What this flow does

- Loads `backend/.env` locally and syncs it to EC2
- Builds backend and frontend Docker images locally
- Pushes both images to ECR
- Deploys on EC2 via AWS SSM (no SSH key required)
- Restarts services with Docker Compose
- Prints backend/frontend logs after restart

### Prerequisites

- Local machine has: `python3`, `docker`, `aws` CLI
- AWS credentials configured (`aws configure` or profile)
- EC2 instance has:
   - Docker + Docker Compose plugin installed
   - SSM agent online
   - IAM permissions for SSM + ECR pull

### Run

```bash
cd deploy
python3 deploy_ec2.py \
   --instance-id i-xxxxxxxxxxxxxxxxx \
   --region ap-south-1
```

Optional flags:

```bash
# If you use a named AWS profile
python3 deploy_ec2.py --instance-id i-xxx --region ap-south-1 --profile myprofile

# Use a custom image tag
python3 deploy_ec2.py --instance-id i-xxx --region ap-south-1 --tag v2026-03-15

# Override frontend API URL baked at build time
python3 deploy_ec2.py --instance-id i-xxx --region ap-south-1 --frontend-api-url http://YOUR_EC2_IP:8080
```

### Output

The script prints:

- Build and push progress for both images
- SSM command status
- Last backend/frontend container logs after restart
- Final frontend and backend health URLs

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Users (browser)                                                │
└──────────────┬──────────────────────────────┬───────────────────┘
               │ HTTPS                        │ HTTPS
               ▼                              ▼
   ┌───────────────────────┐    ┌──────────────────────────────┐
   │  CloudFront + S3      │    │  AWS App Runner              │
   │  React frontend       │    │  FastAPI backend             │
   │  (static, global CDN) │    │  Docker container            │
   └───────────────────────┘    │  Port 8080                   │
                                │  IAM role → Bedrock          │
                                └──────────┬───────────────────┘
                                           │
               ┌───────────────────────────┼────────────────────┐
               ▼                           ▼                    ▼
   ┌───────────────────┐  ┌──────────────────────┐  ┌──────────────────┐
   │  AWS Bedrock       │  │  Azure Speech        │  │  Azure Translator│
   │  Claude Sonnet 3.5 │  │  STT + TTS           │  │  (optional)      │
   └───────────────────┘  └──────────────────────┘  └──────────────────┘
```

## What you need

| Tool | Install |
|------|---------|
| AWS CLI v2 | `brew install awscli` or [aws.amazon.com/cli](https://aws.amazon.com/cli/) |
| Docker Desktop | [docker.com](https://www.docker.com/products/docker-desktop/) |
| Node.js 18+ | `brew install node` |
| AWS account with Bedrock Claude 3.5 Sonnet enabled | [Bedrock model access](https://console.aws.amazon.com/bedrock/home#/modelaccess) |

## Pre-flight checks

```bash
# Verify AWS credentials
aws sts get-caller-identity

# Verify Bedrock model access (must return 200)
aws bedrock get-foundation-model \
    --model-identifier anthropic.claude-3-5-sonnet-20240620-v1:0 \
    --region ap-southeast-1

# Verify Docker is running
docker info
```

---

## Step 0 — Fill in your secrets

Edit `vsco/backend/.env`:

```env
# Azure Speech (STT + TTS) — required
AZURE_SPEECH_KEY=your_azure_speech_key_here
AZURE_SPEECH_REGION=southeastasia

# Azure Translator — optional (Claude is used as fallback)
AZURE_TRANSLATOR_KEY=your_azure_translator_key_here
AZURE_TRANSLATOR_REGION=southeastasia

# AWS — leave blank when running on App Runner (uses IAM role)
# Fill only for local development
AWS_REGION=ap-southeast-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

# Claude model
CLAUDE_MODEL_ID=anthropic.claude-3-5-sonnet-20240620-v1:0
```

---

## Step 1 — Push Docker image to ECR

```bash
cd vsco/deploy
chmod +x *.sh

export AWS_REGION=ap-southeast-1
./1_ecr_push.sh
```

**What it does:**
- Creates an ECR repository `banking-voice-agent-backend`
- Builds the Docker image (`--platform linux/amd64`)
- The sentence-transformers model is baked into the image (~80 MB)
- Pushes to ECR

**Expected output:**
```
✅ Image pushed successfully:
   123456789.dkr.ecr.ap-southeast-1.amazonaws.com/banking-voice-agent-backend:latest
```

**Build time:** ~8–12 minutes first time (model download), ~2 minutes after.

---

## Step 2 — Deploy backend to App Runner

```bash
./2_apprunner.sh
```

**What it does:**
- Creates an IAM role `AppRunnerBedrockRole` with Bedrock permission
- Creates an IAM role `AppRunnerECRAccessRole` for pulling ECR images
- Creates the App Runner service with:
  - 2 vCPU / 4 GB RAM (sufficient for sentence-transformers)
  - Azure API keys passed as environment variables
  - IAM role attached — **no AWS keys needed in the container**
  - Health check on `/health`
  - Auto-deploy on new ECR pushes

**Expected output:**
```
✅ App Runner service deploying.
   Backend URL : https://abc123xyz.ap-southeast-1.awsapprunner.com
```

**Time:** ~3–5 minutes to build and start.

Monitor deployment:
```bash
aws apprunner list-services --region ap-southeast-1
```

Test backend:
```bash
curl https://abc123xyz.ap-southeast-1.awsapprunner.com/health
# → {"status":"healthy","service":"Banking Voice Agent"}
```

---

## Step 3 — Deploy frontend to S3 + CloudFront

```bash
./3_frontend_s3.sh https://abc123xyz.ap-southeast-1.awsapprunner.com
```

**What it does:**
- Runs `npm run build` with `VITE_API_URL` set to your App Runner URL
- Creates an S3 bucket with public access blocked
- Uploads the `dist/` folder with correct cache headers
- Creates a CloudFront distribution with HTTPS
- Configures CloudFront Origin Access Control (OAC) for secure S3 access
- Sets up SPA routing (403 → index.html)

**Expected output:**
```
✅ Frontend deployed!
   CloudFront URL : https://d1abc123.cloudfront.net
   Backend URL    : https://abc123xyz.ap-southeast-1.awsapprunner.com
```

**Time:** ~5–10 minutes for CloudFront to propagate globally.

---

## Update deployments

### Re-deploy backend after code changes

```bash
cd vsco/deploy
./1_ecr_push.sh          # builds + pushes new image
# App Runner auto-deploys (AutoDeploymentsEnabled: true)
```

### Re-deploy frontend after UI changes

```bash
./3_frontend_s3.sh https://your-app-runner-url.amazonaws.com

# Invalidate CloudFront cache
aws cloudfront create-invalidation \
    --distribution-id YOUR_CF_ID \
    --paths "/*"
```

---

## Cost estimate (ap-southeast-1, light usage)

| Service | Estimate |
|---------|----------|
| App Runner (2vCPU/4GB) | ~$65/month running 24/7 |
| App Runner (pause when idle) | ~$5–15/month |
| ECR storage (~600MB image) | ~$0.06/month |
| S3 frontend | ~$0.01/month |
| CloudFront | ~$1–5/month (traffic dependent) |
| Bedrock Claude 3.5 | ~$3 per 1M tokens |
| **Total** | **~$10–80/month** |

> App Runner pauses automatically when no requests arrive for a while.
> You can configure minimum instances to 0 to reduce idle cost.

---

## IAM permissions you need to run the deploy scripts

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": ["ecr:*"],           "Resource": "*"},
    {"Effect": "Allow", "Action": ["apprunner:*"],     "Resource": "*"},
    {"Effect": "Allow", "Action": ["iam:*"],           "Resource": "*"},
    {"Effect": "Allow", "Action": ["s3:*"],            "Resource": "*"},
    {"Effect": "Allow", "Action": ["cloudfront:*"],    "Resource": "*"},
    {"Effect": "Allow", "Action": ["sts:GetCallerIdentity"], "Resource": "*"}
  ]
}
```

---

## Troubleshooting

### App Runner fails to start

Check the App Runner logs:
```bash
aws apprunner list-services --region ap-southeast-1
# Copy the ServiceArn, then:
aws apprunner describe-service --service-arn arn:aws:apprunner:... --region ap-southeast-1
```

Or view in the AWS Console → App Runner → banking-voice-agent → Logs.

### Bedrock access denied

```
An error occurred (AccessDeniedException): You don't have access to the model...
```

1. Open [Bedrock Model Access](https://console.aws.amazon.com/bedrock/home#/modelaccess)
2. Enable `Claude 3.5 Sonnet` for your region
3. Wait 2–3 minutes and retry

### CORS errors in browser

Check that `VITE_API_URL` in the frontend build matches your App Runner URL exactly (no trailing slash).

The backend already has `CORSMiddleware` with `allow_origins=["*"]`.

### Audio not playing

The TTS WAV is returned as `tts_audio_base64` in the JSON response — no separate download request. Check the browser console for `TTS autoplay blocked`. If blocked, the UI shows a **▶ Replay** button.

---

## Local Docker test (before deploying)

```bash
cd vsco/backend

# Build image
docker build -t banking-voice-agent-backend .

# Run with your .env
docker run --rm -p 8080:8080 \
    --env-file .env \
    banking-voice-agent-backend

# Test
curl http://localhost:8080/health
```
