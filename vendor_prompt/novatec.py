NOVATEC_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari kolom "PO.NO.".
2. `inv_spart_item_no`: Ekstrak dari kolom "CODE" (misalnya "RIMNT28R4RIM0001" atau "BNXNT-44MM00000").
3. `inv_description`: Ekstrak teks deskripsi dari kolom "DESCRIPTION".
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak nilai angka dari kolom "QTY".
6. `inv_quantity_unit`: Ekstrak dari kolom "UNIT" (misalnya "PCS" atau "SET").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "UNIT PRICE".
8. `inv_amount`: Ekstrak nilai angka dari kolom "AMOUNT".

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari kolom "PO NO.".
2. `pl_item_no`: Ekstrak dari kolom "CODE".
3. `pl_description`: Ekstrak teks deskripsi dari kolom "DESCRIPTION".
4. `pl_quantity`: Ekstrak nilai angka dari kolom "QTY".
5. `pl_package_unit`: Simpulkan sebagai "CT" berdasarkan header kolom "TOTAL CTNS".

STRUKTUR MERGED CELL DAN KOLOM COMBINED:
    Tabel ini memiliki dua area berbeda di sisi kanan untuk baris-baris yang memiliki merged TOTAL CTNS cell:

    AREA A — nilai per-merge-group (yang digunakan untuk ekstraksi):
    Format: [Combined QTY] [TOTAL CTNS] [Combined N.W] [Combined G.W] [CBM]
    Nilai ini merepresentasikan satu merge group spesifik. Selalu disertai angka TOTAL CTNS (mis. 1, 2).
    AREA A ini adalah yang harus digunakan untuk mengisi pl_package_count, pl_nw, pl_gw, pl_volume.

    AREA B — nilai total seluruh tipe item (HARUS DIABAIKAN):
    Format: [Combined QTY besar] [Combined N.W] [Combined G.W]
    Nilai ini adalah akumulasi dari SEMUA baris dengan item yang sama. TIDAK disertai TOTAL CTNS.
    Nilai ini LEBIH BESAR dari AREA A karena mencakup seluruh item sejenis.
    JANGAN gunakan nilai AREA B untuk mengisi field apapun.

    DISAMBIGUASI AREA A vs AREA B — WAJIB dilakukan terlebih dahulu:
    Dalam satu blok item yang sama, bisa muncul DUA set nilai Combined di area yang berdekatan:
    satu AREA A (untuk sub-group tertentu) dan satu AREA B (untuk total semua baris item tersebut).
    Cara membedakannya:
    - AREA A: Combined QTY = sum QTY hanya beberapa baris berurutan (sub-set). DISERTAI TOTAL CTNS.
    - AREA B: Combined QTY = sum QTY SEMUA baris dengan item yang sama (total keseluruhan). TANPA TOTAL CTNS.
    Jika dua Combined QTY muncul berdekatan pada visual yang sama, pilih yang LEBIH KECIL sebagai AREA A
    dan ABAIKAN yang lebih besar (AREA B).

    TIGA POSISI VISUAL AREA A — SEMUA HARUS DIHANDLE:

    POSISI 1 — AREA A muncul di baris TERAKHIR group (pola normal):
    Nilai AREA A muncul dalam baris Y (baris terakhir group). Baris sebelumnya (X) tidak memiliki data
    di kolom main table. Assign ke baris X (TOP), baris Y mendapat 0.

    POSISI 2 — AREA A muncul DI ANTARA dua baris (pola khusus, sering terjadi saat row tinggi):
    Nilai AREA A (Combined QTY, TOTAL CTNS, NW, GW, CBM) muncul BUKAN di baris X maupun baris Y,
    melainkan di RUANG DI ANTARA keduanya (di area merged cell yang terbentang di tengah).
    Baris Y menampilkan data AREA B (Combined QTY besar tanpa TOTAL CTNS) — BUKAN AREA A.
    Dalam kasus ini: Assign nilai AREA A ke baris X (TOP), baris Y mendapat 0.

    Contoh Posisi 2 (generik):
      Baris X: PO=A, QTY=P, UNIT=SET  [kolom right: tidak ada data]
      --- AREA A floating di antara baris: Combined QTY=(P+Q), TOTAL CTNS=T, NW=nw, GW=gw, CBM=cbm ---
      Baris Y: PO=B, QTY=Q, UNIT=SET  [kolom right: Combined QTY=(P+Q+...) ← ini AREA B, abaikan]
      → Hasil: Baris X mendapat pl_package_count=T, pl_nw=nw, pl_gw=gw, pl_volume=cbm
      → Hasil: Baris Y mendapat pl_package_count=0, pl_nw=0, pl_gw=0, pl_volume=0

    POSISI 3 — AREA A muncul di baris PERTAMA group:
    Nilai AREA A muncul di baris X (baris pertama). Assign langsung ke baris X.

    CARA MENGIDENTIFIKASI POSISI 2 VS AREA B:
    Jika pada suatu baris terdapat Combined QTY TANPA TOTAL CTNS = itu AREA B, ABAIKAN.
    Jika ada Combined QTY yang muncul di ANTARA dua baris (tidak di baris manapun) dengan TOTAL CTNS = itu AREA A Posisi 2.

    ALGORITMA ASSIGNMENT (jalankan urutan ini):
    Langkah 1: Baca seluruh tabel. Kumpulkan SEMUA Combined QTY yang disertai TOTAL CTNS (dari mana saja posisinya).
               Ini adalah daftar AREA A groups. ABAIKAN Combined QTY yang tidak ada TOTAL CTNS-nya (= AREA B).
    Langkah 2: Untuk setiap AREA A entry, temukan baris-baris berurutan yang jumlah QTY-nya = Combined QTY tersebut.
               Verifikasi dengan aritmatika: sum(QTY baris-baris) = Combined QTY AREA A.
    Langkah 3: Baris PERTAMA dari merge group → assign pl_package_count=TOTAL CTNS, pl_nw=Combined N.W (AREA A),
               pl_gw=Combined G.W (AREA A), pl_volume=CBM (AREA A).
    Langkah 4: Baris KEDUA dst. dalam merge group → pl_package_count=0, pl_nw=0, pl_gw=0, pl_volume=0.
    Langkah 5: ABAIKAN semua nilai Combined dari AREA B (tidak ada field yang menggunakan AREA B).

    PERINGATAN KRITIS — JANGAN SALAH MENGIDENTIFIKASI AREA B SEBAGAI AREA A:
    Jika satu tipe item memiliki BEBERAPA merge group (mis. rows A-B adalah group 1, rows C-D-E adalah group 2),
    maka AREA B untuk seluruh tipe item tersebut akan muncul di baris TERAKHIR dari semua baris tipe tersebut
    (mis. baris E) dengan Combined QTY = sum SEMUA rows tipe tersebut.
    Ini BUKAN AREA A. AREA A untuk group 1 dan group 2 masing-masing memiliki Combined QTY yang LEBIH KECIL.
    Jangan assign AREA B ke row manapun.

    Cara menentukan batas merge group:
    - Hitung jumlah QTY beberapa baris berturut-turut sampai hasilnya cocok dengan Combined QTY AREA A.
    - Contoh: Combined QTY = 754, baris A (qty=320) + B (qty=354) + C (qty=80) = 754 → A, B, C satu group.
    - Contoh: Combined QTY = 3, baris X (qty=2) + Y (qty=1) = 3 → X dan Y satu group.
    - PENTING: kesamaan PO number BUKAN penentu batas group. Verifikasi selalu dengan Combined QTY.
      Contoh: baris dengan PO berbeda bisa berada dalam satu merge group yang sama.

6. `pl_package_count`:
    - Ekstrak dari kolom "TOTAL CTNS" main table.
    - Untuk merged cell group: TOTAL CTNS (nilai AREA A) diberikan ke baris PALING ATAS group, sisanya 0.
    - Batas group ditentukan dengan Combined QTY AREA A = sum QTY baris-baris dalam group.
    - JANGAN gunakan nilai AREA B meskipun visually muncul lebih dekat ke baris yang dimaksud.
7. `pl_nw`:
    - Untuk baris standalone (tidak ada merge): ekstrak dari kolom "TOTAL N.W." main table.
    - Untuk merged cell group: ambil nilai Combined N.W dari AREA A yang sesuai untuk group tersebut.
      Berikan ke baris PALING ATAS group, sisanya 0.
    - JANGAN gunakan Combined N.W dari AREA B (nilainya jauh lebih besar, tidak disertai TOTAL CTNS).
    - Jika dua nilai Combined N.W muncul berdekatan, gunakan yang LEBIH KECIL (AREA A).
8. `pl_gw`:
    - Untuk baris standalone: ekstrak dari kolom "TOTAL G.W." main table.
    - Untuk merged cell group: ambil nilai Combined G.W dari AREA A yang sesuai untuk group tersebut.
      Berikan ke baris PALING ATAS group, sisanya 0.
    - JANGAN gunakan Combined G.W dari AREA B.
    - Jika dua nilai Combined G.W muncul berdekatan, gunakan yang LEBIH KECIL (AREA A).
9. `pl_volume`:
    - Untuk baris standalone: ekstrak dari kolom "TOTAL CBM" main table.
    - Untuk merged cell group: ambil nilai CBM yang mengikuti Combined G.W di AREA A untuk group tersebut.
      Berikan ke baris PALING ATAS group, sisanya 0.

BILL OF LADING (BL):

STRUKTUR KOLOM "Number and Kind of packages / Description of Goods" PADA BL NOVATEC:
    Kolom ini memuat DUA bagian terpisah:
    (a) MARKS (kolom kiri): baris-baris seperti "INSERA", "P/O:", "MODEL:", "Q.TY:",
        "C/NO:", "MADE IN CHINA". Ini untuk bl_mark_number, BUKAN bl_description.
    (b) DESCRIPTION OF GOODS (kolom utama): diawali baris umum
        ("1 x 40HC CONTAINER", "STC 42 CARTON(S)", "BICYCLE PARTS") lalu DIIKUTI
        DAFTAR ITEM per KATEGORI PRODUK dalam format:
            "<NAMA KATEGORI PRODUK> HS NUMBER: <kode HS>"
        Contoh nyata pada dokumen ini:
            RIM G24 HS NUMBER: 8714.92
            RIM R4 FRONT HS NUMBER: 8714.92
            RIM R4 REAR HS NUMBER: 8714.92
            WHEEL SET HS NUMBER: 8714.92
            VALVES FOR TUBELESS TYRES HS NUMBER: 8481.80

LANGKAH 1 — Kumpulkan DAFTAR pasangan (deskripsi, HS) dari kolom Description of Goods:
    Untuk setiap baris berpola "<NAMA KATEGORI> HS NUMBER: <kode>", catat:
      - deskripsi kategori = teks SEBELUM "HS NUMBER:" (mis. "WHEEL SET", "RIM G24",
        "RIM R4 FRONT", "RIM R4 REAR", "VALVES FOR TUBELESS TYRES").
      - kode HS = angka SETELAH "HS NUMBER:" (mis. "8714.92", "8481.80").
    ABAIKAN baris generik "BICYCLE PARTS", "STC ... CARTON(S)", "... CONTAINER".

LANGKAH 2 — Petakan tiap baris item (per inv_description) ke SATU kategori BL di atas,
    berdasarkan JENIS PRODUK (pencocokan semantik, BUKAN pencocokan teks persis):
      - inv_description diawali "WHEELSET" / "WHEEL SET"  -> kategori "WHEEL SET".
      - inv_description jenis "RIM ... G24" / mengandung model "G24"  -> "RIM G24".
      - inv_description jenis "RIM ... R4 ..." dan menyebut "FRONT"  -> "RIM R4 FRONT".
      - inv_description jenis "RIM ... R4 ..." dan menyebut "REAR"   -> "RIM R4 REAR".
      - inv_description jenis "VALVE ... TUBELESS" (mis. R3 L:44MM maupun R5 L:70MM)
        -> "VALVES FOR TUBELESS TYRES" (kedua varian valve memetakan ke SATU kategori ini).
    Catatan: bila ada beberapa kandidat (mis. R4 FRONT vs R4 REAR), pilih yang cocok
    pada penanda FRONT/REAR di inv_description.

1. `bl_description`:
    - Isi dengan NAMA KATEGORI BL hasil pemetaan Langkah 2 (mis. "WHEEL SET",
      "RIM G24", "RIM R4 FRONT", "RIM R4 REAR", "VALVES FOR TUBELESS TYRES").
    - Gunakan teks kategori PERSIS seperti tertulis di BL (jangan diubah ke inv_description).
    - Jika tidak ada kategori BL yang cocok untuk baris tersebut, isi null.
    - Hanya boleh mengambil dari dokumen Bill Of Lading (BL), TIDAK BOLEH dari dokumen lain.

2. `bl_hs_code`:
    - Isi dengan kode HS dari kategori BL yang sama (pasangan dari bl_description).
      Contoh: bl_description "WHEEL SET" -> bl_hs_code "8714.92";
              bl_description "VALVES FOR TUBELESS TYRES" -> bl_hs_code "8481.80".
    - bl_description dan bl_hs_code SATU PAKET: keduanya terisi atau keduanya null.

CERTIFICATE OF ORIGIN (COO):
1. `coo_seq`:
   - Ambil dari kolom "Item number".
   - Nilai numeric.
   - Item number tercetak jelas seperti:
     - 1
     - 2
     - 3
     - ...
2. `coo_mark_number`: 
    - Ekstrak dari "7. Marks and numbers on packages".
    - Apabila tidak ada informasi marks and numbers pada kolom 7 atau tertlulis "N/M" (Not Mentioned), maka biarkan null.
3. `coo_description`: Ekstrak deskripsi teks dari kolom "8. Number and kind of packages; and description of goods." Abaikan keterangan jumlah paket (angka dan kata) pada field ini.
4. `coo_hs_code`: Ekstrak dari "9. HS Code of the goods".
5. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "TWO (2) CARTONS" ambil angka 2).
6. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "CARTONS").
7. `coo_gw` & `coo_quantity`: 
    - Ekstrak nilai berat dari kolom "12. Quantity..." untuk mengisi `coo_gw` (misalnya dari "41.09KGS G.W. 70PIECES", ekstrak "41.09").
    - Ekstrak nilai jumlah barang dari baris yang sama untuk mengisi `coo_quantity` (misalnya dari "70PIECES", ekstrak "70").
8. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KGS").
9. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
10. `coo_customer_po_no`: Biarkan null kecuali ada referensi nomor PO yang secara spesifik ditulis di dalam kolom 7 atau 8.
"""