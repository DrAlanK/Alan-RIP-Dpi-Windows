import ctypes
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from PySide6.QtCore import QLocale, QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget

ENGLISH_LOCALE = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
_FONTS_LOADED = False
_CUSTOM_UI_FAMILIES: list[str] = []
_CUSTOM_MONO_FAMILIES: list[str] = []


@dataclass(frozen=True)
class ThemePalette:
    name: str
    is_dark: bool
    window_bg: str
    surface_bg: str
    surface_hi: str
    surface_lo: str
    header_bg: str
    rail_bg: str
    card_bg: str
    card_hover_bg: str
    subtle_bg: str
    input_bg: str
    neu_shadow_dark: str
    neu_shadow_light: str
    neu_dark_alpha: int
    neu_light_alpha: int
    neu_bevel_light: str
    neu_bevel_dark: str
    card_border: str
    card_glow_border: str
    table_grid: str
    table_row_alt: str
    table_sel_bg: str
    accent_primary: str
    accent_secondary: str
    accent_soft_bg: str
    button_text_on_accent: str
    text_primary: str
    text_secondary: str
    text_muted: str
    emerald: str
    cyan: str
    warning: str
    danger: str


DARK_PALETTE = ThemePalette(
    name="dark",
    is_dark=True,
    window_bg="#181F2C",
    surface_bg="#181F2C",
    surface_hi="#1E2738",
    surface_lo="#141A25",
    header_bg="#181F2C",
    rail_bg="#181F2C",
    card_bg="#181F2C",
    card_hover_bg="#1D2535",
    subtle_bg="#131923",
    input_bg="#121722",
    neu_shadow_dark="#0A0D14",
    neu_shadow_light="#29354B",
    neu_dark_alpha=155,
    neu_light_alpha=68,
    neu_bevel_light="rgba(255, 255, 255, 0.09)",
    neu_bevel_dark="rgba(6, 9, 14, 0.65)",
    card_border="rgba(255, 255, 255, 0.06)",
    card_glow_border="rgba(255, 208, 0, 0.36)",
    table_grid="rgba(255, 255, 255, 0.04)",
    table_row_alt="rgba(10, 14, 21, 0.28)",
    table_sel_bg="rgba(255, 208, 0, 0.16)",
    accent_primary="#FFD000",
    accent_secondary="#F59E0B",
    accent_soft_bg="rgba(255, 208, 0, 0.14)",
    button_text_on_accent="#10151F",
    text_primary="#F1F5F9",
    text_secondary="#CBD5E1",
    text_muted="#7E8FA6",
    emerald="#10B981",
    cyan="#38BDF8",
    warning="#F97316",
    danger="#EF4444",
)

LIGHT_PALETTE = ThemePalette(
    name="light",
    is_dark=False,
    window_bg="#E4EAF2",
    surface_bg="#E4EAF2",
    surface_hi="#EDF2F8",
    surface_lo="#DAE2EC",
    header_bg="#E4EAF2",
    rail_bg="#E4EAF2",
    card_bg="#E4EAF2",
    card_hover_bg="#EAF0F7",
    subtle_bg="#DAE1EB",
    input_bg="#D7DFEA",
    neu_shadow_dark="#B8C4D4",
    neu_shadow_light="#FFFFFF",
    neu_dark_alpha=165,
    neu_light_alpha=225,
    neu_bevel_light="rgba(255, 255, 255, 0.85)",
    neu_bevel_dark="rgba(163, 177, 198, 0.55)",
    card_border="rgba(163, 177, 198, 0.35)",
    card_glow_border="rgba(217, 155, 0, 0.48)",
    table_grid="rgba(15, 23, 42, 0.05)",
    table_row_alt="rgba(163, 177, 198, 0.14)",
    table_sel_bg="rgba(234, 179, 8, 0.18)",
    accent_primary="#EAB308",
    accent_secondary="#D97706",
    accent_soft_bg="rgba(234, 179, 8, 0.16)",
    button_text_on_accent="#0F172A",
    text_primary="#1E293B",
    text_secondary="#334155",
    text_muted="#64748B",
    emerald="#059669",
    cyan="#0284C7",
    warning="#EA580C",
    danger="#DC2626",
)


_TRANSLATIONS: dict[str, tuple[str, str]] = {
    "app_title": ("Alan-RIP-Dpi", "Alan-RIP-Dpi"),
    "nav_home": ("Home", "خانه"),
    "nav_configs": ("Configs", "کانفیگ‌ها"),
    "nav_lab": ("Lab", "آزمایشگاه"),
    "nav_routing": ("Settings", "تنظیمات"),
    "nav_logs": ("Logs", "گزارش زنده"),
    "local_node_ir": ("Origin: Iran", "مبدأ: ایران"),
    "theme_toggle_tip": ("Switch Dark / Light Neumorphism", "تغییر تم نئومورفیک تیره / روشن"),
    "lang_toggle_tip": ("Switch Language (EN / FA)", "تغییر زبان (EN / FA)"),
    "stop": ("Stop", "توقف"),
    "cancel": ("Cancel", "انصراف"),
    "save": ("Save Changes", "ذخیره تغییرات"),
    "close": ("Close", "بستن"),
    "delete": ("Delete", "حذف"),
    "status_idle": ("Ready to Connect", "آماده اتصال"),
    "status_connecting": ("Establishing Secure Tunnel...", "در حال برقراری تونل امن..."),
    "status_connected": ("Connected & Protected", "متصل و ایمن"),
    "status_error": ("Connection Interrupted", "اختلال در برقراری اتصال"),
    "sub_idle": ("Select Smart Auto-Pool or a Verified Lab Output below.", "حالت اتصال خودکار یا یکی از خروجی‌های تاییدشده آزمایشگاه را انتخاب کنید."),
    "btn_connect": ("Smart Connect", "اتصال هوشمند"),
    "btn_cancel_connect": ("Cancel Probing (Click to Stop)", "لغو فرایند اتصال (کلیک برای توقف)"),
    "btn_disconnect": ("Disconnect Securely", "قطع اتصال امن"),
    "gemini_ready": ("Gemini Ready", "سازگار با Gemini"),
    "gemini_unverified": ("AI Unverified", "تست‌نشده AI"),
    "route_origin": ("Origin: Iran", "مبدأ: ایران"),
    "route_dest": ("Destination: {country}", "مقصد: {country}"),
    "hud_node_target": ("EGRESS ENDPOINT", "نقطه خروجی تونل"),
    "hud_live_spectrum": ("NEUMORPHIC SIGNAL SPECTRUM", "طیف زنده سیگنال تونل"),
    "card_egress_ip": ("Egress IP", "آدرس IP خروجی"),
    "card_real_ping": ("Real Ping", "پینگ واقعی"),
    "card_dl_speed": ("Download Speed", "سرعت دانلود"),
    "card_ul_speed": ("Upload Speed", "سرعت آپلود"),
    "egress_active_sub": ("Exit: {country} | Secure Route", "خروجی: {country} | مسیر امن"),
    "egress_idle_sub": ("No Active Tunnel", "بدون تونل فعال"),
    "output_selector_lbl": ("Final Output:", "خروجی نهایی:"),
    "auto_loc_lbl": ("Auto Location:", "لوکیشن خودکار:"),
    "auto_loc_all_default": ("All Locations (Smart Auto)", "همه لوکیشن‌ها (انتخاب هوشمند)"),
    "refresh_pool_tip": ("Refresh Auto-Connect Pool Locations", "بروزرسانی لوکیشن‌های مخزن خودکار"),
    "smart_auto_pool": ("Smart Auto-Pool (Best Verified / Auto-Hunt)", "حالت اتصال خودکار هوشمند (Smart Auto-Pool)"),
    "verified_item_fmt": ("[Verified] {name}  ({proto} | {vec} | {ping})", "[تاییدشده] {name}  ({proto} | {vec} | {ping})"),
    "ping_outputs_btn": ("Ping Outputs", "پینگ خروجی‌ها"),
    "clear_outputs_tip": ("Clear Verified Outputs List", "پاکسازی لیست خروجی‌های تاییدشده"),
    "sw_sys_proxy": ("System Proxy", "پروکسی سیستم"),
    "sw_tun_mode": ("TUN Mode", "حالت TUN"),
    "sw_autopilot": ("AutoPilot", "اتصال خودکار"),
    "vault_title": ("Config Vault & Subscriptions", "مخزن کانفیگ‌ها و سابسکریپشن"),
    "vault_subtitle": ("Organize configs by subscription, test delay and Gemini access, and send batches to Alan Lab.", "مدیریت کانفیگ‌ها به تفکیک سابسکریپشن، تست پینگ و Gemini و ارسال دسته‌جمعی به آزمایشگاه."),
    "tab_all": ("All ({n})", "همه ({n})"),
    "tab_manual": ("Manual ({n})", "دستی ({n})"),
    "manage_subs_btn": ("Manage Subscriptions", "مدیریت سابسکریپشن‌ها"),
    "hunt_sub_btn": ("Scan Sub & Connect Best", "پویش کامل ساب و اتصال به بهترین"),
    "hunt_sub_short_btn": ("Scan & Connect", "پویش و اتصال"),
    "hunt_sub_dlg_title": ("Scan Subscription & Connect Best", "پویش کامل ساب و اتصال به بهترین"),
    "hunt_sub_dlg_desc": ("Select an existing subscription or paste a new subscription URL to scan all configs and auto-connect to the fastest verified node.", "یکی از ساب‌های موجود را انتخاب کنید یا لینک ساب جدیدی وارد کنید تا تمام کانفیگ‌ها پویش شده و خودکار به بهترین گزینه متصل شود."),
    "hunt_sub_choose_existing": ("Target Subscription:", "انتخاب سابسکریپشن هدف:"),
    "hunt_sub_new_url_opt": ("--- Paste New Subscription URL Below ---", "--- وارد کردن لینک سابسکریپشن جدید در کادر پایین ---"),
    "hunt_sub_url_lbl": ("Subscription URL (https://...):", "آدرس لینک سابسکریپشن (https://...):"),
    "hunt_sub_title_lbl": ("Custom Group Title (Optional):", "عنوان دلخواه گروه (اختیاری):"),
    "hunt_sub_start_btn": ("Scan Sub & Connect Best", "پویش کامل و اتصال به بهترین"),
    "import_clip_btn": ("Import Clipboard", "افزودن از کلیپ‌بورد"),
    "new_config_btn": ("New Config", "کانفیگ جدید"),
    "ping_btn": ("Ping All / Selected", "پینگ همه / انتخابی"),
    "probe_gemini_btn": ("Test Gemini", "تست Gemini"),
    "sort_ping_btn": ("Sort by Ping", "مرتب‌سازی پینگ"),
    "dedup_btn": ("Deduplicate", "حذف تکراری"),
    "remove_dead_btn": ("Remove Dead", "حذف خراب‌ها"),
    "send_to_lab_btn": ("Send to Lab ({n})", "ارسال به آزمایشگاه ({n})"),
    "send_sub_to_lab_btn": ("Send Tab to Lab", "ارسال این تب به آزمایشگاه"),
    "search_vault_ph": ("Search name, host, SNI, protocol, method...", "جستجوی نام، آدرس، SNI، پروتکل، متد..."),
    "col_sel": ("Sel", "انتخاب"),
    "col_proto": ("Protocol", "پروتکل"),
    "col_name": ("Profile Name", "نام کانفیگ"),
    "col_endpoint": ("Server Endpoint", "آدرس و پورت"),
    "col_group": ("Group", "گروه"),
    "col_vector": ("Bound Method", "متد مقید"),
    "col_gemini": ("Gemini AI", "وضعیت Gemini"),
    "col_ping": ("Real Ping", "پینگ"),
    "ctx_set_active": ("Set as Active Profile", "انتخاب به‌عنوان کانفیگ فعال"),
    "ctx_real_ping": ("Real Delay Ping", "تست پینگ واقعی"),
    "ctx_check_gemini": ("Test Gemini", "تست Gemini"),
    "ctx_send_sel_lab": ("Send Selected to Lab", "ارسال انتخاب‌شده‌ها به آزمایشگاه"),
    "ctx_send_tab_lab": ("Send Current Tab/Sub to Lab", "ارسال کل این تب/ساب به آزمایشگاه"),
    "ctx_edit": ("Edit Config", "ویرایش کانفیگ"),
    "ctx_copy_uri": ("Copy URI", "کپی لینک کانفیگ"),
    "ctx_export_verified": ("Export Verified URIs", "کپی خروجی کانفیگ‌های سالم"),
    "ctx_delete_sel": ("Delete Selected", "حذف موارد انتخابی"),
    "vault_feedback_imported": ("Imported configs into '{group}'.", "کانفیگ‌ها به گروه «{group}» اضافه شدند."),
    "vault_feedback_copied": ("Copied URI(s) to clipboard.", "لینک کانفیگ در کلیپ‌بورد کپی شد."),
    "vault_feedback_empty_clip": ("Clipboard is empty.", "کلیپ‌بورد خالی است."),
    "lab_title": ("Alan Lab — Method Simulator & Clean IP Radar", "آزمایشگاه Alan Lab — شبیه‌ساز متد و رادار IP تمیز"),
    "lab_subtitle": ("Simulate anti-DPI methods across configs; verified winners automatically promote to Home.", "شبیه‌سازی متدهای عبوری روی کانفیگ‌ها؛ خروجی‌های تاییدشده خودکار به خانه منتقل می‌شوند."),
    "lab_mode_vectors": ("Config & Method Lab", "آزمایشگاه متد و کانفیگ"),
    "lab_mode_clean_ip": ("Clean IP Radar", "رادار آی‌پی تمیز کلودفلر"),
    "lab_scope_lbl": ("Input Scope:", "دامنه ورودی:"),
    "scope_batch": ("Selected Batch from Vault ({n})", "کانفیگ‌های ارسالی از مخزن ({n})"),
    "scope_sub": ("Subscription / Group", "کل یک سابسکریپشن / گروه"),
    "scope_single": ("Single Config", "تک کانفیگ انتخابی"),
    "lab_method_lbl": ("Method:", "انتخاب متد:"),
    "method_all": ("All", "همه"),
    "chk_lab_gemini": ("Probe Gemini AI Access", "تست دسترسی Gemini AI"),
    "chk_lab_autoconnect": ("Auto-Connect Best Winner", "اتصال خودکار به بهترین خروجی"),
    "sw_winners_only": ("Show Verified Winners Only (True)", "فقط نمایش خروجی‌های سالم (True)"),
    "btn_start_lab": ("Start Lab Simulation", "شروع شبیه‌سازی آزمایشگاه"),
    "btn_stop_lab": ("Stop Scanner", "توقف اسکنر"),
    "btn_promote_home": ("Promote & Go to Home ({n})", "انتقال و رفتن به خانه ({n})"),
    "lab_col_rank": ("Rank", "رتبه"),
    "lab_col_profile": ("Config / Target", "کانفیگ هدف"),
    "lab_col_vector": ("Method", "متد برنده"),
    "lab_col_ping": ("Tunnel Ping", "پینگ تونل"),
    "lab_col_upload": ("Upload / AI", "آپلود / AI"),
    "lab_col_status": ("Verdict", "وضعیت"),
    "lab_col_action": ("Action", "عملیات"),
    "btn_connect_now": ("Connect Now", "اتصال فوری"),
    "radar_port_lbl": ("Target Cloudflare Port:", "پورت هدف کلودفلر:"),
    "btn_start_radar": ("Start Clean IP Scan", "شروع اسکن آی‌پی تمیز"),
    "btn_apply_sel_cdn": ("Apply to Selected Config", "اعمال روی کانفیگ انتخابی"),
    "btn_apply_all_cdn": ("Apply to All CDN Configs", "اعمال روی کل کانفیگ‌های CDN"),
    "radar_col_ip": ("Clean IP Address", "آدرس IP تمیز"),
    "radar_col_tcp": ("TCP RTT", "پینگ TCP"),
    "radar_col_tls": ("TLS Handshake", "پینگ TLS"),
    "radar_col_score": ("Quality Score", "امتیاز کیفیت"),
    "settings_title": ("Routing, Behavior & Core Architecture", "مسیریابی، رفتار سیستم و معماری هسته"),
    "settings_subtitle": ("Configure traffic split-tunneling, System Tray behavior, auto-updates, and core engine settings.", "پیکربندی مسیریابی ترافیک، رفتار سینی سیستم، بروزرسانی خودکار و تنظیمات پیشرفته هسته."),
    "stab_routing": ("Traffic Routing", "مسیریابی ترافیک"),
    "stab_behavior": ("Behavior & Subscriptions", "رفتار برنامه و اشتراک‌ها"),
    "stab_core": ("Advanced Core & Methods", "هسته پیشرفته و متدها"),
    "routing_mode_lbl": ("Routing Strategy:", "استراتژی مسیریابی:"),
    "rmode_bypass_ir": ("Bypass Iran & LAN (bypass_ir)", "عبور مستقیم ایران و شبکه محلی (bypass_ir)"),
    "rmode_global": ("Global Tunnel (global)", "تونل سراسری کل ترافیک (global)"),
    "rmode_custom": ("Custom Domain/IP Rules (custom)", "قوانین سفارشی دامنه و آی‌پی (custom)"),
    "sw_block_quic": ("Block QUIC Protocol (UDP 443)", "مسدودسازی پروتکل QUIC (پورت UDP 443)"),
    "sw_block_quic_desc": ("Forces browsers to fall back to TLS/TCP so anti-DPI mutators can fragment SNI cleanly.", "مرورگرها را مجبور به استفاده از TCP/TLS می‌کند تا تکه‌تکه‌سازی SNI دقیق عمل کند."),
    "remote_dns_lbl": ("Remote Secure DNS:", "سرور DNS امن خارجی:"),
    "domestic_dns_lbl": ("Domestic Direct DNS:", "سرور DNS مستقیم داخلی:"),
    "direct_domains_lbl": ("Custom Direct Domains / CIDR:", "دامنه‌ها و رنج‌های مستقیم (Direct):"),
    "proxy_domains_lbl": ("Custom Proxied Domains / CIDR:", "دامنه‌های اجباری تونل (Proxy):"),
    "blocked_domains_lbl": ("Custom Blocked Domains / Ads:", "دامنه‌های مسدودشده (Blocked):"),
    "sw_min_tray": ("Minimize to System Tray on Window Close", "انتقال به System Tray هنگام بستن پنجره"),
    "sw_min_tray_desc": ("Keeps tunnel running in background when closing the main window.", "با زدن دکمه بستن، برنامه قطع نمی‌شود و در سینی ویندوز فعال می‌ماند."),
    "sw_pool_fallback": ("Smart Auto-Connect Pool Fallback", "سوییچ خودکار بین خروجی‌های تاییدشده (Auto-Pool)"),
    "sw_pool_fallback_desc": ("Automatically hops to the next verified output if the active node degrades.", "در صورت افت کیفیت سرور فعلی، خودکار به بهترین خروجی تاییدشده بعدی متصل می‌شود."),
    "sw_yt_guard": ("Require 6s YouTube Stream Guard", "تست بقای ۶ ثانیه‌ای استریم یوتیوب"),
    "sw_yt_guard_desc": ("Verifies sustained post-handshake data flow to prevent playback freeze.", "پایداری جریان داده پس از هندشیک TLS را بررسی می‌کند تا ویدیو فریز نشود."),
    "sw_upload_burst": ("Verify Upload Stream Burst", "ارزیابی سلامت جریان آپلود"),
    "sw_upload_burst_desc": ("Tests outbound payload transmission to prevent stalled HTTP POST/uploads.", "ارسال بسته‌های خروجی حجیم را برای جلوگیری از قفل شدن آپلود آزمایش می‌کند."),
    "sw_watchdog": ("Self-Healing Background Watchdog", "نگهبان خودترمیم‌گر پس‌زمینه (Watchdog)"),
    "sw_watchdog_desc": ("Continuously monitors tunnel RTT and silently repairs dropped sockets.", "پینگ و سلامت سوکت‌ها را پایش کرده و قطعی‌های لحظه‌ای را بی‌صدا ترمیم می‌کند."),
    "sub_autoupdate_lbl": ("Subscription Auto-Update Interval:", "بازه بروزرسانی خودکار سابسکریپشن‌ها:"),
    "sub_off": ("Off (Manual Only)", "خاموش (فقط دستی)"),
    "sub_every_h": ("Every {h}h", "هر {h} ساعت"),
    "engine_mode_lbl": ("Core Engine Mode:", "حالت موتور ضد فیلتر:"),
    "emode_hybrid": ("Auto Hybrid (Mutator + Xray Fragment)", "ترکیبی هوشمند (Auto Hybrid)"),
    "emode_prop": ("Proprietary Mutator Only", "فقط موتور تغییر بایت اختصاصی"),
    "emode_frag": ("Native Xray Fragment Only", "فقط فرگمنت بومی Xray"),
    "manual_vec_lbl": ("Manual Method Override:", "انتخاب دستی متد عبوری:"),
    "sw_native_frag": ("Enable Native Xray Fragment", "فعال‌سازی فرگمنت بومی Xray"),
    "frag_packets_lbl": ("Fragment Packets:", "بسته‌های فرگمنت:"),
    "frag_length_lbl": ("Fragment Length (Bytes):", "طول قطعات فرگمنت:"),
    "frag_interval_lbl": ("Fragment Interval (ms):", "فاصله زمانی ارسال (ms):"),
    "tls_fp_lbl": ("uTLS Fingerprint:", "اثرانگشت رمزنگاری (Fingerprint):"),
    "alpn_lbl": ("ALPN Override:", "مقدار ALPN:"),
    "early_data_lbl": ("WebSocket EarlyData:", "مقدار WS EarlyData:"),
    "sw_mux": ("Enable TCP Multiplexing (Mux)", "فعال‌سازی مالتی‌پلکسینگ (Mux)"),
    "stride_lbl": ("Forward Stride (Bytes):", "گام پیشروی بایت (Stride):"),
    "jitter_lbl": ("Stride Jitter (Bytes):", "نوسان گام (Jitter):"),
    "tun_mtu_lbl": ("TUN Interface MTU:", "اندازه بسته شبکه مجازی (TUN MTU):"),
    "socks_port_lbl": ("Local SOCKS5 Port:", "پورت محلی SOCKS5:"),
    "http_port_lbl": ("Local HTTP Port:", "پورت محلی HTTP:"),
    "bridge_port_lbl": ("Internal Mutator Bridge Port:", "پورت پل داخلی هسته (Bridge):"),
    "logs_title": ("Live Engineering Console", "کنسول مهندسی گزارش زنده"),
    "logs_search_ph": ("Filter logs by keyword, method, IP, error...", "فیلتر گزارش بر اساس کلیدواژه، متد، IP یا خطا..."),
    "logs_all": ("All", "همه"),
    "logs_warn": ("Warnings / Errors", "هشدار و خطا"),
    "logs_copy": ("Copy Logs", "کپی گزارش"),
    "logs_clear": ("Clear", "پاکسازی"),
    "logs_save": ("Export File", "ذخیره فایل"),
    "subs_dlg_title": ("Subscription Manager", "مدیریت لینک‌های سابسکریپشن"),
    "subs_title_ph": ("Group Title (e.g. Premium-DE)", "عنوان گروه (مثلاً VIP-DE)"),
    "subs_url_ph": ("https://example.com/sub/token", "https://example.com/sub/token"),
    "subs_add_btn": ("Add Subscription", "افزودن ساب"),
    "subs_refresh_btn": ("Refresh All Now", "بروزرسانی همه"),
    "editor_new_title": ("Create New Config", "ساخت کانفیگ جدید"),
    "editor_edit_title": ("Edit Config Parameters", "ویرایش پارامترهای کانفیگ"),
    "editor_use_raw": ("Direct Raw URI Mode", "ویرایش مستقیم لینک خام (Raw URI)"),
    "tray_connect": ("Connect Smart Tunnel", "اتصال هوشمند"),
    "tray_disconnect": ("Disconnect Tunnel", "قطع اتصال"),
    "tray_sys_proxy": ("System Proxy", "پروکسی سیستم ویندوز"),
    "tray_tun_mode": ("TUN Virtual Adapter", "حالت شبکه مجازی TUN"),
    "tray_open": ("Open Alan-RIP-Dpi", "باز کردن پنجره Alan-RIP-Dpi"),
    "tray_exit": ("Exit", "خروج کامل"),
    "tray_minimized_msg": ("Alan-RIP-Dpi is running in the background.", "برنامه در پس‌زمینه در حال اجراست."),
}


class I18nManager(QObject):
    language_changed = Signal(str)

    def __init__(self, initial_lang: str = "fa"):
        super().__init__()
        self._lang = "en" if str(initial_lang).lower().startswith("en") else "fa"

    @property
    def lang(self) -> str:
        return self._lang

    def is_rtl(self) -> bool:
        return self._lang == "fa"

    def layout_direction(self) -> Qt.LayoutDirection:
        return Qt.LayoutDirection.RightToLeft if self._lang == "fa" else Qt.LayoutDirection.LeftToRight

    def set_language(self, lang: str) -> None:
        norm = "en" if str(lang).lower().startswith("en") else "fa"
        if norm != self._lang:
            self._lang = norm
            self.language_changed.emit(self._lang)

    def toggle_language(self) -> str:
        nxt = "en" if self._lang == "fa" else "fa"
        self.set_language(nxt)
        return nxt

    def t(self, key: str, **kwargs) -> str:
        pair = _TRANSLATIONS.get(key)
        if pair is None:
            raw = key
        else:
            raw = pair[0] if self._lang == "en" else pair[1]
        if kwargs:
            try:
                return raw.format(**kwargs)
            except Exception:
                return raw
        return raw


I18N = I18nManager("fa")

_MONO_KEYWORDS = ("mono", "code", "consolas", "courier", "jetbrains", "cascadia", "fira", "hack")


def load_application_fonts() -> None:
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return
    if QGuiApplication.instance() is None:
        return
    _FONTS_LOADED = True

    here = Path(__file__).resolve().parent
    pkg_dir = here.parent
    proj_root = pkg_dir.parent
    exe_dir = Path(sys.argv[0]).resolve().parent if sys.argv else Path.cwd()

    candidate_roots = [
        Path.cwd() / "assets",
        Path.cwd() / "fonts",
        exe_dir / "assets",
        exe_dir / "fonts",
        proj_root / "assets",
        proj_root / "fonts",
        pkg_dir / "assets",
        here / "assets",
        here / "fonts",
    ]

    seen_files: set[Path] = set()
    discovered_files: list[Path] = []
    for folder in candidate_roots:
        if not folder.is_dir():
            continue
        for fpath in sorted(folder.rglob("*")):
            if fpath.is_file() and fpath.suffix.lower() in (".ttf", ".otf", ".ttc"):
                resolved = fpath.resolve()
                if resolved not in seen_files:
                    seen_files.add(resolved)
                    discovered_files.append(resolved)

    for font_path in discovered_files:
        fid = QFontDatabase.addApplicationFont(str(font_path))
        if fid < 0:
            continue
        stem_low = font_path.stem.lower()
        for fam in QFontDatabase.applicationFontFamilies(fid):
            fam_clean = str(fam).strip()
            if not fam_clean:
                continue
            fam_low = fam_clean.lower()
            is_mono = any(kw in fam_low or kw in stem_low for kw in _MONO_KEYWORDS)
            if is_mono:
                if fam_clean not in _CUSTOM_MONO_FAMILIES:
                    _CUSTOM_MONO_FAMILIES.append(fam_clean)
            else:
                if fam_clean not in _CUSTOM_UI_FAMILIES:
                    _CUSTOM_UI_FAMILIES.append(fam_clean)


def resolve_ui_font_family(lang: str | None = None) -> str:
    load_application_fonts()
    if _CUSTOM_UI_FAMILIES:
        return _CUSTOM_UI_FAMILIES[0]

    active_lang = lang or I18N.lang
    available = set(QFontDatabase.families())
    if active_lang == "en":
        preferred = [
            "Vazirmatn",
            "Vazirmatn FD",
            "Vazirmatn UI",
            "IRANSansX",
            "Dana",
            "Peyda",
            "Kalameh",
            "Yekan Bakh",
            "Segoe UI Variable Display",
            "Segoe UI",
        ]
    else:
        preferred = [
            "Vazirmatn",
            "Vazirmatn FD",
            "Vazirmatn UI",
            "Vazir",
            "IRANSansX",
            "IRANSans",
            "Dana",
            "Peyda",
            "Kalameh",
            "Yekan Bakh",
            "Estedad",
            "Shabnam",
            "Samim",
            "Segoe UI Variable Display",
            "Segoe UI",
        ]
    for family in preferred:
        if family in available:
            return family
    return "Segoe UI"


def resolve_mono_font_family() -> str:
    load_application_fonts()
    if _CUSTOM_MONO_FAMILIES:
        return _CUSTOM_MONO_FAMILIES[0]
    preferred = ["JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New"]
    available = set(QFontDatabase.families())
    for family in preferred:
        if family in available:
            return family
    return "Consolas"


def make_ui_font(size: int = 10, weight: QFont.Weight = QFont.Weight.Medium) -> QFont:
    font = QFont(resolve_ui_font_family(), size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality)
    return font


def make_mono_font(size: int = 10, bold: bool = False) -> QFont:
    font = QFont(resolve_mono_font_family(), size)
    font.setWeight(QFont.Weight.Bold if bold else QFont.Weight.DemiBold)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.PreferQuality)
    return font


def enforce_english_ltr(widget: QWidget, mono_size: int = 10, bold: bool = False) -> None:
    widget.setLocale(ENGLISH_LOCALE)
    widget.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
    widget.setFont(make_mono_font(mono_size, bold=bold))


def lock_widget_dimensions(widget: QWidget, width: int, height: int) -> None:
    widget.setMinimumSize(width, height)
    widget.setMaximumSize(width, height)


def make_transparent_scroll_area(content_widget: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    scroll.setAutoFillBackground(False)

    viewport = scroll.viewport()
    viewport.setObjectName("ScrollViewport")
    viewport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    viewport.setAutoFillBackground(False)

    content_widget.setObjectName("ScrollContent")
    content_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    content_widget.setAutoFillBackground(False)

    scroll.setWidget(content_widget)
    return scroll


def strip_emojis(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(
        r"[\U0001F1E6-\U0001F1FF\U0001F300-\U0001FAFF\u2600-\u27BF]+",
        "",
        str(text),
    )
    cleaned = re.sub(r"(?i)\bbehrooz\b", "Alan-Core", cleaned)
    cleaned = re.sub(r"(?i)\boob\b", "PulseSync", cleaned)
    return cleaned.strip()


def get_bool(mapping: dict, key: str, default: bool) -> bool:
    if not isinstance(mapping, dict) or key not in mapping:
        return default
    val = mapping.get(key)
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        low = val.strip().lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
    return default


def get_int(mapping: dict, key: str, default: int = 0) -> int:
    if not isinstance(mapping, dict) or key not in mapping:
        return default
    val = mapping.get(key)
    if val is None:
        return default
    if isinstance(val, bool):
        return int(val)
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def apply_windows_titlebar_theme(widget: QWidget, is_dark: bool) -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        dwmapi = ctypes.windll.dwmapi
        dark_val = ctypes.c_int(1 if is_dark else 0)
        for attr in (20, 19):
            if dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd),
                ctypes.c_uint(attr),
                ctypes.byref(dark_val),
                ctypes.sizeof(dark_val),
            ) == 0:
                break
        caption_color = ctypes.c_uint(0x002C1F18 if is_dark else 0x00F2EAE4)
        text_color = ctypes.c_uint(0x00F9F5F1 if is_dark else 0x003B291E)
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(35),
            ctypes.byref(caption_color),
            ctypes.sizeof(caption_color),
        )
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(36),
            ctypes.byref(text_color),
            ctypes.sizeof(text_color),
        )
    except Exception:
        pass


def build_qpalette(p: ThemePalette) -> QPalette:
    pal = QPalette()
    bg = QColor(p.window_bg)
    surface = QColor(p.surface_bg)
    fg = QColor(p.text_primary)
    accent = QColor(p.accent_primary)
    pal.setColor(QPalette.ColorRole.Window, bg)
    pal.setColor(QPalette.ColorRole.WindowText, fg)
    pal.setColor(QPalette.ColorRole.Base, QColor(p.input_bg))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(p.subtle_bg))
    pal.setColor(QPalette.ColorRole.Text, fg)
    pal.setColor(QPalette.ColorRole.Button, surface)
    pal.setColor(QPalette.ColorRole.ButtonText, fg)
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(p.surface_hi))
    pal.setColor(QPalette.ColorRole.ToolTipText, fg)
    pal.setColor(QPalette.ColorRole.Highlight, accent)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(p.button_text_on_accent))
    return pal


def build_stylesheet(p: ThemePalette, lang: str = "fa") -> str:
    family = resolve_ui_font_family(lang)
    mono = resolve_mono_font_family()
    badge_fg = p.accent_primary if p.is_dark else "#9A6700"

    return f"""
    QWidget {{
        font-family: '{family}', 'Vazirmatn', 'IRANSansX', 'Segoe UI';
        color: {p.text_primary};
        outline: none;
    }}
    QToolTip {{
        background-color: {p.surface_hi};
        color: {p.text_primary};
        border: 1px solid {p.neu_bevel_light};
        border-radius: 10px;
        padding: 6px 11px;
        font-family: '{family}';
        font-size: 11px;
        font-weight: 600;
    }}
    QMenu {{
        background-color: {p.surface_hi};
        color: {p.text_primary};
        border: 1px solid {p.neu_bevel_light};
        border-radius: 12px;
        padding: 6px;
        font-family: '{family}';
    }}
    QMenu::item {{
        padding: 7px 22px 7px 14px;
        border-radius: 8px;
        font-weight: 600;
    }}
    QMenu::item:selected {{
        background-color: {p.accent_soft_bg};
        color: {badge_fg};
    }}
    QMenu::separator {{
        height: 1px;
        background: {p.card_border};
        margin: 5px 8px;
    }}
    QScrollArea,
    QScrollArea > QWidget,
    QScrollArea > QWidget > QWidget,
    QWidget#ScrollViewport,
    QWidget#ScrollContent {{
        background: transparent;
        background-color: transparent;
        border: none;
    }}
    QFrame#MainShell {{
        background-color: {p.window_bg};
        border: none;
    }}
    QDialog#ThemedDialog {{
        background-color: {p.window_bg};
    }}
    QLabel {{
        background: transparent;
        font-family: '{family}';
    }}
    QLabel#MutedLabel {{
        color: {p.text_muted};
        font-size: 11px;
    }}
    QLabel#SecondaryLabel {{
        color: {p.text_secondary};
        font-size: 12px;
        font-weight: 600;
    }}
    QLabel#SecondaryLabel:disabled {{
        color: {p.text_muted};
    }}
    QLabel#PageTitle {{
        color: {p.text_primary};
        font-size: 17px;
        font-weight: 800;
    }}
    QLabel#BadgePill {{
        background-color: {p.input_bg};
        color: {badge_fg};
        border-top: 1px solid {p.neu_bevel_dark};
        border-left: 1px solid {p.neu_bevel_dark};
        border-right: 1px solid {p.neu_bevel_light};
        border-bottom: 1px solid {p.neu_bevel_light};
        border-radius: 10px;
        padding: 3px 10px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 11px;
    }}
    QLabel#EmeraldPill {{
        background-color: rgba(16, 185, 129, 0.14);
        color: {p.emerald};
        border: 1px solid rgba(16, 185, 129, 0.42);
        border-radius: 10px;
        padding: 3px 10px;
        font-family: '{mono}', 'Consolas';
        font-weight: 800;
        font-size: 10px;
    }}
    QLabel#MutedPill {{
        background-color: {p.input_bg};
        color: {p.text_muted};
        border-top: 1px solid {p.neu_bevel_dark};
        border-left: 1px solid {p.neu_bevel_dark};
        border-right: 1px solid {p.neu_bevel_light};
        border-bottom: 1px solid {p.neu_bevel_light};
        border-radius: 10px;
        padding: 3px 10px;
        font-family: '{mono}', 'Consolas';
        font-weight: 700;
        font-size: 10px;
    }}
    QComboBox, QLineEdit, QSpinBox, QPlainTextEdit#CodeEditor {{
        background-color: {p.input_bg};
        color: {p.text_primary};
        border-top: 2px solid {p.neu_bevel_dark};
        border-left: 2px solid {p.neu_bevel_dark};
        border-right: 1px solid {p.neu_bevel_light};
        border-bottom: 1px solid {p.neu_bevel_light};
        border-radius: 12px;
        padding: 6px 12px;
        min-height: 24px;
        font-family: '{family}';
        font-weight: 600;
        selection-background-color: {p.accent_primary};
        selection-color: {p.button_text_on_accent};
    }}
    QComboBox:hover, QLineEdit:hover, QSpinBox:hover,
    QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QPlainTextEdit#CodeEditor:focus {{
        border: 1px solid {p.card_glow_border};
        background-color: {p.subtle_bg};
    }}
    QComboBox:disabled, QLineEdit:disabled, QSpinBox:disabled {{
        color: {p.text_muted};
        background-color: {p.surface_lo};
        border: 1px solid {p.card_border};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 24px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {p.surface_hi};
        color: {p.text_primary};
        border: 1px solid {p.card_glow_border};
        border-radius: 11px;
        selection-background-color: {p.accent_soft_bg};
        selection-color: {p.text_primary};
        padding: 5px;
        font-family: '{family}';
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background: transparent;
        border: none;
        width: 16px;
    }}
    QCheckBox {{
        color: {p.text_secondary};
        spacing: 8px;
        font-family: '{family}';
        font-size: 12px;
        font-weight: 600;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 6px;
        border-top: 2px solid {p.neu_bevel_dark};
        border-left: 2px solid {p.neu_bevel_dark};
        border-right: 1px solid {p.neu_bevel_light};
        border-bottom: 1px solid {p.neu_bevel_light};
        background-color: {p.input_bg};
    }}
    QCheckBox::indicator:checked {{
        background-color: {p.accent_primary};
        border: 1px solid {p.accent_primary};
    }}
    QTableWidget#VaultTable {{
        background-color: {p.input_bg};
        alternate-background-color: {p.table_row_alt};
        color: {p.text_primary};
        border-top: 2px solid {p.neu_bevel_dark};
        border-left: 2px solid {p.neu_bevel_dark};
        border-right: 1px solid {p.neu_bevel_light};
        border-bottom: 1px solid {p.neu_bevel_light};
        border-radius: 16px;
        gridline-color: {p.table_grid};
        selection-background-color: {p.table_sel_bg};
        selection-color: {p.text_primary};
        font-family: '{family}';
    }}
    QTableWidget#VaultTable::item {{
        padding: 6px 8px;
        border-bottom: 1px solid {p.table_grid};
    }}
    QTableWidget#VaultTable::item:selected {{
        background-color: {p.table_sel_bg};
        color: {p.text_primary};
    }}
    QHeaderView::section {{
        background-color: {p.surface_lo};
        color: {p.text_muted};
        border: none;
        border-bottom: 1px solid {p.card_border};
        padding: 9px 8px;
        font-family: '{family}';
        font-weight: 700;
        font-size: 11px;
    }}
    QPushButton#GhostBtn {{
        background-color: {p.surface_hi};
        color: {p.text_secondary};
        border-top: 1px solid {p.neu_bevel_light};
        border-left: 1px solid {p.neu_bevel_light};
        border-right: 2px solid {p.neu_bevel_dark};
        border-bottom: 2px solid {p.neu_bevel_dark};
        border-radius: 11px;
        padding: 6px 13px;
        font-family: '{family}';
        font-weight: 700;
        font-size: 11px;
    }}
    QPushButton#GhostBtn:hover {{
        color: {p.text_primary};
        border: 1px solid {p.card_glow_border};
    }}
    QPushButton#GhostBtn:pressed {{
        background-color: {p.input_bg};
        border-top: 2px solid {p.neu_bevel_dark};
        border-left: 2px solid {p.neu_bevel_dark};
        border-right: 1px solid {p.neu_bevel_light};
        border-bottom: 1px solid {p.neu_bevel_light};
    }}
    QPushButton#AccentBtn {{
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #FFE14D, stop:1 {p.accent_primary});
        color: {p.button_text_on_accent};
        border-top: 1px solid rgba(255, 255, 255, 0.55);
        border-left: 1px solid rgba(255, 255, 255, 0.45);
        border-right: 2px solid rgba(120, 83, 0, 0.45);
        border-bottom: 2px solid rgba(120, 83, 0, 0.55);
        border-radius: 11px;
        padding: 7px 15px;
        font-family: '{family}';
        font-weight: 800;
        font-size: 11px;
    }}
    QPushButton#AccentBtn:hover {{
        background-color: #FFE566;
    }}
    QPushButton#AccentBtn:pressed {{
        background-color: {p.accent_secondary};
    }}
    QPushButton#AccentBtn:disabled {{
        background-color: {p.input_bg};
        color: {p.text_muted};
        border: 1px solid {p.card_border};
    }}
    QPushButton#EmeraldBtn {{
        background-color: {p.surface_hi};
        color: {p.emerald};
        border-top: 1px solid rgba(16, 185, 129, 0.45);
        border-left: 1px solid rgba(16, 185, 129, 0.45);
        border-right: 2px solid {p.neu_bevel_dark};
        border-bottom: 2px solid {p.neu_bevel_dark};
        border-radius: 11px;
        padding: 6px 13px;
        font-family: '{family}';
        font-weight: 700;
        font-size: 11px;
    }}
    QPushButton#EmeraldBtn:hover {{
        background-color: rgba(16, 185, 129, 0.18);
    }}
    QPushButton#EmeraldBtn:pressed {{
        background-color: {p.input_bg};
    }}
    QPushButton#DangerBtn {{
        background-color: {p.surface_hi};
        color: {p.danger};
        border-top: 1px solid rgba(239, 68, 68, 0.40);
        border-left: 1px solid rgba(239, 68, 68, 0.40);
        border-right: 2px solid {p.neu_bevel_dark};
        border-bottom: 2px solid {p.neu_bevel_dark};
        border-radius: 11px;
        padding: 6px 13px;
        font-family: '{family}';
        font-weight: 700;
        font-size: 11px;
    }}
    QPushButton#DangerBtn:hover {{
        background-color: rgba(239, 68, 68, 0.18);
    }}
    QPushButton#DangerBtn:pressed {{
        background-color: {p.input_bg};
    }}
    QPushButton#LangPillBtn {{
        background-color: {p.surface_hi};
        color: {badge_fg};
        border-top: 1px solid {p.neu_bevel_light};
        border-left: 1px solid {p.neu_bevel_light};
        border-right: 2px solid {p.neu_bevel_dark};
        border-bottom: 2px solid {p.neu_bevel_dark};
        border-radius: 11px;
        padding: 5px 12px;
        font-family: '{mono}', 'Consolas';
        font-weight: 800;
        font-size: 11px;
    }}
    QPushButton#LangPillBtn:hover {{
        background-color: {p.accent_primary};
        color: {p.button_text_on_accent};
    }}
    QProgressBar#GoldProgress {{
        background-color: {p.input_bg};
        border-top: 2px solid {p.neu_bevel_dark};
        border-left: 2px solid {p.neu_bevel_dark};
        border-right: 1px solid {p.neu_bevel_light};
        border-bottom: 1px solid {p.neu_bevel_light};
        border-radius: 5px;
        height: 9px;
        text-align: center;
    }}
    QProgressBar#GoldProgress::chunk {{
        background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F59E0B, stop:0.5 #FFD000, stop:1 #10B981);
        border-radius: 4px;
    }}
    QPlainTextEdit#LogConsole {{
        background-color: {p.input_bg};
        color: {p.text_secondary};
        border-top: 2px solid {p.neu_bevel_dark};
        border-left: 2px solid {p.neu_bevel_dark};
        border-right: 1px solid {p.neu_bevel_light};
        border-bottom: 1px solid {p.neu_bevel_light};
        border-radius: 16px;
        padding: 14px;
        font-family: '{mono}', 'Consolas', monospace;
        font-size: 12px;
    }}
    QScrollBar:vertical {{
        background: {p.input_bg};
        width: 8px;
        margin: 6px 2px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.card_glow_border};
        min-height: 28px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
        height: 0px;
    }}
    QScrollBar:horizontal {{
        background: {p.input_bg};
        height: 8px;
        margin: 2px 6px;
        border-radius: 4px;
    }}
    QScrollBar::handle:horizontal {{
        background: {p.card_glow_border};
        min-width: 28px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    """