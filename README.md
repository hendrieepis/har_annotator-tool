# HAR Dataset Annotator

Aplikasi desktop khusus untuk mengubah **video mentah Human Activity
Recognition (HAR)** menjadi **klip dataset pendek yang berisi satu lintasan
saja**.

Setiap video mentah berisi beberapa repetisi dua arah berjalan yang direkam
bolak-balik (agar subjek tidak cepat lelah), contohnya:

```
P001_BRJ_KKN_KNK_NORMAL.mp4   ->   KKN, KNK, KKN, KNK, …  (10 repetisi tiap arah)
```

Operator **hanya menandai awal dan akhir** setiap lintasan (bagian ketika
seluruh tubuh subjek terlihat utuh di dalam frame). Seluruh pekerjaan
administrasi dilakukan otomatis oleh aplikasi: penamaan, penomoran repetisi,
pergantian arah, progres, dan pemotongan yang mempertahankan kualitas.

```
P001_BRJ_KKN_KNK_NORMAL.mp4
        │
        ├─ P001_BRJ_KKN_NORMAL_01.mp4
        ├─ P001_BRJ_KNK_NORMAL_01.mp4
        ├─ P001_BRJ_KKN_NORMAL_02.mp4
        ├─ P001_BRJ_KNK_NORMAL_02.mp4
        └─ …
```

## Pilihan Teknologi

| Kebutuhan | Pilihan | Alasan |
|---|---|---|
| GUI | **PySide6 (Qt)** | Widget desktop native yang matang, penanganan keyboard baik |
| Decode preview | **PyAV** | Seek akurat per-frame **tanpa bentrok Qt** (build GUI OpenCV menautkan Qt-nya sendiri sehingga crash bila bersama PySide6) |
| Pemotongan | **ffmpeg** | Potong akurat per-frame yang mempertahankan resolusi, frame rate, orientasi, dan kualitas (mendekati lossless) |

### Kualitas Output

Klip di-encode ulang dengan **x264 CRF 17 (visually lossless)** sebagai default,
mempertahankan resolusi, frame rate, pixel format, dan metadata rotasi sumber.
Encode ulang (bukan *stream copy* cepat) diperlukan karena *stream copy* hanya
bisa memotong di keyframe, sehingga tidak menghormati frame awal/akhir persis
yang ditentukan operator. Dua preset lain tersedia di UI:

- **Very high** — CRF 14
- **Mathematically lossless** — CRF 0 (piksel persis, file sangat besar)

Pemotongan bersifat *frame-exact*: `-ss` melakukan seek input yang cepat dan
akurat, lalu `-frames:v N` menulis tepat sejumlah frame inklusif yang ditandai.

## Kebutuhan Sistem

- Python 3.10+
- `ffmpeg` / `ffprobe` tersedia di `PATH`
- Paket Python: `pip install -r requirements.txt` (otomatis di `.venv/` saat menjalankan `har-annotator`)

## Menjalankan

```bash
./har-annotator
# atau lewat symlink di PATH:
# ln -sfn "$PWD/har-annotator" ~/.local/bin/har-annotator && har-annotator
```

> **Catatan lingkungan conda:** entry point sudah otomatis mengarahkan Qt ke
> folder plugin milik PySide6. Ini mencegah error
> `Could not find the Qt platform plugin "xcb" in ""` yang muncul ketika ada Qt
> lain (mis. bawaan opencv conda) yang membayangi PySide6. Tidak perlu langkah
> tambahan.

## Alur Kerja

Penandaan (**mark**) dan render fisik (**export**) sekarang **terpisah**:
operator bisa fokus menandai banyak lintasan dulu, baru di-export belakangan.

1. **Open Folder** — pilih folder berisi video mentah. Klip ditulis ke subfolder
   `clips/`; progres disimpan di `clips/.har_annotator/`.
2. Pilih video dari daftar (tanda menunjukkan progres: `✔` ada yang sudah
   di-export, `…` ada yang masih pending, `•` belum ada).
3. Geser / langkah ke **frame pertama** ketika seluruh tubuh terlihat →
   **Set Start (I)**.
4. Langkah ke **frame terakhir** yang masih bagus → **Set End (O)**. Entry baru
   (nama, arah, nomor repetisi sudah dihitung otomatis) langsung masuk ke
   **daftar klip pending** — **belum** di-render — dan playhead maju tepat
   setelah frame akhir. Daftar pending **otomatis disimpan** ke
   `clips/.har_annotator/<video>.pending.json` setiap perubahan, jadi aman dari
   crash.
5. Ulangi langkah 3–4 untuk lintasan berikutnya. **Undo mark (Ctrl+Z)**
   menghapus entry pending terakhir dan **Redo mark (Ctrl+Y / Ctrl+Shift+Z)**
   mengembalikannya persis seperti semula (operasi murah, tanpa menyentuh file).
   Menandai lintasan baru akan menghapus riwayat redo.
6. **Export:**
   - **Export All (S)** — render semua entry pending untuk video aktif.
   - **Export Selected** — pilih satu/beberapa baris di daftar pending (bisa
     multi-pilih), lalu render hanya itu. Berguna untuk mengecek beberapa klip
     dulu sebelum lanjut menandai sisanya.
   - **Auto-export every N marks** — opsional (default aktif, N=5). Tiap kali
     pending mencapai N, aplikasi otomatis meng-export agar sebagian klip selalu
     aman jadi file walau operator lupa menekan Export.

   Export berjalan di latar belakang dengan progress bar; setiap klip yang
   selesai langsung dipindahkan dari "pending" ke "exported" dan dicatat
   permanen — jika export gagal/crash di tengah, klip yang sudah jadi tetap aman.
7. Saat aplikasi dibuka lagi dan video yang sama dipilih, daftar pending yang
   belum di-export **dipulihkan otomatis** (resume) — tidak perlu menandai ulang.

### Pintasan Keyboard

| Tombol | Aksi | Tombol | Aksi |
|---|---|---|---|
| `Space` | Play / pause | `I` | Set awal |
| `←` / `→` | Maju/mundur 1 frame | `O` | Set akhir → tambah ke pending |
| `[` / `]` | Maju/mundur 10 frame | `S` | **Export All** (video aktif) |
| `Ctrl+Z` | Undo mark | `Ctrl+Y` / `Ctrl+Shift+Z` | Redo mark |

## Konvensi Penamaan

Nama file sumber dipecah berdasarkan `_`:

```
P001 _ BRJ _ KKN _ KNK _ NORMAL
└── prefix ──┘ │     │   └ suffix
            arah1  arah2
```

Token arah diambil dari posisi ke-3 dan ke-4 (`FilenameSpec.DIR1_POS` /
`DIR2_POS` di `core/naming.py`). Urutan output selalu mengikuti
urutan kemunculan arah pada nama file sumber.

## Struktur Project

```
./                      # root repo = package `har_annotator` (nama folder bebas)
  har-annotator          # launcher (bash): venv, deps, PYTHONPATH
  requirements.txt
  app.py                 # entry point (python -m har_annotator)
  core/
    naming.py            # parsing nama file + pembuatan nama output
    video.py             # pembaca frame PyAV untuk preview
    exporter.py          # pemotongan klip ffmpeg + preset kualitas
    session.py           # state pending vs exported, auto-persist JSON, resume
  ui/
    player.py            # widget preview: tampilan, transport, scrubber
    export_worker.py     # BatchExportWorker — QThread ffmpeg (banyak klip)
    main_window.py       # browser folder, marking, daftar pending, export batch
tests/
  test_naming.py         # uji kebenaran penamaan/urutan
  test_session.py        # uji pending/exported, persistensi, resume, undo/redo
```

### File state per video (di `clips/.har_annotator/`)

- `<video>.json` — klip yang **sudah** di-export (key `clips`).
- `<video>.pending.json` — klip yang sudah **ditandai tapi belum** di-export;
  ditulis ulang tiap mark/undo dan dihapus saat daftar pending kosong. Inilah
  yang dipulihkan saat resume.

Indeks klip (yang menentukan arah + nomor repetisi) bersifat **kontinu** lintas
pending dan exported, sehingga undo lalu menandai ulang tidak menabrak penomoran
klip yang sudah ter-export.

## Pengujian

```bash
python3 -m pytest tests/
```

## Pengembangan Lanjutan

- **Skema nama berbeda:** sesuaikan `FilenameSpec.DIR1_POS` / `DIR2_POS`, atau
  berikan `FilenameSpec` yang sudah dikustomisasi ke session.
- **Lebih dari dua arah / pola lain:** `FilenameSpec.target_for()` adalah satu-
  satunya tempat yang memetakan indeks klip berjalan ke arah + repetisi.
- **Audio / codec berbeda:** `ExportRequest` dan `QUALITY_PRESETS` di
  `exporter.py`.
- **State pending/exported & persistensi:** `AnnotationSession` di `session.py`
  — `add_mark()` / `remove_last_mark()` / `redo_last_mark()` / `mark_exported()`
  masing-masing menyimpan otomatis. Riwayat undo/redo bersifat in-memory (tidak
  ikut tersimpan antar sesi). Format file lihat bagian *File state per video*.
- **Default auto-export checkpoint:** konstanta `DEFAULT_CHECKPOINT_N` di
  `main_window.py` (default 5; bisa dimatikan via checkbox di UI).
- **Export batch / progres per-klip:** `BatchExportWorker` di `export_worker.py`
  memproses banyak klip berurutan dan memancarkan sinyal `one_done` tiap klip
  selesai (dipakai untuk memindahkan klip ke "exported" dan menyimpannya
  inkremental).
