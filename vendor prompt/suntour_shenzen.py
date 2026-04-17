SUNTOUR_SHENZEN_PROMPT = """

INVOICE (INV):

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

1. bl_description dan bl_hs_code:
   - bl_description dimapping dengan inv_description. Jika inv_description tidak exist pada dokumen BL, maka bl_description fill null saja.
   - Value bl_hs_code diisi sesuai dengan bl_descriptionnya.
   - Hanya boleh mengambil dari dokumen Bill Of Lading (BL), TIDAK BOLEH dari dokumen yang lain

   - Contoh:
     FRAME PART A-F3306-1 HS NUMBER: 8714.91
     FRAME PART A-HG009 HS NUMBER: 8714.91
     FRAME PART A-HG011 HS NUMBER: 8714.91
     FRAME PART A-HG045 HS NUMBER: 8714.91
     FRAME TUBING HS NUMBER: 8714.91

     - Misalkan pada inv_description ada value FRAME PART AF-9F-0270, dimana itu tidak ada pada description item BL. 
       Maka bl_description dan bl_hs_code isi null saja.
     - Misalkan pada inv_description ada value FRAME PART A-HG009, dimana itu ada pada description item BL.
       Maka bl_description isi FRAME PART A-HG009 dan bl_hs_code isi 8714.91

CERTIFICATE OF ORIGIN (COO)

1. coo_mark_number
   - Ekstrak dari field "7. Marks and numbers on packages".
   - Pada format vendor ini bisa berupa "N/M".
   - Ambil persis seperti tertulis.

2. coo_description:
   - Ekstrak dari field "8. Number and kind of packages; and description of goods".
   - Abaikan frasa jumlah kemasan di awal/akhir seperti:
     "FIVE HUNDRED AND SIXTY (560) CTNS".
   - Abaikan juga informasi BL No. dan Container No. bila muncul setelah deskripsi.
   - Fokus pada deskripsi barangnya saja.
   - Contoh hasil:
     "BICYCLE PARTS FORK SUSPENSION GSFXCM32DZ000036;SUNTOUR;SF23-XCM32DS;MATTEBLACKBLADE/CP STANCHION/MATTEBLACK CROWN;-;DISC PM160 QR/NUT,ALLOY BLADE/ALLOY CROWN, 27.5 THREADLESS 28(1-1/8") 255.00MMSTEEL STEERER 100.00 COIL W/ PRELOADADJUSTER - - W/ SEPARATEDECAL"

3. coo_hs_code:
   - Ekstrak dari field "9. HS Code of the goods".
   - Contoh: "8714.91".

4. coo_package_count:
   - Ekstrak angka numerik dari frasa jumlah kemasan dalam field 8.
   - Contoh:
     dari "FIVE HUNDRED AND SIXTY (560) CTNS"
     ambil "560".

5. coo_package_unit:
   - Ekstrak unit kemasan dari frasa jumlah kemasan dalam field 8.
   - Contoh: "CTNS".

6. coo_gw & coo_quantity:
   - Untuk vendor ini, cek isi field "12. Quantity (Gross weight or other measurement)..."
   - Jika field 12 berisi quantity + unit, misalnya "3355SETS", maka:
     - coo_quantity = 3355
     - coo_gw = null
   - Hanya isi coo_gw jika ada nilai berat eksplisit dengan unit seperti KG/KGS.

7. coo_unit:
   - Ekstrak unit yang melekat pada field 12.
   - Jika field 12 berisi quantity, ambil unit quantity tersebut.
   - Contoh: "SETS".
   - Jika field 12 berisi berat, ambil unit beratnya, misalnya "KG".

8. coo_criteria:
   - Ekstrak dari field "10. Origin Conferring Criterion".
   - Jika ada tanda kutip, hilangkan tanda kutipnya.
   - Contoh: "RVC".

9. coo_customer_po_no:
   - Isi hanya jika ada nomor PO yang tertulis eksplisit.
   - Jika tidak ada referensi PO yang jelas, isi null.  
"""