"""Web araştırması: bir ürünün yorumlarını birden çok siteden okuyup video için analiz üretir.

Ekran görüntüsü gerekmez. Kullanıcı ayrıca ekran görüntüsü gönderdiyse onlardaki yorumlar da sayılır.
Trendyol ve Amazon gibi otomatik okumaya kapalı siteler atlanır; robots.txt kurallarına uyulur.
"""
import logging
from datetime import date

import anthropic

import ayarlar as A
from analiz import (OKUMA_KURALLARI, OKUMA_SEMA, AnalizHatasi, _json_cikar, _resim_parcasi, sayim_yap,
                    senaryo_yaz)
from urun_avi import _son_metin, _tum_metin

log = logging.getLogger("arastirma")

SISTEM = """Sen "{kanal}" adlı Türkçe bir YouTube Shorts ve TikTok kanalının yorum okuyucususun.
Görevin: verilen ürünün alıcı yorumlarını internette bulup okumak ve her yorumu tek tek listelemek. Sayımı program yapacak.

Nerede ara (Türkiye):
- Hepsiburada ürün sayfası ve değerlendirmeleri (fiyat, puan ve toplam değerlendirme sayısını buradan al)
- Şikâyetvar'daki ürün ya da model şikâyetleri
- Ekşi Sözlük başlıkları, DonanımHaber ve Donanım Arşivi forumları
- Akakçe kullanıcı yorumları ve bağımsız inceleme yazıları
Trendyol ve Amazon otomatik okumaya kapalı; denersen ve açılmazsa zaman kaybetme, diğer kaynaklara geç.
Açılmayan bir sayfayı başka yollarla (önbellek, kopya site) okumaya çalışma.

Aynı modele odaklan: markanın başka modelleriyle ilgili yorumları listeleme; model özelinde yeterli yorum yoksa "uyarilar"a yaz.
Yalnızca gerçekten açıp okuduğun sayfalardaki yorumları listele. Her yorumun "kaynak" alanına sitenin adını yaz.

""" + OKUMA_KURALLARI + """
6. "urun_gorseli" ve "urun_fotograflari": kullanıcı görüntü gönderdiyse ürün fotoğrafının yerini ve tamamı ürün fotoğrafı
   olan görüntülerin numaralarını yaz (yakın çekimler hariç); göndermediyse null ve []. Görüntülerdeki yorumların
   "kaynak" alanı "ekran görüntüsü", "g" alanı görüntü numarası; internetten okuduklarında "g" null.
7. Araştırma bitince yalnızca istenen JSON'u döndür, başka hiçbir şey yazma."""

ISTEK = """Ürün: {urun}
Bugün {tarih}.
{gorsel_notu}
Önce bu ürünün yorumlarını yukarıdaki kaynaklarda ara ve oku (en az 25 ürün yorumu hedefle).
Sonra her yorumu tek tek listeleyip şu yapıda JSON döndür. Ek olarak "kaynaklar" alanına açıp okuduğun sayfaları yaz:
"kaynaklar": [{{"ad": "Hepsiburada", "adres": "sayfa adresi"}}]

"""

GORSEL_NOTU = ("Kullanıcı ayrıca {n} görüntü gönderdi (ürün fotoğrafları ya da ürün sayfası ve yorum ekran görüntüleri "
               "olabilir). Onlardaki yorumları da listele. Ürün adı görüntüyle uyuşmuyorsa görüntüdekini esas al.")

KAYNAK_NOTU = ("Kaynaklar (okunan yorum): {kaynaklar}. Bağlam cümlesinde yorumların hangi sitelerden okunduğunu kısaca söyle. "
               "Şikâyet siteleri doğası gereği olumsuzdur: hükmü yalnızca şikâyet sayısına dayandırma, "
               "pazaryeri yorumlarıyla dengele.")

DUZELT = ("Bulduklarına göre şimdi yalnızca istenen JSON nesnesini ver. Yeni arama yapma, "
          "JSON dışında hiçbir şey yazma.")


def _araclar(fetch=True):
    araclar = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 8}]
    if fetch:
        araclar.append({"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 10,
                        "max_content_tokens": 12000})
    return araclar


def _calistir(istemci, sistem, icerik, araclar):
    mesajlar = [{"role": "user", "content": icerik}]
    duzeltme = False
    durum = "?"
    for _ in range(10):
        yanit = istemci.messages.create(model=A.CLAUDE_MODEL, max_tokens=16000, system=sistem,
                                        messages=mesajlar, tools=araclar)
        bloklar = list(yanit.content)
        durum = yanit.stop_reason
        log.info("Araştırma yanıtı: durum=%s, arama=%d, sayfa=%d", durum,
                 sum(1 for b in bloklar if getattr(b, "name", "") == "web_search"),
                 sum(1 for b in bloklar if getattr(b, "name", "") == "web_fetch"))
        mesajlar.append({"role": "assistant", "content": yanit.content})
        if durum == "pause_turn":
            continue
        try:
            return _json_cikar(_son_metin(bloklar))
        except AnalizHatasi:
            log.warning("Araştırma JSON vermedi (durum=%s): %s", durum, _tum_metin(bloklar)[-1500:])
            if duzeltme:
                break
            mesajlar.append({"role": "user", "content": DUZELT})
            duzeltme = True
    raise AnalizHatasi(f"Araştırma sonucu okunamadı (durum: {durum}). Ayrıntı için /kayit yaz.")


def arastir(urun, no, gorseller=()):
    """Ürünü web'de araştırır: yorumlar listelenir, kod sayar, metin bu sayılarla yazılır."""
    if not A.ANTHROPIC_API_KEY:
        raise AnalizHatasi("Anthropic anahtarı yok. /anthropic ANAHTAR ile gir.")
    gorseller = list(gorseller)[:20]
    istek = ISTEK.format(urun=urun, tarih=date.today().strftime("%d.%m.%Y"),
                         gorsel_notu=GORSEL_NOTU.format(n=len(gorseller)) if gorseller else "")
    icerik = [_resim_parcasi(g) for g in gorseller]
    icerik.append({"type": "text", "text": istek + OKUMA_SEMA.replace(
        "{kaynak_alani}", '"kaynak": "site adı", ').format()})
    sistem = SISTEM.replace("{kanal}", A.KANAL_ADI)
    istemci = anthropic.Anthropic(api_key=A.ANTHROPIC_API_KEY)
    try:
        okuma = _calistir(istemci, sistem, icerik, _araclar(fetch=True))
    except anthropic.BadRequestError as hata:
        if "web_fetch" not in str(hata):
            raise
        log.warning("Sayfa okuma aracı kullanılamadı, yalnızca aramayla devam: %s", hata)
        okuma = _calistir(istemci, sistem, icerik, _araclar(fetch=False))
    if "hata" in okuma:
        raise AnalizHatasi(okuma["hata"])
    sayim = sayim_yap(okuma)
    adresler = {}
    for k in okuma.get("kaynaklar") or []:
        if isinstance(k, dict) and k.get("ad"):
            adresler.setdefault(str(k["ad"]).strip(), k.get("adres") or "")
    kaynaklar = [{"ad": ad, "okunan": sayi, "adres": adresler.get(ad, "")}
                 for ad, sayi in sorted(sayim["kaynak_sayisi"].items(), key=lambda x: -x[1])]
    not_ = KAYNAK_NOTU.format(kaynaklar=", ".join(f"{k['ad']} {k['okunan']}" for k in kaynaklar) or "belirtilmedi")
    sikayet_sitesi = sum(k["okunan"] for k in kaynaklar if "ikâyet" in k["ad"].lower() or "ikayet" in k["ad"].lower())
    pay = sikayet_sitesi / max(1, sayim["okunan_yorum"])
    if pay > 0.35:
        not_ += (f" DİKKAT: okunanların yüzde {int(pay * 100)}'i şikâyet sitesinden. Şikâyetleri 'şikâyet sitelerinde' "
                 "diye ayrıca belirt, oranı tüm alıcılara genelleme; sitedeki puan yüksekse hükmü 'ALINMAZ' yapma.")
    try:
        veri = senaryo_yaz(istemci, okuma, no, kaynak_notu=not_)
    except AnalizHatasi as hata:
        if "ürünü anlatıyor" not in str(hata):
            raise
        raise AnalizHatasi(
            f"İnternette bu model için yeterli ürün yorumu bulunamadı ({hata.args[0].split(' (')[0]}). "
            "Ürün adını biraz daha genel yaz ya da birkaç yorum ekran görüntüsü gönderip tekrar dene.") from hata
    veri["okuma"] = {"konular": okuma.get("konular"), "yorumlar": okuma.get("yorumlar")}
    if pay > 0.35:
        veri["uyarilar"].append(f"Okunan yorumların yüzde {int(pay * 100)}'i şikâyet sitesinden; örneklem olumsuza kayık. "
                                "Pazaryeri yorumlarının ekran görüntülerini de ekleyip tekrar denemek daha dengeli olur.")
    veri["kaynaklar"] = kaynaklar
    veri["arama"] = urun
    return veri


def kaynak_satiri(veri):
    parcalar = []
    for k in veri.get("kaynaklar") or []:
        try:
            sayi = int(k.get("okunan") or 0)
        except (TypeError, ValueError):
            sayi = 0
        parcalar.append(f"{k['ad']} ({sayi})" if sayi else str(k["ad"]))
    return ", ".join(parcalar)
