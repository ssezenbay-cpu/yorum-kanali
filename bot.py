"""Telegram botu: ekran görüntülerini alır, videoyu üretir ve sana geri gönderir."""
import asyncio
import logging
import os
import shutil
import subprocess
import sys
import zipfile

import requests
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import InvalidToken, NetworkError, TimedOut
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import ayarlar as A

import urun_avi
from analiz import ROLLER, AnalizHatasi, analiz_et, anthropic_dogrula
from demo import demo_uret
from ayarlar import (CALISMA, CIKTI, GELEN, KOK, TELEGRAM_PROXY, TELEGRAM_TOKEN, eksik_ayarlar,
                     maskele, no_kaydet, sonraki_no)
from ses import SesHatasi, sesleri_listele, seslendir
from veriler import rapor_metni, sonuc_kaydet, video_kaydet
from video import videoyu_kurgula

try:
    from zoneinfo import ZoneInfo
    TR = ZoneInfo("Europe/Istanbul")
except Exception:  # noqa: BLE001 - saat dilimi verisi yoksa sabit +3
    TR = timezone(timedelta(hours=3))

KAYIT_DOSYASI = CALISMA / "bot.log"
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO,
    handlers=[logging.StreamHandler(),
              RotatingFileHandler(KAYIT_DOSYASI, maxBytes=500_000, backupCount=1, encoding="utf-8")])
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("bot")

YARDIM = (
    "Nasıl kullanılır:\n"
    "1. Ürün sayfasının ekran görüntüsünü gönder (ürün adı, fiyat ve puan görünsün).\n"
    "2. Yorumların ekran görüntülerini gönder: en az 30 yorum, bir kısmı 1-2 yıldızlılardan.\n"
    "3. Hepsini gönderince /hazirla yaz.\n\n"
    "Diğer komutlar:\n"
    "/durum – kaç görüntü gönderdiğini gösterir\n"
    "/iptal – gönderilen görüntüleri siler\n"
    "/oneri – internette araştırıp 5 ürün adayı önerir (her pazartesi 10:00'da kendiliğinden gelir)\n"
    "/sonuc NO İZLENME TIKLAMA [KAZANÇ] – videonun sonucunu kaydeder (ör. /sonuc 3 12000 40 350)\n"
    "/rapor – hangi ürün grubunun daha iyi gittiğini gösterir\n"
    "/demo – API kullanmadan sessiz örnek video yapar\n\n"
    "Ayarlar:\n"
    "/ayarlar – hangi ayarların tamam olduğunu gösterir\n"
    "/elevenlabs ANAHTAR – ElevenLabs anahtarını kaydeder, sesini bulur\n"
    "/ses – kullanılacak ses klonunu seçtirir\n"
    "/anthropic ANAHTAR – Anthropic anahtarını kaydeder\n"
    "/kanal AD – videolardaki kanal adını değiştirir\n\n"
    "Bakım:\n"
    "/guncelle – GitHub'dan son sürümü alıp kendini günceller\n"
    "/kayit – botun son kayıtlarını gösterir\n"
    "/yeniden – botu yeniden başlatır"
)

KONTROL = (
    "Yüklemeden önce 2 dakikalık kontrol:\n"
    "☐ Ürün adı ve fiyat doğru mu?\n"
    "☐ Hüküm yorumlarla uyumlu mu?\n"
    "☐ 'Denedim' gibi yanlış bir ifade var mı?\n"
    "☐ YouTube'da 'değiştirilmiş veya sentetik içerik' kutusunu işaretle.\n"
    "☐ Ürün linkini link sayfana bu dosya numarasıyla ekle."
)


def yetkili(update: Update) -> bool:
    return bool(A.IZINLI_KULLANICI_ID) and str(update.effective_user.id) == A.IZINLI_KULLANICI_ID


def oturum(chat_id):
    klasor = GELEN / str(chat_id)
    klasor.mkdir(parents=True, exist_ok=True)
    return klasor


def resimler(chat_id):
    return sorted(p for p in oturum(chat_id).iterdir() if p.is_file())


async def basla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not A.IZINLI_KULLANICI_ID:
        A.kaydet("IZINLI_KULLANICI_ID", update.effective_user.id)
        log.info("Bot sahibi kaydedildi: %s", update.effective_user.id)
        await update.message.reply_text("Bot artık sadece sana çalışıyor.")
    if not yetkili(update):
        return
    await update.message.reply_text("Hazırım.\n\n" + YARDIM)
    eksik = eksik_ayarlar()
    if eksik:
        await update.message.reply_text(ayar_ozeti())


async def demo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    durum_mesaji = await update.message.reply_text("Örnek video hazırlanıyor (sessiz, API kullanmaz)...")
    try:
        yol = await asyncio.to_thread(demo_uret)
    except Exception as hata:  # noqa: BLE001 - kullanıcıya gösterilir
        log.exception("Demo üretilemedi")
        await durum_mesaji.edit_text(f"Demo üretilemedi: {hata}")
        return
    with open(yol, "rb") as dosya:
        await update.message.reply_video(dosya, caption="Demo video", supports_streaming=True,
                                         read_timeout=180, write_timeout=180)
    await durum_mesaji.delete()


def ayar_ozeti():
    satirlar = [
        "Ayarlar:",
        f"{'✅' if A.ANTHROPIC_API_KEY else '❌'} Anthropic anahtarı: {maskele(A.ANTHROPIC_API_KEY)}",
        f"{'✅' if A.ELEVENLABS_API_KEY else '❌'} ElevenLabs anahtarı: {maskele(A.ELEVENLABS_API_KEY)}",
        f"{'✅' if A.ELEVENLABS_VOICE_ID else '❌'} Ses: "
        f"{A._al('ELEVENLABS_SES_ADI') or A.ELEVENLABS_VOICE_ID or 'seçilmedi'}",
        f"Kanal adı: {A.KANAL_ADI}",
    ]
    if not A.ELEVENLABS_API_KEY:
        satirlar.append("\nSıradaki adım: /elevenlabs ANAHTAR yaz (ElevenLabs → Developers → API Keys).")
    elif not A.ELEVENLABS_VOICE_ID:
        satirlar.append("\nSıradaki adım: /ses yazıp sesini seç.")
    elif not A.ANTHROPIC_API_KEY:
        satirlar.append("\nSıradaki adım: /anthropic ANAHTAR yaz.")
    else:
        satirlar.append("\nHer şey hazır. Ekran görüntülerini gönderip /hazirla yazabilirsin.")
    return "\n".join(satirlar)


async def _anahtar_mesajini_sil(update: Update):
    try:
        await update.message.delete()
    except Exception:  # noqa: BLE001 - silinemezse önemli değil
        pass


async def ayarlar_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if yetkili(update):
        await update.message.reply_text(ayar_ozeti())


async def anthropic_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    if not context.args:
        await update.message.reply_text("Kullanım: /anthropic ANAHTAR")
        return
    anahtar = context.args[0].strip("`\"'")
    await _anahtar_mesajini_sil(update)
    try:
        gecerli = await asyncio.to_thread(anthropic_dogrula, anahtar)
    except Exception as hata:  # noqa: BLE001
        await update.effective_chat.send_message(f"Anahtar kontrol edilemedi: {hata}")
        return
    if not gecerli:
        await update.effective_chat.send_message("Bu Anthropic anahtarı geçersiz. Kaydetmedim.")
        return
    A.kaydet("ANTHROPIC_API_KEY", anahtar)
    await update.effective_chat.send_message(
        f"Anthropic anahtarı kaydedildi ({maskele(anahtar)}). Güvenlik için mesajını sildim.")


def _ses_dugmeleri(sesler):
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(ad, callback_data=f"ses:{sid}")] for ad, sid in sesler[:20]])


async def _sesleri_goster(chat, anahtar):
    try:
        sesler = await asyncio.to_thread(sesleri_listele, anahtar)
    except SesHatasi as hata:
        await chat.send_message(str(hata))
        return
    if not sesler:
        await chat.send_message(
            "Hesabında henüz klon ses yok. ElevenLabs'te sesini klonla (Voices → Instant Voice Clone), "
            "sonra burada /ses yaz.")
    elif len(sesler) == 1:
        ad, sid = sesler[0]
        A.kaydet("ELEVENLABS_VOICE_ID", sid)
        A.kaydet("ELEVENLABS_SES_ADI", ad)
        await chat.send_message(f"Ses seçildi: {ad}\n\n" + ayar_ozeti())
    else:
        await chat.send_message("Hangi sesi kullanayım?", reply_markup=_ses_dugmeleri(sesler))


async def elevenlabs_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    if not context.args:
        await update.message.reply_text("Kullanım: /elevenlabs ANAHTAR")
        return
    anahtar = context.args[0].strip("`\"'")
    await _anahtar_mesajini_sil(update)
    try:
        await asyncio.to_thread(sesleri_listele, anahtar)
    except SesHatasi as hata:
        if "geçersiz" in str(hata):
            await update.effective_chat.send_message(str(hata) + " Kaydetmedim.")
            return
    A.kaydet("ELEVENLABS_API_KEY", anahtar)
    await update.effective_chat.send_message(
        f"ElevenLabs anahtarı kaydedildi ({maskele(anahtar)}). Güvenlik için mesajını sildim.")
    await _sesleri_goster(update.effective_chat, anahtar)


async def ses_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    if context.args:
        A.kaydet("ELEVENLABS_VOICE_ID", context.args[0].strip())
        A.kaydet("ELEVENLABS_SES_ADI", "")
        await update.message.reply_text("Ses ID'si kaydedildi.\n\n" + ayar_ozeti())
        return
    if not A.ELEVENLABS_API_KEY:
        await update.message.reply_text("Önce /elevenlabs ANAHTAR ile ElevenLabs anahtarını gir.")
        return
    await _sesleri_goster(update.effective_chat, A.ELEVENLABS_API_KEY)


async def ses_secildi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorgu = update.callback_query
    if not yetkili(update):
        await sorgu.answer()
        return
    sid = sorgu.data.split(":", 1)[1]
    ad = next((b.text for satir in sorgu.message.reply_markup.inline_keyboard for b in satir
               if b.callback_data == sorgu.data), sid)
    A.kaydet("ELEVENLABS_VOICE_ID", sid)
    A.kaydet("ELEVENLABS_SES_ADI", ad)
    await sorgu.answer("Kaydedildi")
    await sorgu.edit_message_text(f"Ses seçildi: {ad}\n\n" + ayar_ozeti())


async def kanal_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    if not context.args:
        await update.message.reply_text(f"Şu anki kanal adı: {A.KANAL_ADI}\nDeğiştirmek için: /kanal YENİ AD")
        return
    A.kaydet("KANAL_ADI", " ".join(context.args))
    await update.message.reply_text(f"Kanal adı: {A.KANAL_ADI}")


async def kayit_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    try:
        satirlar = KAYIT_DOSYASI.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
    except FileNotFoundError:
        satirlar = ["Kayıt yok."]
    await update.message.reply_text("\n".join(satirlar)[-3900:] or "Kayıt boş.")


def _yeniden_baslat(context: ContextTypes.DEFAULT_TYPE):
    context.application.bot_data["yeniden_basla"] = True
    context.application.stop_running()


async def yeniden_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    await update.message.reply_text("Yeniden başlatıyorum, 15 saniye sonra /durum yazabilirsin.")
    _yeniden_baslat(context)


GUNCELLENEBILIR = {"requirements.txt", "sunucu_kurulum.sh"}


def _guncellemeyi_uygula(zip_yolu):
    """Zip'teki program dosyalarını kontrol edip yerine koyar. Değişen dosyaların listesini döndürür."""
    yeni = {}
    with zipfile.ZipFile(zip_yolu) as arsiv:
        for bilgi in arsiv.infolist():
            if bilgi.is_dir():
                continue
            ad = bilgi.filename.replace("\\", "/").rsplit("/", 1)[-1]
            if ad.endswith(".py") or ad in GUNCELLENEBILIR:
                if bilgi.file_size > 2_000_000:
                    raise ValueError(f"{ad} çok büyük.")
                yeni[ad] = arsiv.read(bilgi)
    if "bot.py" not in yeni:
        raise ValueError("Bu zip'te bot.py yok; doğru dosyayı gönderdiğinden emin ol.")
    for ad, icerik in yeni.items():
        if ad.endswith(".py"):
            compile(icerik.decode("utf-8"), ad, "exec")  # yazım hatası varsa burada durur
    degisen = [ad for ad, icerik in yeni.items()
               if not (KOK / ad).exists() or (KOK / ad).read_bytes() != icerik]
    if not degisen:
        return []
    yedek = CALISMA / "yedek"
    shutil.rmtree(yedek, ignore_errors=True)
    yedek.mkdir(parents=True)
    for ad in degisen:
        if (KOK / ad).exists():
            shutil.copy2(KOK / ad, yedek / ad)
        (KOK / ad).write_bytes(yeni[ad])
    try:
        if "requirements.txt" in degisen:
            subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                            "-r", str(KOK / "requirements.txt")], check=True, capture_output=True,
                           text=True, timeout=600)
        sonuc = subprocess.run([sys.executable, "-c", "import bot"], cwd=KOK, capture_output=True,
                               text=True, timeout=120)
        if sonuc.returncode != 0:
            raise RuntimeError(sonuc.stderr.strip().splitlines()[-1] if sonuc.stderr else "bilinmeyen hata")
    except Exception:
        for ad in degisen:  # eski sürüme dön
            if (yedek / ad).exists():
                shutil.copy2(yedek / ad, KOK / ad)
            else:
                (KOK / ad).unlink(missing_ok=True)
        raise
    return degisen


def _githubdan_indir(hedef):
    """Depodaki son sürümü zip olarak indirir; sürüm bilgisini döndürür."""
    depo, dal = A.GITHUB_DEPO, A.GITHUB_DAL
    yanit = requests.get(f"https://codeload.github.com/{depo}/zip/refs/heads/{dal}", timeout=90)
    if yanit.status_code == 404:
        raise RuntimeError(f"GitHub'da {depo} deposu ya da '{dal}' dalı bulunamadı.")
    yanit.raise_for_status()
    hedef.write_bytes(yanit.content)
    try:
        son = requests.get(f"https://api.github.com/repos/{depo}/commits/{dal}", timeout=20).json()
        return f"{son['sha'][:7]} – {son['commit']['message'].splitlines()[0][:90]}"
    except Exception:  # noqa: BLE001 - sürüm bilgisi şart değil
        return ""


async def _guncelle(update: Update, context: ContextTypes.DEFAULT_TYPE, indir):
    mesaj = await update.message.reply_text("Güncelleme kontrol ediliyor…")
    zip_yolu = CALISMA / "guncelleme.zip"
    try:
        surum = await indir(zip_yolu)
        degisen = await asyncio.to_thread(_guncellemeyi_uygula, zip_yolu)
    except Exception as hata:  # noqa: BLE001
        log.exception("Güncelleme uygulanamadı")
        await mesaj.edit_text(f"Güncelleme uygulanmadı, eski sürüm çalışmaya devam ediyor.\nSebep: {hata}")
        return
    finally:
        zip_yolu.unlink(missing_ok=True)
    surum_satiri = f"\nSürüm: {surum}" if surum else ""
    if not degisen:
        await mesaj.edit_text("Zaten en son sürüm çalışıyor." + surum_satiri)
        return
    log.info("Güncellendi: %s %s", ", ".join(degisen), surum)
    await mesaj.edit_text(f"Güncellendi: {', '.join(degisen)}{surum_satiri}\n"
                          "Yeniden başlatıyorum; 15 saniye sonra /yardim yaz.")
    _yeniden_baslat(context)


async def guncelle_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/guncelle: GitHub'daki son sürümü kurar."""
    if not yetkili(update):
        return

    async def indir(hedef):
        return await asyncio.to_thread(_githubdan_indir, hedef)

    await _guncelle(update, context, indir)


async def guncelleme_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sohbete gönderilen .zip dosyasıyla güncelleme (yedek yol)."""
    if not yetkili(update):
        return

    async def indir(hedef):
        dosya = await update.message.document.get_file()
        await dosya.download_to_drive(hedef)
        return ""

    await _guncelle(update, context, indir)


async def hata_yakala(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Hata", exc_info=context.error)
    if isinstance(context.error, (NetworkError, TimedOut)) or not A.IZINLI_KULLANICI_ID:
        return
    try:
        await context.bot.send_message(int(A.IZINLI_KULLANICI_ID),
                                       f"Bir hata oldu: {type(context.error).__name__}: {context.error}"[:800])
    except Exception:  # noqa: BLE001
        pass


async def yardim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if yetkili(update):
        await update.message.reply_text(YARDIM)


async def resim_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    mesaj = update.message
    if mesaj.photo:
        dosya, uzanti = await mesaj.photo[-1].get_file(), ".jpg"
    elif mesaj.document and (mesaj.document.mime_type or "").startswith("image/"):
        dosya = await mesaj.document.get_file()
        uzanti = "." + (mesaj.document.file_name or "x.jpg").rsplit(".", 1)[-1].lower()
    else:
        return
    yol = oturum(mesaj.chat_id) / f"{mesaj.message_id:010d}{uzanti}"
    await dosya.download_to_drive(yol)
    if len(resimler(mesaj.chat_id)) == 1:
        await mesaj.reply_text("İlk görüntü alındı. Hepsini gönderince /hazirla yaz.")


async def durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if yetkili(update):
        n = len(resimler(update.effective_chat.id))
        await update.message.reply_text(f"{n} görüntü bekliyor. Sıradaki dosya numarası: #{sonraki_no()}")


async def iptal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if yetkili(update):
        shutil.rmtree(oturum(update.effective_chat.id), ignore_errors=True)
        await update.message.reply_text("Görüntüler silindi. Yeni ürün için baştan gönderebilirsin.")


async def oneri(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    bekle = await update.message.reply_text("İnternette araştırıyorum, 1-3 dakika sürebilir…")
    try:
        metin = await asyncio.to_thread(urun_avi.haftalik_mesaj)
    except Exception as hata:  # noqa: BLE001 - kullanıcıya anlaşılır mesaj
        log.exception("öneri hatası")
        await bekle.edit_text(f"Öneri alınamadı: {hata}")
        return
    await bekle.delete()
    await _html_gonder(context.bot, update.effective_chat.id, metin)


async def _html_gonder(bot, chat_id, metin):
    try:
        await bot.send_message(chat_id, metin, parse_mode="HTML", disable_web_page_preview=True)
    except Exception:  # noqa: BLE001 - biçim bozulursa düz metin gönder
        import re as _re
        await bot.send_message(chat_id, _re.sub(r"<[^>]+>", "", metin), disable_web_page_preview=True)


def _sayi(metin):
    metin = metin.lower().replace(".", "").replace(",", "")
    carpan = 1000 if metin.endswith("k") else 1
    return int(float(metin.rstrip("k")) * carpan)


async def sonuc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    try:
        no = int(context.args[0].lstrip("#"))
        izlenme, tiklama = _sayi(context.args[1]), _sayi(context.args[2])
        kazanc = _sayi(context.args[3]) if len(context.args) > 3 else None
    except (IndexError, ValueError):
        await update.message.reply_text(
            "Kullanım: /sonuc DOSYA_NO İZLENME TIKLAMA [KAZANÇ]\n"
            "Örnek: /sonuc 3 12000 40 350\n"
            "İzlenme: TikTok + YouTube + Instagram toplamı. Tıklama ve kazanç: satış ortaklığı panelinden.")
        return
    kayit = sonuc_kaydet(no, izlenme, tiklama, kazanc)
    await update.message.reply_text(
        f"Kaydedildi: #{no} {kayit.get('urun') or ''}\n"
        f"{izlenme} izlenme, {tiklama} tıklama" + (f", {kazanc} TL" if kazanc is not None else "")
        + "\n\nGenel durum için /rapor yaz.")


async def rapor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if yetkili(update):
        await update.message.reply_text(rapor_metni())


def sonraki_pazartesi(simdi, saat=10):
    hedef = simdi.replace(hour=saat, minute=0, second=0, microsecond=0) + timedelta(days=(-simdi.weekday()) % 7)
    if hedef <= simdi:
        hedef += timedelta(days=7)
    return hedef


async def _haftalik_dongu(uygulama):
    while True:
        simdi = datetime.now(TR)
        hedef = sonraki_pazartesi(simdi)
        log.info("Sıradaki haftalık ürün listesi: %s", hedef.strftime("%d.%m.%Y %H:%M"))
        await asyncio.sleep((hedef - simdi).total_seconds())
        if not (A.IZINLI_KULLANICI_ID and A.ANTHROPIC_API_KEY):
            continue
        try:
            metin = await asyncio.to_thread(urun_avi.haftalik_mesaj)
            await _html_gonder(uygulama.bot, int(A.IZINLI_KULLANICI_ID), metin)
        except Exception as hata:  # noqa: BLE001
            log.exception("Haftalık liste gönderilemedi")
            try:
                await uygulama.bot.send_message(int(A.IZINLI_KULLANICI_ID),
                                                f"Haftalık ürün listesi hazırlanamadı: {hata}\n/oneri ile tekrar dene.")
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(120)


def paylasim_metni(veri, no):
    etiketler = " ".join("#" + e for e in veri.get("etiketler", []) if e)
    parcalar = [
        f"BAŞLIK:\n{veri['baslik']}",
        f"AÇIKLAMA:\n{veri.get('aciklama', '').strip()}\n\n"
        f"Ürün linki profilde: Yorum dosyası #{no}. Profildeki link satış ortaklığı linkidir. #işbirliği\n"
        f"{etiketler}",
    ]
    if veri.get("satici"):
        parcalar.append(f"SATICI: {veri['satici']}\nLinki koyarken bu satıcının ürününü seçtiğinden emin ol.")
    if veri.get("uyarilar"):
        parcalar.append("⚠️ DİKKAT:\n" + "\n".join("• " + u for u in veri["uyarilar"]))
    parcalar.append(KONTROL)
    return "\n\n".join(parcalar)


async def hazirla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    chat_id = update.effective_chat.id
    liste = resimler(chat_id)
    if len(liste) < 2:
        await update.message.reply_text(
            "En az 2 görüntü gönder: ürün sayfası ve yorumlar. İlk görüntü ürün sayfası olmalı.")
        return
    no = sonraki_no()
    klasor = CALISMA / f"dosya_{no:03d}"
    klasor.mkdir(parents=True, exist_ok=True)
    durum_mesaji = await update.message.reply_text(f"1/3 Yorumları okuyorum… ({len(liste)} görüntü)")
    try:
        veri = await asyncio.to_thread(analiz_et, liste, no)
        await durum_mesaji.edit_text(
            f"2/3 Seslendiriyorum… ({veri['okunan_yorum']} yorum okundu, {veri['urun_yorumu']} tanesi ürünü "
            f"anlatıyor; hüküm: {veri['hukum']})")
        metin = " ".join(veri["senaryo"][r] for r in ROLLER)
        ses_yolu = klasor / "ses.mp3"
        hiz = await asyncio.to_thread(seslendir, metin, ses_yolu)
        await durum_mesaji.edit_text("3/3 Videoyu kurguluyorum… (1-2 dakika)")
        cikti = CIKTI / f"yorum_dosyasi_{no:03d}.mp4"
        await asyncio.to_thread(videoyu_kurgula, veri, liste, ses_yolu, hiz, no, cikti)
    except (AnalizHatasi, SesHatasi) as hata:
        await durum_mesaji.edit_text(f"Olmadı: {hata}\n\nGörüntüler duruyor. Ekleme yapıp /hazirla ile tekrar deneyebilir ya da /iptal ile silebilirsin.")
        return
    except Exception as hata:  # noqa: BLE001
        log.exception("üretim hatası")
        await durum_mesaji.edit_text(f"Beklenmeyen hata: {hata}\n\nGörüntüler duruyor; /hazirla ile tekrar dene.")
        return

    no_kaydet(no)
    video_kaydet(no, veri)
    for kaynak in liste:
        shutil.copy2(kaynak, klasor / kaynak.name)
    (klasor / "senaryo.txt").write_text(metin, encoding="utf-8")
    await durum_mesaji.edit_text(f"Hazır: Yorum dosyası #{no}")
    with open(cikti, "rb") as dosya:
        await update.message.reply_video(
            dosya, caption=f"Yorum dosyası #{no}", supports_streaming=True,
            read_timeout=180, write_timeout=180)
    await update.message.reply_text(paylasim_metni(veri, no))
    shutil.rmtree(oturum(chat_id), ignore_errors=True)


async def _baglandi(uygulama):
    ben = await uygulama.bot.get_me()
    print(f"Bot çalışıyor: @{ben.username}")
    uygulama.bot_data["haftalik"] = asyncio.create_task(_haftalik_dongu(uygulama))


async def _kapaniyor(uygulama):
    gorev = uygulama.bot_data.get("haftalik")
    if gorev:
        gorev.cancel()


def main():
    eksik = eksik_ayarlar()
    if eksik:
        print("Eksik ayarlar var. .env dosyasında şunları doldur:")
        for ad in eksik:
            print("  -", ad)
        if "TELEGRAM_TOKEN" in eksik:
            return
        print("Bot yine de açılıyor; eksikleri Telegram'dan /ayarlar ile tamamlayabilirsin.\n")
    kurucu = (Application.builder().token(TELEGRAM_TOKEN)
              .connect_timeout(30).read_timeout(60).write_timeout(180).pool_timeout(30)
              .get_updates_connect_timeout(30).get_updates_read_timeout(60))
    if TELEGRAM_PROXY:
        kurucu = kurucu.proxy(TELEGRAM_PROXY).get_updates_proxy(TELEGRAM_PROXY)
    uygulama = kurucu.post_init(_baglandi).post_shutdown(_kapaniyor).build()
    uygulama.add_handler(CommandHandler("start", basla))
    uygulama.add_handler(CommandHandler(["yardim", "help"], yardim))
    uygulama.add_handler(CommandHandler("durum", durum))
    uygulama.add_handler(CommandHandler("iptal", iptal))
    uygulama.add_handler(CommandHandler("oneri", oneri))
    uygulama.add_handler(CommandHandler("hazirla", hazirla))
    uygulama.add_handler(CommandHandler("demo", demo))
    uygulama.add_handler(CommandHandler("sonuc", sonuc))
    uygulama.add_handler(CommandHandler("rapor", rapor))
    uygulama.add_handler(CommandHandler("ayarlar", ayarlar_komutu))
    uygulama.add_handler(CommandHandler("anthropic", anthropic_komutu))
    uygulama.add_handler(CommandHandler("elevenlabs", elevenlabs_komutu))
    uygulama.add_handler(CommandHandler("ses", ses_komutu))
    uygulama.add_handler(CallbackQueryHandler(ses_secildi, pattern=r"^ses:"))
    uygulama.add_handler(CommandHandler("kanal", kanal_komutu))
    uygulama.add_handler(CommandHandler("kayit", kayit_komutu))
    uygulama.add_handler(CommandHandler("yeniden", yeniden_komutu))
    uygulama.add_handler(CommandHandler("guncelle", guncelle_komutu))
    uygulama.add_handler(MessageHandler(filters.Document.FileExtension("zip"), guncelleme_al))
    uygulama.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, resim_al))
    uygulama.add_error_handler(hata_yakala)
    print("Telegram'a bağlanılıyor...")
    try:
        uygulama.run_polling(drop_pending_updates=False)
    except (TimedOut, NetworkError) as hata:
        print("\nTelegram'a bağlanılamadı:", hata)
        print("İnternet bağlantını kontrol et. Sorun sürerse baglanti_testi.bat'ı çalıştırıp")
        print("çıkan sonucun ekran görüntüsünü gönder.")
    except InvalidToken:
        print("\nTelegram token'ı geçersiz. .env dosyasındaki TELEGRAM_TOKEN satırını kontrol et.")
        return
    if uygulama.bot_data.get("yeniden_basla"):
        print("Yeniden başlatılıyor...")
        logging.shutdown()
        os.execv(sys.executable, [sys.executable, "-u", str(KOK / "bot.py")])


if __name__ == "__main__":
    main()
