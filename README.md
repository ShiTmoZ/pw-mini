# Pwnagotchi for PC (Linux x86_64 / Kali)

A standalone wrapper, hardware auditor, and automated patchset for running **Jayofelony Pwnagotchi** natively on standard Linux PCs (Kali, Debian, Ubuntu x86_64) with **zero Raspberry Pi hardware dependencies**.

---

## 🇮🇷 راهنمای فارسی (مستندات کامل)

### ۱. پیش‌نیازها
* **سیستم‌عامل:** لینوکس ۶۴ بیتی مبتنی بر دبیان (تست‌شده روی Kali Linux Live و Debian 12 / Ubuntu x86_64).
* **کارت شبکه وای‌فای:** هر کارت شبکه‌ای که از حالت Monitor Mode در لینوکس پشتیبانی کند (شامل کارت‌های آنبرد اینتل `iwlwifi` و ریل‌تک `rtw89`/`rtw88` و دانگل‌های اکسترنال).
* **پکیج‌های سیستمی مورد نیاز:**
  ```text
  git, bettercap, libpcap-dev, python3-pip, python3-prctl, python3-pycryptodome,
  python3-flask-cors, iw, aircrack-ng, python3-dbus, python3-pil, fonts-dejavu,
  openssh-client, net-tools
  ```

---

### ۲. نحوه نصب سریع و خودکار (دستور یک‌خطی)

ترمینال کالی لینوکس را باز کرده و دستور یک‌خطی زیر را اجرا کنید:

```bash
sudo rm -rf /opt/pwnagotchi-pc /etc/pwnagotchi ~/pw-mini && git clone https://github.com/ShiTmoZ/pw-mini.git ~/pw-mini && cd ~/pw-mini && sudo bash setup.sh && sudo ./start.sh
```

این دستور به صورت کاملاً خودکار:
1. پکیج‌های پایه و سیستمی مورد نیاز را از مخازن کالی نصب می‌کند.
2. سورس رسمی پوناگوچی را دانلود و تمام پچ‌های سازگاری PC (شامل رفع خطاهای Pillow 10+، نام‌گذاری پکیج‌های پایتون و حذف وابستگی‌های رزبری‌پای) را اعمال می‌کند.
3. کلیدهای هویت RSA و استاب pwngrid را ایجاد کرده و برنامه را آماده اجرا می‌سازد.

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
  * اگر کارت شبکه از ارسال پکت (Packet Injection / Deauth) پشتیبانی نکند (مثل بیشتر چیپست‌های آنبرد لپ‌تاپ و مادربرد نظیر Realtek `rtw89` یا Intel `iwlwifi`)، برنامه متوقف نمی‌شود؛ بلکه به صورت خودکار حالت **۱۰۰٪ پسیو (Passive Sniffer)** را فعال می‌کند (`deauth = false` و `associate = false`). در این حالت، ابزار هیچ پکت اضافه‌ای ارسال نمی‌کند و بدون کرش، صرفاً هندشیک‌ها و PMKIDهای حاصل از اتصال مجدد طبیعی دستگاه‌ها در محیط را به آرامی و بدون سر‌وصدا شکار می‌کند.
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

### ۶. حل مشکل تحریم و خطای ۴۰۳ (تنظیم سریع‌ترین میرور برای ایران)

مخزن پیش‌فرض کالی (`kali.download`) پشت کلودفلر قرار دارد و برای کاربران داخل ایران ارور `403 Forbidden` برمی‌گرداند. برای تعویض مستقیم به سرور دانشگاهی پرسرعت و پایدار در ایران، کافیست این دستور تک‌خطی را در ترمینال بزنید:

```bash
echo "deb http://ftp.halifax.rwth-aachen.de/kali kali-rolling main contrib non-free non-free-firmware" | sudo tee /etc/apt/sources.list && sudo apt update
```

---

### ۷. بازیابی دستی کارت شبکه و اتصال مجدد اینترنت

اسکریپت `start.sh` با فشردن کلیدهای `Ctrl + C` به صورت خودکار کارت شبکه را به وضعیت عادی بازمی‌گرداند. اما اگر به هر دلیلی (کرش، بستن ناگهانی ترمینال یا قطعی برق) اینترنت سیستم قطع ماند، با اجرای دستور یک‌خطی زیر در ترمینال کالی، مانیتور مود فوراً متوقف شده، کارت شبکه ریست شده و اینترنت متصل می‌شود:

```bash
sudo ip link set wlan0mon down 2>/dev/null; sudo iw dev wlan0mon del 2>/dev/null; sudo nmcli device set wlan0 managed yes 2>/dev/null; sudo rfkill unblock wifi; sudo systemctl restart NetworkManager
```
*(در صورت تفاوت نام اینترفیس، به جای `wlan0` نام کارت شبکه خود را وارد کنید).*

---

### ۸. عیب‌یابی و نکات تکمیلی (Troubleshooting)

* **خطای متد فونت در Pillow 10+ (`FreeTypeFont has no attribute getsize`):**  
  در نسخه‌های جدید کالی لینوکس، کتابخانه Pillow متد `getsize` را حذف کرده است. اسکریپت `start.sh` به صورت خودکار این متد را برای رابط وب شبیه‌سازی (Monkey-patch) می‌کند.
* **خطای ساخت کلیدهای هویت (`KeyPair has no attribute fingerprint`):**  
  پوناگوچی برای امضای بسته به یک جفت‌کلید RSA نیاز دارد که در رزبری‌پای توسط باینری `pwngrid` ساخته می‌شد. روی PC این باینری وجود ندارد؛ اسکریپت `start.sh` به صورت خودکار یک ماک اجرایی با OpenSSL ایجاد می‌کند تا کلیدها تولید و اعتبارسنجی شوند. در صورت نیاز به تولید دستی:
  ```bash
  sudo openssl genrsa -out /etc/pwnagotchi/id_rsa 2048 && sudo openssl rsa -in /etc/pwnagotchi/id_rsa -pubout -out /etc/pwnagotchi/id_rsa.pub && sudo chmod 600 /etc/pwnagotchi/id_rsa
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
sudo apt update && sudo apt install -y git bettercap libpcap-dev python3-pip python3-prctl python3-pycryptodome python3-flask-cors iw aircrack-ng python3-dbus python3-pil fonts-dejavu openssh-client net-tools && sudo rm -rf pw-mini && git clone https://github.com/ShiTmoZ/pw-mini.git && cd pw-mini && sudo bash setup.sh
```

### Run
```bash
sudo ./start.sh
```
Access dashboard at `http://localhost:8080` (user/pass: `admin`/`admin`). Handshakes saved to `/root/handshakes/`.

### Manual Network & Wi-Fi Restoration
If an ungraceful shutdown occurs, restore full Wi-Fi and internet connectivity with:
```bash
sudo ip link set wlan0mon down 2>/dev/null; sudo iw dev wlan0mon del 2>/dev/null; sudo nmcli device set wlan0 managed yes 2>/dev/null; sudo rfkill unblock wifi; sudo systemctl restart NetworkManager
```
