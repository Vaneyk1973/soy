import json
import logging
import os
from typing import Optional

import redis
from redis.sentinel import Sentinel

logger = logging.getLogger(__name__)


class Cache:
    def __init__(self) -> None:
        self._client = self._init_client()
        self._ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "300"))

    def _init_client(self):
        sentinel_hosts = os.getenv("REDIS_SENTINEL_HOSTS")
        if sentinel_hosts:
            hosts = []
            for host in sentinel_hosts.split(","):
                host = host.strip()
                if not host:
                    continue
                h, p = host.split(":")
                hosts.append((h, int(p)))
            service_name = os.getenv("REDIS_SENTINEL_SERVICE", "mymaster")
            sentinel = Sentinel(hosts, socket_timeout=0.5)
            return sentinel.master_for(service_name, socket_timeout=0.5)
        redis_url = os.getenv("REDIS_URL", "redis://redis-master:6379/0")
        return redis.Redis.from_url(redis_url, socket_timeout=0.5)

    def get_json(self, key: str) -> Optional[dict]:
        value = self._client.get(key)
        if value is None:
            logger.info("cache miss: %s", key)
            return None
        logger.info("cache hit: %s", key)
        return json.loads(value)

    def set_json(self, key: str, payload: dict) -> None:
        self._client.setex(key, self._ttl_seconds, json.dumps(payload))

    def delete(self, key: str) -> None:
        self._client.delete(key)

    def delete_pattern(self, pattern: str) -> None:
        for key in self._client.scan_iter(match=pattern):
            self._client.delete(key)
