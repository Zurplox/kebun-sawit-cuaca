#!/usr/bin/env python3
"""Kirim notifikasi harian kebun.

WhatsApp (CallMeBot) — GRATIS. Dipecah jadi beberapa pesan pendek supaya
tidak terpotong (batas panjang CallMeBot ~900 karakter):
  1) HEADLINE (+ PENGINGAT 7 HARI bila ada kegiatan dalam 0-7 hari)
  2) DETAIL A — cuaca & rekomendasi
  3) DETAIL B — jadwal kegiatan + dashboard
  4) Warna asli   (tautan sendiri -> pratinjau thumbnail)
  5) NDVI         (tautan sendiri -> pratinjau thumbnail)
  6) Grafik hujan (tautan sendiri -> pratinjau thumbnail)
  Secrets: WA_PHONE, WA_APIKEY

Telegram (opsional) — GRATIS, foto asli: TG_TOKEN, TG_CHAT_ID

Citra terbaru diambil otomatis dari repo Harvin (folder citra/<tanggal>).
Hanya modul standar Python.
"""
import json
import os
import time
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from analysis import (
    BULAN, HARI, compute_insights, fmt, fmt_dow, headline, water_verdict,
    weather_desc,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "data", "last_sent.json")
JENIS = {"pupuk": "🌱 Pupuk", "pruning": "✂️ Pruning", "tebas": "🌾 Tebas"}


def today_summary_lines(td):
    """Ringkasan cuaca hari ini untuk pesan (kondisi, suhu, angin, jam hujan)."""
    if not td:
        return []
    out = []
    cond = td.get("condition")
    emoji = td.get("emoji") or "🌥️"
    cloud = td.get("cloud")
    hum = td.get("humidity")
    if cond:
        extra = []
        if cloud is not None:
            extra.append("awan " + str(cloud) + "%")
        if hum is not None:
            extra.append("lembap " + str(hum) + "%")
        tail = (" · " + " · ".join(extra)) if extra else ""
        out.append(emoji + " " + cond + tail)
    bits = []
    tmin = td.get("tmin")
    tmax = td.get("tmax")
    if tmin is not None and tmax is not None:
        bits.append("🌡️ " + str(round(tmin)) + "–" + str(round(tmax)) + "°C")
    w = td.get("wind")
    wd = td.get("wind_dir")
    if w is not None:
        wtxt = "💨 " + str(round(w)) + " km/j"
        if wd:
            wtxt += " dari " + wd
        bits.append(wtxt)
    if bits:
        out.append(" · ".join(bits))
    rw = td.get("rain_windows") or []
    ph = td.get("precip_hours")
    if rw:
        cap = (" (±" + str(int(round(ph))) + " jam)") if ph is not None else ""
        out.append("⏱️ Jam hujan: " + ", ".join(rw) + " WIB" + cap)
    elif ph is not None and ph < 1:
        out.append("⏱️ Cenderung tanpa hujan berarti hari ini")
    return out


def today_detail_lines(td):
    """Baris tambahan (matahari, hembusan angin) untuk pesan detail."""
    if not td:
        return []
    out = []
    sr = td.get("sunrise")
    ss = td.get("sunset")
    if sr and ss:
        out.append("🌅 Matahari: terbit " + sr + ", terbenam " + ss + " WIB")
    g = td.get("gust")
    if g is not None:
        out.append("💨 Hembusan angin maks: " + str(round(g)) + " km/j")
    return out


def load_json(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        return json.load(f)


def http_json(url, timeout=30):
    req = urllib.request.Request(url, headers={
        "User-Agent": "kebun-cuaca/1.0",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def chart_url(cfg):
    base = (cfg.get("dashboard_url") or "").strip().rstrip("/")
    return base + "/chart.png" if base else ""


# ---------- Ambil citra terbaru dari repo Harvin ----------
def harvin_latest(cfg):
    owner = (cfg.get("harvin_owner") or "").strip()
    repo = (cfg.get("harvin_repo") or "").strip()
    branch = (cfg.get("harvin_branch") or "main").strip()
    if not (owner and repo):
        return None
    api = "https://api.github.com/repos/" + owner + "/" + repo + "/contents/citra?ref=" + branch
    try:
        items = http_json(api)
    except Exception as e:
        print("Harvin: gagal daftar citra:", e)
        return None
    dates = sorted([it["name"] for it in items if it.get("type") == "dir"])
    if not dates:
        return None
    d = dates[-1]
    raw = "https://raw.githubusercontent.com/" + owner + "/" + repo + "/" + branch + "/citra/" + d
    # Pratinjau thumbnail WhatsApp lebih andal dari GitHub Pages daripada raw.
    pages = (cfg.get("harvin_pages_url") or "").strip().rstrip("/")
    base = (pages + "/citra/" + d) if pages else raw
    tc = (cfg.get("truecolor_name") or "1_warna_asli_terbaru.png").strip()
    nd = (cfg.get("ndvi_name") or "2_ndvi_terbaru.png").strip()
    meta = {}
    try:
        meta = http_json(raw + "/meta.json")
    except Exception:
        pass
    sat = cloud = None
    imgs = meta.get("images", {}) if isinstance(meta, dict) else {}
    info = imgs.get(tc) or (next(iter(imgs.values())) if imgs else {})
    if isinstance(info, dict):
        sat = info.get("sat")
        cloud = info.get("cloud")
    return {
        "date": d,
        "truecolor": base + "/" + tc,
        "ndvi": base + "/" + nd,
        "sat": sat, "cloud": cloud,
    }


def sat_label(harv):
    return str(harv.get("sat") or harv["date"])


def next_event(jadwal, jenis, today):
    cand = [
        e for e in jadwal.get("events", [])
        if e.get("type") == jenis
        and datetime.strptime(e["date"], "%Y-%m-%d").date() >= today
    ]
    cand.sort(key=lambda e: e["date"])
    return cand[0] if cand else None


def soon_events(jadwal, today, within=7):
    """Semua kegiatan dalam 0..within hari, urut terdekat."""
    out = []
    for e in jadwal.get("events", []):
        ed = datetime.strptime(e["date"], "%Y-%m-%d").date()
        dd = (ed - today).days
        if 0 <= dd <= within:
            out.append((dd, e))
    out.sort(key=lambda x: x[0])
    return out


def when_label(dd):
    return "hari ini" if dd == 0 else ("besok" if dd == 1 else str(dd) + " hari lagi")


# ---------- PESAN 1: HEADLINE ----------
def build_headline(cfg, jadwal, cuaca, today, harv):
    days = cuaca.get("days", [])
    by = {d["date"]: d for d in days}
    ins = compute_insights(days, cfg, today)
    L = []
    L.append("🌴 *" + cfg.get("farm_name", "Kebun") + "*")
    L.append(HARI[today.weekday()] + ", " + f"{today.day:02d} {BULAN[today.month]} {today.year}")
    L.append("")
    L.append(headline(ins, cfg))
    L.append("")

    # PENGINGAT H-7: semua kegiatan (pupuk/pruning/tebas) dalam 0-7 hari
    soon = soon_events(jadwal, today, 7)
    if soon:
        L.append("⏰ *PENGINGAT 7 HARI:*")
        for dd, e in soon:
            L.append("   " + JENIS.get(e["type"], "•") + " " + e["label"] + " — *" + when_label(dd) + "* (" + fmt(e["date"]) + ")")
        L.append("")

    t = by.get(today.isoformat())
    if t and t.get("precip") is not None:
        pr = (" (kmk " + str(t["prob"]) + "%)") if t.get("prob") is not None else ""
        L.append("☔ Hujan hari ini: *" + str(t["precip"]) + " mm*" + pr)
    for line in today_summary_lines(cuaca.get("today") or {}):
        L.append(line)
    if ins["best"]:
        b = ins["best"]
        verdict = "ideal" if b["score"] >= 70 else ("cukup baik" if b["score"] >= 55 else "kurang ideal")
        L.append("🎯 Pupuk terbaik: *" + fmt_dow(b["date"]) + "* (" + verdict + ")")
    if ins["dry_longest"]:
        s = ins["dry_longest"]
        L.append("☀️ Kering terpanjang: *" + str(s["len"]) + " hari* dari " + fmt_dow(s["start"]))
    if harv and harv.get("sat"):
        L.append("🛰️ Citra satelit: *" + sat_label(harv) + "* (foto menyusul)")

    # Info pupuk terjadwal berikutnya (hanya bila >7 hari; kalau ≤7 hari sudah ada di PENGINGAT)
    pupuk = next_event(jadwal, "pupuk", today)
    if pupuk:
        d = datetime.strptime(pupuk["date"], "%Y-%m-%d").date()
        if (d - today).days > 7:
            L.append("🌱 Pupuk terjadwal: *" + str((d - today).days) + " hari lagi*")

    url = (cfg.get("dashboard_url") or "").strip()
    L.append("")
    if url:
        L.append("📊 Dashboard: " + url)
    L.append("📩 Detail + foto menyusul ⬇️")
    return "\n".join(L)


# ---------- PESAN 2: DETAIL (dipecah 2 bagian agar tidak terpotong) ----------
def build_detail(cfg, jadwal, cuaca, today, harv):
    days = cuaca.get("days", [])
    by = {d["date"]: d for d in days}
    heavy = cfg.get("heavy_rain_mm", 25)
    dry = cfg.get("dry_threshold_mm", 2)
    ins = compute_insights(days, cfg, today)

    # ===== Bagian A: cuaca & rekomendasi =====
    A = []
    A.append("🌴 *" + cfg.get("farm_name", "Kebun") + "* — Cuaca (" + f"{today.day:02d} {BULAN[today.month]}" + ")")
    A.append("")
    t = by.get(today.isoformat())
    if t and t.get("precip") is not None:
        prob = (" (kemungkinan " + str(t["prob"]) + "%)") if t.get("prob") is not None else ""
        A.append("☔ Hujan hari ini: *" + str(t["precip"]) + " mm*" + prob)
    td = cuaca.get("today") or {}
    for line in today_summary_lines(td):
        A.append(line)
    for line in today_detail_lines(td):
        A.append(line)
    A.append("💧 Neraca air 30 hari: *" + f"{ins['water_balance']:.0f} mm* (" + water_verdict(ins["water_balance"]) + ")")
    A.append("")
    A.append("📅 *Prakiraan 3 hari:*")
    for i in range(1, 4):
        d = today + timedelta(days=i)
        row = by.get(d.isoformat())
        if not row:
            continue
        p = row.get("precip")
        p = (str(p) + " mm") if p is not None else "-"
        emo = weather_desc(row.get("code"))[1] if row.get("code") is not None else ""
        A.append("   • " + HARI[d.weekday()] + f" {d.day:02d} {BULAN[d.month]}: " + p + ((" " + emo) if emo else ""))
    A.append("")
    if ins["best"]:
        b = ins["best"]
        verdict = "ideal" if b["score"] >= 70 else ("cukup baik" if b["score"] >= 55 else "kurang ideal")
        A.append("🎯 *Hari terbaik memupuk (16 hr):* " + fmt_dow(b["date"]) + " — " + verdict)
        why = b["why"][:2]
        A.append("   " + (", ".join(why) if why else "tanah lembap, tanpa hujan deras sesudahnya"))
    if ins["dry_longest"]:
        s = ins["dry_longest"]
        A.append("☀️ *Rentang kering terpanjang:* " + str(s["len"]) + " hari mulai " + fmt_dow(s["start"]) + " (tebas/semprot)")

    # ===== Bagian B: jadwal kegiatan + dashboard =====
    def rain_advice(dstr):
        row = by.get(dstr)
        if not row or row.get("precip") is None:
            return "🕒 Prakiraan belum tersedia — cek mendekati tanggal"
        p = row["precip"]
        if p >= heavy:
            return "⚠️ Hujan lebat (" + str(p) + " mm) — risiko hara tercuci"
        if p < dry:
            return "☀️ Cenderung kering (" + str(p) + " mm) — hara lambat larut"
        return "✅ Kondisi baik (" + str(p) + " mm)"

    B = []
    B.append("🗓️ *" + cfg.get("farm_name", "Kebun") + "* — Jadwal kegiatan")
    B.append("")
    pupuk = next_event(jadwal, "pupuk", today)
    if pupuk:
        d = datetime.strptime(pupuk["date"], "%Y-%m-%d").date()
        B.append("🌱 *Pupuk terjadwal:* " + pupuk["label"])
        B.append("   " + fmt(pupuk["date"]) + " — " + str((d - today).days) + " hari lagi")
        B.append("   " + rain_advice(pupuk["date"]))
    for jenis in ("pruning", "tebas"):
        e = next_event(jadwal, jenis, today)
        if e:
            d = datetime.strptime(e["date"], "%Y-%m-%d").date()
            B.append(JENIS[jenis] + ": " + e["label"] + " — " + fmt(e["date"]) + " (" + str((d - today).days) + " hari lagi)")
    if harv and harv.get("cloud") is not None:
        B.append("")
        B.append("🛰️ Citra satelit " + sat_label(harv) + " · awan " + str(harv["cloud"]) + "% (foto menyusul)")
    B.append("")
    wurl = (cfg.get("dashboard_url") or "").strip()
    curl = (cfg.get("citra_dashboard_url") or "").strip()
    if wurl:
        B.append("📊 Dashboard cuaca: " + wurl)
    if curl:
        B.append("🛰️ Dashboard citra: " + curl)

    return ["\n".join(A), "\n".join(B)]


# ---------- CallMeBot WhatsApp (teks + tautan pratinjau) ----------
def wa_send(text):
    phone = os.environ.get("WA_PHONE", "").strip()
    apikey = os.environ.get("WA_APIKEY", "").strip()
    if not (phone and apikey):
        return False
    q = urllib.parse.urlencode({"phone": phone, "text": text, "apikey": apikey})
    try:
        with urllib.request.urlopen("https://api.callmebot.com/whatsapp.php?" + q, timeout=45) as r:
            status = r.status
            body = r.read().decode("utf-8", "replace")
    except Exception as e:
        print("WA gagal (jaringan):", e)
        return False
    snippet = re.sub(r"<[^>]+>", " ", body)
    snippet = re.sub(r"\s+", " ", snippet).strip()[:300]
    low = snippet.lower()
    ok_markers = ("queued", "message sent", "sent to", "will receive", "waiting to be delivered")
    err_markers = ("apikey", "api key", "not valid", "invalid", "not registered",
                   "not allowed", "too fast", "too many", "wait until", "limit",
                   "expired", "activate", "error")
    is_ok = any(m in low for m in ok_markers)
    is_err = any(m in low for m in err_markers)
    print("WA:", status, "| resp:", snippet if snippet else "(kosong)")
    if is_ok and not is_err:
        return True
    if is_err:
        print("WA DITOLAK CallMeBot (kemungkinan rate-limit / apikey / aktivasi).")
        return False
    print("WA: respons tidak dikenal, dianggap GAGAL agar aman.")
    return False


# ---------- Telegram (opsional: teks + foto asli) ----------
def tg_env():
    return (os.environ.get("TG_TOKEN", "").strip(),
            os.environ.get("TG_CHAT_ID", "").strip())


def tg_send_text(text):
    token, chat = tg_env()
    if not (token and chat):
        return False
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat, "text": text, "parse_mode": "Markdown"}).encode()
    try:
        with urllib.request.urlopen(url, data=body, timeout=45) as r:
            print("TG text:", r.status)
        return True
    except Exception as e:
        print("TG text gagal:", e)
        return False


def tg_send_photo(link, caption):
    token, chat = tg_env()
    if not (token and chat and link):
        return False
    url = "https://api.telegram.org/bot" + token + "/sendPhoto"
    body = urllib.parse.urlencode({"chat_id": chat, "photo": link, "caption": caption}).encode()
    try:
        with urllib.request.urlopen(url, data=body, timeout=45) as r:
            print("TG photo:", r.status)
        return True
    except Exception as e:
        print("TG photo gagal:", e)
        return False


# Jeda minimum antar-kirim (jam): cegah dobel bila run terpicu berdekatan,
# tapi tetap izinkan 3x kirim/hari karena jadwalnya berjauhan.
MIN_GAP_HOURS = 4


def recently_sent(now):
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return False
    ts = data.get("ts")
    if not ts:
        return False
    try:
        last = datetime.fromisoformat(ts)
    except Exception:
        return False
    if last.tzinfo is None:
        last = last.replace(tzinfo=now.tzinfo)
    return (now - last) < timedelta(hours=MIN_GAP_HOURS)


def mark_sent(now):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"date": now.date().isoformat(), "ts": now.isoformat()}, f)
        print("Status kirim disimpan:", now.isoformat())
    except Exception as e:
        print("Gagal simpan status:", e)


def main():
    cfg = load_json("config.json")
    jadwal = load_json("jadwal.json")
    cuaca = load_json(os.path.join("data", "cuaca.json"))
    offset = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    now = datetime.now(offset)
    today = now.date()

    force = os.environ.get("FORCE_SEND", "").strip().lower() == "true"
    if recently_sent(now) and not force:
        print("Baru saja kirim (< " + str(MIN_GAP_HOURS) + " jam lalu) - lewati.")
        return

    harv = harvin_latest(cfg)
    msg1 = build_headline(cfg, jadwal, cuaca, today, harv)
    parts = build_detail(cfg, jadwal, cuaca, today, harv)
    cu = chart_url(cfg)

    print("===== PESAN 1 (HEADLINE) =====\n" + msg1)
    for i, p in enumerate(parts, 1):
        print("\n===== DETAIL " + str(i) + " =====\n" + p)
    if harv:
        print("\nCitra terbaru:", harv["date"], "|", harv["truecolor"], "|", harv["ndvi"])
    print("=" * 30)

    wa_configured = bool(os.environ.get("WA_PHONE", "").strip() and os.environ.get("WA_APIKEY", "").strip())
    tg_configured = bool(os.environ.get("TG_TOKEN", "").strip() and os.environ.get("TG_CHAT_ID", "").strip())

    # ---- WhatsApp (CallMeBot): jumlah pesan dikurangi supaya tidak kena rate-limit ----
    wa_msgs = [msg1] + list(parts)
    links = []
    if cu:
        links.append("Grafik hujan & jadwal:\n" + cu)
    if harv:
        links.append("Warna asli (" + sat_label(harv) + "):\n" + harv["truecolor"])
        links.append("NDVI (" + sat_label(harv) + "):\n" + harv["ndvi"])
    if links:
        wa_msgs.append("\n\n".join(links))

    wa_ok = False
    if wa_configured:
        for i, m in enumerate(wa_msgs):
            if i:
                time.sleep(6)
            if wa_send(m):
                wa_ok = True
            elif i == 0:
                print("WhatsApp: pesan pertama gagal, hentikan sisa pesan (hindari blokir).")
                break

    # ---- Telegram (opsional): foto asli ----
    tg_ok = False
    if tg_configured and tg_send_text(msg1):
        tg_ok = True
        if cu:
            tg_send_photo(cu, "Curah hujan & jadwal")
        if harv:
            tg_send_photo(harv["truecolor"], "Warna asli - " + sat_label(harv))
            tg_send_photo(harv["ndvi"], "NDVI - " + sat_label(harv))
        for p2 in parts:
            tg_send_text(p2)

    # WhatsApp = kanal utama: hanya tandai "terkirim" bila WA berhasil, supaya
    # run terjadwal berikutnya otomatis mencoba lagi kalau WA gagal.
    if wa_ok:
        mark_sent(now)
    elif tg_ok and not wa_configured:
        mark_sent(now)

    if not (wa_configured or tg_configured):
        print("(Tidak ada secret notifikasi - mode uji saja.)")

    if wa_configured and not wa_ok:
        print("GAGAL: WhatsApp tidak terkirim (lihat respons CallMeBot di atas).")
        sys.exit(1)


if __name__ == "__main__":
    main()
