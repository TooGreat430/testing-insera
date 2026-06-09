TOHO_PROMPT = """
INVOICE (INV)

Struktur umum invoice TOHO:
- Ada grouping "P/O No.C25-1544U/45323564" atau format serupa.
- Setelah itu muncul beberapa line item.
- Header utama line item:
  Seq. | Item No. | Description | Quantity | Unit Price | Amount
- Satu line item biasanya berbentuk:
  "1 CWSSXSAC400001 "SAMOX" CHAINWHEEL MODEL: 129 SET 9.05 1167.45"
  lalu di bawahnya ada lanjutan deskripsi model
  lalu line "** CODE:XXXXXXXXXXXX"
- Pada vendor TOHO, satu item juga bisa terpotong ke halaman berikutnya.
  Contoh: item seq 6 berlanjut ke page berikutnya dan BUKAN item baru.

1. inv_customer_po_no
   - Ambil dari "P/O No." terdekat yang menaungi line item tersebut.
   - Format P/O vendor TOHO biasanya seperti:
     - C25-1544U/45323564
     - C25-1619U/45324707
   - inv_customer_po_no yang diambil adalah angka customer PO setelah slash "/".
   - Contoh:
     - "P/O No.C25-1544U/45323564" -> inv_customer_po_no = "45323564"
     - "P/O No.C25-1619U/45324707" -> inv_customer_po_no = "45324707"
   - Jangan ambil prefix seperti "C25-1544U" atau "C25-1619U" sebagai customer PO number.
   - Jangan ambil invoice number, BL number, atau nomor lain.

2. inv_seq
   - Gunakan nilai pada kolom "Seq.".
   - Untuk vendor TOHO, seq sudah tercetak jelas pada dokumen, jadi pakai angka tersebut apa adanya.
   - Jika satu item terpotong ke halaman berikutnya tetapi seq-nya sama, tetap anggap itu item yang sama dan JANGAN dihitung ulang.
   - Contoh:
     - seq 6 di page 1 dan lanjutan seq 6 di page 2 tetap inv_seq = 6, bukan item baru.

3. inv_spart_item_no
   - Ambil item code / part code untuk item invoice.
   - Prioritas pencarian:
     1) nilai setelah label "** CODE:" atau "**CODE:"
     2) jika tidak ada, gunakan Item No.
   - Untuk vendor TOHO, CODE pada deskripsi memiliki prioritas lebih tinggi daripada Item No.
   - Contoh:
     - Item No: CWSSXAF38D0002-165
       Description berisi: ** CODE: CWSSXAF38D0002
       maka inv_spart_item_no = "CWSSXAF38D0002"
     - Item No: CWSSXSAC38J00002-152
       Description berisi: **CODE:CWSSXSAC38J00002
       maka inv_spart_item_no = "CWSSXSAC38J00002"
   - Jika Item No dan CODE sama, ambil value tersebut.
   - Jangan ambil qty, unit, seq, unit price, atau amount.

4. inv_description
   - Ambil deskripsi barang dari line item invoice.
   - Gabungkan seluruh baris deskripsi item sampai sebelum item berikutnya atau sebelum P/O berikutnya.
   - Pada vendor TOHO, description biasanya dimulai dari teks seperti:
     - "SAMOX CHAINWHEEL MODEL:"
     - "STEEL CHAINWHEEL & ALLOY CRANK"
     - "SAMOX CW MODEL:"
   - Masukkan detail spesifikasi barang yang memang bagian dari deskripsi, misalnya:
     - model
     - warna
     - ukuran crank
     - tooth
     - BB / CL information jika masih merupakan spesifikasi item
   - Jangan masukkan:
     - seq
     - Item No.
     - quantity
     - unit
     - unit price
     - amount
     - line "** CODE:..."
   - Jika description terpotong ke halaman berikutnya, gabungkan ke item yang sama.
   - Contoh hasil:
     - "SAMOX CHAINWHEEL MODEL: SAC40-018BNS42, BLACK, 170 MM 10/11SP, ALLOY BK 170MM, STEEL: BED 42T, OT, W/O CG W/O SPIDER, SQUARE, E/CAPLESS BOLT, W/O LOGO ** BB :68 MM CL : NORMAL NON BOOST"
     - "SAMOX CHAINWHEEL MODEL: AF38-D28NS-BG31, BLACK 1 SP, (3/32\" *28T* 165 MM), ALLOY CRANK, STEEL 28T BED, 49MM 0T, W/CG, W/O SPIDER, SQUARE, C/CAPLESS BOLT W/O LOGO, W/BCD76, ALLOY CG"

5. inv_gw
   - HANYA boleh diambil dari invoice.
   - Jika invoice tidak menyediakan gross weight per line item, isi "null".
   - Pada dokumen invoice TOHO yang tersedia, tidak ada gross weight per line item.
   - Karena itu, untuk vendor TOHO:
     inv_gw = "null"

6. inv_gw_unit
   - HANYA boleh diambil dari invoice.
   - Jika invoice tidak menyediakan gross weight per line item, isi "null".
   - Pada dokumen invoice TOHO yang tersedia, tidak ada gross weight per line item.
   - Karena itu, untuk vendor TOHO:
     inv_gw_unit = "null"

7. inv_quantity
   - Ambil nilai quantity line item pada invoice.
   - Ambil dari kolom Quantity pada baris item invoice.
   - Contoh:
     - "129 SET" -> inv_quantity = 129
     - "100 SET" -> inv_quantity = 100
     - "525 SET" -> inv_quantity = 525

8. inv_quantity_unit
   - Ambil unit quantity yang menempel pada Quantity di invoice.
   - Untuk vendor TOHO pada dokumen ini, unit yang muncul adalah "SET".
   - Contoh:
     - "129 SET" -> inv_quantity_unit = "SET"

9. inv_unit_price
   - Ambil dari kolom Unit Price line item invoice.
   - Nilai harus numeric saja.
   - Contoh:
     - "9.05" -> 9.05
     - "8.6" -> 8.6
     - "18.45" -> 18.45

10. inv_amount
   - Ambil dari kolom Amount line item invoice.
   - Nilai harus numeric saja.
   - Contoh:
     - "1167.45" -> 1167.45
     - "860" -> 860
     - "3003" -> 3003


PACKING LIST (PL)

Struktur umum packing list TOHO:
- Ada grouping "Customer P/O No.C25-1544U/45323564" atau format serupa.
- Header utama:
  Carton No. | Item No.(Cust_Item_No.)/Desc. | Quantity | N.W. | G.W. | Meas'mt
- Satu item biasanya berbentuk:
  "23~32 CWSSXTAC400001 @10 SET @13.20 @13.99 @1.90"
  lalu line total item:
  ""SAMOX" CHAINWHEEL MODEL: 100 SET 132 139.9 19"
  lalu di bawahnya ada deskripsi lanjutan
  lalu line "** CODE:XXXXXXXXXXXX"
- Pada vendor TOHO, satu logical item bisa dipecah ke lebih dari satu Carton No.
  Contoh:
    - 63~78 ... 160 SET
    - 79 ... 5 SET
    Keduanya masih item yang sama.
- Jadi untuk line item TOHO, fokus pada logical item, BUKAN hanya potongan visual per baris.

1. pl_customer_po_no
   - Ambil dari "Customer P/O No." terdekat yang menaungi line item tersebut.
   - Format P/O vendor TOHO biasanya seperti:
     - C25-1544U/45323564
     - C25-1619U/45324707
   - pl_customer_po_no yang diambil adalah angka customer PO setelah slash "/".
   - Contoh:
     - "Customer P/O No.C25-1544U/45323564" -> pl_customer_po_no = "45323564"
     - "Customer P/O No.C25-1619U/45324707" -> pl_customer_po_no = "45324707"

2. pl_item_no
   - Ambil part code / item code line item packing list.
   - Prioritas:
     1) nilai setelah "** CODE:" atau "**CODE:"
     2) jika tidak ada, gunakan Item No.(Cust_Item_No.)
   - Untuk vendor TOHO, CODE pada description memiliki prioritas lebih tinggi daripada Item No header.
   - Contoh:
     - Item No.(Cust_Item_No.): CWSSXAF38D0002-165
       Description berisi: ** CODE: CWSSXAF38D0002
       maka pl_item_no = "CWSSXAF38D0002"
     - Item No.(Cust_Item_No.): CWSSXSAC38J00002-152
       Description berisi: **CODE:CWSSXSAC38J00002
       maka pl_item_no = "CWSSXSAC38J00002"
   - Jangan ambil Carton No. sebagai pl_item_no.

3. pl_description
   - Ambil deskripsi barang dari packing list.
   - Gabungkan seluruh teks deskripsi logical item.
   - Jangan masukkan:
     - Carton No.
     - Item No.
     - line rasio per carton seperti "@10 SET @13.20 @13.99 @1.90"
     - angka total quantity/NW/GW/Meas'mt
     - line "** CODE:..."
   - Masukkan spesifikasi barang yang memang bagian dari description.
   - Jika satu item dipecah ke beberapa carton rows, gabungkan semuanya menjadi satu description item.
   - Contoh hasil:
     - "SAMOX CHAINWHEEL MODEL: TAC40-018T38NS, BLACK, 170 MM 10/11SP, ALLOY BK 170MM, STEEL: BED 38T, OT, W/O CG W/O SPIDER, 2-PIECE, W/BLACK BOLT, W/O LOGO, W/BB EB2401 ** BB: 68 MM, CL :NORMAL NON BOOST"
     - "STEEL CHAINWHEEL & ALLOY CRANK MODEL:SAC38J-166S-P37P SAND ANOD. BK;1SP,152MM,ALLOY,28T,STEEL,BK,44MM 0T,W/DOUBLE BK CG,W/O SPIDER,SQUARE,W/O BOLT,W/O LOGO (KONA) W/PLASTIC CAP"

4. pl_quantity
   - Ambil total quantity barang untuk logical item packing list.
   - Jangan salah ambil quantity per carton dari line "@10 SET".
   - Pada vendor TOHO:
     - "@10 SET" adalah quantity per carton
     - "100 SET" / "160 SET" / "5 SET" adalah quantity total per potongan row
   - Jika satu logical item dipecah ke beberapa carton rows, maka pl_quantity harus dijumlahkan.
   - Contoh:
     - 63~78 = 160 SET
       79 = 5 SET
       maka pl_quantity = 165
     - 80~91 = 120 SET
       92 = 9 SET
       maka pl_quantity = 129
     - 93~144 = 520 SET
       145 = 5 SET
       maka pl_quantity = 525

5. pl_package_unit
   - pl_package_unit hanya boleh diambil dari BUKTI package, bukan dari quantity unit.
   - Canonical value yang diperbolehkan hanya:
     ["CT", "PX", "BL", "PXCT", "null"]
   - Mapping canonical:
     - CTN / CTNS / CARTON / CARTONS / Carton No. -> CT
     - PLT / PALLET / PALLETS -> PX
     - BALE / BALES -> BL
     - Jika lebih dari 1 tipe package unit -> PXCT
   - Pada vendor TOHO, bukti package sangat jelas berasal dari:
     - header "Carton No."
     - total "163CTNS"
   - Maka untuk item packing list TOHO seperti dokumen ini:
     pl_package_unit = "CT"
   - Jangan ambil SET sebagai pl_package_unit.

6. pl_package_count
   - Hitung jumlah package fisik line item dari Carton No.
   - Untuk vendor TOHO, Carton No. bisa berupa:
     - range dengan "~"
     - single carton no
   - Aturan:
     - "23~32" -> 10
     - "33~42" -> 10
     - "63~78" -> 16
     - "79" -> 1
     - "80~91" -> 12
     - "92" -> 1
     - "93~144" -> 52
     - "145" -> 1
   - Jika satu logical item dipecah ke beberapa carton rows, jumlahkan semua package_count-nya.
   - Contoh:
     - 63~78 + 79 -> 16 + 1 = 17
     - 80~91 + 92 -> 12 + 1 = 13
     - 93~144 + 145 -> 52 + 1 = 53
   - Jangan ambil total dokumen "163CTNS" sebagai package_count item-level.

7. pl_nw
   - Ambil dari kolom N.W. (KGS) line item.
   - Nilai numeric saja.
   - Jika satu logical item dipecah ke beberapa carton rows, jumlahkan seluruh N.W.-nya.
   - Contoh:
     - 131.36 + 4.11 -> pl_nw = 135.47
     - 98.4 + 7.38 -> pl_nw = 105.78
     - 263.12 + 2.53 -> pl_nw = 265.65

8. pl_gw
   - Ambil dari kolom G.W. (KGS) line item.
   - Nilai numeric saja.
   - Jika satu logical item dipecah ke beberapa carton rows, jumlahkan seluruh G.W.-nya.
   - Contoh:
     - 137.12 + 4.46 -> pl_gw = 141.58
     - 103.56 + 7.81 -> pl_gw = 111.37
     - 285.48 + 2.96 -> pl_gw = 288.44

9. pl_volume
   - Ambil dari kolom Meas'mt (CU'FT) line item.
   - Nilai numeric saja.
   - Jika satu logical item dipecah ke beberapa carton rows, jumlahkan seluruh volume-nya.
   - Contoh:
     - 9.6 + 0.6 -> pl_volume = 10.2
     - 9.12 + 0.76 -> pl_volume = 9.88
     - 40.04 + 0.77 -> pl_volume = 40.81
   - Jangan salah ambil volume per carton dari line "@... @... @... @0.60" jika total line item sudah tersedia.


BILL OF LADING (BL)

Struktur umum BL TOHO:
- Pada deskripsi goods terdapat grouping umum:
  - BICYCLE PARTS
  - CHAINWHEEL AND CRANK
  - MODEL/TYPE, HS CODE: 8714.96
- Contoh:
  - CHAINWHEEL AND CRANK / SAC40-018BNS42, HS CODE: 8714.96
  - CHAINWHEEL AND CRANK / SAC40-018B38NS, HS CODE: 8714.96
  - CHAINWHEEL AND CRANK / TAC40-018T38NS, HS CODE: 8714.96
  - CHAINWHEEL AND CRANK / AF38-D28NS-BG31, HS CODE: 8714.96
  - CHAINWHEEL AND CRANK / SAC38J-166S-P37P, HS CODE: 8714.96
- Pada vendor TOHO, BL menuliskan model family, BUKAN item code lengkap seperti CWSSXSAC400001.

1. bl_description
   - Ambil hanya deskripsi barang pada BL.
   - Jika deskripsi terpecah menjadi dua line:
     - "CHAINWHEEL AND CRANK"
     - "SAC40-018BNS42, HS CODE: 8714.96"
     maka gabungkan menjadi:
       "CHAINWHEEL AND CRANK SAC40-018BNS42"
   - Ambil teks sebelum "HS CODE:".
   - Contoh:
     - "CHAINWHEEL AND CRANK SAC40-018BNS42"
     - "CHAINWHEEL AND CRANK TAC40-018T38NS"
     - "CHAINWHEEL AND CRANK AF38-D28NS-BG31"
   - Jangan ambil:
     - BICYCLE PARTS
     - container info
     - gross weight
     - package total
     - vessel
     - freight terms
     - marks seperti N/M

2. bl_hs_code
   - Ambil HS code yang menempel pada bl_description yang sama.
   - Ambil value setelah "HS CODE:".
   - Contoh:
     - "HS CODE: 8714.96" -> bl_hs_code = "8714.96"

Catatan tambahan BL:
- Pada vendor TOHO, BL memakai model family, bukan item code lengkap.
- Satu bl_description dapat merepresentasikan lebih dari satu invoice/pl item yang memiliki model sama tetapi item_no berbeda.
- Contoh:
   - SAC40-018BNS42 pada BL bisa cocok ke lebih dari satu item invoice/pl dengan perbedaan panjang crank.
   - SAC38J-166S-P37P pada BL bisa cocok ke lebih dari satu item code.
- Jadi jika melakukan matching, cocokkan berdasarkan model utama pada description, bukan berdasarkan item code CWSS... secara langsung.
- Jangan memaksa one-to-one mapping item code ke BL jika BL memang hanya merangkum per model family.


CERTIFICATE OF ORIGIN (COO)

Struktur umum COO TOHO:
- Dokumen berbentuk Form RCEP.
- Exporter / producer pada COO adalah CHUAN WEI METAL PRODUCTS (KUN SHAN) CO., LTD.
- Third-party invoicing dicentang, dengan remark third-party operator TO HO (HK) ENTERPRISES LIMITED.
- Kolom penting:
  6. Item number
  7. Marks and numbers on packages
  8. Number and kind of packages; and description of goods
  9. HS Code of the goods
  10. Origin Conferring Criterion
  11. RCEP Country of Origin
  12. Quantity / Gross weight / value and FOB where RVC is applied
  13. Invoice number(s) and date of invoice(s)

1. coo_seq
   - Ambil dari kolom "Item number".
   - Nilai numeric.
   - Untuk vendor TOHO pada dokumen ini, item number tercetak jelas seperti:
     - 1
     - 2
     - 3
     - ...
     - 9

2. coo_mark_number
   - Ambil dari kolom "Marks and numbers on packages" jika ada value item-level yang jelas.
   - Pada COO TOHO, mark yang muncul adalah "N/M" atau kosong.
   - "N/M" berarti no mark / generic shipment mark, BUKAN mark number item-level yang spesifik.
   - Karena itu, untuk vendor TOHO:
     - jika value = "N/M" -> coo_mark_number = "null"
     - jika kosong -> coo_mark_number = "null"

3. coo_description
   - Ambil deskripsi barang dari kolom 8 (description of goods).
   - Fokus pada goods description item-level.
   - Gabungkan seluruh line description item yang memang milik item tersebut.
   - Jangan masukkan:
     - item number
     - marks column
     - HS code
     - criteria
     - country of origin
     - quantity
     - gross weight
     - invoice no/date
     - line "** CODE:..."
   - Pada vendor TOHO, jika ada frasa package shipment-level di awal seperti:
     - "ONE HUNDRED AND SIXTY THREE (163) CARTONS OF"
     dan frasa itu tidak berulang konsisten sebagai package count per item,
     maka anggap itu sebagai shipment-level phrase dan JANGAN dijadikan bagian utama coo_description item.
   - Contoh hasil:
     - "SAMOX CHAINWHEEL AND CRANK MODEL TAC40-018T38NS, BLACK, 170 MM 10/11SP, ALLOY BK 170MM, STEEL: BED 38T, OT, W/O CG W/O SPIDER, 2-PIECE, W/BLACK BOLT, W/O LOGO, W/BB EB2401 ** BB: 68 MM, CL : NORMAL NON BOOST"
     - "SAMOX CHAINWHEEL AND CRANK MODEL SAC38J-166S-P37P SAND ANOD. BK;1SP,140MM,ALLOY,28T,STEEL,BK,44MM 0T,W/DOUBLE BK CG,W/O SPIDER,SQUARE,W/O BOLT,W/O LOGO W/PLASTIC CAP"

4. coo_hs_code
   - Ambil dari kolom 9 "HS Code of the goods".
   - Untuk vendor TOHO pada dokumen ini, HS code per item adalah:
     - "8714.96"

5. coo_quantity
   - Ambil quantity barang dari kolom 12.
   - Ambil angka sebelum unit.
   - Contoh:
     - "100SETS" -> 100
     - "165SETS" -> 165
     - "525SETS" -> 525

6. coo_unit
   - Ambil unit quantity yang menempel pada coo_quantity.
   - Contoh:
     - "100SETS" -> "SETS"
     - "129SETS" -> "SETS"

7. coo_package_count
   - Pada COO TOHO yang tersedia, tidak ada package_count item-level yang konsisten dan reliable untuk setiap row.
   - Ada frasa seperti "ONE HUNDRED AND SIXTY THREE (163) CARTONS", tetapi itu merupakan shipment-level total, bukan package_count yang jelas per item.
   - Karena itu, JANGAN gunakan angka 163 sebagai package_count untuk setiap item.
   - Jika tidak ada bukti package_count yang benar-benar item-level, isi null.
   - Untuk vendor TOHO pada dokumen ini:
     coo_package_count = null

8. coo_package_unit
   - Pada COO TOHO yang tersedia, package_unit item-level juga tidak tersedia secara jelas dan konsisten per row.
   - Jangan gunakan CARTONS dari shipment-level phrase sebagai package_unit semua item.
   - Jika tidak ada bukti package_unit yang benar-benar item-level, isi "null".
   - Untuk vendor TOHO pada dokumen ini:
     coo_package_unit = "null"

9. coo_gw
   - Ambil gross weight dari kolom 12.
   - Ambil angka sebelum "KGS G.W." atau "KG G.W.".
   - Contoh:
     - "139.9KGS G.W." -> 139.9
     - "127.9KGS G.W." -> 127.9
     - "288.44KGS G.W." -> 288.44
     - "81KGS G.W." -> 81

10. coo_amount
   - Ambil nilai amount / FOB / value HANYA jika benar-benar tercantum pada kolom 12.
   - Pada COO TOHO yang tersedia, kolom 12 hanya berisi quantity dan G.W., tidak ada FOB/value per item.
   - Karena itu:
     coo_amount = null
   - Jangan ambil amount dari invoice untuk mengisi coo_amount.

11. coo_criteria
   - Ambil dari kolom 10 "Origin Conferring Criterion".
   - Untuk vendor TOHO pada dokumen ini, value yang muncul adalah:
     - "PE"

12. coo_customer_po_no
   - Field ini hanya diisi jika ada customer PO number yang jelas pada COO.
   - Pada COO TOHO yang tersedia, yang muncul pada box 13 adalah invoice number/date, BUKAN customer PO number.
   - Jangan ambil invoice number seperti "C25-1544U" sebagai coo_customer_po_no.
   - Karena tidak ada customer PO number yang jelas pada COO vendor TOHO:
     coo_customer_po_no = "null"
"""