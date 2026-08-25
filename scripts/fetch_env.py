#!/usr/bin/env python3
"""Ambil data LINGKUNGAN sekitar kebun -> data/lingkungan.json.

Semua sumber GRATIS:
  1. Karhutla (titik api) - NASA FIRMS Area API (perlu FIRMS_MAP_KEY gratis).
     -> status peringatan + titik api TERDEKAT (jarak km + arah + wilayah).
     Ditambah cek silang SIPONGI+ (Kemenhut) sebagai SUMBER SEKUNDER dengan
     aturan yang sama; FIRMS tetap primer. Wajib cantum: SIPONGI KEMENHUT.
  2. Kualitas udara - Open-Meteo Air Quality API (tanpa key).
  3. Banjir / tinggi air - Open-Meteo Flood API (debit sungai, tanpa key).
  4. Air pasang (pasang surut) - Open-Meteo Marine API (tanpa key) di titik
     pesisir TERDEKAT (kebun di darat, jadi pasang diambil dari laut terdekat:
     Selat Malaka di timur laut).

Titik acuan = koordinat kebun Harvin (Rawang Air Putih, Siak, Riau):
  farm_lat / farm_lon di config.json.

Hanya modul standar Python. Dijalankan oleh GitHub Actions.
"""
import csv
import io
import json
import math
import os
import re
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")
OUT_PATH = os.path.join(ROOT, "data", "lingkungan.json")
CUACA_PATH = os.path.join(ROOT, "data", "cuaca.json")

# Titik laut kandidat di Selat Malaka (timur laut kebun) untuk data pasang surut.
# Kebun di darat -> Marine API tak punya data di titik kebun; pakai titik laut
# terdekat yang mengembalikan data. Diurut otomatis berdasar jarak dari kebun.
TIDE_CANDIDATES = [
    (1.30, 102.35, "Selat Malaka (dekat Sungai Apit)"),
    (1.50, 102.30, "Selat Malaka (lepas pantai Siak)"),
    (1.70, 102.50, "Selat Malaka"),
    (1.95, 102.30, "Selat Malaka (dekat Bengkalis)"),
    (2.20, 102.60, "Selat Malaka"),
]

COMPASS8 = ["utara", "timur laut", "timur", "tenggara",
            "selatan", "barat daya", "barat", "barat laut"]


def load_config():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _get(url, headers=None, timeout=60, as_json=True):
    last = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                url, headers=headers or {"User-Agent": "kebun-lingkungan/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8", "replace")
            return json.loads(raw) if as_json else raw
        except Exception as e:
            last = e
            print("Percobaan " + str(attempt) + "/3 gagal:", e)
            if attempt < 3:
                time.sleep(4 * attempt)
    if last:
        print("Menyerah:", last)
    return None


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_compass(lat1, lon1, lat2, lon2, pts=COMPASS8):
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(math.radians(lat2))
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dl))
    brng = (math.degrees(math.atan2(y, x)) + 360) % 360
    idx = int((brng / (360 / len(pts))) + 0.5) % len(pts)
    return pts[idx]


def reverse_geocode(lat, lon):
    url = ("https://api.bigdatacloud.net/data/reverse-geocode-client?latitude="
           + str(lat) + "&longitude=" + str(lon) + "&localityLanguage=id")
    d = _get(url)
    if not isinstance(d, dict):
        return None
    parts = []
    for k in ("locality", "city", "principalSubdivision"):
        v = d.get(k)
        if v and v not in parts:
            parts.append(v)
    return ", ".join(parts) if parts else None


# ---------- 1) KARHUTLA (NASA FIRMS) ----------
def fetch_fire(cfg):
    lat = cfg["farm_lat"]
    lon = cfg["farm_lon"]
    warn_km = cfg.get("karhutla_warn_km", 50)
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        return {"status": "tidak tersedia", "note": "FIRMS_MAP_KEY belum diatur",
                "warn_km": warn_km, "nearest": None, "count_within": 0}
    deg = cfg.get("karhutla_scan_deg", 2.5)
    days = cfg.get("fire_day_range", 2)
    box = "%.4f,%.4f,%.4f,%.4f" % (lon - deg, lat - deg, lon + deg, lat + deg)
    sources = cfg.get("firms_sources") or ["VIIRS_NOAA20_NRT", "VIIRS_SNPP_NRT"]
    rows = []
    for src in sources:
        url = ("https://firms.modaps.eosdis.nasa.gov/api/area/csv/" + key + "/"
               + src + "/" + box + "/" + str(days))
        txt = _get(url, as_json=False)
        if not txt or "," not in txt:
            continue
        try:
            for row in csv.DictReader(io.StringIO(txt)):
                rows.append(row)
        except Exception as e:
            print("FIRMS parse gagal:", e)
    pts = []
    for r in rows:
        try:
            la = float(r.get("latitude"))
            lo = float(r.get("longitude"))
        except Exception:
            continue
        pts.append((haversine_km(lat, lon, la, lo), la, lo, r))
    if not pts:
        return {"status": "aman", "warn_km": warn_km, "nearest": None,
                "count_within": 0, "scanned_days": days}
    pts.sort(key=lambda x: x[0])
    within = [p for p in pts if p[0] <= warn_km]
    km, la, lo, r = pts[0]
    acq_fmt = r.get("acq_date", "")  # tanggal saja, tanpa jam
    nearest = {
        "km": round(km, 1),
        "dir": bearing_compass(lat, lon, la, lo),
        "lat": round(la, 4), "lon": round(lo, 4),
        "place": reverse_geocode(la, lo),
        "acq": acq_fmt.strip(),
        "sat": r.get("satellite") or r.get("instrument"),
        "confidence": r.get("confidence"),
        "frp": r.get("frp"),
    }
    if km <= warn_km:
        status = "bahaya" if (km <= warn_km / 2 or len(within) >= 5) else "waspada"
    else:
        status = "aman"
    return {"status": status, "warn_km": warn_km, "nearest": nearest,
            "count_within": len(within), "scanned_days": days}


def fire_weather_risk(cfg):
    """Risiko cuaca kebakaran dari cuaca.json: hari kering beruntun + kelembapan."""
    try:
        with open(CUACA_PATH, encoding="utf-8") as f:
            c = json.load(f)
    except Exception:
        return None
    td = c.get("today") or {}
    hum = td.get("humidity")
    by = {d["date"]: d for d in c.get("days", [])}
    off = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    today = datetime.now(off).date()
    dry = cfg.get("dry_threshold_mm", 2)
    streak = 0
    for i in range(0, 14):
        r = by.get((today + timedelta(days=i)).isoformat())
        if r and r.get("precip") is not None and r["precip"] < dry:
            streak += 1
        else:
            break
    level = "rendah"
    if streak >= 7 or (hum is not None and hum < 55):
        level = "tinggi"
    elif streak >= 3:
        level = "sedang"
    return {"level": level, "dry_streak": streak, "humidity": hum}


# ---------- 1b) KARHUTLA SEKUNDER: SIPONGI+ (Kemenhut) ----------
# FIRMS tetap PRIMER. SIPONGI hanya lapisan cek silang dengan aturan yang
# sama: radius peringatan (karhutla_warn_km), arah mata angin, titik terdekat.
# Data diambil dari unduhan publik halaman Data > Hotspot SiPongi+
# (format KMZ / TXT / JSON didukung). Wajib cantum sumber: SIPONGI KEMENHUT.
SIPONGI_LAT_KEYS = ("lat", "latitude", "lintang", "y")
SIPONGI_LON_KEYS = ("lon", "lng", "long", "longitude", "bujur", "x")
SIPONGI_CONF_KEYS = ("kepercayaan", "confidence", "conf", "level")


def _get_bytes(url, timeout=60):
    last = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "kebun-lingkungan/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            print("SIPONGI percobaan " + str(attempt) + "/3 gagal:", e)
            if attempt < 3:
                time.sleep(4 * attempt)
    if last:
        print("SIPONGI menyerah:", last)
    return None


def _parse_kmz(raw):
    """KMZ = zip berisi KML. Ambil koordinat tiap Placemark."""
    pts = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except Exception:
        return pts
    for name in zf.namelist():
        if not name.lower().endswith(".kml"):
            continue
        try:
            root = ET.fromstring(zf.read(name))
        except Exception:
            continue
        for pm in root.iter():
            if not pm.tag.split("}")[-1] == "Placemark":
                continue
            nm = desc = coord = None
            for el in pm.iter():
                t = el.tag.split("}")[-1]
                if t == "name" and nm is None:
                    nm = (el.text or "").strip()
                elif t == "description" and desc is None:
                    desc = (el.text or "").strip()
                elif t == "coordinates" and coord is None:
                    coord = (el.text or "").strip()
            if not coord:
                continue
            try:
                parts = coord.split(",")
                lo, la = float(parts[0]), float(parts[1])
            except Exception:
                continue
            pts.append({"lat": la, "lon": lo, "name": nm or "",
                        "conf": None, "date": ""})
    return pts


def _walk_json_points(obj, out):
    """Cari rekursif objek dengan kolom lat+lon di JSON."""
    if isinstance(obj, dict):
        ks = {str(k).lower(): k for k in obj.keys()}
        la_k = next((ks[k] for k in SIPONGI_LAT_KEYS if k in ks), None)
        lo_k = next((ks[k] for k in SIPONGI_LON_KEYS if k in ks), None)
        if la_k and lo_k:
            try:
                out.append({
                    "lat": float(obj[la_k]), "lon": float(obj[lo_k]),
                    "conf": next((str(obj[ks[k]]) for k in SIPONGI_CONF_KEYS
                                  if k in ks), None),
                    "name": str(obj.get("kab_kota") or obj.get("kabupaten")
                                or obj.get("name") or ""),
                    "date": str(obj.get("tanggal") or obj.get("date")
                                or obj.get("acq_date") or "")})
                return
            except Exception:
                pass
        for v in obj.values():
            _walk_json_points(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_json_points(v, out)


def _parse_txt_points(txt):
    """CSV/TXT: pakai header lat/lon bila ada, kalau tidak tebak dua kolom
    angka dalam rentang Indonesia (lat -11.5..6.5, lon 94..141.5)."""
    head = txt[:2000].lower()
    if "<html" in head or "<!doctype" in head:
        return []
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    if not lines:
        return []
    dialect = None
    try:
        dialect = csv.Sniffer().sniff("\n".join(lines[:20]),
                                      delimiters=",;\t|")
    except Exception:
        pass
    rows = []
    if dialect:
        try:
            rows = [r for r in csv.reader(io.StringIO(txt), dialect)
                    if any(c.strip() for c in r)]
        except Exception:
            rows = []
    if not rows:
        rows = [ln.split() for ln in lines]
    hdr = None
    for i, r in enumerate(rows[:10]):
        low = [c.strip().lower() for c in r]
        if any(c in SIPONGI_LAT_KEYS for c in low) and \
                any(c in SIPONGI_LON_KEYS for c in low):
            hdr = i
            break
    pts = []
    if hdr is not None:
        low = [c.strip().lower() for c in rows[hdr]]
        li = next(i for i, c in enumerate(low) if c in SIPONGI_LAT_KEYS)
        lo_i = next(i for i, c in enumerate(low) if c in SIPONGI_LON_KEYS)
        ci = next((i for i, c in enumerate(low) if c in SIPONGI_CONF_KEYS), None)
        for r in rows[hdr + 1:]:
            try:
                pts.append({"lat": float(r[li]), "lon": float(r[lo_i]),
                            "conf": (r[ci].strip()
                                     if ci is not None and ci < len(r) else None),
                            "name": "", "date": ""})
            except Exception:
                continue
        return pts
    for r in rows:
        la = lo = None
        for c in r:
            try:
                v = float(c)
            except Exception:
                continue
            if -11.5 <= v <= 6.5 and la is None:
                la = v
            elif 94.0 <= v <= 141.5 and lo is None:
                lo = v
        if la is not None and lo is not None:
            pts.append({"lat": la, "lon": lo, "conf": None, "name": "", "date": ""})
    return pts


SIPONGI_PAGES = (
    "https://sipongi.gakkum.kehutanan.go.id/sebaran-titik-panas",
    "https://sipongi.menlhk.go.id/sebaran-titik-panas",
)


def _fetch_sipongi_points(url):
    """Unduh satu URL SIPONGI lalu urai sesuai format (KMZ/JSON/TXT)."""
    raw = _get_bytes(url)
    if not raw:
        return []
    if raw[:2] == b"PK":
        return _parse_kmz(raw)
    t = raw.decode("utf-8", "replace").lstrip("\ufeff").lstrip()
    if t.startswith("{") or t.startswith("["):
        pts = []
        try:
            _walk_json_points(json.loads(t), pts)
        except Exception as e:
            print("SIPONGI JSON parse gagal:", e)
        return pts
    return _parse_txt_points(t)


def discover_sipongi_urls():
    """Temukan tautan unduhan (KMZ/TXT/CSV/JSON) langsung dari halaman
    Data > Hotspot SiPongi+ — otomatis, tanpa input manual."""
    found = []
    for page in SIPONGI_PAGES:
        raw = _get_bytes(page)
        if not raw:
            continue
        html = raw.decode("utf-8", "replace")
        for m in re.finditer(r"""(?:href|action|src)=["']([^"']+)["']""",
                             html, re.I):
            u = m.group(1).strip()
            low = u.lower()
            if "xlsx" in low:
                continue  # XLSX tak diurai (cukup KMZ/TXT/CSV/JSON)
            if not any(k in low for k in ("unduh", "download", "export",
                                          ".kmz", ".txt", ".csv")):
                continue
            u = urljoin(page, u)
            if u not in found:
                found.append(u)
    # KMZ duluan (paling rapi), lalu TXT/CSV/JSON
    found.sort(key=lambda u: (0 if "kmz" in u.lower() else 1, u))
    return found


def fetch_fire_sipongi(cfg):
    """Titik panas SIPONGI+ (SUMBER SEKUNDER) -> dict sebentuk fetch_fire."""
    if not cfg.get("use_sipongi", True):
        return None
    lat = cfg["farm_lat"]
    lon = cfg["farm_lon"]
    warn_km = cfg.get("karhutla_warn_km", 50)
    urls = []
    if cfg.get("sipongi_url"):
        urls.append(cfg["sipongi_url"])
    urls += [u for u in (cfg.get("sipongi_urls") or []) if u not in urls]
    pts, used = [], None
    for url in urls:
        pts = _fetch_sipongi_points(url)
        if pts:
            used = url
            break
    if used is None:
        # Daftar URL gagal/kosong -> cari tautan unduhan otomatis dari
        # halaman SiPongi+ (tanpa input manual sama sekali).
        for url in discover_sipongi_urls():
            if url in urls:
                continue
            pts = _fetch_sipongi_points(url)
            if pts:
                used = url
                break
    if used is None:
        return {"status": "tidak tersedia",
                "note": "Semua URL SIPONGI gagal diunduh/dibaca",
                "warn_km": warn_km, "nearest": None, "count_within": 0}
    geo = []
    for p in pts:
        try:
            la, lo = float(p["lat"]), float(p["lon"])
        except Exception:
            continue
        if not (-11.5 <= la <= 6.5 and 94.0 <= lo <= 141.5):
            continue
        geo.append((haversine_km(lat, lon, la, lo), la, lo, p))
    if not geo:
        return {"status": "aman", "warn_km": warn_km, "nearest": None,
                "count_within": 0, "total_points": 0, "source_url": used}
    geo.sort(key=lambda x: x[0])
    within = [g for g in geo if g[0] <= warn_km]
    km, la, lo, p = geo[0]
    nearest = {"km": round(km, 1), "dir": bearing_compass(lat, lon, la, lo),
               "lat": round(la, 4), "lon": round(lo, 4),
               "place": reverse_geocode(la, lo) if km <= warn_km * 2 else None,
               "acq": (p.get("date") or "").strip() or None,
               "sat": "SIPONGI", "confidence": p.get("conf"), "frp": None,
               "src": "SIPONGI"}
    if km <= warn_km:
        status = "bahaya" if (km <= warn_km / 2 or len(within) >= 5) else "waspada"
    else:
        status = "aman"
    return {"status": status, "warn_km": warn_km, "nearest": nearest,
            "count_within": len(within), "total_points": len(geo),
            "source_url": used}


def combine_fire(fire, sp, cfg):
    """Gabungkan FIRMS (primer) + SIPONGI (sekunder). Aturan jarak/status sama.
    SIPONGI hanya menaikkan kewaspadaan bila FIRMS nonaktif atau nihil."""
    fire = fire or {"status": "tidak tersedia"}
    if not sp:
        return fire
    fire["sipongi"] = sp
    if sp.get("status") == "tidak tersedia":
        return fire
    if fire.get("status") == "tidak tersedia":
        # FIRMS nonaktif (mis. FIRMS_MAP_KEY kosong) -> SIPONGI mengambil alih.
        fire["status"] = sp.get("status")
        fire["nearest"] = sp.get("nearest")
        fire["count_within"] = sp.get("count_within", 0)
        fire["primary_src"] = "SIPONGI"
        return fire
    fire["primary_src"] = "FIRMS"
    if fire.get("status") == "aman" and sp.get("status") in ("waspada", "bahaya"):
        # FIRMS bilang aman tapi SIPONGI melihat titik dekat -> waspada.
        warn = sp.get("warn_km", cfg.get("karhutla_warn_km", 50))
        sn = sp.get("nearest") or {}
        fire["status"] = "waspada"
        fire["crosscheck"] = (
            "SIPONGI mendeteksi " + str(sp.get("count_within", 0))
            + " titik \u2264" + str(warn) + " km"
            + ((" \u00b7 terdekat " + str(sn.get("km")) + " km ("
                + str(sn.get("dir", "")) + ")")
               if sn.get("km") is not None else "")
            + " \u2014 FIRMS nihil/aman")
    return fire


# ---------- 2) KUALITAS UDARA (Open-Meteo Air Quality) ----------
def aqi_category(aqi):
    if aqi is None:
        return ("tidak tersedia", "muted")
    if aqi <= 50:
        return ("Baik", "green")
    if aqi <= 100:
        return ("Sedang", "gold")
    if aqi <= 150:
        return ("Tidak sehat (kel. sensitif)", "orange")
    if aqi <= 200:
        return ("Tidak sehat", "red")
    if aqi <= 300:
        return ("Sangat tidak sehat", "red")
    return ("Berbahaya", "red")


def haze_category(aod):
    if aod is None:
        return ("tidak tersedia", "muted")
    if aod < 0.3:
        return ("cerah", "green")
    if aod < 0.6:
        return ("berkabut tipis", "gold")
    if aod < 1.0:
        return ("berasap/berkabut", "orange")
    return ("asap tebal", "red")


def uv_category(uv):
    if uv is None:
        return "tidak tersedia"
    if uv < 3:
        return "rendah"
    if uv < 6:
        return "sedang"
    if uv < 8:
        return "tinggi"
    if uv < 11:
        return "sangat tinggi"
    return "ekstrem"


def fetch_air(cfg):
    url = ("https://air-quality-api.open-meteo.com/v1/air-quality?latitude="
           + str(cfg["farm_lat"]) + "&longitude=" + str(cfg["farm_lon"])
           + "&current=pm2_5,pm10,us_aqi,aerosol_optical_depth,dust,uv_index&timezone=auto")
    d = _get(url)
    if not isinstance(d, dict):
        return None
    cur = d.get("current", {})
    aqi = cur.get("us_aqi")
    cat, color = aqi_category(aqi)
    aod = cur.get("aerosol_optical_depth")
    dust = cur.get("dust")
    uv = cur.get("uv_index")
    hcat, hcolor = haze_category(aod)
    return {"us_aqi": aqi, "pm2_5": cur.get("pm2_5"), "pm10": cur.get("pm10"),
            "category": cat, "color": color,
            "aod": round(aod, 2) if aod is not None else None,
            "dust": round(dust) if dust is not None else None,
            "haze": hcat, "haze_color": hcolor,
            "uv": round(uv, 1) if uv is not None else None,
            "uv_cat": uv_category(uv)}


# ---------- 3) BANJIR / DEBIT SUNGAI (Open-Meteo Flood) ----------
def fetch_flood(cfg):
    url = ("https://flood-api.open-meteo.com/v1/flood?latitude="
           + str(cfg["farm_lat"]) + "&longitude=" + str(cfg["farm_lon"])
           + "&daily=river_discharge&past_days=7&forecast_days=3")
    d = _get(url)
    if not isinstance(d, dict):
        return None
    daily = d.get("daily", {})
    dates = daily.get("time", [])
    disch = daily.get("river_discharge", [])
    if not dates:
        return None
    off = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    today = datetime.now(off).date().isoformat()
    idx = dates.index(today) if today in dates else len(dates) - 1
    val = disch[idx] if idx < len(disch) else None
    prev = [disch[i] for i in range(max(0, idx - 3), idx)
            if i < len(disch) and disch[i] is not None]
    trend = "stabil"
    if val is not None and prev:
        pm = sum(prev) / len(prev)
        if val > pm * 1.1:
            trend = "naik"
        elif val < pm * 0.9:
            trend = "turun"
    fut = [disch[i] for i in range(idx + 1, min(len(disch), idx + 4))
           if disch[i] is not None]
    prev7 = [disch[i] for i in range(max(0, idx - 7), idx)
             if i < len(disch) and disch[i] is not None]
    base = None
    if prev7:
        sp = sorted(prev7)
        base = sp[len(sp) // 2]  # median 7 hari
    ratio = (val / base) if (val is not None and base) else None
    if ratio is None:
        status = "tidak tersedia"
    elif ratio < 1.15:
        status = "Normal"
    elif ratio < 1.5:
        status = "Agak tinggi"
    elif ratio < 2.0:
        status = "Tinggi"
    else:
        status = "Sangat tinggi"
    return {"river_discharge": round(val, 1) if val is not None else None,
            "unit": "m3/s", "trend": trend,
            "peak_next3": round(max(fut), 1) if fut else None,
            "baseline": round(base, 1) if base is not None else None,
            "ratio_pct": round(ratio * 100) if ratio is not None else None,
            "status": status}


def tide_extremes(pairs):
    """Semua titik balik pasang/surut dari deret ketinggian per jam."""
    ext = []
    prev_sign = 0
    for i in range(1, len(pairs)):
        d = pairs[i][1] - pairs[i - 1][1]
        s = 1 if d > 0.005 else (-1 if d < -0.005 else 0)
        if s == 0:
            continue
        if prev_sign != 0 and s != prev_sign:
            typ = "pasang" if prev_sign > 0 else "surut"
            ext.append({"type": typ,
                        "h": round(pairs[i - 1][1], 2),
                        "time": pairs[i - 1][0][11:16]})
        prev_sign = s
    return ext


# ---------- 4) AIR PASANG (Open-Meteo Marine) ----------
# ---------- Prediksi pasang jangka panjang (analisis harmonik) ----------
# Pasang bersifat astronomis & periodik, jadi bisa diprediksi jauh ke depan
# dengan mencocokkan konstituen pasang utama (M2, S2, K1, O1, dll) ke data
# historis + prakiraan, lalu memproyeksikannya ke depan. Hanya komponen
# astronomis; efek cuaca/surge tak diprediksi di luar jangkauan model (~16 hr).
TIDE_CONSTITUENTS = [
    ("M2", 28.9841042), ("S2", 30.0), ("N2", 28.4397295), ("K2", 30.0821373),
    ("K1", 15.0410686), ("O1", 13.9430356), ("P1", 14.9589314), ("Q1", 13.3986609),
    ("Mf", 1.0980331), ("Mm", 0.5443747),
]


def _solve_linear(A, b):
    n = len(A)
    M = [list(A[i]) + [b[i]] for i in range(n)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        pv = M[col][col]
        for j in range(col, n + 1):
            M[col][j] /= pv
        for r in range(n):
            if r != col and M[r][col]:
                f = M[r][col]
                for j in range(col, n + 1):
                    M[r][j] -= f * M[col][j]
    return [M[i][n] for i in range(n)]


def _tide_design(t):
    row = [1.0]
    for (_, sp) in TIDE_CONSTITUENTS:
        ph = math.radians(sp * t)
        row.append(math.cos(ph))
        row.append(math.sin(ph))
    return row


def tide_harmonic_fit(times_h, heights):
    ncol = 1 + 2 * len(TIDE_CONSTITUENTS)
    ATA = [[0.0] * ncol for _ in range(ncol)]
    ATb = [0.0] * ncol
    for t, y in zip(times_h, heights):
        row = _tide_design(t)
        for i in range(ncol):
            ATb[i] += row[i] * y
            ri = row[i]
            for j in range(i, ncol):
                ATA[i][j] += ri * row[j]
    for i in range(ncol):
        for j in range(i):
            ATA[i][j] = ATA[j][i]
    return _solve_linear(ATA, ATb)


def tide_harmonic_value(coef, t):
    row = _tide_design(t)
    return sum(coef[i] * row[i] for i in range(len(coef)))


def fetch_tide(cfg):
    lat = cfg["farm_lat"]
    lon = cfg["farm_lon"]
    off = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    today = datetime.now(off).date().isoformat()
    fdays = int(cfg.get("tide_forecast_days", 16) or 16)
    fdays = max(1, min(16, fdays))
    pdays = int(cfg.get("tide_past_days", 60) or 0)
    pdays = max(0, min(92, pdays))
    predict_days = int(cfg.get("tide_predict_days", 30) or 30)
    predict_days = max(fdays, min(60, predict_days))
    cands = []
    if cfg.get("tide_lat") is not None and cfg.get("tide_lon") is not None:
        cands.append((cfg["tide_lat"], cfg["tide_lon"],
                      cfg.get("tide_name") or "Pesisir terdekat"))
    cands += TIDE_CANDIDATES
    cands.sort(key=lambda c: haversine_km(lat, lon, c[0], c[1]))
    for (tlat, tlon, name) in cands:
        url = ("https://marine-api.open-meteo.com/v1/marine?latitude="
               + str(tlat) + "&longitude=" + str(tlon)
               + "&hourly=sea_level_height_msl&timezone=auto&forecast_days=" + str(fdays)
               + "&past_days=" + str(pdays))
        d = _get(url)
        if not isinstance(d, dict):
            continue
        h = d.get("hourly", {})
        times = h.get("time", [])
        lv = h.get("sea_level_height_msl", [])
        all_pairs = [(times[i], lv[i]) for i in range(min(len(times), len(lv)))
                     if lv[i] is not None]
        if not all_pairs:
            continue
        all_pairs.sort(key=lambda p: p[0])
        pairs = [p for p in all_pairs if p[0][:10] == today] or all_pairs
        hi = max(pairs, key=lambda p: p[1])
        lo = min(pairs, key=lambda p: p[1])
        t0 = datetime.strptime(all_pairs[0][0][:16], "%Y-%m-%dT%H:%M")

        def _th(ts):
            return (datetime.strptime(ts[:16], "%Y-%m-%dT%H:%M") - t0).total_seconds() / 3600.0

        by_day = {}
        for (tt, vv) in all_pairs:
            by_day.setdefault(tt[:10], []).append((tt, vv))
        daily = []
        for day in sorted(by_day.keys()):
            if day < today:
                continue
            dps = by_day[day]
            dh = max(dps, key=lambda p: p[1])
            dl = min(dps, key=lambda p: p[1])
            daily.append({"date": day,
                          "high": round(dh[1], 2), "high_time": dh[0][11:16],
                          "low": round(dl[1], 2), "low_time": dl[0][11:16]})
        # Perpanjang ke predict_days via prediksi harmonik (astronomis).
        have = set(x["date"] for x in daily)
        coef = None
        try:
            coef = tide_harmonic_fit([_th(p[0]) for p in all_pairs],
                                     [p[1] for p in all_pairs])
        except Exception as _e:
            coef = None
        if coef:
            base = datetime.strptime(today, "%Y-%m-%d")
            for k in range(predict_days):
                day = (base + timedelta(days=k)).strftime("%Y-%m-%d")
                if day in have:
                    continue
                best_h = best_t = low_h = low_t = None
                for m in range(48):
                    ts = day + "T%02d:%02d" % (m // 2, 30 * (m % 2))
                    val = tide_harmonic_value(coef, _th(ts))
                    if best_h is None or val > best_h:
                        best_h, best_t = val, ts[11:16]
                    if low_h is None or val < low_h:
                        low_h, low_t = val, ts[11:16]
                daily.append({"date": day,
                              "high": round(best_h, 2), "high_time": best_t,
                              "low": round(low_h, 2), "low_time": low_t,
                              "est": True})
            daily.sort(key=lambda x: x["date"])
        return {"point_name": name, "lat": tlat, "lon": tlon,
                "km": round(haversine_km(lat, lon, tlat, tlon)),
                "dir": bearing_compass(lat, lon, tlat, tlon),
                "high": {"h": round(hi[1], 2), "time": hi[0][11:16]},
                "low": {"h": round(lo[1], 2), "time": lo[0][11:16]},
                "extremes": tide_extremes(pairs),
                "daily": daily}
    return None


def main():
    cfg = load_config()
    off = timezone(timedelta(hours=cfg.get("utc_offset_hours", 8)))
    fire = fetch_fire(cfg)
    try:
        fire["weather_risk"] = fire_weather_risk(cfg)
    except Exception as e:
        print("Risiko cuaca kebakaran gagal:", e)
    try:
        fire = combine_fire(fire, fetch_fire_sipongi(cfg), cfg)
    except Exception as e:
        print("SIPONGI gagal (diabaikan, FIRMS tetap primer):", e)
    out = {
        "updated_at": datetime.now(off).isoformat(timespec="minutes"),
        "farm": {"lat": cfg["farm_lat"], "lon": cfg["farm_lon"],
                 "name": cfg.get("farm_name", "Kebun")},
        "fire": fire,
        "air": fetch_air(cfg),
        "flood": fetch_flood(cfg),
        "tide": fetch_tide(cfg),
    }
    fl, fo = cfg["farm_lat"], cfg["farm_lon"]
    if out.get("fire"):
        out["fire"]["map"] = ("https://firms.modaps.eosdis.nasa.gov/map/#d:24hrs;@"
                              + "{:.3f},{:.3f},9z".format(fo, fl))
        _nr = out["fire"].get("nearest") or {}
        if _nr.get("lat") is not None:
            out["fire"]["map_google"] = "https://www.google.com/maps?q=" + str(_nr["lat"]) + "," + str(_nr["lon"])
    if out.get("flood"):
        out["flood"]["map"] = "https://sites.research.google/floods/l/" + format(fl, ".3f") + "/" + format(fo, ".3f") + "/9"
    if out.get("tide") and out["tide"].get("lat") is not None:
        out["tide"]["map"] = "https://www.google.com/maps?q=" + str(out["tide"]["lat"]) + "," + str(out["tide"]["lon"])
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("OK: data/lingkungan.json tersimpan.")
    print(json.dumps(out, ensure_ascii=False)[:600])


if __name__ == "__main__":
    main()
