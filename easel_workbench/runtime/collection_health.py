"""Content-free health check for the project's authenticated local service."""
import json
import urllib.error
import urllib.request


def site_health():
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request('http://127.0.0.1:9123/health', headers={'Host': 'leopc.tail2ce65.ts.net:8443'})
        try:
            with opener.open(request, timeout=8) as response:
                return response.headers.get('X-Desk-Architecture') == 'toolbox' and json.load(response).get('ok') is True
        except urllib.error.HTTPError as response:
            try:
                return response.code == 401 and response.headers.get('X-Desk-Architecture') == 'toolbox'
            finally:
                response.close()
    except (OSError, ValueError, urllib.error.URLError):
        return False
