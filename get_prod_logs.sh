aws ssm start-session --region ap-south-1 --target i-083a2c776ad95735c#!/bin/bash
REGION="ap-south-1"
INSTANCE="i-083a2c776ad95735c"

echo "Fetching recent production logs relating to language switch and barge-in..."
CMD_ID=$(aws --region "$REGION" ssm send-command \
  --instance-ids "$INSTANCE" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker logs --tail 2000 banking-backend | grep -iE \"language|barge|vad\""]' \
  --query 'Command.CommandId' \
  --output text)

sleep 3

aws --region "$REGION" ssm get-command-invocation \
  --command-id "$CMD_ID" \
  --instance-id "$INSTANCE" \
  --query 'StandardOutputContent' \
  --output text
