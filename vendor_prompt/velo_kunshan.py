VELO_KUNSHAN_PROMPT = """
INVOICE (INV)

Struktur umum invoice VELO KUNSHAN:
- Vendor: VELO CYCLE(KUNSHAN) CO., LTD.
- Ada grouping "P.O. NO:45322815" atau format serupa.
- Header utama line item:
  Item/Part no. | Description | Quantity | Unit Price | Amount
- Pada vendor ini, ada angka item number tercetak sebelum part number, misalnya:
  30
  SDLVL1A866000
  1
- Dalam kasus seperti itu, angka paling atas adalah nomor item, sedangkan part number harus digabung dari baris-baris code di bawahnya.
- Contoh:
  30
  SDLVL1A866000
  1
  maka:
  - inv_seq = 30
  - inv_spart_item_no = SDLVL1A8660001
- Contoh lain:
  HBGVL519AD200
  3
  maka inv_spart_item_no = HBGVL519AD2003
- Contoh lain:
  SDLVLVL514400
  001
  maka inv_spart_item_no = SDLVLVL514400001

1. inv_customer_po_no
   - Ambil dari "P.O. NO:" terdekat yang menaungi line item tersebut.
   - Satu P.O. NO berlaku untuk semua item di bawahnya sampai bertemu P.O. NO berikutnya.
   - Pada vendor VELO, customer PO number berupa angka 8 digit, misalnya:
     - 45322815
     - 45322816
     - 45323076
     - 45323434
   - Jangan ambil invoice number 80010947, BL number, Ref.#, atau nomor lain.

2. inv_seq
   - Gunakan nomor item yang tercetak pada dokumen invoice.
   - Pada vendor VELO, nomor item tidak selalu berurutan 1,2,3..., tetapi mengikuti nomor asli dokumen seperti:
     - 30
     - 40
     - 70
     - 71
     - 90
     - 132
   - Gunakan angka itu apa adanya sebagai inv_seq.
   - Jangan hitung ulang dari atas ke bawah.

3. inv_spart_item_no
   - Ambil dari kolom "Item/Part no."
   - Pada vendor VELO, part number adalah product code utama dan TIDAK memakai label CODE:.
   - Jika part number terpotong ke beberapa baris, gabungkan semua fragmen yang masih merupakan bagian dari code.
   - Contoh:
     - SDLVL1A866000 + 1 -> SDLVL1A8660001
     - SDLVLVL1C2800 + 2 -> SDLVLVL1C28002
     - HBGVL519AD200 + 3 -> HBGVL519AD2003
     - HBGVL31146003 + 5 -> HBGVL311460035
     - SDLVLVL614200 + 4 -> SDLVLVL6142004
   - Jangan masukkan inv_seq ke dalam part number.
   - Jangan ambil model description seperti VL-1A866 atau VLG-311D2 sebagai inv_spart_item_no jika item/part no sudah ada.

4. inv_description
   - Ambil deskripsi barang dari item invoice.
   - Deskripsi dimulai setelah item/part no dan berlanjut ke baris-baris spesifikasi di bawahnya.
   - Gabungkan seluruh baris deskripsi item sampai sebelum item berikutnya atau sebelum P.O. NO berikutnya.
   - Jangan masukkan:
     - inv_seq
     - item/part no
     - quantity
     - unit
     - unit price
     - amount
   - Pada vendor VELO, value seperti "2024" atau "2020" yang muncul di akhir blok deskripsi tetap dianggap bagian dari description jika memang berada di area deskripsi item.
   - Contoh hasil:
     - "SADDLE;VELO;VL-1A866;BLACK/BLACK;NP1 BLACK NYLON FIBER INJECTION BASE BLACK GUARD, W/O ELASTOMER CR-MO BLACK RAIL, W/O CLAMP 243*155MM,W/LOGO W/LINC AND FLUX2 LOGO 2024"
     - "HANDLE GRIP VELO VLG-311D2 L:130/130MM. CLOSE END AT RUBBER/GEL. ALL BLACK OEM PACKING 2020"

5. inv_gw
   - HANYA boleh diambil dari invoice.
   - Jika invoice tidak menyediakan gross weight per line item, isi "null".
   - Pada dokumen invoice VELO yang tersedia, tidak ada gross weight per line item.
   - Karena itu, untuk vendor VELO:
     inv_gw = "null"

6. inv_gw_unit
   - HANYA boleh diambil dari invoice.
   - Jika invoice tidak menyediakan gross weight per line item, isi "null".
   - Pada dokumen invoice VELO yang tersedia, tidak ada gross weight per line item.
   - Karena itu, untuk vendor VELO:
     inv_gw_unit = "null"

7. inv_quantity
   - Ambil dari kolom Quantity pada line item invoice.
   - Contoh:
     - 45 PCS -> inv_quantity = 45
     - 166 PRS -> inv_quantity = 166
     - 4,000 PRS -> inv_quantity = 4000

8. inv_quantity_unit
   - Ambil unit quantity yang menempel pada Quantity di invoice.
   - Pada vendor VELO, unit yang umum muncul:
     - PCS
     - PRS
   - Contoh:
     - 45 PCS -> inv_quantity_unit = "PCS"
     - 166 PRS -> inv_quantity_unit = "PRS"

9. inv_unit_price
   - Ambil dari kolom Unit Price.
   - Nilai harus numeric saja.
   - Hilangkan koma ribuan jika ada.
   - Contoh:
     - USD 5.2500 -> 5.25
     - USD 1.0500 -> 1.05
     - USD 0.9500 -> 0.95

10. inv_amount
   - Ambil dari kolom Amount.
   - Nilai harus numeric saja.
   - Hilangkan koma ribuan jika ada.
   - Contoh:
     - USD 236.25 -> 236.25
     - USD 3,800.00 -> 3800
     - USD 1,293.50 -> 1293.5


PACKING LIST (PL)

Struktur umum packing list VELO KUNSHAN:
- Header utama:
  C/NO. | DESCRIPTION | CTN | QUANTITY | N. WEIGHT | G. WEIGHT | MEASURE'T/CUFT
- Ada grouping "P.O. NO: 45322815" atau format serupa di dalam area description.
- Pada vendor VELO, satu item packing list sering ditulis dalam format:
  part_number
  description
  lalu kolom kanan:
  CTN = 2 @
  QUANTITY = 20 PCS @
  N. WEIGHT = 6.200 @
  G. WEIGHT = 7 @
  MEASURE'T = 1.350
  dan di bawahnya ada total line:
  40 / 12.4 / 14 / 2.7
- Artinya:
  - CTN = jumlah carton/package
  - 20 PCS = quantity per carton
  - 6.200 = net weight per carton
  - 7 = gross weight per carton
  - 1.350 = volume per carton
  - Baris bawah adalah total untuk item tersebut

- Pada vendor VELO, satu logical item juga bisa dipecah ke beberapa baris packing karena carton terakhir berisi remainder quantity.
  Contoh:
    - 37 carton @ 20 PCS = 740
    - 1 carton @ 10 PCS = 10
    total logical item = 750
- Karena itu, jika item yang sama berlanjut ke baris berikutnya dalam konteks item yang sama, jumlahkan nilai totalnya.

1. pl_customer_po_no
   - Ambil dari "P.O. NO:" terdekat yang menaungi line item tersebut.
   - Satu P.O. NO berlaku untuk semua item di bawahnya sampai bertemu P.O. NO berikutnya.
   - Yang diambil hanya angka customer PO-nya.
   - Contoh:
     - P.O. NO: 45322815 -> pl_customer_po_no = "45322815"

2. pl_item_no
   - Ambil dari part number pada awal blok item packing list.
   - Pada vendor VELO, pl_item_no berasal dari product code utama, bukan dari model description.
   - Jika part number terpotong ke beberapa baris, gabungkan semua fragmennya.
   - Contoh:
     - SDLVL1A866000 + 1 -> SDLVL1A8660001
     - SDLVLVL1C2800 + 2 -> SDLVLVL1C28002
     - HBGVL519AD200 + 3 -> HBGVL519AD2003
     - HBGVL31146003 + 5 -> HBGVL311460035
   - Jangan ambil C/NO. sebagai pl_item_no.
   - Jangan ambil model description seperti VL-1A866 atau VLG-311D2 sebagai pl_item_no jika part number sudah ada.

3. pl_description
   - Ambil deskripsi barang dari packing list.
   - Gabungkan seluruh teks description item.
   - Jangan masukkan:
     - C/NO.
     - P.O. NO.
     - part number / pl_item_no
     - angka di kolom CTN / QUANTITY / N.WEIGHT / G.WEIGHT / MEASURE'T
     - simbol "@" pada kolom kanan
   - Pada vendor VELO, description biasanya berupa blok teks seperti:
     - "SADDLE;VELO;VL-4252;BLACK/GREY;Z20191 ..."
     - "HANDLE GRIP;VELO;VLG-1777D2;BLACK;KRATON ..."
   - Value seperti "2020" atau "2024" tetap dianggap bagian description jika memang berada di blok deskripsi item.

4. pl_quantity
   - Ambil total quantity barang untuk line item packing list.
   - Prioritas:
     1) gunakan total quantity pada baris bawah item jika tersedia
     2) jika tidak ada, hitung dari quantity per carton × CTN
   - Contoh:
     - CTN 2 @, QUANTITY 20 PCS @, total bawah 40 -> pl_quantity = 40
     - CTN 37 @, QUANTITY 20 PCS @, total bawah 740 -> pl_quantity = 740
   - Jika satu logical item dipecah ke beberapa baris, jumlahkan seluruh total quantity-nya.
   - Contoh:
     - 740 + 10 = 750
     - 320 + 5 = 325
     - 160 + 6 = 166
     - 480 + 8 = 488

5. pl_package_unit
   - pl_package_unit hanya boleh diambil dari bukti package, bukan dari quantity unit.
   - Canonical value yang diperbolehkan hanya:
     ["CT", "PX", "BL", "PXCT", "null"]
   - Pada vendor VELO, bukti package sangat jelas berasal dari:
     - kolom "CTN"
     - total dokumen "496 CTNS"
     - B/L "496 CARTON(s)"
   - Maka untuk vendor VELO:
     pl_package_unit = "CT"
   - Jangan ambil PCS atau PRS sebagai pl_package_unit.

6. pl_package_count
   - Ambil dari kolom CTN.
   - Pada vendor VELO, CTN adalah jumlah carton/package untuk item tersebut.
   - Prioritas:
     1) gunakan angka CTN sebelum simbol "@"
     2) C/NO. hanya digunakan sebagai validasi tambahan, bukan sumber utama jika CTN sudah jelas
   - Contoh:
     - 2 @ -> pl_package_count = 2
     - 37 @ -> pl_package_count = 37
     - 1 @ -> pl_package_count = 1
   - Jika satu logical item dipecah ke beberapa baris, jumlahkan seluruh CTN.
   - Contoh:
     - 37 + 1 = 38
     - 16 + 1 = 17
     - 6 + 1 = 7

7. pl_nw
   - Ambil total net weight line item.
   - Prioritas:
     1) gunakan total N. WEIGHT pada baris bawah item
     2) jika tidak ada, hitung dari net weight per carton × CTN
   - Contoh:
     - 6.200 @ dan total bawah 12.4 -> pl_nw = 12.4
     - 10.500 @ dan total bawah 63 -> pl_nw = 63
   - Jika satu logical item dipecah ke beberapa baris, jumlahkan seluruh total N.W.
   - Contoh:
     - 233.1 + 3.15 = 236.25
     - 21 + 0.79 = 21.79

8. pl_gw
   - Ambil total gross weight line item.
   - Prioritas:
     1) gunakan total G. WEIGHT pada baris bawah item
     2) jika tidak ada, hitung dari gross weight per carton × CTN
   - Contoh:
     - 7 @ dan total bawah 14 -> pl_gw = 14
     - 11.500 @ dan total bawah 69 -> pl_gw = 69
   - Jika satu logical item dipecah ke beberapa baris, jumlahkan seluruh total G.W.
   - Contoh:
     - 273.8 + 3.7 = 277.5
     - 23 + 0.86 = 23.86

9. pl_volume
   - Ambil total volume line item dari kolom MEASURE'T/CUFT.
   - Prioritas:
     1) gunakan total volume pada baris bawah item
     2) jika tidak ada, hitung dari volume per carton × CTN
   - Contoh:
     - 1.350 dan total bawah 2.7 -> pl_volume = 2.7
     - 1.650 dan total bawah 61.05 -> pl_volume = 61.05
   - Jika satu logical item dipecah ke beberapa baris, jumlahkan seluruh total volume.
   - Contoh:
     - 61.05 + 0.83 = 61.88
     - 3.1 + 0.12 = 3.22

Catatan tambahan penting untuk PL vendor VELO:
- Pada vendor VELO, C/NO. memiliki format seperti:
  - 1/2~2/2
  - 4/40~40/40
  - 1/80~80/80
  - 145/172~172/172
- C/NO. membantu menunjukkan rentang carton, tetapi package_count utama tetap diambil dari kolom CTN.
- Jika item yang sama muncul berurutan dengan item_no dan description yang sama, dan hanya berbeda karena remainder carton, gabungkan nilainya menjadi satu logical line item.


BILL OF LADING (BL)

Struktur umum BL VELO KUNSHAN:
- BL hanya merangkum beberapa family model, bukan seluruh detail item invoice.
- Contoh value pada BL:
  - SADDLE VL1C28, HS CODE : 8714.95
  - SADDLE VL-4252, HS CODE : 8714.95
  - SADDLE VL-3530, HS CODE : 8714.95
  - HANDLE GRIP VLG-311D2, HS CODE : 8714.99
  - HANDLE GRIP VLG-519AD2, HS CODE : 8714.99

1. bl_description
   - Ambil hanya deskripsi barang pada BL.
   - Ambil teks sebelum "HS CODE".
   - Bersihkan spasi berlebih.
   - Contoh:
     - "SADDLE VL1C28"
     - "SADDLE VL-4252"
     - "SADDLE VL-3530"
     - "HANDLE GRIP VLG-311D2"
     - "HANDLE GRIP VLG-519AD2"
   - Jangan ambil:
     - BICYCLE PARTS
     - PT. IS
     - PO NO.
     - C/NO.
     - MADE IN CHINA
     - container info
     - package total
     - weight / volume
     - vessel / freight terms

2. bl_hs_code
   - Ambil HS code yang menempel pada bl_description yang sama.
   - Normalisasi spasi jika dokumen menulis "8714. 95" menjadi "8714.95"
   - Contoh:
     - "SADDLE VL1C28, HS CODE : 8714.95" -> bl_hs_code = "8714.95"
     - "HANDLE GRIP VLG-311D2, HS CODE : 8714.99" -> bl_hs_code = "8714.99"

Catatan tambahan BL vendor VELO:
- BL hanya memuat sebagian family model.
- Jika inv/pl item tidak muncul pada BL, maka:
  - bl_description = "null"
  - bl_hs_code = "null"
- Contoh item invoice/pl yang tidak terlihat pada BL:
  - VL-1A866
  - VL-1C50
  - VL-5144
  - VLG-1777D2
  - VL-6142
  - VL-5088
  Maka untuk item-item itu, bl_description dan bl_hs_code diisi null.
- Jangan memaksa matching berdasarkan kemiripan lemah.
- Matching BL harus berdasarkan family model yang benar-benar tertulis pada BL.


CERTIFICATE OF ORIGIN (COO)

Struktur umum COO VELO KUNSHAN:
- Dokumen berbentuk Form RCEP.
- Terdapat item number per row.
- Untuk setiap item biasanya ada pola:
  - frasa package:
    "THREE (3) CARTONS OF"
    "THIRTY EIGHT (38) CARTONS OF"
  - deskripsi barang:
    "SADDLE;VELO;VL-1A866;BLACK/BLACK"
    "HANDLE GRIP;VELO;VLG-1777D2;BLACK"
  - HS code:
    8714.95 atau 8714.99
  - criteria:
    "PE"
  - country:
    CHINA
  - quantity:
    45PIECES / 166PAIRS / 600PAIRS / dst
  - invoice number and date:
    80010947 / DEC. 29,2025

1. coo_seq
   - Ambil dari item number yang tercetak pada COO.
   - Gunakan angka itu apa adanya.
   - Contoh:
     - 1
     - 2
     - 20
     - 42

2. coo_mark_number
   - Ambil dari kolom "Marks and numbers on packages" jika ada value item-level yang jelas.
   - Pada COO vendor VELO, mark yang terlihat bersifat shipment-level/generic seperti:
     - PT.IS
     - PO NO.
     - C/NO.
     - MADE IN CHINA
   - Mark tersebut bukan mark number item-level yang spesifik.
   - Karena itu, untuk vendor VELO:
     coo_mark_number = "null"

3. coo_description
   - Ambil deskripsi barang item-level dari COO.
   - Fokus pada goods description.
   - Gabungkan baris yang terpotong menjadi satu string utuh.
   - Jangan masukkan:
     - frasa package seperti "THREE (3) CARTONS OF"
     - coo_seq
     - hs code
     - criteria
     - country
     - quantity
     - invoice number / date
   - Contoh hasil:
     - "SADDLE;VELO;VL-1A866;BLACK/BLACK"
     - "SADDLE;VELO;VL1C28;BLACK/BLACK"
     - "HANDLE GRIP;VELO;VLG-1777D2;BLACK"
     - "HANDLE GRIP;VELO;VLG-311-4/6;BLACK"

4. coo_hs_code
   - Ambil dari kolom HS Code of the goods.
   - Normalisasi spasi jika ada.
   - Contoh:
     - 8714.95
     - 8714.99

5. coo_quantity
   - Ambil angka quantity barang dari COO.
   - Ambil angka sebelum unit.
   - Contoh:
     - 45PIECES -> 45
     - 166PAIRS -> 166
     - 4000PAIRS -> 4000

6. coo_unit
   - Ambil unit yang menempel pada coo_quantity.
   - Pada vendor VELO, unit yang muncul:
     - PIECES
     - PAIRS
   - Contoh:
     - 45PIECES -> "PIECES"
     - 166PAIRS -> "PAIRS"

7. coo_package_count
   - Ambil dari frasa package pada description item COO.
   - Prioritaskan angka dalam tanda kurung.
   - Contoh:
     - "THREE (3) CARTONS OF" -> coo_package_count = 3
     - "THIRTY EIGHT (38) CARTONS OF" -> coo_package_count = 38
     - "ONE (1) CARTONS OF" -> coo_package_count = 1
     - "SIXTY (60) CARTONS OF" -> coo_package_count = 60

8. coo_package_unit
   - Ambil package unit yang menempel pada coo_package_count.
   - Pada vendor VELO, yang tertulis adalah CARTONS.
   - Contoh:
     - "THREE (3) CARTONS OF" -> coo_package_unit = "CARTONS"
     - "ONE (1) CARTONS OF" -> coo_package_unit = "CARTONS"
   - Ambil sesuai yang tertulis pada COO.
   - Jangan ambil PIECES atau PAIRS karena itu quantity unit.

9. coo_gw
   - Ambil gross weight item-level hanya jika benar-benar terlihat jelas pada COO.
   - Pada dokumen COO VELO yang tersedia, quantity item-level terlihat jelas, tetapi gross weight item-level tidak terlihat jelas per row.
   - Karena itu, untuk vendor VELO pada dokumen ini:
     coo_gw = null
   - Jangan ambil gross weight dari BL atau packing list untuk mengisi coo_gw.

10. coo_amount
   - Ambil value / FOB / amount hanya jika benar-benar tercantum pada COO.
   - Pada dokumen COO VELO yang tersedia, tidak ada amount/FOB item-level yang terlihat jelas.
   - Karena itu:
     coo_amount = null
   - Jangan ambil amount dari invoice untuk mengisi coo_amount.

11. coo_criteria
   - Ambil dari kolom Origin Conferring Criterion.
   - Pada vendor VELO, value yang terlihat adalah:
     - "PE"

12. coo_customer_po_no
   - Field ini hanya diisi jika ada customer PO number yang jelas pada dokumen COO vendor Shimano.
   - Dokumen ini berasal dari vendor VELO CYCLE(KUNSHAN) CO., LTD., bukan Shimano.
   - Karena itu, untuk vendor VELO:
     coo_customer_po_no = "null"


ATURAN VALIDASI TAMBAHAN

1. quantity vs package_count
   - quantity = jumlah barang
   - package_count = jumlah carton/package fisik
   - kedua field ini berbeda dan tidak boleh saling menggantikan

2. Jangan tertukar antara:
   - item number / seq dengan part number
   - item code dengan model description
   - quantity total dengan quantity per carton
   - package unit dengan quantity unit

3. Untuk vendor VELO pada invoice dan packing list:
   - product code utama sering terpotong ke beberapa baris
   - gabungkan fragmen code yang masih berada di area item/part number
   - contoh:
     SDLVL1A866000 + 1 -> SDLVL1A8660001
   - tetapi JANGAN gabungkan inv_seq ke item code

4. Untuk vendor VELO pada packing list:
   - kolom CTN = package_count
   - kolom QUANTITY menampilkan quantity per carton dan total quantity
   - kolom N.WEIGHT / G.WEIGHT / MEASURE'T juga menampilkan nilai per carton dan total
   - jika total line tidak terbaca, hitung:
     total = nilai_per_carton × CTN

5. Untuk vendor VELO pada BL:
   - BL hanya merangkum family model tertentu
   - jika model family tidak tertulis di BL, maka bl_description dan bl_hs_code harus null

6. Untuk vendor VELO pada COO:
   - package_count dan package_unit diambil dari frasa karton item-level
   - quantity diambil dari value seperti 45PIECES / 166PAIRS
   - gross weight dan amount jangan ditebak jika tidak terlihat jelas

7. Output akhir harus bersih:
   - numeric tanpa koma ribuan
   - hs code tanpa spasi berlebih
   - string tanpa label tambahan yang tidak perlu
   - tanpa TOTAL/SAY TOTAL/SUMMARY
"""