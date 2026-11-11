import base64
import concurrent.futures
import copy
import ctypes
import hashlib
import json
import os
import random
import threading
import time
import urllib.parse
from dataclasses import asdict
from typing import Any, Callable, Dict, List, Optional, Tuple
import requests

from alan_dpi.engine.bridge import FullDuplexMutatorBridge
from alan_dpi.engine.clean_ip import CleanIpScanner, SEED_CLEAN_IPS
from alan_dpi.engine.doh_shield import DohVeilEngine
from alan_dpi.engine.models import (
    BypassVector,
    EngineSettings,
    EngineState,
    LocationExtractor,
    ProfileNode,
    SubscriptionItem,
    TelemetrySnapshot,
    VECTOR_REGISTRY,
    VerifiedOutputItem,
    filter_vectors_by_mode,
    find_vector,
    format_byte_rate,
    format_uptime_hms,
)
from alan_dpi.engine.per_app_proxy import PerAppSplitGateway, WindowsProcessInspector
from alan_dpi.engine.tun_manager import WindowsXrayTunManager, is_windows_admin, relaunch_as_admin
from alan_dpi.engine.verifier import TunnelStreamVerifier
from alan_dpi.engine.xray_driver import UriConfigCodec, XrayProcessDriver


DEFAULT_BOOTSTRAP_URI = ""

HIDDEN_AUTO_SUB_URLS: List[str] = [
    "https://raw.githubusercontent.com/DrAlanK/Alan-RIP-Dpi/refs/heads/main/Alan-RIP-Dpi-Sub.txt"
]

FAST_LAB_VECTOR_IDS = [
    "VEC-21",
    "VEC-22",
    "VEC-23",
    "VEC-01",
    "VEC-18",
    "VEC-17",
    "VEC-19",
    "VEC-20",
    "VEC-04",
    "VEC-00",
]

CONNECTING_STATES = {
    EngineState.FAST_RESUME,
    EngineState.SCANNING_CLEAN_IP,
    EngineState.PROBING_VECTORS,
    EngineState.SCANNING_REPOSITORY,
    EngineState.HUNTING_BEST,
    EngineState.VERIFYING_STABILITY,
    EngineState.RECOVERING,
}

SETTING_KEY_ALIASES = {
    "ui_language": "language",
    "clean_ip": "auto_clean_ip",
    "auto_clean": "auto_clean_ip",
    "youtube_6s": "require_youtube_6s",
    "youtube_guard": "require_youtube_6s",
    "yt_guard": "require_youtube_6s",
    "upload_check": "verify_upload_stream",
    "verify_upload": "verify_upload_stream",
    "self_healing": "self_healing_watchdog",
    "watchdog": "self_healing_watchdog",
    "system_proxy": "system_proxy_enabled",
    "sys_proxy": "system_proxy_enabled",
    "autopilot": "autopilot_enabled",
    "auto_mode_enabled": "autopilot_enabled",
    "auto_pool": "auto_pool_enabled",
    "auto_pool_fallback": "auto_pool_enabled",
    "selected_auto_location": "preferred_auto_location",
    "auto_location": "preferred_auto_location",
    "location": "preferred_auto_location",
    "tun": "tun_enabled",
    "tray": "minimize_to_tray",
    "sub_update_hours": "sub_auto_update_hours",
}


def _decode_hidden_url(entry: str) -> str:
    val = (entry or "").strip()
    if not val:
        return ""
    if val.lower().startswith(("http://", "https://")):
        return val
    try:
        pad = (-len(val)) % 4
        dec = base64.b64decode(val + ("=" * pad)).decode("utf-8", errors="ignore").strip()
        if dec.lower().startswith(("http://", "https://")):
            return dec
    except Exception:
        pass
    return ""


class WindowsSystemProxy:
    @staticmethod
    def apply(enable: bool, http_port: int = 10809):
        if os.name != "nt":
            return
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
                if enable:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"127.0.0.1:{int(http_port)}")
                    winreg.SetValueEx(
                        key,
                        "ProxyOverride",
                        0,
                        winreg.REG_SZ,
                        "localhost;127.*;10.*;192.168.*;*.ir;<local>",
                    )
                else:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
            internet_set_option = ctypes.windll.Wininet.InternetSetOptionW
            internet_set_option(0, 39, 0, 0)
            internet_set_option(0, 37, 0, 0)
        except Exception:
            pass


class AlanAutoPilotEngine:
    def __init__(
        self,
        base_dir: str,
        on_telemetry: Optional[Callable[[dict], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
        on_profiles_changed: Optional[Callable[[List[dict]], None]] = None,
        on_settings_changed: Optional[Callable[[dict], None]] = None,
        on_scan_row: Optional[Callable[[dict], None]] = None,
        on_scan_ranked: Optional[Callable[[List[dict]], None]] = None,
        on_scan_progress: Optional[Callable[[int, str], None]] = None,
        on_scan_state: Optional[Callable[[bool, str], None]] = None,
        on_subscriptions_changed: Optional[Callable[[List[dict]], None]] = None,
        on_task_progress: Optional[Callable[[bool, int, str], None]] = None,
        on_tun_status: Optional[Callable[..., None]] = None,
        on_verified_outputs: Optional[Callable[[List[dict]], None]] = None,
    ):
        self.base_dir = base_dir
        self.core_dir = os.path.join(base_dir, "core")
        self.configs_dir = os.path.join(base_dir, "configs")
        self.logs_dir = os.path.join(base_dir, "logs")
        for folder in (self.core_dir, self.configs_dir, self.logs_dir):
            os.makedirs(folder, exist_ok=True)

        self.settings_path = os.path.join(self.configs_dir, "settings.json")
        self.repo_path = os.path.join(self.configs_dir, "repository.json")
        self.subs_path = os.path.join(self.configs_dir, "subscriptions.json")
        self.verified_path = os.path.join(self.configs_dir, "verified_outputs.json")
        self.hidden_cache_path = os.path.join(self.configs_dir, ".pool_cache.dat")
        self.pool_meta_path = os.path.join(self.configs_dir, ".pool_meta.json")

        self.on_telemetry = on_telemetry
        self.on_log = on_log
        self.on_profiles: Optional[Callable[[List[dict], int], None]] = None
        self._on_profiles_changed = on_profiles_changed
        self.on_verified_outputs = on_verified_outputs
        self.on_auto_locations: Optional[Callable[[List[dict], str], None]] = None
        self.on_settings = on_settings_changed
        self.on_subscriptions = on_subscriptions_changed
        self.on_scan_row = on_scan_row
        self.on_scan_ranked = on_scan_ranked
        self.on_scan_progress = on_scan_progress
        self.on_scan_state = on_scan_state
        self.on_task_progress = on_task_progress
        self.on_tun_status = on_tun_status
        self.on_request_quit: Optional[Callable[[], None]] = None

        self._state_lock = threading.RLock()
        self._repo_lock = threading.RLock()
        self._op_generation = 0
        self._abort_flag = False
        self._scan_abort_flag = False
        self._task_abort_flag = False
        self._scanner_running = False
        self._shutdown_flag = False
        self._worker_thread: Optional[threading.Thread] = None
        self._connected_since_ts: Optional[float] = None
        self._last_sub_auto_check: float = time.time()

        self.settings: EngineSettings = self._load_settings()
        if self.settings.tun_enabled and (not is_windows_admin()):
            self.settings.tun_enabled = False
            self._save_settings(self.settings)

        self.profiles: List[ProfileNode] = self._load_profiles()
        self.hidden_pool: List[ProfileNode] = self._load_hidden_pool_cache()
        self.verified_outputs: List[VerifiedOutputItem] = self._load_verified_outputs()
        self.subscriptions: List[SubscriptionItem] = self._load_subscriptions()
        self.selected_index: int = self._restore_persisted_selection()

        self.snapshot = TelemetrySnapshot(
            tun_enabled=self.settings.tun_enabled,
            system_proxy_enabled=self.settings.system_proxy_enabled,
            selected_index=max(0, self.selected_index),
        )
        self._persist_active_selection(save_disk=True)

        self.doh_engine = DohVeilEngine(configs_dir=self.configs_dir, log_fn=self.emit_log)
        self.per_app_gateway = PerAppSplitGateway(log_fn=self.emit_log)
        self.per_app_gateway.start(preferred_port=self.settings.http_port + 2)

        self.tun = WindowsXrayTunManager(core_dir=self.core_dir, log_fn=self.emit_log)
        self.bridge = FullDuplexMutatorBridge(
            listen_port=self.settings.bridge_port,
            log_fn=self.emit_log,
            on_endpoint_change=self._handle_bridge_endpoint_change,
        )
        self.bridge.start()

        self.xray = XrayProcessDriver(
            core_dir=self.core_dir,
            configs_dir=self.configs_dir,
            log_fn=self.emit_log,
        )
        self._sync_per_app_gateway()

        self._active_runtime_node: Optional[ProfileNode] = None
        self._active_runtime_vec: BypassVector = VECTOR_REGISTRY[0]
        self._prev_tx_bytes = 0
        self._prev_rx_bytes = 0
        self._prev_tick_ts = time.perf_counter()

        threading.Thread(target=self._telemetry_ticker_loop, daemon=True).start()
        threading.Thread(target=self._self_healing_watchdog_loop, daemon=True).start()
        threading.Thread(target=self._sync_hidden_auto_pool, daemon=True).start()

    def _parse_per_app_list(self) -> List[str]:
        raw = self.settings.per_app_list or ""
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        return [
            x.strip()
            for x in str(raw).replace(";", "\n").replace(",", "\n").splitlines()
            if x.strip()
        ]

    def _effective_system_proxy_port(self) -> int:
        p_mode = (self.settings.per_app_mode or "off").strip().lower()
        app_items = self._parse_per_app_list()
        if (p_mode in ("include", "exclude", "only_selected", "bypass_selected")) and app_items and (self.per_app_gateway.listen_port > 0):
            return self.per_app_gateway.listen_port
        return self.xray.active_http_port

    def _should_enable_global_wininet_proxy(self) -> bool:
        return bool(self.settings.system_proxy_enabled)

    def _sync_per_app_gateway(self):
        self.per_app_gateway.configure(
            mode=self.settings.per_app_mode,
            app_list=self._parse_per_app_list(),
            upstream_http_port=self.xray.active_http_port,
            upstream_socks_port=self.xray.active_socks_port,
        )

    def discover_system_apps(self) -> List[dict]:
        return WindowsProcessInspector.discover_user_applications()

    def launch_tunneled_app(self, exe_path_or_name: str, extra_args: str = "") -> Tuple[bool, str]:
        base_exe = os.path.basename(str(exe_path_or_name or "").strip().strip('"'))
        if base_exe:
            cur_list = self._parse_per_app_list()
            if base_exe.lower() not in {x.lower() for x in cur_list}:
                cur_list.append(base_exe)
                self.settings.per_app_list = "\n".join(cur_list)
                self._save_settings(self.settings)
                self._notify_settings_updated()
        self._sync_per_app_gateway()
        ok, msg = PerAppSplitGateway.launch_app_through_tunnel(
            exe_path_or_name=exe_path_or_name,
            http_port=self.xray.active_http_port,
            socks_port=self.xray.active_socks_port,
            extra_args=extra_args,
            restart_if_running=True,
        )
        self.emit_log(f"[PerApp] {msg}")
        return ok, msg

    def get_doh_repositories(self) -> List[dict]:
        return self.doh_engine.get_all_doh_Visual_list()

    def add_doh_custom(self, url_or_text: str, title: str = "Custom DoH") -> int:
        return self.doh_engine.add_doh_entries(url_or_text, title=title)

    def start_doh_scan(self):
        with self._state_lock:
            self._op_generation += 1
            gen_id = self._op_generation
            self._scan_abort_flag = False
            self._task_abort_flag = False

        def _doh_worker():
            try:
                self._emit_scan_state(True, "در حال اسکن موازی سرورهای DoH ضد تحریم و فیلتر...")
                ranked = self.doh_engine.scan_doh_repositories(
                    on_row_cb=self._emit_scan_row,
                    progress_cb=self._emit_scan_progress,
                    abort_check=lambda: self._is_op_cancelled(gen_id),
                )
                if self._is_op_cancelled(gen_id):
                    return
                self._emit_scan_ranked(ranked)
                ok_cnt = sum(1 for r in ranked if r.get("verified"))
                self._emit_scan_progress(100, f"{ok_cnt} سرور DoH سالم و بدون مسمومیت یافت شد")
                self._emit_scan_state(False, f"اسکن DoH پایان یافت ({ok_cnt} سرور سالم)")
            except Exception as exc:
                self.emit_log(f"[DoH Scan] Error: {exc}")
                self._emit_scan_state(False, f"خطا در اسکن DoH: {exc}")

        self._worker_thread = threading.Thread(target=_doh_worker, daemon=True)
        self._worker_thread.start()

    def apply_doh_to_tunnel_dns(self, doh_url: str):
        clean_u = (doh_url or "").strip()
        if not clean_u:
            return
        self.update_settings({"remote_dns": clean_u, "active_doh_url": clean_u})
        self.emit_log(f"[DoH] Tunnel Remote DNS updated to: {clean_u}")
        self._emit_task_progress(False, 100, f"سرور DoH روی مسیریابی تونل تنظیم شد: {clean_u}")

    def toggle_system_doh_veil(self, enabled: bool, doh_url: str = "") -> Tuple[bool, str]:
        target_u = (doh_url or self.settings.active_doh_url or self.settings.remote_dns or "https://cloudflare-dns.com/dns-query").strip()
        if enabled:
            ok, msg = self.doh_engine.activate_system_doh_veil(target_u)
            self.settings.doh_shield_enabled = ok
            if ok:
                self.settings.active_doh_url = target_u
            self._save_settings(self.settings)
            self._notify_settings_updated()
            self._push_telemetry()
            return ok, msg
        else:
            ok, msg = self.doh_engine.stop_system_doh_veil()
            self.settings.doh_shield_enabled = False
            self._save_settings(self.settings)
            self._notify_settings_updated()
            self._push_telemetry()
            return ok, msg

    @staticmethod
    def _replace_uri_endpoint_ip(uri: str, new_ip: str) -> str:
        clean_ip = (new_ip or "").strip()
        if not clean_ip:
            return uri
        ed = UriConfigCodec.parse_to_editable(uri)
        if not ed.get("sni") and ed.get("address"):
            ed["sni"] = ed["address"]
        if not ed.get("host_header") and ed.get("address"):
            ed["host_header"] = ed["address"]
        ed["address"] = clean_ip
        return UriConfigCodec.build_uri_from_editable(ed)

    @staticmethod
    def _update_uri_remark(uri: str, new_name: str) -> str:
        clean_name = (new_name or "").strip()
        if not clean_name:
            return uri
        if uri.lower().startswith("vmess://"):
            ed = UriConfigCodec.parse_to_editable(uri)
            ed["name"] = clean_name
            return UriConfigCodec.build_uri_from_editable(ed)
        base_part = uri.split("#", 1)[0]
        return f"{base_part}#{urllib.parse.quote(clean_name)}"

    @staticmethod
    def _build_exportable_node_uri(node: ProfileNode, inject_early_data: int = 0) -> str:
        ed = UriConfigCodec.parse_to_editable(
            node.uri,
            uid=node.uid,
            group_tag=node.group_tag,
            preferred_vec=node.cached_vector_id or "AUTO",
        )
        if node.cached_clean_ip and CleanIpScanner.is_cdn_eligible(node):
            if not ed.get("sni"):
                ed["sni"] = node.original_host
            ed["address"] = node.cached_clean_ip
        ed["name"] = node.name
        return UriConfigCodec.build_uri_from_editable(ed, inject_early_data=inject_early_data)

    @staticmethod
    def _probe_fast_tuple(http_port: int, timeout: float = 4.2) -> Tuple[bool, int, str]:
        res = TunnelStreamVerifier.fast_probe(http_port=http_port, timeout=timeout)
        if isinstance(res, tuple):
            return bool(res[0]), int(res[1]), str(res[2])
        return bool(res.passed), int(res.ping_ms), str(getattr(res, "detail", ""))

    @staticmethod
    def _probe_full_tuple(
        http_port: int,
        verify_upload: bool,
        require_youtube_6s: bool,
        abort_check: Optional[Callable[[], bool]] = None,
    ) -> Tuple[bool, int, float, str]:
        res = TunnelStreamVerifier.run_full_qualification(
            http_port=http_port,
            verify_upload=verify_upload,
            require_youtube_6s=require_youtube_6s,
            abort_check=abort_check,
        )
        if isinstance(res, tuple):
            return bool(res[0]), int(res[1]), float(res[2]), str(res[3])
        return bool(res.passed), int(res.ping_ms), 0.0, str(getattr(res, "detail", ""))

    def _resolve_origin_endpoint(self, node: ProfileNode) -> str:
        if not CleanIpScanner.is_cdn_eligible(node):
            node.cached_clean_ip = ""
        resolved_orig = CleanIpScanner.resolve_unpoisoned_ipv4(node.original_host, timeout=1.6)
        if resolved_orig and (not CleanIpScanner.is_poisoned_ip(resolved_orig)):
            return resolved_orig
        if node.original_host and (not CleanIpScanner.is_poisoned_ip(node.original_host)):
            return node.original_host
        return ""

    def _discover_fallback_clean_ips(
        self,
        node: ProfileNode,
        gen_id: int,
        port_edge_cache: Optional[Dict[int, List[str]]] = None,
        sample_count: int = 34,
    ) -> List[str]:
        if (not self.settings.auto_clean_ip) or (not CleanIpScanner.is_cdn_eligible(node)):
            return []
        candidates: List[str] = []
        if node.cached_clean_ip and (not CleanIpScanner.is_poisoned_ip(node.cached_clean_ip)):
            candidates.append(node.cached_clean_ip)
        if (port_edge_cache is not None) and (node.port in port_edge_cache):
            discovered_ips = port_edge_cache[node.port]
        else:
            edges = CleanIpScanner.discover_best_ips(
                port=node.port,
                top_n=3,
                sample_count=sample_count,
                probe_sni="speed.cloudflare.com",
                log_fn=self.emit_log,
                abort_check=lambda: self._is_op_cancelled(gen_id),
            )
            discovered_ips = [ip_val for ip_val, _ in edges]
            if port_edge_cache is not None:
                port_edge_cache[node.port] = discovered_ips
        for ip_val in discovered_ips:
            if ip_val and (ip_val not in candidates):
                candidates.append(ip_val)
        return candidates[:3]

    def get_visible_profiles(self) -> List[ProfileNode]:
        with self._repo_lock:
            return [p for p in self.profiles if not p.is_hidden_pool]

    def get_selected_index(self) -> int:
        with self._repo_lock:
            visible = [p for p in self.profiles if not p.is_hidden_pool]
            if not visible:
                return -1
            if self.settings.selected_profile_uid == "__SMART_AUTO__":
                return -1
            for idx, node in enumerate(visible):
                if node.uid == self.settings.selected_profile_uid:
                    self.selected_index = idx
                    return idx
            clamped = max(0, min(self.selected_index, len(visible) - 1))
            self.selected_index = clamped
            return clamped

    def _restore_persisted_selection(self) -> int:
        with self._repo_lock:
            visible = [p for p in self.profiles if not p.is_hidden_pool]
            if not visible:
                return 0
            target_uid = (self.settings.selected_profile_uid or "").strip()
            if target_uid == "__SMART_AUTO__":
                return -1
            if target_uid:
                for idx, node in enumerate(visible):
                    if node.uid == target_uid:
                        return idx
            idx_val = int(self.settings.selected_index)
            if 0 <= idx_val < len(visible):
                return idx_val
            return 0

    def _persist_active_selection(self, save_disk: bool = True):
        with self._repo_lock:
            visible = [p for p in self.profiles if not p.is_hidden_pool]
            if self.settings.selected_profile_uid == "__SMART_AUTO__":
                self.selected_index = -1
                with self._state_lock:
                    self.snapshot.selected_index = 0
                    if not self.snapshot.is_connected:
                        self.snapshot.active_profile_uid = "__SMART_AUTO__"
                        self.snapshot.active_profile_name = "Smart Auto-Pool"
                        self.snapshot.protocol_label = "AUTO"
            elif visible:
                self.selected_index = max(0, min(self.selected_index, len(visible) - 1))
                active = visible[self.selected_index]
                self.settings.selected_index = self.selected_index
                self.settings.selected_profile_uid = active.uid
                with self._state_lock:
                    self.snapshot.selected_index = self.selected_index
                    if not self.snapshot.is_connected:
                        self.snapshot.active_profile_uid = active.uid
                        self.snapshot.active_profile_name = active.name
                        self.snapshot.protocol_label = active.protocol
            else:
                self.selected_index = 0
                self.settings.selected_index = 0
                if self.settings.selected_profile_uid != "__SMART_AUTO__":
                    self.settings.selected_profile_uid = ""
                with self._state_lock:
                    self.snapshot.selected_index = 0
                    if not self.snapshot.is_connected:
                        self.snapshot.active_profile_uid = "__SMART_AUTO__" if self.hidden_pool else ""
                        self.snapshot.active_profile_name = "Smart Auto-Pool" if self.hidden_pool else "---"
                        self.snapshot.protocol_label = "AUTO" if self.hidden_pool else "---"
        if save_disk:
            self._save_settings(self.settings)

    def _resolve_profile_index(self, index_or_uid: Any) -> int:
        with self._repo_lock:
            visible = [p for p in self.profiles if not p.is_hidden_pool]
            if not visible:
                return -1
            if isinstance(index_or_uid, str) and (not index_or_uid.lstrip("-").isdigit()):
                uid_clean = index_or_uid.strip()
                for idx, node in enumerate(visible):
                    if node.uid == uid_clean:
                        return idx
                return -1
            try:
                idx_num = int(index_or_uid)
                if 0 <= idx_num < len(visible):
                    return idx_num
            except Exception:
                pass
            return -1

    def _find_visible_node(self, index_or_uid: Any) -> Optional[ProfileNode]:
        idx = self._resolve_profile_index(index_or_uid)
        visible = self.get_visible_profiles()
        if 0 <= idx < len(visible):
            return visible[idx]
        return None

    def _serialize_profiles(self) -> List[dict]:
        with self._repo_lock:
            visible = [p for p in self.profiles if not p.is_hidden_pool]
            out: List[dict] = []
            for idx, node in enumerate(visible):
                item = node.to_dict()
                is_sel = idx == self.selected_index
                item["index"] = idx
                item["is_selected"] = is_sel
                item["is_active"] = is_sel
                out.append(item)
            return out

    @staticmethod
    def _build_vector_plan(node: ProfileNode, engine_mode: str) -> List[BypassVector]:
        base_vectors = [v for v in filter_vectors_by_mode(engine_mode) if v.family != "DIRECT"]
        direct_vec = find_vector("VEC-00")
        uri_low = node.uri.lower()
        proto_up = node.protocol.upper()

        if proto_up in ("SHADOWSOCKS", "SOCKS"):
            return [direct_vec]

        if "security=reality" in uri_low:
            frag_subset = [v for v in base_vectors if v.family in ("COALESCE", "FRAGMENT")][:3]
            return [direct_vec] + frag_subset

        is_tunnel_or_plain = (
            CleanIpScanner.is_domestic_or_direct_tunnel(node)
            or ("headertype=http" in uri_low)
            or ("security=none" in uri_low)
        )
        if is_tunnel_or_plain:
            return [direct_vec] + base_vectors

        ordered = list(base_vectors)
        if node.cached_vector_id:
            cv = find_vector(node.cached_vector_id)
            if cv in ordered:
                ordered.remove(cv)
            ordered.insert(0, cv)
        return ordered + [direct_vec]

    def build_vector_plan(self, node: ProfileNode) -> List[BypassVector]:
        if not self.settings.autopilot_enabled:
            return [find_vector(self.settings.manual_vector_id)]
        return self._build_vector_plan(node, self.settings.engine_mode)

    def _handle_bridge_endpoint_change(self, remote_host: str):
        if self.settings.tun_enabled and self.tun.active:
            self.tun.pin_endpoint_direct_route(remote_host)

    def _emit_tun_status(self, enabled: bool, active: bool, detail: str):
        with self._state_lock:
            self.snapshot.tun_enabled = bool(enabled)
            self.snapshot.tun_active = bool(active)
        if self.on_tun_status is not None:
            try:
                self.on_tun_status(bool(enabled), bool(active), str(detail))
            except TypeError:
                self.on_tun_status(bool(active), str(detail))
        self._push_telemetry()

    def emit_log(self, message: str):
        ts = time.strftime("%H:%M:%S")
        line = message if (message.startswith("[") and len(message) > 9 and message[3] == ":") else f"[{ts}] {message}"
        if self.on_log is not None:
            try:
                self.on_log(line)
            except Exception:
                pass

    def _emit_task_progress(self, active: bool, pct: int, message: str):
        clamped = max(0, min(100, int(pct)))
        with self._state_lock:
            self.snapshot.progress_percent = clamped if active else 0
        if self.on_task_progress is not None:
            self.on_task_progress(bool(active), clamped, str(message))

    def _emit_scan_row(self, row: dict):
        if self.on_scan_row is not None:
            self.on_scan_row(copy.deepcopy(row))

    def _emit_scan_ranked(self, rows: List[dict]):
        if self.on_scan_ranked is not None:
            self.on_scan_ranked(copy.deepcopy(rows))

    def _emit_scan_progress(self, pct: int, label: str):
        clamped = max(0, min(100, int(pct)))
        if self.on_scan_progress is not None:
            self.on_scan_progress(clamped, str(label))
        is_running_pct = (clamped > 0) and (clamped < 100)
        self._emit_task_progress(is_running_pct, clamped, str(label))

    def _emit_scan_state(self, running: bool, summary: str):
        self._scanner_running = bool(running)
        if self.on_scan_state is not None:
            self.on_scan_state(bool(running), str(summary))
        if not running:
            self._emit_task_progress(False, 100, str(summary))

    def _push_telemetry(self):
        if self.on_telemetry is not None:
            with self._state_lock:
                payload = asdict(self.snapshot)
            try:
                self.on_telemetry(payload)
            except Exception:
                pass

    def _notify_settings_updated(self):
        if self.on_settings is not None:
            self.on_settings(self.settings.to_dict())

    def _notify_profiles_updated(self, save_selection: bool = True):
        self._persist_active_selection(save_disk=save_selection)
        if save_selection:
            self._save_profiles(self.profiles)
        snapshot_list = self._serialize_profiles()
        sel_idx = self.get_selected_index()
        if self.on_profiles is not None:
            self.on_profiles(snapshot_list, sel_idx)
        if self._on_profiles_changed is not None:
            self._on_profiles_changed(snapshot_list)

    def _notify_verified_outputs_updated(self):
        self._save_verified_outputs()
        if self.on_verified_outputs is not None:
            with self._repo_lock:
                payload = [v.to_dict() for v in self.verified_outputs]
            self.on_verified_outputs(payload)

    def _notify_subscriptions_updated(self):
        with self._repo_lock:
            subs_copy = [s.to_dict() for s in self.subscriptions]
        if self.on_subscriptions is not None:
            self.on_subscriptions(subs_copy)

    def _set_state(self, state: EngineState, headline: str, detail: str, progress: Optional[int] = None):
        with self._state_lock:
            self.snapshot.state = state.value
            self.snapshot.tun_enabled = self.settings.tun_enabled
            self.snapshot.tun_active = self.tun.active or (self.settings.tun_enabled and is_windows_admin())
            self.snapshot.tun_badge = "ON" if (self.settings.tun_enabled and is_windows_admin()) else "OFF"
            self.snapshot.system_proxy_enabled = self.settings.system_proxy_enabled
            self.snapshot.selected_index = max(0, self.selected_index)

            if state == EngineState.CONNECTED:
                if self._connected_since_ts is None:
                    self._connected_since_ts = time.perf_counter()
                self.snapshot.ui_phase = "CONNECTED"
                self.snapshot.is_connecting = False
                self.snapshot.is_connected = True
                self.snapshot.button_text = "قطع اتصال امن"
            elif state in CONNECTING_STATES:
                self._connected_since_ts = None
                self.snapshot.uptime_seconds = 0
                self.snapshot.uptime_label = "00:00:00"
                self.snapshot.ui_phase = "CONNECTING"
                self.snapshot.is_connecting = True
                self.snapshot.is_connected = False
                self.snapshot.button_text = "لغو فرایند"
            elif state == EngineState.ERROR:
                self._connected_since_ts = None
                self.snapshot.uptime_seconds = 0
                self.snapshot.uptime_label = "00:00:00"
                self.snapshot.ui_phase = "ERROR"
                self.snapshot.is_connecting = False
                self.snapshot.is_connected = False
                self.snapshot.button_text = "تلاش مجدد"
            else:
                self._connected_since_ts = None
                self.snapshot.uptime_seconds = 0
                self.snapshot.uptime_label = "00:00:00"
                self.snapshot.ui_phase = "IDLE"
                self.snapshot.is_connecting = False
                self.snapshot.is_connected = False
                self.snapshot.button_text = "اتصال هوشمند"

            self.snapshot.status_headline = headline
            self.snapshot.status_detail = detail
            if progress is not None:
                self.snapshot.progress_percent = max(0, min(100, int(progress)))
        self._push_telemetry()

    def _load_settings(self) -> EngineSettings:
        if os.path.exists(self.settings_path):
            try:
                with open(self.settings_path, "r", encoding="utf-8") as f:
                    return EngineSettings.from_dict(json.load(f))
            except Exception:
                pass
        cfg = EngineSettings()
        self._save_settings(cfg)
        return cfg

    def _save_settings(self, cfg: Optional[EngineSettings] = None):
        target = cfg if (cfg is not None) else self.settings
        try:
            with open(self.settings_path, "w", encoding="utf-8") as f:
                json.dump(target.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as exc:
            self.emit_log(f"[Settings] Write error: {exc}")

    def _load_profiles(self) -> List[ProfileNode]:
        if os.path.exists(self.repo_path):
            try:
                with open(self.repo_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, list):
                        return [ProfileNode.from_dict(item) for item in raw if not item.get("is_hidden_pool")]
            except Exception:
                pass
        if DEFAULT_BOOTSTRAP_URI.strip():
            seed = UriConfigCodec.extract_profile_node(DEFAULT_BOOTSTRAP_URI.strip(), group_tag="Default")
            self._save_profiles([seed])
            return [seed]
        return []

    def _save_profiles(self, nodes: Optional[List[ProfileNode]] = None):
        target_nodes = nodes if (nodes is not None) else self.profiles
        with self._repo_lock:
            try:
                serializable = [n.to_dict() for n in target_nodes if not n.is_hidden_pool]
                with open(self.repo_path, "w", encoding="utf-8") as f:
                    json.dump(serializable, f, indent=2, ensure_ascii=False)
            except Exception as exc:
                self.emit_log(f"[Repository] Write error: {exc}")

    def _load_verified_outputs(self) -> List[VerifiedOutputItem]:
        if os.path.exists(self.verified_path):
            try:
                with open(self.verified_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, list):
                        return [VerifiedOutputItem.from_dict(x) for x in raw]
            except Exception:
                pass
        return []

    def _save_verified_outputs(self):
        with self._repo_lock:
            try:
                with open(self.verified_path, "w", encoding="utf-8") as f:
                    json.dump([v.to_dict() for v in self.verified_outputs], f, indent=2, ensure_ascii=False)
            except Exception as exc:
                self.emit_log(f"[VerifiedOutputs] Write error: {exc}")

    def _load_subscriptions(self) -> List[SubscriptionItem]:
        if os.path.exists(self.subs_path):
            try:
                with open(self.subs_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, list):
                        return [SubscriptionItem.from_dict(x) for x in raw]
            except Exception:
                pass
        return []

    def _save_subscriptions(self):
        with self._repo_lock:
            try:
                with open(self.subs_path, "w", encoding="utf-8") as f:
                    json.dump([s.to_dict() for s in self.subscriptions], f, indent=2, ensure_ascii=False)
            except Exception as exc:
                self.emit_log(f"[Subscriptions] Write error: {exc}")

    @staticmethod
    def _parse_worker_pool_payload(raw_text: str) -> List[ProfileNode]:
        txt = (raw_text or "").strip()
        if not txt:
            return []

        entries: List[Tuple[str, str]] = []
        seen_uris = set()

        def _add_uri(u_str: str, loc_hint: str = ""):
            u_clean = (u_str or "").strip()
            if u_clean and any(u_clean.lower().startswith(s) for s in UriConfigCodec.SUPPORTED_SCHEMES):
                if u_clean not in seen_uris:
                    seen_uris.add(u_clean)
                    entries.append((u_clean, (loc_hint or "").strip()))

        if txt.startswith(("[", "{")):
            try:
                parsed_json = json.loads(txt)
                if isinstance(parsed_json, dict):
                    list_found = None
                    for wrap_key in ("configs", "nodes", "items", "data", "proxies", "servers"):
                        if isinstance(parsed_json.get(wrap_key), list):
                            list_found = parsed_json[wrap_key]
                            break
                    if list_found is not None:
                        parsed_json = list_found
                    else:
                        for loc_k, val_list in parsed_json.items():
                            if isinstance(val_list, list):
                                for item in val_list:
                                    if isinstance(item, str):
                                        _add_uri(item, str(loc_k))
                                    elif isinstance(item, dict):
                                        u_v = item.get("uri") or item.get("config") or item.get("link") or item.get("url") or ""
                                        l_v = item.get("location") or item.get("country_code") or item.get("country") or item.get("cc") or item.get("loc") or loc_k
                                        _add_uri(str(u_v), str(l_v))
                if isinstance(parsed_json, list):
                    for item in parsed_json:
                        if isinstance(item, str):
                            _add_uri(item, "")
                        elif isinstance(item, dict):
                            u_v = item.get("uri") or item.get("config") or item.get("link") or item.get("url") or item.get("u") or ""
                            l_v = item.get("location") or item.get("country_code") or item.get("country") or item.get("cc") or item.get("loc") or item.get("c") or ""
                            _add_uri(str(u_v), str(l_v))
            except Exception:
                pass

        if not entries:
            for u in UriConfigCodec.extract_uris_from_blob(txt):
                _add_uri(u, "")

        nodes: List[ProfileNode] = []
        for u_val, loc_val in entries:
            try:
                nd = UriConfigCodec.extract_profile_node(
                    u_val,
                    group_tag="__AUTO_POOL__",
                    is_hidden=True,
                    explicit_country=loc_val,
                )
                nodes.append(nd)
            except Exception:
                continue
        return nodes

    def _load_hidden_pool_cache(self) -> List[ProfileNode]:
        if os.path.exists(self.hidden_cache_path):
            try:
                with open(self.hidden_cache_path, "rb") as fh:
                    dec = base64.b64decode(fh.read()).decode("utf-8", errors="ignore")
                nodes = self._parse_worker_pool_payload(dec)
                meta = self._load_pool_meta()
                for nd in nodes:
                    key = hashlib.sha1(nd.uri.encode("utf-8", errors="ignore")).hexdigest()[:16]
                    entry = meta.get(key)
                    if isinstance(entry, dict):
                        nd.cached_vector_id = str(entry.get("vec") or "")
                        saved_ip = str(entry.get("ip") or "")
                        nd.cached_clean_ip = saved_ip if CleanIpScanner.is_cdn_eligible(nd) else ""
                        nd.last_ping_ms = int(entry.get("ping") or -1)
                        if nd.last_ping_ms > 0:
                            nd.health_status = "VERIFIED"
                return nodes
            except Exception:
                pass
        return []

    def _resolve_hidden_urls(self) -> List[str]:
        urls: List[str] = []
        for raw_u in HIDDEN_AUTO_SUB_URLS:
            dec = _decode_hidden_url(raw_u)
            if dec and (dec not in urls):
                urls.append(dec)
        env_u = _decode_hidden_url(os.environ.get("ALAN_AUTO_SUB_URL", ""))
        if env_u and (env_u not in urls):
            urls.append(env_u)
        secret_file = os.path.join(self.configs_dir, ".auto_pool_url")
        if os.path.exists(secret_file):
            try:
                with open(secret_file, "r", encoding="utf-8") as fh:
                    for line in fh:
                        du = _decode_hidden_url(line)
                        if du and (du not in urls):
                            urls.append(du)
            except Exception:
                pass
        return urls

    def _sync_hidden_auto_pool(self):
        urls = self._resolve_hidden_urls()
        if not urls:
            self._notify_auto_locations_updated()
            return
        sess = requests.Session()
        sess.trust_env = False
        sess.headers.update({"User-Agent": "v2rayNG/1.9.5"})
        if self.snapshot.is_connected:
            px = f"http://127.0.0.1:{self.xray.active_http_port}"
            sess.proxies = {"http": px, "https": px}

        merged_nodes: List[ProfileNode] = []
        seen_uris = set()
        try:
            for u in urls:
                try:
                    resp = sess.get(u, timeout=12.0)
                    if resp.status_code == 200 and resp.text:
                        for nd in self._parse_worker_pool_payload(resp.text):
                            if nd.uri not in seen_uris:
                                seen_uris.add(nd.uri)
                                merged_nodes.append(nd)
                except Exception:
                    continue
        finally:
            sess.close()

        if merged_nodes:
            with self._repo_lock:
                self.hidden_pool = merged_nodes
            self._hydrate_hidden_pool_meta()
            try:
                compact = [{"u": n.uri, "c": n.country_code} for n in merged_nodes]
                enc = base64.b64encode(json.dumps(compact, ensure_ascii=False).encode("utf-8"))
                with open(self.hidden_cache_path, "wb") as fh:
                    fh.write(enc)
            except Exception:
                pass
            loc_items = self.get_available_auto_locations()
            loc_count = max(0, len(loc_items) - 1)
            self.emit_log(f"[AutoPool] Synced {len(merged_nodes)} repository endpoints across {loc_count} location(s).")
        self._notify_auto_locations_updated()
        self._push_telemetry()

    def get_available_auto_locations(self) -> List[dict]:
        with self._repo_lock:
            pool_copy = list(self.hidden_pool)
        total = len(pool_copy)
        counts: Dict[str, int] = {}
        for nd in pool_copy:
            cc = (nd.country_code or "").strip().upper()
            if not cc:
                cc = LocationExtractor.extract_country_code(name=nd.name, uri=nd.uri)
                nd.country_code = cc
            if cc:
                counts[cc] = counts.get(cc, 0) + 1

        cur_pref = (self.settings.preferred_auto_location or "ALL").strip().upper()
        if (cur_pref not in ("", "ALL", "AUTO")) and (total > 0) and (cur_pref not in counts):
            self.settings.preferred_auto_location = "ALL"
            self._save_settings(self.settings)

        items: List[dict] = [
            {
                "code": "ALL",
                "country_code": "ALL",
                "name_fa": "همه لوکیشن‌ها (خودکار)",
                "name_en": "All Locations (Auto)",
                "label_fa": f"همه لوکیشن‌ها ({total})" if total > 0 else "همه لوکیشن‌ها (خودکار)",
                "label_en": f"All Locations ({total})" if total > 0 else "All Locations (Auto)",
                "count": total,
            }
        ]
        for cc, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            en_n, fa_n = LocationExtractor.get_country_names(cc)
            items.append({
                "code": cc,
                "country_code": cc,
                "name_fa": fa_n,
                "name_en": en_n,
                "label_fa": f"{fa_n} ({cc}) — {cnt}",
                "label_en": f"{en_n} ({cc}) — {cnt}",
                "count": cnt,
            })
        return items

    def get_selected_auto_location(self) -> str:
        val = (self.settings.preferred_auto_location or "ALL").strip().upper()
        return "ALL" if val in ("", "AUTO", "همه") else val

    def _notify_auto_locations_updated(self):
        locs = self.get_available_auto_locations()
        sel_loc = self.get_selected_auto_location()
        with self._state_lock:
            self.snapshot.preferred_auto_location = sel_loc
            self.snapshot.available_auto_locations = locs
        if self.on_auto_locations is not None:
            self.on_auto_locations(locs, sel_loc)

    def set_auto_location(self, location_code: str):
        raw_c = (location_code or "ALL").strip().upper()
        norm_c = "ALL" if raw_c in ("", "ALL", "AUTO", "همه") else raw_c
        available_codes = {item["code"] for item in self.get_available_auto_locations()}
        if (norm_c != "ALL") and (len(available_codes) > 1) and (norm_c not in available_codes):
            norm_c = "ALL"

        changed = (norm_c != self.get_selected_auto_location()) or (not self.is_auto_repo_mode())
        self.settings.preferred_auto_location = norm_c
        self.settings.autopilot_enabled = True
        self.settings.selected_profile_uid = "__SMART_AUTO__"
        self.selected_index = -1
        self._save_settings(self.settings)
        self._notify_auto_locations_updated()
        self._notify_settings_updated()
        self._notify_profiles_updated(save_selection=True)
        self._push_telemetry()

        if norm_c == "ALL":
            self.emit_log("[AutoPool] Location filter set to: ALL")
        else:
            en_n, _ = LocationExtractor.get_country_names(norm_c)
            self.emit_log(f"[AutoPool] Location filter locked to: {en_n} ({norm_c})")

        if changed and (self.snapshot.is_connected or self.snapshot.is_connecting):
            self.request_connect()

    def get_profiles_as_dicts(self) -> List[dict]:
        return self._serialize_profiles()

    def get_subscriptions_as_dicts(self) -> List[dict]:
        with self._repo_lock:
            return [s.to_dict() for s in self.subscriptions]

    def get_settings_as_dict(self) -> dict:
        return self.settings.to_dict()

    def get_vectors_as_dicts(self) -> List[dict]:
        return [asdict(v) for v in VECTOR_REGISTRY]

    def set_system_proxy(self, enabled: bool):
        self.settings.system_proxy_enabled = bool(enabled)
        self._save_settings(self.settings)
        self._sync_per_app_gateway()
        if self.snapshot.is_connected:
            WindowsSystemProxy.apply(self._should_enable_global_wininet_proxy(), self._effective_system_proxy_port())
        self._notify_settings_updated()
        self._push_telemetry()

    def is_auto_repo_mode(self) -> bool:
        return bool(self.settings.autopilot_enabled) or (self.settings.selected_profile_uid == "__SMART_AUTO__")

    def _load_pool_meta(self) -> dict:
        if os.path.exists(self.pool_meta_path):
            try:
                with open(self.pool_meta_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                pass
        return {}

    def _save_pool_winner_meta(self, node: ProfileNode, vec_id: str, clean_ip: str, ping_ms: int):
        try:
            key = hashlib.sha1(node.uri.encode("utf-8", errors="ignore")).hexdigest()[:16]
            meta = self._load_pool_meta()
            meta[key] = {
                "vec": vec_id,
                "ip": clean_ip,
                "ping": int(ping_ms),
                "ts": int(time.time()),
            }
            with open(self.pool_meta_path, "w", encoding="utf-8") as fh:
                json.dump(meta, fh)
        except Exception:
            pass

    def _hydrate_hidden_pool_meta(self):
        meta = self._load_pool_meta()
        if not meta:
            return
        with self._repo_lock:
            for nd in self.hidden_pool:
                key = hashlib.sha1(nd.uri.encode("utf-8", errors="ignore")).hexdigest()[:16]
                entry = meta.get(key)
                if isinstance(entry, dict):
                    nd.cached_vector_id = str(entry.get("vec") or "")
                    nd.cached_clean_ip = str(entry.get("ip") or "") if CleanIpScanner.is_cdn_eligible(nd) else ""
                    nd.last_ping_ms = int(entry.get("ping") or -1)
                    if nd.last_ping_ms > 0:
                        nd.health_status = "VERIFIED"

    def set_tun_mode(self, enabled: bool):
        want_tun = bool(enabled)
        if want_tun and (not is_windows_admin()):
            was_connected = bool(self.snapshot.is_connected or self.snapshot.is_connecting)
            self.settings.tun_enabled = True
            self._save_settings(self.settings)
            extra_flags = ["--tun-on"] + (["--resume-connect"] if was_connected else [])
            self.emit_log("[TUN] Requesting Windows Administrator (UAC) elevation...")
            elevated = relaunch_as_admin(extra_args=extra_flags)
            if elevated:
                if self.on_request_quit is not None:
                    self.on_request_quit()
                return

            self.settings.tun_enabled = False
            self._save_settings(self.settings)
            self.snapshot.tun_enabled = False
            self.snapshot.tun_active = False
            self.snapshot.tun_badge = "OFF"
            self._emit_tun_status(False, False, "OFF")
            self._notify_settings_updated()
            self.emit_log("[TUN] Administrator elevation canceled by user.")
            return

        self.settings.tun_enabled = want_tun
        self._save_settings(self.settings)
        self.snapshot.tun_enabled = want_tun
        self.snapshot.tun_badge = "ON" if want_tun else "OFF"
        self._notify_settings_updated()

        if want_tun:
            def _prep_and_maybe_start():
                ok_dll, dll_msg = self.tun.ensure_wintun_dll()
                if not ok_dll:
                    self.emit_log(f"[TUN] {dll_msg}")
                    self.settings.tun_enabled = False
                    self.snapshot.tun_enabled = False
                    self.snapshot.tun_badge = "OFF"
                    self._save_settings(self.settings)
                    self._emit_tun_status(False, False, dll_msg)
                    self._notify_settings_updated()
                    return
                self.xray._native_tun_supported = None
                if self.snapshot.is_connected and (self._active_runtime_node is not None):
                    ep = self.bridge.remote_host
                    self._activate_xray_tun_async(self._active_runtime_node, ep)
                else:
                    self._emit_tun_status(True, True, "ON")

            threading.Thread(target=_prep_and_maybe_start, daemon=True).start()
        else:
            def _disable_tun():
                self.tun.stop()
                self.bridge.refresh_physical_interface(enable_tun_bind=False)
                if self.snapshot.is_connected and (self._active_runtime_node is not None):
                    self.xray.ensure_running(
                        uri=self._active_runtime_node.uri,
                        settings=self.settings,
                        enable_native_tun_inbound=False,
                    )
                    self._sync_per_app_gateway()
                    if self.settings.system_proxy_enabled:
                        WindowsSystemProxy.apply(self._should_enable_global_wininet_proxy(), self._effective_system_proxy_port())
                self.snapshot.tun_badge = "OFF"
                self._emit_tun_status(False, False, "OFF")

            threading.Thread(target=_disable_tun, daemon=True).start()

    def _activate_xray_tun_async(self, node: ProfileNode, endpoint_host: str):
        _, phys_alias = self.tun.detect_physical_egress()
        self.bridge.refresh_physical_interface(enable_tun_bind=True)
        self.tun.ensure_wintun_dll()
        self.xray._native_tun_supported = None
        native_tun = self.xray.supports_native_tun() and self.tun.has_wintun_dll()

        if native_tun:
            self.xray.ensure_running(
                uri=node.uri,
                settings=self.settings,
                use_native_fragment=False,
                enable_native_tun_inbound=True,
                physical_nic_alias=phys_alias,
            )

        ok, detail = self.tun.activate_routes_for_xray_tun(
            socks_port=self.xray.active_socks_port,
            native_xray_tun_active=native_tun,
            tun_dns=self.settings.tun_dns,
            endpoint_ip=endpoint_host,
        )
        if not ok:
            self.emit_log(f"[TUN] Activation aborted: {detail}")
            self.bridge.refresh_physical_interface(enable_tun_bind=False)
            self.settings.tun_enabled = False
            self.snapshot.tun_badge = "OFF"
            self._save_settings(self.settings)
            if native_tun:
                self.xray.ensure_running(uri=node.uri, settings=self.settings, enable_native_tun_inbound=False)
            self._emit_tun_status(False, False, detail)
            self._notify_settings_updated()
        else:
            self.snapshot.tun_badge = "ON"
            self._emit_tun_status(True, True, "ON")

    def set_single_setting(self, key: str, value: Any):
        clean_key = SETTING_KEY_ALIASES.get(str(key).strip(), str(key).strip())
        if clean_key == "tun_enabled":
            self.set_tun_mode(bool(value))
            return
        if clean_key == "system_proxy_enabled":
            self.set_system_proxy(bool(value))
            return
        if clean_key == "preferred_auto_location":
            self.set_auto_location(str(value))
            return
        if clean_key == "doh_shield_enabled":
            self.toggle_system_doh_veil(bool(value))
            return
        if clean_key in ("autopilot_enabled", "auto_pool_enabled"):
            auto_on = bool(value)
            if auto_on:
                self.update_settings({"autopilot_enabled": True, "auto_pool_enabled": True, "selected_profile_uid": "__SMART_AUTO__"})
                self.selected_index = -1
                self._notify_profiles_updated(save_selection=True)
            else:
                vis = self.get_visible_profiles()
                next_uid = vis[0].uid if vis else ""
                self.selected_index = 0 if vis else -1
                self.update_settings({"autopilot_enabled": False, "selected_profile_uid": next_uid, "selected_index": 0})
                self._notify_profiles_updated(save_selection=True)
            return
        self.update_settings({clean_key: value})

    def update_settings_dict(self, new_data: dict):
        self.update_settings(new_data)

    def update_settings(self, settings_dict: dict):
        if not isinstance(settings_dict, dict):
            return

        prev_tun = self.settings.tun_enabled
        prev_sys_proxy = self.settings.system_proxy_enabled
        cur_uid = self.settings.selected_profile_uid
        cur_idx = self.settings.selected_index

        normalized: Dict[str, Any] = {}
        for raw_k, raw_v in settings_dict.items():
            if raw_v is None:
                continue
            mapped_k = SETTING_KEY_ALIASES.get(str(raw_k).strip(), str(raw_k).strip())
            if isinstance(raw_v, list) and mapped_k in ("custom_direct_domains", "custom_proxy_domains", "custom_blocked_domains", "per_app_list"):
                raw_v = "\n".join(str(x).strip() for x in raw_v if str(x).strip())
            normalized[mapped_k] = raw_v

        merged = self.settings.to_dict()
        merged.update(normalized)
        if "selected_profile_uid" not in normalized:
            merged["selected_profile_uid"] = cur_uid
        if "selected_index" not in normalized:
            merged["selected_index"] = cur_idx

        self.settings = EngineSettings.from_dict(merged)
        self._save_settings(self.settings)
        self.snapshot.tun_enabled = self.settings.tun_enabled
        self.snapshot.system_proxy_enabled = self.settings.system_proxy_enabled
        self._sync_per_app_gateway()

        self.emit_log(
            f"[Settings] Applied (AutoCleanIP={self.settings.auto_clean_ip}, "
            f"PerApp={self.settings.per_app_mode}, Routing={self.settings.routing_mode}, "
            f"Mode={self.settings.engine_mode})"
        )

        hot_reload_keys = {
            "routing_mode", "block_quic", "remote_dns", "domestic_dns",
            "custom_direct_domains", "custom_proxy_domains", "custom_blocked_domains",
            "fingerprint", "alpn_override", "mux_enabled", "mux_concurrency",
            "per_app_mode", "per_app_list",
        }
        needs_xray_reload = any(k in normalized for k in hot_reload_keys)

        if "tun_enabled" in normalized and (bool(normalized["tun_enabled"]) != prev_tun):
            self.set_tun_mode(bool(normalized["tun_enabled"]))

        if self.snapshot.is_connected:
            if needs_xray_reload and (self._active_runtime_node is not None) and (not self.tun.active):
                try:
                    self.xray.ensure_running(uri=self._active_runtime_node.uri, settings=self.settings)
                    self._sync_per_app_gateway()
                except Exception as exc:
                    self.emit_log(f"[Xray] Hot-reload warning: {exc}")
            if self.settings.system_proxy_enabled != prev_sys_proxy or needs_xray_reload:
                WindowsSystemProxy.apply(self._should_enable_global_wininet_proxy(), self._effective_system_proxy_port())

        self._notify_settings_updated()
        self._push_telemetry()

    def get_config_editable(self, index_or_uid: Any) -> dict:
        nd = self._find_visible_node(index_or_uid)
        if nd is None:
            return UriConfigCodec.parse_to_editable(
                "vless://00000000-0000-0000-0000-000000000000@example.com:443?security=tls&type=ws#New"
            )
        ed = UriConfigCodec.parse_to_editable(
            nd.uri,
            uid=nd.uid,
            group_tag=nd.group_tag,
            preferred_vec=nd.cached_vector_id or "AUTO",
        )
        if nd.cached_clean_ip and CleanIpScanner.is_cdn_eligible(nd):
            ed["address"] = nd.cached_clean_ip
        return ed

    def save_config_editable(self, index_or_uid: Any, data: dict) -> bool:
        try:
            raw_override = str(data.get("raw_uri", "")).strip()
            use_raw = bool(data.get("use_raw_uri", False))
            rebuilt_uri = raw_override if (use_raw and bool(raw_override)) else UriConfigCodec.build_uri_from_editable(data)

            group = str(data.get("group") or data.get("group_tag") or "Manual").strip() or "Manual"
            pref_vec = str(data.get("preferred_vector_id", "")).strip()
            if pref_vec == "AUTO":
                pref_vec = ""

            parsed_node = UriConfigCodec.extract_profile_node(rebuilt_uri, group_tag=group)
            parsed_node.cached_vector_id = pref_vec

            target_node = self._find_visible_node(index_or_uid)
            with self._repo_lock:
                if target_node is not None:
                    raw_idx = self.profiles.index(target_node)
                    parsed_node.uid = target_node.uid
                    old_host = target_node.cached_clean_ip if target_node.cached_clean_ip else target_node.original_host
                    if parsed_node.original_host == old_host:
                        parsed_node.last_ping_ms = target_node.last_ping_ms
                        parsed_node.health_status = target_node.health_status
                        parsed_node.gemini_status = target_node.gemini_status
                    self.profiles[raw_idx] = parsed_node
                    self.emit_log(f"[Repository] Updated configuration for '{parsed_node.name}'.")
                else:
                    self.profiles.insert(0, parsed_node)
                    self.selected_index = 0
                    self.emit_log(f"[Repository] Created new profile '{parsed_node.name}'.")

            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self._push_telemetry()
            return True
        except Exception as exc:
            self.emit_log(f"[Editor] Validation failed: {exc}")
            return False

    def clear_all_configs(self) -> int:
        if self.snapshot.is_connected or self.snapshot.is_connecting:
            self.request_disconnect()
        with self._repo_lock:
            visible_count = len([p for p in self.profiles if not p.is_hidden_pool])
            self.profiles = [p for p in self.profiles if p.is_hidden_pool]
            self.verified_outputs.clear()
            self.selected_index = 0
        self._save_profiles(self.profiles)
        self._notify_profiles_updated()
        self._notify_verified_outputs_updated()
        self._push_telemetry()
        self.emit_log(f"[Repository] Cleared all {visible_count} profile(s) from repository.")
        return visible_count

    def import_configs(self, raw_text: str, group_tag: str = "Manual") -> int:
        uris = UriConfigCodec.extract_uris_from_blob(raw_text)
        if not uris:
            return 0
        added = 0
        with self._repo_lock:
            existing_uris = {p.uri for p in self.profiles if not p.is_hidden_pool}
            for candidate in uris:
                if candidate in existing_uris:
                    continue
                try:
                    node = UriConfigCodec.extract_profile_node(candidate, group_tag=group_tag)
                    self.profiles.append(node)
                    existing_uris.add(candidate)
                    added += 1
                except Exception as exc:
                    self.emit_log(f"[Import] Rejected malformed URI: {exc}")

        if added > 0:
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self.emit_log(f"[Repository] Added {added} profile(s) under group '{group_tag}'.")
        return added

    def import_configs_from_file(self, file_path: str) -> int:
        if (not file_path) or (not os.path.exists(file_path)):
            return 0
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return self.import_configs(content, group_tag=os.path.basename(file_path))
        except Exception as exc:
            self.emit_log(f"[Import] File read error: {exc}")
            return 0

    def add_subscription(self, url: str, title: str = "Subscription") -> int:
        clean_url = (url or "").strip()
        if not clean_url.startswith(("http://", "https://")):
            return 0
        with self._repo_lock:
            existing = next((s for s in self.subscriptions if s.url == clean_url), None)
            if existing is None:
                existing = SubscriptionItem(url=clean_url, title=(title or "Subscription").strip() or "Subscription")
                self.subscriptions.append(existing)
                self._save_subscriptions()
                self._notify_subscriptions_updated()

        threading.Thread(target=self._pull_single_subscription, args=(existing,), daemon=True).start()
        return 1

    def _pull_single_subscription(self, sub: SubscriptionItem) -> int:
        self._emit_task_progress(True, 30, f"دریافت اشتراک «{sub.title}»...")
        try:
            sess = requests.Session()
            sess.trust_env = False
            sess.headers.update({"User-Agent": "v2rayNG/1.9.5"})
            if self.snapshot.is_connected:
                px = f"http://127.0.0.1:{self.xray.active_http_port}"
                sess.proxies = {"http": px, "https": px}
            try:
                resp = sess.get(sub.url, timeout=12.0)
            except Exception:
                sess.proxies = {}
                resp = sess.get(sub.url, timeout=12.0)
            finally:
                sess.close()

            if (resp.status_code == 200) and bool(resp.text):
                uris = UriConfigCodec.extract_uris_from_blob(resp.text)
                if uris:
                    new_nodes = [UriConfigCodec.extract_profile_node(u, group_tag=sub.title) for u in uris]
                    with self._repo_lock:
                        self.profiles = [p for p in self.profiles if p.is_hidden_pool or (p.group_tag != sub.title)]
                        self.profiles.extend(new_nodes)
                        sub.last_updated_ts = int(time.time())
                        sub.node_count = len(new_nodes)
                    self._save_profiles(self.profiles)
                    self._save_subscriptions()
                    self._notify_subscriptions_updated()
                    self._notify_profiles_updated()
                    self._emit_task_progress(False, 100, f"اشتراک «{sub.title}» به‌روزرسانی شد ({len(new_nodes)} کانفیگ)")
                    return len(new_nodes)
        except Exception as exc:
            self.emit_log(f"[Subscription] Failed fetching '{sub.title}': {exc}")
        self._emit_task_progress(False, 0, f"خطا در دریافت اشتراک «{sub.title}»")
        return 0

    def refresh_subscriptions(self):
        self.refresh_all_subscriptions()

    def refresh_all_subscriptions(self):
        def _bg():
            with self._repo_lock:
                subs_list = [s for s in self.subscriptions if s.enabled]
            if not subs_list:
                return
            self._task_abort_flag = False
            total_added = 0
            for idx, sub in enumerate(subs_list, 1):
                if self._task_abort_flag or self._shutdown_flag:
                    break
                pct = int((idx / len(subs_list)) * 90)
                self._emit_task_progress(True, pct, f"به‌روزرسانی اشتراک ({idx}/{len(subs_list)}): {sub.title}...")
                total_added += self._pull_single_subscription(sub)
            self._emit_task_progress(False, 100, f"به‌روزرسانی اشتراک‌ها کامل شد ({total_added} نود فعال)")

        threading.Thread(target=_bg, daemon=True).start()

    def delete_subscription(self, index: int):
        with self._repo_lock:
            if 0 <= index < len(self.subscriptions):
                removed = self.subscriptions.pop(index)
                self.profiles = [p for p in self.profiles if p.is_hidden_pool or (p.group_tag != removed.title)]
                self._save_subscriptions()
                self._save_profiles(self.profiles)
                self._notify_subscriptions_updated()
                self._notify_profiles_updated()
                self.emit_log(f"[Subscription] Removed feed: {removed.title}")

    def delete_configs(self, uid_or_index_list: list) -> int:
        targets = set()
        for item in uid_or_index_list:
            nd = self._find_visible_node(item)
            if nd is not None:
                targets.add(nd.uid)
        if not targets:
            return 0
        with self._repo_lock:
            before = len(self.profiles)
            self.profiles = [p for p in self.profiles if p.uid not in targets]
            self.verified_outputs = [v for v in self.verified_outputs if v.profile_uid not in targets]
            removed = before - len(self.profiles)
        if removed > 0:
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self._notify_verified_outputs_updated()
            self._push_telemetry()
            self.emit_log(f"[Repository] Deleted {removed} selected profile(s).")
        return removed

    def delete_config(self, index_or_uid: Any) -> int:
        return self.delete_configs([index_or_uid])

    def rename_config(self, index_or_uid: Any, new_name: str):
        nd = self._find_visible_node(index_or_uid)
        if (nd is not None) and bool((new_name or "").strip()):
            with self._repo_lock:
                nd.name = new_name.strip()
                nd.uri = self._update_uri_remark(nd.uri, nd.name)
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()

    def select_config(self, index_or_uid: Any):
        token = str(index_or_uid).strip()
        if token.upper() in ("__SMART_AUTO__", "AUTO", "SMART_AUTO", "-1", ""):
            self.settings.selected_profile_uid = "__SMART_AUTO__"
            self.settings.autopilot_enabled = True
            self.selected_index = -1
            self._notify_settings_updated()
            self._notify_profiles_updated(save_selection=True)
            self._push_telemetry()
            self.emit_log("[AutoPool] Switched to exclusive Auto-Repository mode.")
            return

        idx = self._resolve_profile_index(index_or_uid)
        visible = self.get_visible_profiles()
        if 0 <= idx < len(visible):
            self.selected_index = idx
            self.settings.selected_profile_uid = visible[idx].uid
            self.settings.selected_index = idx
            self.settings.autopilot_enabled = False
            self._notify_settings_updated()
            self._notify_profiles_updated(save_selection=True)
            self._push_telemetry()
            self.emit_log(f"[Repository] Selected user node: {visible[idx].name}")

    def deduplicate_configs(self) -> int:
        with self._repo_lock:
            seen = set()
            unique_list: List[ProfileNode] = []
            removed = 0
            for node in self.profiles:
                if node.is_hidden_pool:
                    unique_list.append(node)
                    continue
                base_sig = (node.protocol, node.original_host.lower(), node.port, node.sni.lower(), node.uri.split("#")[0].strip())
                if base_sig in seen:
                    removed += 1
                else:
                    seen.add(base_sig)
                    unique_list.append(node)
            if removed > 0:
                self.profiles = unique_list
        if removed > 0:
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self.emit_log(f"[Repository] Deduplicated {removed} identical profile(s).")
        return removed

    def remove_dead_configs(self) -> int:
        with self._repo_lock:
            alive = [p for p in self.profiles if p.is_hidden_pool or (p.health_status != "DEAD")]
            removed = len(self.profiles) - len(alive)
            if removed > 0:
                self.profiles = alive
        if removed > 0:
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self.emit_log(f"[Repository] Purged {removed} dead profile(s).")
        return removed

    def sort_configs(self, sort_by: str = "ping"):
        with self._repo_lock:
            hidden = [p for p in self.profiles if p.is_hidden_pool]
            visible = [p for p in self.profiles if not p.is_hidden_pool]
            if sort_by == "ping":
                visible.sort(
                    key=lambda n: (
                        0 if (n.health_status == "VERIFIED") else (1 if (n.health_status == "HEALTHY") else 2),
                        n.last_ping_ms if (n.last_ping_ms > 0) else 999999,
                        n.name.lower(),
                    )
                )
            elif sort_by == "name":
                visible.sort(key=lambda n: n.name.lower())
            elif sort_by == "protocol":
                visible.sort(key=lambda n: (n.protocol, n.last_ping_ms if (n.last_ping_ms > 0) else 999999))
            self.profiles = visible + hidden
        self._save_profiles(self.profiles)
        self._notify_profiles_updated()

    def _normalize_target_nodes(self, uid_list: Any) -> List[ProfileNode]:
        visible = self.get_visible_profiles()
        if (uid_list is None) or isinstance(uid_list, bool) or (uid_list == ""):
            return visible
        raw_items = [uid_list] if isinstance(uid_list, (str, int, dict)) else list(uid_list)
        cleaned = [x for x in raw_items if not isinstance(x, bool)]
        if not cleaned:
            return visible

        matched: List[ProfileNode] = []
        seen_uids = set()
        for item in cleaned:
            if isinstance(item, dict):
                key = item.get("profile_uid") or item.get("uid") or item.get("index")
            else:
                key = item
            if key is None:
                continue
            nd = self._find_visible_node(key)
            if nd is None and isinstance(key, str):
                nd = next((p for p in visible if p.uri.strip() == key.strip()), None)
            if (nd is not None) and (nd.uid not in seen_uids):
                seen_uids.add(nd.uid)
                matched.append(nd)
        return matched

    def ping_configs(self, uid_list: Optional[Any] = None, check_gemini: bool = False):
        def _real_ping_worker():
            targets = self._normalize_target_nodes(uid_list)
            total = len(targets)
            if total == 0:
                self._emit_task_progress(False, 0, "کانفیگی برای تست یافت نشد")
                return

            self._task_abort_flag = False
            mode_title = "تست دقیق Gemini و پینگ واقعی" if check_gemini else "پینگ واقعی تونل"
            self._emit_task_progress(True, 8, f"در حال اجرای {mode_title} روی {total} کانفیگ...")

            def _apply_partial(chunk_map: Dict[str, Tuple[int, str]]):
                now_ts = int(time.time())
                vo_changed = False
                with self._repo_lock:
                    for nd in targets:
                        if nd.uid in chunk_map:
                            rtt, gem_stat = chunk_map[nd.uid]
                            nd.last_ping_ms = rtt
                            if check_gemini or (gem_stat in ("OK", "BLOCKED")):
                                nd.gemini_status = gem_stat
                            nd.last_tested_ts = now_ts
                            nd.health_status = ("VERIFIED" if nd.cached_vector_id else "HEALTHY") if (rtt > 0) else "DEAD"
                            for vo in self.verified_outputs:
                                if vo.profile_uid == nd.uid:
                                    vo.ping_ms = rtt
                                    if check_gemini:
                                        vo.gemini_status = nd.gemini_status
                                    vo_changed = True
                    if vo_changed:
                        self.verified_outputs.sort(key=lambda x: x.ping_ms if (x.ping_ms > 0) else 999999)
                self._save_profiles(self.profiles)
                self._notify_profiles_updated(save_selection=False)
                if vo_changed:
                    self._notify_verified_outputs_updated()

            res_map = self.xray.batch_real_ping_and_gemini(
                nodes=targets,
                settings=self.settings,
                shared_cdn_ip="",
                check_gemini=check_gemini,
                chunk_size=8,
                abort_check=lambda: (self._task_abort_flag or self._shutdown_flag),
                progress_cb=lambda p, m: self._emit_task_progress(True, p, m),
                on_chunk_done=_apply_partial,
            )

            alive_count = sum(1 for rtt, _ in res_map.values() if rtt > 0)
            is_full_list = len(targets) == len(self.get_visible_profiles())
            if is_full_list and (len(targets) > 1):
                self.sort_configs("ping")
            else:
                self._save_profiles(self.profiles)
                self._notify_profiles_updated(save_selection=False)

            if check_gemini:
                gem_ok_cnt = sum(1 for rtt, gm in res_map.values() if (rtt > 0 and gm == "OK"))
                summary = f"تست پایان یافت: {alive_count} فعال | {gem_ok_cnt} سازگار با Gemini"
            else:
                summary = f"پینگ پایان یافت: {alive_count} از {total} کانفیگ پاسخ دادند"
            self.emit_log(f"[Ping] {summary}")
            self._emit_task_progress(False, 100, summary)

        threading.Thread(target=_real_ping_worker, daemon=True).start()

    def quick_ping_repository(self):
        self.ping_configs(uid_list=None, check_gemini=False)

    def clone_config_with_clean_ips(self, index_or_uid: Any, clone_count: int = 3):
        base_ref = self._find_visible_node(index_or_uid)
        if base_ref is None:
            return
        base_node = copy.deepcopy(base_ref)

        def _clone_worker():
            self._task_abort_flag = False
            self._emit_task_progress(True, 10, f"یافتن {clone_count} آی‌پی تمیز برتر برای کلون «{base_node.name}»...")
            edges = CleanIpScanner.discover_best_ips(
                port=base_node.port,
                top_n=clone_count,
                sample_count=36,
                progress_cb=lambda p, m: self._emit_task_progress(True, p, m),
                abort_check=lambda: (self._task_abort_flag or self._shutdown_flag),
            )
            if self._task_abort_flag:
                self._emit_task_progress(False, 0, "عملیات کلون لغو شد")
                return

            created = 0
            with self._repo_lock:
                for rank, (ip_addr, tls_ms) in enumerate(edges, 1):
                    cloned_name = f"{base_node.name} [Edge-{rank} | {tls_ms}ms]"
                    cloned_uri = self._replace_uri_endpoint_ip(base_node.uri, ip_addr)
                    cloned_uri = self._update_uri_remark(cloned_uri, cloned_name)
                    new_node = UriConfigCodec.extract_profile_node(cloned_uri, group_tag="Optimized-Clones")
                    new_node.cached_clean_ip = ip_addr
                    new_node.cached_vector_id = base_node.cached_vector_id
                    new_node.last_ping_ms = tls_ms
                    new_node.health_status = "HEALTHY"
                    self.profiles.insert(created, new_node)
                    created += 1

            if created > 0:
                self._save_profiles(self.profiles)
                self._notify_profiles_updated()
                self.emit_log(f"[Repository] Created {created} optimized Clean-IP clone(s).")
            self._emit_task_progress(False, 100, f"{created} کلون بهینه با آی‌پی تمیز ساخته شد")

        threading.Thread(target=_clone_worker, daemon=True).start()

    def export_configs(self, mode: str = "verified", inject_early_data: int = 0) -> str:
        lines: List[str] = []
        for node in self.get_visible_profiles():
            if (mode == "verified") and (node.health_status not in ("VERIFIED", "HEALTHY")):
                continue
            lines.append(self._build_exportable_node_uri(node, inject_early_data=inject_early_data))
        return "\n".join(lines)

    def apply_clean_ip(self, ip_addr: str, apply_all_cdn: bool = True) -> int:
        return self.apply_clean_ip_to_repository(clean_ip=ip_addr, only_selected=(not apply_all_cdn))

    def apply_clean_ip_to_repository(self, clean_ip: str, only_selected: bool = False) -> int:
        ip_val = (clean_ip or "").strip().split(":")[0]
        if not ip_val:
            return 0
        updated = 0
        with self._repo_lock:
            visible = [p for p in self.profiles if not p.is_hidden_pool]
            if not visible:
                return 0
            sel = max(0, min(self.selected_index, len(visible) - 1))
            targets = [visible[sel]] if only_selected else visible
            for node in targets:
                if CleanIpScanner.is_cdn_eligible(node):
                    node.cached_clean_ip = ip_val
                    updated += 1
        if updated > 0:
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self.emit_log(f"[Patch] Applied Clean IP {ip_val} onto {updated} CDN-eligible profile(s).")
            self._emit_task_progress(False, 100, f"آی‌پی تمیز {ip_val} روی {updated} کانفیگ CDN اعمال شد")
        return updated

    def apply_scanned_vector(self, vector_id: str, target_uid: str = "", connect_now: bool = False):
        target_key: Any = target_uid if target_uid else self.get_selected_index()
        self.bind_vector_to_profile(vector_id=vector_id, target_index=target_key, connect_now=connect_now)

    def bind_vector_to_profile(
        self,
        vector_id: str,
        target_index: Any = -1,
        clean_ip: str = "",
        connect_now: bool = False,
    ):
        clean_ep = (clean_ip or "").strip().split(":")[0]
        node = self._find_visible_node(target_index)
        if node is None:
            node = self._find_visible_node(self.get_selected_index())
        if node is None:
            return

        with self._repo_lock:
            node.cached_vector_id = "" if (vector_id == "AUTO") else vector_id
            if bool(clean_ep) and (clean_ep != node.original_host) and CleanIpScanner.is_cdn_eligible(node):
                node.cached_clean_ip = clean_ep
            node_name = node.name
            node_uid = node.uid

        vec_obj = find_vector(vector_id)
        self._save_profiles(self.profiles)
        self._notify_profiles_updated()
        self.emit_log(f"[Patch] Bound {vec_obj.vector_id} ({vec_obj.code_name}) -> '{node_name}'.")
        self._emit_task_progress(False, 100, f"متد {vec_obj.vector_id} روی «{node_name}» اعمال شد")

        if connect_now:
            self.select_config(node_uid)
            self.request_connect()

    def apply_vector_to_all_configs(self, vector_id: str, clean_ip: str = "") -> int:
        clean_ep = (clean_ip or "").strip().split(":")[0]
        vec_val = "" if (vector_id == "AUTO") else vector_id
        count = 0
        with self._repo_lock:
            for node in self.profiles:
                if node.is_hidden_pool:
                    continue
                if (node.protocol.upper() == "SHADOWSOCKS") and (vec_val not in ("", "VEC-00")):
                    continue
                node.cached_vector_id = vec_val
                if bool(clean_ep) and (clean_ep != node.original_host) and CleanIpScanner.is_cdn_eligible(node):
                    node.cached_clean_ip = clean_ep
                count += 1
        if count > 0:
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            vec_obj = find_vector(vector_id)
            self.emit_log(f"[Patch] Applied {vec_obj.vector_id} ({vec_obj.code_name}) across {count} profiles.")
            self._emit_task_progress(False, 100, f"متد {vec_obj.vector_id} روی {count} کانفیگ مخزن وصله شد")
        return count

    def _promote_node_to_verified_outputs(
        self,
        node: ProfileNode,
        vec: BypassVector,
        endpoint_host: str,
        ping_ms: int,
        upload_kbps: float = 0.0,
    ):
        if node.is_hidden_pool:
            return
        with self._repo_lock:
            existing = next((v for v in self.verified_outputs if v.profile_uid == node.uid), None)
            item = VerifiedOutputItem(
                uid=existing.uid if (existing is not None) else f"vo_{node.uid}",
                profile_uid=node.uid,
                name=node.name,
                protocol=node.protocol,
                uri=node.uri,
                endpoint_host=endpoint_host,
                port=node.port,
                sni=node.sni,
                vector_id=vec.vector_id,
                vector_name=vec.code_name,
                ping_ms=ping_ms,
                upload_kbps=upload_kbps,
                gemini_status=node.gemini_status,
                country_code=node.country_code,
                group_tag=node.group_tag,
                verified_ts=int(time.time()),
            )
            if existing is not None:
                pos = self.verified_outputs.index(existing)
                self.verified_outputs[pos] = item
            else:
                self.verified_outputs.insert(0, item)
            self.verified_outputs.sort(key=lambda x: x.ping_ms if (x.ping_ms > 0) else 999999)
        self._notify_verified_outputs_updated()

    def connect_verified_output(self, uid_or_index: Any):
        target: Optional[VerifiedOutputItem] = None
        with self._repo_lock:
            if isinstance(uid_or_index, int) and (0 <= uid_or_index < len(self.verified_outputs)):
                target = self.verified_outputs[uid_or_index]
            else:
                key = str(uid_or_index).strip()
                target = next((v for v in self.verified_outputs if (v.uid == key) or (v.profile_uid == key)), None)
        if target is None:
            self.request_connect()
            return
        nd = self._find_visible_node(target.profile_uid)
        if nd is not None:
            nd.cached_vector_id = target.vector_id
            if (target.endpoint_host != nd.original_host) and CleanIpScanner.is_cdn_eligible(nd):
                nd.cached_clean_ip = target.endpoint_host
            self.select_config(nd.uid)
            self.request_connect()
        else:
            self.request_connect(uri=target.uri)

    def ping_verified_outputs(self):
        with self._repo_lock:
            uids = [v.profile_uid for v in self.verified_outputs]
        if uids:
            self.ping_configs(uid_list=uids, check_gemini=False)

    def clear_verified_outputs(self):
        with self._repo_lock:
            self.verified_outputs.clear()
        self._notify_verified_outputs_updated()

    def connect_scanned_profile(self, target_index_or_uid: Any, vector_id: str = "", clean_ip: str = ""):
        clean_ep = (clean_ip or "").strip().split(":")[0]
        nd = self._find_visible_node(target_index_or_uid)
        if nd is None:
            return
        with self._repo_lock:
            if bool(vector_id) and (vector_id != "AUTO"):
                nd.cached_vector_id = vector_id
            if bool(clean_ep) and (clean_ep != nd.original_host) and CleanIpScanner.is_cdn_eligible(nd):
                nd.cached_clean_ip = clean_ep
        self._save_profiles(self.profiles)
        self.select_config(nd.uid)
        self.request_connect()

    def hunt_subscription_and_connect(self, sub_url_or_title: Any = "", title: str = ""):
        if self.snapshot.is_connecting or self.snapshot.is_connected:
            self._teardown_active_tunnel_sync()

        with self._state_lock:
            self._op_generation += 1
            gen_id = self._op_generation
            self._abort_flag = False
            self._scan_abort_flag = False
            self._task_abort_flag = False

        self._set_state(
            EngineState.HUNTING_BEST,
            "پویش کامل اشتراک و اتصال به برترین کانفیگ...",
            "دریافت و غربالگری موازی تمام کانفیگ‌های اشتراک",
            progress=5,
        )
        self._emit_task_progress(True, 5, "آماده‌سازی پویش کامل اشتراک...")

        self._worker_thread = threading.Thread(
            target=self._run_subscription_hunt_pipeline,
            args=(gen_id, sub_url_or_title, title),
            daemon=True,
        )
        self._worker_thread.start()

    def _run_subscription_hunt_pipeline(self, gen_id: int, sub_url_or_title: Any, custom_title: str = ""):
        try:
            target_sub: Optional[SubscriptionItem] = None
            group_label = (custom_title or "").strip()

            if isinstance(sub_url_or_title, int):
                with self._repo_lock:
                    if 0 <= sub_url_or_title < len(self.subscriptions):
                        target_sub = self.subscriptions[sub_url_or_title]
            else:
                raw_key = str(sub_url_or_title or "").strip()
                if raw_key.lower().startswith(("http://", "https://")):
                    with self._repo_lock:
                        target_sub = next((s for s in self.subscriptions if s.url == raw_key), None)
                        if target_sub is None:
                            auto_title = group_label or f"Sub-{len(self.subscriptions) + 1}"
                            target_sub = SubscriptionItem(url=raw_key, title=auto_title)
                            self.subscriptions.append(target_sub)
                            self._save_subscriptions()
                            self._notify_subscriptions_updated()
                elif raw_key:
                    with self._repo_lock:
                        target_sub = next(
                            (s for s in self.subscriptions if s.title.lower() == raw_key.lower() or s.url == raw_key),
                            None,
                        )
                    if target_sub is None:
                        group_label = raw_key
                else:
                    with self._repo_lock:
                        if self.subscriptions:
                            target_sub = self.subscriptions[0]

            if target_sub is not None:
                group_label = target_sub.title
                self._set_state(
                    EngineState.HUNTING_BEST,
                    f"دریافت آخرین کانفیگ‌های «{group_label}»...",
                    "بروزرسانی لینک اشتراک قبل از شروع شکار",
                    progress=10,
                )
                self._pull_single_subscription(target_sub)

            if self._is_op_cancelled(gen_id):
                return

            visible = self.get_visible_profiles()
            if group_label and (group_label not in ("All", "همه")):
                sub_nodes = [p for p in visible if p.group_tag.lower() == group_label.lower()]
            else:
                sub_nodes = visible

            if not sub_nodes:
                self._emit_task_progress(False, 0, "کانفیگی در این اشتراک یافت نشد")
                self._set_state(EngineState.ERROR, "اشتراک خالی است", "هیچ کانفیگ معتبری در این لینک ساب یافت نشد", 0)
                return

            total_sub = len(sub_nodes)
            self._set_state(
                EngineState.HUNTING_BEST,
                f"پینگ موازی {total_sub} کانفیگ در «{group_label or 'اشتراک'}»...",
                "تست واقعی تونل با اولویت هاست اصلی (Origin-First)",
                progress=22,
            )

            def _prog_ping(p_val: int, p_msg: str):
                scaled = 22 + int((p_val / 100.0) * 42)
                self._emit_task_progress(True, scaled, f"[{group_label}] {p_msg}")
                self._set_state(EngineState.HUNTING_BEST, f"پویش اشتراک «{group_label}»...", p_msg, scaled)

            ping_map = self.xray.batch_real_ping_and_gemini(
                nodes=sub_nodes,
                settings=self.settings,
                shared_cdn_ip="",
                check_gemini=False,
                chunk_size=10,
                abort_check=lambda: self._is_op_cancelled(gen_id),
                progress_cb=_prog_ping,
            )

            if self._is_op_cancelled(gen_id):
                return

            alive_nodes: List[ProfileNode] = []
            now_ts = int(time.time())
            with self._repo_lock:
                for nd in sub_nodes:
                    rtt, _ = ping_map.get(nd.uid, (-1, "UNKNOWN"))
                    nd.last_ping_ms = rtt
                    nd.last_tested_ts = now_ts
                    if rtt > 0:
                        nd.health_status = "HEALTHY"
                        alive_nodes.append(nd)
                    else:
                        nd.health_status = "DEAD"

            self.sort_configs("ping")

            if not alive_nodes:
                for cand in sub_nodes[:8]:
                    if self._is_op_cancelled(gen_id):
                        return
                    if self._execute_autopilot_pipeline(gen_id, cand, max_vectors=8, force_auto_vectors=True):
                        self.select_config(cand.uid)
                        return
                self._emit_task_progress(False, 0, "هیچ کانفیگ فعالی در این اشتراک پاسخ نداد")
                self._set_state(EngineState.ERROR, "کانفیگ فعالی در ساب یافت نشد", "تمام سرورهای این اشتراک بررسی شدند", 0)
                return

            alive_nodes.sort(key=lambda n: n.last_ping_ms if n.last_ping_ms > 0 else 999999)
            for rank_i, best_cand in enumerate(alive_nodes[:6], 1):
                if self._is_op_cancelled(gen_id):
                    return
                pct = 68 + int((rank_i / min(6, len(alive_nodes))) * 28)
                self._set_state(
                    EngineState.VERIFYING_STABILITY,
                    f"تایید نهایی رتبه #{rank_i} اشتراک «{group_label}»...",
                    f"کانفیگ «{best_cand.name}» ({best_cand.last_ping_ms}ms)",
                    progress=pct,
                )
                if self._execute_autopilot_pipeline(gen_id, best_cand, max_vectors=10, force_auto_vectors=True):
                    self.settings.autopilot_enabled = False
                    self.settings.selected_profile_uid = best_cand.uid
                    self._save_settings(self.settings)
                    self._notify_settings_updated()
                    self._notify_profiles_updated(save_selection=True)
                    self.emit_log(f"[SubHunter] Connected to #1 config in '{group_label}': {best_cand.name} ({best_cand.last_ping_ms}ms)")
                    return

            self._emit_task_progress(False, 0, "پایداری استریم روی کاندیدهای ساب تایید نشد")
            self._set_state(EngineState.ERROR, "اتصال پایدار برقرار نشد", "سرورهای ساب پینگ دادند اما استریم را عبور ندادند", 0)
        except Exception as exc:
            self.emit_log(f"[SubHunter] Error: {exc}")
            if not self._is_op_cancelled(gen_id):
                self._set_state(EngineState.ERROR, "خطا در پویش اشتراک", str(exc), 0)

    def hunt_best_and_connect(self):
        visible = self.get_visible_profiles()
        if (not visible) and (not self.hidden_pool):
            self._sync_hidden_auto_pool()
            if (not self.get_visible_profiles()) and (not self.hidden_pool):
                self._set_state(EngineState.ERROR, "مخزن خالی است", "ابتدا کانفیگ یا لینک ساب وارد کنید", 0)
                return

        if self.snapshot.is_connecting or self.snapshot.is_connected:
            self._teardown_active_tunnel_sync()

        with self._state_lock:
            self._op_generation += 1
            gen_id = self._op_generation
            self._abort_flag = False
            self._scan_abort_flag = False
            self._task_abort_flag = False

        self._set_state(
            EngineState.HUNTING_BEST,
            "شکار هوشمند برترین کانفیگ...",
            "پویش موازی کانفیگ‌ها، لبه‌های شبکه و متدهای عبوری",
            progress=5,
        )
        self._emit_task_progress(True, 5, "شروع شکار خودکار برترین مسیر...")

        self._worker_thread = threading.Thread(
            target=self._run_hunt_best_pipeline,
            args=(gen_id,),
            daemon=True,
        )
        self._worker_thread.start()

    def _run_hunt_best_pipeline(self, gen_id: int):
        try:
            loc_code = "ALL"
            if self.is_auto_repo_mode():
                if not self.hidden_pool:
                    self._sync_hidden_auto_pool()
                pool_filtered, loc_code = self._filter_hidden_pool_by_location()
                verified_h = [n for n in pool_filtered if n.health_status == "VERIFIED"]
                others_h = [n for n in pool_filtered if n.health_status != "VERIFIED"]
                random.shuffle(others_h)
                all_nodes = verified_h + others_h[:96]
            else:
                all_nodes = self.get_visible_profiles()

            total_nodes = len(all_nodes)
            if total_nodes == 0:
                if loc_code != "ALL":
                    _, fa_n = LocationExtractor.get_country_names(loc_code)
                    self._set_state(EngineState.ERROR, f"سروری برای {fa_n} ({loc_code}) یافت نشد", "لوکیشن دیگری انتخاب کنید", 0)
                else:
                    self._set_state(EngineState.ERROR, "مخزن خالی است", "کانفیگی برای شکار یافت نشد", 0)
                return

            loc_title = ""
            if loc_code != "ALL":
                _, fa_loc = LocationExtractor.get_country_names(loc_code)
                loc_title = f" [{fa_loc} • {loc_code}]"

            self._set_state(EngineState.HUNTING_BEST, f"پالایش سرورها{loc_title}...", f"بررسی مستقیم هاست اصلی روی {total_nodes} سرور", 18)
            self._emit_task_progress(True, 18, f"غربالگری مستقیم هاست اصلی روی {total_nodes} سرور{loc_title}...")

            def _fast_eval(nd: ProfileNode):
                if not CleanIpScanner.is_cdn_eligible(nd):
                    nd.cached_clean_ip = ""
                orig_ep = self._resolve_origin_endpoint(nd)
                if orig_ep:
                    ms = CleanIpScanner.fast_tcp_ping(orig_ep, nd.port, timeout=1.5)
                    if ms >= 0:
                        return ms, nd, orig_ep
                if nd.cached_clean_ip and CleanIpScanner.is_cdn_eligible(nd):
                    ms_c = CleanIpScanner.fast_tcp_ping(nd.cached_clean_ip, nd.port, timeout=1.4)
                    if ms_c >= 0:
                        return ms_c, nd, nd.cached_clean_ip
                return -1, nd, ""

            prior_verified: List[Tuple[int, ProfileNode, str]] = []
            foreign_candidates: List[Tuple[int, ProfileNode, str]] = []
            domestic_candidates: List[Tuple[int, ProfileNode, str]] = []
            blocked_cdn_nodes: List[ProfileNode] = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=18) as pool:
                for ms, nd, ep in pool.map(_fast_eval, all_nodes):
                    if ms < 0:
                        if self.settings.auto_clean_ip and CleanIpScanner.is_cdn_eligible(nd):
                            blocked_cdn_nodes.append(nd)
                        else:
                            nd.health_status = "DEAD"
                            nd.last_ping_ms = -1
                        continue
                    if (nd.health_status == "VERIFIED") or bool(nd.cached_vector_id):
                        prior_verified.append((ms, nd, ep))
                    elif CleanIpScanner.is_domestic_or_direct_tunnel(nd):
                        domestic_candidates.append((ms, nd, ep))
                    else:
                        foreign_candidates.append((ms, nd, ep))

            if self._is_op_cancelled(gen_id):
                return

            prior_verified.sort(key=lambda x: x[0])
            foreign_candidates.sort(key=lambda x: x[0])
            domestic_candidates.sort(key=lambda x: x[0])

            shortlist: List[Tuple[int, ProfileNode, str]] = []
            shortlist.extend(prior_verified[:5])
            shortlist.extend(foreign_candidates[:8])
            shortlist.extend(domestic_candidates[:4])

            port_edge_cache: Dict[int, List[str]] = {}
            if (len(shortlist) < 4) and blocked_cdn_nodes and self.settings.auto_clean_ip:
                for cdn_nd in blocked_cdn_nodes[:6]:
                    if self._is_op_cancelled(gen_id):
                        return
                    fb_ips = self._discover_fallback_clean_ips(cdn_nd, gen_id, port_edge_cache=port_edge_cache, sample_count=28)
                    if fb_ips:
                        shortlist.append((250, cdn_nd, fb_ips[0]))

            if not shortlist:
                self._emit_task_progress(False, 0, "هیچ سرور در دسترسی یافت نشد")
                self._set_state(EngineState.ERROR, f"سرور فعالی یافت نشد{loc_title}", "لوکیشن دیگر یا اتصال اینترنت را بررسی کنید", 0)
                return

            qualified_winners: List[Tuple[int, float, ProfileNode, str, BypassVector]] = []
            soft_winners: List[Tuple[int, float, ProfileNode, str, BypassVector]] = []

            total_short = len(shortlist)
            for c_idx, (_, cand_node, cand_ep) in enumerate(shortlist, 1):
                if self._is_op_cancelled(gen_id):
                    return
                try:
                    self.xray.ensure_running(uri=cand_node.uri, settings=self.settings, use_native_fragment=False)
                except Exception:
                    continue

                node_plan = self._build_vector_plan(cand_node, self.settings.engine_mode)
                probe_vecs = node_plan[:3] if CleanIpScanner.is_domestic_or_direct_tunnel(cand_node) else node_plan[:5]

                endpoints_for_cand = [cand_ep]
                cand_connected = False

                for stage_idx in range(2):
                    if self._is_op_cancelled(gen_id):
                        return
                    if stage_idx == 1:
                        if cand_connected or (not self.settings.auto_clean_ip) or (not CleanIpScanner.is_cdn_eligible(cand_node)):
                            break
                        fb_ips = self._discover_fallback_clean_ips(cand_node, gen_id, port_edge_cache=port_edge_cache, sample_count=28)
                        fb_ips = [ip for ip in fb_ips if ip not in endpoints_for_cand]
                        if not fb_ips:
                            break
                        active_ep = fb_ips[0]
                    else:
                        active_ep = cand_ep

                    for v_i, vec in enumerate(probe_vecs):
                        if self._is_op_cancelled(gen_id):
                            return
                        pct = 30 + int(((c_idx - 1 + ((v_i + 1) / max(1, len(probe_vecs)))) / total_short) * 62)
                        disp_name = f"Auto-Server ({cand_node.country_code or 'GLOBAL'})" if cand_node.is_hidden_pool else cand_node.name
                        msg = f"[{c_idx}/{total_short}] تست «{disp_name}» با {vec.vector_id}..."
                        self._set_state(EngineState.HUNTING_BEST, f"شکار بهترین مسیر{loc_title}...", msg, pct)
                        self._emit_task_progress(True, pct, msg)

                        self.bridge.update_route(
                            remote_host=active_ep,
                            remote_port=cand_node.port,
                            vector=vec,
                            custom_stride=self.settings.forward_stride_bytes,
                            jitter_bytes=self.settings.stride_jitter_bytes,
                            raw_passthrough=(vec.family == "DIRECT"),
                            flush_existing_pool=True,
                        )

                        q_ok, q_ms, _ = self._probe_fast_tuple(http_port=self.xray.active_http_port, timeout=3.8)
                        if self._is_op_cancelled(gen_id):
                            return
                        if not q_ok:
                            continue

                        cand_connected = True
                        cand_node.last_ping_ms = q_ms
                        cand_node.health_status = "HEALTHY"
                        soft_winners.append((q_ms, 0.0, cand_node, active_ep, vec))

                        f_ok, f_ms, f_up, _ = self._probe_full_tuple(
                            http_port=self.xray.active_http_port,
                            verify_upload=self.settings.verify_upload_stream,
                            require_youtube_6s=self.settings.require_youtube_6s,
                            abort_check=lambda: self._is_op_cancelled(gen_id),
                        )
                        if self._is_op_cancelled(gen_id):
                            return
                        if f_ok:
                            qualified_winners.append((f_ms, f_up, cand_node, active_ep, vec))
                            break
                    if qualified_winners:
                        break
                if qualified_winners:
                    break

            if self._is_op_cancelled(gen_id):
                return

            final_pool = qualified_winners if qualified_winners else soft_winners
            if final_pool:
                final_pool.sort(key=lambda x: x[0])
                win_ms, win_up, win_node, win_ep, win_vec = final_pool[0]

                self.xray.ensure_running(uri=win_node.uri, settings=self.settings, use_native_fragment=False)
                self.bridge.update_route(
                    remote_host=win_ep,
                    remote_port=win_node.port,
                    vector=win_vec,
                    custom_stride=self.settings.forward_stride_bytes,
                    jitter_bytes=self.settings.stride_jitter_bytes,
                    raw_passthrough=(win_vec.family == "DIRECT"),
                    flush_existing_pool=True,
                )

                if not win_node.is_hidden_pool:
                    self.sort_configs("ping")
                    self.select_config(win_node.uid)

                disp = f"Smart Auto ({win_node.country_code or 'GLOBAL'})" if win_node.is_hidden_pool else win_node.name
                self._emit_task_progress(False, 100, f"متصل شد: «{disp}» ({win_ms}ms • {win_vec.vector_id})")
                self._lock_winning_tunnel(
                    gen_id=gen_id,
                    node=win_node,
                    endpoint_ip=win_ep,
                    vec=win_vec,
                    ping_ms=win_ms,
                    upload_kbps=win_up,
                    raw_passthrough=(win_vec.family == "DIRECT"),
                )
                return

            self.xray.stop()
            self._emit_task_progress(False, 0, "هیچ سرور پایداری پاسخ نداد")
            self._set_state(EngineState.ERROR, f"اتصال ناموفق بود{loc_title}", "سرورهای کاندید تونل پایدار باز نکردند", 0)
        except Exception as exc:
            self.emit_log(f"[Hunter] Unexpected error: {exc}")
            self._emit_task_progress(False, 0, f"خطا در پویش مخزن: {exc}")
            if not self._is_op_cancelled(gen_id):
                self._set_state(EngineState.ERROR, "خطا در پویش مخزن", str(exc), 0)

    def start_clean_ip_scan(self, port: int = 443):
        self.start_dedicated_scan(mode="clean_ip_radar", options={"port": int(port), "samples": 48})

    def start_lab_scan(
        self,
        scope: str = "selected",
        uid_list: Optional[list] = None,
        group_tag: str = "",
        scan_depth: str = "all",
        target_vector: str = "ALL",
        check_gemini: bool = False,
        auto_connect: bool = False,
    ):
        with self._state_lock:
            self._op_generation += 1
            gen_id = self._op_generation
            self._scan_abort_flag = False
            self._task_abort_flag = False
            self._abort_flag = False

        chosen_vec = (target_vector or "").strip().upper()
        depth_token = (scan_depth or "all").strip()
        if depth_token.upper().startswith("VEC-"):
            chosen_vec = depth_token.upper()
            depth_token = "single"
        elif chosen_vec in ("", "ALL", "AUTO", "همه", "همه متدها"):
            chosen_vec = "ALL"

        visible = self.get_visible_profiles()
        if uid_list:
            uid_set = {str(u) for u in uid_list}
            targets = [p for p in visible if p.uid in uid_set]
        elif group_tag and (group_tag not in ("All", "همه")):
            targets = [p for p in visible if p.group_tag == group_tag]
        elif scope == "full_repository":
            targets = visible
        else:
            sel = self.get_selected_index()
            targets = [visible[sel]] if (0 <= sel < len(visible)) else visible[:1]

        if (len(targets) == 1) and (chosen_vec == "ALL") and (depth_token.lower() in ("all", "full", "")):
            idx = visible.index(targets[0])
            self._worker_thread = threading.Thread(
                target=self._run_active_profile_matrix_scan,
                args=(gen_id, idx, auto_connect, check_gemini, None),
                daemon=True,
            )
            self._worker_thread.start()
            return

        if (len(targets) == 1) and chosen_vec.startswith("VEC-"):
            idx = visible.index(targets[0])
            self._worker_thread = threading.Thread(
                target=self._run_active_profile_matrix_scan,
                args=(gen_id, idx, auto_connect, check_gemini, chosen_vec),
                daemon=True,
            )
            self._worker_thread.start()
            return

        effective_mode = chosen_vec if chosen_vec.startswith("VEC-") else depth_token.lower()
        self._worker_thread = threading.Thread(
            target=self._run_lab_batch_scan_task,
            args=(gen_id, targets, effective_mode, check_gemini, auto_connect),
            daemon=True,
        )
        self._worker_thread.start()

    def start_dedicated_scan(self, mode: str = "active_profile", target_index: Any = -1, options: Optional[dict] = None):
        opts = options if isinstance(options, dict) else {}
        if mode == "doh_scan":
            self.start_doh_scan()
            return
        with self._state_lock:
            self._op_generation += 1
            gen_id = self._op_generation
            self._scan_abort_flag = False
            self._task_abort_flag = False
            self._abort_flag = False

        if mode in ("clean_ip_radar", "clean_ip"):
            port = int(opts.get("port", 443))
            samples = int(opts.get("samples", 48))
            self._worker_thread = threading.Thread(
                target=self._run_clean_ip_radar_task,
                args=(gen_id, port, samples),
                daemon=True,
            )
            self._worker_thread.start()
        elif mode == "full_repository":
            prune_dead = bool(opts.get("prune_dead", False))
            auto_ip = bool(opts.get("auto_clean_ip", True))
            self._worker_thread = threading.Thread(
                target=self._run_repository_deep_scan_task,
                args=(gen_id, prune_dead, auto_ip),
                daemon=True,
            )
            self._worker_thread.start()
        else:
            resolved = self._resolve_profile_index(target_index)
            idx = resolved if (resolved >= 0) else max(0, self.get_selected_index())
            auto_connect = bool(opts.get("auto_connect", False))
            check_gem = bool(opts.get("check_gemini", False))
            self._worker_thread = threading.Thread(
                target=self._run_active_profile_matrix_scan,
                args=(gen_id, idx, auto_connect, check_gem),
                daemon=True,
            )
            self._worker_thread.start()

    def stop_scanner(self):
        self.stop_dedicated_scan()

    def stop_dedicated_scan(self):
        was_connecting = self.snapshot.is_connecting
        with self._state_lock:
            self._op_generation += 1
            self._scan_abort_flag = True
            self._task_abort_flag = True
            if was_connecting:
                self._abort_flag = True

        if was_connecting:
            self.bridge.drop_active_connections()
            threading.Thread(target=self.xray.stop, daemon=True).start()
            self._set_state(EngineState.DISCONNECTED, "آماده اتصال", "عملیات توسط کاربر متوقف شد", 0)

        self._emit_scan_state(False, "اسکن توسط کاربر متوقف شد")
        self._emit_task_progress(False, 0, "عملیات توسط کاربر متوقف شد")

    def _is_op_cancelled(self, gen_id: int) -> bool:
        return (
            self._abort_flag
            or self._scan_abort_flag
            or self._task_abort_flag
            or self._shutdown_flag
            or (gen_id != self._op_generation)
        )

    def _run_clean_ip_radar_task(self, gen_id: int, port: int, sample_count: int):
        try:
            collected: List[dict] = []
            self._emit_scan_state(True, f"در حال اسکن {sample_count} کاندید رنج IP تمیز روی پورت {port}...")
            self._emit_scan_progress(8, "کاوش موازی زیرشبکه‌های CDN...")

            def _capture_row(r: dict):
                collected.append(r)
                self._emit_scan_row(r)

            winners = CleanIpScanner.discover_best_ips(
                port=port,
                top_n=12,
                sample_count=sample_count,
                log_fn=self.emit_log,
                on_row_cb=_capture_row,
                progress_cb=self._emit_scan_progress,
                abort_check=lambda: self._is_op_cancelled(gen_id),
            )
            if self._is_op_cancelled(gen_id):
                return

            collected.sort(key=lambda x: (-x.get("score", 0), x.get("tunnel_ms", 9999)))
            for rk, item in enumerate(collected, 1):
                item["rank"] = rk
            self._emit_scan_ranked(collected)
            self._emit_scan_progress(100, f"{len(winners)} آی‌پی تمیز رتبه‌بندی شد")
            self._emit_scan_state(False, f"اسکن IP تمیز کامل شد ({len(winners)} لبه برتر)")
        except Exception as exc:
            self.emit_log(f"[Radar] Error: {exc}")
            self._emit_scan_state(False, f"خطا در رادار IP: {exc}")

    def _run_lab_batch_scan_task(
        self,
        gen_id: int,
        targets: List[ProfileNode],
        scan_depth: str,
        check_gemini: bool,
        auto_connect: bool,
    ):
        if not targets:
            self._emit_scan_state(False, "کانفیگی برای آزمایشگاه انتخاب نشده است")
            return

        lab_settings = EngineSettings.from_dict(self.settings.to_dict())
        lab_settings.socks_port = 22808
        lab_settings.http_port = 22809
        lab_settings.bridge_port = 22810

        lab_bridge = FullDuplexMutatorBridge(listen_port=lab_settings.bridge_port, log_fn=self.emit_log)
        lab_bridge.start()
        lab_xray = XrayProcessDriver(core_dir=self.core_dir, configs_dir=self.configs_dir, log_fn=self.emit_log)

        if scan_depth.upper().startswith("VEC-"):
            vec_pool = [find_vector(scan_depth.upper())]
        elif scan_depth == "fast":
            vec_pool = [find_vector(vid) for vid in FAST_LAB_VECTOR_IDS]
        else:
            vec_pool = filter_vectors_by_mode(self.settings.engine_mode)

        winners: List[dict] = []
        port_edge_cache: Dict[int, List[str]] = {}

        try:
            self._emit_scan_state(True, f"شبیه‌سازی آزمایشگاه روی {len(targets)} کانفیگ...")
            total_steps = max(1, len(targets) * len(vec_pool))
            step_done = 0

            for nd in targets:
                if self._is_op_cancelled(gen_id):
                    break

                if not CleanIpScanner.is_cdn_eligible(nd):
                    nd.cached_clean_ip = ""

                orig_ep = self._resolve_origin_endpoint(nd)
                try:
                    _, lab_http = lab_xray.ensure_running(
                        uri=nd.uri,
                        settings=lab_settings,
                        use_native_fragment=False,
                        is_probe_mode=True,
                    )
                except Exception as exc:
                    self.emit_log(f"[Lab] Xray error on '{nd.name}': {exc}")
                    step_done += len(vec_pool)
                    continue

                node_vecs = [find_vector("VEC-00")] if (nd.protocol.upper() in ("SHADOWSOCKS", "SOCKS")) else vec_pool
                best_for_node: Optional[Tuple[int, float, BypassVector, str, str]] = None

                stage_endpoints: List[str] = []
                if orig_ep and (CleanIpScanner.fast_tcp_ping(orig_ep, nd.port, timeout=1.6) >= 0):
                    stage_endpoints.append(orig_ep)

                for stage_idx in range(2):
                    if self._is_op_cancelled(gen_id):
                        break
                    if stage_idx == 0:
                        if not stage_endpoints:
                            continue
                        ep_host = stage_endpoints[0]
                        ep_vecs = node_vecs
                    else:
                        if (best_for_node is not None) or (not self.settings.auto_clean_ip) or (not CleanIpScanner.is_cdn_eligible(nd)):
                            break
                        self.emit_log(f"[Lab] Direct host blocked on '{nd.name}' -> Trying Clean IP fallback...")
                        fb_ips = self._discover_fallback_clean_ips(nd, gen_id, port_edge_cache=port_edge_cache, sample_count=30)
                        fb_ips = [ip for ip in fb_ips if ip not in stage_endpoints]
                        if not fb_ips:
                            break
                        ep_host = fb_ips[0]
                        if CleanIpScanner.fast_tcp_ping(ep_host, nd.port, timeout=1.5) < 0:
                            break
                        ep_vecs = node_vecs[:6] if (len(node_vecs) > 6) else node_vecs

                    for vec in ep_vecs:
                        if self._is_op_cancelled(gen_id):
                            break
                        if stage_idx == 0:
                            step_done += 1
                        pct = min(98, max(8, int((step_done / total_steps) * 100)))
                        self._emit_scan_progress(pct, f"آزمایشگاه: {nd.name[:24]} • {vec.vector_id} @ {ep_host}")

                        lab_bridge.update_route(
                            remote_host=ep_host,
                            remote_port=nd.port,
                            vector=vec,
                            custom_stride=self.settings.forward_stride_bytes,
                            jitter_bytes=self.settings.stride_jitter_bytes,
                            raw_passthrough=(vec.family == "DIRECT"),
                            flush_existing_pool=True,
                        )

                        ok_f, f_ms, _ = self._probe_fast_tuple(http_port=lab_http, timeout=4.2)
                        if not ok_f:
                            continue

                        ok_q, q_ms, up_kbps, _ = self._probe_full_tuple(
                            http_port=lab_http,
                            verify_upload=True,
                            require_youtube_6s=False,
                            abort_check=lambda: self._is_op_cancelled(gen_id),
                        )
                        if not ok_q:
                            q_ms = f_ms
                            up_kbps = 0.0

                        gem_label = "OK" if (nd.gemini_status == "OK") else ""
                        if check_gemini:
                            g_ok, _ = TunnelStreamVerifier.check_gemini_access(lab_http, timeout=5.0)
                            gem_label = "OK" if g_ok else "BLOCKED"

                        score = max(15, min(100, int(100 - (q_ms / 24.0) + min(20.0, up_kbps / 15.0))))
                        row = {
                            "scan_type": "lab",
                            "rank": 1,
                            "uid": nd.uid,
                            "target_uid": nd.uid,
                            "item_id": vec.vector_id,
                            "vector_id": vec.vector_id,
                            "bound_vector": vec.vector_id,
                            "title": f"{nd.name} [{vec.vector_id}]",
                            "profile_name": nd.name,
                            "vector_name": vec.code_name,
                            "category": vec.family,
                            "endpoint": f"{ep_host}:{nd.port}",
                            "tcp_ms": f_ms,
                            "tunnel_ms": q_ms,
                            "upload_kbps": up_kbps,
                            "upload_ok": up_kbps > 0,
                            "gemini_status": gem_label,
                            "gemini_ok": gem_label == "OK",
                            "status": "VERIFIED",
                            "verified": True,
                            "score": score,
                            "detail": f"Up={up_kbps:.0f} KB/s | {vec.code_name}",
                        }
                        winners.append(row)
                        self._emit_scan_row(row)

                        if (best_for_node is None) or (q_ms < best_for_node[0]):
                            best_for_node = (q_ms, up_kbps, vec, gem_label, ep_host)

                        if len(targets) > 1:
                            break

                if best_for_node is not None:
                    b_ms, b_up, b_vec, b_gem, b_ep = best_for_node
                    nd.cached_vector_id = b_vec.vector_id
                    if b_ep in (nd.original_host, orig_ep):
                        nd.cached_clean_ip = ""
                    elif CleanIpScanner.is_cdn_eligible(nd):
                        nd.cached_clean_ip = b_ep
                    nd.last_ping_ms = b_ms
                    nd.upload_kbps = b_up
                    if b_gem:
                        nd.gemini_status = b_gem
                    nd.health_status = "VERIFIED"
                    nd.last_tested_ts = int(time.time())
                    self._promote_node_to_verified_outputs(nd, b_vec, b_ep, b_ms, b_up)
                else:
                    nd.health_status = "DEAD"

            winners.sort(key=lambda r: (-r.get("score", 0), r.get("tunnel_ms", 999999)))
            for idx_r, r in enumerate(winners, 1):
                r["rank"] = idx_r
            self._emit_scan_ranked(winners)
            self._save_profiles(self.profiles)
            self._notify_profiles_updated()
            self._emit_scan_state(False, f"آزمایشگاه کامل شد — {len(winners)} خروجی تاییدشده به خانه منتقل شد")

            if auto_connect and winners and (not self._is_op_cancelled(gen_id)):
                top = winners[0]
                self.apply_scanned_vector(top["bound_vector"], target_uid=top["uid"], connect_now=True)
        except Exception as exc:
            self.emit_log(f"[Lab] Error: {exc}")
            self._emit_scan_state(False, f"خطا در آزمایشگاه: {exc}")
        finally:
            lab_xray.stop()
            lab_bridge.stop()

    def _run_active_profile_matrix_scan(
        self,
        gen_id: int,
        idx: int,
        auto_connect: bool,
        check_gemini: bool = False,
        single_vector_id: Optional[str] = None,
    ):
        visible = self.get_visible_profiles()
        if not (0 <= idx < len(visible)):
            self._emit_scan_state(False, "پروفایل معتبری در مخزن انتخاب نشده است")
            return
        node = visible[idx]
        if not CleanIpScanner.is_cdn_eligible(node):
            node.cached_clean_ip = ""

        lab_settings = EngineSettings.from_dict(self.settings.to_dict())
        lab_settings.socks_port = 22818
        lab_settings.http_port = 22819
        lab_settings.bridge_port = 22820
        lab_bridge = FullDuplexMutatorBridge(listen_port=lab_settings.bridge_port, log_fn=self.emit_log)
        lab_bridge.start()
        lab_xray = XrayProcessDriver(core_dir=self.core_dir, configs_dir=self.configs_dir, log_fn=self.emit_log)

        try:
            self._emit_scan_state(True, f"اسکن متدهای هسته روی «{node.name}»...")
            self._emit_scan_progress(6, "راه‌اندازی هسته ایزوله آزمایشگاه...")

            _, lab_http = lab_xray.ensure_running(
                uri=node.uri,
                settings=lab_settings,
                use_native_fragment=False,
                is_probe_mode=True,
            )

            orig_ep = self._resolve_origin_endpoint(node)
            orig_tcp_ms = CleanIpScanner.fast_tcp_ping(orig_ep, node.port, timeout=1.7) if orig_ep else -1
            can_fallback_cdn = bool(self.settings.auto_clean_ip) and CleanIpScanner.is_cdn_eligible(node)

            if orig_tcp_ms >= 0:
                active_endpoint = orig_ep
            elif can_fallback_cdn:
                self._emit_scan_progress(12, f"هاست اصلی مسدود است — جستجوی IP تمیز جایگزین روی پورت {node.port}...")
                fb_ips = self._discover_fallback_clean_ips(node=node, gen_id=gen_id, sample_count=36)
                active_endpoint = fb_ips[0] if fb_ips else (orig_ep or node.original_host)
            else:
                active_endpoint = orig_ep or node.original_host

            vectors = [find_vector(single_vector_id)] if single_vector_id else self._build_vector_plan(node, self.settings.engine_mode)
            evaluated_rows: List[dict] = []
            passing_results: List[Tuple[int, int, float, BypassVector, str]] = []
            cached_lab_gem: Optional[str] = None

            def _evaluate_vectors_on_endpoint(ep_target: str, vec_seq: List[BypassVector], allow_early_gate: bool) -> bool:
                nonlocal cached_lab_gem
                gate_limit = min(3, len(vec_seq))
                for v_idx, vec in enumerate(vec_seq, 1):
                    if self._is_op_cancelled(gen_id):
                        return False
                    pct = 16 + int((v_idx / max(1, len(vec_seq))) * 80)
                    self._emit_scan_progress(pct, f"[{v_idx}/{len(vec_seq)}] آزمایش {vec.vector_id} ({vec.code_name}) @ {ep_target}...")

                    lab_bridge.update_route(
                        remote_host=ep_target,
                        remote_port=node.port,
                        vector=vec,
                        custom_stride=self.settings.forward_stride_bytes,
                        jitter_bytes=self.settings.stride_jitter_bytes,
                        raw_passthrough=(vec.family == "DIRECT"),
                        flush_existing_pool=True,
                    )

                    tcp_ms = CleanIpScanner.fast_tcp_ping(ep_target, node.port, timeout=1.5)
                    q_ok, q_ms, q_detail = self._probe_fast_tuple(http_port=lab_http, timeout=4.2)
                    if self._is_op_cancelled(gen_id):
                        return False

                    if not q_ok:
                        if allow_early_gate and (v_idx == gate_limit) and (not passing_results):
                            return False
                        row = {
                            "scan_type": "vector",
                            "rank": 99,
                            "target_index": idx,
                            "uid": node.uid,
                            "target_uid": node.uid,
                            "item_id": vec.vector_id,
                            "vector_id": vec.vector_id,
                            "bound_vector": vec.vector_id,
                            "title": f"{vec.vector_id} • {vec.code_name}",
                            "profile_name": node.name,
                            "vector_name": vec.code_name,
                            "category": vec.family,
                            "endpoint": f"{ep_target}:{node.port}",
                            "tcp_ms": tcp_ms,
                            "tunnel_ms": -1,
                            "status": "BLOCKED",
                            "verified": False,
                            "score": 0,
                            "detail": q_detail,
                        }
                        evaluated_rows.append(row)
                        self._emit_scan_row(row)
                        continue

                    f_ok, f_ms, f_up, f_detail = self._probe_full_tuple(
                        http_port=lab_http,
                        verify_upload=self.settings.verify_upload_stream,
                        require_youtube_6s=self.settings.require_youtube_6s,
                        abort_check=lambda: self._is_op_cancelled(gen_id),
                    )
                    if self._is_op_cancelled(gen_id):
                        return False

                    if f_ok:
                        if check_gemini:
                            if cached_lab_gem is None:
                                g_ok, _ = TunnelStreamVerifier.check_gemini_access(lab_http, timeout=5.0)
                                cached_lab_gem = "OK" if g_ok else "BLOCKED"
                            gem_stat = cached_lab_gem
                            node.gemini_status = gem_stat
                        else:
                            gem_stat = "OK" if (node.gemini_status == "OK") else ""

                        score = max(35, min(100, int(100 - (f_ms // 22) + min(15.0, f_up / 20.0))))
                        row = {
                            "scan_type": "vector",
                            "rank": 1,
                            "target_index": idx,
                            "uid": node.uid,
                            "target_uid": node.uid,
                            "item_id": vec.vector_id,
                            "vector_id": vec.vector_id,
                            "bound_vector": vec.vector_id,
                            "title": f"{vec.vector_id} • {vec.code_name}",
                            "profile_name": node.name,
                            "vector_name": vec.code_name,
                            "category": vec.family,
                            "endpoint": f"{ep_target}:{node.port}",
                            "tcp_ms": tcp_ms,
                            "tunnel_ms": f_ms,
                            "upload_kbps": f_up,
                            "upload_ok": f_up > 0,
                            "gemini_status": gem_stat,
                            "gemini_ok": gem_stat == "OK",
                            "status": "VERIFIED",
                            "verified": True,
                            "score": score,
                            "detail": f"Up={f_up:.0f} KB/s | {f_detail}",
                        }
                        evaluated_rows.append(row)
                        self._emit_scan_row(row)
                        passing_results.append((-score, f_ms, f_up, vec, ep_target))
                        if auto_connect:
                            return True
                    else:
                        partial_score = max(15, 50 - (q_ms // 35))
                        row = {
                            "scan_type": "vector",
                            "rank": 50,
                            "target_index": idx,
                            "uid": node.uid,
                            "target_uid": node.uid,
                            "item_id": vec.vector_id,
                            "vector_id": vec.vector_id,
                            "bound_vector": vec.vector_id,
                            "title": f"{vec.vector_id} • {vec.code_name}",
                            "profile_name": node.name,
                            "vector_name": vec.code_name,
                            "category": vec.family,
                            "endpoint": f"{ep_target}:{node.port}",
                            "tcp_ms": tcp_ms,
                            "tunnel_ms": q_ms,
                            "status": "PARTIAL_OK",
                            "verified": False,
                            "score": partial_score,
                            "detail": f"Initial {q_ms}ms OK ({f_detail})",
                        }
                        evaluated_rows.append(row)
                        self._emit_scan_row(row)
                        passing_results.append((-partial_score, q_ms, 0.0, vec, ep_target))
                return bool(passing_results)

            used_origin_with_cdn_gate = (active_endpoint == orig_ep) and can_fallback_cdn
            origin_ok = _evaluate_vectors_on_endpoint(active_endpoint, vectors, allow_early_gate=used_origin_with_cdn_gate)

            if (not origin_ok) and used_origin_with_cdn_gate and (not self._is_op_cancelled(gen_id)):
                self.emit_log(f"[Lab] Direct host '{orig_ep}' blocked -> Falling back to Clean IP scan...")
                self._emit_scan_progress(15, f"هاست اصلی مسدود است — جستجوی IP تمیز جایگزین روی پورت {node.port}...")
                fb_ips = self._discover_fallback_clean_ips(node=node, gen_id=gen_id, sample_count=36)
                fb_ips = [ip for ip in fb_ips if ip != orig_ep]
                if fb_ips:
                    evaluated_rows.clear()
                    _evaluate_vectors_on_endpoint(fb_ips[0], vectors, allow_early_gate=False)

            if self._is_op_cancelled(gen_id):
                return

            evaluated_rows.sort(
                key=lambda r: (
                    0 if (r["status"] == "VERIFIED") else (1 if (r["status"] == "PARTIAL_OK") else 2),
                    -r["score"],
                    r["tunnel_ms"] if (r["tunnel_ms"] > 0) else 999999,
                )
            )
            for rk, r_item in enumerate(evaluated_rows, 1):
                r_item["rank"] = rk
            self._emit_scan_ranked(evaluated_rows)

            if passing_results:
                passing_results.sort(key=lambda x: (x[0], x[1]))
                _, best_ms, best_up, best_vec, win_ep = passing_results[0]
                node.cached_vector_id = best_vec.vector_id
                if win_ep in (node.original_host, orig_ep):
                    node.cached_clean_ip = ""
                elif CleanIpScanner.is_cdn_eligible(node):
                    node.cached_clean_ip = win_ep
                node.last_ping_ms = best_ms
                node.upload_kbps = best_up
                node.health_status = "VERIFIED"
                node.last_tested_ts = int(time.time())
                self._promote_node_to_verified_outputs(node, best_vec, win_ep, best_ms, best_up)
                self._save_profiles(self.profiles)
                self._notify_profiles_updated()
                self._emit_scan_progress(100, f"رتبه ۱: {best_vec.vector_id} ({best_vec.code_name}) با پینگ {best_ms}ms")
                self._emit_scan_state(False, f"برنده آزمایشگاه: {best_vec.vector_id} ({best_ms}ms) به خانه منتقل شد")
                if auto_connect:
                    self.select_config(node.uid)
                    self.request_connect()
            else:
                self._emit_scan_progress(0, "متد فعالی روی این سرور پاسخ نداد")
                self._emit_scan_state(False, "اسکن پایان یافت؛ پاسخی از سرور دریافت نشد")
        except Exception as exc:
            self.emit_log(f"[MatrixScan] Error: {exc}")
            self._emit_scan_state(False, f"خطا در اسکن عمیق: {exc}")
        finally:
            lab_xray.stop()
            lab_bridge.stop()

    def _run_repository_deep_scan_task(self, gen_id: int, prune_dead: bool, auto_clean_ip: bool):
        visible = self.get_visible_profiles()
        self._run_lab_batch_scan_task(
            gen_id=gen_id,
            targets=visible,
            scan_depth="fast",
            check_gemini=False,
            auto_connect=False,
        )
        if prune_dead and (not self._is_op_cancelled(gen_id)):
            self.remove_dead_configs()

    def toggle_connection(self, uri: str = ""):
        if self.snapshot.is_connecting or self.snapshot.is_connected:
            self.request_disconnect()
        else:
            self.request_connect(uri)

    def connect(self, explicit_uri: str = ""):
        self.request_connect(explicit_uri)

    def disconnect(self):
        self.request_disconnect()

    def _teardown_active_tunnel_sync(self):
        with self._state_lock:
            self._op_generation += 1
            self._abort_flag = True
        self.tun.stop()
        self.bridge.refresh_physical_interface(enable_tun_bind=False)
        WindowsSystemProxy.apply(False, self.xray.active_http_port)
        self.bridge.drop_active_connections()
        self.xray.stop()

    def _filter_hidden_pool_by_location(self) -> Tuple[List[ProfileNode], str]:
        loc_code = self.get_selected_auto_location()
        with self._repo_lock:
            pool_raw = list(self.hidden_pool)
        if loc_code == "ALL":
            return pool_raw, "ALL"
        filtered = [n for n in pool_raw if (n.country_code or "").upper() == loc_code]
        return filtered, loc_code

    def _run_auto_repository_only_connect(self, gen_id: int):
        if not self.hidden_pool:
            self._sync_hidden_auto_pool()
        repo_nodes, loc_code = self._filter_hidden_pool_by_location()

        if not repo_nodes:
            if loc_code != "ALL" and self.hidden_pool:
                _, fa_n = LocationExtractor.get_country_names(loc_code)
                self._set_state(
                    EngineState.ERROR,
                    f"لوکیشن {fa_n} ({loc_code}) در مخزن یافت نشد",
                    "لوکیشن دیگری انتخاب کنید یا روی «همه لوکیشن‌ها» بگذارید",
                    0,
                )
            else:
                self._set_state(
                    EngineState.ERROR,
                    "مخزن خودکار در دسترس نیست",
                    "عدم دریافت سرورهای خودکار؛ اتصال اینترنت را بررسی کنید",
                    0,
                )
            return

        prior_winners = [n for n in repo_nodes if (n.health_status == "VERIFIED") and n.cached_vector_id]
        prior_winners.sort(key=lambda x: x.last_ping_ms if x.last_ping_ms > 0 else 99999)
        for fast_nd in prior_winners[:2]:
            if self._is_op_cancelled(gen_id):
                return
            if self._execute_autopilot_pipeline(gen_id, fast_nd, max_vectors=4, force_auto_vectors=True):
                return

        self._run_hunt_best_pipeline(gen_id)

    def request_connect(self, uri: str = ""):
        if self.snapshot.is_connecting and (not uri):
            self.request_disconnect()
            return

        clean_uri = uri.strip() if isinstance(uri, str) else ""
        if clean_uri.lower().startswith(("http://", "https://")):
            self.hunt_subscription_and_connect(clean_uri)
            return
        if clean_uri:
            with self._repo_lock:
                matched = next((p for p in self.profiles if (not p.is_hidden_pool) and (p.uri == clean_uri)), None)
                if matched is not None:
                    self.settings.selected_profile_uid = matched.uid
                    self.settings.autopilot_enabled = False
                else:
                    try:
                        new_node = UriConfigCodec.extract_profile_node(clean_uri, group_tag="QuickConnect")
                        self.profiles.insert(0, new_node)
                        self.settings.selected_profile_uid = new_node.uid
                        self.settings.autopilot_enabled = False
                    except Exception as exc:
                        self._set_state(EngineState.ERROR, "خطا در ساختار کانفیگ", str(exc), 0)
                        return
            self._save_profiles(self.profiles)
            self._notify_settings_updated()
            self._notify_profiles_updated(save_selection=True)

        with self._state_lock:
            self._op_generation += 1
            gen_id = self._op_generation
            self._abort_flag = False
            self._scan_abort_flag = False
            self._task_abort_flag = False

        if self.is_auto_repo_mode():
            self._persist_active_selection(save_disk=True)
            self._set_state(
                EngineState.HUNTING_BEST,
                "اتصال خودکار از مخزن هوشمند...",
                "پویش موازی سرورهای مخزن خودکار (بدون استفاده از کانفیگ‌های دستی)",
                progress=8,
            )
            self._worker_thread = threading.Thread(
                target=self._run_auto_repository_only_connect,
                args=(gen_id,),
                daemon=True,
            )
            self._worker_thread.start()
            return

        visible = self.get_visible_profiles()
        sel_idx = self.get_selected_index()
        if not (0 <= sel_idx < len(visible)):
            self._set_state(EngineState.ERROR, "کانفیگی انتخاب نشده است", "یک کانفیگ انتخاب کنید یا حالت خودکار را روشن کنید", 0)
            return

        primary_node = visible[sel_idx]
        self._persist_active_selection(save_disk=True)
        self._set_state(
            EngineState.FAST_RESUME,
            "در حال اتصال به کانفیگ انتخابی...",
            f"آماده‌سازی «{primary_node.name}» (برای لغو کلیک کنید)",
            progress=6,
        )
        self._worker_thread = threading.Thread(
            target=self._run_single_user_node_connect,
            args=(gen_id, primary_node),
            daemon=True,
        )
        self._worker_thread.start()

    def _run_single_user_node_connect(self, gen_id: int, user_node: ProfileNode):
        locked = self._execute_autopilot_pipeline(gen_id, user_node, max_vectors=14, force_auto_vectors=True)
        if (not locked) and (not self._is_op_cancelled(gen_id)):
            self.xray.stop()
            self._emit_task_progress(False, 0, "")
            self._set_state(
                EngineState.ERROR,
                "اتصال به این کانفیگ برقرار نشد",
                f"سرور «{user_node.name}» پاسخ نداد؛ کانفیگ دیگر یا حالت خودکار را امتحان کنید",
                0,
            )

    def request_disconnect(self):
        with self._state_lock:
            self._op_generation += 1
            self._abort_flag = True
            self._scan_abort_flag = True
            self._task_abort_flag = True

        self._active_runtime_node = None
        self.snapshot.egress_ip = "---"
        self.snapshot.egress_country_code = ""
        self.snapshot.country_code = ""
        self.snapshot.egress_country = "مسیر جهانی" if self.settings.language == "fa" else "Global"
        self.snapshot.destination_label = self.snapshot.egress_country
        self.snapshot.endpoint_ip = "---"
        self.snapshot.ping_ms = -1
        self.snapshot.gemini_ready = False
        self.snapshot.gemini_status = "UNKNOWN"
        self.snapshot.tx_rate_kbps = 0.0
        self.snapshot.rx_rate_kbps = 0.0
        self.snapshot.tx_rate_label = "0 B/s"
        self.snapshot.rx_rate_label = "0 B/s"
        self._set_state(EngineState.DISCONNECTED, "آماده اتصال", "تونل به صورت ایمن قطع شد", progress=0)
        self._emit_task_progress(False, 0, "")

        def _async_teardown():
            self.tun.stop()
            self.bridge.refresh_physical_interface(enable_tun_bind=False)
            WindowsSystemProxy.apply(False, self.xray.active_http_port)
            self.bridge.drop_active_connections()
            self.xray.stop()
            self._emit_tun_status(self.settings.tun_enabled, False, "Disconnected")
            self.emit_log("[AutoPilot] Tunnel stopped and routes restored.")

        threading.Thread(target=_async_teardown, daemon=True).start()

    def shutdown(self):
        with self._state_lock:
            self._op_generation += 1
            self._shutdown_flag = True
            self._abort_flag = True
            self._scan_abort_flag = True
            self._task_abort_flag = True
        self.tun.stop()
        self.per_app_gateway.stop()
        self.doh_engine.stop_system_doh_veil()
        WindowsSystemProxy.apply(False, self.xray.active_http_port)
        self.bridge.stop()
        self.xray.stop()

    def _execute_autopilot_pipeline(self, gen_id: int, node: ProfileNode, max_vectors: int = 12, force_auto_vectors: bool = True) -> bool:
        try:
            if not CleanIpScanner.is_cdn_eligible(node):
                node.cached_clean_ip = ""

            self.bridge.refresh_physical_interface(enable_tun_bind=False)
            self.bridge.reset_counters()
            self._prev_tx_bytes = 0
            self._prev_rx_bytes = 0

            disp_name = f"Alan Smart Auto ({node.country_code or 'GLOBAL'})" if node.is_hidden_pool else node.name
            self.snapshot.active_profile_uid = "__SMART_AUTO__" if node.is_hidden_pool else node.uid
            self.snapshot.active_profile_name = disp_name
            self.snapshot.protocol_label = node.protocol

            use_native_xray_frag = bool(self.settings.fragment_enabled and (not self.settings.autopilot_enabled))
            orig_ep = self._resolve_origin_endpoint(node)
            initial_ep = orig_ep or node.cached_clean_ip or node.original_host

            try:
                self.xray.ensure_running(
                    uri=node.uri,
                    settings=self.settings,
                    use_native_fragment=use_native_xray_frag,
                    direct_remote_host=initial_ep,
                    direct_remote_port=node.port,
                    enable_native_tun_inbound=False,
                )
            except Exception as exc:
                self.emit_log(f"[Xray] Core start error on '{disp_name}': {exc}")
                return False

            if self._is_op_cancelled(gen_id):
                return False

            if (not force_auto_vectors) and (not self.settings.autopilot_enabled):
                default_vec_id = (
                    "VEC-00"
                    if CleanIpScanner.is_domestic_or_direct_tunnel(node)
                    else (node.cached_vector_id or self.settings.manual_vector_id)
                )
                vec = find_vector(default_vec_id)
                self._set_state(EngineState.VERIFYING_STABILITY, "در حال اتصال مستقیم...", f"مسیر {disp_name}", 65)
                self.bridge.update_route(
                    remote_host=initial_ep,
                    remote_port=node.port,
                    vector=vec,
                    custom_stride=self.settings.forward_stride_bytes,
                    jitter_bytes=self.settings.stride_jitter_bytes,
                    raw_passthrough=(use_native_xray_frag or (vec.family == "DIRECT")),
                    flush_existing_pool=True,
                )
                q_ok, q_ms, _ = self._probe_fast_tuple(http_port=self.xray.active_http_port, timeout=4.2)
                if q_ok and (not self._is_op_cancelled(gen_id)):
                    self._lock_winning_tunnel(
                        gen_id=gen_id,
                        node=node,
                        endpoint_ip=initial_ep,
                        vec=vec,
                        ping_ms=q_ms,
                        upload_kbps=0.0,
                        raw_passthrough=(use_native_xray_frag or (vec.family == "DIRECT")),
                    )
                    return True
                return False

            soft_winners: List[Tuple[int, str, BypassVector]] = []
            vectors_all = self._build_vector_plan(node, self.settings.engine_mode)[:max_vectors]
            can_cdn_fallback = bool(self.settings.auto_clean_ip) and CleanIpScanner.is_cdn_eligible(node)

            def _try_vectors_on_host(ep_host: str, vec_subset: List[BypassVector], start_pct: int, span_pct: int) -> bool:
                total_v = max(1, len(vec_subset))
                for idx_v, vec in enumerate(vec_subset, 1):
                    if self._is_op_cancelled(gen_id):
                        return False
                    pct = start_pct + int((idx_v / total_v) * span_pct)
                    self._set_state(
                        EngineState.PROBING_VECTORS,
                        f"تست موتور عبوری روی «{disp_name}»...",
                        f"آزمایش {vec.vector_id} ({vec.code_name})",
                        progress=pct,
                    )
                    self.bridge.update_route(
                        remote_host=ep_host,
                        remote_port=node.port,
                        vector=vec,
                        custom_stride=self.settings.forward_stride_bytes,
                        jitter_bytes=self.settings.stride_jitter_bytes,
                        raw_passthrough=(vec.family == "DIRECT"),
                        flush_existing_pool=True,
                    )
                    q_ok, q_ms, _ = self._probe_fast_tuple(http_port=self.xray.active_http_port, timeout=4.0)
                    if self._is_op_cancelled(gen_id):
                        return False
                    if not q_ok:
                        continue

                    soft_winners.append((q_ms, ep_host, vec))
                    self._set_state(
                        EngineState.VERIFYING_STABILITY,
                        "تایید پایداری استریم و آپلود...",
                        f"پینگ اولیه {q_ms}ms — بررسی سلامت تونل",
                        progress=min(96, pct + 4),
                    )
                    f_ok, f_ms, f_up, _ = self._probe_full_tuple(
                        http_port=self.xray.active_http_port,
                        verify_upload=self.settings.verify_upload_stream,
                        require_youtube_6s=self.settings.require_youtube_6s,
                        abort_check=lambda: self._is_op_cancelled(gen_id),
                    )
                    if self._is_op_cancelled(gen_id):
                        return False
                    if f_ok:
                        self._lock_winning_tunnel(
                            gen_id=gen_id,
                            node=node,
                            endpoint_ip=ep_host,
                            vec=vec,
                            ping_ms=f_ms,
                            upload_kbps=f_up,
                            raw_passthrough=(vec.family == "DIRECT"),
                        )
                        return True
                    if len(soft_winners) >= 2:
                        break
                return False

            if orig_ep and (CleanIpScanner.fast_tcp_ping(orig_ep, node.port, timeout=1.6) >= 0):
                stage1_vecs = vectors_all[:5] if can_cdn_fallback else vectors_all
                if _try_vectors_on_host(orig_ep, stage1_vecs, start_pct=18, span_pct=(42 if can_cdn_fallback else 75)):
                    return True

            if (not soft_winners) and can_cdn_fallback and (not self._is_op_cancelled(gen_id)):
                self._set_state(
                    EngineState.SCANNING_CLEAN_IP,
                    "هاست اصلی مسدود است — جستجوی IP تمیز...",
                    f"کاوش لبه جایگزین برای پورت {node.port}",
                    progress=62,
                )
                fallback_ips = self._discover_fallback_clean_ips(node=node, gen_id=gen_id, sample_count=34)
                for fb_ip in fallback_ips[:2]:
                    if self._is_op_cancelled(gen_id) or (fb_ip == orig_ep):
                        continue
                    if CleanIpScanner.fast_tcp_ping(fb_ip, node.port, timeout=1.5) < 0:
                        continue
                    if _try_vectors_on_host(fb_ip, vectors_all, start_pct=66, span_pct=28):
                        return True

            if soft_winners and (not self._is_op_cancelled(gen_id)):
                soft_winners.sort(key=lambda x: x[0])
                best_ping, best_ep, best_v = soft_winners[0]
                self.bridge.update_route(
                    remote_host=best_ep,
                    remote_port=node.port,
                    vector=best_v,
                    custom_stride=self.settings.forward_stride_bytes,
                    jitter_bytes=self.settings.stride_jitter_bytes,
                    raw_passthrough=(best_v.family == "DIRECT"),
                    flush_existing_pool=True,
                )
                self._lock_winning_tunnel(
                    gen_id=gen_id,
                    node=node,
                    endpoint_ip=best_ep,
                    vec=best_v,
                    ping_ms=best_ping,
                    upload_kbps=0.0,
                    raw_passthrough=(best_v.family == "DIRECT"),
                )
                return True

            node.health_status = "DEAD"
            if not node.is_hidden_pool:
                self._save_profiles(self.profiles)
                self._notify_profiles_updated(save_selection=False)
            return False
        except Exception as exc:
            self.emit_log(f"[AutoPilot] Pipeline exception: {exc}")
            return False

    def _lock_winning_tunnel(
        self,
        gen_id: int,
        node: ProfileNode,
        endpoint_ip: str,
        vec: BypassVector,
        ping_ms: int,
        upload_kbps: float = 0.0,
        raw_passthrough: bool = False,
    ):
        if self._is_op_cancelled(gen_id):
            return

        self.bridge.reset_counters()
        self._prev_tx_bytes = 0
        self._prev_rx_bytes = 0
        self._active_runtime_node = node
        self._active_runtime_vec = vec

        node.cached_vector_id = vec.vector_id
        orig_check = CleanIpScanner.resolve_unpoisoned_ipv4(node.original_host, timeout=1.0)
        if endpoint_ip in (node.original_host, orig_check):
            node.cached_clean_ip = ""
        elif CleanIpScanner.is_cdn_eligible(node):
            node.cached_clean_ip = endpoint_ip
        node.last_ping_ms = ping_ms
        node.upload_kbps = upload_kbps
        node.health_status = "VERIFIED"
        node.last_tested_ts = int(time.time())

        if not node.is_hidden_pool:
            self._promote_node_to_verified_outputs(node, vec, endpoint_ip, ping_ms, upload_kbps)
            self._save_profiles(self.profiles)
            self._notify_profiles_updated(save_selection=True)

        self._sync_per_app_gateway()
        if self.settings.system_proxy_enabled:
            WindowsSystemProxy.apply(self._should_enable_global_wininet_proxy(), self._effective_system_proxy_port())

        shown_ep = f"Protected Edge ({node.country_code or 'GLOBAL'})" if node.is_hidden_pool else f"{endpoint_ip}:{node.port}"
        shown_name = f"Alan Smart Auto ({node.country_code or 'GLOBAL'})" if node.is_hidden_pool else node.name
        shown_uid = "__SMART_AUTO__" if node.is_hidden_pool else node.uid

        with self._state_lock:
            self.snapshot.active_profile_uid = shown_uid
            self.snapshot.active_profile_name = shown_name
            self.snapshot.protocol_label = node.protocol
            self.snapshot.endpoint_ip = shown_ep
            self.snapshot.active_vector_id = "FRAG" if (raw_passthrough and self.settings.fragment_enabled) else vec.vector_id
            self.snapshot.active_vector_name = (
                f"Native Fragment ({self.settings.fragment_length})"
                if (raw_passthrough and self.settings.fragment_enabled)
                else vec.code_name
            )
            self.snapshot.ping_ms = ping_ms

        self._emit_task_progress(False, 100, "")
        self._set_state(
            EngineState.CONNECTED,
            "VPN متصل و پایدار است",
            f"{self.snapshot.active_vector_name} | {shown_ep}",
            progress=100,
        )

        if node.is_hidden_pool:
            self._save_pool_winner_meta(node, vec.vector_id, endpoint_ip, ping_ms)

        def _post_connect_tun_and_geo():
            if self.settings.tun_enabled:
                self._activate_xray_tun_async(node, endpoint_ip)
                time.sleep(0.35)

            geo = {"ip": "---", "country_code": "", "country_en": "Global", "country_fa": "مسیر جهانی"}
            for _ in range(2):
                if self._is_op_cancelled(gen_id) or (not self.snapshot.is_connected):
                    return
                geo = TunnelStreamVerifier.resolve_egress_geo(http_port=self.xray.active_http_port, timeout=4.2)
                if geo.get("ip", "---") != "---":
                    break
                time.sleep(1.2)

            g_ok, _ = TunnelStreamVerifier.check_gemini_access(http_port=self.xray.active_http_port, timeout=5.2, geo_hint=geo)
            if (not self._is_op_cancelled(gen_id)) and self.snapshot.is_connected:
                gem_str = "OK" if g_ok else "BLOCKED"
                node.gemini_status = gem_str
                ip_only = geo.get("ip", "---")
                cc = geo.get("country_code", "") or node.country_code
                c_fa = geo.get("country_fa", "مسیر جهانی")
                c_en = geo.get("country_en", "Global")
                c_disp = c_fa if (self.settings.language == "fa") else c_en
                dest_lbl = f"{c_disp} ({cc})" if cc else c_disp

                with self._state_lock:
                    self.snapshot.egress_ip = ip_only
                    self.snapshot.egress_country_code = cc
                    self.snapshot.country_code = cc
                    self.snapshot.egress_country = c_disp
                    self.snapshot.egress_country_en = c_en
                    self.snapshot.egress_country_fa = c_fa
                    self.snapshot.destination_label = dest_lbl
                    self.snapshot.gemini_ready = g_ok
                    self.snapshot.gemini_status = gem_str
                if not node.is_hidden_pool:
                    self._save_profiles(self.profiles)
                    self._notify_profiles_updated(save_selection=False)
                self._push_telemetry()
                if cc:
                    self.emit_log(f"[GeoIP] Egress IP: {ip_only} | Country: {c_en} ({cc})")

        threading.Thread(target=_post_connect_tun_and_geo, daemon=True).start()

    def get_telemetry_snapshot(self) -> dict:
        with self._state_lock:
            return asdict(self.snapshot)

    def _telemetry_ticker_loop(self):
        while not self._shutdown_flag:
            time.sleep(1.0)
            now = time.perf_counter()
            dt = max(0.1, now - self._prev_tick_ts)
            self._prev_tick_ts = now

            tx_cur = self.bridge.tx_bytes_total
            rx_cur = self.bridge.rx_bytes_total

            with self._state_lock:
                connected = self.snapshot.is_connected
                since = self._connected_since_ts

            if connected:
                tx_delta = max(0, tx_cur - self._prev_tx_bytes)
                rx_delta = max(0, rx_cur - self._prev_rx_bytes)
                tx_kbps = round((tx_delta / 1024.0) / dt, 2)
                rx_kbps = round((rx_delta / 1024.0) / dt, 2)
                up_sec = int(max(0.0, now - since)) if (since is not None) else 0
            else:
                tx_kbps = 0.0
                rx_kbps = 0.0
                up_sec = 0

            self._prev_tx_bytes = tx_cur
            self._prev_rx_bytes = rx_cur

            with self._state_lock:
                self.snapshot.tx_rate_kbps = tx_kbps
                self.snapshot.rx_rate_kbps = rx_kbps
                self.snapshot.tx_rate_label = format_byte_rate(tx_kbps)
                self.snapshot.rx_rate_label = format_byte_rate(rx_kbps)
                self.snapshot.tx_total_bytes = tx_cur if connected else 0
                self.snapshot.rx_total_bytes = rx_cur if connected else 0
                self.snapshot.active_sessions = self.bridge.active_session_count if connected else 0
                self.snapshot.uptime_seconds = up_sec
                self.snapshot.uptime_label = format_uptime_hms(up_sec)
                self.snapshot.tun_enabled = self.settings.tun_enabled
                self.snapshot.tun_active = self.tun.active or (self.settings.tun_enabled and is_windows_admin())
                self.snapshot.tun_badge = "ON" if (self.settings.tun_enabled and is_windows_admin()) else "OFF"
                self.snapshot.auto_mode_enabled = self.is_auto_repo_mode()
                self.snapshot.preferred_auto_location = self.get_selected_auto_location()
                self.snapshot.doh_shield_active = self.doh_engine.veil_active
                self.snapshot.per_app_mode = self.settings.per_app_mode
                self.snapshot.system_proxy_enabled = self.settings.system_proxy_enabled
                self.snapshot.selected_index = max(0, self.selected_index)

            self._push_telemetry()

    def _self_healing_watchdog_loop(self):
        missed = 0
        while not self._shutdown_flag:
            time.sleep(18.0)

            hrs = int(self.settings.sub_auto_update_hours or 0)
            if (hrs > 0) and ((time.time() - self._last_sub_auto_check) >= (hrs * 3600)):
                self._last_sub_auto_check = time.time()
                self.refresh_all_subscriptions()
                threading.Thread(target=self._sync_hidden_auto_pool, daemon=True).start()

            if (not self.snapshot.is_connected) or (not self.settings.self_healing_watchdog) or self._scanner_running:
                missed = 0
                continue
            if self.snapshot.rx_rate_kbps > 1.5:
                missed = 0
                continue

            ok_p, rtt_p, _ = self._probe_fast_tuple(http_port=self.xray.active_http_port, timeout=4.2)
            if ok_p:
                missed = 0
                with self._state_lock:
                    self.snapshot.ping_ms = rtt_p
            else:
                missed += 1
                if (missed >= 2) and self.snapshot.is_connected:
                    missed = 0
                    worker_idle = (self._worker_thread is None) or (not self._worker_thread.is_alive())
                    if worker_idle:
                        active_node = self._active_runtime_node
                        if active_node is not None:
                            active_node.cached_vector_id = ""
                        with self._state_lock:
                            self._op_generation += 1
                            gen_id = self._op_generation
                            self._abort_flag = False
                        self._set_state(EngineState.RECOVERING, "ترمیم خودکار مسیر...", "سوییچ خودکار به مسیر جایگزین", 35)
                        target_fn = (
                            self._run_auto_repository_only_connect
                            if self.is_auto_repo_mode()
                            else (lambda g: self._run_single_user_node_connect(g, active_node))
                        )
                        self._worker_thread = threading.Thread(
                            target=target_fn,
                            args=(gen_id,),
                            daemon=True,
                        )
                        self._worker_thread.start()
