# Pwnagotchi for PC (Linux x86_64 / Kali)

A standalone wrapper, hardware auditor, and automated patchset for running **Jayofelony Pwnagotchi** natively on standard Linux PCs (Kali, Debian, Ubuntu x86_64) with **zero Raspberry Pi hardware dependencies**.

---

## 🇮🇷 راهنمای فارسی (مستندات کامل)

### ۱. پیش‌نیازها
* **سیستم‌عامل:** لینوکس ۶۴ بیتی مبتنی بر دبیان (تست‌شده روی Kali Linux Live و Debian 12 / Ubuntu x86_64).
* **کارت شبکه وای‌فای:** هر کارت شبکه‌ای که از حالت Monitor Mode در لینوکس پشتیبانی کند (شامل کارت‌های آنبرد اینتل `iwlwifi` و ریل‌تک `rtw89`/`rtw88` و دانگل‌های اکسترنال).
* **پکیج‌های سیستمی مورد نیاز:**
  ```text
  git, bettercap, libpcap-dev, python3-pip, python3-prctl, iw, aircrack-ng,
  python3-dbus, python3-pil, fonts-dejavu, openssh-client, net-tools
  ```

---

### ۲. نحوه نصب سریع و خودکار (دستور یک‌خطی)

ترمینال کالی لینوکس را باز کرده و دستور زیر را به صورت کامل کپی و اجرا کنید:

```bash
sudo apt update && sudo apt install -y git bettercap libpcap-dev python3-pip python3-prctl iw aircrack-ng python3-dbus python3-pil fonts-dejavu openssh-client net-tools && sudo rm -rf pw-mini && git clone https://github.com/ShiTmoZ/pw-mini.git && cd pw-mini && sudo bash setup.sh
```

این دستور به صورت خودکار:
1. پکیج‌های پایه و درایورهای مورد نیاز را نصب می‌کند.
2. سورس اصلی پوناگوچی را دانلود و پچ‌های لینوکس PC را روی آن اعمال می‌کند (حذف پیش‌نیازهای اختصاصی سخت‌افزار رزبری‌پای مانند پین‌های GPIO، نمایشگر اینکی و سنسورهای باتری).
3. کلیدهای رمزنگاری RSA را ساخته و کانفیگ سازگار با کامپیوتر را ایجاد می‌کند.

---

### ۳. نحوه اجرا

برای راه‌اندازی، داخل فولدر `pw-mini` دستور زیر را بزنید:

```bash
sudo ./start.sh
```

#### پارامترهای اختیاری:
* انتخاب کارت شبکه مشخص (در صورت داشتن چند کارت):
  ```bash
  sudo PWN_IFACE=wlan1 ./start.sh
  ```
* اجرای تست عمیق اینجکشن سخت‌افزاری (`aireplay-ng`):
  ```bash
  sudo PWN_DEEP_SCAN=1 ./start.sh
  ```

---

### ۴. نحوه کارکرد (مکانیسم هوشمند)

* **عیب‌یابی خودکار سخت‌افزار (`doctor.py`):**  
  اسکریپت قبل از شروع، چیپست کارت شبکه را بررسی می‌کند.  
  * اگر کارت شبکه از ارسال پکت (Packet Injection / Deauth) پشتیبانی نکند (مثل بیشتر چیپست‌های آنبرد لپ‌تاپ و مادربرد)، برنامه متوقف نمی‌شود؛ بلکه به صورت خودکار حالت **۱۰۰٪ پسیو (Passive Sniffer)** را فعال می‌کند (`deauth = false` و `associate = false`). در این حالت، ابزار هیچ پکت اضافه‌ای ارسال نمی‌کند و بدون کرش، صرفاً هندشیک‌ها و PMKIDهای حاصل از اتصال مجدد طبیعی دستگاه‌ها در محیط را به آرامی و بدون سر‌وصدا شکار می‌کند.
  * اگر کارت شبکه شما اینجکشن داشته باشد، حالت فعال (Active) روشن می‌شود.
* **شبیه‌ساز سرور گرید داخلی (Pwngrid Mock):**  
  یک وب‌سرویس پایتونی سبک روی پورت داخلی `127.0.0.1:8666` اجرا می‌شود تا بدون نیاز به کامپایل ابزارهای سنگین Go، چرخه تبادل دیتای پوناگوچی را تغذیه کند.
* **مهار باگ ریبوت خودکار PC:**  
  نام ابزار به طور خودکار با نام هاست سیستم هماهنگ می‌شود تا لاجیک ریبوت رزبری‌پای روی ویندوز/لینوکس خنثی شود.
* **بازیابی تمیز کارت شبکه (Graceful Exit):**  
  با فشردن کلیدهای `Ctrl + C` در هر لحظه، کلیه پروسه‌ها بسته شده، اینترفیس مانیتور حذف و کنترل کارت شبکه بدون نیاز به ریستارت به NetworkManager بازگردانده می‌شود.

---

### ۵. خروجی و رابط کاربری (Web UI)

پس از اجرای `start.sh`، مرورگر سیستم را باز کرده و به آدرس زیر بروید:
* **آدرس:** `http://localhost:8080`
* **نام کاربری پیش‌فرض:** `admin`
* **رمز عبور پیش‌فرض:** `admin`

**چه چیزهایی مشاهده می‌کنید؟**
* چهره نمادین پوناگوچی (`(◕‿◕)`) با نمایش لحظه‌ای حالات و رفتارها.
* وضعیت کانال‌های تحت نظر و تعداد مودم‌های شناسایی‌شده (APs).
* تعداد هندشیک‌های شکار شده.
* تمامی هندشیک‌های ضبط‌شده با فرمت استاندارد در مسیر زیر ذخیره می‌شوند:
  ```text
  /root/handshakes/
  ```

---

## 🇬🇧 English Documentation

### Features
- **Zero Pi Dependencies**: Bypasses all Raspberry Pi-exclusive hardware wheels (`gpiozero`, `inky`, `rpi-lgpio`, `rpi_hardware_pwm`, `smbus`, `pisugar`).
- **Hardware Doctor (`doctor.py`)**: Auto-detects Wi-Fi chipsets and monitor mode; seamlessly falls back to **100% Passive Sniffer** mode (`personality.deauth = false`, `associate = false`) on hardware lacking raw frame injection (e.g. Realtek `rtw89`/`rtw88`, Intel `iwlwifi`).
- **Embedded Pwngrid Mock**: Replaces external Go binary with built-in mock HTTP service on `127.0.0.1:8666`.
- **Anti-Reboot Safeguard**: Pins `main.name` to host hostname, neutralizing reboot bugs on generic PCs.
- **Clean Network Lifecycle**: Graceful shutdown and network restoration on `Ctrl+C`.

### Quick Install (Debian / Kali Linux Live)
```bash
sudo apt update && sudo apt install -y git bettercap libpcap-dev python3-pip python3-prctl iw aircrack-ng python3-dbus python3-pil fonts-dejavu openssh-client net-tools && sudo rm -rf pw-mini && git clone https://github.com/ShiTmoZ/pw-mini.git && cd pw-mini && sudo bash setup.sh
```

### Run
```bash
sudo ./start.sh
```
Access dashboard at `http://localhost:8080` (user/pass: `admin`/`admin`). Handshakes saved to `/root/handshakes/`.
