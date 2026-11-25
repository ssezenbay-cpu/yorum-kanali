#!/usr/bin/env bash
# Sunucuda çalışır: gerekli paketleri kurar, botu kalıcı servis olarak (yeniden) başlatır.
# sunucuya_gonder.bat tarafından otomatik çağrılır; elle çalıştırmana gerek yok.
set -euo pipefail
KLASOR=/opt/yorum-kanali
KULLANICI=yorumbot
cd "$KLASOR"

# Ayarlar: sunucudaki .env esastır (Telegram'dan değiştirilenler korunur).
# Bilgisayardan gelen .env sadece boş/eksik ayarları tamamlar; TELEGRAM_TOKEN ise her zaman güncellenir.
if [ -f .env.bilgisayar ]; then
  sed -i '1s/^\xEF\xBB\xBF//; s/\r$//' .env.bilgisayar
  if [ ! -f .env ]; then
    mv .env.bilgisayar .env
  else
    python3 - <<'PY'
from pathlib import Path

def anahtar(satir):
    if "=" not in satir or satir.lstrip().startswith("#"):
        return None
    return satir.split("=", 1)[0].strip()

gelen = {}
for satir in Path(".env.bilgisayar").read_text(encoding="utf-8").splitlines():
    if anahtar(satir):
        gelen[anahtar(satir)] = satir.split("=", 1)[1].strip()
satirlar = Path(".env").read_text(encoding="utf-8").splitlines()
gorulen = set()
for i, satir in enumerate(satirlar):
    k = anahtar(satir)
    if not k:
        continue
    gorulen.add(k)
    mevcut = satir.split("=", 1)[1].strip()
    yeni = gelen.get(k, "")
    if yeni and (not mevcut or k == "TELEGRAM_TOKEN"):
        satirlar[i] = f"{k}={yeni}"
satirlar += [f"{k}={v}" for k, v in gelen.items() if v and k not in gorulen]
Path(".env").write_text("\n".join(satirlar) + "\n", encoding="utf-8")
PY
    rm -f .env.bilgisayar
  fi
fi
if [ ! -f .env ]; then
  echo "HATA: Sunucuda .env dosyası yok."
  exit 1
fi

if ! dpkg -s ffmpeg python3-venv fonts-dejavu-core >/dev/null 2>&1; then
  echo "Gerekli paketler kuruluyor (sadece ilk seferde, birkaç dakika sürer)..."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq ffmpeg python3-venv fonts-dejavu-core >/dev/null
fi

id "$KULLANICI" >/dev/null 2>&1 || \
  useradd --system --home-dir "$KLASOR" --shell /usr/sbin/nologin "$KULLANICI"

if [ ! -x .venv/bin/python ]; then
  echo "Python ortamı hazırlanıyor..."
  python3 -m venv .venv
fi
echo "Python paketleri kontrol ediliyor..."
.venv/bin/pip install -q --disable-pip-version-check -r requirements.txt

mkdir -p calisma videolar
chown -R "$KULLANICI":"$KULLANICI" "$KLASOR"
chmod 600 .env

cat > /etc/systemd/system/yorum-kanali.service <<EOF
[Unit]
Description=Yorum kanali Telegram botu
After=network-online.target
Wants=network-online.target

[Service]
User=$KULLANICI
WorkingDirectory=$KLASOR
ExecStart=$KLASOR/.venv/bin/python -u bot.py
Restart=always
RestartSec=15
Nice=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --quiet yorum-kanali
systemctl restart yorum-kanali
echo "Bot başlatıldı, kontrol ediliyor..."
sleep 12
echo "---------------- bot kaydı ----------------"
journalctl -u yorum-kanali -n 12 --no-pager -o cat || true
echo "-------------------------------------------"
KAYIT=$(journalctl -u yorum-kanali -n 30 --no-pager -o cat || true)
if systemctl is-active --quiet yorum-kanali && [[ "$KAYIT" == *"Bot çalışıyor"* ]]; then
  echo "TAMAM: Bot sunucuda çalışıyor. Telegram'da /start yazabilirsin."
else
  echo "SORUN: Bot çalışmıyor. Bu pencerenin ekran görüntüsünü gönder."
fi
