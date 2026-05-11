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
   - Jika tertulis "FOC", isi dengan 0[cite: 180, 181].

PACKING LIST (PL)

1. pl_customer_po_no:
   - Ekstrak dari kolom "PO/NO" yang sejajar dengan baris item[cite: 193].

2. pl_item_no:
   - Ekstrak dari kolom "Material"[cite: 193].

3. pl_description:
   - Gabungkan teks kategori (kolom ke-3) dengan teks di kolom "DESCRIPTION" (kolom ke-4)[cite: 193].
   - Contoh: "FRAME PART A-F3306-1"[cite: 193].

4. pl_quantity:
   - Ambil total quantity dari kolom "QTY"[cite: 193].
   - Jika satu item terbagi dalam beberapa baris karena beda karton, jumlahkan seluruh quantity untuk item tersebut[cite: 193, 195].

5. pl_package_unit:
   - PL package unit sudah pasti Carton untuk semua line item, maka pl_package_unit = "CT".

6. pl_package_count:
   - Ekstrak jumlah karton dari kolom "箱数" (Box Count) atau hitung dari range kolom "CTN"[cite: 193, 195].
   - Contoh: Jika kolom CTN berisi "10-11", maka pl_package_count = 2[cite: 193].

7. pl_nw:
   - Ambil total berat bersih dari kolom "NW(KGS)"[cite: 193].

8. pl_gw:
   - Ambil total berat kotor dari kolom "GW (KGS)"[cite: 193].

9. pl_volume:
   - Ambil total volume dari kolom "CUF"[cite: 193].

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