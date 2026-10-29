import concurrent.futures
import ipaddress
import random
import socket
import struct
import time
from typing import Callable, List, Optional, Tuple
from alan_dpi.engine.models import ProfileNode


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

ACTIVE_EDGE_SUBNETS = [
    "172.64.148.0/24",
    "172.64.154.0/24",
    "172.64.155.0/24",
    "172.67.74.0/24",
    "104.16.132.0/24",
    "104.17.147.0/24",
    "104.18.32.0/24",
    "104.18.40.0/24",
    "162.159.135.0/24",
    "162.159.152.0/24",
    "188.114.96.0/24",
    "188.114.97.0/24",
    "108.162.192.0/24",
    "141.101.90.0/24",
    "198.41.209.0/24",
]

SEED_CLEAN_IPS = [
    "172.64.154.159",
    "172.64.155.88",
    "104.18.32.47",
    "162.159.135.42",
    "188.114.96.3",
    "141.101.90.96",
    "198.41.209.102",
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

    @staticmethod
    def is_domestic_or_direct_tunnel(node: ProfileNode) -> bool:
        if node.protocol.upper() == "SHADOWSOCKS":
            return True
        host_lower = (node.original_host or "").lower().strip()
        if host_lower.endswith(".ir"):
            return True
        return False

    @staticmethod
    def is_cdn_eligible(node: ProfileNode) -> bool:
        proto_upper = node.protocol.upper()
        uri_lower = node.uri.lower()
        if proto_upper == "SHADOWSOCKS":
            return False
        if "security=reality" in uri_lower:
            return False
        if "headertype=http" in uri_lower and ("type=tcp" in uri_lower):
            return False

        host_lower = (node.original_host or "").lower().strip()
        sni_lower = (node.sni or "").lower().strip()
        if host_lower.endswith(".ir"):
            return False

        if int(node.port) not in ALL_CLOUDFLARE_PORTS:
            return False

        for sfx in CDN_DOMAIN_SUFFIXES:
            if sni_lower.endswith(sfx) or host_lower.endswith(sfx):
                return True

        if CleanIpScanner.is_ip_in_cloudflare(node.original_host):
            return True

        try:
            resolved = socket.gethostbyname(node.original_host)
            if not CleanIpScanner.is_poisoned_ip(resolved):
                if CleanIpScanner.is_ip_in_cloudflare(resolved):
                    return True
        except Exception:
            return False

        return False

    @staticmethod
    def generate_candidate_pool(sample_count: int = 40) -> List[str]:
        candidates = list(SEED_CLEAN_IPS)
        per_subnet = max(2, (sample_count - len(candidates)) // len(ACTIVE_EDGE_SUBNETS) + 1)

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

    @staticmethod
    def _build_minimal_tls_probe() -> bytes:
        host = b"cloudflare.com"
        sni_entry = b"\x00" + struct.pack("!H", len(host)) + host
        sni_ext = struct.pack("!HH", 0x0000, len(sni_entry) + 2) + struct.pack("!H", len(sni_entry)) + sni_entry
        sup_ver = struct.pack("!HHBHH", 0x002B, 5, 4, 0x0304, 0x0303)
        exts = sni_ext + sup_ver

        random_bytes = b"\x11" * 32
        ciphers = struct.pack("!HHH", 4, 0x1301, 0xC02F)
        ch_body = (
            b"\x03\x03"
            + random_bytes
            + b"\x00"
            + ciphers
            + b"\x01\x00"
            + struct.pack("!H", len(exts))
            + exts
        )
        hs = b"\x01" + struct.pack("!I", len(ch_body))[1:] + ch_body
        return b"\x16\x03\x01" + struct.pack("!H", len(hs)) + hs

    @classmethod
    def fast_tcp_ping(cls, host: str, port: int = 443, timeout: float = 1.6) -> int:
        target = (host or "").strip()
        if not target:
            return -1
        try:
            resolved_ip = socket.gethostbyname(target)
            if cls.is_poisoned_ip(resolved_ip):
                return -1
        except Exception:
            return -1

        t0 = time.perf_counter()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
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
    def _deep_edge_verify(cls, ip: str, port: int = 443, timeout: float = 1.8) -> Optional[Tuple[int, int, int, str]]:
        is_plain_http = int(port) in CLOUDFLARE_HTTP_PORTS
        probe_pkt = (
            b"HEAD / HTTP/1.1\r\nHost: cloudflare.com\r\nConnection: close\r\n\r\n"
            if is_plain_http
            else cls._build_minimal_tls_probe()
        )
        samples = []

        for _ in range(2):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            t0 = time.perf_counter()
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.connect((ip, int(port)))
                sock.sendall(probe_pkt)
                rx = sock.recv(64)
                if not rx or len(rx) < 5:
                    return None
                if is_plain_http and (not rx.startswith(b"HTTP/")):
                    return None
                if (not is_plain_http) and (rx[0] not in (0x16, 0x15)):
                    return None
                samples.append(max(1, int((time.perf_counter() - t0) * 1000)))
            except Exception:
                return None
            finally:
                try:
                    sock.close()
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
        sample_count: int = 40,
        log_fn: Optional[Callable[[str], None]] = None,
        on_row_cb: Optional[Callable[[dict], None]] = None,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        abort_check: Optional[Callable[[], bool]] = None,
    ) -> List[Tuple[str, int]]:
        check_port = int(port) if int(port) in ALL_CLOUDFLARE_PORTS else 443
        pool_ips = cls.generate_candidate_pool(sample_count=sample_count)
        total_pool = max(1, len(pool_ips))
        if log_fn:
            log_fn(f"[CleanIP] Probing {len(pool_ips)} CIDR edge candidates on port {check_port}...")

        tcp_winners: List[Tuple[int, str]] = []
        done_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            fut_map = {executor.submit(cls.fast_tcp_ping, ip, check_port, 1.2): ip for ip in pool_ips}
            for fut in concurrent.futures.as_completed(fut_map):
                if abort_check and abort_check():
                    return []
                done_count += 1
                rtt = fut.result()
                ip_val = fut_map[fut]
                if rtt >= 0:
                    tcp_winners.append((rtt, ip_val))
                if progress_cb and ((done_count % 4 == 0) or (done_count == total_pool)):
                    pct = 10 + int((done_count / total_pool) * 50)
                    progress_cb(pct, f"پویش TCP رنج‌های IP تمیز ({done_count}/{total_pool})...")

        if not tcp_winners:
            return []

        tcp_winners.sort(key=lambda x: x[0])
        shortlist = tcp_winners[:12]
        total_short = max(1, len(shortlist))

        verified_edges: List[Tuple[int, int, int, str]] = []
        v_done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            fut_map = {
                executor.submit(cls._deep_edge_verify, ip, check_port, 1.8): (tcp_ms, ip)
                for tcp_ms, ip in shortlist
            }
            for fut in concurrent.futures.as_completed(fut_map):
                if abort_check and abort_check():
                    return []
                v_done += 1
                tcp_ms, ip_val = fut_map[fut]
                res = fut.result()
                if progress_cb:
                    pct = 60 + int((v_done / total_short) * 38)
                    progress_cb(pct, f"راستی‌آزمایی هندشیک و جیتر لبه ({v_done}/{total_short})...")
                if res:
                    score, edge_rtt, jitter, _ = res
                    verified_edges.append(res)
                    if on_row_cb:
                        rank_score = max(5, min(100, 100 - (score // 4)))
                        on_row_cb({
                            "scan_type": "clean_ip",
                            "rank": 0,
                            "item_id": ip_val,
                            "title": ip_val,
                            "category": "CDN_EDGE",
                            "endpoint": ip_val,
                            "tcp_ms": tcp_ms,
                            "tunnel_ms": edge_rtt,
                            "status": "CLEAN_VERIFIED",
                            "score": rank_score,
                            "detail": f"Handshake={edge_rtt}ms | Jitter={jitter}ms",
                        })

        if not verified_edges:
            return [(ip, rtt) for rtt, ip in tcp_winners[:top_n]]

        verified_edges.sort(key=lambda x: x[0])
        return [(ip, edge_rtt) for _, edge_rtt, _, ip in verified_edges[:top_n]]