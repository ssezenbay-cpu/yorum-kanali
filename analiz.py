"""Ekran görüntülerini Claude'a okutur; özet, sayılar ve senaryoyu JSON olarak alır."""
import base64
import io
import json
import logging
import re
from datetime import datetime

import anthropic
from PIL import Image, ImageOps

import ayarlar as A
from veriler import GRUPLAR, fiyat_sayi

ROLLER = ["acilis", "baglam", "ovgu", "sikayet", "hukum", "kapanis"]
SENARYO_SURUMU = 8  # kurallar değişince artar; /tekrar eski metni görünce analizi yeniler
HUKUMLER = {"ALINIR", "ALINMAZ", "DİKKATLİ AL"}
log = logging.getLogger("analiz")
YASAK_IFADELER = ["denedim", "kullandım", "test ettim", "aldım ve", "bende de"]


class AnalizHatasi(Exception):
    pass


def _resim_parcasi(yol):
    with Image.open(yol) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((1300, 1300))  # yorum yazısı bu boyutta okunuyor; büyüğü maliyeti artırır
        tampon = io.BytesIO()
        im.save(tampon, "JPEG", quality=85)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(tampon.getvalue()).decode("ascii"),
        },
    }


def _json_cikar(metin):
    eslesme = re.search(r"\{.*\}", metin or "", re.S)
    if not eslesme:
        raise AnalizHatasi("Yapay zekâ geçerli bir yanıt vermedi. Tekrar dene.")
    ham = eslesme.group(0)
    try:
        return json.loads(ham)
    except json.JSONDecodeError:
        pass
    try:  # sık görülen küçük bozukluklar: sondaki virgüller
        return json.loads(re.sub(r",\s*([}\]])", r"\1", ham))
    except json.JSONDecodeError as hata:
        raise AnalizHatasi(f"Yanıt okunamadı ({hata}). Tekrar dene.") from hata


DUZELT = ("Yanıtın istenen JSON değildi ya da yarım kaldı. Aynı analizi yalnızca istenen JSON nesnesi olarak "
          "ver; metinleri kısa tut, JSON dışında hiçbir şey yazma. Görüntülerde ürün sayfası ya da yorum yoksa "
          'yalnızca {"hata": "kısa açıklama"} döndür.')


OKUMA_KURALLARI = """Kesin kurallar:
1. Hiçbir bilgi uydurma. Fiyat, puan veya toplam değerlendirme sayısı okunamıyorsa boş bırak ve "uyarilar"a yaz.
2. Sayı verme; sayımı program yapacak. Senin işin her alıcı yorumunu "yorumlar" listesine TEK TEK ve BİR KEZ yazmak.
   Aynı yorum birden fazla yerde görünüyorsa (üst üste binen ekran görüntüleri, aynı tarih ve aynı başlangıç) bir kez yaz.
   Sitenin yapay zekâ özetleri ("Değerlendirme Özeti" gibi), puan dağılımı grafikleri, satıcı bilgileri ve soru-cevaplar yorum değildir.
3. "urun": yorum ürünün kendisi hakkında bilgi veriyorsa true: performans, malzeme, dayanıklılık, beden/kalıp, kullanım,
   kırık/eksik/taklit gelmesi, garanti ya da fatura sorunu. Yalnızca kargo hızı, paketleme, satıcı ilgisi, "teşekkürler",
   "tavsiye ederim", "güzel ürün" gibi bilgi vermeyen yorumlar false.
4. "konular": önce yorumlarda geçen ürün konularını tanımla: kod, kısa ad (en fazla 4 kelime), yön (arti ya da eksi).
   Aynı şeyi anlatan ifadeleri tek konuda birleştir ("boyası soyuldu" ve "boyası çizildi" → "Dış boya soyulma").
   Aynı parçanın sorunlarını da tek konuda topla ("kulp kırıldı" ve "kulp vidası uymuyor" → "Kulp sorunu"),
   böylece aynı kişi iki kez sayılmaz.
   "Orijinal çıktı", "hızlı geldi", "iyi paketlenmiş" konu değildir. Taklit gelme, garanti ya da fatura sorunu eksi konu olabilir.
   Her yorumun "konular" alanına o yorumda gerçekten geçen konuların kodlarını yaz; bir yorumda hem artı hem eksi olabilir.
5. "anahtar": yorumun ilk 4 kelimesi (yalnızca tekrarları ayıklamak için kullanılır, videoda kullanılmaz).
   Yorum yazanın adını hiçbir alana yazma.
6. Her konu için "alinti": o konuyu anlatan gerçek bir yorumdan en fazla 10 kelimelik birebir parça
   (küçük harf, yazım hatası düzeltilebilir). İsim, telefon, sipariş numarası gibi kişisel bilgi içermesin; yoksa boş bırak.
7. "yildiz": yorumun verdiği yıldız (1-5), görünmüyorsa null. "site": görüntülerdeki site adı (Trendyol, Hepsiburada...)."""

OKUMA_SEMA = """{{
  "urun_adi": "kısa ürün adı, en fazla 6 kelime",
  "kategori": "ürün tipi, 1-3 kelime (ör. termos, robot süpürge, kışlık bot)",
  "grup": "gunluk | ev_elektronigi | pahali  (pahali: 20.000 TL üstü; ev_elektronigi: daha ucuz elektronik ve küçük ev aletleri; gunluk: geri kalan her şey)",
  "fiyat": "ör. 1.299 TL ya da boş",
  "puan": "ör. 4,3 ya da boş",
  "toplam_yorum": "sayfada görünen toplam değerlendirme sayısı ya da boş",
  "satici": "görünüyorsa satıcı adı ve satıcı puanı, yoksa boş",
  "urun_gorseli": {{"goruntu": 1, "kutu": [0.0, 0.0, 1.0, 1.0]}},
  "urun_fotograflari": [1, 2],
  "site": "Trendyol",
  "konular": [{{"kod": "A1", "ad": "Sıcak tutma", "yon": "arti", "alinti": "en fazla 10 kelimelik gerçek parça"}}, {{"kod": "E1", "ad": "Kapak sızdırıyor", "yon": "eksi", "alinti": "..."}}],
  "yorumlar": [{{"g": 2, {kaynak_alani}"tarih": "görünüyorsa", "yildiz": 5, "anahtar": "ilk dört kelime", "urun": true, "konular": ["A1"]}}],
  "uyarilar": ["okunamayan veya belirsiz bilgiler"]
}}"""

GORSEL_KURALLARI = """"urun_gorseli": ürünün kendi büyük fotoğrafının hangi görüntüde olduğu (1'den başlayarak) ve o fotoğrafın sınırları [sol, üst, sağ, alt], görüntünün genişliğine ve yüksekliğine oranla 0 ile 1 arası. Kutu yalnızca ürün fotoğrafını kapsasın: sayfa okları, kalp/paylaş simgeleri, rozetler, "kargo bedava" etiketleri, sayfa göstergesi noktaları ve yazılar dışarıda kalsın. Alıcıların yorumlara eklediği fotoğrafları seçme. Ürün fotoğrafı yoksa null.
"urun_fotograflari": kullanıcının gönderdiği ve tamamı ürün fotoğrafı olan görüntülerin numaraları (ürün sayfasından kaydedilmiş farklı açılar). Ürünün yalnızca bir parçasını gösteren yakın çekimler girmez; ürün baştan sona görünmeli. Ekran görüntüleri, yorum ekranları ve alıcıların çektiği fotoğraflar girmez. Yoksa [].
"yorumlar" içindeki "g": yorumun bulunduğu görüntünün numarası."""

OKUMA_SISTEM = """Sen "{kanal}" adlı Türkçe bir YouTube Shorts ve TikTok kanalının yorum okuyucususun.
Kullanıcı sana bir e-ticaret ürün sayfasının, ürün fotoğraflarının ve alıcı yorumlarının ekran görüntülerini gönderir.
Görevin: görüntülerde gerçekten gördüğün yorumları tek tek listelemek ve konularına ayırmak.

""" + OKUMA_KURALLARI + "\n\n" + GORSEL_KURALLARI + """

Yalnızca geçerli bir JSON nesnesi döndür, başka hiçbir şey yazma.
Görüntülerde ürün sayfası ya da yorum yoksa yalnızca {"hata": "kısa açıklama"} döndür."""

OKUMA_ISTEGI = """{n} görüntü gönderiyorum. Yorumları tek tek listele ve şu yapıda JSON döndür:
""" + OKUMA_SEMA.replace("{kaynak_alani}", "")

SENARYO_SISTEM = """Sen "{kanal}" adlı Türkçe bir YouTube Shorts ve TikTok kanalının metin yazarısın.
Kanal alıcı yorumlarını okuyup "alınır mı" sorusuna cevap verir. Sesi yapay zekâ seslendirir; metin bu yüzden konuşur gibi olmalı.
Sana bir ürünün yorum sayımı verilecek. Bu sayılarla yaklaşık 20 saniyelik video metni yaz.

Kesin kurallar:
1. Yalnızca verilen sayıları kullan. Yeni sayı uydurma, yuvarlama, sayıları toplama.
2. Ürünü sen kullanmadın: "denedim", "kullandım", "test ettim" yok. Yorum yazanların adı yok, cümleleri birebir alıntı yok.
3. "Taklit", "orijinal değil" gibi iddiaları alıcıların görüşü olarak aktar ("7 alıcı orijinal olmadığını düşünüyor").
   Satıcı adı verme, satıcıyı suçlama. Bu tür şikâyetler çoksa hükümde "resmi ya da yetkili mağazadan al" de.
4. Sağlık, tedavi veya güvenlik iddiası yok.
5. Hüküm: şikâyetler ürünün temel işlevini bozuyorsa ya da ürünü anlatan yorumların yarısına yakınındaysa "ALINMAZ";
   övgüler açıkça baskınsa "ALINIR"; karışıksa "DİKKATLİ AL". Ürünü anlatan yorum 100'den azsa hüküm bölümünde
   bunu kısaca söyle ("Yorum az, sonuç kesin değil.").
   Güvenlik riski taşıyan bir şikâyet (sap/kulp kopması, kırılma, yanma, erime, elektrik, aşırı ısınma, patlama,
   keskin kenar) ürünü anlatan yorumların %8'inden fazlasında geçiyorsa hüküm "ALINIR" olamaz.
6. Dürüst oran: azınlıktaki bir bulguya "çoğu", "herkes", "neredeyse hepsi" deme; sayıyı söyle.
   İstisna: 31 sayısını sesli metinde söyleme (Türkçede argo şakaya döner); "otuzu aşkın" de. Ekranda 31 yazmaya devam eder.
7. Konuşur gibi yaz. Toplam 40-50 kelime. Her cümle kısa, en fazla 9 kelime; yan cümle yok.
   Fiyatı ve toplam değerlendirme sayısını söyleme; ekranda yazıyor. Puanı yalnızca açılıştaki çelişki için kullanabilirsin.
8. Bölümler:
   acilis: en şaşırtıcı somut bulgu, rakamlı. Ürünün kendisiyle ilgili olsun (dayanıklılık, performans, kullanım).
     Merak boşluğu bırak: sayıyı söyle, konuyu sonraya sakla ("Bu süpürgeyi alan 5 kişi aynı şeyden şikâyet ediyor").
     Konu şikâyet (ya da övgü) bölümünde açılır; orada açılış cümlesini tekrar etme.
     Sitedeki puan yüksekse (4,5 ve üstü) ve şikâyetler belirginse bu çelişkiyi kullanabilirsin
     ("4,7 puanlı süpürgeyi alan 5 kişi aynı şeyi yazıyor"). Ürünü hiç görmemiş biri de anlamalı; hükmü söyleme.
   baglam: tek kısa cümle: kaç yorum okunduğu ve kaçının ürünü anlattığı, ardından "Hüküm sonda."
   ovgu: bağlamdaki sayıyı tekrar etmeden doğrudan "12 kişi ..." diye başlar; en çok övülen iki konu.
   sikayet: kısa bir soruyla başlar ("Peki sorun ne?" gibi), sonra en çok şikâyet edilen iki ya da üç konu, sayılarıyla.
     ovulenler ve sikayetler listesine yalnızca metinde sayısıyla söylediğin konuları koy (ekrandaki her satır seslendirilmeli).
   hukum: "Hüküm: ..." ve kime uygun olduğu, kısa. "kime_uygun" somut bir kullanım ya da kişi tarifi olsun
     ("küçük evde hızlı temizlik için", "uzun süre çalışacaksan değil"); "riski göze alanlar" gibi boş ifade yok.
   kapanis: "Sıradaki dosyayı sen seç. Yorumlara yaz. Yorum dosyası #N."
9. ekran_acilis: ilk karedeki büyük yazı, en fazla 7 kelime, sesteki gibi sade: "9 alıcı aynı şeyi yazmış".
   Bölü işaretiyle oran yazma; oran ekranda ayrıca küçük etiket olarak gösteriliyor.
10. ovulenler ve sikayetler yalnızca verilen listeden seçilir; konu adı ve sayı listedekiyle aynı. Aynı konu iki tarafta olmasın.
    Yalnızca 1 yorumda geçen konuyu seçme (listede 2 ve üstü varsa).

Yalnızca geçerli bir JSON nesnesi döndür, başka hiçbir şey yazma."""

SENARYO_SEMA = """{{
  "ovulenler": [{{"konu": "listedeki ad", "sayi": 0}}, {{"konu": "...", "sayi": 0}}],
  "sikayetler": [{{"konu": "listedeki ad", "sayi": 0}}, {{"konu": "...", "sayi": 0}}, {{"konu": "varsa üçüncü", "sayi": 0}}],
  "hukum": "ALINIR | ALINMAZ | DİKKATLİ AL",
  "kime_uygun": "en fazla 10 kelime: kime uygun ya da kime uygun değil",
  "uygun": "en fazla 6 kelime: kime ya da ne için uygun (ör. müzik dinleyen, kısıtlı bütçe)",
  "uygun_degil": "en fazla 6 kelime: kime uygun değil (ör. telefonla çok konuşan)",
  "ekran_acilis": "en fazla 7 kelime, oranlı; hüküm değil",
  "senaryo": {{
    "acilis": "...",
    "baglam": "...",
    "ovgu": "...",
    "sikayet": "...",
    "hukum": "...",
    "kapanis": "Sıradaki dosyayı sen seç. Yorumlara yaz. Yorum dosyası #{no}."
  }},
  "baslik": "en fazla 60 karakter, merak uyandıran",
  "aciklama": "2-3 cümle",
  "etiketler": ["5-8 etiket, # işareti olmadan"]
}}"""


def _sade(metin):
    return " ".join(str(metin or "").lower().split())


def sayim_yap(okuma):
    """Modelin listelediği yorumları kodla sayar: tekrarları atar, konu başına kaç yorum olduğunu bulur."""
    konular = {}
    for k in okuma.get("konular") or []:
        if not isinstance(k, dict):
            continue
        kod = str(k.get("kod") or "").strip()
        ad = " ".join(str(k.get("ad") or "").split())[:40]
        if kod and ad:
            yon = "eksi" if str(k.get("yon") or "").lower().startswith("e") else "arti"
            alinti = " ".join(str(k.get("alinti") or "").strip(" \"'“”").split())
            alinti = " ".join(alinti.split()[:12]) if alinti and not re.search(r"\d{6,}", alinti) else ""
            konular[kod] = {"ad": ad, "yon": yon, "sayi": 0, "alinti": alinti}
    gorulen, tekil = set(), []
    for y in okuma.get("yorumlar") or []:
        if not isinstance(y, dict):
            continue
        imza = (_sade(y.get("kaynak")), _sade(y.get("tarih")), _sade(y.get("anahtar")))
        if imza[2] and imza in gorulen:
            continue
        gorulen.add(imza)
        tekil.append(y)
    urun_yorumlari = []
    kaynak_sayisi = {}
    for y in tekil:
        kodlar = {str(k) for k in (y.get("konular") or []) if str(k) in konular}
        urun = y.get("urun") is True or str(y.get("urun")).lower() == "true" or bool(kodlar)
        if y.get("kaynak"):
            ad = str(y["kaynak"]).strip()
            kaynak_sayisi[ad] = kaynak_sayisi.get(ad, 0) + 1
        if urun:
            urun_yorumlari.append(y)
            for kod in kodlar:
                konular[kod]["sayi"] += 1
    sirali = sorted((k for k in konular.values() if k["sayi"] > 0), key=lambda k: -k["sayi"])
    yildizlar = {}
    for y in urun_yorumlari:
        try:
            yildiz = int(y.get("yildiz"))
        except (TypeError, ValueError):
            continue
        if 1 <= yildiz <= 5:
            yildizlar[yildiz] = yildizlar.get(yildiz, 0) + 1
    return {"okunan_yorum": len(tekil), "urun_yorumu": len(urun_yorumlari), "konular": sirali,
            "kaynak_sayisi": kaynak_sayisi, "yildizlar": yildizlar}


def sayim_metni(sayim):
    """Sayımın kısa özeti (Telegram'da kontrol için)."""
    arti = [f"{k['ad']} {k['sayi']}" for k in sayim["konular"] if k["yon"] == "arti"][:5]
    eksi = [f"{k['ad']} {k['sayi']}" for k in sayim["konular"] if k["yon"] == "eksi"][:5]
    return (f"{sayim['okunan_yorum']} yorum, {sayim['urun_yorumu']} tanesi ürünle ilgili.\n"
            f"Övülen: {', '.join(arti) or '-'}\nŞikâyet: {', '.join(eksi) or '-'}")


def _konu_bul(ad, liste):
    hedef = _sade(ad)
    for k in liste:
        if _sade(k["ad"]) == hedef:
            return k
    for k in liste:
        if hedef and (hedef in _sade(k["ad"]) or _sade(k["ad"]) in hedef):
            return k
    return None


def _maddeleri_duzelt(secilen, liste):
    """Modelin seçtiği maddelerin sayısını sayımdan alır; listede olmayanı atar, boş kalırsa en çok geçenleri koyar."""
    sonuc, kullanilan = [], set()
    for oge in secilen or []:
        if not isinstance(oge, dict):
            continue
        k = _konu_bul(oge.get("konu"), liste)
        if k and k["ad"] not in kullanilan:
            sonuc.append({"konu": k["ad"], "sayi": k["sayi"]})
            kullanilan.add(k["ad"])
    for k in liste:
        if len(sonuc) >= 2:
            break
        if k["ad"] not in kullanilan:
            sonuc.append({"konu": k["ad"], "sayi": k["sayi"]})
            kullanilan.add(k["ad"])
    return sonuc[:3]


def _iste(istemci, sistem, icerik, etiket, max_tokens=16000, model=None):
    """Claude'a sorar, JSON döndürür; JSON gelmezse bir kez düzelttirir."""
    mesajlar = [{"role": "user", "content": icerik}]
    for deneme in range(2):
        yanit = istemci.messages.create(model=model or A.CLAUDE_MODEL, max_tokens=max_tokens, system=sistem,
                                        messages=mesajlar)
        metin = "".join(getattr(b, "text", "") for b in yanit.content)
        log.info("%s yanıtı: durum=%s, %d karakter", etiket, yanit.stop_reason, len(metin))
        try:
            return _json_cikar(metin)
        except AnalizHatasi:
            log.warning("%s JSON vermedi (durum=%s): %s", etiket, yanit.stop_reason, metin[-1500:] or "(boş)")
            if deneme == 1:
                raise AnalizHatasi(f"Yapay zekâ geçerli bir yanıt vermedi (durum: {yanit.stop_reason}). "
                                   "Ayrıntı için /kayit yaz.")
            if yanit.content:
                mesajlar.append({"role": "assistant", "content": yanit.content})
            mesajlar.append({"role": "user", "content": DUZELT})
    raise AnalizHatasi("Yapay zekâ geçerli bir yanıt vermedi.")


GUVENLIK = re.compile(r"sap|kulp|kırıl|kop|düş|yan[ıd]|yanık|eri[dm]|elektrik|çarp|ısın|patla|alev|keskin|kıvılcım")


def _guvenlik_riski(sayim):
    """Güvenlikle ilgili görünen ve ürün yorumlarının %8'inden fazlasında geçen şikâyet konusu (yoksa None)."""
    for k in sayim["konular"]:
        if k["yon"] == "eksi" and GUVENLIK.search(k["ad"].lower()) and k["sayi"] > 0.08 * max(1, sayim["urun_yorumu"]):
            return k
    return None


def senaryo_yaz(istemci, okuma, no, kaynak_notu="", kaynak_etiketi="", zorunlu_hukum=""):
    """Sayımı yapar, metni bu sayılarla yazdırır ve doğrulanmış video verisini döndürür."""
    if "hata" in okuma:
        raise AnalizHatasi(okuma["hata"])
    sayim = sayim_yap(okuma)
    if sayim["okunan_yorum"] < 5 or sayim["urun_yorumu"] < 8:
        raise AnalizHatasi(
            f"{sayim['okunan_yorum']} yorum okundu ama yalnızca {sayim['urun_yorumu']} tanesi ürünü anlatıyor "
            "(gerisi kargo, teşekkür vb.). Yorumları sitede 'En yeni' sıralamasıyla açıp daha fazla görüntü gönder.")
    arti = [k for k in sayim["konular"] if k["yon"] == "arti"]
    eksi = [k for k in sayim["konular"] if k["yon"] == "eksi"]
    # tek yorumda geçen konular, daha güçlüleri varsa seçilmesin
    arti = [k for k in arti if k["sayi"] >= 2] if sum(k["sayi"] >= 2 for k in arti) >= 2 else arti
    eksi = [k for k in eksi if k["sayi"] >= 2] if sum(k["sayi"] >= 2 for k in eksi) >= 2 else eksi
    puan, toplam_ = str(okuma.get("puan") or "").strip(), str(okuma.get("toplam_yorum") or "").strip()
    tablo = "\n".join(
        [f"Ürün: {okuma.get('urun_adi', '')} ({okuma.get('kategori', '')})",
         f"Sitedeki puan: {puan or 'bilinmiyor'}" + (f" ({toplam_} değerlendirme)" if toplam_ else ""),
         f"Okunan yorum: {sayim['okunan_yorum']}", f"Ürünün kendisini anlatan yorum: {sayim['urun_yorumu']}",
         "Övülen konular (kaç yorumda geçtiği):"] + [f"- {k['ad']}: {k['sayi']}" for k in arti[:8]]
        + ["Şikâyet edilen konular (kaç yorumda geçtiği):"] + [f"- {k['ad']}: {k['sayi']}" for k in eksi[:8]])
    yz = sayim["yildizlar"]
    if sum(yz.values()) >= 10:
        tablo += (f"\nYıldız dağılımı (ürün yorumlarında): 5 yıldız {yz.get(5, 0)}, 4 yıldız {yz.get(4, 0)}, "
                  f"3 yıldız {yz.get(3, 0)}, 1-2 yıldız {yz.get(1, 0) + yz.get(2, 0)}")
    if kaynak_notu:
        tablo += "\n" + kaynak_notu
    istek = (f"Bu video \"Yorum dosyası #{no}\" olacak.\n\n{tablo}\n\nBu sayılarla şu yapıda JSON döndür:\n"
             + SENARYO_SEMA.format(no=no))
    risk = _guvenlik_riski(sayim)
    if zorunlu_hukum:
        istek = f"Hüküm kesinlikle \"{zorunlu_hukum}\" olacak; metni buna göre yaz.\n" + istek
    sistem_ = SENARYO_SISTEM.replace("{kanal}", A.KANAL_ADI)
    yazi = _iste(istemci, sistem_, [{"type": "text", "text": istek}], "Senaryo", max_tokens=8000)
    if not zorunlu_hukum and risk and str(yazi.get("hukum", "")).upper() == "ALINIR":
        # Güvenlik şikâyeti yüksekken "ALINIR" çıktı: metin bu kuralla yeniden yazılır (tutarlı kalsın diye)
        log.info("Güvenlik şikâyeti (%s %d) varken ALINIR geldi; DİKKATLİ AL ile yeniden yazılıyor", risk["ad"], risk["sayi"])
        zorunlu_hukum = "DİKKATLİ AL"
        istek = (f"Hüküm kesinlikle \"DİKKATLİ AL\" olacak: \"{risk['ad']}\" bir güvenlik riski ve "
                 f"{risk['sayi']} yorumda geçiyor. Metni buna göre yaz.\n" + istek)
        yazi = _iste(istemci, sistem_, [{"type": "text", "text": istek}], "Senaryo", max_tokens=8000)
    if zorunlu_hukum:
        yazi["hukum"] = zorunlu_hukum
    veri = {alan: okuma.get(alan, "") for alan in ("urun_adi", "kategori", "grup", "fiyat", "puan",
                                                   "toplam_yorum", "satici")}
    veri.update({k: yazi.get(k) or "" for k in ("hukum", "kime_uygun", "uygun", "uygun_degil", "ekran_acilis",
                                                 "baslik", "aciklama")})
    if not veri["kime_uygun"] and veri["uygun"]:
        veri["kime_uygun"] = veri["uygun"]
    veri["senaryo"] = yazi.get("senaryo") if isinstance(yazi.get("senaryo"), dict) else {}
    veri["etiketler"] = yazi.get("etiketler") or []
    veri["urun_gorseli"] = okuma.get("urun_gorseli")
    veri["urun_fotograflari"] = okuma.get("urun_fotograflari") or []
    veri["okunan_yorum"] = sayim["okunan_yorum"]
    veri["urun_yorumu"] = sayim["urun_yorumu"]
    veri["ovulenler"] = _maddeleri_duzelt(yazi.get("ovulenler"), arti)
    veri["sikayetler"] = _maddeleri_duzelt(yazi.get("sikayetler"), eksi)
    senaryo_ = yazi.get("senaryo") if isinstance(yazi.get("senaryo"), dict) else {}
    for alan, rol in (("ovulenler", "ovgu"), ("sikayetler", "sikayet")):
        soylenen = set(re.findall(r"\b\d+\b", str(senaryo_.get(rol, ""))))
        uyan = [o for o in veri[alan] if str(o["sayi"]) in soylenen]
        if uyan:  # ekranda yalnızca seslendirilen maddeler kalsın
            veri[alan] = uyan
    # ekranda gösterilecek kısa, isimsiz alıntılar: seçilen ilk övgü ve ilk şikâyet konusundan
    veri["alintilar"] = {}
    for alan, rol, liste in (("ovulenler", "ovgu", arti), ("sikayetler", "sikayet", eksi)):
        for oge in veri[alan]:
            k_ = _konu_bul(oge["konu"], liste)
            if k_ and k_.get("alinti"):
                veri["alintilar"][rol] = k_["alinti"]
                break
    veri["kaynak_etiketi"] = kaynak_etiketi or str(okuma.get("site") or "").strip() or "ekran görüntüleri"
    veri["tarih"] = datetime.now().strftime("%d.%m.%Y")
    gorulen_, uyarilar_ = set(), []
    for u in okuma.get("uyarilar") or []:
        u = " ".join(str(u).split())
        anahtar_ = _sade(u)[:40]
        if not u or anahtar_ in gorulen_ or re.search(r"bu grupta|ürün sayfası yok|site adı|devamını oku|"
                                                       r"görünmüyor|okunamadı|belirsiz|kesik", u.lower()):
            continue  # görüntü okumanın ayrıntıları; kullanıcıya gereksiz
        gorulen_.add(anahtar_)
        uyarilar_.append(u)
    veri["uyarilar"] = uyarilar_[:5]
    if not veri["senaryo"]:
        raise AnalizHatasi("Metin yazılamadı. Tekrar dene.")
    veri = dogrula(veri, no)
    for rol in ROLLER:  # 31 sesli söylenmesin (argo şakaya döner); ekrandaki çubukta 31 yazmaya devam eder
        veri["senaryo"][rol] = re.sub(r"\b31(?=\s)", "otuzu aşkın", veri["senaryo"][rol])
    if sayim["urun_yorumu"] < 100 and "kesin" not in veri["senaryo"]["hukum"].lower():
        veri["senaryo"]["hukum"] = veri["senaryo"]["hukum"].rstrip(" .") + ". Yorum az, sonuç kesin değil."
    izinli = {sayim["okunan_yorum"], sayim["urun_yorumu"], no} | {k["sayi"] for k in sayim["konular"]}
    metin = " ".join(veri["senaryo"].values())
    urun_sayilari = set(re.findall(r"\d+", f"{veri.get('urun_adi', '')} {puan}"))
    for sayi in sorted(set(re.findall(r"\b\d+\b", metin))):
        if int(sayi) not in izinli and sayi not in urun_sayilari:
            veri["uyarilar"].append(f"Metinde sayımda olmayan bir sayı var: {sayi}. Yayından önce kontrol et.")
    if sayim["urun_yorumu"] < 30:
        veri["uyarilar"].append(f"Örneklem küçük: ürünü anlatan {sayim['urun_yorumu']} yorum var. "
                                "Daha fazla yorum (sitede 'En yeni' sıralamasıyla) daha güvenilir sonuç verir.")
    veri["sayim"] = sayim
    return veri


def _gorsel_kutusu(deger):
    """{"goruntu": n, "kutu": [x1, y1, x2, y2]} biçimini doğrular; bozuksa None."""
    try:
        goruntu = int(deger["goruntu"])
    except (TypeError, KeyError, ValueError):
        return None
    try:
        x1, y1, x2, y2 = (min(1.0, max(0.0, float(v))) for v in deger["kutu"])
    except (TypeError, KeyError, ValueError):
        x1, y1, x2, y2 = 0.0, 0.0, 1.0, 1.0  # kutu yoksa görüntünün tamamı (tam ürün fotoğrafı)
    if goruntu < 1 or x2 - x1 < 0.08 or y2 - y1 < 0.05:
        return None
    return {"goruntu": goruntu, "kutu": [x1, y1, x2, y2]}


def dogrula(veri, no):
    if "hata" in veri:
        raise AnalizHatasi(veri["hata"])
    eksik = [a for a in ("urun_adi", "okunan_yorum", "ovulenler", "sikayetler",
                         "hukum", "senaryo", "baslik") if a not in veri]
    if eksik:
        raise AnalizHatasi("Yanıtta eksik alanlar var: " + ", ".join(eksik))

    uyarilar = list(veri.get("uyarilar") or [])
    try:
        okunan = int(veri["okunan_yorum"])
    except (TypeError, ValueError):
        raise AnalizHatasi("Okunan yorum sayısı anlaşılamadı.")
    if okunan < 5:
        raise AnalizHatasi(f"Yalnızca {okunan} yorum okunabildi. Daha fazla yorum ekran görüntüsü gönder.")
    veri["okunan_yorum"] = okunan
    try:
        urun_yorumu = int(veri.get("urun_yorumu", okunan))
    except (TypeError, ValueError):
        urun_yorumu = okunan
    urun_yorumu = max(0, min(urun_yorumu, okunan))
    if urun_yorumu < 8:
        raise AnalizHatasi(
            f"{okunan} yorum okundu ama yalnızca {urun_yorumu} tanesi ürünü anlatıyor (gerisi kargo, teşekkür vb.). "
            "Yorumları sitede 'En yeni' sıralamasıyla açıp daha fazla görüntü gönder, sonra /hazirla yaz.")
    veri["urun_yorumu"] = urun_yorumu
    veri["satici"] = str(veri.get("satici") or "").strip()

    for alan in ("ovulenler", "sikayetler"):
        temiz = []
        for oge in (veri.get(alan) or [])[:3]:
            sayi = max(0, min(int(oge.get("sayi", 0) or 0), urun_yorumu))
            temiz.append({"konu": str(oge.get("konu", "")).strip(), "sayi": sayi})
        if not temiz:
            raise AnalizHatasi(f"'{alan}' listesi boş geldi.")
        veri[alan] = temiz

    hukum = str(veri["hukum"]).strip().upper().replace("DIKKATLI", "DİKKATLİ")
    if hukum not in HUKUMLER:
        hukum = "DİKKATLİ AL"
        uyarilar.append("Hüküm anlaşılamadı, 'DİKKATLİ AL' kullanıldı.")
    veri["hukum"] = hukum

    senaryo = veri["senaryo"]
    for rol in ROLLER:
        if not str(senaryo.get(rol, "")).strip():
            raise AnalizHatasi(f"Senaryonun '{rol}' bölümü boş geldi.")
        senaryo[rol] = " ".join(str(senaryo[rol]).split())
    if "sonda" not in senaryo["baglam"].lower():
        senaryo["baglam"] = senaryo["baglam"].rstrip(" .") + ". Hüküm sonda."
    if f"#{no}" not in senaryo["kapanis"]:
        senaryo["kapanis"] = senaryo["kapanis"].rstrip(".") + f". Yorum dosyası #{no}."

    tam_metin = " ".join(senaryo[r] for r in ROLLER)
    kelime = len(tam_metin.split())
    if kelime > 72:
        uyarilar.append(f"Senaryo uzun ({kelime} kelime); video 30 saniyeyi geçebilir.")
    kucuk = tam_metin.lower()
    for ifade in YASAK_IFADELER:
        if ifade in kucuk:
            uyarilar.append(f"Senaryoda '{ifade}' ifadesi var; yayından önce kontrol et.")

    veri["kategori"] = str(veri.get("kategori") or "").strip()
    grup = str(veri.get("grup") or "").strip().lower()
    fiyat = fiyat_sayi(veri.get("fiyat"))
    if fiyat and fiyat >= 20000:
        grup = "pahali"
    if grup not in GRUPLAR:
        grup = "gunluk"
    veri["grup"] = grup

    veri["ekran_acilis"] = str(veri.get("ekran_acilis") or senaryo["acilis"]).strip()
    veri["urun_gorseli"] = _gorsel_kutusu(veri.get("urun_gorseli"))
    fotolar = []
    for n in veri.get("urun_fotograflari") or []:
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if n >= 1 and n not in fotolar:
            fotolar.append(n)
    veri["urun_fotograflari"] = fotolar[:4]
    veri["kime_uygun"] = str(veri.get("kime_uygun") or "").strip()
    veri["etiketler"] = [str(e).lstrip("#").replace(" ", "") for e in (veri.get("etiketler") or [])][:8]
    veri["uyarilar"] = uyarilar
    veri["surum"] = SENARYO_SURUMU
    return veri


EN_FAZLA_GORUNTU = 200  # ekran kaydından gelen kareler dahil; gruplar halinde okunur
GRUP = 40               # bir istekte gönderilen görüntü sayısı


def _grubu_birlestir(okuma, sonuc, kayma, grup_no):
    """Sonraki görüntü grubunun okumasını öncekine ekler: konu kodları korunur, görüntü numaraları kaydırılır."""
    kodlar = {str(k.get("kod")) for k in okuma.get("konular") or [] if isinstance(k, dict)}
    ad_kod = {_sade(k.get("ad")): str(k.get("kod")) for k in okuma.get("konular") or [] if isinstance(k, dict)}
    cevir = {}
    for k in sonuc.get("konular") or []:
        if not isinstance(k, dict):
            continue
        kod = str(k.get("kod") or "")
        if _sade(k.get("ad")) in ad_kod:  # aynı ad: eski koda bağla
            cevir[kod] = ad_kod[_sade(k.get("ad"))]
        elif kod in kodlar:  # aynı kod başka konu için kullanılmış: çakışmasın
            yeni_kod = f"G{grup_no}_{kod}"
            cevir[kod] = yeni_kod
            okuma["konular"].append(dict(k, kod=yeni_kod))
        else:
            cevir[kod] = kod
            okuma["konular"].append(k)
            kodlar.add(kod)
    for y in sonuc.get("yorumlar") or []:
        if not isinstance(y, dict):
            continue
        y["konular"] = [cevir.get(str(c), str(c)) for c in y.get("konular") or []]
        if isinstance(y.get("g"), int):
            y["g"] += kayma
        okuma.setdefault("yorumlar", []).append(y)
    for alan in ("urun_adi", "fiyat", "puan", "toplam_yorum", "satici", "site", "kategori"):
        if not okuma.get(alan) and sonuc.get(alan):
            okuma[alan] = sonuc[alan]
    if not okuma.get("urun_gorseli") and isinstance(sonuc.get("urun_gorseli"), dict):
        secim = dict(sonuc["urun_gorseli"])
        secim["goruntu"] = int(secim.get("goruntu", 1)) + kayma
        okuma["urun_gorseli"] = secim
    okuma["urun_fotograflari"] = list(okuma.get("urun_fotograflari") or []) + [
        int(n) + kayma for n in sonuc.get("urun_fotograflari") or [] if str(n).isdigit()]
    okuma.setdefault("uyarilar", []).extend(sonuc.get("uyarilar") or [])


def analiz_et(resimler, no, urun_adi=""):
    """İki adım: 1) görüntülerdeki yorumlar tek tek listelenir (40'lık gruplar halinde), 2) kod sayar ve metin
    bu sayılarla yazılır. urun_adi: kullanıcının /hazirla ile yazdığı marka ve model (görüntülerde ad yoksa)."""
    istemci = anthropic.Anthropic(api_key=A.ANTHROPIC_API_KEY)
    resimler = list(resimler)
    okunacak = resimler[:EN_FAZLA_GORUNTU]
    sistem = OKUMA_SISTEM.replace("{kanal}", A.KANAL_ADI)
    okuma = None
    for grup_no, bas in enumerate(range(0, len(okunacak), GRUP), 1):
        parca = okunacak[bas:bas + GRUP]
        icerik = [_resim_parcasi(r) for r in parca]
        istek = OKUMA_ISTEGI.format(n=len(icerik))
        if urun_adi:
            istek = f"Ürün (kullanıcı yazdı): {urun_adi}\n" + istek
        if okuma is not None:
            onceki = json.dumps([{"kod": k.get("kod"), "ad": k.get("ad"), "yon": k.get("yon")}
                                 for k in okuma.get("konular") or [] if isinstance(k, dict)], ensure_ascii=False)
            istek = (f"Bu, aynı ürünün {grup_no}. görüntü grubu (görüntü numaraları bu gruba göre 1'den başlar). "
                     f"Önceki gruplarda tanımlanan konular: {onceki}\n"
                     "Aynı konular için AYNI kodu ve adı kullan; gerçekten yeni bir konu varsa yeni kod ver. "
                     "Önceki gruplardaki bir yorumun devamı ya da tekrarı görünüyorsa yine yaz (program tekrarları ayıklar). "
                     "Ürün sayfası bu grupta yoksa ürün bilgilerini boş, urun_gorseli null bırakabilirsin.\n\n" + istek)
        icerik.append({"type": "text", "text": istek})
        sonuc = _iste(istemci, sistem, icerik, f"Okuma {grup_no}", model=A.OKUMA_MODELI or None)
        if "hata" in sonuc and okuma is not None:
            log.warning("Grup %d okunamadı: %s", grup_no, sonuc["hata"])
            continue
        if okuma is None:
            okuma = sonuc
        else:
            _grubu_birlestir(okuma, sonuc, bas, grup_no)
    if urun_adi:
        okuma["urun_adi"] = urun_adi
    veri = senaryo_yaz(istemci, okuma, no)
    veri["okuma"] = {"konular": okuma.get("konular"), "yorumlar": okuma.get("yorumlar")}
    if not okuma.get("urun_gorseli") and not okuma.get("urun_fotograflari"):
        veri["uyarilar"].append("Ürün fotoğrafı yoktu; videoda ürün yerine adı yazıyor. Ürün sayfasından fotoğraf "
                                f"kaydedip bota gönder, sonra /tekrar {no} yaz.")
    if not urun_adi and not (okuma.get("fiyat") or okuma.get("puan")):
        veri["uyarilar"].append("Ürün sayfası görüntüsü yoktu: ad, fiyat ve puan eksik olabilir. Adı netleştirmek için "
                                "bir dahakinde /hazirla MARKA MODEL yaz ya da ürün sayfasının ekran görüntüsünü ekle.")
    if len(resimler) > EN_FAZLA_GORUNTU:
        veri["uyarilar"].append(f"{len(resimler)} görüntü gönderildi; ilk {EN_FAZLA_GORUNTU} tanesi okundu.")
    return veri


def metni_yeniden_yaz(veri, no, zorunlu_hukum=""):
    """Kayıtlı sayımdan yalnızca video metnini yeniden yazar (görüntüler yeniden okunmaz; birkaç sentlik iş)."""
    kayit = veri.get("okuma") or {}
    if not kayit.get("yorumlar"):
        raise AnalizHatasi("Bu videonun ayrıntılı sayım kaydı yok; /tekrar NO tam ile yeniden analiz et.")
    okuma = {alan: veri.get(alan, "") for alan in ("urun_adi", "kategori", "grup", "fiyat", "puan", "toplam_yorum",
                                                   "satici")}
    okuma.update({"konular": kayit.get("konular") or [], "yorumlar": kayit["yorumlar"],
                  "urun_gorseli": veri.get("urun_gorseli"), "urun_fotograflari": veri.get("urun_fotograflari") or []})
    istemci = anthropic.Anthropic(api_key=A.ANTHROPIC_API_KEY)
    yeni = senaryo_yaz(istemci, okuma, no, kaynak_etiketi=veri.get("kaynak_etiketi", ""), zorunlu_hukum=zorunlu_hukum)
    for alan in ("kaynaklar", "arama", "urun_adi_kullanici"):
        if alan in veri:
            yeni[alan] = veri[alan]
    yeni["okuma"] = kayit
    return yeni


METIN_SISTEM = """Sen "{kanal}" adlı Türkçe bir YouTube Shorts ve TikTok kanalının yorum okuyucususun.
Sana bir ürünün alıcı yorumları numaralı liste olarak verilecek. Görevin: her yorumu konularına ayırmak.
Sayımı program yapacak; sen sayı verme.

""" + OKUMA_KURALLARI + """

Yorumlar zaten tekil; her numarayı bir kez ele al. Yalnızca geçerli bir JSON nesnesi döndür, başka hiçbir şey yazma."""

METIN_SEMA = """{{
  "kategori": "ürün tipi, 1-3 kelime",
  "grup": "gunluk | ev_elektronigi | pahali",
  "konular": [{{"kod": "A1", "ad": "Ses kalitesi", "yon": "arti", "alinti": "en fazla 10 kelimelik gerçek parça"}}],
  "yorumlar": [{{"n": 1, "urun": true, "konular": ["A1"]}}],
  "uyarilar": []
}}"""


def paketi_dogrula(paket):
    """Yorum paketi (yorumlar.json) beklenen yapıda mı; değilse AnalizHatasi."""
    if not isinstance(paket, dict) or paket.get("tur") != "yorum_paketi":
        raise AnalizHatasi("Bu dosya bir yorum paketi değil.")
    yorumlar = [y for y in paket.get("yorumlar") or [] if isinstance(y, dict) and str(y.get("metin") or "").strip()]
    if len(yorumlar) < 10:
        raise AnalizHatasi(f"Pakette yalnızca {len(yorumlar)} yorum var; en az 10 gerekli.")
    paket["yorumlar"] = yorumlar[:400]
    paket.setdefault("urun", {})
    return paket


def analiz_metinden(paket, gorseller, no):
    """Yorum paketinden video verisi: yorumlar metin olarak okunur, kod sayar, metin bu sayılarla yazılır.
    gorseller: ürün fotoğrafları (paketteki adreslerden indirilenler ya da kullanıcının gönderdikleri)."""
    paket = paketi_dogrula(paket)
    urun = paket["urun"]
    istemci = anthropic.Anthropic(api_key=A.ANTHROPIC_API_KEY)
    satirlar = []
    for i, y in enumerate(paket["yorumlar"], 1):
        yildiz = f"{y.get('yildiz')}★ · " if y.get("yildiz") else ""
        metin = " ".join(str(y.get("metin")).split())[:700]
        satirlar.append(f"[{i}] {yildiz}{metin}")
    istek = (f"Ürün: {urun.get('ad', '')}\nKaynak: {paket.get('kaynak', '')}\n\n{len(satirlar)} yorum:\n"
             + "\n".join(satirlar) + "\n\nŞu yapıda JSON döndür (her yorum numarası için bir satır):\n"
             + METIN_SEMA.format())
    okuma = _iste(istemci, METIN_SISTEM.replace("{kanal}", A.KANAL_ADI), [{"type": "text", "text": istek}],
                  "Metin okuma", model=A.OKUMA_MODELI or None)
    kaynak = str(paket.get("kaynak") or "").strip()
    gelen = {}
    for y in okuma.get("yorumlar") or []:
        try:
            gelen[int(y.get("n"))] = y
        except (TypeError, ValueError, AttributeError):
            continue
    yorumlar = []
    for i, y in enumerate(paket["yorumlar"], 1):
        siniflama = gelen.get(i, {})
        yorumlar.append({"anahtar": f"#{i}", "tarih": y.get("tarih", ""), "yildiz": y.get("yildiz"), "kaynak": kaynak,
                         "urun": siniflama.get("urun", False), "konular": siniflama.get("konular") or []})
    if len(gelen) < len(paket["yorumlar"]) * 0.8:
        log.warning("Metin okumada %d/%d yorum sınıflandı", len(gelen), len(paket["yorumlar"]))
    okuma.update({
        "urun_adi": urun.get("ad", ""), "fiyat": urun.get("fiyat", ""), "puan": urun.get("puan", ""),
        "toplam_yorum": urun.get("toplam_degerlendirme", ""), "satici": urun.get("satici", ""), "site": kaynak,
        "kategori": okuma.get("kategori") or urun.get("kategori", ""), "yorumlar": yorumlar,
        "urun_gorseli": {"goruntu": 1} if gorseller else None,
        "urun_fotograflari": list(range(1, min(len(gorseller), 4) + 1)),
    })
    etiket = kaynak + (f" · {paket['siralama']} {len(yorumlar)}" if paket.get("siralama") else "")
    veri = senaryo_yaz(istemci, okuma, no, kaynak_etiketi=etiket)
    veri["okuma"] = {"konular": okuma.get("konular"), "yorumlar": yorumlar}
    if len(gelen) < len(paket["yorumlar"]) * 0.8:
        veri["uyarilar"].append(f"Yorumların yalnızca {len(gelen)}/{len(paket['yorumlar'])} tanesi sınıflandırıldı.")
    if not gorseller:
        veri["uyarilar"].append("Ürün fotoğrafı yoktu; videoda ürün yerine adı yazıyor. Fotoğraf gönderip "
                                f"/tekrar {no} yaz.")
    return veri


def anthropic_dogrula(anahtar):
    """Anahtar geçerliyse True döner (ücretsiz bir istekle)."""
    try:
        anthropic.Anthropic(api_key=anahtar).models.list(limit=1)
        return True
    except anthropic.AuthenticationError:
        return False
