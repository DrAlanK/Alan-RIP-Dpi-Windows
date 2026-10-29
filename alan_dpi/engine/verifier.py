import os
import time
from dataclasses import dataclass
from typing import Callable, Optional
import requests


@dataclass
class VerificationReport:
    passed: bool
    ping_ms: int
    stage_failed: str
    detail: str


class TunnelStreamVerifier:
    @staticmethod
    def _create_isolated_session(http_port: int) -> requests.Session:
        proxy_url = f"http://127.0.0.1:{int(http_port)}"
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = {"http": proxy_url, "https": proxy_url}
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36",
            "Connection": "keep-alive",
        })
        return sess

    @classmethod
    def fast_probe(cls, http_port: int = 10809, timeout: float = 2.6) -> VerificationReport:
        sess = cls._create_isolated_session(http_port)
        urls = [
            "https://www.gstatic.com/generate_204",
            "http://cp.cloudflare.com/generate_204",
        ]
        try:
            for url in urls:
                t0 = time.perf_counter()
                try:
                    resp = sess.get(url, timeout=timeout, allow_redirects=False)
                    rtt = max(1, int((time.perf_counter() - t0) * 1000))
                    if resp.status_code in (200, 204):
                        return VerificationReport(True, rtt, "NONE", f"HTTP {resp.status_code} ({rtt}ms)")
                    if resp.status_code in (502, 503):
                        break
                except Exception:
                    continue
            return VerificationReport(False, -1, "INITIAL_PING", "Tunnel probe failed")
        finally:
            sess.close()

    @classmethod
    def quick_ping(cls, http_port: int = 10809, timeout: float = 3.8) -> VerificationReport:
        sess = cls._create_isolated_session(http_port)
        urls = [
            "https://www.gstatic.com/generate_204",
            "http://cp.cloudflare.com/generate_204",
            "https://www.youtube.com/generate_204",
        ]
        try:
            for url in urls:
                t0 = time.perf_counter()
                try:
                    resp = sess.get(url, timeout=timeout, allow_redirects=False)
                    rtt = max(1, int((time.perf_counter() - t0) * 1000))
                    if resp.status_code in (200, 204):
                        return VerificationReport(True, rtt, "NONE", f"HTTP {resp.status_code} ({rtt}ms)")
                    if (url.startswith("https://")) and (resp.status_code in (502, 503)):
                        break
                except Exception:
                    continue
            return VerificationReport(False, -1, "INITIAL_PING", "Tunnel probe timed out")
        finally:
            sess.close()

    @classmethod
    def run_full_qualification(
        cls,
        http_port: int = 10809,
        verify_upload: bool = True,
        require_youtube_6s: bool = True,
        base_rtt_ms: int = 350,
        abort_check: Optional[Callable[[], bool]] = None,
        log_fn: Optional[Callable[[str], None]] = None,
    ) -> VerificationReport:
        sess = cls._create_isolated_session(http_port)
        adaptive_timeout = max(5.2, min(10.0, ((max(200, int(base_rtt_ms)) / 1000.0) * 2.8) + 3.2))

        try:
            t0 = time.perf_counter()
            primary_url = "https://www.youtube.com/generate_204"
            init_rtt = -1

            for probe_url in ("https://www.youtube.com/generate_204", "https://www.gstatic.com/generate_204"):
                if (abort_check is not None) and abort_check():
                    return VerificationReport(False, -1, "ABORTED", "Cancelled")
                t_req = time.perf_counter()
                try:
                    r_init = sess.get(probe_url, timeout=adaptive_timeout, allow_redirects=False)
                    if r_init.status_code in (200, 204):
                        init_rtt = max(1, int((time.perf_counter() - t_req) * 1000))
                        primary_url = probe_url
                        break
                except Exception:
                    continue

            if init_rtt < 0:
                return VerificationReport(False, -1, "STAGE1_YT_INIT", "HTTPS stream blocked")

            if (abort_check is not None) and abort_check():
                return VerificationReport(False, -1, "ABORTED", "Cancelled")

            if verify_upload:
                pad_block = os.urandom(2048).hex()
                t_up = time.perf_counter()
                try:
                    for burst_idx in range(3):
                        if (abort_check is not None) and abort_check():
                            return VerificationReport(False, -1, "ABORTED", "Cancelled")
                        r_up = sess.get(
                            f"{primary_url}?b={burst_idx}",
                            headers={"X-Stream-Pad": pad_block},
                            timeout=adaptive_timeout,
                            allow_redirects=False,
                        )
                        if r_up.status_code not in (200, 204):
                            return VerificationReport(False, -1, "STAGE2_UPLINK", f"Uplink status {r_up.status_code}")
                    up_ms = max(1, int((time.perf_counter() - t_up) * 1000))
                    if log_fn is not None:
                        log_fn(f"[Verifier] 12KB Uplink burst verified in {up_ms}ms")
                except Exception:
                    return VerificationReport(False, -1, "STAGE2_UPLINK", "Uplink stalled under burst load")

            if not require_youtube_6s:
                return VerificationReport(True, init_rtt, "NONE", f"Verified ({init_rtt}ms)")

            elapsed = time.perf_counter() - t0
            end_mid = time.perf_counter() + max(0.2, 2.5 - elapsed)
            while time.perf_counter() < end_mid:
                if (abort_check is not None) and abort_check():
                    return VerificationReport(False, -1, "ABORTED", "Cancelled")
                time.sleep(0.15)

            try:
                r_mid = sess.get(primary_url, timeout=adaptive_timeout, allow_redirects=False)
                if r_mid.status_code not in (200, 204):
                    return VerificationReport(False, -1, "STAGE3_MID", f"Dropped at 2.5s ({r_mid.status_code})")
            except Exception:
                return VerificationReport(False, -1, "STAGE3_MID", "Stream dropped at 2.5s")

            elapsed_after_mid = time.perf_counter() - t0
            end_final = time.perf_counter() + max(0.4, 5.4 - elapsed_after_mid)
            while time.perf_counter() < end_final:
                if (abort_check is not None) and abort_check():
                    return VerificationReport(False, -1, "ABORTED", "Cancelled")
                time.sleep(0.15)

            t_fin = time.perf_counter()
            try:
                r_fin = sess.get(primary_url, timeout=adaptive_timeout, allow_redirects=False)
                if r_fin.status_code in (200, 204):
                    fin_rtt = max(1, int((time.perf_counter() - t_fin) * 1000))
                    avg_rtt = (init_rtt + fin_rtt) // 2
                    return VerificationReport(True, avg_rtt, "NONE", f"6s Stream + Uplink Stable ({avg_rtt}ms)")
                return VerificationReport(False, -1, "STAGE3_5S_KILL", f"Post-5s status {r_fin.status_code}")
            except Exception:
                return VerificationReport(False, -1, "STAGE3_5S_KILL", "Terminated at 5s mark by secondary DPI")

        finally:
            sess.close()

    @classmethod
    def resolve_egress_ip(cls, http_port: int = 10809, timeout: float = 5.0) -> str:
        sess = cls._create_isolated_session(http_port)
        try:
            r = sess.get("https://cloudflare.com/cdn-cgi/trace", timeout=timeout)
            if r.status_code == 200:
                for line in r.text.splitlines():
                    if line.startswith("ip="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass
        try:
            r2 = sess.get("http://api.ipify.org?format=json", timeout=timeout)
            if r2.status_code == 200:
                return str(r2.json().get("ip", "---"))
        except Exception:
            pass
        finally:
            sess.close()
        return "---"