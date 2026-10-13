"""Rate limiting: per process, and shared through Redis (when a Redis server is available)."""

import os
import shutil
import socket
import subprocess
import time

import pytest

from app.core.deps import RateLimiter, RedisRateLimiter, make_limiter
from app.core.errors import TooManyRequests


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def redis_url():
    if os.environ.get("EDU_TEST_REDIS_URL"):
        yield os.environ["EDU_TEST_REDIS_URL"]
        return
    if not shutil.which("redis-server"):
        pytest.skip("no Redis server available")
    port = _free_port()
    proc = subprocess.Popen(["redis-server", "--port", str(port), "--save", "", "--appendonly", "no"], stdout=subprocess.DEVNULL)
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
            break
        except OSError:
            time.sleep(0.05)
    yield f"redis://127.0.0.1:{port}/0"
    proc.terminate()
    proc.wait()


def test_in_process_limiter_window():
    lim = RateLimiter()
    for _ in range(3):
        lim.hit("k", 3, window=0.2)
    with pytest.raises(TooManyRequests):
        lim.hit("k", 3, window=0.2)
    lim.hit("other", 3, window=0.2)  # keys are independent
    time.sleep(0.25)
    lim.hit("k", 3, window=0.2)  # the window slid


def test_redis_limiter_is_shared_between_replicas(redis_url):
    a, b = RedisRateLimiter(redis_url), RedisRateLimiter(redis_url)  # two API processes
    a.reset()
    a.hit("auth:1.2.3.4", 3, window=1)
    b.hit("auth:1.2.3.4", 3, window=1)
    a.hit("auth:1.2.3.4", 3, window=1)
    with pytest.raises(TooManyRequests):
        b.hit("auth:1.2.3.4", 3, window=1)
    a.hit("auth:5.6.7.8", 3, window=1)
    time.sleep(1.1)
    b.hit("auth:1.2.3.4", 3, window=1)
    a.reset()
    for _ in range(3):
        a.hit("auth:1.2.3.4", 3, window=1)


def test_redis_outage_falls_back_to_per_process_limits():
    lim = RedisRateLimiter(f"redis://127.0.0.1:{_free_port()}/0")  # nothing listens here
    lim.hit("k", 2)
    lim.hit("k", 2)
    with pytest.raises(TooManyRequests):
        lim.hit("k", 2)


def test_factory():
    assert isinstance(make_limiter(""), RateLimiter)
    assert isinstance(make_limiter("redis://127.0.0.1:1/0"), RedisRateLimiter)
