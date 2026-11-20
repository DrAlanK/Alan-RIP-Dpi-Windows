<div align="center">
  <img src="assets/logo.png" alt="Alan-RIP-Dpi Logo" width="110" />
  <h1>Alan-RIP-Dpi (Windows Desktop) — v1.5.0</h1>
  <p><b>Adaptive Anti-DPI Engine, Full-Duplex Byte Mutator, Regional PMTU Guard & Xray Routing Client for Windows</b></p>
  <p>
    <a href="https://github.com/DrAlanK/Alan-RIP-Dpi-Windows/releases/latest">Download Latest Release (v1.5.0)</a>
    ·
    <a href="https://github.com/DrAlanK/Alan-RIP-Dpi-Android">Android Version (Alan-RIP-Dpi-Android)</a>
    ·
    <a href="https://t.me/LabALan">Telegram Channel (@LabALan)</a>
  </p>
</div>

---

## معرفی اجمالی و تجربه کاربری (غیرفنی)

**Alan-RIP-Dpi** یک کلاینت دسکتاپ متن‌باز برای ویندوز مبتنی بر هسته **Xray-core** است که پیچیدگی‌های فنی دور زدن فیلترینگ (DPI)، رفع مشکل قفل شدن آپلود و سیاه‌چاله‌های شبکه‌های منطقه‌ای، تنظیم فرگمنت، تفکیک برنامه‌ها و تست صدها کانفیگ را در یک رابط کاربری نئومورفیک و یک‌کلیکی جمع کرده است:

- **اتصال خودکار هوشمند با انتخابگر لوکیشن:** بدون نیاز به داشتن کانفیگ شخصی، برنامه به مخزن ابری متصل شده و امکان انتخاب کشور مقصد (آلمان، هلند، فنلاند، آمریکا و...) را فراهم می‌کند.
- **تشخیص هوشمند کلیپ‌بورد و ایمپورت فایل (Drag & Drop):** کافی است لینک سابسکریپشن، کانفیگ‌های متنی یا متن Base64 را در کلیپ‌بورد کپی کنید؛ برنامه به‌صورت خودکار تشخیص می‌دهد لینک اشتراک است یا کانفیگ مستقیم. همچنین می‌توانید فایل‌های کانفیگ (Raw / Base64) را از طریق دکمه **«افزودن از فایل»** یا کشیدن و رها کردن (Drag & Drop) وارد کنید.
- **بروزرسانی تکی و همگانی سابسکریپشن‌ها:** در نوار تب‌های کانفیگ می‌توانید فقط ساب فعال فعلی (**بروزرسانی همین ساب**) یا کل اشتراک‌ها (**بروزرسانی کل ساب‌ها**) را با یک کلیک آپدیت کنید.
- **پشتیبانی از پروتکل‌های Xray و SOCKS5:** پشتیبانی کامل از `VLESS`، `VMess`، `Trojan`، `Shadowsocks`، `SOCKS5` (`socks://` / `socks5://`)، `Hysteria2` و `TUIC`.
- **جریان کاری سه‌مرحله‌ای (`Configs -> Lab -> Home`):**
  1. **کانفیگ‌ها (مخزن):** مدیریت تب‌بندی‌شده کانفیگ‌ها و ساب‌ها مشابه `v2rayNG` با پینگ واقعی موازی و تست دسترسی **Gemini**.
  2. **آزمایشگاه (Lab):** تست دقیق تک‌کانفیگ یا دسته‌جمعی روی ۲۹ بردار عبوری همراه با **تست واقعی دانلود پیوسته (`160KB`) و سرعت واقعی آپلود (`KB/s` و `MB/s`)**، با تیک اختیاری تزریق آی‌پی تمیز (خاموش به‌صورت پیش‌فرض برای محافظت از کانفیگ‌های Railway و سرورهای مستقیم).
  3. **خانه (Home):** اتصال فوری، انیمیشن نئومورفیک پویا با حباب‌های سه‌حالته ترافیک (رنگ‌بندی طبق پرچم کشور مقصد)، باکس پرچم برجسته، نمودار سرعت زنده و پشتیبانی از System Tray ویندوز.
- **تفکیک حرفه‌ای برنامه‌ها (Per-App Split) و TUN ضد سیاه‌چاله:** تفکیک ترافیک برنامه‌های ویندوز در سطح کرنل (IPv4/IPv6 + HTTP & SOCKS5 + معافیت خودکار شبکه محلی و هماهنگی با حالت TUN با `MTU=1360`)، همگام‌سازی `WinHTTP` و لانچر اجرای مستقیم برنامه‌ها در تونل.
- **سپر رمزنگاری DNS (DoH Shield) و بررسی خودکار بروزرسانی:** صفحه اختصاصی **«درباره»** با بررسی خودکار آخرین ریلیز گیت‌هاب و دسترسی مستقیم به مخازن و کانال تلگرام.

> **نسخه اندروید:** برای استفاده روی موبایل، به ریپازیتوری رسمی اندروید در آدرس **[DrAlanK/Alan-RIP-Dpi-Android](https://github.com/DrAlanK/Alan-RIP-Dpi-Android)** مراجعه کنید.

---

## کانال تلگرام

برای دریافت آخرین نسخه‌ها، اطلاعیه‌ها، آموزش‌ها و کانفیگ‌ها، عضو کانال تلگرام شوید:

**[@LabALan](https://t.me/LabALan)** — https://t.me/LabALan

---

## معماری فنی و نحوه عملکرد موتور (Technical Architecture)

### ۱. نحوه قرارگیری Mutator و Per-App Gateway در کنار هسته `Xray-core`

در معماری `Alan-RIP-Dpi v1.5.0`، هسته استاندارد `xray.exe` وظیفه رمزنگاری پروتکل‌ها (`VLESS`, `VMess`, `Trojan`, `Shadowsocks`, `SOCKS5`, `Hysteria2`, `TUIC`)، مدیریت `Split-DNS`، قوانین `Routing` و کارت شبکه مجازی `Wintun` (`AlanTUN` با `MTU=1360`) را بر عهده دارد، اما مستقیماً به سرور راه دور متصل نمی‌شود.

```text
[ Windows Apps / Per-App Split Gateway (:10811) / AlanTUN (MTU 1360) ]
           │
           ▼  (SOCKS5 :10808 / HTTP :10809 / Wintun)
   [ Xray-Core Engine ]  ──(Custom Polymorphic uTLS + Routing + DoH Shield)
           │
           ▼  (Local Loopback 127.0.0.1:20809)
[ FullDuplexMutatorBridge ] ──(Byte-Level TLS/TCP Mutation: VEC-00..VEC-28)
           │
           ▼  (Physical NIC Direct Socket / TCP_MAXSEG=1220 / Loop-Free)
   [ Remote Edge / Server ]
```

خروجی Xray-core به FullDuplexMutatorBridge روی پورت محلی هدایت می‌شود. این پل دوطرفه نه تنها Flight 1 (TLS ClientHello) را در سطح بایت بازآرایی می‌کند، بلکه روی پروازهای ۲ تا ۶ (Application Data 0x17) و کل جریان آپلود نیز الگوریتم‌های کنترل پنجره ارسال (CWND Pacing)، کلمپینگ سگمنت و بافر نامتقارن اعمال می‌کند تا هم از DPI رفتاری عبور کند و هم جلوی قفل شدن آپلود و سیاه‌چاله‌های PMTU منطقه‌ای را بگیرد.

### ۲. خانواده بردارهای عبوری (VEC-00 تا VEC-28 — ۲۹ بردار تخصصی)

- **سپر سیاه‌چاله PMTU و ضد قفل ۱۶ کیلوبایتی منطقه‌ای (VEC-27 و VEC-28 — جدید در v1.5.0):**
  - **VEC-27 (Regional PMTU Guard - 1180B):** حل ریشه‌ای مشکل شبکه‌های استانی و دکل‌های موبایل (مانند برخی گیت‌وی‌های کرج/البرز و شهرستان‌ها) که در آن‌ها پینگ و لوکیشن ثابت است اما وب‌گردی قفل می‌شود؛ با برش استاندارد ۴رکوردی TLS 1.3 و قفل کردن سقف سگمنت‌های ارسالی زیر 1180B در کل نشست همراه با TCP_MAXSEG=1220.
  - **VEC-28 (Anti-16KB Flow-Stall):** تقطیع نامتقارن پروازهای ۱ تا ۶ (0x16 + 0x17) همراه با شکل‌دهی جریان روی سقف 920B برای عبور از فیلترهای خفه‌کننده جریان‌های بالای ۱۶ تا ۳۲ کیلوبایت.
- **بردارهای پرچمدار ضد قفل آپلود (VEC-24 تا VEC-26):**
  - **VEC-24 (Record-Boundary CWND Pacer):** تقطیع دقیق مرز رکورد روی نقاط دامنه (.) و اکستنشن KeyShare + الگوریتم Token-Bucket CWND Pacing روی ۴۸ کیلوبایت اول آپلود بدون استفاده از بایت OOB.
  - **VEC-25 (Multi-Flight Asymmetric Desync):** شکست امضای طول بسته‌های 0x17 در پروازهای ۱ تا ۴ + بافر نامتقارن سوکت (4MB RX / 96KB TX) برای حذف Bufferbloat و قفل آپلود.
  - **VEC-26 (Fast-Path Offload Bypass):** دور زدن تجمیع سخت‌افزاری TSO/LSO کارت شبکه ویندوز در هندشیک و ورود به حالت Bulk Relay پس از ۱۶ کیلوبایت اول.
- **بردارهای تزریق خارج از باند (MSG_OOB Structural Desync):** ارسال بایت‌های فریب با پرچم URG روی آفست‌های حساس (SNI Tag, Length, Mid-Host, CipherSuites Pivot) همراه با برش استراید پویا.
- **بردارهای پاکت‌بندی و برش هندسی رکورد (Record-Layer Framing & Slicing):** شکستن ClientHello به چند رکورد استاندارد 0x16 با نسخه‌های بیرونی متناوب و برش فیبوناچی در یک فراخوانی واحد کرنل.

### ۳. راستی‌آزمایی واقعی جریان (160KB Download + 192KB Real Upload)

برخلاف تسترهای ساده که فقط یک generate_204 کوچک ارسال می‌کنند و در مناطق دارای PMTU Blackhole دچار خطای مثبت کاذب می‌شوند، موتور verifier.py در نسخه v1.5.0 قبل از تایید نهایی هر متد، سه مرحله واقعی را می‌سنجد:

1. پینگ اولیه و تست استریم یوتیوب
2. تست دانلود پیوسته 160KB (Sustained Download Probe) برای شناسایی و رد فوری متدهایی که بعد از ۱۶ کیلوبایت فریز می‌شوند.
3. تست واقعی سرعت آپلود 192KB روی سرور دریافت واقعی (speed.cloudflare.com/__up با فال‌بک) و نمایش سرعت دقیق بر حسب KB/s و MB/s در ستون اختصاصی آزمایشگاه.

### ۴. منطق Origin-First، محافظت PaaS و کنترل اختیاری آی‌پی تمیز

- در آزمایشگاه (Lab)، تزریق خودکار آی‌پی تمیز به‌صورت پیش‌فرض خاموش است تا کانفیگ‌های Railway، Render، Fly.io، SOCKS5 و سرورهای مستقیم دست‌نخورده تست شوند؛ کاربران در صورت نیاز به اسکن کلودفلر می‌توانند تیک «تزریق خودکار IP تمیز (هنگام اسکن)» را فعال کنند.
- فینگرپرینت چندریختی Custom Polymorphic uTLS به‌صورت پیش‌فرض امضای کلاینت، ترتیب اکستنشن‌ها و مقادیر GREASE را در هر اتصال تغییر می‌دهد.

### ۵. موتور Per-App Split Tunneling (سطح کرنل ویندوز)

- شناسایی لحظه‌ای پردازش مالک هر اتصال TCP روی IPv4 و IPv6 از طریق iphlpapi.dll (GetExtendedTcpTable) همراه با کش درخت پردازش (تا ۸ لایه والد/فرزند).
- پشتیبانی کامل از HTTP/HTTPS و SOCKS5 در هر دو حالت تونل و عبور مستقیم (Bypass)، معافیت خودکار آی‌پی‌های شبکه محلی (LAN / Private CIDR)، مقیدسازی سوکت‌های معاف به کارت شبکه فیزیکی در حالت TUN، و شمارنده زنده اتصالات تفکیک‌شده.

### ۶. ساختار پروژه

```plaintext
Alan-RIP-Dpi/
├── main.py                      # نقطه ورود، مدیریت فونت‌ها و همگام‌ساز ترد اصلی Qt
├── build_release.ps1            # اسکریپت ساخت نسخه پرتابل ویندوز (PyInstaller)
├── core/                        # باینری‌های هسته (xray.exe, wintun.dll, geoip/geosite)
├── assets/                      # آیکون‌ها و فونت‌های باندل‌شده (Vazirmatn / JetBrainsMono)
└── alan_dpi/
    ├── engine/
    │   ├── models.py            # مدل‌های داده، رجیستری ۲۹ بردار (VEC-00..28) و LocationExtractor
    │   ├── mutator.py           # پارسر بایتی ClientHello، برش چندپروازه 0x17 و NIC Offload Bypass
    │   ├── bridge.py            # پراکسی Full-Duplex با بافر نامتقارن، CWND Pacing و PMTU Guard
    │   ├── xray_driver.py       # کامپایلر Xray (V2Ray + SOCKS5)، قوانین Routing و پینگ موازی
    │   ├── clean_ip.py          # رادار CIDR کلودفلر با تستر MemoryBIO و فیلتر محافظ PaaS
    │   ├── verifier.py          # تستر دانلود پیوسته 160KB، سرعت واقعی آپلود 192KB و Gemini
    │   ├── per_app_proxy.py     # گیت‌وی تفکیک برنامه‌ها (IPv4/IPv6 PID Mapper + HTTP/SOCKS5 + WinHTTP)
    │   ├── doh_shield.py        # سپر رمزنگاری DNS (DNS-over-HTTPS)
    │   ├── tun_manager.py       # مدیریت کارت مجازی Wintun (MTU 1360)، جدول Route و ارتقای UAC
    │   ├── updater.py           # سرویس بررسی خودکار آخرین ریلیز از GitHub API
    │   ├── autopilot.py         # ماشین حالت اتصال خودکار، شکارچی ساب و نگهبان خودترمیم‌گر
    │   └── qt_adapter.py        # پل ارتباطی سیگنال‌ها و صف Thread-Safe رابط گرافیکی
    └── ui/                      # رابط نئومورفیک دوزبانه (Home, Configs, Lab, Settings, Logs, About)
```

## منابع و پروژه‌های استفاده‌شده (Credits & Third-Party)

این پروژه بر پایه‌ی کارهای متن‌باز زیر ساخته شده است و از همه‌ی توسعه‌دهندگانشان سپاسگزاریم:

- [Xray-core](https://github.com/XTLS/Xray-core) — هسته‌ی اصلی مسیریابی و پروتکل‌ها (VLESS, VMess, Trojan, Shadowsocks, SOCKS5, Hysteria2, TUIC) تحت لایسنس MPL-2.0.
- [Wintun](https://www.wintun.net/) — درایور کارت شبکه‌ی مجازی لایه ۳ برای حالت TUN (ساخته‌ی تیم WireGuard).
- [Qt for Python (PySide6)](https://www.qt.io/qt-for-python) — چارچوب رابط گرافیکی.
- [PyInstaller](https://pyinstaller.org/) — ساخت نسخه‌ی Portable.
- [Vazirmatn](https://github.com/rastikerdar/vazirmatn) و [JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) — فونت‌های باندل‌شده (لایسنس OFL).
- Geoip / Geosite — دیتابیس‌های مسیریابی جغرافیایی همراه هسته‌ی Xray.

هر کدام از این پروژه‌ها تحت لایسنس خودشان هستند و لایسنس Alan-RIP-Dpi روی آن‌ها اعمال نمی‌شود.

## قدردانی (Acknowledgments)

تشکر و قدردانی ویژه از [Floxu1](https://github.com/Floxu1/) بابت ابداع متد OOB (Out-of-Band) و کمک‌های فنی ارزشمند ایشان در روند طراحی و تکامل متدهای عبوری این پروژه.

## لایسنس (License)

این پروژه تحت لایسنس MIT منتشر شده است. متن کامل لایسنس در فایل [LICENSE](https://www.google.com/search?q=LICENSE) موجود است.

استفاده، کپی، تغییر و توزیع آزاد است، به شرطی که اعلان کپی‌رایت و متن لایسنس حفظ شود. نرم‌افزار «همان‌طور که هست» و بدون هیچ‌گونه ضمانتی ارائه می‌شود.
