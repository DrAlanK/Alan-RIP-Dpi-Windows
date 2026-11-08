import concurrent.futures
import ipaddress
import random
import socket
import ssl
import time
from typing import Callable, Dict, List, Optional, Set, Tuple
import requests
from alan_dpi.engine.models import ProfileNode
from alan_dpi.engine.mutator import TlsByteMutator


CLOUDFLARE_SUPERNETS = [
    ipaddress.ip_network("172.64.0.0/13"),
    ipaddress.ip_network("104.16.0.0/13"),
    ipaddress.ip_network("104.24.0.0/14"),
    ipaddress.ip_network("162.159.0.0/16"),
    ipaddress.ip_network("188.114.96.0/20"),
    ipaddress.ip_network("108.162.192.0/18"),
    ipaddress.ip_network("141.101.64.0/18"),
    ipaddress.ip_network("198.41.128.0/17"),
    ipaddress.ip_network("190.93.240.0/20"),
]

POISONED_DNS_PREFIXES = (
    "10.10.34.",
    "0.0.0.0",
    "127.",
    "198.18.",
)

NON_SWAPPABLE_PAAS_SUFFIXES = (
    ".railway.app",
    ".up.railway.app",
    ".onrender.com",
    ".fly.dev",
    ".koyeb.app",
    ".vercel.app",
    ".netlify.app",
    ".herokuapp.com",
    ".hf.space",
    ".huggingface.co",
    ".ondigitalocean.app",
    ".azurewebsites.net",
    ".run.app",
    ".appspot.com",
    ".cloudfront.net",
    ".fastly.net",
    ".akamaized.net",
    ".gcore.lu",
    ".edg.io",
    ".glitch.me",
    ".replit.dev",
    ".replit.app",
    ".deno.dev",
    ".supabase.co",
)

ACTIVE_EDGE_SUBNETS = [
    "172.64.148.0/24",
    "172.64.150.0/24",
    "172.64.152.0/24",
    "172.64.154.0/24",
    "172.64.155.0/24",
    "172.66.40.0/24",
    "172.66.43.0/24",
    "172.66.44.0/24",
    "172.66.47.0/24",
    "104.16.132.0/24",
    "104.17.147.0/24",
    "104.18.32.0/24",
    "104.18.38.0/24",
    "104.18.40.0/24",
    "104.19.144.0/24",
    "104.21.48.0/24",
    "104.24.112.0/24",
    "162.159.135.0/24",
    "162.159.137.0/24",
    "162.159.140.0/24",
    "188.114.96.0/24",
    "188.114.97.0/24",
    "188.114.98.0/24",
]

SEED_CLEAN_IPS = [
    "172.64.154.159",
    "172.64.155.88",
    "172.66.40.212",
    "172.66.43.118",
    "172.66.44.110",
    "104.18.32.47",
    "104.18.40.122",
    "104.19.144.33",
    "162.159.135.42",
    "162.159.140.98",
    "188.114.96.3",
    "188.114.97.3",
]

CDN_DOMAIN_SUFFIXES = (
    ".pages.dev",
    ".workers.dev",
    ".trycloudflare.com",
    ".cfargotunnel.com",
)

CLOUDFLARE_HTTP_PORTS = (80, 8080, 8880, 2052, 2082, 2086, 2095)
CLOUDFLARE_HTTPS_PORTS = (443, 2053, 2083, 2087, 2096, 8443)
ALL_CLOUDFLARE_PORTS = CLOUDFLARE_HTTPS_PORTS + CLOUDFLARE_HTTP_PORTS

_DOH_CACHE: Dict[str, str] = {}
_NON_SWAPPABLE_CNAME_HOSTS: Set[str] = set()
_DOH_CNAME_CHECKED: Set[str] = set()


class CleanIpScanner:
    @staticmethod
    def is_poisoned_ip(ip_str: str) -> bool:
        val = (ip_str or "").strip()
        if not val:
            return True
        return any(val.startswith(p) for p in POISONED_DNS_PREFIXES)

    @staticmethod
    def is_ip_in_cloudflare(ip_str: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip_str.strip())
            if addr.version != 4:
                return False
            return any(addr in net for net in CLOUDFLARE_SUPERNETS)
        except ValueError:
            return False

    @classmethod
    def is_paas_or_non_swappable(cls, host: str, sni: str = "") -> bool:
        for val in ((host or "").strip().lower(), (sni or "").strip().lower()):
            if not val:
                continue
            if val in _NON_SWAPPABLE_CNAME_HOSTS:
                return True
            if any(val.endswith(sfx) or (val == sfx.lstrip(".")) for sfx in NON_SWAPPABLE_PAAS_SUFFIXES):
                return True
        return False

    @classmethod
    def _query_doh_with_cnames(cls, clean_h: str, timeout: float = 2.0) -> str:
        doh_endpoints = (
            f"https://1.1.1.1/dns-query?name={clean_h}&type=A",
            f"https://8.8.8.8/resolve?name={clean_h}&type=A",
        )
        sess = requests.Session()
        sess.trust_env = False
        resolved_a = ""
        try:
            for url in doh_endpoints:
                try:
                    resp = sess.get(url, headers={"Accept": "application/dns-json"}, timeout=timeout)
                    if resp.status_code == 200:
                        answers = resp.json().get("Answer", [])
                        _DOH_CNAME_CHECKED.add(clean_h)
                        for ans in answers:
                            atype = int(ans.get("type", 0))
                            adata = str(ans.get("data", "")).strip().rstrip(".").lower()
                            if (atype == 5) and adata:
                                if any(adata.endswith(sfx) for sfx in NON_SWAPPABLE_PAAS_SUFFIXES):
                                    _NON_SWAPPABLE_CNAME_HOSTS.add(clean_h)
                            elif (atype == 1) and adata and (not cls.is_poisoned_ip(adata)) and (not resolved_a):
                                resolved_a = adata
                        if resolved_a:
                            _DOH_CACHE[clean_h] = resolved_a
                            return resolved_a
                except Exception:
                    continue
        finally:
            sess.close()
        return ""

    @classmethod
    def resolve_unpoisoned_ipv4(cls, host: str, timeout: float = 2.0) -> str:
        clean_h = (host or "").strip().lower()
        if not clean_h:
            return ""
        try:
            ipaddress.ip_address(clean_h)
            return clean_h
        except ValueError:
            pass

        if clean_h in _DOH_CACHE:
            return _DOH_CACHE[clean_h]

        try:
            local_ip = socket.gethostbyname(clean_h)
            if not cls.is_poisoned_ip(local_ip):
                _DOH_CACHE[clean_h] = local_ip
                return local_ip
        except Exception:
            pass

        return cls._query_doh_with_cnames(clean_h, timeout=timeout)

    @staticmethod
    def is_domestic_or_direct_tunnel(node: ProfileNode) -> bool:
        if node.protocol.upper() in ("SHADOWSOCKS", "SOCKS"):
            return True
        host_lower = (node.original_host or "").lower().strip()
        if host_lower.endswith(".ir"):
            return True
        return False

    @classmethod
    def is_cdn_eligible(cls, node: ProfileNode) -> bool:
        proto_upper = node.protocol.upper()
        uri_lower = node.uri.lower()
        if proto_upper in ("SHADOWSOCKS", "SOCKS"):
            return False
        if "security=reality" in uri_lower:
            return False
        if ("headertype=http" in uri_lower) and ("type=tcp" in uri_lower):
            return False

        host_lower = (node.original_host or "").lower().strip()
        sni_lower = (node.sni or "").lower().strip()
        if host_lower.endswith(".ir") or sni_lower.endswith(".ir"):
            return False

        if cls.is_paas_or_non_swappable(host_lower, sni_lower):
            return False

        if int(node.port) not in ALL_CLOUDFLARE_PORTS:
            return False

        for sfx in CDN_DOMAIN_SUFFIXES:
            if sni_lower.endswith(sfx) or host_lower.endswith(sfx):
                return True

        if cls.is_ip_in_cloudflare(host_lower):
            return True

        for domain_candidate in (host_lower, sni_lower):
            if (not domain_candidate) or cls.is_ip_in_cloudflare(domain_candidate):
                continue
            try:
                ipaddress.ip_address(domain_candidate)
                continue
            except ValueError:
                pass
            if domain_candidate not in _DOH_CNAME_CHECKED:
                cls._query_doh_with_cnames(domain_candidate, timeout=1.6)
            if domain_candidate in _NON_SWAPPABLE_CNAME_HOSTS:
                return False

        resolved = cls.resolve_unpoisoned_ipv4(host_lower, timeout=1.5)
        if resolved and cls.is_ip_in_cloudflare(resolved):
            return True

        if sni_lower and (sni_lower != host_lower):
            resolved_sni = cls.resolve_unpoisoned_ipv4(sni_lower, timeout=1.5)
            if resolved_sni and cls.is_ip_in_cloudflare(resolved_sni):
                return True

        return False

    @staticmethod
    def generate_candidate_pool(sample_count: int = 44) -> List[str]:
        candidates = list(SEED_CLEAN_IPS)
        per_subnet = max(2, ((sample_count - len(candidates)) // len(ACTIVE_EDGE_SUBNETS)) + 1)
        shuffled_subnets = list(ACTIVE_EDGE_SUBNETS)
        random.shuffle(shuffled_subnets)

        for cidr in shuffled_subnets:
            prefix = cidr.split("/")[0].rsplit(".", 1)[0]
            octets = random.sample(range(2, 253), k=min(per_subnet, 12))
            for last_octet in octets:
                ip_candidate = f"{prefix}.{last_octet}"
                if ip_candidate not in candidates:
                    candidates.append(ip_candidate)
                if len(candidates) >= sample_count:
                    break
            if len(candidates) >= sample_count:
                break
        return candidates[:sample_count]

    @classmethod
    def fast_tcp_ping(cls, host: str, port: int = 443, timeout: float = 1.5) -> int:
        target = (host or "").strip()
        if not target:
            return -1
        resolved_ip = cls.resolve_unpoisoned_ipv4(target, timeout=1.4)
        if not resolved_ip:
            return -1

        t0 = time.perf_counter()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.connect((resolved_ip, int(port)))
            return max(1, int((time.perf_counter() - t0) * 1000))
        except Exception:
            return -1
        finally:
            try:
                sock.close()
            except Exception:
                pass

    @classmethod
    def _tls_bio_trace_probe(cls, raw_sock: socket.socket, probe_sni: str, req_bytes: bytes) -> bytes:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        in_bio = ssl.MemoryBIO()
        out_bio = ssl.MemoryBIO()
        ssl_obj = ssl_ctx.wrap_bio(in_bio, out_bio, server_side=False, server_hostname=probe_sni)

        first_flight = True
        while True:
            try:
                ssl_obj.do_handshake()
                out_pending = out_bio.read()
                if out_pending:
                    raw_sock.sendall(out_pending)
                break
            except ssl.SSLWantReadError:
                out_pending = out_bio.read()
                if out_pending:
                    if first_flight and (len(out_pending) > 48) and (out_pending[0] == 0x16):
                        first_flight = False
                        hs = out_pending[5:]
                        frames = TlsByteMutator.reframe_handshake_chunks(hs, [37, 24, 32], 0x0303)
                        raw_sock.sendall(b"".join(frames[:2]))
                        raw_sock.sendall(b"".join(frames[2:]))
                    else:
                        raw_sock.sendall(out_pending)
                rx_wire = raw_sock.recv(16384)
                if not rx_wire:
                    return b""
                in_bio.write(rx_wire)

        ssl_obj.write(req_bytes)
        enc_req = out_bio.read()
        if enc_req:
            raw_sock.sendall(enc_req)

        plain_buf = bytearray()
        for _ in range(4):
            rx_wire = raw_sock.recv(8192)
            if not rx_wire:
                break
            in_bio.write(rx_wire)
            try:
                while True:
                    dec = ssl_obj.read(2048)
                    if not dec:
                        break
                    plain_buf.extend(dec)
            except ssl.SSLWantReadError:
                pass
            if b"fl=" in plain_buf:
                break
        return bytes(plain_buf)

    @classmethod
    def _deep_edge_verify(
        cls,
        ip: str,
        port: int = 443,
        probe_sni: str = "speed.cloudflare.com",
        timeout: float = 2.4,
    ) -> Optional[Tuple[int, int, int, str]]:
        is_plain_http = int(port) in CLOUDFLARE_HTTP_PORTS
        sni_host = probe_sni or "speed.cloudflare.com"
        req_bytes = (
            f"GET /cdn-cgi/trace HTTP/1.1\r\nHost: {sni_host}\r\nUser-Agent: Mozilla/5.0\r\nConnection: close\r\n\r\n"
        ).encode("ascii", errors="ignore")

        samples: List[int] = []
        for _ in range(2):
            raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw_sock.settimeout(timeout)
            t0 = time.perf_counter()
            try:
                raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                raw_sock.connect((ip, int(port)))
                if is_plain_http:
                    raw_sock.sendall(req_bytes)
                    rx = raw_sock.recv(1024)
                else:
                    rx = cls._tls_bio_trace_probe(raw_sock, sni_host, req_bytes)
                if (not rx) or (b"fl=" not in rx):
                    return None
                samples.append(max(1, int((time.perf_counter() - t0) * 1000)))
            except Exception:
                return None
            finally:
                try:
                    raw_sock.close()
                except Exception:
                    pass

        avg_rtt = sum(samples) // len(samples)
        jitter = abs(samples[1] - samples[0])
        score = avg_rtt + (jitter * 2)
        return score, avg_rtt, jitter, ip

    @classmethod
    def discover_best_ips(
        cls,
        port: int = 443,
        top_n: int = 5,
        sample_count: int = 44,
        probe_sni: str = "speed.cloudflare.com",
        log_fn: Optional[Callable[[str], None]] = None,
        on_row_cb: Optional[Callable[[dict], None]] = None,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        abort_check: Optional[Callable[[], bool]] = None,
    ) -> List[Tuple[str, int]]:
        check_port = int(port) if (int(port) in ALL_CLOUDFLARE_PORTS) else 443
        pool_ips = cls.generate_candidate_pool(sample_count=sample_count)
        total_pool = max(1, len(pool_ips))
        if log_fn is not None:
            log_fn(f"[CleanIP] Probing {len(pool_ips)} CIDR edge candidates on port {check_port}...")

        tcp_winners: List[Tuple[int, str]] = []
        done_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=22) as executor:
            fut_map = {executor.submit(cls.fast_tcp_ping, ip, check_port, 1.3): ip for ip in pool_ips}
            for fut in concurrent.futures.as_completed(fut_map):
                if (abort_check is not None) and abort_check():
                    return []
                done_count += 1
                rtt = fut.result()
                ip_val = fut_map[fut]
                if rtt >= 0:
                    tcp_winners.append((rtt, ip_val))
                if (progress_cb is not None) and ((done_count % 4 == 0) or (done_count == total_pool)):
                    pct = 10 + int((done_count / total_pool) * 50)
                    progress_cb(pct, f"پویش TCP رنج‌های IP تمیز ({done_count}/{total_pool})...")

        if not tcp_winners:
            return []

        tcp_winners.sort(key=lambda x: x[0])
        shortlist = tcp_winners[:14]
        total_short = max(1, len(shortlist))

        verified_edges: List[Tuple[int, int, int, str]] = []
        v_done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            fut_map = {
                executor.submit(cls._deep_edge_verify, ip, check_port, "speed.cloudflare.com", 2.4): (tcp_ms, ip)
                for tcp_ms, ip in shortlist
            }
            for fut in concurrent.futures.as_completed(fut_map):
                if (abort_check is not None) and abort_check():
                    return []
                v_done += 1
                tcp_ms, ip_val = fut_map[fut]
                res = fut.result()
                if progress_cb is not None:
                    pct = 60 + int((v_done / total_short) * 38)
                    progress_cb(pct, f"راستی‌آزمایی واقعی لبه CDN ({v_done}/{total_short})...")
                if res is not None:
                    score, edge_rtt, jitter, _ = res
                    verified_edges.append(res)
                    if on_row_cb is not None:
                        rank_score = max(5, min(100, 100 - (score // 4)))
                        on_row_cb({
                            "scan_type": "clean_ip",
                            "rank": 0,
                            "item_id": ip_val,
                            "title": ip_val,
                            "category": f"CDN_EDGE:{check_port}",
                            "endpoint": ip_val,
                            "tcp_ms": tcp_ms,
                            "tunnel_ms": edge_rtt,
                            "status": "CLEAN_VERIFIED",
                            "score": rank_score,
                            "detail": f"Trace={edge_rtt}ms | Jitter={jitter}ms",
                        })

        if not verified_edges:
            return [(ip, rtt) for rtt, ip in tcp_winners[:top_n]]

        verified_edges.sort(key=lambda x: x[0])
        return [(ip, edge_rtt) for _, edge_rtt, _, ip in verified_edges[:top_n]]
