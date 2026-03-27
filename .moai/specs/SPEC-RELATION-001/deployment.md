# SPEC-RELATION-001 배포 가이드

## 필수 작업

### 1. DB 마이그레이션

서버에서 alembic upgrade head 실행:

```
ssh -i ~/Downloads/news-hive-key.key ubuntu@140.245.76.242
cd ~/news-hive && source venv/bin/activate
alembic upgrade head
```

적용될 마이그레이션:
- 019: stock_relations 테이블 신규 생성
- 020: news_stock_relations에 3개 컬럼 추가 (relation_sentiment, propagation_type, impact_reason)

### 2. 앱 재시작

```
sudo systemctl restart newshive
```

앱 재시작 후 자동 실행:
- stock_relations 테이블이 비어있으면 Gemini AI 관계 추론 시작 (백그라운드)
- 추론 완료까지 약 1-3분 소요 (Gemini API rate limit에 따라 변동)

### 3. 확인 방법

추론 완료 확인:

```
journalctl -u newshive -n 50 --no-pager | grep "relation"
```

API 동작 확인:

```
curl http://localhost:8000/api/stocks/relations?stock_id=1
```

## 자동 동작

- **매주 일요일 04:00 KST**: 신규 섹터에 대한 증분 관계 추론 자동 실행
- **뉴스 크롤링 시마다**: 관계 그래프 기반 간접 영향 뉴스 자동 전파

## 롤백

문제 발생 시:

```
alembic downgrade 018
```

(019, 020 마이그레이션이 롤백됨)
