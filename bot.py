"""Telegram botu: ekran görüntülerini alır, videoyu üretir ve sana geri gönderir."""
import asyncio
import json
import re
import logging
import os
import shutil
import subprocess
import sys
import time
import zipfile

import requests
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import InvalidToken, NetworkError, TimedOut
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import ayarlar as A

import arastirma
import ekran_kaydi
import miksaj
import okunus
import urun_avi
from analiz import (ROLLER, SENARYO_SURUMU, AnalizHatasi, analiz_et, analiz_metinden, anthropic_dogrula,
                    paketi_dogrula, sayim_metni)
from demo import demo_uret
from ayarlar import (CALISMA, CIKTI, GELEN, KOK, TELEGRAM_PROXY, TELEGRAM_TOKEN, eksik_ayarlar,
                     maskele, no_kaydet, sonraki_no)
from ses import SesHatasi, hiz_carpani, sesleri_listele, seslendir
from veriler import rapor_metni, sonuc_kaydet, video_kaydet
from video import TEMALAR, kapak_uret, videoyu_kurgula

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
    "En kolay yol:\n"
    "/arastir ÜRÜN ADI – bot yorumları internette kendisi okur (Hepsiburada, Şikâyetvar, Ekşi, forumlar) "
    "ve videoyu hazırlar. /oneri listesindeki düğmeler de aynısını yapar.\n\n"
    "Ekran görüntüsüyle (Trendyol gibi otomatik okunamayan siteler için):\n"
    "1. Ürün sayfasından 2-3 ürün fotoğrafı kaydet (uzun bas → Fotoğrafı Kaydet; farklı açılar) ve onları gönder. "
    "Sonra yorumların ekran görüntülerini gönder. Video her bölümde başka açıyı gösterir.\n"
    "2. /hazirla yaz (ürün adı görüntülerde yoksa: /hazirla MARKA MODEL). İstersen /arastir da yazabilirsin.\n"
    "Videoya sonradan ürün fotoğrafı eklemek için: fotoğrafı gönder, sonra /tekrar NO.\n"
    "Ekran kaydı da olur: yorumları 'En yeni' sıralamasıyla aç, kaydı başlat, yavaşça aşağı kaydır ve "
    "kaydı bota gönder (1 dakikada 40-60 yorum).\n\n"
    "Diğer komutlar:\n"
    "/durum – kaç görüntü gönderdiğini gösterir\n"
    "/iptal – gönderilen görüntüleri siler\n"
    "/oneri – internette araştırıp 5 ürün adayı önerir (her pazartesi 10:00'da kendiliğinden gelir)\n"
    "/sonuc NO İZLENME TIKLAMA [KAZANÇ] – videonun sonucunu kaydeder (ör. /sonuc 3 12000 40 350)\n"
    "/rapor – hangi ürün grubunun daha iyi gittiğini gösterir\n"
    "/demo – API kullanmadan sessiz örnek video yapar\n"
    "/okunus KELİME = OKUNUŞ – yanlış okunan kelimeyi düzeltir (ör. /okunus Dreame = Drim)\n"
    "/tekrar NO – videonun sesini ve kurgusunu yeniden yapar; /tekrar NO tam analizi de yeniler\n\n"
    "Ayarlar:\n"
    "/ayarlar – hangi ayarların tamam olduğunu gösterir\n"
    "/elevenlabs ANAHTAR – ElevenLabs anahtarını kaydeder, sesini bulur\n"
    "/ses – kullanılacak ses klonunu seçtirir\n"
    "/anthropic ANAHTAR – Anthropic anahtarını kaydeder\n"
    "/kanal AD – videolardaki kanal adını değiştirir\n"
    "/link ac | kapat – 'link profilde' yazısını açar/kapatır (link ekleyince aç)\n"
    "/hiz 1.1 – konuşma hızı (1 = sesin kendi hızı; 1.15 üstü sonradan hızlandırılır, robotik duyulabilir)\n"
    "/muzik – videolara eklenen müzikler; müzik eklemek için bota mp3 gönder\n"
    "/efekt ac | kapat – geçiş, pop ve damga seslerini açar/kapatır\n"
    "/okuma haiku | sonnet – yorumları okuyan model (haiku çok daha ucuz)\n"
    "/tema – videonun görünümünü seçtirir (canlı renk, açık stüdyo, sarı)\n\n"
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


ESKI_GORUNTU_DK = 10  # bu kadar dakikadan sonra gelen görüntüde "yeni ürün mü?" diye sorulur


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
        f"Konuşma hızı: {hiz_carpani():.2f} (/hiz)",
        f"Görünüm: {TEMALAR.get(A.VIDEO_TEMA, A.VIDEO_TEMA)} (/tema)",
        f"Müzik: {len(miksaj.muzik_listesi())} parça (/muzik), efektler {'açık' if miksaj.efektler_acik() else 'kapalı'}",
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


async def link_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/link ac | /link kapat: videolarda ve açıklamada 'link profilde' yazısını açar/kapatır."""
    if not yetkili(update):
        return
    secim = (context.args[0].lower() if context.args else "")
    if secim in ("ac", "aç", "acik", "açık"):
        A.kaydet("LINK_PROFILDE", "1")
    elif secim in ("kapat", "kapali", "kapalı"):
        A.kaydet("LINK_PROFILDE", "")
    durum = "açık" if A.LINK_PROFILDE else "kapalı"
    await update.message.reply_text(
        f"'Link profilde' yazısı: {durum}.\n"
        "Satış ortaklığı linkini profiline ekleyince /link ac yaz; o zamana kadar kapalı kalsın.")


async def hiz_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/hiz 1.3: seslendirmenin hızını ayarlar."""
    if not yetkili(update):
        return
    if context.args:
        try:
            deger = float(context.args[0].replace(",", "."))
        except ValueError:
            deger = 0
        if not 0.8 <= deger <= 1.6:
            await update.message.reply_text("0.8 ile 1.6 arasında bir sayı yaz. Örnek: /hiz 1.3")
            return
        A.kaydet("SES_HIZI", f"{deger:.2f}")
    await update.message.reply_text(
        f"Konuşma hızı: {hiz_carpani():.2f}\n"
        "1 = ses klonunun kendi hızı. 1.0-1.15 arası doğal kalır (ElevenLabs'in kendi ayarı); "
        "üstü sonradan hızlandırılır ve robotik duyulabilir. Videoyu kısaltmak için metin zaten kısa tutuluyor.\n"
        "Son videoyu bu hızla yeniden yapmak için: /tekrar NO")


async def tema_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tema: videonun görünümünü düğmelerle seçtirir; /tema acik gibi doğrudan da yazılabilir."""
    if not yetkili(update):
        return
    secim = (context.args[0].lower() if context.args else "")
    secim = {"canlı": "canli", "açık": "acik", "sarı": "sari"}.get(secim, secim)
    if secim in TEMALAR:
        A.kaydet("VIDEO_TEMA", secim)
        await update.message.reply_text(f"Görünüm: {TEMALAR[secim]}. Mevcut videoyu bununla yapmak için: /tekrar NO")
        return
    dugmeler = InlineKeyboardMarkup([[InlineKeyboardButton(
        ("✅ " if A.VIDEO_TEMA == ad else "") + baslik, callback_data=f"tema:{ad}")] for ad, baslik in TEMALAR.items()])
    await update.message.reply_text("Videoların görünümü:", reply_markup=dugmeler)


async def tema_secildi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorgu = update.callback_query
    await sorgu.answer()
    if not yetkili(update):
        return
    ad = sorgu.data.split(":", 1)[1]
    if ad in TEMALAR:
        A.kaydet("VIDEO_TEMA", ad)
        await sorgu.edit_message_text(f"Görünüm: {TEMALAR[ad]}. Mevcut videoyu bununla yapmak için: /tekrar NO")


async def muzik_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Gönderilen müzik dosyasını kaydeder; sonraki videolarda alçak seste kullanılır."""
    if not yetkili(update):
        return
    mesaj = update.message
    kaynak = mesaj.audio or mesaj.document
    if kaynak is None:
        return
    ad = (getattr(kaynak, "file_name", None) or getattr(kaynak, "title", None) or f"muzik_{mesaj.message_id}")
    uzanti = Path(ad).suffix.lower()
    if uzanti not in miksaj.MUZIK_UZANTILARI:
        uzanti = ".mp3"
    if (kaynak.file_size or 0) > 20 * 1024 * 1024:
        await mesaj.reply_text("Dosya 20 MB'tan büyük; Telegram botları bunu indiremiyor. Daha kısa bir parça gönder.")
        return
    temiz = re.sub(r"[^\w\-]+", "_", Path(ad).stem, flags=re.UNICODE).strip("_")[:40] or "muzik"
    miksaj.MUZIK_KLASORU.mkdir(parents=True, exist_ok=True)
    yol = miksaj.MUZIK_KLASORU / f"{temiz}{uzanti}"
    dosya = await kaynak.get_file()
    await dosya.download_to_drive(yol)
    sayi = len(miksaj.muzik_listesi())
    await mesaj.reply_text(
        f"Müzik kaydedildi: {yol.name} (toplam {sayi} parça). Videolarda sırayla, konuşmanın altında alçak seste çalar.\n"
        "Bu parçanın lisansının YouTube ve TikTok'ta kullanıma izin verdiğinden emin ol.\n"
        "Listelemek ya da silmek için: /muzik")


async def muzik_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/muzik: liste; /muzik sil N; /muzik ac|kapat; /muzik ses 0.12"""
    if not yetkili(update):
        return
    args = [a.lower() for a in context.args]
    liste = miksaj.muzik_listesi()
    if args[:1] == ["sil"] and len(args) > 1 and args[1].isdigit() and 1 <= int(args[1]) <= len(liste):
        liste[int(args[1]) - 1].unlink(missing_ok=True)
        liste = miksaj.muzik_listesi()
    elif args[:1] and args[0] in ("ac", "aç"):
        A.kaydet("MUZIK", "1")
    elif args[:1] and args[0] in ("kapat", "kapali", "kapalı"):
        A.kaydet("MUZIK", "0")
    elif args[:1] == ["ses"] and len(args) > 1:
        try:
            deger = float(args[1].replace(",", "."))
        except ValueError:
            deger = -1
        if 0.02 <= deger <= 0.5:
            A.kaydet("MUZIK_SES", f"{deger:.2f}")
        else:
            await update.message.reply_text("0.02 ile 0.5 arasında bir sayı yaz. Örnek: /muzik ses 0.15")
            return
    durum_ = "açık" if str(A.MUZIK) not in ("0", "kapali", "kapalı") else "kapalı"
    satirlar = [f"Müzik: {durum_}, ses seviyesi {miksaj.muzik_sesi():.2f}"]
    satirlar += [f"{i}. {p.name}" for i, p in enumerate(liste, 1)] or ["Kayıtlı müzik yok. Bota bir mp3 gönder."]
    satirlar.append("\n/muzik sil N · /muzik ac | kapat · /muzik ses 0.18 (konuşma sırasında müzik ayrıca kısılır)")
    await update.message.reply_text("\n".join(satirlar))


OKUMA_MODELLERI = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5"}


async def okuma_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/okuma haiku | sonnet: yorumları okuyan model (Haiku çok daha ucuz, Sonnet daha dikkatli)."""
    if not yetkili(update):
        return
    secim = context.args[0].lower() if context.args else ""
    if secim in OKUMA_MODELLERI:
        A.kaydet("OKUMA_MODELI", OKUMA_MODELLERI[secim])
    simdiki = A.OKUMA_MODELI or A.CLAUDE_MODEL
    ad = next((k for k, v in OKUMA_MODELLERI.items() if v == simdiki), simdiki)
    await update.message.reply_text(
        f"Yorumları okuyan model: {ad}\n"
        "haiku: yaklaşık 20 kat ucuz, sonnet: daha dikkatli. Metni her durumda sonnet yazar.\n"
        "Değiştirmek için: /okuma haiku  ya da  /okuma sonnet")


async def efekt_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    secim = context.args[0].lower() if context.args else ""
    if secim in ("ac", "aç"):
        A.kaydet("EFEKT", "1")
    elif secim in ("kapat", "kapali", "kapalı"):
        A.kaydet("EFEKT", "0")
    await update.message.reply_text(
        f"Ses efektleri: {'açık' if miksaj.efektler_acik() else 'kapalı'} (geçişte whoosh, sayılarda pop, hükümde damga).\n"
        "Değiştirmek için: /efekt ac | kapat")


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
            parcalar = bilgi.filename.replace("\\", "/").split("/")
            ad = parcalar[-1]
            if len(parcalar) >= 2 and parcalar[-2] == "yazitipleri" and ad.endswith((".ttf", ".txt")):
                ad = "yazitipleri/" + ad  # videoda kullanılan yazı tipleri
            elif not (ad.endswith(".py") or ad in GUNCELLENEBILIR):
                continue
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
        (yedek / ad).parent.mkdir(parents=True, exist_ok=True)
        (KOK / ad).parent.mkdir(parents=True, exist_ok=True)
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
    onceki = resimler(mesaj.chat_id)
    simdi = time.time()
    yol = oturum(mesaj.chat_id) / f"{mesaj.message_id:010d}{uzanti}"
    await dosya.download_to_drive(yol)
    if not onceki:
        await mesaj.reply_text("İlk görüntü alındı. Hepsini gönderince /hazirla ya da /arastir ÜRÜN ADI yaz.")
        return
    await _eski_goruntu_sor(mesaj, onceki, simdi)


MUZIK_YOK = ("Not: videoda müzik yok, çünkü bota henüz müzik gönderilmedi. Bir mp3'ü bota dosya olarak gönder; "
             "bundan sonraki videolarda konuşmanın altında alçak seste çalar (/muzik ile yönetilir).")


async def _eski_goruntu_sor(mesaj, onceki, simdi):
    """Uzun aradan sonra yeni görüntü/kayıt gelince eskilerin silinip silinmeyeceğini sorar."""
    if not onceki:
        return
    en_yeni = max(p.stat().st_mtime for p in onceki)
    if simdi - en_yeni > ESKI_GORUNTU_DK * 60:
        # Uzun aradan sonra gelen görüntü: büyük ihtimalle yeni bir ürün. Eskilerle karışmasın diye sor.
        dakika = int((simdi - en_yeni) // 60)
        dugmeler = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"🗑 Eski {len(onceki)} görüntüyü sil", callback_data=f"eski:sil:{int(simdi)}"),
            InlineKeyboardButton("➕ Aynı ürün", callback_data="eski:tut")]])
        await mesaj.reply_text(
            f"Daha önce gönderdiğin {len(onceki)} görüntü bekliyor ({dakika} dk önce). "
            "Yeni bir ürüne geçtiysen eskileri sil; aynı ürünse devam et.", reply_markup=dugmeler)


def paket_yolu(chat_id):
    return GELEN / f"paket_{chat_id}.json"


def _foto_indir(adres, hedef):
    """Paketteki ürün fotoğrafını indirir (yalnızca https ve resim, en fazla 8 MB)."""
    if not str(adres).startswith("https://"):
        return False
    yanit = requests.get(adres, timeout=25, headers={"User-Agent": "Mozilla/5.0"}, stream=True)
    if yanit.status_code != 200 or not yanit.headers.get("Content-Type", "").startswith("image/"):
        return False
    veri = yanit.raw.read(8 * 1024 * 1024 + 1, decode_content=True)
    if len(veri) > 8 * 1024 * 1024:
        return False
    hedef.write_bytes(veri)
    return True


async def paket_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yorum paketi (yorumlar.json): Claude'un bilgisayardaki Chrome'dan okuduğu yorumlar."""
    if not yetkili(update):
        return
    mesaj = update.message
    if (mesaj.document.file_size or 0) > 5 * 1024 * 1024:
        await mesaj.reply_text("Dosya çok büyük (5 MB üstü).")
        return
    gecici = GELEN / f"paket_gelen_{mesaj.chat_id}.json"
    dosya = await mesaj.document.get_file()
    await dosya.download_to_drive(gecici)
    try:
        paket = paketi_dogrula(json.loads(gecici.read_text(encoding="utf-8")))
    except (ValueError, AnalizHatasi) as hata:
        gecici.unlink(missing_ok=True)
        await mesaj.reply_text(f"Yorum paketi okunamadı: {hata}")
        return
    gecici.replace(paket_yolu(mesaj.chat_id))
    urun = paket["urun"]
    indirilen = 0
    for i, adres in enumerate((urun.get("fotograflar") or [])[:4]):
        try:
            if await asyncio.to_thread(_foto_indir, adres, oturum(mesaj.chat_id) / f"{mesaj.message_id:010d}_f{i}.jpg"):
                indirilen += 1
        except requests.RequestException:
            log.warning("Paket fotoğrafı indirilemedi: %s", adres)
    foto = (f"{indirilen} ürün fotoğrafı indirildi." if indirilen else
            "Ürün fotoğrafı indirilemedi; ürün sayfasından 2-3 fotoğraf kaydedip gönder.")
    await mesaj.reply_text(
        f"Yorum paketi alındı: {urun.get('ad') or 'ürün'}\n"
        f"{len(paket['yorumlar'])} yorum · {paket.get('kaynak', '')} {paket.get('siralama', '')}".rstrip() + "\n"
        f"{foto}\nHazırsa /hazirla yaz.")


async def kayit_al(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ekran kaydı: yorumları kaydırırken alınan video. Kareleri çıkarılıp ekran görüntüsü gibi okunur."""
    if not yetkili(update):
        return
    mesaj = update.message
    kaynak = mesaj.video or mesaj.document
    if kaynak is None:
        return
    if (kaynak.file_size or 0) > 20 * 1024 * 1024:
        await mesaj.reply_text(
            "Kayıt 20 MB'tan büyük; Telegram botları bunu indiremiyor.\n"
            "Telegram'da 'dosya' olarak değil normal video olarak gönder (küçültülür) ya da kaydı 1 dakikalık "
            "parçalara bölüp ayrı ayrı gönder.")
        return
    onceki = resimler(mesaj.chat_id)
    simdi = time.time()
    durum_ = await mesaj.reply_text("Ekran kaydı alındı, kareleri çıkarıyorum…")
    gecici = GELEN / f"kayit_{mesaj.chat_id}_{mesaj.message_id}.mp4"
    try:
        dosya = await kaynak.get_file()
        await dosya.download_to_drive(gecici)
        kareler, toplam = await asyncio.to_thread(
            ekran_kaydi.kareleri_cikar, gecici, oturum(mesaj.chat_id), f"{mesaj.message_id:010d}")
    except Exception as hata:  # noqa: BLE001
        log.exception("ekran kaydı hatası")
        await durum_.edit_text(f"Kayıt okunamadı: {hata}")
        return
    finally:
        gecici.unlink(missing_ok=True)
    hepsi = len(resimler(mesaj.chat_id))
    await durum_.edit_text(
        f"Kayıttan {len(kareler)} farklı kare alındı (toplam {hepsi} görüntü bekliyor).\n"
        "Ürün fotoğraflarını da gönderdiysen /hazirla yaz. Aynı yorum birden çok karede görünse de bir kez sayılır.")
    await _eski_goruntu_sor(mesaj, onceki, simdi)


async def eski_goruntu_secildi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorgu = update.callback_query
    await sorgu.answer()
    if not yetkili(update):
        return
    parcalar = sorgu.data.split(":")
    if parcalar[1] == "sil" and len(parcalar) > 2:
        sinir = int(parcalar[2]) - 1
        silinen = 0
        for p in resimler(update.effective_chat.id):
            if p.stat().st_mtime < sinir:
                p.unlink(missing_ok=True)
                silinen += 1
        kalan = len(resimler(update.effective_chat.id))
        await sorgu.edit_message_text(f"{silinen} eski görüntü silindi. Şu an {kalan} görüntü var; "
                                      "kalanları gönderince /hazirla ya da /arastir yaz.")
    else:
        await sorgu.edit_message_text("Tamam, hepsi aynı ürün için kullanılacak.")


async def durum(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if yetkili(update):
        liste = resimler(update.effective_chat.id)
        ek = ""
        if liste:
            dakika = int((time.time() - min(p.stat().st_mtime for p in liste)) // 60)
            ek = f" (ilki {dakika} dk önce gönderildi; başka ürüne aitse /iptal yaz)"
        if paket_yolu(update.effective_chat.id).exists():
            ek += ". Bir yorum paketi de bekliyor"
        await update.message.reply_text(f"{len(liste)} görüntü bekliyor{ek}. Sıradaki dosya numarası: #{sonraki_no()}")


async def iptal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if yetkili(update):
        shutil.rmtree(oturum(update.effective_chat.id), ignore_errors=True)
        paket_yolu(update.effective_chat.id).unlink(missing_ok=True)
        await update.message.reply_text("Görüntüler ve yorum paketi silindi. Yeni ürün için baştan gönderebilirsin.")


async def oneri(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    bekle = await update.message.reply_text("İnternette araştırıyorum, 1-3 dakika sürebilir…")
    try:
        metin, adaylar = await asyncio.to_thread(urun_avi.haftalik_mesaj)
    except Exception as hata:  # noqa: BLE001 - kullanıcıya anlaşılır mesaj
        log.exception("öneri hatası")
        await bekle.edit_text(f"Öneri alınamadı: {hata}")
        return
    await bekle.delete()
    await _html_gonder(context.bot, update.effective_chat.id, metin, _aday_dugmeleri(adaylar))


def _kisalt_bayt(metin, sinir):
    while len(metin.encode("utf-8")) > sinir:
        metin = metin[:-1]
    return metin


def _aday_dugmeleri(adaylar):
    satirlar = []
    for i, aday in enumerate(adaylar, 1):
        urun = str(aday.get("urun") or aday.get("arama") or "").strip()
        if not urun:
            continue
        satirlar.append([InlineKeyboardButton(f"🎬 {i}. {urun[:40]}",
                                              callback_data="ara:" + _kisalt_bayt(urun, 60))])
    return InlineKeyboardMarkup(satirlar) if satirlar else None


async def _html_gonder(bot, chat_id, metin, dugmeler=None):
    try:
        await bot.send_message(chat_id, metin, parse_mode="HTML", disable_web_page_preview=True,
                               reply_markup=dugmeler)
    except Exception:  # noqa: BLE001 - biçim bozulursa düz metin gönder
        import re as _re
        await bot.send_message(chat_id, _re.sub(r"<[^>]+>", "", metin), disable_web_page_preview=True,
                               reply_markup=dugmeler)


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
            metin, adaylar = await asyncio.to_thread(urun_avi.haftalik_mesaj)
            await _html_gonder(uygulama.bot, int(A.IZINLI_KULLANICI_ID), metin, _aday_dugmeleri(adaylar))
        except Exception as hata:  # noqa: BLE001
            log.exception("Haftalık liste gönderilemedi")
            try:
                await uygulama.bot.send_message(int(A.IZINLI_KULLANICI_ID),
                                                f"Haftalık ürün listesi hazırlanamadı: {hata}\n/oneri ile tekrar dene.")
            except Exception:  # noqa: BLE001
                pass
        await asyncio.sleep(120)


def yayin_kontrolu(veri, no):
    """Yayından önce bakılacakları tek tek işaretler: ✅ tamam, ⚠️ dikkat, ❌ düzelt."""
    satirlar = []
    if veri.get("urun_gorseli") or veri.get("urun_fotograflari"):
        satirlar.append("✅ Ürün fotoğrafı var")
    else:
        satirlar.append(f"❌ Ürün fotoğrafı yok (videoda adı yazıyor). Fotoğraf gönder, sonra /tekrar {no}")
    ad = str(veri.get("urun_adi") or "").strip()
    genel = len(ad.split()) <= 2 or ad.lower() == str(veri.get("kategori") or "").lower()
    satirlar.append(f"⚠️ Ürün adı genel görünüyor: \"{ad}\". Düzeltmek için: /tekrar {no} MARKA MODEL" if genel
                    else f"✅ Ürün adı: {ad}")
    if veri.get("fiyat") and veri.get("puan"):
        satirlar.append("✅ Fiyat ve puan var")
    else:
        satirlar.append("⚠️ Fiyat ya da puan yok. Ürün sayfasının ekran görüntüsünü eklersen çıkar")
    n = veri.get("urun_yorumu", veri.get("okunan_yorum", 0))
    if n >= 150:
        satirlar.append(f"✅ {n} ürün yorumu okundu")
    elif n >= 100:
        satirlar.append(f"⚠️ {n} ürün yorumu: sınırda, 150+ daha güvenilir")
    else:
        satirlar.append(f"❌ {n} ürün yorumu: az (videoda 'sonuç kesin değil' deniyor). Daha çok yorum ekle")
    if miksaj.muzik_listesi() and str(A.MUZIK) not in ("0", "kapali", "kapalı"):
        satirlar.append("✅ Müzik var")
    else:
        satirlar.append("⚠️ Müzik yok. Bota bir mp3 gönder")
    if veri.get("uyarilar"):
        satirlar.append(f"⚠️ Analizde {len(veri['uyarilar'])} uyarı var (aşağıda)")
    tamam = not any(s.startswith(("❌", "⚠️")) for s in satirlar)
    satirlar.append("Hepsi ✅: yayınlayabilirsin." if tamam else "Önce işaretli olanlara bak.")
    return "YAYIN KONTROLÜ:\n" + "\n".join(satirlar)


def paylasim_metni(veri, no):
    etiketler = " ".join("#" + e for e in veri.get("etiketler", []) if e)
    kaynak = f"Okunan yorumlar: {arastirma.kaynak_satiri(veri)}.\n" if veri.get("kaynaklar") else ""
    if veri.get("tarih"):
        kaynak += (f"Veri: {veri['okunan_yorum']} yorum ({veri.get('urun_yorumu', veri['okunan_yorum'])} ürünle ilgili), "
                   f"kaynak: {veri.get('kaynak_etiketi', '')}, {veri['tarih']}. Rakamlar okunan yorumlardan sayıldı.\n")
    parcalar = [
        f"BAŞLIK:\n{veri['baslik']}",
        f"AÇIKLAMA:\n{veri.get('aciklama', '').strip()}\n\n{kaynak}"
        + (f"Ürün linki profilde: Yorum dosyası #{no}. Profildeki link satış ortaklığı linkidir. #işbirliği\n"
           if A.LINK_PROFILDE else f"Yorum dosyası #{no}. Sıradaki ürünü yorumlara yaz.\n")
        + f"{etiketler}",
    ]
    if veri.get("satici"):
        parcalar.append(f"SATICI: {veri['satici']}\nLinki koyarken bu satıcının ürününü seçtiğinden emin ol.")
    if veri.get("sayim"):
        parcalar.append("SAYIM (kodla sayıldı, kontrol için):\n" + sayim_metni(veri["sayim"]))
    if veri.get("uyarilar"):
        parcalar.append("⚠️ DİKKAT:\n" + "\n".join("• " + u for u in veri["uyarilar"]))
    parcalar.append(KONTROL)
    return yayin_kontrolu(veri, no) + "\n\n" + "\n\n".join(parcalar)


async def _uret(context: ContextTypes.DEFAULT_TYPE, chat_id, ilk_mesaj, analiz_cagir, gorseller, hata_eki):
    """Analiz → ses → video → gönderim. Başarılıysa True döner."""
    kilit = context.application.bot_data.setdefault("uretim_kilidi", asyncio.Lock())
    if kilit.locked():
        await context.bot.send_message(chat_id, "Şu an bir video hazırlanıyor; o bitince tekrar dene.")
        return False
    async with kilit:
        no = sonraki_no()
        klasor = CALISMA / f"dosya_{no:03d}"
        klasor.mkdir(parents=True, exist_ok=True)
        durum_mesaji = await context.bot.send_message(chat_id, ilk_mesaj)
        try:
            veri = await asyncio.to_thread(analiz_cagir, no)
            await durum_mesaji.edit_text(
                f"2/3 Seslendiriyorum… ({veri['okunan_yorum']} yorum okundu, {veri['urun_yorumu']} tanesi ürünü "
                f"anlatıyor; hüküm: {veri['hukum']})")
            metin = " ".join(veri["senaryo"][r] for r in ROLLER)
            konusma = okunus.konusma_metni([veri["senaryo"][r] for r in ROLLER])
            ses_yolu = klasor / "ses.mp3"
            hiz = await asyncio.to_thread(seslendir, konusma, ses_yolu)
            await durum_mesaji.edit_text("3/3 Videoyu kurguluyorum… (1-2 dakika)")
            kullanilan = list(gorseller) or [kapak_uret(veri["urun_adi"], klasor / "kapak.png")]
            cikti = CIKTI / f"yorum_dosyasi_{no:03d}.mp4"
            await asyncio.to_thread(videoyu_kurgula, veri, kullanilan, ses_yolu, hiz, no, cikti)
        except (AnalizHatasi, SesHatasi) as hata:
            await durum_mesaji.edit_text(f"Olmadı: {hata}\n\n{hata_eki}")
            return False
        except Exception as hata:  # noqa: BLE001
            log.exception("üretim hatası")
            await durum_mesaji.edit_text(f"Beklenmeyen hata: {hata}\n\n{hata_eki}")
            return False

        no_kaydet(no)
        video_kaydet(no, veri)
        for kaynak in gorseller:
            shutil.copy2(kaynak, klasor / kaynak.name)
        (klasor / "senaryo.txt").write_text(metin, encoding="utf-8")
        (klasor / "okunus.txt").write_text(konusma, encoding="utf-8")
        (klasor / "analiz.json").write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
        await durum_mesaji.edit_text(f"Hazır: Yorum dosyası #{no}")
        with open(cikti, "rb") as dosya:
            await context.bot.send_video(chat_id, dosya, caption=f"Yorum dosyası #{no}", supports_streaming=True,
                                         read_timeout=180, write_timeout=180)
        await context.bot.send_message(chat_id, paylasim_metni(veri, no))
        return True


async def okunus_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/okunus KELİME = OKUNUŞ  |  /okunus sil KELİME  |  /okunus"""
    if not yetkili(update):
        return
    metin = " ".join(context.args).strip()
    if not metin:
        kayitli = okunus.kullanici_sozlugu()
        liste = "\n".join(f"• {k} → {v}" for k, v in sorted(kayitli.items())) or "(henüz eklemedin)"
        await update.message.reply_text(
            "Yanlış okunan bir kelimeyi düzeltmek için:\n/okunus Stanley = Stenli\n"
            "Silmek için: /okunus sil Stanley\n\n"
            "Sayılar (1.839 TL, 4,6, 46'sı), %, QR gibi kısaltmalar zaten Türkçe okunuyor.\n"
            "Düzelttikten sonra videonun sesini yenilemek için: /tekrar DOSYA_NO\n"
            "Analizi de baştan yaptırmak için: /tekrar DOSYA_NO tam\n\n"
            f"Senin eklediklerin:\n{liste}")
        return
    if metin.lower().startswith("sil "):
        kelime = metin[4:].strip()
        okunus.sozluge_ekle(kelime, "")
        await update.message.reply_text(f"Silindi: {kelime}")
        return
    if "=" not in metin:
        await update.message.reply_text("Biçim: /okunus KELİME = OKUNUŞ   (ör. /okunus Dreame = Drim)")
        return
    kelime, okunan = (x.strip() for x in metin.split("=", 1))
    if not kelime or not okunan or " " in kelime:
        await update.message.reply_text("Tek bir kelime ve okunuşunu yaz: /okunus Dreame = Drim")
        return
    okunus.sozluge_ekle(kelime, okunan)
    ornek = okunus.konusma_metni([f"{kelime} ürünü"])
    await update.message.reply_text(f"Kaydedildi: {kelime} → {okunan}\nÖrnek okunuş: {ornek}")


async def tekrar_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tekrar NO: analizi yeniden yapmadan sesi ve videoyu baştan üretir (okunuş düzeltmesinden sonra)."""
    if not yetkili(update):
        return
    try:
        no = int(context.args[0].lstrip("#"))
    except (IndexError, ValueError):
        await update.message.reply_text("Kullanım: /tekrar DOSYA_NO   (ör. /tekrar 1)\n"
                                        "Analizi de yenilemek için: /tekrar 1 tam\n"
                                        "Ürün adını düzeltmek için: /tekrar 1 MARKA MODEL")
        return
    klasor = CALISMA / f"dosya_{no:03d}"
    analiz_yolu = klasor / "analiz.json"
    tam = len(context.args) > 1 and context.args[1].lower() in ("tam", "analiz")
    yeni_ad = " ".join(context.args[2 if tam else 1:]).strip()[:80]  # /tekrar 3 Tefal Ingenio 3'lü set
    gorseller = sorted(p for p in klasor.iterdir()
                       if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and p.name != "kapak.png") \
        if klasor.exists() else []
    if tam and not gorseller and not (klasor / "yorum_paketi.json").exists() and not (
            analiz_yolu.exists() and json.loads(analiz_yolu.read_text(encoding="utf-8")).get("arama")):
        await update.message.reply_text(f"#{no} için kayıtlı ekran görüntüsü yok; /arastir ile yeniden yapabilirsin.")
        return
    if not tam and not analiz_yolu.exists():
        await update.message.reply_text(f"#{no} için kayıtlı analiz yok. Görüntüler duruyorsa: /tekrar {no} tam")
        return
    eski_veri = json.loads(analiz_yolu.read_text(encoding="utf-8")) if analiz_yolu.exists() else {}
    arama = eski_veri.get("arama")  # /arastir ile yapılmışsa yeniden internetten okunur
    bekleyen = resimler(update.effective_chat.id)
    if bekleyen and klasor.exists():
        # Sonradan gönderilen fotoğraflar bu videonun ürün fotoğrafı olur (ör. önce yalnızca yorum gönderildiyse)
        damga_ = int(time.time())
        eklenen = []
        for i, p in enumerate(bekleyen):
            hedef = klasor / f"urun_ek_{damga_}_{i:02d}{p.suffix.lower()}"
            shutil.copy2(p, hedef)
            eklenen.append(hedef.name)
        shutil.rmtree(oturum(update.effective_chat.id), ignore_errors=True)
        gorseller = sorted(p for p in klasor.iterdir()
                           if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp") and p.name != "kapak.png")
        yeni_no = [i + 1 for i, p in enumerate(gorseller) if p.name in eklenen]
        if eski_veri:
            eski_veri["urun_fotograflari"] = yeni_no + [n for n in eski_veri.get("urun_fotograflari") or []
                                                        if n not in yeni_no]
            analiz_yolu.write_text(json.dumps(eski_veri, ensure_ascii=False, indent=1), encoding="utf-8")
        await update.message.reply_text(f"{len(eklenen)} fotoğraf #{no} için ürün fotoğrafı olarak eklendi.")
    if yeni_ad and eski_veri:
        eski_veri["urun_adi"] = yeni_ad
        analiz_yolu.write_text(json.dumps(eski_veri, ensure_ascii=False, indent=1), encoding="utf-8")
    veri = eski_veri if not tam else None
    if veri is not None and veri.get("surum", 0) < SENARYO_SURUMU:
        if gorseller or arama or (klasor / "yorum_paketi.json").exists():
            tam, veri = True, None
            await update.message.reply_text(
                f"#{no} metni eski kurallarla yazılmıştı (uzun, fiyatı okuyordu). Yeni kısa metin yazılıyor.")
        else:
            await update.message.reply_text(
                f"#{no} metni eski kurallarla yazılmış ve kayıtlı görüntü yok. Yeni metin için: /arastir ÜRÜN ADI")
    kilit = context.application.bot_data.setdefault("uretim_kilidi", asyncio.Lock())
    if kilit.locked():
        await update.message.reply_text("Şu an bir video hazırlanıyor; o bitince tekrar dene.")
        return
    async with kilit:
        durum_mesaji = await update.message.reply_text(
            f"#{no} yeniden analiz ediliyor…" if tam else f"#{no} yeniden seslendiriliyor…")
        try:
            if tam:
                if (klasor / "yorum_paketi.json").exists():
                    paket = json.loads((klasor / "yorum_paketi.json").read_text(encoding="utf-8"))
                    if yeni_ad:
                        paket.setdefault("urun", {})["ad"] = yeni_ad
                    veri = await asyncio.to_thread(analiz_metinden, paket, gorseller, no)
                elif arama:
                    veri = await asyncio.to_thread(arastirma.arastir, arama, no, gorseller)
                else:
                    veri = await asyncio.to_thread(analiz_et, gorseller, no,
                                                   yeni_ad or eski_veri.get("urun_adi_kullanici", ""))
                if yeni_ad:
                    veri["urun_adi_kullanici"] = yeni_ad
                analiz_yolu.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
                video_kaydet(no, veri)
                await durum_mesaji.edit_text(f"#{no} seslendiriliyor… (hüküm: {veri['hukum']})")
            konusma = okunus.konusma_metni([veri["senaryo"][r] for r in ROLLER])
            ses_yolu = klasor / "ses.mp3"
            hiz = await asyncio.to_thread(seslendir, konusma, ses_yolu)
            await durum_mesaji.edit_text(f"#{no} videosu kurgulanıyor… (1-2 dakika)")
            if not gorseller:
                gorseller = [kapak_uret(veri["urun_adi"], klasor / "kapak.png")]
            cikti = CIKTI / f"yorum_dosyasi_{no:03d}.mp4"
            await asyncio.to_thread(videoyu_kurgula, veri, gorseller, ses_yolu, hiz, no, cikti)
        except Exception as hata:  # noqa: BLE001
            log.exception("tekrar hatası")
            await durum_mesaji.edit_text(f"Olmadı: {hata}")
            return
        (klasor / "okunus.txt").write_text(konusma, encoding="utf-8")
        await durum_mesaji.edit_text(f"Hazır: Yorum dosyası #{no} (yeni ses)")
        with open(cikti, "rb") as dosya:
            await update.message.reply_video(dosya, caption=f"Yorum dosyası #{no}", supports_streaming=True,
                                             read_timeout=180, write_timeout=180)
        await update.message.reply_text(paylasim_metni(veri, no) if tam else
                                        yayin_kontrolu(veri, no) + "\n\nSeslendirilen metin:\n" + konusma)


async def hazirla(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    chat_id = update.effective_chat.id
    liste = resimler(chat_id)
    paket_ = paket_yolu(chat_id)
    if paket_.exists():
        paket = json.loads(paket_.read_text(encoding="utf-8"))

        def cagir(no):
            shutil.copy2(paket_, CALISMA / f"dosya_{no:03d}" / "yorum_paketi.json")
            return analiz_metinden(paket, liste, no)

        tamam = await _uret(context, chat_id,
                            f"1/3 Yorum paketini okuyorum… ({len(paket.get('yorumlar', []))} yorum)",
                            cagir, liste, "Paket duruyor. /hazirla ile tekrar deneyebilir ya da /iptal ile silebilirsin.")
        if tamam:
            paket_.unlink(missing_ok=True)
            shutil.rmtree(oturum(chat_id), ignore_errors=True)
        return
    if len(liste) < 2:
        await update.message.reply_text(
            "En az 2 görüntü gönder: ürün sayfası ve yorumlar. İlk görüntü ürün sayfası olmalı.\n"
            "Görüntüsüz yol: /arastir ÜRÜN ADI")
        return
    urun_adi = " ".join(context.args).strip()[:80]
    grup = -(-min(len(liste), 200) // 40)
    sure_ = "1-2 dakika" if grup == 1 else f"{grup} grup, {grup + 1}-{grup * 2} dakika"
    tamam = await _uret(context, chat_id, f"1/3 Yorumları okuyorum… ({len(liste)} görüntü, {sure_})",
                        lambda no: analiz_et(liste, no, urun_adi), liste,
                        "Görüntüler duruyor. Ekleme yapıp /hazirla ile tekrar deneyebilir ya da /iptal ile silebilirsin.")
    if tamam:
        shutil.rmtree(oturum(chat_id), ignore_errors=True)


async def _arastir_ve_uret(context, chat_id, urun):
    liste = resimler(chat_id)
    ek = f" + {len(liste)} ekran görüntüsü" if liste else ""
    tamam = await _uret(
        context, chat_id,
        f"1/3 \"{urun}\" için internetteki yorumları okuyorum{ek}… (2-4 dakika)",
        lambda no: arastirma.arastir(urun, no, liste), liste,
        f"Tekrar denemek için: /arastir {urun}")
    if tamam and liste:
        shutil.rmtree(oturum(chat_id), ignore_errors=True)


async def arastir_komutu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not yetkili(update):
        return
    urun = " ".join(context.args).strip()
    if not urun:
        await update.message.reply_text(
            "Kullanım: /arastir ÜRÜN ADI\nÖrnek: /arastir Stanley Quencher 1.18 L\n\n"
            "Bot Hepsiburada, Şikâyetvar, Ekşi Sözlük, forumlar ve Akakçe'deki yorumları okuyup videoyu hazırlar. "
            "Trendyol ve Amazon otomatik okumaya kapalı; oradan yorum eklemek istersen önce ekran görüntülerini gönder.")
        return
    await _arastir_ve_uret(context, update.effective_chat.id, urun)


async def aday_secildi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sorgu = update.callback_query
    await sorgu.answer()
    if not yetkili(update):
        return
    urun = sorgu.data.split(":", 1)[1]
    await _arastir_ve_uret(context, update.effective_chat.id, urun)


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
    uygulama.add_handler(CommandHandler("arastir", arastir_komutu))
    uygulama.add_handler(CommandHandler("okunus", okunus_komutu))
    uygulama.add_handler(CommandHandler("tekrar", tekrar_komutu))
    uygulama.add_handler(CommandHandler("link", link_komutu))
    uygulama.add_handler(CommandHandler("hiz", hiz_komutu))
    uygulama.add_handler(CallbackQueryHandler(eski_goruntu_secildi, pattern=r"^eski:"))
    uygulama.add_handler(CommandHandler("muzik", muzik_komutu))
    uygulama.add_handler(CommandHandler("efekt", efekt_komutu))
    uygulama.add_handler(CommandHandler("okuma", okuma_komutu))
    uygulama.add_handler(MessageHandler(filters.AUDIO | filters.Document.Category("audio/"), muzik_al))
    uygulama.add_handler(MessageHandler(filters.VIDEO | filters.Document.Category("video/"), kayit_al))
    uygulama.add_handler(CommandHandler("tema", tema_komutu))
    uygulama.add_handler(CallbackQueryHandler(tema_secildi, pattern=r"^tema:"))
    uygulama.add_handler(CallbackQueryHandler(aday_secildi, pattern=r"^ara:"))
    uygulama.add_handler(MessageHandler(filters.Document.FileExtension("zip"), guncelleme_al))
    uygulama.add_handler(MessageHandler(filters.Document.FileExtension("json"), paket_al))
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
