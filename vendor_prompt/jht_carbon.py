TANGSHAN_JINHENGTONG_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari kolom "PO No.".
2. `inv_spart_item_no`: Ekstrak dari kolom "Material".
3. `inv_description`: Ekstrak dari kolom "Description".
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak dari kolom "qty".
6. `inv_quantity_unit`: Ekstrak dari kolom "unit" (misalnya "SET" atau "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Unit Price" (hapus simbol mata uang seperti $).
8.  `inv_amount`: Ekstrak nilai angka dari kolom "Amount" (hapus koma dan simbol mata uang).

PACKING LIST (PL):
INSTRUKSI PENTING:
Pada vendor ini, value setiap line item sudah bersifat ATOMIC sehingga DILARANG KERAS untuk menambahkan value numerik pada satu line item ke line item lain TANPA TERKECUALI!
Apabila ada line item pada PL yang TIDAK MEMILIKI pl_customer_po_no, pl_item_no, dan pl_description; maka ABAIKAN LINE ITEM TERSEBUT!
Contoh:
Line item yang tidak memiliki pl_customer_po_no, pl_item_no (misal hanya ada keterangan "Spare parts"), dan pl_description namun memiliki nilai numerik pada pl_quantity, pl_package_count, pl_nw, pl_gw, atau pl_volume; maka line item tersebut HARUS DIABAIKAN dan TIDAK BOLEH DITAMBAHKAN ke line item lain.
Line item ini biasanya terletak di bagian bawah tabel PL dengan keterangan yang sangat umum seperti "Spare parts" tanpa informasi detail lainnya. Meskipun memiliki nilai numerik pada beberapa kolom, line item ini TIDAK BOLEH DIGABUNGKAN dengan line item lain MANAPUN karena tidak memiliki informasi yang cukup untuk diidentifikasi secara unik.

1. `pl_customer_po_no`: Ekstrak dari kolom "PO No.".
2. `pl_item_no`: Ekstrak dari kolom "Material".
3. `pl_description`: Ekstrak dari kolom "DESCRIPTION".
4. `pl_quantity`: Ekstrak nilai angka dari kolom "Qty".
5. `pl_package_unit`: Simpulkan sebagai "CARTONS" berdasarkan konteks header "Number of Carton".
6. `pl_package_count`: Ekstrak dari kolom "Number of Carton".
7. `pl_nw`: Ekstrak dari kolom "N.W(KG)" dengan sub-kolom 'total'.
8. `pl_gw`: Ekstrak dari kolom "G.W(KG)" dengan sub-kolom 'total'.
9. `pl_volume`: Ekstrak nilai angka dari kolom "CBM" dengan sub-kolom 'total'.

BILL OF LADING (BL):
1. bl_description dan bl_hs_code:
   - Field bl_description dan bl_hs_code merupakan SATU PAKET dan WAJIB selalu terisi (TIDAK BOLEH NULL).
   - Sumber data HANYA boleh dari dokumen Bill Of Lading (BL) saja, TIDAK BOLEH mengambil dari dokumen lain.

   =========================
   LOGIC MAPPING (BERURUTAN)
   =========================
   STEP 1 — Mapping berdasarkan inv_description:
   - Cari apakah inv_description MATCH dengan deskripsi item pada BL.
   - Jika ditemukan:
     - bl_description = description item pada BL yang sesuai
     - bl_hs_code = HS CODE yang terkait dengan bl_description tersebut

   STEP 2 — Jika TIDAK ditemukan di STEP 1, mapping berdasarkan inv_spart_item_no:
   - Pada deskripsi BL, identifikasi nomor spart item (biasanya berupa kode unik di akhir deskripsi).
     Contoh:
       FORK SUSPENSION GSFM3010APV00034 → spart item = GSFM3010APV00034
   - Jika inv_spart_item_no MATCH dengan spart item pada BL:
     - bl_description = description item pada BL yang mengandung spart item tersebut
     - bl_hs_code = HS CODE yang terkait

   STEP 3 — Jika STEP 1 dan STEP 2 TIDAK ditemukan:
   - Karena bl_description dan bl_hs_code TIDAK BOLEH NULL,
   - Maka PILIH SECARA ACAK (RANDOM) satu pasangan data dari item BL:
     - bl_description = salah satu description item dari BL
     - bl_hs_code = HS CODE yang sesuai dengan item tersebut
   - JANGAN MEMBUAT BL DESCRIPTION DAN BL HS CODE BARU YANG TIDAK ADA DI DOKUMEN BILL OF LADING (BL). GUNAKAN RANDOM ITEM YANG ADA SAJA DI DOKUMEN BILL OF LADING (BL).
     Contoh:
     DATA DI BL SEPERTI INI:
     FORK SUSPENSION GSFM3010APV00034  HS CODE: 8714.91
     FORK SUSPENSION GSFNEXDSV0000261  HS CODE: 8714.91
     FORK SUSPENSION GSFNEXE25DSV0830  HS CODE: 8714.91
     FORK SUSPENSION GSFNEXE25PDV0021  HS CODE: 8714.91
     FORK SUSPENSION GSFNVX30DSV00484  HS CODE: 8714.91
     
     JANGAN BUAT DATA BARU SEPERTI = FORK SUSPENSION GSFXCM32DSV00012, YANG TIDAK ADA PADA DOKUMEN BILL OF LADING SEBAGAI HASIL EKSTRAKSI DAN MAPPING.
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
       2. inv_spart_item_no (fallback)
       3. random BL item (last resort, WAJIB jika tidak match)

   =========================
   CONTOH
   =========================
   BL:
     - FRAME PART A-HG009 HS CODE: 8714.91
     - FORK SUSPENSION GSFM3010APV00034 HS CODE: 8714.91

   Case 1:
     inv_description = FRAME PART A-HG009
     → MATCH STEP 1
     → bl_description = FRAME PART A-HG009
     → bl_hs_code = 8714.91

   Case 2:
     inv_spart_item_no = GSFM3010APV00034
     → MATCH STEP 2
     → bl_description = FORK SUSPENSION GSFM3010APV00034
     → bl_hs_code = 8714.91

   Case 3:
     inv_description & inv_spart_item_no tidak ada di BL
     → STEP 3 (RANDOM)
     → bl_description = FRAME PART A-HG009 (contoh random)
     → bl_hs_code = 8714.91

CERTIFICATE OF ORIGIN (COO):
1. `coo_mark_number`:
    - Ekstrak dari "7. Marks and numbers on packages".
    - Apabila tidak ada informasi marks and numbers pada kolom 7 atau tertlulis "N/M" (Not Mentioned), maka biarkan null.s
2. `coo_description`: Ekstrak deskripsi teks dari kolom "8. Number and kind of packages; and description of goods." Abaikan keterangan jumlah paket (angka dan kata) pada field ini.
3. `coo_hs_code`: Ekstrak dari "9. HS Code of the goods".
4. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "FIFTY SIX (56) CARTONS" ambil angka 56).
5. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "CARTONS").
6. `coo_gw` & `coo_quantity`: Ekstrak berat angka dari kolom "12. Quantity...".
7. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KGS").
8. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion".
9. `coo_customer_po_no`: Biarkan null kecuali ada nomor PO yang secara spesifik ditulis per baris item.
"""