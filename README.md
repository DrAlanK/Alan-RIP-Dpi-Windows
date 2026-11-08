<div align="center">
  <img src="assets/logo.png" alt="Alan-RIP-Dpi Logo" width="110" />
  <h1>Alan-RIP-Dpi (Windows Desktop) — v1.2.0</h1>
  <p><b>Adaptive Anti-DPI Engine, Full-Duplex Byte Mutator & Xray Routing Client for Windows</b></p>
  <p>
    <a href="https://github.com/DrAlanK/Alan-RIP-Dpi-Windows/releases/latest">Download Latest Release (v1.2.0)</a>
    ·
    <a href="https://github.com/DrAlanK/Alan-RIP-Dpi-Android">Android Version (Alan-RIP-Dpi-Android)</a>
    ·
    <a href="https://t.me/LabALan">Telegram Channel (@LabALan)</a>
  </p>
</div>

---

## معرفی اجمالی و تجربه کاربری (غیرفنی)

**Alan-RIP-Dpi** ابزاری دسکتاپ برای ویندوز است که پیچیدگی‌های فنی دور زدن فیلترینگ (DPI)، پیدا کردن آی‌پی تمیز، تنظیم فرگمنت و تست صدها کانفیگ را به یک دکمه واحد تبدیل می‌کند:

* **اتصال خودکار هوشمند با انتخابگر لوکیشن:** بدون نیاز به داشتن کانفیگ شخصی، برنامه به مخزن ابری متصل شده و امکان انتخاب کشور مقصد (آلمان، هلند، فنلاند، آمریکا و...) را فراهم می‌کند.
* **شکارچی کامل لینک سابسکریپشن (Sub Hunter):** کافی است یک لینک اشتراک بدهید تا برنامه تمام کانفیگ‌های داخل آن را به‌صورت موازی پینگ و تست استریم کرده و خودکار به پایدارترین سرور (رتبه ۱) وصل شود.
* **جریان کاری سه‌مرحله‌ای (`Configs -> Lab -> Home`):**
  1. **کانفیگ‌ها (مخزن):** مدیریت تب‌بندی‌شده کانفیگ‌ها و ساب‌ها مشابه `v2rayNG` با پینگ واقعی همگانی و تست دسترسی **Gemini AI**.
  2. **آزمایشگاه (Lab):** تست تک‌کانفیگ یا دسته‌جمعی روی تمام متدهای عبوری و انتقال خودکار خروجی‌های سالم (`VERIFIED`) به صفحه خانه.
  3. **خانه (Home):** اتصال فوری، نمایش زنده آی‌پی و پرچم کشور خروجی، نمودار سرعت و پشتیبانی از System Tray ویندوز.
* **حالت TUN یک‌کلیکی:** تونل کردن کل ترافیک ویندوز با دریافت خودکار دسترسی Administrator و نصب خودکار درایور `Wintun`.

> **نسخه اندروید:** برای استفاده روی موبایل، به ریپازیتوری رسمی اندروید در آدرس **[DrAlanK/Alan-RIP-Dpi-Android](https://github.com/DrAlanK/Alan-RIP-Dpi-Android)** مراجعه کنید.

---

## کانال تلگرام

برای دریافت آخرین نسخه‌ها، اطلاعیه‌ها، آموزش‌ها و کانفیگ‌ها، عضو کانال تلگرام شوید:

**[@LabALan](https://t.me/LabALan)** — https://t.me/LabALan

---

## معماری فنی و نحوه عملکرد موتور (Technical Architecture)

### ۱. نحوه قرارگیری Mutator در کنار هسته `Xray-core`
در معماری `Alan-RIP-Dpi`، هسته استاندارد `xray.exe` وظیفه رمزنگاری پروتکل‌ها (`VLESS`, `VMess`, `Trojan`, `Shadowsocks`)، مدیریت `Split-DNS`، قوانین `Routing` و کارت شبکه مجازی `Wintun` (`AlanTUN`) را بر عهده دارد، اما مستقیماً به سرور راه دور متصل نمی‌شود.

~~~text
[ Windows Apps / AlanTUN ]
           │
           ▼  (SOCKS5 :10808 / HTTP :10809 / Wintun)
   [ Xray-Core Engine ]  ──(Custom Polymorphic uTLS + Routing/DNS)
           │
           ▼  (Local Loopback 127.0.0.1:20809)
[ FullDuplexMutatorBridge ] ──(Byte-Level TLS/TCP Mutation: VEC-00..VEC-23)
           │
           ▼  (Physical NIC Direct Socket / Loop-Free)
   [ Remote Edge / Server ]
~~~

خروجی `Xray-core` به `FullDuplexMutatorBridge` روی پورت محلی هدایت می‌شود. این پل دوطرفه اولین پرواز (`Flight 1` حاوی `TLS ClientHello` یا درخواست `HTTP Upgrade`) و پرواز دوم (`Flight 2` حاوی فریم‌های `Application Data 0x17` و `WebSocket EarlyData ?ed=2048`) را در سطح سوکت خام رهگیری کرده و بدون خراب کردن `Transcript-Hash` رمزنگاری TLS 1.3، تغییرات سطح بایت را اعمال می‌کند.

### ۲. خانواده بردارهای عبوری (`VEC-00` تا `VEC-23`)

* **بردارهای تزریق خارج از باند (`MSG_OOB` Structural Desync):** ارسال بایت‌های فریب تصادفی با پرچم `URG` در لایه TCP روی آفست‌های حساس (`SNI Extension Tag`, `Length Field`, `Mid-Host`, `CipherSuites Pivot`) همراه با برش استراید با پنجره متغیر (`400B` / `360B`). پشته شبکه لینوکس سرور مقصد بایت `OOB` را دور می‌ریزد، اما ماشین حالت DPI در بازسازی توالی بایت‌ها دچار خطا می‌شود.
* **بردارهای پاکت‌بندی و برش هندسی رکورد (`Record-Layer Framing & Slicing`):** شکستن بدنه `ClientHello` به چند رکورد معتبر `0x16` با نسخه‌های بیرونی متناوب (`0x0301`, `0x0303`, `0x0304`)، جداسازی مرز کاراکتر نقطه (`.`) در نام دامنه و برش پلکانی فیبوناچی (`[1, 2, 3, 5, 8]`) روی بافر `SNI` در یک فراخوانی واحد کرنل بدون تاخیر زمانی.
* **بردارهای ترکیبی و سپر آپلود (`Hybrid & Uplink Shield`):** ترکیب رکورد فانتوم بدون SNI با جابه‌جایی مرز هدر، و کلمپینگ اندازه سگمنت‌های ۱۶ کیلوبایت اول آپلود (`MSS Clamping`) برای جلوگیری از قفل شدن پنجره ارسال TCP در استریم‌های WebSocket.

### ۳. منطق `Origin-First` و محافظت از کانفیگ‌های PaaS

موتور پیش از هرگونه تزریق آی‌پی، ابتدا هاست اصلی کانفیگ (`original_host`) را با حلول `DoH` ضد مسمومیت تست می‌کند. دامنه‌ها و `CNAME`های سرویس‌های PaaS (مانند `Railway`, `Render`, `Fly.io`, `Vercel`, `Koyeb`) به‌طور خودکار شناسایی و از دریافت آی‌پی کلودفلر معاف می‌شوند. اسکنر موازی آی‌پی تمیز (مجهز به تستر `ssl.MemoryBIO` روی `/cdn-cgi/trace`) صرفاً به عنوان **Fallback** زمانی وارد عمل می‌شود که هاست اصلی مسدود بوده و واجد شرایط CDN کلودفلر باشد.

### ۴. فینگرپرینت چندریختی (`Custom Polymorphic uTLS`)

برای جلوگیری از مسدودسازی بر اساس امضای ثابت مرورگرها (`JA3`/`JA4` کروم یا فایرفاکس)، پروفایل پیش‌فرض `custom_poly` در هر نشست امضای کلاینت، ترتیب اکستنشن‌ها، مقادیر `GREASE` و بایت‌های فریب سطح سیم را به‌صورت پویا تغییر می‌دهد و هم‌زمان روی کانفیگ‌های WebSocket مقدار `ALPN` را روی `http/1.1` قفل می‌کند.

### ۵. ساختار پروژه

~~~text
Alan-RIP-Dpi/
├── main.py                      # نقطه ورود، مدیریت فونت‌ها و همگام‌ساز ترد اصلی Qt
├── build_release.ps1            # اسکریپت ساخت نسخه پرتابل ویندوز (PyInstaller)
├── core/                        # باینری‌های هسته (xray.exe, wintun.dll, geoip/geosite)
├── assets/                      # آیکون‌ها و فونت‌های باندل‌شده (Vazirmatn / JetBrainsMono)
└── alan_dpi/
    ├── engine/
    │   ├── models.py            # مدل‌های داده، رجیستری ۲۴ بردار و LocationExtractor
    │   ├── mutator.py           # پارسر بایتی ClientHello و موتور دستکاری پکت‌های TLS/HTTP
    │   ├── bridge.py            # پراکسی محلی Full-Duplex با بافر 4MB و مقیدسازی ضد حلقه TUN
    │   ├── xray_driver.py       # کامپایلر کانفیگ Xray، قوانین Routing و موتور پینگ موازی
    │   ├── clean_ip.py          # رادار CIDR کلودفلر با تستر MemoryBIO و فیلتر محافظ PaaS
    │   ├── verifier.py          # راستی‌آزمایی استریم ۶ ثانیه‌ای، تست آپلود و تشخیص دیتاسنتر 
    │   ├── tun_manager.py       # مدیریت کارت مجازی Wintun، جدول Route و ارتقای UAC
    │   ├── autopilot.py         # ماشین حالت اتصال خودکار، شکارچی ساب و نگهبان خودترمیم‌گر
    │   └── qt_adapter.py        # پل ارتباطی سیگنال‌ها و صف Thread-Safe رابط گرافیکی
    └── ui/                      # صفحات رابط کاربری دوزبانه (Home, Configs, Lab, Routing, Logs)
~~~

---

## منابع و پروژه‌های استفاده‌شده (Credits & Third-Party)

این پروژه بر پایه‌ی کارهای متن‌باز زیر ساخته شده است و از همه‌ی توسعه‌دهندگانشان سپاسگزاریم:

* **[Xray-core](https://github.com/XTLS/Xray-core)** — هسته‌ی اصلی مسیریابی و پروتکل‌ها (`VLESS`, `VMess`, `Trojan`, `Shadowsocks`). این پروژه از باینری رسمی `xray.exe` استفاده می‌کند و تحت لایسنس **MPL-2.0** منتشر شده است.
* **[Wintun](https://www.wintun.net/)** — درایور کارت شبکه‌ی مجازی لایه ۳ برای حالت TUN (ساخته‌ی تیم WireGuard).
* **[Qt for Python (PySide / PyQt)](https://www.qt.io/qt-for-python)** — چارچوب رابط گرافیکی.
* **[PyInstaller](https://pyinstaller.org/)** — ساخت نسخه‌ی Portable.
* **[Vazirmatn](https://github.com/rastikerdar/vazirmatn)** و **[JetBrains Mono](https://github.com/JetBrains/JetBrainsMono)** — فونت‌های باندل‌شده (لایسنس OFL).
* **Geoip / Geosite** — دیتابیس‌های مسیریابی جغرافیایی همراه هسته‌ی Xray.

هر کدام از این پروژه‌ها تحت لایسنس خودشان هستند و لایسنس Alan-RIP-Dpi روی آن‌ها اعمال نمی‌شود.

---

## قدردانی (Acknowledgments)

* تشکر و قدردانی ویژه از **[Floxu1](https://github.com/Floxu1/)** بابت ابداع متد **OOB (Out-of-Band)** و کمک‌های فنی ارزشمند ایشان در روند طراحی و تکامل متدهای عبوری این پروژه.

---

## لایسنس (License)

این پروژه تحت لایسنس **MIT** منتشر شده است. متن کامل لایسنس در فایل [LICENSE](LICENSE) موجود است.

استفاده، کپی، تغییر و توزیع آزاد است، به شرطی که اعلان کپی‌رایت و متن لایسنس حفظ شود. نرم‌افزار «همان‌طور که هست» و بدون هیچ‌گونه ضمانتی ارائه می‌شود.

---

<div align="center">
  <p>ساخته‌شده با ❤️ توسط <a href="https://github.com/DrAlanK">DrAlanK</a> · <a href="https://t.me/LabALan">@LabALan</a></p>
</div>