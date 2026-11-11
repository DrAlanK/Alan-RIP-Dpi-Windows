import base64
import concurrent.futures
import ctypes
import json
import os
import socket
import ssl
import struct
import subprocess
import threading
import time
import urllib.parse
from typing import Callable, Dict, List, Optional, Tuple
import requests

from alan_dpi.engine.mutator import TlsByteMutator


DEFAULT_DOH_REPOSITORIES: List[Dict[str, str]] = [
    {"name": "Cloudflare Primary", "url": "https://cloudflare-dns.com/dns-query", "category": "Global Anycast"},
    {"name": "Cloudflare 1.1.1.1", "url": "https://1.1.1.1/dns-query", "category": "Direct IP DoH"},
    {"name": "Cloudflare 1.0.0.1", "url": "https://1.0.0.1/dns-query", "category": "Direct IP DoH"},
    {"name": "Cloudflare Security", "url": "https://security.cloudflare-dns.com/dns-query", "category": "Security"},
    {"name": "Cloudflare Mozilla", "url": "https://mozilla.cloudflare-dns.com/dns-query", "category": "Privacy"},
    {"name": "Google Public DNS", "url": "https://dns.google/dns-query", "category": "Global Anycast"},
    {"name": "Google Direct 8888", "url": "https://8.8.8.8/dns-query", "category": "Direct IP DoH"},
    {"name": "Google Direct 8844", "url": "https://8.8.4.4/dns-query", "category": "Direct IP DoH"},
    {"name": "Quad9 Secured", "url": "https://dns.quad9.net/dns-query", "category": "Security & Privacy"},
    {"name": "Quad9 Direct 9.9.9.9", "url": "https://9.9.9.9:5053/dns-query", "category": "Direct IP DoH"},
    {"name": "Quad9 Unsecured", "url": "https://dns10.quad9.net/dns-query", "category": "Unfiltered"},
    {"name": "ControlD Unfiltered", "url": "https://freedns.controld.com/p0", "category": "Unfiltered"},
    {"name": "ControlD Anti-Malware", "url": "https://freedns.controld.com/p1", "category": "Security"},
    {"name": "ControlD Ads & Trackers", "url": "https://freedns.controld.com/p2", "category": "AdBlock"},
    {"name": "Mullvad Base DoH", "url": "https://dns.mullvad.net/dns-query", "category": "Privacy"},
    {"name": "Mullvad AdBlock DoH", "url": "https://adblock.dns.mullvad.net/dns-query", "category": "AdBlock"},
    {"name": "AdGuard Unfiltered", "url": "https://unfiltered.adguard-dns.com/dns-query", "category": "Unfiltered"},
    {"name": "AdGuard Default", "url": "https://dns.adguard-dns.com/dns-query", "category": "AdBlock"},
    {"name": "NextDNS Anycast", "url": "https://dns.nextdns.io/dns-query", "category": "Global Anycast"},
    {"name": "RethinkDNS Sky", "url": "https://sky.rethinkdns.com/dns-query", "category": "Anti-Censorship"},
    {"name": "Max-Bit RethinkDNS", "url": "https://max.rethinkdns.com/dns-query", "category": "Anti-Censorship"},
    {"name": "Cisco OpenDNS", "url": "https://doh.opendns.com/dns-query", "category": "Global Anycast"},
    {"name": "CleanBrowsing Security", "url": "https://doh.cleanbrowsing.org/doh/security-filter/", "category": "Security"},
    {"name": "Digitale Gesellschaft CH", "url": "https://dns.digitale-gesellschaft.ch/dns-query", "category": "Swiss Privacy"},
    {"name": "Switch.ch Teletext", "url": "https://dns.switch.ch/dns-query", "category": "Swiss Privacy"},
    {"name": "FFMUC German DoH", "url": "https://doh.ffmuc.net/dns-query", "category": "European Privacy"},
    {"name": "Applied Privacy AT", "url": "https://doh.applied-privacy.net/query", "category": "European Privacy"},
    {"name": "CIRA Canadian Shield", "url": "https://private.canadianshield.cira.ca/dns-query", "category": "Privacy"},
    {"name": "DNS.SB Anycast", "url": "https://doh.dns.sb/dns-query", "category": "Unfiltered"},
    {"name": "185.222.222.222 (DNS.SB)", "url": "https://185.222.222.222/dns-query", "category": "Direct IP DoH"},
    {"name": "Shecan Anti-Sanction", "url": "https://free.shecan.ir/dns-query", "category": "Anti-Sanction"},
    {"name": "Electro Anti-Sanction", "url": "https://electro.ir/dns-query", "category": "Anti-Sanction"},
    {"name": "Begzar Anti-Sanction", "url": "https://dns.begzar.ir/dns-query", "category": "Anti-Sanction"},
    {"name": "403.online DNS", "url": "https://dns.403.online/dns-query", "category": "Anti-Sanction"},
]

POISONED_ANSWERS = ("10.10.34.", "0.0.0.0", "127.0.0.", "198.18.")

BOOTSTRAP_HOST_IPS: Dict[str, str] = {
    "cloudflare-dns.com": "104.16.248.249",
    "security.cloudflare-dns.com": "104.16.248.249",
    "mozilla.cloudflare-dns.com": "104.16.248.249",
    "dns.google": "8.8.8.8",
    "dns.quad9.net": "9.9.9.9",
    "dns10.quad9.net": "9.9.9.10",
    "freedns.controld.com": "76.76.2.0",
    "dns.mullvad.net": "194.242.2.2",
    "adblock.dns.mullvad.net": "194.242.2.3",
    "unfiltered.adguard-dns.com": "94.140.14.140",
    "dns.adguard-dns.com": "94.140.14.14",
    "dns.nextdns.io": "45.90.28.0",
    "sky.rethinkdns.com": "104.21.83.62",
    "max.rethinkdns.com": "172.64.155.88",
    "doh.opendns.com": "208.67.222.222",
    "doh.cleanbrowsing.org": "185.228.168.9",
    "doh.dns.sb": "185.222.222.222",
}


class DohWireCodec:
    @staticmethod
    def build_dns_query(domain: str, qtype: int = 1) -> bytes:
        tx_id = os.urandom(2)
        header = tx_id + struct.pack("!HHHHH", 0x0100, 1, 0, 0, 0)
        qname = b"".join(
            struct.pack("!B", len(lbl)) + lbl.encode("ascii")
            for lbl in domain.strip(".").split(".")
            if lbl
        ) + b"\x00"
        return header + qname + struct.pack("!HH", qtype, 1)

    @staticmethod
    def parse_a_records_from_wire(packet: bytes) -> List[str]:
        if len(packet) < 12:
            return []
        try:
            qdcount, ancount = struct.unpack("!HH", packet[4:8])
            if ancount <= 0:
                return []
            pos = 12
            for _ in range(qdcount):
                while pos < len(packet):
                    ln = packet[pos]
                    if ln == 0:
                        pos += 1
                        break
                    if (ln & 0xC0) == 0xC0:
                        pos += 2
                        break
                    pos += 1 + ln
                pos += 4

            ips: List[str] = []
            for _ in range(ancount):
                if pos >= len(packet):
                    break
                if (packet[pos] & 0xC0) == 0xC0:
                    pos += 2
                else:
                    while pos < len(packet) and packet[pos] != 0:
                        pos += 1 + packet[pos]
                    pos += 1
                if (pos + 10) > len(packet):
                    break
                rtype, rclass, _ttl, rdlen = struct.unpack("!HHIH", packet[pos : pos + 10])
                pos += 10
                if (pos + rdlen) > len(packet):
                    break
                if (rtype == 1) and (rclass == 1) and (rdlen == 4):
                    ip_str = socket.inet_ntoa(packet[pos : pos + 4])
                    ips.append(ip_str)
                pos += rdlen
            return ips
        except Exception:
            return []


class DohAntiDpiTransport:
    @staticmethod
    def resolve_host_ip(host: str) -> str:
        clean_h = (host or "").strip().lower()
        if not clean_h:
            return ""
        if clean_h[0].isdigit():
            return clean_h
        if clean_h in BOOTSTRAP_HOST_IPS:
            return BOOTSTRAP_HOST_IPS[clean_h]
        try:
            ip = socket.gethostbyname(clean_h)
            if not any(ip.startswith(p) for p in POISONED_ANSWERS):
                return ip
        except Exception:
            pass
        return clean_h

    @classmethod
    def query_doh_wire(
        cls,
        doh_url: str,
        wire_query: bytes,
        timeout: float = 2.8,
        use_anti_dpi_slicing: bool = True,
    ) -> Tuple[Optional[bytes], int, str]:
        parsed = urllib.parse.urlsplit(doh_url.strip())
        if parsed.scheme.lower() != "https" or (not parsed.hostname):
            return None, -1, "Invalid URL"

        host = parsed.hostname
        port = int(parsed.port or 443)
        path = parsed.path or "/dns-query"
        b64_dns = base64.urlsafe_b64encode(wire_query).decode("ascii").rstrip("=")
        sep = "&" if parsed.query else "?"
        full_path = f"{path}{('?' + parsed.query) if parsed.query else ''}{sep}dns={b64_dns}"

        target_ip = cls.resolve_host_ip(host)
        req_bytes = (
            f"GET {full_path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Accept: application/dns-message\r\n"
            f"User-Agent: Mozilla/5.0\r\n"
            f"Connection: close\r\n\r\n"
        ).encode("ascii", errors="ignore")

        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(timeout)
        t0 = time.perf_counter()
        try:
            raw_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            raw_sock.connect((target_ip, port))

            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            in_bio = ssl.MemoryBIO()
            out_bio = ssl.MemoryBIO()
            sni_name = None if host[0].isdigit() else host
            ssl_obj = ssl_ctx.wrap_bio(in_bio, out_bio, server_side=False, server_hostname=sni_name)

            first_flight = True
            while True:
                try:
                    ssl_obj.do_handshake()
                    pending = out_bio.read()
                    if pending:
                        raw_sock.sendall(pending)
                    break
                except ssl.SSLWantReadError:
                    pending = out_bio.read()
                    if pending:
                        if use_anti_dpi_slicing and first_flight and (len(pending) > 48) and (pending[0] == 0x16):
                            first_flight = False
                            hs = pending[5:]
                            frames = TlsByteMutator.reframe_handshake_chunks(
                                hs, [37, 2, 3, 5, 8], 0x0303, alternating_versions=(0x0301, 0x0303)
                            )
                            raw_sock.sendall(b"".join(frames[:3]))
                            raw_sock.sendall(b"".join(frames[3:]))
                        else:
                            raw_sock.sendall(pending)
                    rx = raw_sock.recv(16384)
                    if not rx:
                        return None, -1, "Handshake EOF"
                    in_bio.write(rx)

            ssl_obj.write(req_bytes)
            enc_req = out_bio.read()
            if enc_req:
                raw_sock.sendall(enc_req)

            resp_buf = bytearray()
            for _ in range(8):
                rx = raw_sock.recv(16384)
                if not rx:
                    break
                in_bio.write(rx)
                try:
                    while True:
                        dec = ssl_obj.read(8192)
                        if not dec:
                            break
                        resp_buf.extend(dec)
                except ssl.SSLWantReadError:
                    pass
                if b"\r\n\r\n" in resp_buf:
                    hdr_end = resp_buf.find(b"\r\n\r\n") + 4
                    hdr_text = bytes(resp_buf[:hdr_end]).decode("latin1", errors="ignore")
                    cl_val = -1
                    for line in hdr_text.splitlines():
                        if line.lower().startswith("content-length:"):
                            cl_val = int(line.split(":", 1)[1].strip())
                            break
                    if (cl_val >= 0) and (len(resp_buf) >= hdr_end + cl_val):
                        break

            rtt_ms = max(1, int((time.perf_counter() - t0) * 1000))
            if b"\r\n\r\n" not in resp_buf:
                return None, -1, "Incomplete HTTP"

            hdr_raw, body = bytes(resp_buf).split(b"\r\n\r\n", 1)
            status_line = hdr_raw.splitlines()[0].decode("latin1", errors="ignore")
            if " 200 " not in status_line:
                return None, -1, status_line[:24]

            if b"transfer-encoding: chunked" in hdr_raw.lower():
                body = cls._decode_chunked(body)

            return body, rtt_ms, "OK"
        except Exception as exc:
            return None, -1, str(exc)[:32]
        finally:
            try:
                raw_sock.close()
            except Exception:
                pass

    @staticmethod
    def _decode_chunked(data: bytes) -> bytes:
        out = bytearray()
        pos = 0
        while pos < len(data):
            rn = data.find(b"\r\n", pos)
            if rn == -1:
                break
            try:
                sz = int(data[pos:rn].split(b";")[0].strip(), 16)
            except ValueError:
                break
            if sz == 0:
                break
            start = rn + 2
            out.extend(data[start : start + sz])
            pos = start + sz + 2
        return bytes(out) if out else data


class DohVeilEngine:
    def __init__(self, configs_dir: str, log_fn: Optional[Callable[[str], None]] = None):
        self.configs_dir = configs_dir
        self._log_fn = log_fn
        self.custom_doh_path = os.path.join(configs_dir, "doh_repositories.json")
        self.custom_servers: List[Dict[str, str]] = self._load_custom_servers()

        self.veil_active = False
        self.active_doh_url = "https://cloudflare-dns.com/dns-query"
        self._udp_sock: Optional[socket.socket] = None
        self._tcp_sock: Optional[socket.socket] = None
        self._modified_adapters: List[str] = []
        self._dns_cache: Dict[Tuple[bytes, int], Tuple[float, bytes]] = {}
        self._lock = threading.RLock()

    def _log(self, msg: str):
        if self._log_fn is not None:
            self._log_fn(msg)

    def _load_custom_servers(self) -> List[Dict[str, str]]:
        if os.path.exists(self.custom_doh_path):
            try:
                with open(self.custom_doh_path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                    if isinstance(raw, list):
                        return [x for x in raw if isinstance(x, dict) and x.get("url")]
            except Exception:
                pass
        return []

    def _save_custom_servers(self):
        try:
            with open(self.custom_doh_path, "w", encoding="utf-8") as fh:
                json.dump(self.custom_servers, fh, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get_all_doh_Visual_list(self) -> List[Dict[str, str]]:
        combined: List[Dict[str, str]] = []
        seen = set()
        for item in (self.custom_servers + DEFAULT_DOH_REPOSITORIES):
            u = str(item.get("url") or "").strip()
            if u and (u not in seen):
                seen.add(u)
                combined.append({
                    "name": str(item.get("name") or urllib.parse.urlsplit(u).hostname or "DoH"),
                    "url": u,
                    "category": str(item.get("category") or "Custom"),
                })
        return combined

    def add_doh_entries(self, raw_text_or_url: str, title: str = "Custom DoH") -> int:
        txt = (raw_text_or_url or "").strip()
        if not txt:
            return 0

        if txt.startswith(("http://", "https://")) and ("\n" not in txt) and (not txt.endswith("/dns-query")) and ("raw.githubusercontent" in txt or txt.endswith(".txt") or txt.endswith(".json")):
            try:
                sess = requests.Session()
                sess.trust_env = False
                resp = sess.get(txt, timeout=10.0)
                sess.close()
                if resp.status_code == 200 and resp.text:
                    txt = resp.text
            except Exception:
                pass

        added = 0
        existing = {x.get("url") for x in self.get_all_doh_Visual_list()}
        for line in txt.splitlines():
            clean = line.strip()
            if not clean or clean.startswith("#"):
                continue
            for m in urllib.parse.urlsplit(clean) and [clean]:
                if clean.startswith("https://") and ("/" in clean[8:]):
                    if clean not in existing:
                        host_lbl = urllib.parse.urlsplit(clean).hostname or title
                        self.custom_servers.insert(0, {
                            "name": f"{title} ({host_lbl})" if title != "Custom DoH" else host_lbl,
                            "url": clean,
                            "category": "User Added",
                        })
                        existing.add(clean)
                        added += 1
        if added > 0:
            self._save_custom_servers()
            self._log(f"[DoH] Added {added} new DoH endpoint(s) to repository.")
        return added

    @classmethod
    def probe_single_doh(cls, entry: Dict[str, str], target_domain: str = "www.youtube.com") -> dict:
        url = str(entry.get("url") or "").strip()
        name = str(entry.get("name") or "DoH Server")
        cat = str(entry.get("category") or "General")

        q_yt = DohWireCodec.build_dns_query(target_domain, qtype=1)
        q_gh = DohWireCodec.build_dns_query("github.com", qtype=1)

        resp1, rtt1, det1 = DohAntiDpiTransport.query_doh_wire(url, q_yt, timeout=2.8, use_anti_dpi_slicing=True)
        if not resp1:
            return {
                "scan_type": "doh",
                "name": name,
                "url": url,
                "category": cat,
                "ping_ms": -1,
                "resolved_ip": "---",
                "unblocks": "---",
                "status": "FAILED",
                "verified": False,
                "score": 0.0,
                "detail": det1,
            }

        yt_ips = DohWireCodec.parse_a_records_from_wire(resp1)
        clean_yt = [ip for ip in yt_ips if not any(ip.startswith(p) for p in POISONED_ANSWERS)]
        if not clean_yt:
            return {
                "scan_type": "doh",
                "name": name,
                "url": url,
                "category": cat,
                "ping_ms": rtt1,
                "resolved_ip": yt_ips[0] if yt_ips else "Poisoned",
                "unblocks": "POISONED",
                "status": "POISONED",
                "verified": False,
                "score": 0.0,
                "detail": "DNS Poisoned / Empty",
            }

        resp2, rtt2, _ = DohAntiDpiTransport.query_doh_wire(url, q_gh, timeout=2.5, use_anti_dpi_slicing=True)
        gh_ips = DohWireCodec.parse_a_records_from_wire(resp2) if resp2 else []
        clean_gh = [ip for ip in gh_ips if not any(ip.startswith(p) for p in POISONED_ANSWERS)]

        avg_rtt = (rtt1 + rtt2) // 2 if (rtt2 > 0) else rtt1
        tags = ["YouTube"]
        if clean_gh:
            tags.append("GitHub")
        if cat == "Anti-Sanction":
            tags.append("Anti-Sanction")
        else:
            tags.append("Twitch/Kick")

        score = round(max(10.0, min(100.0, 100.0 - (avg_rtt * 0.18) + (8.0 if clean_gh else 0.0))), 1)
        return {
            "scan_type": "doh",
            "name": name,
            "url": url,
            "category": cat,
            "ping_ms": avg_rtt,
            "resolved_ip": clean_yt[0],
            "unblocks": " + ".join(tags),
            "status": "VERIFIED",
            "verified": True,
            "score": score,
            "detail": f"IP={clean_yt[0]} ({avg_rtt}ms)",
        }

    def scan_doh_repositories(
        self,
        on_row_cb: Optional[Callable[[dict], None]] = None,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        abort_check: Optional[Callable[[], bool]] = None,
    ) -> List[dict]:
        candidates = self.get_all_doh_Visual_list()
        total = max(1, len(candidates))
        self._log(f"[DoH] Scanning {total} DoH servers with Anti-DPI TLS Slicing...")

        results: List[dict] = []
        done = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
            fut_map = {pool.submit(self.probe_single_doh, item): item for item in candidates}
            for fut in concurrent.futures.as_completed(fut_map):
                if (abort_check is not None) and abort_check():
                    break
                done += 1
                row = fut.result()
                results.append(row)
                if on_row_cb is not None:
                    on_row_cb(row)
                if progress_cb is not None:
                    pct = int((done / total) * 100)
                    progress_cb(pct, f"اسکن سرورهای DoH ضد تحریم و فیلتر ({done}/{total})...")

        results.sort(
            key=lambda r: (
                0 if r.get("verified") else 1,
                -float(r.get("score") or 0.0),
                int(r.get("ping_ms") or 99999) if int(r.get("ping_ms") or -1) > 0 else 99999,
            )
        )
        for rk, r in enumerate(results, 1):
            r["rank"] = f"#{rk}"
        return results

    def _resolve_dns_packet_via_doh(self, raw_query: bytes) -> Optional[bytes]:
        if len(raw_query) < 12:
            return None
        tx_id = raw_query[:2]
        cache_key = (raw_query[2:], 1)
        now = time.monotonic()

        with self._lock:
            cached = self._dns_cache.get(cache_key)
            if cached and (now - cached[0] < 180.0):
                return tx_id + cached[1][2:]
            doh_target = self.active_doh_url

        wire_req = b"\x00\x01" + raw_query[2:]
        resp_wire, _, _ = DohAntiDpiTransport.query_doh_wire(
            doh_target, wire_req, timeout=3.2, use_anti_dpi_slicing=True
        )
        if resp_wire and len(resp_wire) >= 12:
            with self._lock:
                self._dns_cache[cache_key] = (now, resp_wire)
            return tx_id + resp_wire[2:]
        return None

    def _udp_dns_loop(self, srv: socket.socket):
        while self.veil_active:
            try:
                data, addr = srv.recvfrom(4096)
                if not data:
                    continue
                threading.Thread(
                    target=self._handle_udp_dns_client,
                    args=(srv, data, addr),
                    daemon=True,
                ).start()
            except Exception:
                if not self.veil_active:
                    break

    def _handle_udp_dns_client(self, srv: socket.socket, data: bytes, addr):
        ans = self._resolve_dns_packet_via_doh(data)
        if ans:
            try:
                srv.sendto(ans, addr)
            except Exception:
                pass

    @staticmethod
    def _run_Elevated_cmd(cmd_str: str) -> bool:
        if os.name != "nt":
            return False
        try:
            is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            is_admin = False

        if is_admin:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd_str],
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=8.0,
            )
            return res.returncode == 0
        else:
            rc = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "powershell.exe",
                f'-NoProfile -WindowStyle Hidden -Command "{cmd_str}"',
                None,
                0,
            )
            time.sleep(1.2)
            return int(rc) > 32

    def activate_system_doh_veil(self, doh_url: str) -> Tuple[bool, str]:
        clean_u = (doh_url or "").strip()
        if not clean_u.startswith("https://"):
            return False, "آدرس DoH باید با https:// شروع شود."

        self.stop_system_doh_veil()
        with self._lock:
            self.active_doh_url = clean_u

        try:
            udp_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp_s.bind(("127.0.0.1", 53))
            self._udp_sock = udp_s
            self.veil_active = True
            threading.Thread(target=self._udp_dns_loop, args=(udp_s,), daemon=True).start()
            bind_ip = "127.0.0.1"
        except OSError:
            parsed_h = urllib.parse.urlsplit(clean_u).hostname or ""
            bind_ip = DohAntiDpiTransport.resolve_host_ip(parsed_h)
            if not bind_ip or not bind_ip[0].isdigit():
                bind_ip = "1.1.1.1"
            self.veil_active = True

        ps_set_dns = (
            "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.Name -notlike '*Alan*' -and $_.Name -notlike '*Loopback*' } | "
            f"ForEach-Object {{ Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ServerAddresses ('{bind_ip}','1.1.1.1') }}; "
            "Clear-DnsClientCache"
        )
        ok = self._run_Elevated_cmd(ps_set_dns)
        if ok:
            self._log(f"[DoH Veil] Active on Windows Network -> {clean_u} (Local Gateway: {bind_ip})")
            return True, f"DoH روی کارت شبکه ویندوز ست شد ({clean_u})"
        return False, "نیاز به تایید دسترسی Administrator برای تغییر DNS کارت شبکه ویندوز است."

    def stop_system_doh_veil(self) -> Tuple[bool, str]:
        was_active = self.veil_active
        self.veil_active = False
        if self._udp_sock is not None:
            try:
                self._udp_sock.close()
            except Exception:
                pass
            self._udp_sock = None

        if os.name == "nt" and was_active:
            ps_reset = (
                "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.Name -notlike '*Alan*' } | "
                "ForEach-Object { Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ResetServerAddresses }; "
                "Clear-DnsClientCache"
            )
            self._run_Elevated_cmd(ps_reset)
            self._log("[DoH Veil] Restored Windows network adapter DNS to automatic (DHCP).")
        return True, "تنظیمات DNS ویندوز به حالت خودکار (DHCP) بازگردانده شد."
