JOY_PROMPT = """
INVOICE (INV):

ATURAN SANGAT PENTING UNTUK DOKUMEN INVOICE VENDOR INI (BACA DUA KALI):
- Apabila ada beberapa line item dengan tipe data numerik (QTY, AMOUNT) yang tergabung dalam satu merged-cell, maka value yang tertera adalah untuk line item dalam group tersebut yang **PALING BAWAH** (BOTTOM row), dan sisanya **0**.
- DILARANG KERAS untuk menduplikasi value numerik pada line item yang memiliki merged-cell. HANYA LINE ITEM PALING BAWAH DARI MERGED-CELL YANG BOLEH MENGAMBIL VALUE NUMERIK; SELURUH BARIS LAIN DALAM GROUP TERSEBUT HARUS DIISI 0 (BUKAN null, BUKAN nilai apapun selain 0).
- DILARANG KERAS untuk menambahkan/membagi value numerik dari satu line item ke line item lain TANPA TERKECUALI!
- KONSISTENSI: Aturan "paling bawah" ini berlaku SERAGAM untuk SEMUA kolom numerik merged-cell di invoice ini (QTY, AMOUNT, dan kolom numerik lain yang merged). JANGAN ada satu pun kolom yang dibaca dengan aturan "paling atas".

SANITY-CHECK ANGKA (untuk meredam salah baca OCR digit-mirip — 6 vs 7, 0 vs 3, 2 vs 5, dll):
- Setelah mengekstrak `inv_quantity` dan `inv_unit_price` dari baris merged-cell PALING BAWAH, hitung perkiraan amount = inv_quantity × inv_unit_price, lalu bandingkan dengan `inv_amount` yang dibaca.
- Jika selisihnya signifikan (> 1% dari amount), KEMUNGKINAN BESAR salah satu dari ketiganya salah baca OCR. Periksa ulang digit-digit yang mungkin terbalik (terutama 6↔7, 2↔3, 0↔8, 1↔7) dan pilih kombinasi yang konsisten amount = qty × price.
- Contoh: jika qty=6234, price=30 → amount harus 187020; jangan terima qty=6754 (yang menghasilkan 202620) bila amount tertulis 187020.

1. `inv_customer_po_no`: Ekstrak dari kolom "PO.NO.".
2. `inv_spart_item_no`: Ekstrak dari kolom "CODE" (Misal: HUFJY4310000000)
3. `inv_description`: Ekstrak teks deskripsi spesifikasi barang dari kolom "DESCRIPTION" (pisahkan dari kode barang, ambil teks panjangnya).
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`:
    - Ekstrak dari kolom "QTY".
    - SANGAT PENTING: Apabila ada beberapa line item yang tergabung dalam satu QTY (quantity) merged-cell, maka QTY yang tertera adalah untuk line item dalam group tersebut yang **PALING BAWAH (BOTTOM row)**, dan sisanya **0**.
        Contoh visual merged-cell QTY (sel QTY menyatu/merged secara vertikal mencakup 3 baris A, B, C; angka 480 tercetak di sel merged tersebut secara visual):
        |   ITEM  |  QTY    |
        |   A     |         |   ← bagian merged-cell, BUKAN baris tujuan
        |   B     |         |   ← bagian merged-cell, BUKAN baris tujuan
        |   C     |  480    |   ← BARIS PALING BAWAH dari group, INI yang mengambil 480
        Maka:
        - Line item A: inv_quantity = 0 (BUKAN 480, BUKAN null)
        - Line item B: inv_quantity = 0 (BUKAN 480, BUKAN null)
        - Line item C: inv_quantity = 480
        Verifikasi: jumlah inv_quantity dari seluruh baris dalam satu merged-cell group HARUS = nilai numerik yang tercetak di sel merged tersebut (0 + 0 + 480 = 480 ✓).
    - Ekstrak HANYA dari kolom "QTY" dari dokumen invoice. DILARANG KERAS untuk mengambil dari kolom lain manapun atau dari dokumen lain manapun.
    - CROSS-CHECK: Setelah ekstrak, validasi dengan inv_amount = inv_quantity × inv_unit_price pada baris bottom merged-cell. Jika tidak match (selisih > 1%), periksa kembali digit yang mungkin salah baca OCR.

6. `inv_quantity_unit`: Ekstrak dari kolom "UNIT" (misalnya "SET").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "UNIT PRICE".
8.  `inv_amount`:
    - Ekstrak nilai angka dari kolom "AMOUNT".
    - Apabila ada beberapa line item yang tergabung dalam satu AMOUNT (amount) merged-cell, maka AMOUNT yang tertera adalah untuk line item dalam group tersebut yang **PALING BAWAH (BOTTOM row)**, dan sisanya **0**.
        Contoh visual merged-cell AMOUNT (sel AMOUNT menyatu/merged secara vertikal mencakup 3 baris A, B, C; angka 5760 tercetak di sel merged tersebut secara visual):
        |   ITEM  |  AMOUNT    |
        |   A     |            |   ← bagian merged-cell, BUKAN baris tujuan
        |   B     |            |   ← bagian merged-cell, BUKAN baris tujuan
        |   C     |  5760      |   ← BARIS PALING BAWAH dari group, INI yang mengambil 5760
        Maka:
        - Line item A: inv_amount = 0 (BUKAN 5760, BUKAN null)
        - Line item B: inv_amount = 0 (BUKAN 5760, BUKAN null)
        - Line item C: inv_amount = 5760
        Verifikasi: jumlah inv_amount dari seluruh baris dalam satu merged-cell group HARUS = nilai numerik yang tercetak di sel merged tersebut (0 + 0 + 5760 = 5760 ✓).
    - CROSS-CHECK WAJIB sebelum finalisasi inv_amount: hitung inv_quantity × inv_unit_price pada baris bottom. Hasilnya HARUS persis sama dengan inv_amount yang dibaca. Bila tidak, kemungkinan ada digit OCR yang salah baca — periksa ulang angka yang mungkin tertukar (6↔7, 2↔3, 0↔8, 1↔7) pada SALAH SATU dari ketiga field tersebut hingga konsisten.
    - GRAND-TOTAL CHECK: Total seluruh inv_amount (non-zero) di dokumen ini harus mendekati total grand-total invoice. Jika sum invoice anda menyimpang signifikan dari total yang tertera di footer dokumen, kemungkinan ada satu atau lebih merged-cell yang nilainya salah baca — periksa kembali.

PACKING LIST (PL):

INFORMASI PENTING (HANYA BERLAKU UNTUK DOKUMEN PL VENDOR INI):
Pada DOKUMEN PL vendor ini, akan ada beberapa line item yang diberi highlight warna berbeda. ABAIKAN HIGHLIGHT TERSEBUT dan FOKUS HANYA MEMBACA PER LINE ITEM.
DILARANG KERAS MENGGABUNGKAN VALUE NUMERIK DARI SATU LINE ITEM KE LINE ITEM LAIN TANPA TERKECUALI!

1. `pl_customer_po_no`: Ekstrak dari kolom "PO NO.".
2. `pl_item_no`: Ekstrak dari kolom gabungan "CODE" ambil HANYA baris kodenya (misalnya "HUFJY...").
3. `pl_description`: Ekstrak teks deskripsi dari kolom gabungan "CODE" / "DESCRIPTION".
4. `pl_quantity`: Ekstrak nilai angka dari kolom "QTY" dan BUKAN "Combined QTY".
5. `pl_package_unit`: Simpulkan sebagai "CT" berdasarkan header kolom "TOTAL CTNS" atau "QTY/CTN".
6. `pl_package_count`: Ekstrak HANYA dari kolom "TOTAL CTNS".DILARANG KERAS untuk mengambil dari kolom lain manapun.
7. `pl_nw`: Ekstrak nilai angka dari kolom "TOTAL N.W." dan BUKAN "Combined N.W.".
8. `pl_gw`: Ekstrak nilai angka dari kolom "TOTAL G.W." dan BUKAN "Combined G.W."
9. `pl_volume`: Ekstrak nilai angka dari kolom "TOTAL CBM".

BILL OF LADING (BL):

STRUKTUR DESKRIPSI BARANG PADA BL VENDOR INI:
- Di area "Description of Goods", barang ditulis sebagai DAFTAR per model. Setiap baris barang berisi nama/kode model diikuti label "HS NUMBER: <kode_hs>".
  Pola umum (ILUSTRASI FORMAT, bukan daftar barang yang wajib ada):
    <KODE/MODEL BARANG A> HS NUMBER: <kode_hs>
    <KODE/MODEL BARANG B> HS NUMBER: <kode_hs>
- Token di kolom kiri (mis. "PO NO:", "ITEM:", "ORDER QTY:", "CTN NO:", "QTY/CTN:", "NW:", "GW:") adalah label area marks, BUKAN baris barang.
- Teks generik seperti "BICYCLE PARTS" dan "MADE IN CHINA" BUKAN baris barang. Abaikan untuk bl_description/bl_hs_code.

1. `bl_description`:
    - Untuk SETIAP BASE_ROW, cari baris barang di BL yang kode/model-nya cocok dengan produk row tersebut.
      Pencocokan dilakukan dengan membandingkan kode/model produk pada baris BL terhadap inv_description / inv_spart_item_no / pl_item_no row tersebut.
    - Jika cocok: isi bl_description dengan teks barang pada baris BL itu (bagian nama/kode model saja, TANPA bagian "HS NUMBER: ...").
    - Jika produk row TIDAK tercantum pada daftar barang BL: isi bl_description = "null".
    - Satu baris barang BL boleh dipakai untuk BEBERAPA BASE_ROW yang produknya sama (mis. beberapa varian yang berbagi kode model yang sama). Isi bl_description yang sama pada semua row tersebut.
    - Hanya boleh mengambil dari dokumen Bill Of Lading (BL), TIDAK BOLEH dari dokumen lain.
2. `bl_hs_code`:
    - Isi dengan kode HS yang tertera setelah "HS NUMBER:" pada baris BL yang SAMA dengan bl_description row tersebut.
    - Ambil hanya angka kode HS-nya (mis. format seperti 8714.93), tanpa kata "HS NUMBER:".
    - Jika bl_description = "null", maka bl_hs_code = "null".
    - Hanya boleh mengambil dari dokumen Bill Of Lading (BL), TIDAK BOLEH dari dokumen lain.

CERTIFICATE OF ORIGIN (COO):

STRUKTUR COO VENDOR INI (form RCEP, sering memakai Continuation Sheet beberapa halaman):
- Kolom "8. Number and kind of packages; and description of goods" untuk SETIAP item diawali frasa paket "<ANGKA-HURUF> (<N>) CARTON(S) OF" lalu DIIKUTI deskripsi barang pada baris berikutnya.
  Deskripsi barang dapat ter-wrap ke beberapa baris dan BAHKAN menyambung melintasi batas halaman (akhir satu halaman menyambung ke awal halaman berikutnya). Gabungkan menjadi satu deskripsi utuh untuk item tersebut.
- Kolom "12. Quantity (Gross weight or other measurement)..." berisi DUA nilai bertumpuk: gross weight (mis. "<angka>KGS G.W.") dan quantity (mis. "<angka>SETS"/PIECES/PAIRS).
- SATU item COO BISA mewakili gabungan BEBERAPA line item invoice yang produknya sama (COO sering meng-agregat per produk). Karena itu satu item COO boleh dipetakan ke BEBERAPA BASE_ROW.

CARA MAPPING (WAJIB):
- Untuk SETIAP BASE_ROW, temukan item COO yang deskripsi barangnya (kolom 8) cocok dengan produk row tersebut.
  Pencocokan dilakukan dengan membandingkan kode/model produk pada deskripsi COO terhadap inv_description / inv_spart_item_no / pl_item_no row tersebut.
- Jika cocok: isi field coo_* item-level row dari item COO tersebut.
- Item COO yang SAMA boleh dipakai untuk beberapa BASE_ROW yang produknya sama. Isi nilai coo_* yang sama pada semua row tersebut (nilai numerik per-row akan dinormalisasi sistem mengikuti packing list).
- Jika produk row tidak ada di COO: biarkan semua coo_* item-level = "null".
- Semua field coo_* HANYA boleh diambil dari dokumen COO, TIDAK BOLEH dari invoice/PL/BL.

1. `coo_seq`:
   - Ambil dari kolom "6. Item number" (nilai numeric: 1, 2, 3, ...).
2. `coo_mark_number`:
    - Ekstrak dari "7. Marks and numbers on packages".
    - Apabila kolom 7 hanya berisi marks umum (mis. "PO NO:", "ITEM:", "ORDER QTY:", "MADE IN CHINA") yang tidak terikat ke satu item tertentu, atau tertulis "N/M", maka biarkan "null".
3. `coo_description`:
    - Ekstrak deskripsi barang dari kolom 8 SETELAH frasa paket.
    - ABAIKAN frasa jumlah paket "<...> (<N>) CARTON(S) OF" dan kata generik "BICYCLE PARTS".
    - Gabungkan baris yang ter-wrap (termasuk yang menyambung lintas halaman) menjadi satu string.
    - Jangan masukkan item number, HS code, criteria, country of origin, quantity, maupun GW.
4. `coo_hs_code`: Ekstrak dari "9. HS Code of the goods" (mis. format seperti 8714.93).
5. `coo_package_count`: Ekstrak angka pada frasa paket di kolom 8 (mis. "TWENTY (20) CARTONS OF" -> 20). Prioritaskan angka di dalam tanda kurung. Jangan tertukar dengan coo_quantity.
6. `coo_package_unit`: Ekstrak jenis kemasan pada frasa paket di kolom 8 (mis. "CARTONS" / "CARTON"). JANGAN ambil SETS/PIECES/PAIRS (itu unit quantity, bukan unit paket).
7. `coo_quantity`:
    - Ekstrak angka QUANTITY dari kolom 12, yaitu nilai yang berunit SETS/PIECES/PAIRS (mis. dari "1000SETS" ambil 1000).
    - JANGAN ambil angka gross weight untuk field ini.
8. `coo_unit`:
    - Ekstrak unit yang menempel pada coo_quantity (mis. "SETS" / "PIECES" / "PAIRS").
    - BUKAN unit berat (KGS).
9. `coo_gw`:
    - Ekstrak angka GROSS WEIGHT dari kolom 12, yaitu nilai sebelum "KGS G.W." / "KG G.W." (mis. dari "255.6KGS G.W." ambil 255.6).
10. `coo_amount`:
    - Isi hanya jika kolom 12 mencantumkan nilai/FOB secara eksplisit.
    - Jika kolom 12 hanya berisi quantity dan gross weight (tanpa value/FOB), isi "null". Jangan ambil amount dari invoice.
11. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
12. `coo_customer_po_no`: Biarkan "null" kecuali ada nomor PO yang secara spesifik ditulis per baris item di dalam COO.
"""