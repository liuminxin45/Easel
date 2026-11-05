"""Probe the existing HTTPS ingress through public DNS, without tailnet/proxy shortcuts.

This observes transport only. It never changes Funnel, restarts an application,
follows redirects, or sends application credentials to a DNS provider.
"""
import http.client
import ipaddress
import json
import socket
import time
import urllib.parse
import urllib.request


RESOLVERS = ('https://dns.alidns.com/resolve', 'https://cloudflare-dns.com/dns-query')


def public_addresses(host, timeout=2):
    if not isinstance(host, str) or not host.endswith('.ts.net') or len(host) > 253:
        raise ValueError('invalid_public_ingress')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for resolver in RESOLVERS:
        try:
            query = urllib.parse.urlencode({'name': host, 'type': 'A'})
            request = urllib.request.Request(resolver + '?' + query, headers={'Accept': 'application/dns-json'})
            with opener.open(request, timeout=timeout) as response:
                raw = response.read(16385)
                if len(raw) > 16384 or response.status != 200:
                    continue
                value = json.loads(raw)
            if not isinstance(value, dict) or value.get('Status') != 0:
                continue
            addresses = []
            for row in value.get('Answer', [])[:32]:
                if not isinstance(row, dict) or row.get('type') != 1:
                    continue
                address = ipaddress.ip_address(row.get('data', ''))
                # Explicitly reject MagicDNS/CGNAT, loopback and private routes.
                if address.version == 4 and address.is_global and str(address) not in addresses:
                    addresses.append(str(address))
            if addresses:
                return addresses[:2]
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    raise OSError('public_dns_unavailable')


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, *, address, **kwargs):
        self.address = address
        super().__init__(host, **kwargs)

    def connect(self):
        if self._tunnel_host or not ipaddress.ip_address(self.address).is_global:
            raise OSError('public_route_required')
        raw = socket.create_connection((self.address, self.port), self.timeout, self.source_address)
        try:
            # Connect to the public IP but authenticate the original hostname.
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def public_opener(address):
    class PublicHTTPSHandler(urllib.request.HTTPSHandler):
        def https_open(self, request):
            def connection(host, **kwargs):
                return PublicHTTPSConnection(host, address=address, **kwargs)
            return self.do_open(connection, request, context=self._context)

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    return urllib.request.build_opener(urllib.request.ProxyHandler({}), PublicHTTPSHandler(), NoRedirect())


def probe_public_http(url, token, release, timeout=5, *, resolve=public_addresses):
    from .monitor import HEALTH_PATH, ingress_origin, probe_http
    started = time.monotonic()
    parsed = urllib.parse.urlsplit(url)
    ingress_origin(urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, '', '', '')))
    if parsed.path != HEALTH_PATH or parsed.query or parsed.fragment:
        raise ValueError('invalid_public_health_url')
    try:
        addresses = resolve(parsed.hostname)
    except (OSError, ValueError):
        return {'ok': False, 'reason': 'public_dns_unavailable', 'recoverable': False,
                'seconds': round(time.monotonic() - started, 4)}
    for address in addresses[:2]:
        result = probe_http(url, token, release, timeout, opener=public_opener(address))
        # Do not retry an identity/HTTP rejection as though it were a network failure.
        if result['ok'] or not result.get('recoverable'):
            break
    else:
        if not addresses:
            result = {'ok': False, 'reason': 'public_dns_unavailable', 'recoverable': False}
    result['seconds'] = round(time.monotonic() - started, 4)
    return result
