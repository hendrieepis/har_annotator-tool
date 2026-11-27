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

## Repositori GitHub

Kode sumber: **https://github.com/hendrieepis/har_annotator-tool**

## Kebutuhan Sistem

| Kebutuhan | Keterangan |
|---|---|
| Python | 3.10 atau lebih baru (`python3 --version`) |
| ffmpeg + ffprobe | Wajib untuk memotong klip; harus ada di `PATH` |
| Git | Untuk mengunduh (clone) dari GitHub |
| Layar grafis | Aplikasi ini GUI desktop (Linux/macOS/Windows) |

Paket Python (PySide6, PyAV) **diinstal otomatis** oleh `har-annotator` pada
run pertama ke dalam `.venv/` di folder proyek, jadi tidak perlu
`pip install` manual dan tidak mengotori Python sistem.

### Instal Git dan ffmpeg

| Sistem | Perintah |
|---|---|
| Ubuntu / Debian | `sudo apt update && sudo apt install -y git ffmpeg python3 python3-venv` |
| macOS (Homebrew) | `brew install git ffmpeg python` |
| Windows | Instal [Git for Windows](https://git-scm.com/download/win) (sudah termasuk *Git Bash*), [Python](https://www.python.org/downloads/) (centang *Add to PATH*), dan ffmpeg (`winget install ffmpeg`) |

Cek: `ffmpeg -version` dan `ffprobe -version` harus menampilkan versi.

## Mengunduh dari GitHub

```bash
git clone https://github.com/hendrieepis/har_annotator-tool.git
cd har_annotator-tool
```

Tanpa Git, bisa juga unduh ZIP: buka halaman repositori → tombol hijau
**Code** → **Download ZIP**, lalu ekstrak.

> Nama folder hasil unduhan bebas (mis. `har_annotator-tool` atau
> `har_annotator-tool-main`); aplikasi tetap jalan.

## Menjalankan

**Linux / macOS** (dari dalam folder hasil clone):

```bash
./har-annotator
```

Jika muncul `Permission denied`: `chmod +x har-annotator`.

**Windows** (belum diuji): buka **Git Bash** di folder proyek, lalu jalankan
`./har-annotator` (atau pakai WSL). Cara manual tanpa Bash (`mklink` perlu
PowerShell/CMD sebagai Administrator):

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
mkdir .pkgroot
mklink /D .pkgroot\har_annotator ..
set PYTHONPATH=.pkgroot
.venv\Scripts\python -m har_annotator
```

Pada run pertama `har-annotator` membuat `.venv/` dan mengunduh dependensi
(butuh internet, beberapa menit). Run berikutnya langsung membuka aplikasi.

### Menjalankan dari folder mana pun (opsional)

```bash
mkdir -p ~/.local/bin
ln -sfn "$PWD/har-annotator" ~/.local/bin/har-annotator
har-annotator          # sekarang bisa dipanggil dari folder mana saja
```

Pastikan `~/.local/bin` ada di `PATH`. Jika folder proyek dipindah, buat ulang
symlink-nya dengan perintah yang sama.

### Memperbarui ke versi terbaru

```bash
cd har_annotator-tool
git pull
```

### Opsi lanjutan

| Variabel | Fungsi |
|---|---|
| `PYTHON=/path/ke/python3 ./har-annotator` | Pakai interpreter tertentu (lewati pembuatan `.venv`) |
| `HAR_NO_VENV=1 ./har-annotator` | Jangan buat `.venv`; pakai `python3` yang ada |

### Pemecahan Masalah

| Gejala | Solusi |
|---|---|
| `warning: 'ffmpeg' not on PATH` | Instal ffmpeg (lihat tabel di atas); export klip tidak akan jalan tanpanya |
| `python3 not found` / `No module named venv` | Ubuntu: `sudo apt install python3 python3-venv` |
| `Could not find the Qt platform plugin "xcb"` | Ubuntu: `sudo apt install libxcb-cursor0 libxkbcommon-x11-0` |
| Gagal saat menginstal dependensi | Cek koneksi internet, hapus `.venv/`, jalankan ulang |
| Ingin mengulang instalasi bersih | `rm -rf .venv` lalu `./har-annotator` |

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

### Marker Start/Stop (garis yang bisa digeser)

Di atas video ada **garis marker** berwarna (biru dan oranye) lengkap dengan
**pegangan** di tengahnya. **Geser garis dengan mouse** (klik-tahan lalu seret;
kursor berubah saat berada di atas garis). Posisinya disimpan otomatis per video
di `clips/.har_annotator/<video>.markers.json`, jadi terpulihkan saat dibuka lagi.
Kotak **Show markers** menyembunyikan/menampilkan garis.

Garis yang tampil mengikuti kode arah pada nama file, dan labelnya menjelaskan
mana *start* dan mana *stop*:

| Kode | Arti | Garis | START | STOP |
|---|---|---|---|---|
| `KKN` | kiri → kanan | 2 garis vertikal | garis **kiri** | garis **kanan** |
| `KNK` | kanan → kiri | 2 garis vertikal | garis **kanan** | garis **kiri** |
| `MDK` | mendekat (atas → bawah) | 2 garis horizontal | garis **atas** | garis **bawah** |
| `MJH` | menjauh (bawah → atas) | 2 garis horizontal | garis **bawah** | garis **atas** |

Contoh label pada garis kiri: `KKN START | KNK STOP`.

### Mode: Manual atau Auto clip

Pilih mode di bawah video:

- **Manual (Set Start / Set End)** — cara lama, lihat langkah 3–4 di atas.
- **Auto clip (from markers)** — aplikasi memotong klip sendiri saat video diputar:
  1. Pilih mode **Auto clip (from markers)**. Tombol Play berubah menjadi
     **▶ Play & auto clip**.
  2. **Geser marker** kiri dan kanan (atau atas dan bawah) ke batas jalan subjek.
     Tekan **👁 Preview (adjust markers)** untuk memutar video **tanpa memotong
     klip**: marker tetap bisa digeser saat video berjalan, dan teks di sebelah
     tombol menampilkan jumlah lintasan yang akan terdeteksi dengan posisi marker
     saat ini (mis. `KKN 10 · KNK 10`). Tekan tombol yang sama untuk berhenti.
  3. Tekan **▶ Play & auto clip** (atau `Space`). Pertama kali aplikasi menganalisis gerakan
     video lebih dulu (sekitar 10 detik, hasilnya di-cache di `<video>.traj.npz`),
     lalu video otomatis diputar.
  4. Setiap kali subjek berjalan dari garis *start* ke garis *stop*, klip
     langsung dibuat dan **di-export menjadi file** (mis. `..._KKN_..._01.mp4`
     untuk kiri → kanan, lalu `..._KNK_..._01.mp4` untuk kanan → kiri), dengan
     penomoran repetisi otomatis. Proses berulang sampai frame terakhir.
  5. **Pause** kapan saja untuk menggeser marker (saat berjalan, garis dikunci),
     lalu Play lagi untuk melanjutkan. Klip yang sudah ada tidak digandakan.
  6. **🗑 Clear pending** menghapus klip yang belum di-export. Klik ganda klip di
     daftar pending untuk melompat ke awalnya.

**Opsi tambahan di mode Auto** (semuanya disimpan per video di `<video>.markers.json`
dan terkunci saat auto clip berjalan):

| Opsi | Kapan dipakai |
|---|---|
| **Reverse direction** (kotak centang di baris mode) | Arah jalan di gambar berkebalikan dengan kode arah pada nama file, misalnya video `..._KNK_KKN_...` yang lintasan pertamanya bergerak kiri → kanan di layar. Opsi ini menukar garis START dan STOP; labelnya ikut berubah. |
| **Pre-roll** (detik) | Klip dimulai lebih awal dari saat subjek melewati garis START. Berguna pada MDK/MJH: operator biasanya mulai merekam klip beberapa saat sebelum subjek mulai berjalan, dan jedanya berbeda per rekaman. |
| **Post-roll** (detik) | Klip berakhir lebih lambat dari saat subjek melewati garis STOP. |

Pre/post-roll tidak pernah menimpa klip di sebelahnya. Nilai bawaan 0.

Cara kerja deteksi: kamera dianggap diam; latar belakang diestimasi dengan median
frame, lalu posisi subjek per frame diambil dari piksel yang berbeda dari latar
(titik tengah tubuh untuk kiri-kanan, area kaki untuk mendekat/menjauh).
Lintasan hanya dihitung jika subjek melewati garis start **dan** garis stop
dengan arah yang benar; jalan setengah jalan diabaikan. Lintasan yang arahnya
tidak sesuai urutan nama (mis. `KKN, KNK, KKN, …`) dilewati dan dilaporkan di
status bar.

> **Selalu periksa hasil auto clip.** Posisi marker, Reverse direction, dan
> pre-roll yang tepat berbeda-beda per rekaman, jadi atur dulu dengan Preview. Klip langsung di-export, jadi cek file di
> folder `clips/` setelah selesai. Deteksi gerakan bisa
> keliru jika ada orang lain yang lewat, bayangan kuat, atau kamera bergeser.
> Pada uji dengan video contoh, video kiri-kanan menghasilkan 20 lintasan
> (10 per arah) dan satu video mendekat/menjauh menghasilkan 22 (ada 2 tambahan
> yang perlu diperiksa).

### Pintasan Keyboard

| Tombol | Aksi | Tombol | Aksi |
|---|---|---|---|
| `Space` | Play / pause | `I` | Set awal |
| `←` / `→` | Maju/mundur 1 frame | `O` | Set akhir → tambah ke pending |
| `[` / `]` | Maju/mundur 10 frame | `S` | **Export All** (video aktif) |
| `Ctrl+Z` | Undo mark | `Ctrl+Y` / `Ctrl+Shift+Z` | Redo mark |

`I` dan `O` hanya berlaku pada mode Manual. Pada mode Auto, `Space` memulai Play & auto clip.

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
./                       # root repo = package `har_annotator` (nama folder bebas)
  har-annotator          # launcher (bash): venv, deps, PYTHONPATH
  requirements.txt
  app.py                 # entry point (python -m har_annotator)
  core/
    naming.py            # parsing nama file + pembuatan nama output
    video.py             # pembaca frame PyAV untuk preview
    exporter.py          # pemotongan klip ffmpeg + preset kualitas
    session.py           # state pending vs exported, auto-persist JSON, resume
    markers.py           # model garis marker + arti START/STOP per kode arah
    autoclip.py          # analisis gerakan + pencarian lintasan antar marker
  ui/
    player.py            # widget preview: tampilan, transport, scrubber
    export_worker.py     # BatchExportWorker — QThread ffmpeg (banyak klip)
    auto_worker.py       # TrajectoryWorker — analisis gerakan di background
    main_window.py       # browser folder, marking, daftar pending, export batch
tests/
  test_naming.py         # uji kebenaran penamaan/urutan
  test_session.py        # uji pending/exported, persistensi, resume, undo/redo
  test_markers.py        # uji marker: arti start/stop, batas geser, simpan/muat
  test_autoclip.py       # uji deteksi lintasan (termasuk video sintetis)
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
