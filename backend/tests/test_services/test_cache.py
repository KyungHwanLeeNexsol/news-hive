"""
Redis 캐시 모듈 및 Rate Limiter 테스트.

Redis 없이 실행되며, mock을 사용하여 Redis 연동 로직을 검증한다.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# --- cache.py 유닛 테스트 ---


class TestJsonSerializer:
    """JSON 직렬화 헬퍼 테스트."""

    def test_datetime_serialization(self):
        from app.cache import _json_serializer
        dt = datetime(2026, 3, 29, 12, 0, 0)
        result = _json_serializer(dt)
        assert result == "2026-03-29T12:00:00"

    def test_unsupported_type_raises(self):
        from app.cache import _json_serializer
        with pytest.raises(TypeError):
            _json_serializer(set())


class TestGetRedisDisabled:
    """REDIS_URL 미설정 시 None 반환 테스트."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_url(self):
        import app.cache as cache_mod
        # 상태 초기화
        cache_mod._redis_client = None
        cache_mod._redis_initialized = False

        with patch("app.config.settings", MagicMock(REDIS_URL="")):
            result = await cache_mod.get_redis()
            assert result is None

        # 정리
        cache_mod._redis_initialized = False
        cache_mod._redis_client = None


class TestCacheGetWithoutRedis:
    """Redis 미연결 시 cache_get이 None 반환."""

    @pytest.mark.asyncio
    async def test_returns_none_when_redis_unavailable(self):
        import app.cache as cache_mod
        cache_mod._redis_client = None
        cache_mod._redis_initialized = False

        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=None):
            result = await cache_mod.cache_get("test:key")
            assert result is None


class TestCacheSetWithoutRedis:
    """Redis 미연결 시 cache_set이 False 반환."""

    @pytest.mark.asyncio
    async def test_returns_false_when_redis_unavailable(self):
        import app.cache as cache_mod
        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=None):
            result = await cache_mod.cache_set("test:key", {"foo": "bar"})
            assert result is False


class TestCacheDeleteWithoutRedis:
    """Redis 미연결 시 cache_delete가 0 반환."""

    @pytest.mark.asyncio
    async def test_returns_zero_when_redis_unavailable(self):
        import app.cache as cache_mod
        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=None):
            result = await cache_mod.cache_delete("test:*")
            assert result == 0


class TestCacheGetWithMockRedis:
    """Mock Redis로 cache_get 동작 검증."""

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        import app.cache as cache_mod
        cache_mod._cache_stats = {"hits": 0, "misses": 0}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=json.dumps({"name": "test"}))

        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            result = await cache_mod.cache_get("test:key")
            assert result == {"name": "test"}
            assert cache_mod._cache_stats["hits"] == 1

    @pytest.mark.asyncio
    async def test_cache_miss(self):
        import app.cache as cache_mod
        cache_mod._cache_stats = {"hits": 0, "misses": 0}

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            result = await cache_mod.cache_get("nonexistent")
            assert result is None
            assert cache_mod._cache_stats["misses"] == 1


class TestCacheSetWithMockRedis:
    """Mock Redis로 cache_set 동작 검증."""

    @pytest.mark.asyncio
    async def test_stores_json_with_ttl(self):
        import app.cache as cache_mod

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            result = await cache_mod.cache_set("test:key", {"data": 123}, ttl=60)
            assert result is True
            mock_redis.set.assert_called_once()
            call_args = mock_redis.set.call_args
            assert call_args[0][0] == "newshive:test:key"
            assert call_args[1]["ex"] == 60

    @pytest.mark.asyncio
    async def test_serializes_datetime(self):
        import app.cache as cache_mod

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()

        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            result = await cache_mod.cache_set(
                "test:dt",
                {"time": datetime(2026, 1, 1)},
                ttl=60,
            )
            assert result is True
            stored = json.loads(mock_redis.set.call_args[0][1])
            assert stored["time"] == "2026-01-01T00:00:00"

    @pytest.mark.asyncio
    async def test_handles_redis_error_gracefully(self):
        import app.cache as cache_mod

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(side_effect=ConnectionError("disconnected"))

        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            result = await cache_mod.cache_set("test:key", "value")
            assert result is False


class TestCacheDeleteWithMockRedis:
    """Mock Redis로 cache_delete 동작 검증."""

    @pytest.mark.asyncio
    async def test_deletes_matching_keys(self):
        import app.cache as cache_mod

        mock_redis = AsyncMock()
        # scan_iter를 async generator로 모킹
        async def fake_scan_iter(**kwargs):
            for k in ["newshive:api:news:1", "newshive:api:news:2"]:
                yield k
        mock_redis.scan_iter = fake_scan_iter
        mock_redis.delete = AsyncMock()

        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            result = await cache_mod.cache_delete("api:news:*")
            assert result == 2
            assert mock_redis.delete.call_count == 2


class TestCacheStats:
    """캐시 통계 함수 테스트."""

    def test_stats_calculation(self):
        import app.cache as cache_mod
        cache_mod._cache_stats = {"hits": 7, "misses": 3}
        stats = cache_mod.get_cache_stats()
        assert stats["hits"] == 7
        assert stats["misses"] == 3
        assert stats["total"] == 10
        assert stats["hit_rate"] == 0.7

    def test_stats_with_zero_total(self):
        import app.cache as cache_mod
        cache_mod._cache_stats = {"hits": 0, "misses": 0}
        stats = cache_mod.get_cache_stats()
        assert stats["hit_rate"] == 0.0

    def test_reset_stats(self):
        import app.cache as cache_mod
        cache_mod._cache_stats = {"hits": 100, "misses": 50}
        cache_mod.reset_cache_stats()
        assert cache_mod._cache_stats == {"hits": 0, "misses": 0}


class TestKeyPrefix:
    """캐시 키 접두사 검증."""

    def test_key_prefix_value(self):
        from app.cache import KEY_PREFIX
        assert KEY_PREFIX == "newshive:"

    @pytest.mark.asyncio
    async def test_key_prefix_applied_on_get(self):
        import app.cache as cache_mod

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            await cache_mod.cache_get("sector:perf")
            mock_redis.get.assert_called_once_with("newshive:sector:perf")


# --- Rate Limiter 미들웨어 테스트 ---


class TestRateLimiterExpensiveEndpoints:
    """고비용 엔드포인트 판별 테스트."""

    def test_refresh_is_expensive(self):
        from app.middleware.rate_limiter import _is_expensive
        assert _is_expensive("POST", "/api/news/refresh") is True

    def test_fund_manager_is_expensive(self):
        from app.middleware.rate_limiter import _is_expensive
        assert _is_expensive("POST", "/api/fund-manager/briefing") is True

    def test_get_news_is_not_expensive(self):
        from app.middleware.rate_limiter import _is_expensive
        assert _is_expensive("GET", "/api/news") is False

    def test_health_is_not_expensive(self):
        from app.middleware.rate_limiter import _is_expensive
        assert _is_expensive("GET", "/api/health") is False


class TestRateLimiterMiddleware:
    """Rate Limiter 미들웨어 동작 테스트."""

    @pytest.mark.asyncio
    async def test_allows_when_redis_unavailable(self):
        """Redis 미연결 시 모든 요청 허용."""
        from app.middleware.rate_limiter import RateLimiterMiddleware

        middleware = RateLimiterMiddleware(app=MagicMock())

        # call_next 모킹
        mock_response = MagicMock()
        call_next = AsyncMock(return_value=mock_response)

        # Request 모킹
        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.method = "GET"
        request.url = MagicMock(path="/api/news")

        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=None):
            response = await middleware.dispatch(request, call_next)
            assert response == mock_response

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded_returns_429(self):
        """제한 초과 시 429 응답."""
        from app.middleware.rate_limiter import RateLimiterMiddleware

        middleware = RateLimiterMiddleware(app=MagicMock())

        mock_redis = AsyncMock()
        # 61번째 요청 (기본 제한 60)
        mock_redis.incr = AsyncMock(return_value=61)
        mock_redis.expire = AsyncMock()

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.method = "GET"
        request.url = MagicMock(path="/api/news")

        call_next = AsyncMock()

        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            response = await middleware.dispatch(request, call_next)
            assert response.status_code == 429
            call_next.assert_not_called()

    @pytest.mark.asyncio
    async def test_allows_within_limit(self):
        """제한 내 요청 허용."""
        from app.middleware.rate_limiter import RateLimiterMiddleware

        middleware = RateLimiterMiddleware(app=MagicMock())

        mock_redis = AsyncMock()
        mock_redis.incr = AsyncMock(return_value=5)
        mock_redis.expire = AsyncMock()

        mock_response = MagicMock()
        call_next = AsyncMock(return_value=mock_response)

        request = MagicMock()
        request.client = MagicMock(host="127.0.0.1")
        request.method = "GET"
        request.url = MagicMock(path="/api/news")

        with patch("app.cache.get_redis", new_callable=AsyncMock, return_value=mock_redis):
            response = await middleware.dispatch(request, call_next)
            assert response == mock_response


class TestCloseRedis:
    """Redis 연결 종료 테스트."""

    @pytest.mark.asyncio
    async def test_close_resets_state(self):
        import app.cache as cache_mod
        cache_mod._redis_client = AsyncMock()
        cache_mod._redis_initialized = True

        await cache_mod.close_redis()

        assert cache_mod._redis_client is None
        assert cache_mod._redis_initialized is False
