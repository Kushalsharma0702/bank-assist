#!/usr/bin/env python3
"""
Cross-platform deployment script for backend + frontend on EC2.

What it does:
1) Loads backend/.env
2) Builds backend and frontend Docker images
3) Pushes both images to ECR
4) Sends an SSM command to EC2 that:
   - logs into ECR
   - writes .env and docker-compose.yml
   - pulls latest images
   - restarts services
   - prints recent container logs

Requirements (local):
- Python 3.9+
- Docker
- AWS CLI configured

Requirements (EC2):
- SSM agent online and IAM role with SSM + ECR access
- Docker + Docker Compose plugin installed
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def log(msg: str) -> None:
	print(f"[deploy] {msg}", flush=True)


def run(
	cmd: list[str],
	*,
	check: bool = True,
	capture: bool = False,
	stdin_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
	pretty = " ".join(cmd)
	log(f"$ {pretty}")
	return subprocess.run(
		cmd,
		check=check,
		text=True,
		input=stdin_text,
		capture_output=capture,
	)


def require_command(cmd: str, install_hint: str) -> None:
	from shutil import which

	if which(cmd) is None:
		raise RuntimeError(f"Missing required command '{cmd}'. {install_hint}")


def aws_cmd(profile: str | None, region: str | None, *args: str) -> list[str]:
	cmd = ["aws"]
	if profile:
		cmd += ["--profile", profile]
	if region:
		cmd += ["--region", region]
	cmd += list(args)
	return cmd


def aws_json(profile: str | None, region: str | None, *args: str) -> dict:
	cp = run(aws_cmd(profile, region, *args), capture=True)
	out = cp.stdout.strip()
	if not out:
		return {}
	return json.loads(out)


def get_account_id(profile: str | None) -> str:
	data = aws_json(profile, None, "sts", "get-caller-identity")
	account_id = data.get("Account")
	if not account_id:
		raise RuntimeError("Unable to determine AWS account ID from sts get-caller-identity")
	return account_id


def load_dotenv(env_path: Path) -> dict[str, str]:
	if not env_path.exists():
		raise RuntimeError(f"Env file not found: {env_path}")

	env: dict[str, str] = {}
	for raw in env_path.read_text(encoding="utf-8").splitlines():
		line = raw.strip()
		if not line or line.startswith("#") or "=" not in line:
			continue
		key, value = line.split("=", 1)
		key = key.strip()
		value = value.strip().strip('"').strip("'")
		env[key] = value
	return env


def ensure_ecr_repo(profile: str | None, region: str, repo_name: str) -> None:
	describe = run(
		aws_cmd(
			profile,
			region,
			"ecr",
			"describe-repositories",
			"--repository-names",
			repo_name,
		),
		check=False,
		capture=True,
	)
	if describe.returncode == 0:
		log(f"ECR repository exists: {repo_name}")
		return

	log(f"Creating ECR repository: {repo_name}")
	run(
		aws_cmd(
			profile,
			region,
			"ecr",
			"create-repository",
			"--repository-name",
			repo_name,
			"--image-scanning-configuration",
			"scanOnPush=true",
			"--encryption-configuration",
			"encryptionType=AES256",
		)
	)


def ecr_login(profile: str | None, region: str, registry: str) -> None:
	cp = run(
		aws_cmd(profile, region, "ecr", "get-login-password"),
		capture=True,
	)
	password = cp.stdout
	run(["docker", "login", "--username", "AWS", "--password-stdin", registry], stdin_text=password)


def docker_build_and_push(
	*,
	image_local: str,
	image_remote: str,
	context_dir: Path,
	dockerfile: Path | None,
	build_args: dict[str, str] | None = None,
) -> None:
	cmd = ["docker", "build", "--platform", "linux/amd64", "-t", image_local]
	if dockerfile:
		cmd += ["-f", str(dockerfile)]
	for k, v in (build_args or {}).items():
		cmd += ["--build-arg", f"{k}={v}"]
	cmd += [str(context_dir)]
	run(cmd)

	run(["docker", "tag", image_local, image_remote])
	run(["docker", "push", image_remote])


def get_ec2_endpoint(profile: str | None, region: str, instance_id: str) -> str:
	data = aws_json(
		profile,
		region,
		"ec2",
		"describe-instances",
		"--instance-ids",
		instance_id,
	)
	reservations = data.get("Reservations") or []
	if not reservations or not reservations[0].get("Instances"):
		raise RuntimeError(f"Could not find EC2 instance details for {instance_id}")

	inst = reservations[0]["Instances"][0]
	for key in ("PublicDnsName", "PublicIpAddress", "PrivateIpAddress"):
		val = inst.get(key)
		if val:
			return val
	raise RuntimeError(f"No reachable endpoint found on EC2 instance {instance_id}")


def build_compose_yaml(backend_image: str, frontend_image: str) -> str:
	return f"""services:
  backend:
		image: {backend_image}
		container_name: banking-backend
		restart: unless-stopped
		env_file:
			- .env
		expose:
			- \"8080\"
		ports:
			- \"8080:8080\"

  frontend:
		image: {frontend_image}
		container_name: banking-frontend
		restart: unless-stopped
		depends_on:
			- backend
		ports:
			- \"80:80\"
"""


def send_ssm_deploy(
	*,
	profile: str | None,
	region: str,
	instance_id: str,
	account_id: str,
	env_text: str,
	compose_text: str,
	backend_repo: str,
	frontend_repo: str,
	image_tag: str,
) -> str:
	env_b64 = base64.b64encode(env_text.encode("utf-8")).decode("ascii")
	compose_b64 = base64.b64encode(compose_text.encode("utf-8")).decode("ascii")

	registry = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
	backend_image = f"{registry}/{backend_repo}:{image_tag}"
	frontend_image = f"{registry}/{frontend_repo}:{image_tag}"

	remote_script = f"""#!/bin/bash
set -euo pipefail

APP_DIR=/opt/banking-voice-agent
mkdir -p "$APP_DIR"
cd "$APP_DIR"

echo "[ec2] writing .env"
echo '{env_b64}' | base64 -d > .env

echo "[ec2] writing docker-compose.yml"
echo '{compose_b64}' | base64 -d > docker-compose.yml

echo "[ec2] logging in to ECR"
aws ecr get-login-password --region {region} | docker login --username AWS --password-stdin {registry}

echo "[ec2] pulling images"
docker pull {backend_image}
docker pull {frontend_image}

echo "[ec2] restarting services"
	if docker compose version >/dev/null 2>&1; then
	  COMPOSE_CMD="docker compose"
	elif command -v docker-compose >/dev/null 2>&1; then
	  COMPOSE_CMD="docker-compose"
	else
	  COMPOSE_CMD=""
	fi

	if [ -n "$COMPOSE_CMD" ]; then
	  echo "[ec2] using compose command: $COMPOSE_CMD"
	  $COMPOSE_CMD down || true
	  $COMPOSE_CMD up -d --remove-orphans
	else
	  echo "[ec2] compose not found, using docker run fallback"
	  docker rm -f banking-frontend banking-backend >/dev/null 2>&1 || true
	  # Remove any other Docker containers that are holding frontend/backend ports.
	  for PORT in 8080 80; do
	    CONFLICT_IDS=$(docker ps -q --filter "publish=${{PORT}}")
	    if [ -n "$CONFLICT_IDS" ]; then
	      echo "[ec2] removing containers on port ${{PORT}}: $CONFLICT_IDS"
	      docker rm -f $CONFLICT_IDS >/dev/null 2>&1 || true
	    fi
	  done
	  docker network create banking-net >/dev/null 2>&1 || true

	  docker rm -f banking-backend >/dev/null 2>&1 || true
	  docker run -d \
	    --name banking-backend \
	    --restart unless-stopped \
	    --network banking-net \
	    --network-alias backend \
	    --env-file .env \
	    -p 8080:8080 \
	    {backend_image} || {{
	      echo "[ec2] backend failed to start. Port 8080 may still be occupied by non-Docker process."
	      ss -lntp | grep ':8080' || true
	      exit 125
	    }}

	  docker rm -f banking-frontend >/dev/null 2>&1 || true
	  docker run -d \
	    --name banking-frontend \
	    --restart unless-stopped \
	    --network banking-net \
	    -p 80:80 \
	    {frontend_image} || {{
	      echo "[ec2] frontend failed to start. Port 80 may still be occupied by non-Docker process."
	      ss -lntp | grep ':80' || true
	      exit 125
	    }}
	fi

echo "[ec2] running containers"
docker ps --format 'table {{{{.Names}}}}\t{{{{.Image}}}}\t{{{{.Status}}}}\t{{{{.Ports}}}}'

echo "[ec2] backend logs (last 80)"
docker logs --tail 80 banking-backend || true

echo "[ec2] frontend logs (last 80)"
docker logs --tail 80 banking-frontend || true
"""

	params = {"commands": [remote_script]}
	with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
		json.dump(params, tf)
		params_file = tf.name

	try:
		cp = run(
			aws_cmd(
				profile,
				region,
				"ssm",
				"send-command",
				"--instance-ids",
				instance_id,
				"--document-name",
				"AWS-RunShellScript",
				"--comment",
				"Deploy banking voice backend+frontend",
				"--parameters",
				f"file://{params_file}",
				"--query",
				"Command.CommandId",
				"--output",
				"text",
			),
			capture=True,
		)
		return cp.stdout.strip()
	finally:
		try:
			os.unlink(params_file)
		except OSError:
			pass


def wait_for_ssm(profile: str | None, region: str, instance_id: str, command_id: str) -> tuple[str, str]:
	terminal_states = {"Success", "Cancelled", "TimedOut", "Failed", "DeliveryTimedOut"}
	for _ in range(80):
		time.sleep(6)
		cp = run(
			aws_cmd(
				profile,
				region,
				"ssm",
				"get-command-invocation",
				"--command-id",
				command_id,
				"--instance-id",
				instance_id,
			),
			check=False,
			capture=True,
		)
		if cp.returncode != 0:
			continue

		data = json.loads(cp.stdout)
		status = data.get("Status", "Unknown")
		log(f"SSM status: {status}")
		if status in terminal_states:
			stdout = data.get("StandardOutputContent", "")
			stderr = data.get("StandardErrorContent", "")
			return status, f"{stdout}\n{stderr}".strip()

	return "TimedOut", "SSM command polling timeout"


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Deploy backend + frontend Docker images to EC2 via ECR + SSM")
	parser.add_argument(
		"--instance-id",
		default=os.getenv("EC2_INSTANCE_ID", ""),
		help="EC2 instance ID (example: i-0123456789abcdef0). Can also be set via EC2_INSTANCE_ID env var.",
	)
	parser.add_argument("--region", default=os.getenv("AWS_REGION", "ap-south-1"), help="AWS region")
	parser.add_argument("--profile", default=os.getenv("AWS_PROFILE"), help="AWS CLI profile (optional)")
	parser.add_argument("--tag", default="latest", help="Docker image tag")
	parser.add_argument(
		"--backend-repo",
		default="banking-voice-agent-backend",
		help="ECR repo name for backend image",
	)
	parser.add_argument(
		"--frontend-repo",
		default="banking-voice-agent-frontend",
		help="ECR repo name for frontend image",
	)
	parser.add_argument(
		"--env-file",
		default="backend/.env",
		help="Path to env file that will be loaded and copied to EC2",
	)
	parser.add_argument(
		"--frontend-api-url",
		default="",
		help="Value for VITE_API_URL at frontend build time. Defaults to http://<ec2-host>:8080",
	)
	return parser.parse_args()


def main() -> int:
	args = parse_args()

	if not args.instance_id:
		raise RuntimeError(
			"Missing EC2 instance ID. Pass --instance-id i-xxxxxxxxxxxxxxxxx "
			"or set EC2_INSTANCE_ID environment variable."
		)

	repo_root = Path(__file__).resolve().parents[1]
	backend_dir = repo_root / "backend"
	frontend_dir = repo_root / "frontend"
	frontend_dockerfile = frontend_dir / "Dockerfile"
	env_file = (repo_root / args.env_file).resolve()

	require_command("aws", "Install AWS CLI v2 and configure credentials.")
	require_command("docker", "Install Docker Desktop or Docker Engine.")

	if not backend_dir.exists():
		raise RuntimeError(f"Backend directory missing: {backend_dir}")
	if not frontend_dir.exists():
		raise RuntimeError(f"Frontend directory missing: {frontend_dir}")
	if not frontend_dockerfile.exists():
		raise RuntimeError(
			f"Frontend Dockerfile missing: {frontend_dockerfile}. "
			"Create it before running deploy."
		)

	log("Loading environment values from backend .env")
	env_kv = load_dotenv(env_file)
	# Re-serialize parsed env values to avoid carrying wrapping quotes that can
	# break consumers like botocore region parsing on EC2.
	env_text = "\n".join(f"{k}={v}" for k, v in env_kv.items()) + "\n"
	log(f"Loaded {len(env_kv)} env keys")

	account_id = get_account_id(args.profile)
	registry = f"{account_id}.dkr.ecr.{args.region}.amazonaws.com"

	ensure_ecr_repo(args.profile, args.region, args.backend_repo)
	ensure_ecr_repo(args.profile, args.region, args.frontend_repo)
	ecr_login(args.profile, args.region, registry)

	backend_local = f"{args.backend_repo}:{args.tag}"
	backend_remote = f"{registry}/{args.backend_repo}:{args.tag}"
	frontend_local = f"{args.frontend_repo}:{args.tag}"
	frontend_remote = f"{registry}/{args.frontend_repo}:{args.tag}"

	if args.frontend_api_url:
		frontend_api_url = args.frontend_api_url
	else:
		endpoint = get_ec2_endpoint(args.profile, args.region, args.instance_id)
		frontend_api_url = f"http://{endpoint}:8080"

	log(f"Frontend build API URL: {frontend_api_url}")

	log("Building and pushing backend image")
	docker_build_and_push(
		image_local=backend_local,
		image_remote=backend_remote,
		context_dir=backend_dir,
		dockerfile=backend_dir / "Dockerfile",
	)

	log("Building and pushing frontend image")
	docker_build_and_push(
		image_local=frontend_local,
		image_remote=frontend_remote,
		context_dir=frontend_dir,
		dockerfile=frontend_dockerfile,
		build_args={"VITE_API_URL": frontend_api_url},
	)

	compose_text = build_compose_yaml(backend_remote, frontend_remote)
	command_id = send_ssm_deploy(
		profile=args.profile,
		region=args.region,
		instance_id=args.instance_id,
		account_id=account_id,
		env_text=env_text,
		compose_text=compose_text,
		backend_repo=args.backend_repo,
		frontend_repo=args.frontend_repo,
		image_tag=args.tag,
	)
	log(f"SSM command ID: {command_id}")

	status, output = wait_for_ssm(args.profile, args.region, args.instance_id, command_id)
	print("\n==================== SSM OUTPUT ====================")
	print(output or "(no output)")
	print("====================================================\n")

	if status != "Success":
		raise RuntimeError(f"Deployment failed with SSM status: {status}")

	endpoint = get_ec2_endpoint(args.profile, args.region, args.instance_id)
	print("Deployment successful")
	print(f"Frontend URL: http://{endpoint}")
	print(f"Backend URL : http://{endpoint}:8080/health")
	return 0


if __name__ == "__main__":
	try:
		raise SystemExit(main())
	except KeyboardInterrupt:
		log("Interrupted by user")
		raise SystemExit(130)
	except Exception as exc:  # noqa: BLE001
		print(f"Deployment failed: {exc}", file=sys.stderr)
		raise SystemExit(1)
