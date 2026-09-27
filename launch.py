#!/usr/bin/env python3
"""Start the existing THESIS app with an app-only Bitget DNS workaround.

Run: python3 ~/Downloads/Start-THESIS.py
Optional: --app-dir /path/to/thesis-agent, or --check for a connection test.

Only this Python process resolves api.bitget.com through Cloudflare's DNS over
HTTPS API. Other hosts use the original resolver. No system DNS, hosts file,
certificate store, installed app code, or machine-wide environment is changed.
The existing app still writes its normal paper-trading data in run-data.
Bitget URLs, HTTPS Host headers, SNI, and certificate verification stay intact.
Closing this process ends the workaround. Start with app.py to run normally.

DNS API documentation:
https://developers.cloudflare.com/1.1.1.1/encryption/dns-over-https/make-api-requests/dns-json/
"""

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import os
from pathlib import Path
import runpy
import socket
import ssl
import sys
import threading
import time
import urllib.request


BITGET_HOST = "api.bitget.com"
RESOLVERS = ("1.1.1.1", "1.0.0.1")
MAX_DNS_BYTES = 65_536


def read_dns(resolver):
    # The resolver's numeric address needs no hostname lookup. Python verifies
    # its HTTPS certificate against that address; no custom trust bypass.
    connection = http.client.HTTPSConnection(
        resolver, timeout=8, context=ssl.create_default_context()
    )
    try:
        connection.request(
            "GET", "/dns-query?name=" + BITGET_HOST + "&type=A",
            headers={"Accept": "application/dns-json", "User-Agent": "THESIS-DNS/1.0"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise OSError(f"DNS service returned HTTP {response.status}")
        raw = response.read(MAX_DNS_BYTES + 1)
        if len(raw) > MAX_DNS_BYTES:
            raise ValueError("DNS response exceeded the size limit")
        return json.loads(raw)
    finally:
        connection.close()


def parse_dns(payload):
    if payload.get("Status") != 0 or payload.get("TC"):
        raise ValueError("DNS service did not return a complete successful answer")
    records = payload.get("Answer", [])
    name, ttl, visited = BITGET_HOST, 300, set()
    for _ in range(10):
        if name in visited:
            raise ValueError("DNS alias loop")
        visited.add(name)
        matching = [r for r in records if str(r.get("name", "")).rstrip(".").lower() == name]
        addresses = []
        for record in matching:
            if record.get("type") != 1:
                continue
            address = ipaddress.IPv4Address(record["data"])
            if not address.is_global:
                raise ValueError("DNS returned a non-public Bitget address")
            addresses.append(str(address))
            ttl = min(ttl, max(0, int(record.get("TTL", 0))))
        if addresses:
            return tuple(dict.fromkeys(addresses)), ttl
        aliases = [r for r in matching if r.get("type") == 5]
        if len(aliases) != 1:
            raise ValueError("DNS did not return an IPv4 address for Bitget")
        ttl = min(ttl, max(0, int(aliases[0].get("TTL", 0))))
        name = str(aliases[0]["data"]).rstrip(".").lower()
    raise ValueError("DNS alias chain is too long")


class BitgetResolver:
    def __init__(self, original, fetch=read_dns, clock=time.monotonic):
        self.original, self.fetch, self.clock = original, fetch, clock
        self.addresses, self.expires = (), 0.0
        self.lock = threading.Lock()

    def resolve(self):
        with self.lock:
            if self.addresses and self.clock() < self.expires:
                return self.addresses
            errors = []
            for resolver in RESOLVERS:
                try:
                    # Count lookup time toward TTL; never extend stale answers.
                    started = self.clock()
                    addresses, ttl = parse_dns(self.fetch(resolver))
                    self.addresses, self.expires = addresses, started + ttl
                    return addresses
                except (OSError, ValueError, TypeError, KeyError, AttributeError, http.client.HTTPException) as exc:
                    errors.append(f"{resolver}: {exc}")
            raise socket.gaierror(socket.EAI_AGAIN, "THESIS Bitget DNS failed: " + "; ".join(errors))

    def __call__(self, host, port, family=0, type=0, proto=0, flags=0):
        # A narrowly scoped resolver hook, installed only in this process.
        # HTTPS continues to see api.bitget.com, not the returned IP address.
        if (host not in (BITGET_HOST, BITGET_HOST.encode())
                or port not in (443, "443", "https")
                or family not in (socket.AF_UNSPEC, socket.AF_INET)
                or type not in (0, socket.SOCK_STREAM)
                or proto not in (0, socket.IPPROTO_TCP)
                or flags & socket.AI_NUMERICHOST):
            return self.original(host, port, family, type, proto, flags)
        results = []
        for address in self.resolve():
            for af, kind, protocol, canonical, endpoint in self.original(
                    address, port, family, type, proto, flags | socket.AI_NUMERICHOST):
                results.append((af, kind, protocol,
                                BITGET_HOST if flags & socket.AI_CANONNAME else canonical,
                                endpoint))
        return results


def check_bitget():
    url = "https://api.bitget.com/api/v3/market/tickers?category=SPOT&symbol=RAAPLUSDT"
    print("Checking Bitget through the app-only connection...", flush=True)
    with urllib.request.urlopen(url, timeout=20) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Bitget response exceeded the size limit")
    result = json.loads(raw)
    if result.get("code") != "00000":
        raise ValueError("Bitget response: " + str(result.get("code")) + " " + str(result.get("msg", "")))
    rows = result.get("data", [])
    print(f"Bitget connection successful; {len(rows)} ticker(s) returned.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    app_dir = args.app_dir.expanduser().resolve()
    if not args.check and not (app_dir / "app.py").is_file():
        print(f"THESIS was not found at {app_dir}. Use --app-dir followed by its folder path.", flush=True)
        return 1
    original_resolver = socket.getaddrinfo
    original_cwd, original_argv, original_path = Path.cwd(), sys.argv[:], sys.path[:]
    defaults = {"THESIS_LLM_ENDPOINT": "http://127.0.0.1:11434/v1/chat/completions",
                "THESIS_LLM_MODEL": "qwen3:8b"}
    added_env = []
    socket.getaddrinfo = BitgetResolver(original_resolver)
    try:
        try:
            check_bitget()
        except (OSError, ValueError, http.client.HTTPException) as exc:
            if args.check:
                raise
            print("Bitget is not reachable yet: " + str(exc), flush=True)
            print("Opening the workspace; use Refresh inputs after connectivity returns.", flush=True)
        if args.check:
            return 0
        for name, value in defaults.items():
            if name not in os.environ:
                os.environ[name] = value
                added_env.append(name)
        os.chdir(app_dir)  # Keep the existing app's run-data directory.
        sys.path.insert(0, str(app_dir))
        sys.argv = [str(app_dir / "app.py"), "--open"]
        print("Starting THESIS with local Qwen defaults. Mac DNS settings are unchanged.", flush=True)
        runpy.run_path(str(app_dir / "app.py"), run_name="__main__")
        return 0
    except KeyboardInterrupt:
        return 0
    except (OSError, ValueError, http.client.HTTPException) as exc:
        print(f"THESIS could not start: {exc}", flush=True)
        print("Copy this message back into the chat. No Mac network settings were changed.", flush=True)
        return 1
    finally:
        socket.getaddrinfo = original_resolver
        os.chdir(original_cwd)
        sys.argv, sys.path[:] = original_argv, original_path
        for name in added_env:
            os.environ.pop(name, None)


if __name__ == "__main__":
    sys.exit(main())
