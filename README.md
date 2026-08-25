# Kebun Cuaca — Dashboard Hujan + Bot Harian

Web app gratis (GitHub Pages) + otomasi (GitHub Actions) yang:

1. **Menarik data hujan tiap hari** dari Open-Meteo (gratis, tanpa API key).
2. **Menampilkan dashboard** curah hujan harian + prakiraan, dengan **garis tanggal pupuk / pruning / tebas** supaya terlihat apakah jadwal pemupukan pas dengan hujan.
3. **Mengirim pesan harian jam 10 pagi** ke **WhatsApp** dan/atau **Telegram**: hujan hari ini, prakiraan 3 hari, dan pupuk berikutnya + saran.

Semua jalan sendiri — sekali pasang, tiap hari otomatis.

---

## Isi repo

| File | Fungsi |
|------|--------|
| `index.html` | Dashboard (halaman utama Pages) |
| `config.json` | Koordinat kebun + setelan (ambang hujan lebat/kering, dll) |
| `jadwal.json` | Tanggal pupuk / pruning / tebas — **kamu edit sendiri** |
| `data/cuaca.json` | Log hujan — dibuat & diperbarui otomatis |
| `scripts/fetch_weather.py` | Ambil data Open-Meteo → tulis `data/cuaca.json` |
| `scripts/notify.py` | Kirim pesan harian ke WA/Telegram |
| `.github/workflows/cuaca.yml` | Jadwal harian (cron) + jalankan kedua script |
| `.nojekyll` | Supaya Pages menyajikan file apa adanya |

> Data contoh sudah diisi di `data/cuaca.json` supaya dashboard langsung tampil. Saat workflow pertama jalan, data itu ditimpa data asli.

---

## Cara pasang (sekali saja)

### 1. Buat repo & upload
- Buat repo baru, misal **`kebun-sawit-cuaca`**.
- Upload SEMUA isi folder ini (termasuk folder `.github` dan `scripts`).

### 2. Aktifkan GitHub Pages
- Settings → **Pages** → Source: **Deploy from a branch** → `main` / `(root)` → **Save**.
- Setelah beberapa menit, dashboard hidup di:
  `https://<username>.github.io/kebun-sawit-cuaca/`
- Update baris `dashboard_url` di `config.json` dengan alamat itu (agar tautan muncul di pesan).

### 3. Sambungkan notifikasi (pilih salah satu / dua-duanya)

#### A. WhatsApp (lewat CallMeBot — gratis, pribadi)
1. Simpan nomor **+34 644 51 95 23** di kontak HP.
2. Kirim WhatsApp ke nomor itu: **`I allow callmebot to send me messages`**
3. Balasannya berisi **apikey** kamu.
4. Di GitHub: Settings → **Secrets and variables → Actions → New repository secret**, tambahkan:
   - `WA_PHONE` = nomor kamu format internasional tanpa `+`, contoh `628123456789`
   - `WA_APIKEY` = apikey dari balasan CallMeBot

#### B. Telegram (lewat BotFather — gratis)
1. Chat **@BotFather** → `/newbot` → ikuti langkah → dapat **token**.
2. Chat bot barumu (kirim `halo`), lalu buka:
   `https://api.telegram.org/bot<TOKEN>/getUpdates` untuk lihat **chat id** kamu.
3. Tambah secret di GitHub:
   - `TG_TOKEN` = token dari BotFather
   - `TG_CHAT_ID` = chat id kamu

> Set salah satu atau keduanya. Kalau tidak ada secret, workflow tetap jalan dan hanya mencetak pesan di log (mode uji).

### 4. Jalankan pertama kali
- Tab **Actions** → aktifkan workflow → **Cuaca Kebun (harian)** → **Run workflow**.
- Setelah selesai, `data/cuaca.json` terisi data asli dan kamu terima pesan pertama.

---

## Mengatur jadwal kirim

Di `.github/workflows/cuaca.yml`:
```yaml
- cron: "17 2 * * *"   # 10:17 WIB
- cron: "17 3 * * *"   # 11:17 WIB (cadangan)
- cron: "17 4 * * *"   # 12:17 WIB (cadangan) - notify.py kirim SEKALI per hari
```
Ubah angka bila mau jam lain. Rumus: **jam lokal − 8 = jam UTC**.

## Mengubah lokasi / ambang

Di `config.json`:
- `lat`, `lon` — titik tengah kebun.
- `heavy_rain_mm` (default 25) — di atas ini dianggap **hujan lebat** (risiko hara tercuci).
- `dry_threshold_mm` (default 2) — di bawah ini dianggap **kering** (hara lambat larut).

## Mengubah jadwal kebun

Edit `jadwal.json`. Contoh:
```json
{ "date": "2026-08-15", "type": "pupuk", "label": "NPK 16 HA" }
```
`type` bisa `pupuk`, `pruning`, atau `tebas`. Tanggal & garis di dashboard langsung ikut.

## Sumber titik api: NASA FIRMS (primer) + SIPONGI (sekunder)

Data karhutla utama tetap **NASA FIRMS** (VIIRS NOAA-20 & SNPP, perlu `FIRMS_MAP_KEY`).
Di atasnya ditambahkan **cek silang SIPONGI+ (Kemenhut)** dengan aturan yang sama
(radius `karhutla_warn_km`, arah mata angin, titik terdekat):

* FIRMS aktif & ada titik → SIPONGI hanya tampil sebagai baris pembanding.
* FIRMS aman/nihil, tapi SIPONGI melihat titik ≤ radius → status naik jadi **WASPADA** + catatan cek silang.
* `FIRMS_MAP_KEY` belum diatur → SIPONGI mengambil alih penilaian status.

**Tanpa input apa pun.** Koordinat sudah terpasang di `config.json` (`farm_lat` /
`farm_lon`) dan semua titik disaring otomatis berdasar jarak dari kebun —
tak perlu pilih provinsi/tanggal.

### Urutan sumber sekunder (3 lapis, otomatis)

1. **`sipongi_urls` / `sipongi_url`** dari `config.json` — kalau diisi manual.
2. **Auto-discovery** dari halaman [Data Hotspot SiPongi+](https://sipongi.gakkum.kehutanan.go.id/sebaran-titik-panas):
   HTML dan bundel `.js` dipindai untuk mencari endpoint data (KMZ/JSON/CSV).
3. **`sipongi_fallback_urls`** — layanan resmi pengganti yang stabil dan bisa
   dikueri: **BMKG GeoHotspot** (ArcGIS REST). Kueri dipersempit pakai kotak
   `{BBOX}` di sekitar kebun, jadi muatannya kecil.

> **Catatan penting.** SiPongi+ kini berupa aplikasi sisi-klien (SPA) dan tidak
> membuka endpoint unduhan publik yang stabil; domain lama `sipongi.menlhk.go.id`
> sudah mati. Karena itu lapis 3 disediakan supaya fungsi **cek silang tetap
> hidup**. Menarik: SIPONGI sendiri menerbitkan ulang data NASA (VIIRS/MODIS),
> sedangkan BMKG GeoHotspot memakai **Himawari-8** — sensor yang benar-benar
> independen dari FIRMS, jadi justru **lebih berguna** sebagai pembanding.

Setelan di `config.json` (semua opsional):

* `use_sipongi` — `true`/`false` untuk mematikan lapis sekunder.
* `sipongi_url` — cadangan terakhir saja; biasanya **dibiarkan kosong**.
* `sipongi_urls` — daftar URL yang dicoba berurutan (KMZ/TXT/CSV/JSON/ArcGIS).
* `sipongi_fallback_urls` — sumber pengganti; mendukung placeholder `{BBOX}`,
  `{LAT}`, `{LON}`.
* `sipongi_fallback_label` — nama sumber pengganti untuk atribusi.

**Atribusi otomatis & jujur.** Skrip menuliskan `fire.sipongi.source_label`
sesuai sumber yang benar-benar terbaca, dan dashboard/WhatsApp memakai label itu
— jadi kalau datanya dari BMKG, tulisannya "BMKG", bukan "SIPONGI".

> Setiap penggunaan data yang bersumber dari SIPONGI wajib mencantumkan:
> **SIPONGI KEMENHUT**. Data BMKG wajib mencantumkan sumber **BMKG**.

**Galat permanen tidak diulang.** HTTP 400/401/403/404/405/410 dan kegagalan DNS
langsung dilewati tanpa 3x percobaan, sehingga log Actions bersih dan tiap
jalannya hemat ±60 detik.

**Baris cek silang selalu kelihatan.** Kalau sumber ke-2 (SIPONGI) dan ke-3
(BMKG) dua-duanya gagal, barisnya tetap tampil dengan tanda hubung
(`Cek silang: —`) supaya jelas lapisannya terpasang tapi datanya belum masuk.
JSON lama yang belum punya blok `sipongi` tetap sunyi (mundur-kompatibel).

* * *

## (Opsional) NDVI di pesan

Sudah **disetel ke repo Harvin** kamu: `ndvi_url` = `https://zurplox.github.io/kebun-sawit/data.json`.
- Tinggal sesuaikan `ndvi_key` di `config.json` dengan nama field NDVI di `data.json` repo `kebun-sawit` (sekarang ditebak `ndvi_mean`).
- Kalau nama field-nya beda / belum ada, baris NDVI otomatis dilewati (aman).

---

## Catatan agronomi (kenapa hujan penting untuk pupuk)

- **Terlalu kering** saat memupuk → butiran lambat larut, hara tidak terserap.
- **Hujan lebat tepat setelah memupuk** → hara (terutama N & K) tercuci/hanyut, boros biaya.
- **Sasaran ideal**: tanah lembap, hujan ringan–sedang di sekitar tanggal pemupukan.

Dashboard & pesan menandai kondisi ini otomatis (hijau = baik, oranye = kering, merah = terlalu basah).


---

## Peningkatan (versi ini)

- **Anti-gagal kirim:** workflow jalan 3x pagi (10:17 / 11:17 / 12:17 WIB). `notify.py` hanya mengirim SEKALI per hari (dicatat di `data/last_sent.json`), jadi tidak dobel.
- **Peringatan bila error:** kalau workflow gagal, kamu dapat WhatsApp "Cuaca Kebun GAGAL" (`scripts/alert_fail.py`).
- **Versi matplotlib dikunci:** `matplotlib>=3.8,<4.0` supaya update besar tidak tiba-tiba merusak grafik.
- **Retry API:** `fetch_weather.py` mencoba 3x kalau Open-Meteo sedang gangguan.
- **Riwayat 1 tahun:** data hujan disimpan maksimal 365 hari (`MAX_HISTORY_DAYS`).
- **Run manual selalu kirim:** menjalankan lewat tombol Run workflow memakai FORCE_SEND=true (abaikan anti-dobel) untuk tes.

### Kaitan dengan neraca air

Info **banjir (debit sungai)** dan **air pasang** tidak berdiri sendiri — keduanya
dihubungkan dengan **neraca air 30 hari** (curah hujan) supaya saling melengkapi:

- **Neraca air berlebih + sungai naik / pasang tinggi** → air menumpuk: utamakan
  drainase, tunda pemupukan (hara mudah tercuci), waspada genangan.
- **Neraca air kurang + sungai surut** → cadangan air menipis: tahan buka parit,
  tunda pemupukan sampai tanah lembap.
- **Neraca air cukup** → banjir & pasang belum mengancam, kondisi seimbang.

Baris "🔗 Kaitan neraca air" ini muncul di pesan WhatsApp (blok Lingkungan,
tepat di atas Jadwal kegiatan) dan sebagai kartu di dashboard.
