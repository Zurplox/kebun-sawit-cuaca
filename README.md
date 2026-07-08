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
