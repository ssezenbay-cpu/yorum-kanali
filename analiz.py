"""Ekran görüntülerini Claude'a okutur; özet, sayılar ve senaryoyu JSON olarak alır."""
import base64
import io
import json
import logging
import re

import anthropic
from PIL import Image, ImageOps

import ayarlar as A
from veriler import GRUPLAR, fiyat_sayi

ROLLER = ["acilis", "baglam", "ovgu", "sikayet", "hukum", "kapanis"]
SENARYO_SURUMU = 5  # kurallar değişince artar; /tekrar eski metni görünce analizi yeniler
HUKUMLER = {"ALINIR", "ALINMAZ", "DİKKATLİ AL"}
log = logging.getLogger("analiz")
YASAK_IFADELER = ["denedim", "kullandım", "test ettim", "aldım ve", "bende de"]


class AnalizHatasi(Exception):
    pass


def _resim_parcasi(yol):
    with Image.open(yol) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((1568, 1568))
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
   "Orijinal çıktı", "hızlı geldi", "iyi paketlenmiş" konu değildir. Taklit gelme, garanti ya da fatura sorunu eksi konu olabilir.
   Her yorumun "konular" alanına o yorumda gerçekten geçen konuların kodlarını yaz; bir yorumda hem artı hem eksi olabilir.
5. "anahtar": yorumun ilk 4 kelimesi (yalnızca tekrarları ayıklamak için kullanılır, videoda kullanılmaz).
   Yorum yazanın adını hiçbir alana yazma."""

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
  "konular": [{{"kod": "A1", "ad": "Sıcak tutma", "yon": "arti"}}, {{"kod": "E1", "ad": "Kapak sızdırıyor", "yon": "eksi"}}],
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
   övgüler açıkça baskınsa "ALINIR"; karışıksa "DİKKATLİ AL". Ürünü anlatan yorum 30'dan azsa hükmü temkinli kur.
6. Dürüst oran: azınlıktaki bir bulguya "çoğu", "herkes", "neredeyse hepsi" deme; sayıyı söyle.
7. Konuşur gibi yaz. Toplam 40-50 kelime. Her cümle kısa, en fazla 9 kelime; yan cümle yok.
   Fiyatı, puanı ve toplam değerlendirme sayısını söyleme; ekranda yazıyor.
8. Bölümler:
   acilis: en şaşırtıcı somut bulgu, rakamlı. Ürünün kendisiyle ilgili olsun (dayanıklılık, performans, kullanım).
     Ürünü hiç görmemiş biri de ilk duyuşta anlamalı; açıklamasız teknik terim yok. Hükmü söyleme.
   baglam: tek kısa cümle: kaç yorum okunduğu ve kaçının ürünü anlattığı, ardından "Hüküm sonda."
   ovgu: bağlamdaki sayıyı tekrar etmeden doğrudan "12 kişi ..." diye başlar; en çok övülen iki konu.
   sikayet: kısa bir soruyla başlar ("Peki sorun ne?" gibi), sonra en çok şikâyet edilen iki konu, sayılarıyla.
   hukum: "Hüküm: ..." ve kime uygun olduğu, kısa.
   kapanis: "Sıradaki ürün ne olsun? Yorumlara yaz. Yorum dosyası #N."
9. ekran_acilis: ilk karedeki büyük yazı, en fazla 7 kelime, oranı göster: "7/46 alıcı: boya soyuluyor" gibi.
10. ovulenler ve sikayetler yalnızca verilen listeden seçilir; konu adı ve sayı listedekiyle aynı. Aynı konu iki tarafta olmasın.

Yalnızca geçerli bir JSON nesnesi döndür, başka hiçbir şey yazma."""

SENARYO_SEMA = """{{
  "ovulenler": [{{"konu": "listedeki ad", "sayi": 0}}, {{"konu": "...", "sayi": 0}}],
  "sikayetler": [{{"konu": "listedeki ad", "sayi": 0}}, {{"konu": "...", "sayi": 0}}],
  "hukum": "ALINIR | ALINMAZ | DİKKATLİ AL",
  "kime_uygun": "en fazla 10 kelime: kime uygun ya da kime uygun değil",
  "ekran_acilis": "en fazla 7 kelime, oranlı; hüküm değil",
  "senaryo": {{
    "acilis": "...",
    "baglam": "...",
    "ovgu": "...",
    "sikayet": "...",
    "hukum": "...",
    "kapanis": "Sıradaki ürün ne olsun? Yorumlara yaz. Yorum dosyası #{no}."
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
            konular[kod] = {"ad": ad, "yon": yon, "sayi": 0}
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
    return {"okunan_yorum": len(tekil), "urun_yorumu": len(urun_yorumlari), "konular": sirali,
            "kaynak_sayisi": kaynak_sayisi}


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
    return sonuc[:2]


def _iste(istemci, sistem, icerik, etiket, max_tokens=16000):
    """Claude'a sorar, JSON döndürür; JSON gelmezse bir kez düzelttirir."""
    mesajlar = [{"role": "user", "content": icerik}]
    for deneme in range(2):
        yanit = istemci.messages.create(model=A.CLAUDE_MODEL, max_tokens=max_tokens, system=sistem,
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


def senaryo_yaz(istemci, okuma, no, kaynak_notu=""):
    """Sayımı yapar, metni bu sayılarla yazdırır ve doğrulanmış video verisini döndürür."""
    if "hata" in okuma:
        raise AnalizHatasi(okuma["hata"])
    sayim = sayim_yap(okuma)
    if sayim["okunan_yorum"] < 5 or sayim["urun_yorumu"] < 8:
        raise AnalizHatasi(
            f"{sayim['okunan_yorum']} yorum okundu ama yalnızca {sayim['urun_yorumu']} tanesi ürünü anlatıyor "
            "(gerisi kargo, teşekkür vb.). 1-3 yıldız ve fotoğraflı yorumlardan daha fazla görüntü gönderip tekrar dene.")
    arti = [k for k in sayim["konular"] if k["yon"] == "arti"]
    eksi = [k for k in sayim["konular"] if k["yon"] == "eksi"]
    tablo = "\n".join(
        [f"Ürün: {okuma.get('urun_adi', '')} ({okuma.get('kategori', '')})",
         f"Okunan yorum: {sayim['okunan_yorum']}", f"Ürünün kendisini anlatan yorum: {sayim['urun_yorumu']}",
         "Övülen konular (kaç yorumda geçtiği):"] + [f"- {k['ad']}: {k['sayi']}" for k in arti[:8]]
        + ["Şikâyet edilen konular (kaç yorumda geçtiği):"] + [f"- {k['ad']}: {k['sayi']}" for k in eksi[:8]])
    if kaynak_notu:
        tablo += "\n" + kaynak_notu
    istek = (f"Bu video \"Yorum dosyası #{no}\" olacak.\n\n{tablo}\n\nBu sayılarla şu yapıda JSON döndür:\n"
             + SENARYO_SEMA.format(no=no))
    yazi = _iste(istemci, SENARYO_SISTEM.replace("{kanal}", A.KANAL_ADI), [{"type": "text", "text": istek}],
                 "Senaryo", max_tokens=8000)
    veri = {alan: okuma.get(alan, "") for alan in ("urun_adi", "kategori", "grup", "fiyat", "puan",
                                                   "toplam_yorum", "satici")}
    veri.update({k: yazi.get(k) or "" for k in ("hukum", "kime_uygun", "ekran_acilis", "baslik", "aciklama")})
    veri["senaryo"] = yazi.get("senaryo") if isinstance(yazi.get("senaryo"), dict) else {}
    veri["etiketler"] = yazi.get("etiketler") or []
    veri["urun_gorseli"] = okuma.get("urun_gorseli")
    veri["urun_fotograflari"] = okuma.get("urun_fotograflari") or []
    veri["okunan_yorum"] = sayim["okunan_yorum"]
    veri["urun_yorumu"] = sayim["urun_yorumu"]
    veri["ovulenler"] = _maddeleri_duzelt(yazi.get("ovulenler"), arti)
    veri["sikayetler"] = _maddeleri_duzelt(yazi.get("sikayetler"), eksi)
    veri["uyarilar"] = list(okuma.get("uyarilar") or [])
    if not veri["senaryo"]:
        raise AnalizHatasi("Metin yazılamadı. Tekrar dene.")
    veri = dogrula(veri, no)
    izinli = {sayim["okunan_yorum"], sayim["urun_yorumu"], no} | {k["sayi"] for k in sayim["konular"]}
    metin = " ".join(veri["senaryo"].values())
    urun_sayilari = set(re.findall(r"\d+", str(veri.get("urun_adi", ""))))
    for sayi in sorted(set(re.findall(r"\b\d+\b", metin))):
        if int(sayi) not in izinli and sayi not in urun_sayilari:
            veri["uyarilar"].append(f"Metinde sayımda olmayan bir sayı var: {sayi}. Yayından önce kontrol et.")
    veri["sayim"] = sayim
    return veri


def _gorsel_kutusu(deger):
    """{"goruntu": n, "kutu": [x1, y1, x2, y2]} biçimini doğrular; bozuksa None."""
    try:
        goruntu = int(deger["goruntu"])
        x1, y1, x2, y2 = (min(1.0, max(0.0, float(v))) for v in deger["kutu"])
    except (TypeError, KeyError, ValueError):
        return None
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
            "1-3 yıldız ve fotoğraflı yorumlardan daha fazla görüntü gönderip tekrar /hazirla yaz.")
    veri["urun_yorumu"] = urun_yorumu
    veri["satici"] = str(veri.get("satici") or "").strip()

    for alan in ("ovulenler", "sikayetler"):
        temiz = []
        for oge in (veri.get(alan) or [])[:2]:
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


EN_FAZLA_GORUNTU = 30


def analiz_et(resimler, no):
    """İki adım: 1) görüntülerdeki yorumlar tek tek listelenir, 2) kod sayar ve metin bu sayılarla yazılır."""
    istemci = anthropic.Anthropic(api_key=A.ANTHROPIC_API_KEY)
    resimler = list(resimler)
    icerik = [_resim_parcasi(r) for r in resimler[:EN_FAZLA_GORUNTU]]
    icerik.append({"type": "text", "text": OKUMA_ISTEGI.format(n=len(icerik))})
    okuma = _iste(istemci, OKUMA_SISTEM.replace("{kanal}", A.KANAL_ADI), icerik, "Okuma")
    veri = senaryo_yaz(istemci, okuma, no)
    veri["okuma"] = {"konular": okuma.get("konular"), "yorumlar": okuma.get("yorumlar")}
    if len(resimler) > EN_FAZLA_GORUNTU:
        veri["uyarilar"].append(f"{len(resimler)} görüntü gönderildi; ilk {EN_FAZLA_GORUNTU} tanesi okundu.")
    return veri


def anthropic_dogrula(anahtar):
    """Anahtar geçerliyse True döner (ücretsiz bir istekle)."""
    try:
        anthropic.Anthropic(api_key=anahtar).models.list(limit=1)
        return True
    except anthropic.AuthenticationError:
        return False
