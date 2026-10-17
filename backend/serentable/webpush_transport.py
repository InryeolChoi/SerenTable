"""Strict provider-only Web Push boundary. Network dispatch is opt-in."""

import base64
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from py_vapid import Vapid
from pywebpush import WebPushException, webpush
from requests import Response

# Official provider references are recorded in webpush-transport-contract.md.
PROVIDERS = frozenset({"fcm.googleapis.com", "updates.push.services.mozilla.com"})


def decode_key(value, length):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid_push_key")
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if len(decoded) != length or base64.urlsafe_b64encode(decoded).decode().rstrip("=") != value:
        raise ValueError("invalid_push_key")
    return decoded


def validate_endpoint(endpoint):
    if (
        not isinstance(endpoint, str)
        or len(endpoint) > 4096
        or any(ord(c) <= 32 or ord(c) == 127 or c == "\\" for c in endpoint)
    ):
        raise ValueError("invalid_push_endpoint")
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in PROVIDERS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
        or "#" in endpoint
        or not parsed.path
        or not endpoint.startswith("https://" + parsed.hostname)
    ):
        raise ValueError("invalid_push_endpoint")
    return parsed


def validate_subscription(value):
    validate_endpoint(value["endpoint"])
    decode_key(value["keys"]["auth"], 16)
    point = decode_key(value["keys"]["p256dh"], 65)
    if point[0] != 4:
        raise ValueError("invalid_push_key")
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    return value


def configuration():
    """Only environment key material is accepted; never interpret it as a file path."""
    raw = os.getenv("WEB_PUSH_VAPID_PRIVATE_KEY", "")
    subject = os.getenv("WEB_PUSH_VAPID_SUBJECT", "")
    if not raw or not subject.startswith("mailto:") or any(ord(c) < 33 for c in subject):
        return None
    try:
        decode_key(raw, 32)
        vapid = Vapid.from_raw(raw.encode("ascii"))
        public = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        return vapid, subject, base64.urlsafe_b64encode(public).decode().rstrip("=")
    except (ValueError, TypeError):
        return None


class PinnedSession:
    """Fresh DNS checks, fixed destination socket, original TLS name, no redirects/proxies."""

    def post(self, endpoint, *, data, headers, timeout):
        parsed = validate_endpoint(endpoint)
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses:
            raise ValueError("push_dns_rejected")
        for family, _, _, _, sockaddr in addresses:
            ip = ipaddress.ip_address(sockaddr[0])
            if (
                family not in (socket.AF_INET, socket.AF_INET6)
                or not ip.is_global
                or ip.is_multicast
                or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None)
            ):
                raise ValueError("push_dns_rejected")
        family, socktype, proto, _, sockaddr = addresses[0]
        raw = socket.socket(family, socktype, proto)
        conn = http.client.HTTPSConnection(parsed.hostname, timeout=min(timeout, 10))
        try:
            raw.settimeout(min(timeout, 10))
            raw.connect(sockaddr)
            conn.sock = ssl.create_default_context().wrap_socket(
                raw, server_hostname=parsed.hostname
            )
            path = parsed.path + ("?" + parsed.query if parsed.query else "")
            conn.request("POST", path, body=data, headers=headers)
            reply = conn.getresponse()
            result = Response()
            result.status_code = reply.status
            result.reason = "provider_response"
            result.headers = dict(reply.getheaders())
            # Provider response bodies can contain endpoint secrets: discard them.
            result._content = b""
            return result
        finally:
            conn.close()
            raw.close()


def send_push(subscription, session=None):
    config = configuration()
    if config is None:
        return "server_unconfigured"
    if session is None and os.getenv("WEB_PUSH_NETWORK_ENABLED") != "true":
        return "network_disabled"
    try:
        validate_subscription(subscription)
        response = webpush(
            subscription,
            data=json.dumps(
                {
                    "title": "우연한 식탁",
                    "body": "새 안내가 도착했습니다. 앱에서 확인해 주세요.",
                    "url": "/participant/gatherings",
                }
            ),
            vapid_private_key=config[0],
            vapid_claims={"sub": config[1]},
            requests_session=session if session is not None else PinnedSession(),
            timeout=10,
            ttl=3600,
        )
        return "accepted" if response.status_code in (200, 201, 202) else "provider_failed"
    except WebPushException as error:
        if error.response is not None and error.response.status_code in (404, 410):
            return "subscription_expired"
        return "provider_failed"
    except Exception:
        # Exception strings may contain keys/endpoint; only this fixed code leaves the boundary.
        return "transport_failed"
