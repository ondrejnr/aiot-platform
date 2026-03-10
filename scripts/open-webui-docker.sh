#!/bin/bash
# Open WebUI - runs as Docker container (not in K8s)
# Volume: open-webui:/app/backend/data
# Port: 8080 (host network)

docker run -d \
  --name open-webui \
  --network host \
  --restart always \
  -v open-webui:/app/backend/data \
  -e OLLAMA_BASE_URL=http://10.164.0.3:11434 \
  -e OLLAMA_API_BASE_URL=http://10.164.0.3:11434 \
  -e USE_OLLAMA_DOCKER=false \
  ghcr.io/open-webui/open-webui:main

echo "Open WebUI started on port 8080"
echo "Configure Cerebrus + Ngrok connections in Admin > Settings > Connections"
