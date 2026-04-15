#!/bin/bash
set -e

echo "==> Deploying to asa.ipronto.net..."

ssh ubuntu@ipronto.net << 'EOF'
  set -e
  echo "==> Pulling latest code..."
  cd /home/ubuntu/app_store_analyzer/Backend

  git -C /home/ubuntu/app_store_analyzer pull

  echo "==> Rebuilding and restarting backend container..."
  docker-compose down
  docker-compose up --build -d

  echo "==> Checking health..."
  sleep 3
  curl -sf http://localhost:5001/api/health && echo " OK" || echo " WARNING: health check failed"
EOF

echo "==> Deploy complete. Live at https://asa.ipronto.net/api/health"
