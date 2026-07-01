"""Security hardening regressions for the engine's untrusted-input surfaces. The FCR-safety of the verdict is
covered elsewhere; this pins the NON-verdict security guards: the outbound data-fetch SSRF/LFI guard (the URL
comes from untrusted search results), and points to the exec-sandbox + pip-arg guards proven in their own
suites."""
import os
import sys

_SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _SPIKE)

from runner import data_resolver as DR  # noqa: E402


def test_fetch_url_guard_blocks_non_http_schemes():
    for bad in ("file:///etc/passwd", "ftp://host/x.csv", "gopher://h/x", "data:text/plain,hi", "", "notaurl"):
        assert not DR._url_is_safe(bad), bad


def test_fetch_url_guard_blocks_internal_hosts():
    # IP literals + localhost resolve without external DNS
    for bad in ("http://127.0.0.1/x.csv", "https://169.254.169.254/latest/meta-data",   # cloud metadata
                "http://10.0.0.5/x.csv", "http://192.168.1.1/x", "http://[::1]/x", "http://localhost/x.csv"):
        assert not DR._url_is_safe(bad), bad


def test_fetch_url_guard_allows_a_public_https_host():
    # raw.githubusercontent.com is the intended fetch target; this needs DNS, so tolerate a resolver failure
    import socket
    try:
        socket.getaddrinfo("raw.githubusercontent.com", None)
    except socket.gaierror:
        return  # offline CI — the reject-path tests above still gate the guard
    assert DR._url_is_safe("https://raw.githubusercontent.com/o/r/main/data.csv")


def test_fetch_to_refuses_unsafe_url(tmp_path):
    # even called directly, a file:// URL must not be read to disk
    assert DR.fetch_to("file:///etc/hostname", str(tmp_path / "out")) is None
