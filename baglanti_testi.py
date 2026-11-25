"""Telegram, Anthropic ve ElevenLabs sunucularına ulaşılıp ulaşılamadığını test eder."""
import socket
import time
import urllib.request

import httpx

HEDEFLER = [
    ("Telegram", "api.telegram.org"),
    ("Anthropic", "api.anthropic.com"),
    ("ElevenLabs", "api.elevenlabs.io"),
    ("Google (karşılaştırma için)", "www.google.com"),
]


def baglan(host, aile, etiket):
    try:
        adres = socket.getaddrinfo(host, 443, aile)[0][4][0]
    except OSError:
        print(f"  {etiket}: adres yok")
        return
    try:
        bas = time.time()
        socket.create_connection((adres, 443), timeout=10).close()
        print(f"  {etiket}: tamam ({time.time() - bas:.1f} sn)")
    except OSError as hata:
        print(f"  {etiket}: HATA -> {hata}")


def main():
    print("=== Bağlantı testi ===")
    vekil = {k: v for k, v in urllib.request.getproxies().items() if k in ("http", "https")}
    print("Sistem proxy ayarı:", vekil or "yok")
    for ad, host in HEDEFLER:
        print(f"\n{ad} ({host})")
        try:
            adresler = sorted({a[4][0] for a in socket.getaddrinfo(host, 443)})
            print("  DNS: tamam ->", ", ".join(adresler)[:100])
        except OSError as hata:
            print("  DNS: HATA ->", hata)
            continue
        baglan(host, socket.AF_INET, "IPv4")
        baglan(host, socket.AF_INET6, "IPv6")
        try:
            bas = time.time()
            yanit = httpx.get(f"https://{host}", timeout=20)
            print(f"  HTTPS: tamam (kod {yanit.status_code}, {time.time() - bas:.1f} sn)")
        except Exception as hata:  # noqa: BLE001 - tanı amaçlı
            print(f"  HTTPS: HATA -> {type(hata).__name__}: {hata}")
    print("\nBu pencerenin ekran görüntüsünü gönder.")


if __name__ == "__main__":
    main()
