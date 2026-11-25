"""Botu Hetzner sunucusuna kopyalar ve kurar. Bilgisayarda ssh programı gerekmez.

Kullanım:  python sunucuya_gonder.py          -> dosyaları gönderir, botu (yeniden) başlatır
           python sunucuya_gonder.py kayit    -> botun son kayıtlarını gösterir
"""
import getpass
import io
import os
import socket
import sys
import tarfile
from pathlib import Path

import paramiko

SUNUCU = os.getenv("SUNUCU_ADRESI", "fintrack-samet.duckdns.org")
PORT = int(os.getenv("SUNUCU_PORT", "22"))
KULLANICI = os.getenv("SUNUCU_KULLANICI", "root")
KOK = Path(__file__).resolve().parent
PARMAK_IZI = KOK / "sunucu_parmakizi.txt"
DOSYALAR = ["ayarlar.py", "analiz.py", "ses.py", "video.py", "bot.py", "demo.py",
            "requirements.txt", "sunucu_kurulum.sh", ".env"]
# Bilgisayardaki .env sunucudakinin üstüne yazılmaz; sunucu sadece eksiklerini buradan tamamlar.
ARSIV_ADI = {".env": ".env.bilgisayar"}
UZAK_ARSIV = "/tmp/yorum-kanali.tgz"
KURULUM_KOMUTU = (
    f"mkdir -p /opt/yorum-kanali && tar -xzf {UZAK_ARSIV} -C /opt/yorum-kanali && "
    f"rm -f {UZAK_ARSIV} && sed -i 's/\\r$//' /opt/yorum-kanali/sunucu_kurulum.sh && "
    "bash /opt/yorum-kanali/sunucu_kurulum.sh"
)
KAYIT_KOMUTU = ("systemctl is-active yorum-kanali; "
                "journalctl -u yorum-kanali -n 40 --no-pager -o cat")


class Hata(Exception):
    pass


def paketle():
    eksik = [ad for ad in DOSYALAR if not (KOK / ad).exists()]
    if eksik:
        raise Hata("Bu dosyalar klasörde yok: " + ", ".join(eksik))
    tampon = io.BytesIO()
    with tarfile.open(fileobj=tampon, mode="w:gz") as tar:
        for ad in DOSYALAR:
            tar.add(KOK / ad, arcname=ARSIV_ADI.get(ad, ad))
    return tampon.getvalue()


def baglan():
    istemci = paramiko.SSHClient()
    if PARMAK_IZI.exists():
        istemci.load_host_keys(str(PARMAK_IZI))
    istemci.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Sunucuya bağlanılıyor ({SUNUCU})...")
    try:
        # Önce bu bilgisayarda kayıtlı bir SSH anahtarı varsa onu dene
        istemci.connect(SUNUCU, port=PORT, username=KULLANICI, timeout=20)
    except paramiko.BadHostKeyException as hata:
        raise Hata("Sunucunun kimliği değişmiş. Sunucuyu yeniden kurduysan "
                   "sunucu_parmakizi.txt dosyasını silip tekrar dene.") from hata
    except (socket.timeout, OSError) as hata:
        raise Hata(f"Sunucuya ulaşılamadı: {hata}") from hata
    except paramiko.SSHException:
        for deneme in range(3):
            sifre = getpass.getpass(f"{KULLANICI} şifresi (yazarken görünmez, sonra Enter): ")
            try:
                istemci.connect(SUNUCU, port=PORT, username=KULLANICI, password=sifre,
                                timeout=20, look_for_keys=False, allow_agent=False)
                break
            except paramiko.AuthenticationException:
                print("Şifre kabul edilmedi." + (" Tekrar dene." if deneme < 2 else ""))
        else:
            raise Hata("Sunucuya giriş yapılamadı (şifre).")
    istemci.save_host_keys(str(PARMAK_IZI))
    return istemci


def calistir(istemci, komut):
    _, cikis, _ = istemci.exec_command(komut, get_pty=True)
    for satir in iter(cikis.readline, ""):
        print(satir, end="", flush=True)
    return cikis.channel.recv_exit_status()


def gonder():
    veri = paketle()
    istemci = baglan()
    try:
        print("Dosyalar kopyalanıyor...")
        sftp = istemci.open_sftp()
        sftp.putfo(io.BytesIO(veri), UZAK_ARSIV)
        sftp.close()
        print("Sunucuda kuruluyor (ilk seferde birkaç dakika sürer)...\n")
        kod = calistir(istemci, KURULUM_KOMUTU)
    finally:
        istemci.close()
    if kod != 0:
        raise Hata(f"Sunucudaki kurulum yarıda kaldı (kod {kod}).")


def kayit():
    istemci = baglan()
    try:
        calistir(istemci, KAYIT_KOMUTU)
    finally:
        istemci.close()


def main():
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "kayit":
            kayit()
        else:
            gonder()
    except Hata as hata:
        print("\nSORUN:", hata)
        print("Bu pencerenin ekran görüntüsünü gönder.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nİptal edildi.")
        sys.exit(1)


if __name__ == "__main__":
    main()
