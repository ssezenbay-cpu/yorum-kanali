"""Web araştırması: bir ürünün yorumlarını birden çok siteden okuyup video için analiz üretir.

Ekran görüntüsü gerekmez. Kullanıcı ayrıca ekran görüntüsü gönderdiyse onlardaki yorumlar da sayılır.
Trendyol ve Amazon gibi otomatik okumaya kapalı siteler atlanır; robots.txt kurallarına uyulur.
"""
import logging
from datetime import date

import anthropic

import ayarlar as A
from analiz import SEMA, AnalizHatasi, _json_cikar, _resim_parcasi, dogrula
from urun_avi import _son_metin, _tum_metin

log = logging.getLogger("arastirma")

SISTEM = """Sen "{kanal}" adlı Türkçe bir YouTube Shorts ve TikTok kanalının yorum analistisin.
Görevin: verilen ürünün alıcı yorumlarını internette bulup okumak, saymak, özetlemek ve 30 saniyelik bir video senaryosu yazmak.

Nerede ara (Türkiye):
- Hepsiburada ürün sayfası ve değerlendirmeleri (fiyat, puan ve toplam değerlendirme sayısını buradan al)
- Şikâyetvar'daki ürün ya da model şikâyetleri
- Ekşi Sözlük başlıkları, DonanımHaber ve Donanım Arşivi forumları
- Akakçe kullanıcı yorumları ve bağımsız inceleme yazıları
Trendyol ve Amazon otomatik okumaya kapalı; denersen ve açılmazsa zaman kaybetme, diğer kaynaklara geç.
Açılmayan bir sayfayı başka yollarla (önbellek, kopya site) okumaya çalışma.

Kesin kurallar:
1. Hiçbir bilgi uydurma. Sadece gerçekten açıp okuduğun sayfalardaki yorumları say. Fiyat, puan veya toplam yorum sayısı bulunamazsa boş bırak ve "uyarilar"a yaz.
2. Aynı modele odaklan. Markanın başka modelleriyle ilgili yorumları sayma; model özelinde yeterli yorum yoksa bunu "uyarilar"a yaz.
3. "okunan_yorum" = tüm kaynaklarda metnini okuduğun yorum, şikâyet ve entry sayısı. "urun_yorumu" = bunlardan ürünün kendisini anlatanlar (kargo, satıcı ilgisi, teşekkür gibi bilgi vermeyenler hariç; kırık/eksik/taklit gelmesi dahil). Övgü ve şikâyet sayıları urun_yorumu'nu geçemez.
4. Şikâyet siteleri doğası gereği olumsuzdur. Hükmü yalnızca şikâyet sayısına dayandırma; pazaryeri puanı ve yorumlarıyla dengele. Senaryoda rakamın hangi kaynaktan geldiğini söyle (ör. "Hepsiburada'da okuduğum 20 yorumun 7'si", "şikâyet sitelerinde en çok tekrar eden konu").
5. Ürünü sen kullanmadın: "denedim", "kullandım", "test ettim" gibi ifadeler yasak.
6. Yorum yazanların adlarını kullanma, cümlelerini birebir alıntılama; kendi cümlelerinle özetle.
   "Taklit", "orijinal değil" gibi iddiaları alıcıların görüşü olarak aktar. Senaryoda ve ekranda satıcı adı verme, satıcıyı suçlama. Bu tür şikâyetler çoksa hükümde "resmi ya da yetkili mağazadan al" uyarısı ver.
7. Sağlık, tedavi veya güvenlik iddiası yapma.
8. Hüküm: şikâyetler ürünün temel işlevini bozuyorsa ve pazaryeri yorumlarında da sık geçiyorsa "ALINMAZ"; övgüler açıkça baskınsa "ALINIR"; karışıksa "DİKKATLİ AL".
9. Senaryo konuşma dilinde, kısa cümlelerle, toplam 45-60 kelime (20-28 saniye). Fiyatı ve puanı sesli okuma; ekranda etiket olarak görünür. Bağlam bölümü tek kısa cümle: kaç yorum okunduğu ve hangi sitelerden; sonuna "Hüküm sonda." ekle.
   Dürüst oran: azınlıktaki bir bulguya "çoğu", "herkes" deme; sayıyı söyle. Ürünü anlatan yorum 30'dan azsa hükmü temkinli kur.
   Kapanış: "Sıradaki ürün ne olsun? Yorumlara yaz." gibi tek cümle ve "Yorum dosyası #N".
   Açılış (acilis ve ekran_acilis) okuduklarındaki EN ŞAŞIRTICI somut bulgudur ve bir rakam içerir. Hükmü açılışta söyleme; hüküm sona kalsın.
   Övülenler ürünün kendi özelliklerinden seçilir; "orijinal çıktı", "hızlı geldi" övgü sayılmaz. Aynı konu hem övgüde hem şikâyette olmasın.
   "urun_gorseli" alanı için: kullanıcı ekran görüntüsü gönderdiyse ürün fotoğrafının yerini yaz, göndermediyse null.
10. Araştırma bitince yalnızca istenen JSON'u döndür, başka hiçbir şey yazma."""

ISTEK = """Ürün: {urun}
Bugün {tarih}. Bu video "Yorum dosyası #{no}" olacak.
{gorsel_notu}
Önce bu ürünün yorumlarını yukarıdaki kaynaklarda ara ve oku (en az 25 ürün yorumu hedefle).
Sonra şu yapıda JSON döndür. Ek olarak "kaynaklar" alanına okuduğun kaynakları yaz:
"kaynaklar": [{{"ad": "Hepsiburada", "okunan": 0, "adres": "sayfa adresi"}}]

"""

GORSEL_NOTU = ("Kullanıcı ayrıca {n} ekran görüntüsü gönderdi (ilk görüntü ürün sayfası olabilir). Onlardaki yorumları da "
               "oku ve say; kaynak adı olarak \"ekran görüntüsü\" yaz. Ürün adı görüntüyle uyuşmuyorsa görüntüdekini esas al.")

DUZELT = ("Bulduklarına göre analizi şimdi yalnızca istenen JSON nesnesi olarak ver. Yeni arama yapma, "
          "metinleri kısa tut, JSON dışında hiçbir şey yazma.")


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
    """Ürünü web'de araştırır; video için doğrulanmış analiz sözlüğü döndürür."""
    if not A.ANTHROPIC_API_KEY:
        raise AnalizHatasi("Anthropic anahtarı yok. /anthropic ANAHTAR ile gir.")
    gorseller = list(gorseller)[:20]
    istek = ISTEK.format(urun=urun, tarih=date.today().strftime("%d.%m.%Y"), no=no,
                         gorsel_notu=GORSEL_NOTU.format(n=len(gorseller)) if gorseller else "")
    icerik = [_resim_parcasi(g) for g in gorseller]
    icerik.append({"type": "text", "text": istek + SEMA.format(no=no)})
    sistem = SISTEM.replace("{kanal}", A.KANAL_ADI)
    istemci = anthropic.Anthropic(api_key=A.ANTHROPIC_API_KEY)
    try:
        ham = _calistir(istemci, sistem, icerik, _araclar(fetch=True))
    except anthropic.BadRequestError as hata:
        if "web_fetch" not in str(hata):
            raise
        log.warning("Sayfa okuma aracı kullanılamadı, yalnızca aramayla devam: %s", hata)
        ham = _calistir(istemci, sistem, icerik, _araclar(fetch=False))
    kaynaklar = [k for k in (ham.get("kaynaklar") or []) if isinstance(k, dict) and k.get("ad")]
    try:
        veri = dogrula(ham, no)
    except AnalizHatasi as hata:
        if "ürünü anlatıyor" not in str(hata):
            raise
        raise AnalizHatasi(
            f"İnternette bu model için yeterli ürün yorumu bulunamadı ({hata.args[0].split(' (')[0]}). "
            "Ürün adını biraz daha genel yaz ya da birkaç yorum ekran görüntüsü gönderip tekrar dene.") from hata
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
