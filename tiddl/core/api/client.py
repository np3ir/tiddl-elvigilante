from __future__ import annotations
import json
from logging import getLogger
from pathlib import Path
from typing import Any, Type, TypeVar, Callable, Optional, Literal, Union

from pydantic import BaseModel
from time import sleep
import time
import random
import threading

# CRITICAL FIX: Import HTTPError
from requests.exceptions import JSONDecodeError, HTTPError
from requests_cache import (
    CachedSession,
    StrOrPath,
    NEVER_EXPIRE,
)

from .exceptions import ApiError

T = TypeVar("T", bound=BaseModel)

API_URL = "https://api.tidal.com/v1"
API_V1_URL = "https://api.tidal.com/v1"
API_V2_URL = "https://api.tidal.com/v2"  # For Feed and Activity API
MAX_RETRIES = 5
RETRY_DELAY = 2

log = getLogger(__name__)


class TidalClientImproved:
    """Improved client with support for v1 & v2, auto-refresh, and rate limiting"""
    
    _token: str
    _refresh_token: Optional[str]
    _token_expiry: Optional[int]  # Unix timestamp
    debug_path: Union[Path, None]
    session: CachedSession
    on_token_expiry: Optional[Callable[[bool, int], Union[tuple[str, int, Union[str, None]], None]]]
    
    # Rate Limiting: 60 requests per minute
    _last_request_time: float
    _request_interval: float

    def __init__(
        self,
        token: str,
        cache_name: StrOrPath,
        omit_cache: bool = False,
        debug_path: Union[Path, None] = None,
        on_token_expiry: Optional[Callable[[bool, int], Union[tuple[str, int, Union[str, None]], None]]] = None,
        refresh_token: Optional[str] = None,
        token_expiry: Optional[int] = None,  # Unix timestamp
        requests_per_minute: int = 50,
    ) -> None:
        self.on_token_expiry = on_token_expiry
        self.debug_path = debug_path
        self._refresh_token = refresh_token
        self._token_expiry = token_expiry

        # Rate Limiting Init
        safe_rpm = requests_per_minute if requests_per_minute > 0 else 50
        self._last_request_time = 0.0
        self._request_interval = 60.0 / safe_rpm
        self._rate_lock = threading.Lock()
        self._rate_limit_delay: float = 0.0  # Adaptive: grows on 429, shrinks on success
        
        self.session = CachedSession(
            cache_name=cache_name,
            always_revalidate=omit_cache
        )
        
        # IMPROVEMENT: Add complete headers as per documentation
        self.session.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        self._token = token
    
    @property
    def token(self):
        return self._token

    @token.setter
    def token(self, token: str):
        self._token = token
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
            }
        )

    def _check_token_expiry(self) -> bool:
        """Checks if the token is about to expire (< 1 hour remaining)"""
        if not self._token_expiry:
            return True  # We don't know, assume valid
        
        current_time = int(time.time())
        time_remaining = self._token_expiry - current_time
        
        # If less than 1 hour (3600 seconds) remains, renew
        if time_remaining < 3600:
            log.warning(f"Token expiring soon ({time_remaining}s remaining)")
            return False
        
        return True
    
    def _auto_refresh_token(self, force_refresh: bool = False) -> bool:
        """Tries to renew the token automatically"""
        if not self._refresh_token or not self.on_token_expiry:
            return False
        
        try:
            # Expects (access_token, expires_at, refresh_token)
            # Request at least 3600s validity if we are proactively refreshing (force_refresh=False)
            # If force_refresh=True, validity check is skipped inside callback anyway.
            result = self.on_token_expiry(force_refresh=force_refresh, min_validity=3600)
            if result:
                new_token, new_expiry, new_refresh_token = result
                self.token = new_token
                self._token_expiry = new_expiry
                if new_refresh_token:
                    self._refresh_token = new_refresh_token
                
                log.info(f"Token refreshed successfully. Expires at: {new_expiry}")
                return True
        except Exception as e:
            log.error(f"Failed to refresh token: {e}")
        
        return False
    
    def fetch(
        self,
        model: Type[T],
        endpoint: str,
        params: dict[str, Any] = {},
        expire_after: int = NEVER_EXPIRE,
        api_version: Literal["v1", "v2"] = "v1",
        _attempt: int = 1,
        _refreshed: bool = False,
    ) -> T:
        """
        Improved fetch with:
        - Support for v1 and v2 APIs
        - Automatic token refresh
        - Better rate limiting handling
        - Improved debugging
        """
        
        # Check token expiration
        if not self._check_token_expiry():
            self._auto_refresh_token()
        
        # Select base URL based on version
        base_url = API_V1_URL if api_version == "v1" else API_V2_URL
        
        # Adaptive delay from previous 429s
        if self._rate_limit_delay > 0:
            time.sleep(self._rate_limit_delay)

        # Rate Limiting Enforcement (thread-safe, fixed interval + jitter)
        with self._rate_lock:
            elapsed = time.time() - self._last_request_time
            wait = self._request_interval - elapsed + random.uniform(0, 0.3)
            if wait > 0:
                time.sleep(wait)
            self._last_request_time = time.time()

        res = self.session.get(
            f"{base_url}/{endpoint}",
            params=params,
            expire_after=expire_after
        )

        # Cache hits don't consume API quota — release the slot
        if getattr(res, 'from_cache', False):
            with self._rate_lock:
                self._last_request_time = time.time() - self._request_interval

        # ============================================================
        # IMPROVEMENT 5: Detailed rate limiting handling (429)
        # ============================================================
        if res.status_code == 429:
            self._rate_limit_delay = min(5.0, self._rate_limit_delay + 1.0)
            retry_after = res.headers.get("Retry-After", "60")

            try:
                wait_time = int(retry_after)
            except ValueError:
                wait_time = 60

            log.warning(
                f"Rate limit hit (429). Retry-After: {wait_time}s. "
                f"Attempt {_attempt}/{MAX_RETRIES}"
            )

            if _attempt < MAX_RETRIES:
                time.sleep(wait_time)
                return self.fetch(
                    model=model,
                    endpoint=endpoint,
                    params=params,
                    expire_after=expire_after,
                    api_version=api_version,
                    _attempt=_attempt + 1,
                    _refreshed=_refreshed,
                )
            
            res.raise_for_status()

        # ============================================================
        # IMPROVEMENT 6: Auto-refresh on 401
        # ============================================================
        if res.status_code == 401:
            try:
                error_json = res.json()
                sub_status = error_json.get("subStatus")
                user_message = error_json.get("userMessage", "")
            except:
                error_json = None
                sub_status = None
                user_message = ""
            
            # If it's a content error (Asset not ready), DO NOT refresh token
            if sub_status == 4005:
                log.debug(f"Asset not ready (401/4005): {user_message}. Skipping token refresh.")
                res.raise_for_status()

            log.warning(f"Received 401 Unauthorized. Attempting token refresh. Body: {res.text}")
            
            if not _refreshed and self._auto_refresh_token(force_refresh=True):
                return self.fetch(
                    model=model,
                    endpoint=endpoint,
                    params=params,
                    expire_after=expire_after,
                    api_version=api_version,
                    _attempt=_attempt, # Keep attempt count or reset? Resetting is safer if we trust refresh logic.
                    _refreshed=True,
                )
            
            # If refresh fails, raise error
            res.raise_for_status()

        # ============================================================
        # IMPROVEMENT 7: Improved logging with more context
        # ============================================================
        cache_status = "HIT" if res.from_cache else "MISS"
        log.debug(
            f"[{api_version.upper()}] {endpoint} "
            f"params={params} "
            f"cache={cache_status} "
            f"status={res.status_code} "
            f"size={len(res.content) if res.content else 0}B"
        )

        # ============================================================
        # Parse JSON with better error handling
        # ============================================================
        try:
            data = res.json()
        except JSONDecodeError as e:
            if _attempt >= MAX_RETRIES:
                log.error(
                    f"JSON decode failed after {MAX_RETRIES} attempts\n"
                    f"Endpoint: {endpoint}\n"
                    f"Status: {res.status_code}\n"
                    f"Content preview: {res.text[:200]}"
                )
                raise ApiError(
                    status=res.status_code,
                    subStatus="0",
                    userMessage="Response body does not contain valid json.",
                )

            log.warning(f"JSON decode error, retrying {_attempt}/{MAX_RETRIES}")
            time.sleep(RETRY_DELAY)

            return self.fetch(
                model=model,
                endpoint=endpoint,
                params=params,
                expire_after=expire_after,
                api_version=api_version,
                _attempt=_attempt + 1,
                _refreshed=_refreshed,
            )

        # ============================================================
        # IMPROVEMENT 8: Improved debug with organized structure
        # ============================================================
        if self.debug_path:
            # Organize by API version
            debug_dir = self.debug_path / api_version
            file = debug_dir / f"{endpoint.replace('/', '_')}.json"
            file.parent.mkdir(parents=True, exist_ok=True)
            
            debug_data = {
                "timestamp": time.time(),
                "api_version": api_version,
                "status_code": res.status_code,
                "endpoint": endpoint,
                "params": params,
                "cache_hit": res.from_cache,
                "headers": dict(res.headers),
                "data": data,
            }
            
            file.write_text(json.dumps(debug_data, indent=2, default=str))

        # ============================================================
        # IMPROVEMENT 9: Logical error detection in 200 responses
        # ============================================================
        if res.status_code == 200 and isinstance(data, dict):
            # Detect embedded errors in successful responses
            if "error" in data:
                log.error(f"Logic error in 200 OK response: {data}")
                raise ApiError(
                    status=200,
                    subStatus="LogicError",
                    userMessage=str(data.get("error"))
                )
            
            # Detect error fields according to TIDAL documentation
            if "userMessage" in data and "status" in data and data["status"] != 200:
                log.error(f"TIDAL API error in response: {data}")
                raise ApiError(**data)

        if res.status_code != 200:
            # ============================================================
            # IMPROVEMENT 10: Specific logging by error code
            # ============================================================
            error_context = {
                "endpoint": endpoint,
                "params": params,
                "status": res.status_code,
                "data": data,
            }
            
            if res.status_code == 404:
                log.debug(f"Resource not found: {error_context}")
            elif res.status_code == 403:
                log.warning(f"Forbidden (geo-blocked or premium only): {error_context}")
            elif res.status_code == 451:
                log.warning(f"Unavailable for legal reasons: {error_context}")
            elif res.status_code in [500, 502, 503, 504]:
                log.warning(f"Server error ({res.status_code}): {error_context}")
            else:
                log.error(f"API error: {error_context}")
            
            raise ApiError(**data)

        self._rate_limit_delay = max(0.0, self._rate_limit_delay - 0.1)
        return model.parse_obj(data)

    # ================================================================
    # IMPROVEMENT 11: Method to get usage statistics
    # ================================================================

    def get_cache_stats(self) -> dict[str, Any]:
        """Gets cache statistics"""
        # Validate if requests_cache is enabled and has a backend
        if not hasattr(self.session, 'cache'):
            return {"enabled": False}
            
        try:
            return {
                "cache_name": getattr(self.session.cache, 'db_path', 'unknown'),
                # Use responses.keys() or similar depending on the backend
                # Note: responses is usually a dict-like object
                "responses_cached": len(self.session.cache.responses) if hasattr(self.session.cache, 'responses') else 0,
            }
        except Exception as e:
            log.warning(f"Could not retrieve cache stats: {e}")
            return {"error": str(e)}

    # ================================================================
    # IMPROVEMENT 12: Method to selectively clear the cache
    # ================================================================

    def clear_cache(
        self,
        endpoints: Optional[list[str]] = None,
        older_than: Optional[int] = None  # Seconds
    ) -> None:
        """
        Selectively clears the cache
        
        Args:
            endpoints: List of endpoints to clear (None = all)
            older_than: Clear entries older than N seconds
        """
        if not hasattr(self.session, 'cache'):
            return

        if not endpoints and not older_than:
            self.session.cache.clear()
            log.info("Cache cleared completely")
            return
        
        # Clear by age
        if older_than:
            self.session.cache.remove_old_entries(older_than)
            
        # Clear by endpoints (more complex with requests-cache, requires iteration)
        if endpoints:
            # Note: This is a simplified implementation.
            # requests-cache uses hash keys, not direct URLs.
            # Precise cleaning by URL requires iterating all keys
            # or using delete_url if the backend supports it.
            try:
                for url in endpoints:
                    self.session.cache.delete(urls=[url])
                    # Also try with the full base URL if only the endpoint was passed
                    if not url.startswith("http"):
                         self.session.cache.delete(urls=[f"{API_V1_URL}/{url}", f"{API_V2_URL}/{url}"])
            except Exception as e:
                log.warning(f"Error clearing specific endpoints: {e}")


# TODO add token expiry check
# maybe refactor to aiohttp.ClientSession
class TidalClient(TidalClientImproved):
    """
    DEPRECATED: Use TidalClientImproved directly.
    This class exists only for backward compatibility.
    """
    def __init__(self, *args, **kwargs):
        import warnings
        warnings.warn(
            "TidalClient is deprecated. Use TidalClientImproved instead.",
            DeprecationWarning,
            stacklevel=2
        )
        super().__init__(*args, **kwargs)
