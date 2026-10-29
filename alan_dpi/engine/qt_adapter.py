import copy
import importlib
from typing import Any, List, Optional
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication
from alan_dpi.engine.autopilot import AlanAutoPilotEngine
from alan_dpi.engine.tun_manager import is_windows_admin, relaunch_as_admin


def _resolve_ui_adapter_base():
    candidate_modules = [
        "alan_dpi.ui",
        "alan_dpi.ui.main_window",
        "alan_dpi.ui.controller",
        "alan_dpi.ui.adapter",
        "alan_dpi.ui.pages",
    ]
    for mod_name in candidate_modules:
        try:
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, "BackendControllerAdapter", None)
            if (cls is not None) and isinstance(cls, type) and issubclass(cls, QObject):
                return cls
        except Exception:
            continue
    return QObject


_AdapterBase = _resolve_ui_adapter_base()


class AlanQtBackendController(_AdapterBase):
    if not hasattr(_AdapterBase, "telemetry_updated"):
        telemetry_updated = Signal(dict)
    if not hasattr(_AdapterBase, "log_emitted"):
        log_emitted = Signal(str)
    if not hasattr(_AdapterBase, "profiles_updated"):
        profiles_updated = Signal(list)
    if not hasattr(_AdapterBase, "settings_updated"):
        settings_updated = Signal(dict)
    if not hasattr(_AdapterBase, "scan_row_emitted"):
        scan_row_emitted = Signal(dict)
    if not hasattr(_AdapterBase, "scan_results_ranked"):
        scan_results_ranked = Signal(list)
    if not hasattr(_AdapterBase, "scan_progress_updated"):
        scan_progress_updated = Signal(int, str)
    if not hasattr(_AdapterBase, "scan_state_changed"):
        scan_state_changed = Signal(bool, str)
    if not hasattr(_AdapterBase, "subscriptions_updated"):
        subscriptions_updated = Signal(list)
    if not hasattr(_AdapterBase, "task_progress_updated"):
        task_progress_updated = Signal(bool, int, str)
    if not hasattr(_AdapterBase, "tun_status_changed"):
        tun_status_changed = Signal(bool, str)

    def __init__(self, base_dir: str, parent=None):
        try:
            super().__init__(parent)
        except TypeError:
            super().__init__()

        self.engine = AlanAutoPilotEngine(
            base_dir=base_dir,
            on_telemetry=lambda d: self.telemetry_updated.emit(copy.deepcopy(d)),
            on_log=lambda s: self.log_emitted.emit(str(s)),
            on_profiles_changed=lambda lst: self.profiles_updated.emit(copy.deepcopy(lst)),
            on_settings_changed=lambda cfg: self.settings_updated.emit(copy.deepcopy(cfg)),
            on_scan_row=lambda row: self.scan_row_emitted.emit(copy.deepcopy(row)),
            on_scan_ranked=lambda rows: self.scan_results_ranked.emit(copy.deepcopy(rows)),
            on_scan_progress=lambda pct, lbl: self.scan_progress_updated.emit(int(pct), str(lbl)),
            on_scan_state=lambda run, msg: self.scan_state_changed.emit(bool(run), str(msg)),
            on_subscriptions_changed=lambda subs: self.subscriptions_updated.emit(copy.deepcopy(subs)),
            on_task_progress=lambda act, pct, msg: self.task_progress_updated.emit(bool(act), int(pct), str(msg)),
            on_tun_status=lambda act, det: self.tun_status_changed.emit(bool(act), str(det)),
        )

    @property
    def selected_index(self) -> int:
        return self.engine.selected_index

    def get_selected_index(self) -> int:
        return self.engine.selected_index

    def get_selected_uid(self) -> str:
        return self.engine.settings.selected_profile_uid

    def toggle_connection(self, uri_or_flag: Any = ""):
        uri = uri_or_flag if isinstance(uri_or_flag, str) else ""
        self.engine.toggle_connection(uri)

    def request_connect(self, uri_or_flag: Any = ""):
        uri = uri_or_flag if isinstance(uri_or_flag, str) else ""
        self.engine.request_connect(uri)

    def request_disconnect(self, *_args):
        self.engine.request_disconnect()

    def cancel_connection(self, *_args):
        self.engine.request_disconnect()

    def hunt_best_and_connect(self, *_args):
        self.engine.hunt_best_and_connect()

    @Slot(bool)
    def set_tun_mode(self, enabled: bool):
        self.engine.set_tun_mode(bool(enabled))

    @Slot(bool)
    def set_auto_clean_ip(self, enabled: bool):
        self.engine.set_single_setting("auto_clean_ip", bool(enabled))

    @Slot(bool)
    def set_require_youtube_6s(self, enabled: bool):
        self.engine.set_single_setting("require_youtube_6s", bool(enabled))

    @Slot(bool)
    def set_verify_upload_stream(self, enabled: bool):
        self.engine.set_single_setting("verify_upload_stream", bool(enabled))

    @Slot(bool)
    def set_self_healing_watchdog(self, enabled: bool):
        self.engine.set_single_setting("self_healing_watchdog", bool(enabled))

    @Slot(bool)
    def set_system_proxy(self, enabled: bool):
        self.engine.set_single_setting("system_proxy_enabled", bool(enabled))

    @Slot(bool)
    def set_autopilot(self, enabled: bool):
        self.engine.set_single_setting("autopilot_enabled", bool(enabled))

    @Slot(str, object)
    def set_setting_value(self, key: str, value: Any):
        self.engine.set_single_setting(key, value)

    def is_admin(self) -> bool:
        return is_windows_admin()

    def request_admin_elevation(self) -> bool:
        self.engine.shutdown()
        if relaunch_as_admin():
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return True
        self.engine._shutdown_flag = False
        self.engine.bridge.start()
        return False

    def update_settings(self, settings_dict: dict):
        if isinstance(settings_dict, dict):
            self.engine.update_settings(settings_dict)

    def get_settings(self) -> dict:
        return self.engine.get_settings_as_dict()

    def get_vectors(self) -> List[dict]:
        return self.engine.get_vectors_as_dicts()

    def get_profiles(self) -> List[dict]:
        return self.engine.get_profiles_as_dicts()

    def get_subscriptions(self) -> List[dict]:
        return self.engine.get_subscriptions_as_dicts()

    def get_config_editable(self, index_or_uid: Any) -> dict:
        return self.engine.get_config_editable(index_or_uid)

    def save_config_editable(self, index_or_uid: Any, data: dict) -> bool:
        if isinstance(data, dict):
            return self.engine.save_config_editable(index_or_uid, data)
        return False

    def clear_all_configs(self) -> int:
        return self.engine.clear_all_configs()

    def import_configs(self, raw_text: str, group_tag: str = "Manual") -> int:
        if isinstance(raw_text, str):
            return self.engine.import_configs(raw_text, group_tag=group_tag)
        return 0

    def import_configs_from_file(self, file_path: str) -> int:
        return self.engine.import_configs_from_file(file_path)

    def add_subscription(self, url: str, title: str = "Subscription") -> int:
        return self.engine.add_subscription(url, title)

    def refresh_subscriptions(self):
        self.engine.refresh_all_subscriptions()

    def delete_subscription(self, index: int):
        self.engine.delete_subscription(index)

    def delete_config(self, index_or_uid: Any):
        self.engine.delete_config(index_or_uid)

    def rename_config(self, index_or_uid: Any, new_name: str):
        self.engine.rename_config(index_or_uid, new_name)

    def select_config(self, index_or_uid: Any):
        self.engine.select_config(index_or_uid)

    def deduplicate_configs(self) -> int:
        return self.engine.deduplicate_configs()

    def remove_dead_configs(self) -> int:
        return self.engine.remove_dead_configs()

    def sort_configs(self, sort_by: str = "ping"):
        self.engine.sort_configs(sort_by)

    def quick_ping_configs(self):
        self.engine.quick_ping_repository()

    def clone_config_with_clean_ips(self, index_or_uid: Any, count: int = 3):
        self.engine.clone_config_with_clean_ips(index_or_uid, count)

    def export_configs(self, mode: str = "verified", inject_early_data: int = 0) -> str:
        return self.engine.export_configs(mode=mode, inject_early_data=inject_early_data)

    def start_scanner(self, mode: str = "active_profile", target_index: Any = -1, options: Optional[dict] = None):
        self.engine.start_dedicated_scan(mode=mode, target_index=target_index, options=options)

    def stop_scanner(self):
        self.engine.stop_dedicated_scan()

    def scan_all_configs(self, *_args):
        self.engine.start_dedicated_scan(mode="full_repository", options={"auto_clean_ip": True})

    def apply_scanned_ip(self, clean_ip: str, only_selected: bool = False) -> int:
        return self.engine.apply_clean_ip_to_repository(clean_ip, only_selected=only_selected)

    def apply_scanned_vector(
        self,
        vector_id: str,
        target_index: Any = -1,
        clean_ip: str = "",
        connect_now: bool = False,
    ):
        self.engine.bind_vector_to_profile(
            vector_id=vector_id,
            target_index=target_index,
            clean_ip=clean_ip,
            connect_now=connect_now,
        )

    def apply_vector_to_all_configs(self, vector_id: str, clean_ip: str = "") -> int:
        return self.engine.apply_vector_to_all_configs(vector_id=vector_id, clean_ip=clean_ip)

    def connect_scanned_profile(self, target_index: Any, vector_id: str = "", clean_ip: str = ""):
        self.engine.connect_scanned_profile(target_index, vector_id=vector_id, clean_ip=clean_ip)

    def shutdown(self):
        self.engine.shutdown()