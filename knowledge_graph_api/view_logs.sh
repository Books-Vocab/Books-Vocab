#!/bin/bash
# 連線到 AWS Lightsail 並持續查看 Docker 的即時 Log

echo "連線到 AWS Lightsail 查看即時日誌中 (按 Ctrl+C 退出)..."
ssh -i ~/.ssh/lightsail_default.pem ubuntu@54.95.189.179 "cd ~/knowledge_graph_api && docker compose logs -f"
