"""Reuse immutable trust configuration, never per-run HTTP/stream state.

On Windows each httpx transport can reload the same certificate bundle. A
client with environment proxies may build four transports. Certificate checks,
hostname validation and environment CA overrides remain httpx defaults.
"""
from functools import lru_cache
import os
from pathlib import Path
import time

import httpx


def _stamp(path):
    if not path:
        return None
    try:
        stat = Path(path).stat()
        return (path, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return (path, None, None)


@lru_cache(maxsize=8)
def _verified_context(trust_env, cert_file, cert_directory, refresh_window):
    # Never mutate this context after it is returned to any transport.
    return httpx.create_ssl_context(verify=True, trust_env=trust_env)


def verified_context(trust_env=True):
    return _verified_context(trust_env,
        _stamp(os.environ.get('SSL_CERT_FILE')) if trust_env else None,
        _stamp(os.environ.get('SSL_CERT_DIR')) if trust_env else None,
        int(time.monotonic() // 300))
