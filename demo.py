"""Kurulumu test eder: hiçbir API kullanmadan örnek bir video üretir (sessiz)."""
import os
import subprocess
import sys

from PIL import Image, ImageDraw

from analiz import dogrula
from ayarlar import CALISMA, CIKTI, font_bul
import okunus
from ses import sahte_seslendir
from video import F, videoyu_kurgula


def ornek_ekran_goruntusu(yol):
    resim = Image.new("RGB", (1080, 1500), (250, 250, 250))
    c = ImageDraw.Draw(resim)
    c.rectangle((0, 0, 1080, 110), fill=(242, 122, 26))
    c.text((40, 30), "örnek mağaza", font=F(46), fill=(255, 255, 255))
    c.rounded_rectangle((140, 180, 940, 980), 30, fill=(205, 196, 186))
    c.ellipse((330, 360, 750, 800), fill=(120, 92, 70))
    c.text((60, 1020), "Örnek Su Geçirmez Kışlık Bot", font=F(54), fill=(30, 30, 30))
    c.text((60, 1100), "1.299 TL", font=F(64), fill=(242, 122, 26))
    c.text((60, 1190), "4,2 / 5  ·  2.140 değerlendirme", font=F(40, False), fill=(90, 90, 90))
    resim.save(yol)


def demo_uret():
    """Sessiz örnek videoyu üretir ve dosya yolunu döndürür."""
    font_bul(True)
    klasor = CALISMA / "demo"
    klasor.mkdir(parents=True, exist_ok=True)
    resim = klasor / "urun.png"
    ornek_ekran_goruntusu(resim)
    veri = dogrula({
        "urun_adi": "Su geçirmez kışlık bot",
        "fiyat": "1.299 TL",
        "puan": "4,2",
        "toplam_yorum": "2.140",
        "okunan_yorum": 40,
        "ovulenler": [{"konu": "Sıcak tutuyor", "sayi": 22}, {"konu": "Kaymıyor", "sayi": 14}],
        "sikayetler": [{"konu": "Kalıbı dar", "sayi": 15}, {"konu": "Bağcık kopuyor", "sayi": 6}],
        "hukum": "DİKKATLİ AL",
        "kime_uygun": "Ayağın genişse bir numara büyük al.",
        "ekran_acilis": "40 yorumun 15'i aynı şikâyet",
        "senaryo": {
            "acilis": "Okuduğum 40 yorumun 15'i aynı şeyden şikâyet ediyor.",
            "baglam": "Su geçirmez kışlık bot, 1.299 lira, puanı 4,2. Kırk yorumu okudum.",
            "ovgu": "Yirmi iki alıcı sıcak tuttuğunu, on dört alıcı kaymadığını söylüyor.",
            "sikayet": "Ama asıl sorun kalıp. On beş kişi dar geldiğini yazmış, altı kişi bağcıktan şikâyetçi.",
            "hukum": "Hüküm: dikkatli al. Ayağın genişse bir numara büyük seç.",
            "kapanis": "Link profilde. Yorum dosyası #0.",
        },
        "baslik": "Bu botu almadan önce 40 yoruma baktım",
        "aciklama": "Demo.",
        "etiketler": ["demo"],
    }, 0)
    tam_metin = okunus.konusma_metni([veri["senaryo"][r] for r in
                                      ["acilis", "baglam", "ovgu", "sikayet", "hukum", "kapanis"]])
    ses = klasor / "ses.mp3"
    hiz = sahte_seslendir(tam_metin, ses)
    cikti = CIKTI / "demo.mp4"
    print("Demo video kurgulanıyor, 1-2 dakika sürebilir...")
    videoyu_kurgula(veri, [resim], ses, hiz, 0, cikti)
    return cikti


def main():
    cikti = demo_uret()
    print(f"Tamam: {cikti}")
    if sys.platform.startswith("win"):
        os.startfile(cikti)  # noqa: S606 - kullanıcının kendi dosyası


if __name__ == "__main__":
    try:
        main()
    except FileNotFoundError as hata:
        print("Hata:", hata)
    except subprocess.CalledProcessError:
        print("Hata: ffmpeg çalıştırılamadı. ffmpeg'i kurup pencereyi yeniden aç.")
