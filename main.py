import ctypes
import importlib
import inspect
import os
import re
import sys
import warnings
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QComboBox, QLabel
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


def _load_bundled_fonts(base_dir: str):
    fonts_dir = os.path.join(base_dir, "assets", "fonts")
    if not os.path.isdir(fonts_dir):
        return
    for fname in os.listdir(fonts_dir):
        if fname.lower().endswith((".ttf", ".otf")):
            try:
                QFontDatabase.addApplicationFont(os.path.join(fonts_dir, fname))
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
        ("verified_outputs_updated", "on_verified_outputs_updated"),
        ("settings_updated", "on_settings_updated"),
        ("subscriptions_updated", "on_subscriptions_updated"),
        ("scan_row_emitted", "on_scan_row"),
        ("scan_results_ranked", "on_scan_results_ranked"),
        ("scan_progress_updated", "on_scan_progress"),
        ("scan_state_changed", "on_scan_state_changed"),
        ("task_progress_updated", "on_task_progress"),
        ("tun_status_changed", "on_tun_status_changed"),
        ("auto_locations_updated", "on_auto_locations_updated"),
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



def _polish_all_tables_and_buttons(window):
    from PySide6.QtWidgets import QPushButton, QTableWidget, QWidget
    for tbl in window.findChildren(QTableWidget):
        try:
            vh = tbl.verticalHeader()
            if vh is not None and vh.defaultSectionSize() < 44:
                vh.setDefaultSectionSize(44)
            rows = tbl.rowCount()
            cols = tbl.columnCount()
            action_cols = set()
            for r in range(rows):
                if tbl.rowHeight(r) < 42:
                    tbl.setRowHeight(r, 44)
                for c in range(cols):
                    cw = tbl.cellWidget(r, c)
                    if cw is None:
                        continue
                    btns = [cw] if isinstance(cw, QPushButton) else cw.findChildren(QPushButton)
                    if not btns:
                        continue
                    action_cols.add(c)
                    if isinstance(cw, QWidget) and (cw.layout() is not None):
                        cw.layout().setContentsMargins(4, 3, 4, 3)
                        cw.layout().setSpacing(4)
                    for b in btns:
                        txt = (b.text() or "").strip()
                        if (not txt) and b.icon().isNull():
                            b.setText("اتصال فوری")
                            txt = "اتصال فوری"
                        b.setMinimumHeight(26)
                        b.setMaximumHeight(32)
                        if txt:
                            b.setMinimumWidth(max(88, min(140, len(txt) * 8 + 24)))
                        old_ss = b.styleSheet() or ""
                        if "/*alan-cell-btn*/" not in old_ss:
                            is_danger = any(k in old_ss.lower() or k in txt.lower() for k in ("#ef4444", "#dc2626", "delete", "حذف"))
                            fg = "#FEE2E2" if is_danger else "#ECFDF5"
                            bg_fallback = "" if ("background" in old_ss.lower()) else (
                                "background-color: #7F1D1D; border: 1px solid #EF4444; border-radius: 6px;"
                                if is_danger else
                                "background-color: #065F46; border: 1px solid #10B981; border-radius: 6px;"
                            )
                            b.setStyleSheet(
                                f"{old_ss}; {bg_fallback} padding: 2px 10px; margin: 0px; "
                                f"min-height: 26px; font-size: 11px; font-weight: 700; color: {fg}; /*alan-cell-btn*/"
                            )
            for ac in action_cols:
                if tbl.columnWidth(ac) < 132:
                    tbl.setColumnWidth(ac, 136)
        except Exception:
            pass


def _sync_version_badges(window):
    for cmb in window.findChildren(QComboBox):
        items_txt = [cmb.itemText(i).lower() for i in range(cmb.count())]
        if ('chrome' in items_txt) and not any('custom_poly' in t for t in items_txt):
            cmb.insertItem(0, 'custom_poly', 'custom_poly')
            if not any('random' == t for t in items_txt):
                cmb.insertItem(1, 'random', 'random')
    window.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
    ver_pattern = re.compile(r"^v?\d+\.\d+(?:\.\d+)?(?:\s+CORE)?$", re.IGNORECASE)
    for lbl in window.findChildren(QLabel):
        txt = (lbl.text() or "").strip()
        if ver_pattern.match(txt):
            lbl.setText(f"v{APP_VERSION}")


def main():
    _set_windows_app_id()
    base_dir = _resolve_runtime_base_dir()
    for sub in ("core", "configs", "logs", os.path.join("assets", "fonts")):
        os.makedirs(os.path.join(base_dir, sub), exist_ok=True)

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    _load_bundled_fonts(base_dir)

    for icon_name in ("logo.ico", "app_icon.ico", "logo.png"):
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
    polish_timer = QTimer(window)
    polish_timer.setInterval(450)
    polish_timer.timeout.connect(lambda: _polish_all_tables_and_buttons(window))
    polish_timer.start()
    controller.scan_row_emitted.connect(lambda _r: QTimer.singleShot(20, lambda: _polish_all_tables_and_buttons(window)))
    controller.scan_results_ranked.connect(lambda _rs: QTimer.singleShot(20, lambda: _polish_all_tables_and_buttons(window)))
    controller.profiles_updated.connect(lambda _p, _i: QTimer.singleShot(20, lambda: _polish_all_tables_and_buttons(window)))
    app.aboutToQuit.connect(controller.shutdown)

    def _initial_hydrate():
        _sync_version_badges(window)
        controller.engine.emit_log(f"[{APP_NAME} v{APP_VERSION}] Xray Core & Adaptive Engine Ready.")
        controller.engine._notify_settings_updated()
        controller.engine._notify_subscriptions_updated()
        controller.engine._notify_profiles_updated(save_selection=False)
        controller.engine._notify_verified_outputs_updated()
        controller.engine._notify_auto_locations_updated()
        if "--tun-on" in sys.argv:
            controller.engine.set_tun_mode(True)
        controller.engine._push_telemetry()
        if "--resume-connect" in sys.argv:
            QTimer.singleShot(300, controller.request_connect)

    QTimer.singleShot(40, _initial_hydrate)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()