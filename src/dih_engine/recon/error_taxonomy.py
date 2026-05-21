"""Maps probe status codes to the fallback module that should be tried next."""

FALLBACK_MAP: dict[str, str] = {
    "http_403": "curl_cffi",
    "ssl_error": "curl_cffi",
    "http_429": "delay_retry",
    "timeout": "delay_retry",
    "js_required": "playwright",
}
