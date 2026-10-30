# playstore-reviews

Web app Flask untuk menarik (scrape) review aplikasi Play Store, menyimpannya sebagai
JSON lokal, lalu menjelajahinya di browser. Default target: **PLN Mobile**
(`com.icon.pln123`).

UI-nya bergaya koran ("The Review Wire") dan berjalan sepenuhnya lokal — tidak ada data
yang dikirim ke pihak ketiga selain permintaan ke Play Store.

## Menjalankan

Virtual environment `appreviewvenv/` sudah disiapkan dan berisi Flask +
`google-play-scraper`.

```powershell
# dari folder playstore-reviews
.\appreviewvenv\Scripts\python.exe app.py
```

Buka <http://localhost:5000>.

Kalau ingin pasang dari nol:

```powershell
python -m venv appreviewvenv
.\appreviewvenv\Scripts\python.exe -m pip install -r requirements.txt
```

Konfigurasi opsional lewat environment variable:

| Variable | Default | Keterangan |
|---|---|---|
| `PORT` | `5000` | Port server Flask |
| `FLASK_DEBUG` | `0` | Set `1` untuk mode debug/reload |

## Cara pakai

1. Tempel package ID (`com.icon.pln123`) atau URL Play Store lengkap.
2. Pilih bintang yang mau diambil — kalau tidak ada yang dipilih, semua rating diambil.
3. Tentukan jumlah review, urutan, serta bahasa/negara (default `id`/`id`).
4. Klik **Run the scrape**. Hasilnya tampil di panel kanan dan otomatis tersimpan ke
   `data/`.

Panel kiri bawah (**Filed Dispatches**) berisi hasil scrape sebelumnya; klik untuk
membuka, atau ekspor ulang ke JSON/CSV.

## Endpoint

| Method | Path | Fungsi |
|---|---|---|
| `GET` | `/` | Halaman aplikasi |
| `GET` | `/api/app-info?app_id=...` | Metadata app (nama, ikon, developer, rating) |
| `POST` | `/api/scrape` | Scrape review; body JSON: `app_id`, `count`, `scores`, `sort`, `lang`, `country` |
| `GET` | `/api/saved` | Daftar file hasil scrape (meta + statistik saja) |
| `GET` | `/api/saved/<filename>` | Isi lengkap satu file |
| `GET` | `/api/saved/<filename>/export?format=csv` | Unduh satu file sebagai CSV (UTF-8 BOM, siap Excel) |
| `DELETE` | `/api/saved/<filename>` | Hapus satu file |

## Struktur file

```
app.py                  # Backend Flask (scraper + API + export)
static/index.html       # Seluruh UI (HTML/CSS/JS, tanpa build step)
data/                   # Hasil scrape JSON (tidak di-commit)
requirements.txt        # Dependensi web app
```

Format satu file di `data/`:

```jsonc
{
  "meta": {
    "appId": "com.icon.pln123",
    "requestedCount": 1000,
    "starsFilter": [1, 2, 3, 4, 5],
    "perStar": { "1": 200, "2": 200, "3": 200, "4": 200, "5": 200 },
    "lang": "id", "country": "id", "sort": "newest",
    "scrapedAt": "2026-10-30T15:01:14", "filename": "...json"
  },
  "stats": { "total": 1000, "average": 3.0, "distribution": { "1": 200, ... } },
  "reviews": [ { "reviewId": "...", "userName": "...", "score": 1, "content": "..." } ]
}
```

## Aset analisis sentimen (referensi, bukan bagian web app)

File berikut sengaja dibiarkan apa adanya dan **tidak** dipakai oleh aplikasi web:

- `pln_sentiment_phase1.ipynb`, `pln_sentiment_phase5.ipynb` — pipeline eksperimen
- `combined_reviews.csv` — 1.000 review gabungan
- `indobert_scored_reviews.csv` — hasil labeling lexicon + IndoBERT
- `positive.tsv`, `negative.tsv` — kamus lexicon

## Catatan

- `data/*.json` di-ignore karena setiap scrape menghasilkan file ~850 KB.
- Aplikasi ini tidak berafiliasi dengan Google.
