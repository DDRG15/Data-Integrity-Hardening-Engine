"""Maps probe status codes to the fallback module that should be tried next."""

FALLBACK_MAP: dict[str, str] = {
    "http_403": "curl_cffi",
    "http_521": "curl_cffi",   # Cloudflare origin-down; sometimes bypassed by TLS fingerprinting
    "ssl_error": "curl_cffi",
    "http_429": "delay_retry",
    "timeout":  "delay_retry",
    "js_required": "playwright",
    # http_401: terminal -- site requires credentials, no fallback resolves this
    # connection_error: terminal -- DNS/network failure
}
