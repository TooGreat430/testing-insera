SUNTOUR_SHENZEN_PROMPT = """

INVOICE (INV)

1. inv_customer_po_no:
   - Ekstrak dari kolom "P/O No./Description".
   - Pada format vendor ini, nomor PO adalah angka yang muncul setelah "Item No." dan sebelum kolom "Qty".
   - Contoh: "45324845".
   - Jangan ambil "Ref No".

2. inv_spart_item_no:
   - Ekstrak dari kolom "Item No.".
   - Contoh: "GSFXCM32DZ000036".

3. inv_description:
   - Prioritaskan deskripsi lengkap barang pada blok teks dalam tanda kurung di bagian bawah invoice, karena itu adalah deskripsi item paling lengkap.
   - Jika blok tanda kurung tidak ada, gabungkan seluruh teks deskripsi pada area "P/O No./Description" yang berada di bawah item utama sampai sebelum garis total.
   - Contoh format:
     "FORK SUSPENSION GSFXCM32DZ000036;SUNTOUR;SF23-XCM32DS;MATTEBLACKBLADE/CP STANCHION/MATTEBLACK CROWN;-;DISC PM160 QR/NUT,ALLOY BLADE/ALLOY CROWN, 27.5 THREADLESS 28(1-1/8") 255.00MMSTEEL STEERER 100.00 COIL W/ PRELOADADJUSTER - - W/ SEPARATEDECAL"

4. inv_gw & inv_gw_unit:
   - Isi null kecuali ada gross weight yang tertulis eksplisit pada invoice.

5. inv_quantity:
   - Ekstrak dari kolom "Qty".
   - Contoh: "3355".

6. inv_quantity_unit:
   - Ekstrak dari kolom "Unit".
   - Contoh: "SET".

7. inv_unit_price:
   - Ekstrak dari kolom "U/Price(USD)".
   - Contoh: "19".

PACKING LIST (PL)

CATATAN PENTING — LINGKUP PENJUMLAHAN BARIS (berlaku untuk pl_quantity, pl_package_count,
pl_nw, pl_gw, pl_volume):
   - KODE ITEM yang sama bisa muncul di BEBERAPA baris invoice/PO yang berbeda
     (mis. "GSFXCEDSZ0000533" muncul sebagai 1781 set untuk satu PO, dan 825 set untuk PO lain).
     JANGAN menjumlahkan SEMUA baris carton berkode item sama menjadi satu total
     (mis. JANGAN 1781 + 825 = 2606).
   - Penjumlahan baris carton yang "terpecah" hanya untuk baris yang membentuk SATU
     baris invoice. Patokan paling andal: pilih kumpulan baris carton (umumnya berurutan)
     yang TOTAL Qty-nya SAMA dengan inv_quantity baris tersebut, lalu jumlahkan
     pl_nw/pl_gw/pl_volume/pl_package_count HANYA untuk kumpulan baris carton itu.
   - Contoh: inv_quantity = 1781 -> baris carton 0001-0178 (1780) + 0179-0179 (1) = 1781.
             inv_quantity = 825  -> baris carton 0245-0326 (820) + 0327-0327 (5)   = 825.

1. pl_customer_po_no:
   - Ekstrak dari baris dengan label "CUSTOMER PO:".
   - Contoh: "45324845".

2. pl_item_no:
   - Ekstrak dari kolom "Item No.".
   - Contoh: "GSFXCM32DZ000036".

3. pl_description:
   - Prioritaskan deskripsi lengkap barang pada blok teks dalam tanda kurung di bagian bawah packing list.
   - Jika blok tersebut tidak ada, gabungkan seluruh teks deskripsi item setelah "Item No." sampai sebelum kolom "Unit", "Qty", "N.W.(KG)", "G.W.(KG)", atau "Measurement".
   - Sertakan baris lanjutan/wrapped text yang masih merupakan bagian dari deskripsi item.

4. pl_quantity:
   - Ekstrak total quantity item.
   - Jangan ambil nilai yang diakhiri dengan @
   - Jika item yang sama terpecah ke beberapa baris, jumlahkan semua nilai pada kolom "Qty".
     - Contoh: 
        Qty
        3354
        1
        maka pl_quantity = 3355 (3354 + 1)

5. pl_package_unit:
   - Ekstrak jenis kemasan dari statement total packing atau dari konteks CTN/carton.
   - Pada format vendor ini, gunakan unit kemasan sebagaimana tertulis, misalnya "CARTONS" atau "CTNS".
   - Jangan ubah ke unit lain.

6. pl_package_count:
   - Ekstrak total jumlah kemasan per item.
   - Ekstrak dan hitung dari kolom range CTN# / PTL#.
   - Jika item yang sama terpecah ke beberapa baris, jumlahkan semua nilai range "PTL# / CTN#"
     - Contoh: 
       PTL# / CTN#
       0001- 0559  -> 559
       0560- 0560  -> 1
       maka pl_package_count = 560 (559 + 1)

7. pl_nw:
   - Ekstrak total net weight per item.
   - Ambil nilai yang tidak diakhiri dengan @
   - Jika item terpecah ke beberapa baris, jumlahkan semua nilai "N.W.(KG)" untuk item tersebut.
     - Contoh:
       N.W (KG)
       10173.8
       3
       maka pl_nw = 10176.8 (10173.8 + 3)

8. pl_gw:
   - Ekstrak total gross weight per item.
   - Ambil nilai yang tidak diakhiri dengan @
   - Jika item yang sama terpecah ke beberapa baris, jumlahkan semua nilai "G.W.(KG)".
     - Contoh: 
       G.W (KG)
       11850.8
       3.2
       maka pl_gw = 11854.

9. pl_volume:
   - Ekstrak total numeric value dari kolom "Measurement".
   - Ambil nilai yang tidak diakhiri dengan @
   - Jika item yang sama terpecah ke beberapa baris, jumlahkan semua nilai "Measurement".
     - Contoh:
       Measurement
       2236
       0.8
       maka pl_volume = 2236.8
   - Jangan konversi value meskipun BL mungkin memiliki volume unit yang berbeda dari PL.

BILL OF LADING (BL)

STRUKTUR KOLOM "Number and Kind of packages / Description of Goods" PADA BL:
   - Kolom MARKS (kiri) berisi "N/M" -> itu untuk bl_mark_number, BUKAN bl_description.
   - Kolom DESCRIPTION OF GOODS (utama) diawali baris umum
     ("1 x 40HC CONTAINER", "STC <N> CARTON(S)", "BICYCLE PARTS"), lalu DIIKUTI
     DAFTAR ITEM per produk dengan format:
         "<DESKRIPSI ITEM termasuk KODE ITEM>, HS CODE: <kode HS>"
     Contoh nyata pada dokumen ini:
         FORK SUSPENSION GSFXCEDSZ0000533, HS CODE: 8714.91
         FORK SUSPENSION GSFXCEDSZ0000532, HS CODE: 8714.91
         FORK SUSPENSION GSFXCEDSZ0000690, HS CODE: 8714.91
         FORK SUSPENSION GSFXCEDSZ0000530, HS CODE: 8714.91

1. bl_description:
   - Untuk SETIAP baris item, cocokkan KODE ITEM baris tersebut
     (inv_spart_item_no, mis. "GSFXCEDSZ0000533", atau kode yang sama di inv_description)
     dengan salah satu baris di daftar BL.
   - Isi bl_description dengan teks deskripsi BL pada baris yang cocok, yaitu teks
     SEBELUM ", HS CODE:" (mis. "FORK SUSPENSION GSFXCEDSZ0000533").
   - Jika kode item baris tidak ada di daftar BL, isi null.
   - ABAIKAN baris generik "BICYCLE PARTS", "STC ... CARTON(S)", "... CONTAINER",
     dan kolom marks ("N/M").
   - Hanya boleh mengambil dari dokumen Bill Of Lading (BL), TIDAK dari dokumen lain.

2. bl_hs_code:
   - Isi dengan kode HS SETELAH "HS CODE:" pada baris BL yang sama (mis. "8714.91").
   - bl_description dan bl_hs_code SATU PAKET: keduanya terisi atau keduanya null.

CERTIFICATE OF ORIGIN (COO)

1. coo_seq
   - Ambil dari kolom "Item number".
   - Nilai numeric.
   - Item number tercetak jelas seperti:
     - 1
     - 2
     - 3
     - ...

2. coo_mark_number
   - Ekstrak dari field "7. Marks and numbers on packages".
   - Pada format vendor ini bisa berupa "N/M".
   - Ambil persis seperti tertulis.

3. coo_description:
   - Ekstrak dari field "8. Number and kind of packages; and description of goods".
   - Abaikan frasa jumlah kemasan di awal/akhir seperti:
     "FIVE HUNDRED AND SIXTY (560) CTNS".
   - Abaikan juga informasi BL No. dan Container No. bila muncul setelah deskripsi.
   - Fokus pada deskripsi barangnya saja.
   - Contoh hasil:
     "BICYCLE PARTS FORK SUSPENSION GSFXCM32DZ000036;SUNTOUR;SF23-XCM32DS;MATTEBLACKBLADE/CP STANCHION/MATTEBLACK CROWN;-;DISC PM160 QR/NUT,ALLOY BLADE/ALLOY CROWN, 27.5 THREADLESS 28(1-1/8") 255.00MMSTEEL STEERER 100.00 COIL W/ PRELOADADJUSTER - - W/ SEPARATEDECAL"

4. coo_hs_code:
   - Ekstrak dari field "9. HS Code of the goods".
   - Contoh: "8714.91".

5. coo_package_count:
   - Ekstrak angka numerik dari frasa jumlah kemasan dalam field 8.
   - Contoh:
     dari "FIVE HUNDRED AND SIXTY (560) CTNS"
     ambil "560".

6. coo_package_unit:
   - Ekstrak unit kemasan dari frasa jumlah kemasan dalam field 8.
   - Contoh: "CTNS".

7. coo_gw & coo_quantity:
   - Untuk vendor ini, cek isi field "12. Quantity (Gross weight or other measurement)..."
   - Jika field 12 berisi quantity + unit, misalnya "3355SETS", maka:
     - coo_quantity = 3355
     - coo_gw = null
   - Hanya isi coo_gw jika ada nilai berat eksplisit dengan unit seperti KG/KGS.

8. coo_unit:
   - Ekstrak unit yang melekat pada field 12.
   - Jika field 12 berisi quantity, ambil unit quantity tersebut.
   - Contoh: "SETS".
   - Jika field 12 berisi berat, ambil unit beratnya, misalnya "KG".

9. coo_criteria:
   - Ekstrak dari field "10. Origin Conferring Criterion".
   - Jika ada tanda kutip, hilangkan tanda kutipnya.
   - Contoh: "RVC".

10. coo_customer_po_no:
   - Isi hanya jika ada nomor PO yang tertulis eksplisit.
   - Jika tidak ada referensi PO yang jelas, isi null.  
"""