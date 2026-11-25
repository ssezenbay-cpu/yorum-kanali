// Trendyol yorum paketi okuyucusu: Claude, kullanıcının kendi Chrome'unda (Claude in Chrome) çalıştırır.
// Sunucu Trendyol'a erişemediği için yorumlar kullanıcının tarayıcısında, bir insanın göreceği sayfadan okunur.
// Kullanım (javascript_tool ile, sayfa açıkken):
//   1) Ürün sayfasında:   await urunBilgisi()
//   2) /yorumlar sayfasında, sıralama "En Yeni" seçildikten sonra:   await yorumlariOku(200)
// Çıktılar birleştirilip yorum paketi (yorumlar.json) yapılır; biçim için araclar/YORUM_PAKETI.md.
// Not: Trendyol sayfa yapısını değiştirirse seçiciler güncellenmeli (son kontrol: 25.11.2026, .review yapısı).

async function urunBilgisi() {
  const ld = [...document.querySelectorAll('script[type="application/ld+json"]')]
    .map(s => { try { return JSON.parse(s.textContent); } catch (e) { return null; } })
    .flat().find(x => x && (x['@type'] === 'Product' || (Array.isArray(x['@type']) && x['@type'].includes('Product'))));
  const resimler = ld ? [].concat(ld.image || []).map(r => typeof r === 'string' ? r : r.url).filter(Boolean) : [];
  const teklif = ld && [].concat(ld.offers || [])[0];
  const puan = ld && ld.aggregateRating;
  return {
    ad: ld ? `${(ld.brand && (ld.brand.name || ld.brand)) || ''} ${ld.name || ''}`.trim() : document.title,
    fiyat: teklif && teklif.price ? `${Number(teklif.price).toLocaleString('tr-TR')} TL` : '',
    puan: puan && puan.ratingValue ? String(puan.ratingValue).replace('.', ',') : '',
    toplam_degerlendirme: puan ? String(puan.reviewCount || puan.ratingCount || '') : '',
    fotograflar: resimler.slice(0, 4),
    adres: location.href.split('?')[0],
  };
}

async function yorumlariOku(hedef = 200, enFazlaSure = 120000) {
  const bekle = ms => new Promise(r => setTimeout(r, ms));
  const basla = Date.now();
  let onceki = -1, ayni = 0;
  while (document.querySelectorAll('.review').length < hedef && Date.now() - basla < enFazlaSure) {
    window.scrollTo(0, document.body.scrollHeight);
    await bekle(900 + Math.random() * 600);  // insan hızında kaydır, siteyi yorma
    const n = document.querySelectorAll('.review').length;
    ayni = n === onceki ? ayni + 1 : 0;
    onceki = n;
    if (ayni >= 5) break;  // daha fazla yorum yüklenmiyor
  }
  document.querySelectorAll('.review .read-more').forEach(b => { try { b.click(); } catch (e) {} });
  await bekle(800);
  return [...document.querySelectorAll('.review')].slice(0, hedef).map(e => {
    const metin = [...e.querySelectorAll('.review-comment span')].map(s => s.innerText).join(' ')
      .replace(/Devamını Oku/g, '').replace(/\s+/g, ' ').trim();
    const tarih = (e.querySelector('.detail-item.date') || {}).innerText || '';
    const yildiz = e.querySelectorAll('.star-rating-full-star').length || null;
    const satici = ((e.querySelector('.comment-seller-info') || {}).innerText || '')
      .replace(/satıcısından alındı/i, '').trim();
    return { tarih: tarih.trim(), yildiz: yildiz && yildiz <= 5 ? yildiz : null, metin, satici };  // isim alınmaz
  }).filter(y => y.metin);
}
