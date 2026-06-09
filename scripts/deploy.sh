#!/bin/bash
# OCI VM 배포 스크립트 (GitHub Actions에서 SSH로 실행)
# 직접 실행도 가능: ssh ubuntu@140.245.76.242 'bash -s' < scripts/deploy.sh

set -e

# 동시 배포 방지: 다른 배포가 진행 중이면 최대 5분 대기 후 실행
LOCK_FILE="/tmp/newshive-deploy.lock"
exec 200>"$LOCK_FILE"
flock --wait 300 200 || { echo "!!! 배포 락 획득 실패 (5분 초과). 서버를 확인하세요."; exit 1; }

cd /home/ubuntu/news-hive

echo ">>> git pull..."
git fetch origin
git reset --hard origin/main

echo ">>> pip install..."
cd backend
source venv/bin/activate
pip install --quiet -r requirements.txt

echo ">>> alembic upgrade..."
alembic upgrade head

echo ">>> 서비스 재시작..."
sudo systemctl restart newshive
sleep 3

# 서비스 상태 확인
if systemctl is-active --quiet newshive; then
    echo ">>> 배포 완료 ($(date))"
else
    echo "!!! 서비스 시작 실패"
    journalctl -u newshive -n 20 --no-pager
    exit 1
fi
