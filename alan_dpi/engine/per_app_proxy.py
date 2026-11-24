import ctypes
from ctypes import wintypes
import ipaddress
import os
import socket
import struct
import subprocess
import threading
try:
    threading.stack_size(131072)
except Exception:
    pass
import time
import urllib.parse
from typing import Callable, Dict, List, Optional, Set, Tuple


AF_INET = 2
AF_INET6 = 23
TCP_TABLE_OWNER_PID_ALL = 5
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _MIB_TCPROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("dwState", wintypes.DWORD),
        ("dwLocalAddr", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("dwRemoteAddr", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


class _MIB_TCP6ROW_OWNER_PID(ctypes.Structure):
    _fields_ = [
        ("ucLocalAddr", ctypes.c_ubyte * 16),
        ("dwLocalScopeId", wintypes.DWORD),
        ("dwLocalPort", wintypes.DWORD),
        ("ucRemoteAddr", ctypes.c_ubyte * 16),
        ("dwRemoteScopeId", wintypes.DWORD),
        ("dwRemotePort", wintypes.DWORD),
        ("dwState", wintypes.DWORD),
        ("dwOwningPid", wintypes.DWORD),
    ]


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


SYSTEM_NOISE_PROCESSES = {
    "system", "registry", "smss.exe", "csrss.exe", "wininit.exe", "services.exe",
    "lsass.exe", "svchost.exe", "fontdrvhost.exe", "dwm.exe", "sihost.exe",
    "taskhostw.exe", "ctfmon.exe", "conhost.exe", "dllhost.exe", "spoolsv.exe",
    "searchindexer.exe", "securityhealthservice.exe", "msmpeng.exe", "nissrv.exe",
    "audiodg.exe", "wudfhost.exe", "dashost.exe", "runtimebroker.exe",
    "applicationframehost.exe", "startmenuexperiencehost.exe", "textinputhost.exe",
    "widgetservice.exe", "alan-rip-dpi.exe", "xray.exe", "tun2socks.exe",
}

KNOWN_DESKTOP_APPS: List[Tuple[str, str, List[str]]] = [
    ("Telegram Desktop", "Telegram.exe", [r"%APPDATA%\Telegram Desktop\Telegram.exe"]),
    ("Discord", "Discord.exe", [r"%LOCALAPPDATA%\Discord\Update.exe"]),
    ("Google Chrome", "chrome.exe", [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe", r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"]),
    ("Brave Browser", "brave.exe", [r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe", r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"]),
    ("Microsoft Edge", "msedge.exe", [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe", r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"]),
    ("Mozilla Firefox", "firefox.exe", [r"%ProgramFiles%\Mozilla Firefox\firefox.exe"]),
    ("Visual Studio Code", "Code.exe", [r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe", r"%ProgramFiles%\Microsoft VS Code\Code.exe"]),
    ("Spotify", "Spotify.exe", [r"%APPDATA%\Spotify\Spotify.exe"]),
    ("Steam Client", "steam.exe", [r"%ProgramFiles(x86)%\Steam\steam.exe"]),
    ("Internet Download Manager", "IDMan.exe", [r"%ProgramFiles(x86)%\Internet Download Manager\IDMan.exe"]),
]


def _is_lan_or_local_host(host: str) -> bool:
    h = (host or "").strip().strip("[]").lower()
    if not h or h in ("localhost", "localhost.localdomain") or h.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast)
    except ValueError:
        return False


class WindowsProcessInspector:
    _cache_lock = threading.Lock()
    _proc_table_cache: Dict[int, Tuple[str, int, str]] = {}
    _proc_table_ts: float = 0.0
    _pid_path_cache: Dict[int, Tuple[float, str]] = {}

    @classmethod
    def _query_tcp_table(cls, family: int, target_port: int) -> Tuple[int, Set[int]]:
        matched_pid = -1
        all_pids: Set[int] = set()
        if os.name != "nt":
            return matched_pid, all_pids
        try:
            iphlpapi = ctypes.windll.iphlpapi
            size = wintypes.DWORD(0)
            iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0)
            if size.value <= 0:
                return -1, all_pids
            buf = ctypes.create_string_buffer(size.value)
            rc = iphlpapi.GetExtendedTcpTable(buf, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0)
            if rc != 0:
                return -1, all_pids

            num_entries = struct.unpack_from("<I", buf.raw, 0)[0]
            row_cls = _MIB_TCPROW_OWNER_PID if family == AF_INET else _MIB_TCP6ROW_OWNER_PID
            row_size = ctypes.sizeof(row_cls)
            offset = 4
            target_net_port = socket.htons(int(target_port)) if target_port > 0 else -1

            for _ in range(num_entries):
                if (offset + row_size) > size.value:
                    break
                row = row_cls.from_buffer_copy(buf.raw, offset)
                pid = int(row.dwOwningPid)
                if pid > 4:
                    all_pids.add(pid)
                if (target_net_port >= 0) and ((row.dwLocalPort & 0xFFFF) == target_net_port):
                    matched_pid = pid
                    if target_port > 0:
                        return matched_pid, all_pids
                offset += row_size
        except Exception:
            pass
        return matched_pid, all_pids

    @classmethod
    def get_pid_for_local_tcp_port(cls, client_port: int) -> int:
        if os.name != "nt" or client_port <= 0:
            return -1
        pid4, _ = cls._query_tcp_table(AF_INET, client_port)
        if pid4 > 4:
            return pid4
        pid6, _ = cls._query_tcp_table(AF_INET6, client_port)
        return pid6

    @classmethod
    def get_active_network_pids(cls) -> Set[int]:
        _, p4 = cls._query_tcp_table(AF_INET, 0)
        _, p6 = cls._query_tcp_table(AF_INET6, 0)
        return p4 | p6

    @classmethod
    def query_exe_path_by_pid(cls, pid: int) -> str:
        if os.name != "nt" or pid <= 4:
            return ""
        now = time.monotonic()
        with cls._cache_lock:
            cached = cls._pid_path_cache.get(pid)
            if cached and (now - cached[0]) < 20.0:
                return cached[1]
        kernel32 = ctypes.windll.kernel32
        h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h_proc:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            sz = wintypes.DWORD(1024)
            res = buf.value if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(sz)) else ""
            with cls._cache_lock:
                if len(cls._pid_path_cache) > 512:
                    cls._pid_path_cache.clear()
                cls._pid_path_cache[pid] = (now, res)
            return res
        finally:
            kernel32.CloseHandle(h_proc)

    @classmethod
    def snapshot_process_table(cls, use_cache: bool = True) -> Dict[int, Tuple[str, int, str]]:
        now = time.monotonic()
        if use_cache:
            with cls._cache_lock:
                if cls._proc_table_cache and ((now - cls._proc_table_ts) < 3.0):
                    return cls._proc_table_cache

        table: Dict[int, Tuple[str, int, str]] = {}
        if os.name != "nt":
            return table
        kernel32 = ctypes.windll.kernel32
        h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h_snap == -1 or h_snap is None:
            return table
        try:
            pe = _PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            if not kernel32.Process32FirstW(h_snap, ctypes.byref(pe)):
                return table
            while True:
                pid = int(pe.th32ProcessID)
                ppid = int(pe.th32ParentProcessID)
                exe_name = str(pe.szExeFile or "").strip()
                if pid > 4 and exe_name:
                    full_p = cls.query_exe_path_by_pid(pid)
                    table[pid] = (exe_name, ppid, full_p)
                if not kernel32.Process32NextW(h_snap, ctypes.byref(pe)):
                    break
        finally:
            kernel32.CloseHandle(h_snap)

        with cls._cache_lock:
            cls._proc_table_cache = table
            cls._proc_table_ts = now
        return table

    @classmethod
    def does_pid_match_target_set(cls, pid: int, target_tokens: Set[str]) -> Tuple[bool, str]:
        if pid <= 4:
            return False, ""

        full_p = cls.query_exe_path_by_pid(pid)
        base_name = os.path.basename(full_p).lower() if full_p else ""

        if not target_tokens:
            return False, base_name

        if full_p:
            low_full = full_p.lower()
            stem = os.path.splitext(base_name)[0]
            if (base_name in target_tokens) or (stem in target_tokens) or (low_full in target_tokens):
                return True, base_name

        proc_map = cls.snapshot_process_table(use_cache=True)
        cur_pid = pid
        visited = set()
        for _ in range(8):
            if (cur_pid <= 4) or (cur_pid in visited) or (cur_pid not in proc_map):
                break
            visited.add(cur_pid)
            exe_name, ppid, fpath = proc_map[cur_pid]
            low_exe = exe_name.lower()
            stem_exe = os.path.splitext(low_exe)[0]
            low_fp = (fpath or "").lower()
            if (low_exe in target_tokens) or (stem_exe in target_tokens) or (low_fp and (low_fp in target_tokens)):
                return True, low_exe
            cur_pid = ppid
        return False, base_name

    @classmethod
    def discover_user_applications(cls) -> List[Dict[str, str]]:
        apps: Dict[str, Dict[str, str]] = {}
        net_pids = cls.get_active_network_pids()

        for title, exe_name, candidate_paths in KNOWN_DESKTOP_APPS:
            low_k = exe_name.lower()
            found_path = ""
            for raw_p in candidate_paths:
                exp = os.path.expandvars(raw_p)
                if os.path.exists(exp):
                    found_path = exp
                    break
            if found_path:
                apps[low_k] = {
                    "name": title,
                    "exe": exe_name,
                    "path": found_path,
                    "status": "INSTALLED",
                    "category": "Desktop App",
                }

        proc_table = cls.snapshot_process_table(use_cache=False)
        for pid, (exe_name, _ppid, full_path) in proc_table.items():
            low_e = exe_name.lower()
            if low_e in SYSTEM_NOISE_PROCESSES:
                continue
            if full_path and any(
                sys_dir in full_path.lower()
                for sys_dir in (r"\windows\system32", r"\windows\syswow64", r"\windows\winsxs")
            ):
                continue
            has_net = pid in net_pids
            st_lbl = "ACTIVE_NET" if has_net else "RUNNING"

            if low_e in apps:
                if apps[low_e]["status"] != "ACTIVE_NET":
                    apps[low_e]["status"] = st_lbl
                if full_path and not apps[low_e].get("path"):
                    apps[low_e]["path"] = full_path
            else:
                nice_title = os.path.splitext(exe_name)[0].replace("-", " ").replace("_", " ").title()
                apps[low_e] = {
                    "name": nice_title,
                    "exe": exe_name,
                    "path": full_path or exe_name,
                    "status": st_lbl,
                    "category": "Active Network" if has_net else "Running App",
                }

        local_progs = os.path.expandvars(r"%LOCALAPPDATA%\Programs")
        if os.path.isdir(local_progs):
            try:
                for sub in os.listdir(local_progs):
                    sub_dir = os.path.join(local_progs, sub)
                    if not os.path.isdir(sub_dir):
                        continue
                    for fn in os.listdir(sub_dir):
                        if fn.lower().endswith(".exe") and (not fn.lower().startswith("unins")):
                            low_f = fn.lower()
                            if low_f not in apps and low_f not in SYSTEM_NOISE_PROCESSES:
                                apps[low_f] = {
                                    "name": os.path.splitext(fn)[0].title(),
                                    "exe": fn,
                                    "path": os.path.join(sub_dir, fn),
                                    "status": "INSTALLED",
                                    "category": "Installed App",
                                }
            except Exception:
                pass

        rank_map = {"ACTIVE_NET": 0, "RUNNING": 1, "INSTALLED": 2}
        result = list(apps.values())
        result.sort(
            key=lambda x: (
                rank_map.get(x.get("status", "INSTALLED"), 3),
                0 if x.get("category") == "Desktop App" else 1,
                x.get("name", "").lower(),
            )
        )
        return result


class PerAppSplitGateway:
    BUFFER_SIZE = 32768

    def __init__(self, log_fn: Optional[Callable[[str], None]] = None):
        self._log_fn = log_fn
        self.listen_port = 0
        self.upstream_http_port = 10809
        self.upstream_socks_port = 10808
        self.mode = "off"
        self.target_apps: Set[str] = set()
        self._physical_bind_ip: str = ""
        self.running = False
        self._server_sock: Optional[socket.socket] = None
        self._lock = threading.RLock()
        self.tunneled_count: int = 0
        self.bypassed_count: int = 0
        self._per_app_hits: Dict[str, Dict[str, int]] = {}

    def _log(self, msg: str):
        if self._log_fn is not None:
            self._log_fn(msg)

    def set_physical_bind_ip(self, bind_ip: str):
        with self._lock:
            self._physical_bind_ip = (bind_ip or "").strip()

    def get_stats(self) -> Dict[str, object]:
        with self._lock:
            return {
                "tunneled": int(self.tunneled_count),
                "bypassed": int(self.bypassed_count),
                "listen_port": int(self.listen_port),
                "per_app": {k: dict(v) for k, v in list(self._per_app_hits.items())[:40]},
            }

    def configure(self, mode: str, app_list: List[str], upstream_http_port: int, upstream_socks_port: int):
        clean_mode = (mode or "off").strip().lower()
        normalized_apps: Set[str] = set()
        for item in app_list or []:
            raw = str(item or "").strip().strip('"').lower()
            if not raw:
                continue
            normalized_apps.add(raw)
            base = os.path.basename(raw)
            if base:
                normalized_apps.add(base)
                normalized_apps.add(os.path.splitext(base)[0])

        with self._lock:
            self.mode = clean_mode
            self.target_apps = normalized_apps
            self.upstream_http_port = int(upstream_http_port)
            self.upstream_socks_port = int(upstream_socks_port)

    @staticmethod
    def sync_winhttp_proxy(enable: bool, port: int) -> bool:
        if os.name != "nt":
            return False
        try:
            if not bool(ctypes.windll.shell32.IsUserAnAdmin()):
                return False
            cmd = (
                ["netsh", "winhttp", "set", "proxy", f"127.0.0.1:{int(port)}", "bypass-list=localhost;127.*;10.*;192.168.*;*.ir;<local>"]
                if enable
                else ["netsh", "winhttp", "reset", "proxy"]
            )
            res = subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=4.0,
            )
            return res.returncode == 0
        except Exception:
            return False

    def start(self, preferred_port: int = 10811) -> int:
        if self.running and self._server_sock is not None:
            return self.listen_port
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", int(preferred_port)))
        except OSError:
            srv.bind(("127.0.0.1", 0))
        self.listen_port = int(srv.getsockname()[1])
        srv.listen(512)
        self._server_sock = srv
        self.running = True
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self.listen_port

    def stop(self):
        self.running = False
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except Exception:
                pass
            self._server_sock = None

    def _accept_loop(self):
        while self.running and self._server_sock is not None:
            try:
                client_sock, addr = self._server_sock.accept()
                threading.Thread(target=self._handle_client, args=(client_sock, addr), daemon=True).start()
            except Exception:
                if not self.running:
                    break

    def _record_app_hit(self, proc_name: str, is_tunneled: bool):
        key = (proc_name or "unknown").lower()
        with self._lock:
            if is_tunneled:
                self.tunneled_count += 1
            else:
                self.bypassed_count += 1
            bucket = self._per_app_hits.setdefault(key, {"tunneled": 0, "bypassed": 0})
            if is_tunneled:
                bucket["tunneled"] += 1
            else:
                bucket["bypassed"] += 1

    def _should_tunnel_client(self, client_port: int) -> Tuple[bool, str]:
        with self._lock:
            mode = self.mode
            if mode in ("off", "", "all") or (not self.target_apps):
                return True, ""
            targets = set(self.target_apps)

        pid = WindowsProcessInspector.get_pid_for_local_tcp_port(client_port)
        matched, exe_name = WindowsProcessInspector.does_pid_match_target_set(pid, targets)
        label = exe_name or (f"pid-{pid}" if pid > 0 else "unknown")
        if mode in ("include", "whitelist", "only_selected"):
            return matched, label
        if mode in ("exclude", "blacklist", "bypass_selected"):
            return (not matched), label
        return True, label

    def _dial_direct_bypass(self, host: str, port: int) -> socket.socket:
        with self._lock:
            bind_ip = self._physical_bind_ip
        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        remote.settimeout(7.0)
        if bind_ip and (not _is_lan_or_local_host(host)):
            try:
                remote.bind((bind_ip, 0))
            except Exception:
                pass
        remote.connect((host, int(port)))
        remote.settimeout(None)
        return remote

    def _handle_direct_socks5(self, client_sock: socket.socket, initial: bytes) -> Optional[socket.socket]:
        if len(initial) < 2 or initial[0] != 0x05:
            return None
        client_sock.sendall(b"\x05\x00")
        req = client_sock.recv(512)
        if len(req) < 7 or req[0] != 0x05 or req[1] != 0x01:
            return None
        atyp = req[3]
        if atyp == 0x01:
            host = socket.inet_ntoa(req[4:8])
            port = struct.unpack("!H", req[8:10])[0]
        elif atyp == 0x03:
            ln = req[4]
            host = req[5 : 5 + ln].decode("utf-8", errors="ignore")
            port = struct.unpack("!H", req[5 + ln : 7 + ln])[0]
        elif atyp == 0x04:
            host = socket.inet_ntop(socket.AF_INET6, req[4:20])
            port = struct.unpack("!H", req[20:22])[0]
        else:
            return None

        remote = self._dial_direct_bypass(host, port)
        client_sock.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
        return remote

    @staticmethod
    def _parse_http_target(initial_bytes: bytes) -> Tuple[str, int, bool]:
        try:
            first_line = initial_bytes.split(b"\r\n", 1)[0].decode("latin1", errors="ignore")
            parts = first_line.split(" ")
            if len(parts) < 2:
                return "", 0, False
            method = parts[0].upper()
            uri = parts[1]
            if method == "CONNECT":
                host, _, port_s = uri.partition(":")
                return host.strip("[]"), int(port_s or 443), True
            parsed = urllib.parse.urlsplit(uri)
            if parsed.hostname:
                return parsed.hostname, int(parsed.port or (443 if parsed.scheme == "https" else 80)), False
            for line in initial_bytes.split(b"\r\n")[1:12]:
                if line.lower().startswith(b"host:"):
                    h_val = line.split(b":", 1)[1].strip().decode("latin1", errors="ignore")
                    h_only, _, p_s = h_val.partition(":")
                    return h_only, int(p_s or 80), False
        except Exception:
            pass
        return "", 0, False

    def _handle_client(self, client_sock: socket.socket, addr):
        remote_sock: Optional[socket.socket] = None
        try:
            client_port = int(addr[1])
            use_tunnel, proc_tag = self._should_tunnel_client(client_port)
            client_sock.settimeout(7.0)
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            initial = client_sock.recv(16384)
            if not initial:
                return

            if use_tunnel and initial[0] not in (0x04, 0x05):
                t_host, _t_port, _is_c = self._parse_http_target(initial)
                if t_host and _is_lan_or_local_host(t_host):
                    use_tunnel = False

            self._record_app_hit(proc_tag, use_tunnel)

            if use_tunnel:
                with self._lock:
                    up_port = self.upstream_socks_port if (initial[0] in (0x04, 0x05)) else self.upstream_http_port
                remote_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                remote_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                remote_sock.settimeout(7.0)
                remote_sock.connect(("127.0.0.1", up_port))
                remote_sock.sendall(initial)
            else:
                if initial[0] == 0x05:
                    remote_sock = self._handle_direct_socks5(client_sock, initial)
                    if remote_sock is None:
                        return
                else:
                    host, port, is_connect = self._parse_http_target(initial)
                    if not host or port <= 0:
                        return
                    remote_sock = self._dial_direct_bypass(host, port)
                    if is_connect:
                        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    else:
                        remote_sock.sendall(initial)

            client_sock.settimeout(None)
            remote_sock.settimeout(None)

            def _pump(src: socket.socket, dst: socket.socket):
                try:
                    mv = memoryview(bytearray(self.BUFFER_SIZE))
                    while True:
                        n = src.recv_into(mv)
                        if not n:
                            break
                        dst.sendall(mv[:n])
                except Exception:
                    pass
                finally:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass

            t_down = threading.Thread(target=_pump, args=(remote_sock, client_sock), daemon=True)
            t_down.start()
            _pump(client_sock, remote_sock)
            t_down.join(timeout=8.0)
        except Exception:
            pass
        finally:
            for s in (client_sock, remote_sock):
                if s is not None:
                    try:
                        s.close()
                    except Exception:
                        pass

    @staticmethod
    def launch_app_through_tunnel(
        exe_path_or_name: str,
        http_port: int,
        socks_port: int,
        extra_args: str = "",
        restart_if_running: bool = True,
    ) -> Tuple[bool, str]:
        raw_target = (exe_path_or_name or "").strip().strip('"')
        if not raw_target:
            return False, "مسیر یا نام برنامه مشخص نشده است."

        resolved_path = os.path.expandvars(raw_target)
        exe_base = os.path.basename(resolved_path)

        if not os.path.exists(resolved_path):
            for _, known_exe, paths in KNOWN_DESKTOP_APPS:
                if known_exe.lower() == exe_base.lower():
                    for cand in paths:
                        exp = os.path.expandvars(cand)
                        if os.path.exists(exp):
                            resolved_path = exp
                            break
        if not os.path.exists(resolved_path):
            proc_map = WindowsProcessInspector.snapshot_process_table(use_cache=False)
            for _pid, (p_exe, _ppid, p_full) in proc_map.items():
                if p_exe.lower() == exe_base.lower() and p_full:
                    resolved_path = p_full
                    break

        if restart_if_running and os.name == "nt" and exe_base.lower().endswith(".exe"):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", exe_base],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=3.0,
                )
                time.sleep(0.45)
            except Exception:
                pass

        env = os.environ.copy()
        http_px = f"http://127.0.0.1:{int(http_port)}"
        socks_px = f"socks5://127.0.0.1:{int(socks_port)}"

        for k in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "GLOBAL_AGENT_HTTP_PROXY", "GLOBAL_AGENT_HTTPS_PROXY"):
            env[k] = http_px
        for k in ("ALL_PROXY", "all_proxy"):
            env[k] = socks_px
        env["NO_PROXY"] = "localhost,127.0.0.1,::1,*.local"
        env["no_proxy"] = env["NO_PROXY"]
        env["NODE_USE_ENV_PROXY"] = "1"
        env["ELECTRON_GET_USE_PROXY"] = "1"

        chromium_like = any(
            kw in exe_base.lower()
            for kw in (
                "code", "discord", "spotify", "chrome", "brave", "msedge",
                "opera", "vivaldi", "slack", "notion", "obsidian", "postman",
                "cursor", "windsurf", "claude", "chatgpt",
            )
        )

        cmd = [resolved_path]
        if exe_base.lower() == "update.exe" and "discord" in resolved_path.lower():
            cmd.extend(["--processStart", "Discord.exe"])

        if chromium_like:
            cmd.append(f"--proxy-server=http=127.0.0.1:{int(http_port)};https=127.0.0.1:{int(http_port)}")
            cmd.append("--proxy-bypass-list=<-loopback>")

        if extra_args.strip():
            cmd.extend(extra_args.strip().split())

        try:
            work_dir = os.path.dirname(resolved_path) if os.path.exists(resolved_path) else None
            subprocess.Popen(cmd, cwd=work_dir, env=env)
            return True, f"برنامه «{exe_base}» به‌صورت مستقیم روی تونل (پورت {http_port}) اجرا شد."
        except Exception as exc:
            return False, f"خطا در اجرای برنامه: {exc}"
