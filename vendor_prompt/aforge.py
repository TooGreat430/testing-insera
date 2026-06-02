AFORGE_PROMPT = """
INVOICE (INV)

1. inv_customer_po_no:
   - Ekstrak dari kolom "PO/NO"[cite: 179].
   - Contoh: "45326683", "45324062", "45324727"[cite: 179].
   - Jika tertulis kode klaim seperti "CLM26010069", tetap ekstrak sebagai nomor referensi[cite: 180].

2. inv_spart_item_no:
   - Ekstrak dari kolom "Material"[cite: 179].
   - Contoh: "FRXPVWD5030300", "FREAF330600002"[cite: 179].

3. inv_description:
   - Gabungkan teks kategori barang (kolom ke-3, misal: "FRAME PART") dengan teks di kolom "DESCRIPTION" (kolom ke-4)[cite: 179].
   - Contoh: "FRAME PART 50303-01" atau "FRAME TUBING IS20PTT08 650L"[cite: 179, 180].
   - Sertakan teks Mandarin jika ada untuk kelengkapan deskripsi[cite: 179].

4. inv_gw & inv_gw_unit:
   - Isi null karena berat kotor tidak dirinci per baris pada tabel invoice ini[cite: 179, 180, 181].

5. inv_quantity:
   - Ekstrak dari kolom "QUANTITY"[cite: 179].
   - Contoh: "532", "250", "1"[cite: 179, 180].

6. inv_quantity_unit:
   - Ekstrak dari kolom "UNIT"[cite: 179].
   - Contoh: "PCS", "SET"[cite: 179, 180].

7. inv_unit_price:
   - Ekstrak dari kolom "UNIT PRICE (USD)"[cite: 179].

8. inv_amount:
   - Ekstrak dari kolom "AMOUNT".

ATURAN KHUSUS BARIS FOC (FREE OF CHARGE) — SANGAT PENTING:
   - Sebagian baris invoice ini adalah barang gratis (FOC). Ciri-cirinya: nomor PO/NO berupa kode klaim (mis. "CLM26010069", "CLM25110169") DAN kolom "AMOUNT" tertulis "FOC" (bukan angka).
   - PADA BARIS FOC, kolom "UNIT PRICE (USD)" TETAP menampilkan angka harga referensi (mis. 7.20, 4.50). JANGAN tertipu: karena barang gratis, baris ini WAJIB diisi:
       inv_unit_price = 0
       inv_amount     = 0
   - Jadi penanda "FOC" berada di kolom AMOUNT, bukan di kolom UNIT PRICE. Begitu kolom AMOUNT = "FOC", PAKSA inv_unit_price=0 dan inv_amount=0, abaikan angka harga referensi yang tercetak.
   - inv_quantity baris FOC TETAP diisi sesuai angka di kolom QUANTITY (barang FOC tetap dihitung kuantitasnya).
   - Konsistensi: dengan aturan ini, inv_amount = inv_quantity × inv_unit_price (= qty × 0 = 0) tetap valid untuk baris FOC.

PACKING LIST (PL)

1. pl_customer_po_no:
   - Ekstrak dari kolom "PO/NO" yang sejajar dengan baris item[cite: 193].

2. pl_item_no:
   - Ekstrak dari kolom "Material"[cite: 193].

3. pl_description:
   - Gabungkan teks kategori (kolom ke-3) dengan teks di kolom "DESCRIPTION" (kolom ke-4)[cite: 193].
   - Contoh: "FRAME PART A-F3306-1"[cite: 193].

4. pl_quantity:
   - Ambil HANYA dari kolom "QTY" (kolom ke-4, total quantity item dalam satuan item: SET/PCS). Nilai ini SUDAH merupakan total untuk item tersebut.
   - DILARANG KERAS menjumlahkan angka pecahan di kolom "QTY/CTN" (kolom ke-5, mis. "L:200", "L:50", "R:200", "R:50", atau "200", "100"). Kolom QTY/CTN adalah rincian isi PER-KARTON (dalam PIECES), BUKAN quantity item.
   - CONTOH JEBAKAN (WAJIB DIPAHAMI):
       Baris: PO=45324062 | A-F3306-1 | QTY=250 | QTY/CTN: L:200, L:50, R:200, R:50
       BENAR : pl_quantity = 250 (dari kolom QTY)
       SALAH : pl_quantity = 500 (200+50+200+50 dari kolom QTY/CTN — ini menghitung PIECES, padahal item dijual per SET; 250 SET = 500 PCS tapi yang dilaporkan adalah 250)
   - Patokan kebenaran: pl_quantity HARUS sama dengan inv_quantity untuk baris yang sama (invoice & PL vendor ini 1:1 per line item dengan satuan yang sama). Jika hasil jumlah Anda ≠ inv_quantity, berarti Anda salah menjumlahkan kolom QTY/CTN — pakai kolom QTY.
   - CATATAN: penjumlahan sub-baris TETAP berlaku untuk berat/karton/volume (lihat LANGKAH 3), TAPI TIDAK untuk quantity.

5. pl_package_unit:
   - PL package unit sudah pasti Carton untuk semua line item, maka pl_package_unit = "CT".

6. pl_package_count:
   - pl_package_count = JUMLAH KARTON. Sumber: kolom "箱数" (Box Count) ATAU dihitung dari banyaknya nomor karton di kolom "CTN".
   - CARA MENGHITUNG DARI KOLOM CTN: hitung banyaknya nomor karton dalam range.
       "2"        → 1 karton
       "10-11"    → 2 karton
       "A1-A4"    → 4 karton
       "A71-A74"  → 4 karton
       "46-48"    → 3 karton
   - Jika item terdiri dari beberapa sub-baris karton (lihat LANGKAH 3), JUMLAHKAN karton seluruh sub-barisnya.

   ⛔ DILARANG KERAS — JEBAKAN KOLOM QTY/CTN:
   - JANGAN PERNAH mengisi pl_package_count dengan angka dari kolom "QTY/CTN" (kolom ke-5). Kolom QTY/CTN adalah QUANTITY ISI PER KARTON (mis. 15, 20, 30, 50), BUKAN jumlah karton.
   - Angka di kolom 箱数 (jumlah karton) umumnya KECIL (1, 2, 3, 4, 6, 11, 12, 34). Angka di kolom QTY/CTN umumnya menyerupai quantity (15, 20, 30, 50, 200). Jika pl_package_count yang Anda hasilkan menyerupai quantity/isi-per-karton, ITU SALAH.
   - CONTOH JEBAKAN NYATA (HARUS DIHINDARI):
       Baris: IS23PDT05 | QTY=35 | QTY/CTN: 15 (CTN=A58) , 20 (CTN=A59) | 箱数: 1 , 1
         BENAR : pl_package_count = 2  (A58 + A59 = 2 karton)
         SALAH : pl_package_count = 15 (itu QTY/CTN, bukan jumlah karton)
       Baris: IS21PDT04 | QTY=120 | QTY/CTN: 30 (CTN=A71-A74)
         BENAR : pl_package_count = 4  (A71..A74)
         SALAH : pl_package_count = 30 (itu QTY/CTN)
   - SANITY-CHECK: pl_package_count TIDAK boleh lebih besar dari pl_quantity, dan biasanya jauh lebih kecil. Jika lebih besar atau mendekati quantity, hampir pasti Anda salah ambil kolom QTY/CTN.

7. pl_nw:
   - Ambil total berat bersih dari kolom "NW(KGS)"[cite: 193].
   - PENTING: Kolom "NW" (tanpa KGS) adalah berat per karton, sedangkan "NW(KGS)" adalah total keseluruhan. Selalu gunakan "NW(KGS)" (nilai yang lebih besar).
   - Contoh: jika baris menunjukkan "10.0 ... 110.0", maka pl_nw = 110.0 (bukan 10.0).
   - PERHATIAN DESIMAL: Pastikan titik desimal terbaca dengan benar. Nilai seperti "11.0" (sebelas koma nol) BUKAN "110" (seratus sepuluh). Jika angka tampak tidak wajar (mis. NW per carton > 50 kg untuk FRAME PART kecil), cek ulang apakah titik desimal terbaca.

8. pl_gw:
   - Ambil total berat kotor dari kolom "GW (KGS)"[cite: 193].
   - PENTING: Gunakan kolom "GW(KGS)" (total), bukan kolom "GW" (per karton).

9. pl_volume:
   - Ambil total volume dari kolom "CUF"[cite: 193].
   - PENTING — PERHATIKAN DUA NILAI CUF: Tabel PL A-Forge memiliki DUA nilai CUF per baris:
     a) CUF TOTAL (nilai lebih besar): total kubik untuk SEMUA karton dalam group. INI yang digunakan untuk pl_volume.
     b) CUF PER KARTON (nilai lebih kecil, di kolom paling kanan): kubik satu karton saja. JANGAN digunakan.
   - Contoh: Jika baris menampilkan "22.0 2" di area CUF, maka pl_volume = 22.0 (bukan 2).
   - Contoh lain: "26.4 2.4" → pl_volume = 26.4. "10.4 2.6" → pl_volume = 10.4.
   - Untuk item yang hanya punya 1 karton (箱数=1), kedua nilai biasanya sama (mis. "0.6 0.6"), gunakan nilai pertama.

ATURAN PENTING — IDENTIFIKASI DAN PENANGANAN MERGE CELL (CARTON GROUP BERSAMA):

LANGKAH 1 — CARA MENDETEKSI SUB-ROW MERGE CELL:
Sebuah baris PL adalah SUB-ROW dalam carton group yang sama jika memenuhi SEMUA kondisi berikut:
  a) Baris tersebut memiliki nilai di kolom PO/NO, Material, Description, dan QTY.
  b) Kolom CTN (nomor/range karton) KOSONG atau tidak ada.
  c) Kolom 箱数 (box count) KOSONG atau tidak ada.
  d) Kolom NW, GW, NW(KGS), GW(KGS), CUF SEMUANYA KOSONG.

  Baris seperti ini berbagi carton group dengan baris yang ada DI ATASNYA yang memiliki data CTN lengkap.

  Contoh nyata dari dokumen ini:
  BARIS UTAMA (punya CTN):
    PO=45324061 | PIBAFIREI0510300 | FRAME TUBING REI-05-103 | QTY=2 | CTN=A1-A4 | 箱数=4 | NW=14.5 | GW=15.5 | NW(KGS)=58.0 | GW(KGS)=62.0 | CUF=10.4 | CUF/CTN=2.6
  SUB-ROW (kolom CTN dan berat KOSONG):
    PO=45325158 | PIBAFIREI0510300 | FRAME TUBING REI-05-103 | QTY=78 | [kolom lainnya kosong]

LANGKAH 2 — CARA MENGISI FIELD UNTUK SUB-ROW:
Ketika baris teridentifikasi sebagai sub-row (kolom CTN dan berat kosong):
  - pl_package_count = 0
  - pl_nw = 0
  - pl_gw = 0
  - pl_volume = 0
  - pl_quantity = nilai QTY yang tertulis di kolom QTY baris tersebut (JANGAN dijumlahkan dengan baris utama karena PO berbeda)

  JANGAN mengisi pl_nw/pl_gw/pl_volume dengan nilai NW/GW/CUF per-karton dari baris utama.

LANGKAH 3 — BEDAKAN DARI SUB-ROW YANG BUKAN MERGE CELL:
Beberapa baris memang tidak punya PO/Material eksplisit tetapi PUNYA data CTN (nomor karton berbeda). Ini BUKAN merge cell — ini adalah carton sub-row dari item yang sama.
  Contoh: FREAF330600002 untuk PO 45324062 punya sub-baris L:200, L:50, R:200, R:50 masing-masing dengan CTN berbeda (2, 3, 4, 5). Untuk kasus ini:
  - pl_quantity = nilai kolom QTY item tersebut (= 250). JANGAN dijumlahkan dari L:200+L:50+R:200+R:50. (Lihat aturan pl_quantity #4 — kolom QTY/CTN adalah PIECES per karton, bukan quantity item.)
  - pl_nw = JUMLAH semua NW(KGS) sub-baris (9.8 + 2.6 + 9.5 + 2.5 = 24.4)
  - pl_gw = JUMLAH semua GW(KGS) sub-baris (10.3 + 2.8 + 10.0 + 2.7 = 25.8)
  - pl_volume = JUMLAH semua CUF sub-baris (0.6 × 4 = 2.4)
  - pl_package_count = JUMLAH semua 箱数 sub-baris (1 + 1 + 1 + 1 = 4)

  WAJIB DIINGAT — JUMLAH SUB-BARIS YANG HARUS DIJUMLAHKAN:
  Banyaknya sub-baris berat yang harus Anda jumlahkan = banyaknya entri QTY/CTN item itu = banyaknya karton (pl_package_count). Untuk contoh di atas ada 4 entri (L:200, L:50, R:200, R:50) → Anda WAJIB menemukan dan menjumlahkan TEPAT 4 nilai NW(KGS), 4 nilai GW(KGS), 4 nilai CUF. JANGAN sampai ada sub-baris yang terlewat (penyebab utama total berat kurang). Jika item terdiri dari 4 karton tapi Anda hanya menjumlahkan 3 nilai berat, berarti ada yang terlewat — baca ulang.

RINGKASAN ATURAN DETEKSI:
  Jika kolom CTN KOSONG → sub-row merge cell → pl_package_count/nw/gw/volume = 0 (TAPI pl_quantity TETAP diisi dari kolom QTY baris itu)
  Jika kolom CTN BERISI → sub-row carton biasa (item yang sama) → jumlahkan berat/karton/volume ke baris utama, sedangkan pl_quantity = nilai kolom QTY (BUKAN penjumlahan)

SELF-CHECK FINAL SEBELUM OUTPUT (WAJIB, untuk mencegah total PL meleset):
Dokumen PL ini punya baris TOTAL di paling bawah (mis. TOTAL 174 karton, NW 1919.00, GW 2046.80, CUF 303.30). Gunakan sebagai alat verifikasi:
  1. Σ pl_quantity seluruh baris ≈ total QTY dokumen (mis. 15736). Jika lebih besar → Anda menjumlahkan QTY/CTN (PIECES) di suatu item; perbaiki ke kolom QTY.
  2. Σ pl_package_count seluruh baris ≈ total karton dokumen (mis. 174). Jika lebih besar → ada baris yang salah ambil kolom QTY/CTN sebagai jumlah karton; perbaiki.
  3. Σ pl_nw ≈ total NW(KGS) dokumen, dan Σ pl_gw ≈ total GW(KGS). Jika hasil Anda jauh LEBIH KECIL → ada sub-baris berat L/R yang terlewat saat menjumlahkan; baca ulang item-item yang dipecah L/R dan pastikan SEMUA sub-baris ikut terjumlah.
Tujuannya bukan memaksakan angka, melainkan menangkap kesalahan ekstraksi kolom/sub-baris sebelum commit.

BILL OF LADING (BL)

1. bl_description dan bl_hs_code:
   - Field bl_description dan bl_hs_code merupakan SATU PAKET dan WAJIB selalu terisi (TIDAK BOLEH NULL).
   - Sumber data HANYA boleh dari dokumen Bill Of Lading (BL) area "Description of Goods"[cite: 232, 238].

   =========================
   LOGIC MAPPING (BERURUTAN)
   =========================
   STEP 1 — Mapping berdasarkan inv_description:
   - Cari apakah inv_description MATCH dengan deskripsi item pada BL[cite: 236, 237, 238].
   - Jika ditemukan: bl_description = deskripsi di BL, bl_hs_code = HS Number terkait di BL.

   STEP 2 — Jika TIDAK ditemukan di STEP 1, mapping berdasarkan kode part:
   - Identifikasi kode part (misal: A-F3306-1) dalam deskripsi BL[cite: 236].
   - Jika MATCH: bl_description = deskripsi penuh di baris BL tersebut, bl_hs_code = HS Number terkait.

   STEP 3 — Jika STEP 1 dan STEP 2 TIDAK ditemukan:
   - PILIH SECARA ACAK (RANDOM) satu pasangan data dari item yang tersedia di BL[cite: 236, 237, 238].
   - JANGAN MEMBUAT DATA BARU. Gunakan item yang ada di BL (Contoh: "FRAME PART A-HG009", HS: "8714.91")[cite: 237].

CERTIFICATE OF ORIGIN (COO)

1. coo_seq
   - Ambil dari kolom "Item number".
   - Nilai numeric.
   - Item number tercetak jelas seperti:
     - 1
     - 2
     - 3
     - ...
     
1. coo_mark_number:
   - Ekstrak dari kolom "7. Marks and numbers on packages"[cite: 28, 92].
   - Biasanya bernilai "N/M"[cite: 28, 143].

2. coo_description:
   - Ekstrak dari kolom "8. Number and kind of packages; and description of goods"[cite: 28, 92].
   - Contoh: "FRAME PART: 50303-01"[cite: 28].

3. coo_hs_code:
   - Ekstrak dari kolom "9. HS Code"[cite: 28].
   - Pertahankan format titik jika ada, contoh: "8714.91"[cite: 28].

4. coo_quantity:
   - Ambil angka numerik quantity dari kolom "12. Quantity"[cite: 28, 92].
   - Contoh: "532", "250"[cite: 28].

5. coo_unit:
   - Ambil satuan unit dari kolom "12. Quantity"[cite: 28].
   - Contoh: "PIECES", "SETS"[cite: 28].

6. coo_package_count:
   - Ekstrak jumlah karton per item jika tertera dalam deskripsi Box 8. Jika tidak terperinci, gunakan data dari Packing List sebagai referensi.

7. coo_package_unit:
   - COO package unit sudah pasti Carton untuk semua line item, maka coo_package_unit = "CT".

8. coo_gw:
   - Ambil nilai berat kotor jika tertera eksplisit di Box 12. Jika Box 12 hanya berisi quantity barang, isi null[cite: 28, 92].

9. coo_amount:
   - Isi null karena origin criterion yang digunakan adalah "PE", sehingga nilai FOB (Value) tidak wajib dicantumkan pada kolom 12 dokumen ini[cite: 28, 69, 79].

10. coo_criteria:
    - Ekstrak dari kolom "10. Origin Conferring Criterion"[cite: 28].
    - Contoh: "PE"[cite: 28].

11. coo_customer_po_no:
    - Isi hanya jika ada nomor PO yang tertulis eksplisit pada COO (Box 8 atau Box 14). Jika tidak ada, isi null.
"""