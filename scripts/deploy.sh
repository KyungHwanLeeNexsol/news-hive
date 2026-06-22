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
# 급등 시그널 생성 시간대 배포 guard — 재시작 시 신호 생성 중단 방지
# 가드 1: 10:00 KST 잡 (09:50~10:20 KST) — 평균 소요 13~18분 + 버퍼
# 가드 2: 15:20 KST 잡 (15:15~16:10 KST) — 최대 소요 ~18분 + 커버리지 확장 ~5분 버퍼
_KST_H=$(TZ="Asia/Seoul" date '+%-H')
_KST_M=$(TZ="Asia/Seoul" date '+%-M')
_NOW_MIN=$(( _KST_H * 60 + _KST_M ))
_GUARD1_START=$(( 9 * 60 + 50 ))
_GUARD1_END=$(( 10 * 60 + 20 ))
_GUARD2_START=$(( 15 * 60 + 15 ))
_GUARD2_END=$(( 16 * 60 + 10 ))
if [ "$_NOW_MIN" -ge "$_GUARD1_START" ] && [ "$_NOW_MIN" -le "$_GUARD1_END" ]; then
    _WAIT_SECS=$(( (_GUARD1_END - _NOW_MIN) * 60 ))
    echo ">>> 10:00 KST 급등 시그널 생성 시간대 (09:50~10:20 KST) — ${_WAIT_SECS}초 대기 후 재시작..."
    sleep "$_WAIT_SECS"
elif [ "$_NOW_MIN" -ge "$_GUARD2_START" ] && [ "$_NOW_MIN" -le "$_GUARD2_END" ]; then
    _WAIT_SECS=$(( (_GUARD2_END - _NOW_MIN) * 60 ))
    echo ">>> 15:20 KST 급등 시그널 생성 시간대 (15:15~16:10 KST) — ${_WAIT_SECS}초 대기 후 재시작..."
    sleep "$_WAIT_SECS"
fi
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
