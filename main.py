import ctypes
import importlib
import inspect
import os
import re
import sys
import warnings
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QAbstractButton, QComboBox, QLabel
from alan_dpi.engine.models import APP_NAME, APP_VERSION
from alan_dpi.engine.qt_adapter import AlanQtBackendController

import alan_dpi.ui


def _resolve_runtime_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _set_windows_app_id():
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"Alan.RIP.Dpi.{APP_VERSION}"
            )
        except Exception:
            pass


def _locate_main_window_class():
    search_modules = [
        "alan_dpi.ui.main_window",
        "alan_dpi.ui",
        "alan_dpi.ui.window",
        "alan_dpi.ui.app",
    ]
    for mod_name in search_modules:
        try:
            mod = importlib.import_module(mod_name)
            for cls_name in ("AlanMainWindow", "AlanRipDpiWindow", "MainWindow"):
                cls = getattr(mod, cls_name, None)
                if (cls is not None) and isinstance(cls, type):
                    return cls
        except Exception:
            continue
    raise ImportError("AlanMainWindow class not found inside 'alan_dpi/ui/'.")


def _wire_controller_to_window(controller: AlanQtBackendController, window):
    signal_slot_pairs = [
        ("telemetry_updated", "on_telemetry_update"),
        ("log_emitted", "on_log_message"),
        ("profiles_updated", "on_profiles_updated"),
        ("settings_updated", "on_settings_updated"),
        ("scan_row_emitted", "on_scan_row"),
        ("scan_results_ranked", "on_scan_results_ranked"),
        ("scan_progress_updated", "on_scan_progress"),
        ("scan_state_changed", "on_scan_state_changed"),
        ("subscriptions_updated", "on_subscriptions_updated"),
        ("task_progress_updated", "on_task_progress"),
        ("tun_status_changed", "on_tun_status_changed"),
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        for sig_name, slot_name in signal_slot_pairs:
            sig = getattr(controller, sig_name, None)
            slot = getattr(window, slot_name, None)
            if (sig is not None) and (slot is not None):
                try:
                    sig.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
                try:
                    sig.connect(slot, Qt.ConnectionType.QueuedConnection)
                except (RuntimeError, TypeError):
                    sig.connect(slot)


def _sync_version_badges(window):
    window.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
    ver_pattern = re.compile(r"^v?\d+\.\d+(?:\.\d+)?(?:\s+CORE)?$", re.IGNORECASE)
    for lbl in window.findChildren(QLabel):
        txt = (lbl.text() or "").strip()
        if ver_pattern.match(txt):
            lbl.setText(f"v{APP_VERSION}")


def _sync_persisted_ui_state(controller: AlanQtBackendController, window):
    _sync_version_badges(window)
    cfg = controller.get_settings()
    sel_idx = controller.get_selected_index()

    switch_attr_map = {
        "auto_clean_ip": ("sw_auto_clean_ip", "sw_clean_ip", "chk_auto_clean_ip", "toggle_clean_ip"),
        "require_youtube_6s": ("sw_require_youtube_6s", "sw_yt_6s", "sw_youtube_6s", "chk_yt_guard", "toggle_yt_6s"),
        "verify_upload_stream": ("sw_verify_upload_stream", "sw_upload", "sw_verify_upload", "chk_upload"),
        "self_healing_watchdog": ("sw_self_healing_watchdog", "sw_watchdog", "sw_self_healing", "chk_watchdog"),
    }

    target_containers = [window]
    for page_attr in ("settings_page", "page_settings", "tab_settings", "home_page", "page_home", "profiles_page"):
        sub_obj = getattr(window, page_attr, None)
        if sub_obj is not None:
            target_containers.append(sub_obj)

    for setting_key, candidate_names in switch_attr_map.items():
        val = bool(cfg.get(setting_key, True))
        for container in target_containers:
            for attr_name in candidate_names:
                w = getattr(container, attr_name, None)
                if w is None:
                    continue
                if isinstance(w, QAbstractButton):
                    w.blockSignals(True)
                    w.setChecked(val)
                    w.blockSignals(False)
                    if not bool(w.property("_alan_setting_wired")):
                        w.setProperty("_alan_setting_wired", True)
                        w.toggled.connect(
                            lambda checked, k=setting_key: controller.set_setting_value(k, bool(checked))
                        )
                elif hasattr(w, "setChecked"):
                    try:
                        w.blockSignals(True)
                        w.setChecked(val)
                        w.blockSignals(False)
                    except Exception:
                        pass
                    if not bool(w.property("_alan_setting_wired")):
                        w.setProperty("_alan_setting_wired", True)
                        for sig_n in ("toggled", "checkedChanged", "valueChanged"):
                            sig_obj = getattr(w, sig_n, None)
                            if sig_obj is not None:
                                try:
                                    sig_obj.connect(
                                        lambda checked, k=setting_key: controller.set_setting_value(k, bool(checked))
                                    )
                                    break
                                except Exception:
                                    pass

    for container in target_containers:
        for combo_attr in ("cmb_profile", "combo_profile", "profile_combo", "active_profile_combo"):
            cmb = getattr(container, combo_attr, None)
            if isinstance(cmb, QComboBox) and (0 <= sel_idx < cmb.count()):
                cmb.blockSignals(True)
                cmb.setCurrentIndex(sel_idx)
                cmb.blockSignals(False)


def main():
    _set_windows_app_id()
    base_dir = _resolve_runtime_base_dir()
    for sub in ("core", "configs", "logs", "assets"):
        os.makedirs(os.path.join(base_dir, sub), exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)

    for icon_name in ("logo.ico", "logo.png"):
        icon_path = os.path.join(base_dir, "assets", icon_name)
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
            break

    controller = AlanQtBackendController(base_dir=base_dir)
    WindowClass = _locate_main_window_class()

    sig = inspect.signature(WindowClass.__init__)
    params = list(sig.parameters.keys())
    if "controller" in params:
        window = WindowClass(controller=controller)
    elif len(params) >= 2:
        window = WindowClass(controller)
    else:
        window = WindowClass()
        if hasattr(window, "set_controller"):
            window.set_controller(controller)

    _wire_controller_to_window(controller, window)
    app.aboutToQuit.connect(controller.shutdown)

    controller.engine.emit_log(f"[{APP_NAME} v{APP_VERSION}] Core online.")
    controller.engine._notify_settings_updated()
    controller.engine._notify_profiles_updated(save_selection=False)
    controller.engine._notify_subscriptions_updated()
    controller.engine._push_telemetry()

    QTimer.singleShot(50, lambda: _sync_persisted_ui_state(controller, window))

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()