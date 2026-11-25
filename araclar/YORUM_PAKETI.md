# Yorum paketi (yorumlar.json)

Sunucu Trendyol'a erişemiyor (Cloudflare veri merkezi isteklerini engelliyor). Bu yüzden iki yol var:

1. **Telefon (her zaman):** Kullanıcı yorumları "En yeni" sıralamasıyla açıp ekran görüntüsü ya da ekran kaydı gönderir, `/hazirla` yazar.
2. **Bilgisayar açıkken (Claude):** Kullanıcı Claude'a Trendyol linkini verir. Claude, kullanıcının Chrome'unda (Claude in Chrome)
   `araclar/trendyol_okuyucu.js` ile ürün bilgisini ve en yeni 150-200 yorumu okur, aşağıdaki paketi yazar ve kullanıcıya dosya olarak
   gönderir. Kullanıcı dosyayı bota iletir (Telegram'da dosya olarak), bot "Yorum paketi alındı" der; `/hazirla` ile video çıkar.

Kurallar: yorum yazanların adı pakete girmez; sayfayı insan hızında kaydır; en yeni sıralamayı kullan (örneklem taraflı olmasın).

```json
{
  "tur": "yorum_paketi",
  "surum": 1,
  "kaynak": "Trendyol",
  "siralama": "en yeni",
  "tarih": "25.11.2026",
  "adres": "https://www.trendyol.com/...-p-123",
  "urun": {
    "ad": "Marka Model",
    "kategori": "kulaklık",
    "fiyat": "649 TL",
    "puan": "4,4",
    "toplam_degerlendirme": "10234",
    "fotograflar": ["https://cdn.dsmcdn.com/....jpg"]
  },
  "yorumlar": [
    {"tarih": "24 Kasım 2026", "yildiz": 5, "metin": "yorum metni", "satici": "satıcı adı"}
  ]
}
```

Bot paketi `analiz.analiz_metinden` ile okur: yorumlar metin olarak konulara ayrılır, sayımı kod yapar, metin bu sayılarla yazılır.
Paket `calisma/dosya_NNN/yorum_paketi.json` olarak saklanır; `/tekrar NNN tam` paketten yeniden analiz eder.
