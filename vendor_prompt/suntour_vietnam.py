SUNTOUR_VIETNAM_PROMPT = """

INVOICE (INV)

1. inv_customer_po_no:
   - Ekstrak dari kolom "PONo.".
   - Contoh: "45326060", "45324852", "45327078".
   - Jangan ambil "Invoice No." atau "Ref. No.".

2. inv_spart_item_no:
   - Ekstrak dari kolom "ItemNo.".
   - Contoh: "GSFM3010APV00034".

3. inv_description:
   - Prioritaskan deskripsi lengkap barang pada blok teks dalam tanda kurung di bagian bawah invoice, karena itu adalah deskripsi item paling lengkap.
   - Jika blok tanda kurung tidak ada, gabungkan seluruh teks deskripsi pada area "P/O No./Description" yang berada di bawah item utama sampai sebelum garis total.
   - Contoh format:
     "FORK SUSPENSION GSFXCM32DZ000036;SUNTOUR;SF23-XCM32DS;MATTEBLACKBLADE/CP STANCHION/MATTEBLACK CROWN;-;DISC PM160 QR/NUT,ALLOY BLADE/ALLOY CROWN, 27.5 THREADLESS 28(1-1/8") 255.00MMSTEEL STEERER 100.00 COIL W/ PRELOADADJUSTER - - W/ SEPARATEDECAL"

4. inv_gw & inv_gw_unit:
   - Isi null kecuali ada gross weight yang tertulis eksplisit pada invoice.

5. inv_quantity:
   - Ekstrak dari kolom "Quantity".
   - Contoh: "500.000", "235.000", "1544.000".

6. inv_quantity_unit:
   - Ekstrak dari kolom "Unit".
   - Contoh: "SET".

7. inv_unit_price:
   - Ekstrak dari kolom "U/P(Trans.C)".
   - Contoh: "13.2000", "17.4000", "20.0000".

PACKING LIST (PL)

1. pl_customer_po_no:
   - Ekstrak dari baris angka kedua pada setiap blok item, yaitu angka pertama yang muncul tepat di bawah baris header item.
   - Posisinya persis di bawah Nomor Carton.
   - Contoh:
     Baris 1: "1-50     50  GSFM3010APV00034 ... "
     Baris 2: "45326060 500     1,140.0     1,290.0     260.00"
     Maka pl_customer_po_no = "45326060".

2. pl_item_no:
   - Ekstrak dari kolom "ITEM #".
   - Contoh: "GSFM3010APV00034".

3. pl_description:
   - Ekstrak blok deskripsi teks yang muncul setelah 2 baris numerik tiap item.
   - Gabungkan semua baris deskripsi lanjutan sampai sebelum blok item berikutnya.
   - Sertakan spesifikasi produk yang memang merupakan bagian dari deskripsi.
   - Jangan sertakan nomor PO, qty total, NW total, GW total, atau volume total.

4. pl_quantity:
   - Ambil total quantity item dari baris angka kedua tiap blok item, BUKAN dari qty per karton di baris header.
   - Contoh:
     Baris header: "SET 10  22.8    25.8    5.20" -> ini qty per carton, jangan dipakai sebagai total.
     Baris kedua: "     500 1,140.0 1,290.0 260.00" -> gunakan angka "500".
   - Jika item yang sama muncul di beberapa blok, jumlahkan seluruh total quantity pada baris kedua.
   - Contoh:
     5 + 230 + 5 = 240.

5. pl_package_unit:
   - PL package unit sudah pasti Carton untuk semua line item,
   MAKA pl_package_unit = "CT" untuk semua line item

6. pl_package_count:
   - Ekstrak jumlah karton per item.
   - Prioritaskan kolom "CARTON #" pada baris header item.
   - Jika item yang sama muncul di beberapa blok, jumlahkan semua nilai "CARTON #".
   - Jika kolom "CARTON #" tidak terbaca, hitung dari range "CARTON NO." secara inklusif.
   - Contoh:
     "1-23" = 23
     "24-24" = 1
     maka total = 24.

7. pl_nw:
   - Ambil total net weight dari baris angka kedua tiap blok item, BUKAN nilai N.W per carton pada baris header.
   - Jika item yang sama muncul di beberapa blok, jumlahkan semua total N.W tersebut.
   - Contoh:
     13.3 + 609.5 + 13.3 = 636.1

8. pl_gw:
   - Ambil total gross weight dari baris angka kedua tiap blok item, BUKAN nilai G.W per carton pada baris header.
   - Jika item yang sama muncul di beberapa blok, jumlahkan semua total G.W tersebut.

9. pl_volume:
   - Ambil total volume dari baris angka kedua tiap blok item, BUKAN unit volume per carton pada baris header.
   - Jika item yang sama muncul di beberapa blok, jumlahkan semua total volume tersebut.
   - Jangan konversi unit meskipun BL menuliskan measurement dalam format berbeda.

BILL OF LADING (BL)

1. bl_description dan bl_hs_code:
   - Field bl_description dan bl_hs_code merupakan SATU PAKET dan WAJIB selalu terisi (TIDAK BOLEH NULL).
   - Sumber data HANYA boleh dari dokumen Bill Of Lading (BL), TIDAK BOLEH mengambil dari dokumen lain.

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

   =========================
   ATURAN PENTING
   =========================
   - Tidak boleh mengosongkan field (NO NULL VALUE).
   - bl_description dan bl_hs_code harus selalu berpasangan dari item BL yang sama.
   - Tidak boleh membuat atau mengarang data di luar BL.
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
   
CERTIFICATE OF ORIGIN (COO)

1. coo_mark_number:
   - Ekstrak dari kolom "Marks and Numbers".
   - Pada format vendor ini nilainya dapat berupa "no".
   - Ambil persis seperti tertulis.

2. coo_description:
   - Ekstrak dari kolom "Description".
   - Gabungkan teks yang terpotong/wrapped dalam 1 item menjadi 1 string utuh.
   - Jangan sertakan quantity, hs code, gross weight, FOB, invoice number, atau date.
   - Contoh:
     "FORK SUSPENSION GSFM3010APV00034"

3. coo_hs_code:
   - Ekstrak dari kolom "HS Number".
   - Pertahankan format persis seperti di COO.
   - Pada vendor ini HS code ditulis 8 digit, misalnya "87149199".
   - Jangan ubah menjadi format bertitik seperti "8714.91".

4. coo_quantity:
   - Ambil quantity utama barang dari baris pertama pada kolom "Quantity".
   - Contoh:
     Quantity Code:
       SET
       CT
     Quantity:
       500.0000
       50
     Maka coo_quantity = 500.0000

5. coo_unit:
   - Karena schema hanya menyediakan 1 field unit, gunakan unit utama quantity dari baris pertama kolom "Quantity Code".
   - Contoh: 
     Quantity Code:
     SET
     CT
     Maka coo_unit = "SET"
   - Jangan isi dengan package unit; package unit sudah masuk ke coo_package_unit.

6. coo_package_count:
   - Pada format e-COO ini, package count diambil dari baris kedua pada kolom "Quantity", yaitu angka yang berpasangan dengan package unit di baris kedua kolom "Quantity Code".
   - Contoh:
     Quantity Code:
       SET
       CT
     Quantity:
       500.0000
       50
     Maka:
       coo_package_count = 50

7. coo_package_unit:
   - COO package unit sudah pasti Carton untuk semua line item,
   MAKA coo_package_unit = "CT" untuk semua line item.

8. coo_gw:
   - Ambil dari kolom "Gross weight or Other Quantity".
   - Pada vendor ini nilainya adalah gross weight item.
   - Contoh: "1290.0000", "693.8000", "5482.0000".

9. coo_amount:
   - Pada format e-COO ini, coo_amount diambil dari kolom "Value" yang merupakan sub kolom "FOB"
   - Contoh: "6600.00000", "87.00000", "49.40000"

10. coo_criteria:
   - Ekstrak kode origin criterion dari kolom "Origin Criterion".
   - Jika kolom berisi "RVC 49.92%" atau format sejenisnya, abaikan value numerik presentasenya.
     maka coo_criteria = "RVC"

11. coo_customer_po_no:
   - Isi hanya jika ada nomor PO yang tertulis eksplisit pada COO.
   - Jangan gunakan invoice number sebagai PO number.
   - Jika tidak ada referensi PO yang jelas, isi null. 
"""
