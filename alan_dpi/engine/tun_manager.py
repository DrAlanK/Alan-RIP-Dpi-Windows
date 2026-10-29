import atexit
import ctypes
import io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import zipfile
from typing import Callable, Optional, Tuple
import requests


SINGBOX_PINNED_WIN64_URL = (
    "https://github.com/SagerNet/sing-box/releases/download/v1.11.15/sing-box-1.11.15-windows-amd64.zip"
)
SINGBOX_API_LATEST_URL = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"


def is_windows_admin() -> bool:
    if os.name != "nt":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def relaunch_as_admin() -> bool:
    if os.name != "nt":
        return False
    try:
        if getattr(sys, "frozen", False):
            exe_path = os.path.abspath(sys.executable)
            params = " ".join(f'"{a}"' for a in sys.argv[1:]).strip()
            work_dir = os.path.dirname(exe_path)
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe_path, params, work_dir, 1)
            return int(rc) > 32

        script = os.path.abspath(sys.argv[0])
        extra_args = " ".join(f'"{a}"' for a in sys.argv[1:])
        params = f'"{script}" {extra_args}'.strip()
        work_dir = os.path.dirname(script)
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, work_dir, 1)
        return int(rc) > 32
    except Exception:
        return False
class WinTunManager:
    ADAPTER_NAME = "AlanTUN"
    TUN_IP = "198.18.0.1"
    TUN_CIDR = "198.18.0.1/15"

    def __init__(
        self,
        core_dir: str,
        configs_dir: str,
        log_fn: Optional[Callable[[str], None]] = None,
        status_fn: Optional[Callable[[bool, str], None]] = None,
        progress_fn: Optional[Callable[[bool, int, str], None]] = None,
    ):
        self.core_dir = core_dir
        self.configs_dir = configs_dir
        self._log_fn = log_fn
        self._status_fn = status_fn
        self._progress_fn = progress_fn

        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._active = False
        self._physical_gw: str = ""
        self._bypassed_ips: set = set()

        atexit.register(self.stop)

    def _log(self, msg: str):
        if self._log_fn:
            self._log_fn(msg)

    def _emit_status(self, active: bool, detail: str):
        self._active = active
        if self._status_fn:
            self._status_fn(active, detail)

    def _emit_progress(self, active: bool, pct: int, msg: str):
        if self._progress_fn:
            self._progress_fn(active, pct, msg)

    @property
    def is_active(self) -> bool:
        return self._active and (self._proc is not None) and (self._proc.poll() is None)

    @staticmethod
    def _run_cmd(args: list, timeout: float = 5.0) -> str:
        try:
            res = subprocess.run(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            return res.stdout or ""
        except Exception:
            return ""

    def _detect_physical_gateway(self) -> str:
        out = self._run_cmd(["route", "print", "0.0.0.0"])
        for line in out.splitlines():
            parts = line.split()
            if (len(parts) >= 5) and (parts[0] == "0.0.0.0") and (parts[1] == "0.0.0.0"):
                gw = parts[2].strip()
                if gw and (gw != self.TUN_IP) and (not gw.startswith("198.18.")):
                    return gw
        return ""

    @staticmethod
    def _resolve_ipv4(host_or_ip: str) -> str:
        val = (host_or_ip or "").strip()
        if not val:
            return ""
        try:
            socket.inet_aton(val)
            return val
        except OSError:
            try:
                return socket.gethostbyname(val)
            except Exception:
                return ""

    def add_bypass_endpoint(self, host_or_ip: str):
        if os.name != "nt":
            return
        ip_addr = self._resolve_ipv4(host_or_ip)
        if (not ip_addr) or ip_addr.startswith("127.") or ip_addr.startswith("10.10.34."):
            return
        with self._lock:
            gw = self._physical_gw or self._detect_physical_gateway()
            if not gw:
                return
            self._physical_gw = gw
            if ip_addr in self._bypassed_ips:
                return
            self._run_cmd(["route", "add", ip_addr, "mask", "255.255.255.255", gw, "metric", "1"])
            self._bypassed_ips.add(ip_addr)
            self._log(f"[TUN] Added physical gateway bypass route for {ip_addr} via {gw}")

    def _clear_bypass_routes(self):
        if os.name != "nt":
            return
        for ip_addr in list(self._bypassed_ips):
            self._run_cmd(["route", "delete", ip_addr])
        self._bypassed_ips.clear()

    def _detect_singbox_version(self, sb_bin: str) -> Tuple[int, int]:
        out = self._run_cmd([sb_bin, "version"], timeout=3.0)
        match = re.search(r"version\s+(\d+)\.(\d+)", out)
        if match:
            return int(match.group(1)), int(match.group(2))
        return 1, 11

    def _download_singbox_binary(self, http_proxy_port: int) -> bool:
        sb_exe = os.path.join(self.core_dir, "sing-box.exe")
        if os.path.exists(sb_exe):
            return True

        proxies = {
            "http": f"http://127.0.0.1:{http_proxy_port}",
            "https": f"http://127.0.0.1:{http_proxy_port}",
        }
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = proxies
        sess.headers.update({"User-Agent": "Alan-RIP-Dpi/1.0.0"})

        candidate_urls = [SINGBOX_PINNED_WIN64_URL]
        try:
            self._emit_progress(True, 15, "دریافت هسته شبکه مجازی sing-box از طریق تونل...")
            self._log("[TUN] Provisioning sing-box.exe via active Xray tunnel...")
            try:
                meta_resp = sess.get(SINGBOX_API_LATEST_URL, timeout=10.0)
                if meta_resp.status_code == 200:
                    for asset in meta_resp.json().get("assets", []):
                        aname = str(asset.get("name", "")).lower()
                        if ("windows-amd64" in aname) and aname.endswith(".zip") and ("legacy" not in aname):
                            dl_url = asset.get("browser_download_url", "")
                            if dl_url and (dl_url not in candidate_urls):
                                candidate_urls.append(dl_url)
                            break
            except Exception:
                pass

            for zip_url in candidate_urls:
                try:
                    buf = io.BytesIO()
                    with sess.get(zip_url, stream=True, timeout=35.0) as r_dl:
                        r_dl.raise_for_status()
                        total_len = int(r_dl.headers.get("Content-Length", 0) or 0)
                        downloaded = 0
                        for chunk in r_dl.iter_content(chunk_size=65536):
                            if not chunk:
                                continue
                            buf.write(chunk)
                            downloaded += len(chunk)
                            if total_len > 0:
                                pct = 20 + int((downloaded / total_len) * 75)
                                self._emit_progress(True, min(95, pct), f"دانلود هسته sing-box ({downloaded // 1024} KB)...")

                    buf.seek(0)
                    with zipfile.ZipFile(buf) as zf:
                        for member in zf.namelist():
                            if member.lower().endswith("sing-box.exe"):
                                tmp_path = sb_exe + ".tmp"
                                with open(tmp_path, "wb") as out_f:
                                    out_f.write(zf.read(member))
                                os.replace(tmp_path, sb_exe)
                                self._emit_progress(False, 100, "هسته sing-box آماده شد")
                                self._log("[TUN] sing-box.exe provisioned successfully.")
                                return True
                except Exception as dl_err:
                    self._log(f"[TUN] Mirror attempt failed: {dl_err}")
                    continue
        finally:
            sess.close()

        self._emit_progress(False, 0, "خطا در دریافت خودکار sing-box.exe")
        return os.path.exists(sb_exe)

    def _build_singbox_tun_config(
        self,
        sb_bin: str,
        socks_port: int,
        endpoint_host: str,
        mtu: int,
        dns_server: str,
    ) -> dict:
        major, minor = self._detect_singbox_version(sb_bin)
        ep_ip = self._resolve_ipv4(endpoint_host)
        exclude_cidrs = [
            "127.0.0.0/8",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "169.254.0.0/16",
            "224.0.0.0/4",
        ]
        if ep_ip and (not ep_ip.startswith("127.")) and (not ep_ip.startswith("10.10.34.")):
            exclude_cidrs.append(f"{ep_ip}/32")

        tun_inbound = {
            "type": "tun",
            "tag": "tun-in",
            "interface_name": self.ADAPTER_NAME,
            "mtu": int(mtu),
            "auto_route": True,
            "strict_route": True,
            "route_exclude_address": exclude_cidrs,
            "stack": "system",
        }

        if (major > 1) or (major == 1 and minor >= 10):
            tun_inbound["address"] = [self.TUN_CIDR]
        else:
            tun_inbound["inet4_address"] = self.TUN_CIDR

        socks_outbound = {
            "type": "socks",
            "tag": "xray-out",
            "server": "127.0.0.1",
            "server_port": int(socks_port),
            "version": "5",
        }

        clean_dns = (dns_server or "1.1.1.1").strip()
        if (major > 1) or (major == 1 and minor >= 12):
            return {
                "log": {"level": "warn"},
                "dns": {
                    "servers": [
                        {
                            "type": "tcp",
                            "tag": "remote-dns",
                            "server": clean_dns,
                            "server_port": 53,
                            "detour": "xray-out",
                        }
                    ],
                    "final": "remote-dns",
                },
                "inbounds": [tun_inbound],
                "outbounds": [socks_outbound],
                "route": {
                    "auto_detect_interface": True,
                    "rules": [
                        {"action": "sniff"},
                        {"protocol": "dns", "action": "hijack-dns"},
                    ],
                    "final": "xray-out",
                },
            }

        if major == 1 and minor == 11:
            return {
                "log": {"level": "warn"},
                "dns": {
                    "servers": [
                        {
                            "tag": "remote-dns",
                            "address": f"tcp://{clean_dns}",
                            "detour": "xray-out",
                        }
                    ],
                    "final": "remote-dns",
                },
                "inbounds": [tun_inbound],
                "outbounds": [socks_outbound, {"type": "direct", "tag": "direct-out"}],
                "route": {
                    "auto_detect_interface": True,
                    "rules": [
                        {"action": "sniff"},
                        {"protocol": "dns", "action": "hijack-dns"},
                        {"ip_is_private": True, "outbound": "direct-out"},
                    ],
                    "final": "xray-out",
                },
            }

        tun_inbound["sniff"] = True
        tun_inbound["sniff_override_destination"] = False
        return {
            "log": {"level": "warn"},
            "dns": {
                "servers": [
                    {
                        "tag": "remote-dns",
                        "address": f"tcp://{clean_dns}",
                        "detour": "xray-out",
                    }
                ],
                "final": "remote-dns",
            },
            "inbounds": [tun_inbound],
            "outbounds": [
                socks_outbound,
                {"type": "direct", "tag": "direct-out"},
                {"type": "dns", "tag": "dns-out"},
            ],
            "route": {
                "auto_detect_interface": True,
                "rules": [
                    {"protocol": "dns", "outbound": "dns-out"},
                    {"ip_is_private": True, "outbound": "direct-out"},
                ],
                "final": "xray-out",
            },
        }

    def start(
        self,
        socks_port: int,
        http_port: int,
        endpoint_host: str,
        mtu: int = 1400,
        dns_server: str = "1.1.1.1",
        allow_download: bool = True,
    ) -> bool:
        if os.name != "nt":
            self._emit_status(False, "حالت TUN مختص سیستم‌عامل ویندوز است")
            return False

        if not is_windows_admin():
            self._log("[TUN] Administrator privileges required to start sing-box TUN.")
            self._emit_status(False, "نیاز به اجرای برنامه با دسترسی Administrator")
            return False

        self.stop()

        gw = self._detect_physical_gateway()
        if gw:
            self._physical_gw = gw

        sb_bin = os.path.join(self.core_dir, "sing-box.exe")
        if not os.path.exists(sb_bin):
            if not allow_download or (not self._download_singbox_binary(http_proxy_port=http_port)):
                self._emit_status(False, "فایل sing-box.exe در پوشه core یافت نشد")
                return False

        self.add_bypass_endpoint(endpoint_host)

        sb_cfg = self._build_singbox_tun_config(
            sb_bin=sb_bin,
            socks_port=socks_port,
            endpoint_host=endpoint_host,
            mtu=mtu,
            dns_server=dns_server,
        )
        cfg_file = os.path.join(self.configs_dir, "tun_singbox.json")
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(sb_cfg, f, indent=2)

        self._proc = subprocess.Popen(
            [sb_bin, "run", "-c", cfg_file],
            cwd=self.core_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        threading.Thread(target=self._pipe_singbox_logs, args=(self._proc,), daemon=True).start()

        time.sleep(1.1)
        if (self._proc is None) or (self._proc.poll() is not None):
            self.stop()
            self._emit_status(False, "خطا در راه‌اندازی رابط sing-box TUN")
            return False

        self._log(f"[TUN] Sing-box TUN interface '{self.ADAPTER_NAME}' online (-> SOCKS 127.0.0.1:{socks_port}).")
        self._emit_status(True, f"فعال ({self.ADAPTER_NAME} • Sing-box TUN)")
        return True

    def _pipe_singbox_logs(self, proc: subprocess.Popen):
        try:
            if proc.stdout:
                for line in iter(proc.stdout.readline, ""):
                    if not line:
                        break
                    clean = line.strip()
                    if clean:
                        self._log(f"[SingBox-TUN] {clean}")
        except Exception:
            pass

    def stop(self):
        with self._lock:
            proc_ref = self._proc
            self._proc = None

        if proc_ref:
            try:
                proc_ref.terminate()
                proc_ref.wait(timeout=1.2)
            except Exception:
                try:
                    proc_ref.kill()
                except Exception:
                    pass

        self._clear_bypass_routes()
        if self._active:
            self._log("[TUN] TUN interface stopped and routes restored.")
        self._emit_status(False, "غیرفعال")