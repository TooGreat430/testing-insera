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

1. bl_description dan bl_hs_code:
   - Field bl_description dan bl_hs_code merupakan SATU PAKET dan WAJIB selalu terisi (TIDAK BOLEH NULL).
   - Sumber data HANYA boleh dari dokumen Bill Of Lading (BL) saja, TIDAK BOLEH mengambil dari dokumen lain.

   =========================
   LOGIC MAPPING (BERURUTAN)
   =========================
   - STEP 1 - Mapping berdasarkan inv_description:
     - Cari apakah inv_description MATCH dengan kode barang pada deskripsi item pada BL.
     - Jika ditemukan:
       - bl_description = description item pada BL yang sesuai
       - bl_hs_code = HS CODE yang terkait dengan bl_description tersebut
  - STEP 2 - Jika STEP 2 tidak ditemukan:
     - Karena bl_description dan bl_hs_code TIDAK BOLEH NULL,
   - Maka PILIH SECARA ACAK (RANDOM) satu pasangan data dari item BL:
     - bl_description = salah satu description item dari BL
     - bl_hs_code = HS CODE yang sesuai dengan item tersebut
   - JANGAN MEMBUAT BL DESCRIPTION DAN BL HS CODE BARU YANG TIDAK ADA DI DOKUMEN BILL OF LADING (BL). GUNAKAN RANDOM ITEM YANG ADA SAJA DI DOKUMEN BILL OF LADING (BL).
     Contoh:
     DATA DI BL SEPERTI INI:
     HUB 751DSE HS NUMBER: 8714.93
     HUB 753DSE HS NUMBER: 8714.93
     HUB 752DSE HS NUMBER: 8714.93
     HUB 754DSE HS NUMBER: 8714.93
     HUB D761DSE HS NUMBER: 8714.93
     
     JANGAN BUAT DATA BARU SEPERTI = HUB 431BK, YANG TIDAK ADA PADA DOKUMEN BILL OF LADING SEBAGAI HASIL EKSTRAKSI DAN MAPPING.
   =========================
   ATURAN PENTING
   =========================
   - Tidak boleh mengosongkan field (NO NULL VALUE).
   - bl_description dan bl_hs_code harus selalu berpasangan dari item BL yang sama.
   - Sumber data hanya boleh dari dokumen Bill of Lading (BL) saja.
   - Tidak boleh membuat atau mengarang data di luar dari dokumen Bill of Lading (BL).
   - Tidak boleh mengambil HS CODE dari item yang berbeda dengan bl_description.
   - Prioritas mapping:
       1. inv_description (utama)
       3. random BL item (last resort, WAJIB jika tidak match)

   =========================
   CONTOH
   =========================
   BL:
     - HUB 751DSE HS NUMBER: 8714.93
     - HUB 753DSE HS NUMBER: 8714.93
     - HUB 752DSE HS NUMBER: 8714.93
     - HUB 754DSE HS NUMBER: 8714.93
     - HUB D761DSE HS NUMBER: 8714.93

   Case 1:
     inv_description = 751DSE ANO.BLACK 32X14 W/O LOGO 9X108X100 270:112 ANO.BLACK W/O LOGO W/WARNING LOGO
     → MATCH STEP 1 (751DSE MATCH dengan HUB 751DSE)
     → bl_description = HUB 751DSE
     → bl_hs_code = 8714.93

   Case 2:
     inv_description = 431 BK 32X14 W/O LOGO 69L 9X108X100 270:112 ANO.BLACK W/O LOGO W/WARNING LOGO
     inv_description tidak ada di BL
     → STEP 3 (RANDOM)
     → bl_description = HUB 753DSE (contoh random)
     → bl_hs_code = 8714.93

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
5. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "TEN (10) CARTONS" ambil angka 10).
6. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "CARTONS").
7. `coo_gw` & `coo_quantity`: Ekstrak berat angka dari kolom "12. Quantity..." (biasanya ditulis dengan format seperti "255.6KGS G.W.").
8. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KGS").
9. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
10. `coo_customer_po_no`: Biarkan null kecuali ada nomor PO yang secara spesifik ditulis per baris item.
"""