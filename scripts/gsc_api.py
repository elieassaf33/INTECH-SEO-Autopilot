"""Bounded retries for read-only Google API operations; never log raw responses."""
import time
from requests.exceptions import ConnectionError, Timeout


class ApiError(RuntimeError):
    def __init__(self, status, reason):
        self.status = status
        self.reason = reason
        super().__init__(f"Google API HTTP {status}: {reason}")


def request(session, method, url, **kwargs):
    for attempt in range(3):
        try:
            response = getattr(session, method)(url, timeout=30, **kwargs)
        except (ConnectionError, Timeout):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
            continue
        status = response.status_code
        if isinstance(status, int) and status in (429, 500, 502, 503, 504) and attempt < 2:
            time.sleep(2 ** attempt)
            continue
        if isinstance(status, int) and status >= 400:
            # Do not persist API payloads, request headers, or credential errors.
            reason = {401: "authentication_required", 403: "permission_denied",
                      429: "quota_exhausted"}.get(status, "request_failed")
            raise ApiError(status, reason)
        response.raise_for_status()
        return response.json()


def error_status(exc):
    return {"status": "error", "http_status": getattr(exc, "status", None),
            "error_code": getattr(exc, "reason", "transport_or_credentials_error")}
