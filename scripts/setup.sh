#!/bin/bash
# OCI VM (VM.Standard.E2.1.Micro) 초기 설정 스크립트
# 최초 1회만 실행
# 사용법: ssh ubuntu@140.245.76.242 'bash -s' < scripts/setup.sh

set -e
echo "=== NewsHive OCI VM 초기 설정 시작 ==="

# 1. 스왑 파일 2GB 추가 (E2.1.Micro 1GB RAM 보완)
if [ ! -f /swapfile ]; then
    echo ">>> 스왑 파일 생성 (2GB)..."
    sudo fallocate -l 2G /swapfile
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo ">>> 스왑 설정 완료"
fi

# 2. 시스템 패키지 업데이트
echo ">>> 시스템 업데이트..."
sudo apt-get update -qq

# 3. PostgreSQL 16 설치
if ! command -v psql &>/dev/null; then
    echo ">>> PostgreSQL 16 설치..."
    sudo apt-get install -y postgresql postgresql-contrib
    sudo systemctl enable postgresql
    sudo systemctl start postgresql
fi

# 4. PostgreSQL DB 생성
echo ">>> DB 설정..."
sudo -u postgres psql -c "CREATE USER newshive WITH PASSWORD 'changeme_strong_password';" 2>/dev/null || true
sudo -u postgres psql -c "CREATE DATABASE news_hive OWNER newshive;" 2>/dev/null || true
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE news_hive TO newshive;" 2>/dev/null || true

# PostgreSQL 메모리 최적화 (1GB RAM 환경)
PG_CONF="/etc/postgresql/$(ls /etc/postgresql)/main/postgresql.conf"
sudo sed -i "s/#shared_buffers = 128MB/shared_buffers = 128MB/" "$PG_CONF" 2>/dev/null || true
sudo sed -i "s/shared_buffers = 256MB/shared_buffers = 128MB/" "$PG_CONF" 2>/dev/null || true
echo "work_mem = 4MB" | sudo tee -a "$PG_CONF" > /dev/null
echo "maintenance_work_mem = 32MB" | sudo tee -a "$PG_CONF" > /dev/null
sudo systemctl restart postgresql

# 5. Python 3.12 및 필수 패키지 설치
echo ">>> Python 설치..."
sudo apt-get install -y python3.12 python3.12-venv python3-pip git

# 6. 프로젝트 클론
if [ ! -d /home/ubuntu/news-hive ]; then
    echo ">>> 프로젝트 클론..."
    git clone https://github.com/KyungHwanLeeNexsol/news-hive.git /home/ubuntu/news-hive
fi

# 7. Python 가상환경 + 의존성 설치
echo ">>> Python 의존성 설치..."
cd /home/ubuntu/news-hive/backend
python3.12 -m venv venv
source venv/bin/activate
pip install --quiet -r requirements.txt

# 8. .env 파일 생성 (최초 1회)
if [ ! -f /home/ubuntu/news-hive/backend/.env ]; then
    echo ">>> .env 파일 생성 (편집 필요)..."
    cp /home/ubuntu/news-hive/backend/.env.example /home/ubuntu/news-hive/backend/.env
    sed -i "s|DATABASE_URL=.*|DATABASE_URL=postgresql://newshive:changeme_strong_password@localhost:5432/news_hive|" /home/ubuntu/news-hive/backend/.env
    echo ""
    echo "!!! 중요: /home/ubuntu/news-hive/backend/.env 파일을 편집하여 API 키를 입력하세요 !!!"
fi

# 9. DB 마이그레이션
echo ">>> Alembic 마이그레이션..."
cd /home/ubuntu/news-hive/backend
source venv/bin/activate
alembic upgrade head

# 10. systemd 서비스 등록
echo ">>> systemd 서비스 등록..."
sudo cp /home/ubuntu/news-hive/scripts/newshive.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable newshive
sudo systemctl start newshive

# 11. 방화벽 포트 개방
echo ">>> 포트 8000 개방..."
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT 2>/dev/null || true

echo ""
echo "=== 설정 완료 ==="
echo "서비스 상태 확인: sudo systemctl status newshive"
echo "로그 확인: journalctl -u newshive -f"
echo ""
echo "다음 단계: /home/ubuntu/news-hive/backend/.env 파일에 API 키 입력 후 'sudo systemctl restart newshive'"
