HAOMENG_PROMPT = """
INVOICE (INV)

Struktur umum invoice HAOMENG:
- Ada grouping "P/O NO: xxxxxxxx"
- Setelah itu muncul beberapa line item
- Header utama line item umumnya:
  Item & Model No | Description | Qty | Unit Price | Amount
- Satu line item biasanya berbentuk:
  "ChainWheel set CODE:XXXXXXXXXXXX 30.00 SET 11.8000 354.00"
  lalu di bawahnya ada deskripsi model
  lalu "REMARK: ..."

1. inv_customer_po_no
   - Ambil dari "P/O NO:" terdekat yang menaungi line item tersebut.
   - Satu P/O NO berlaku untuk semua item di bawahnya sampai bertemu P/O NO berikutnya.
   - Format customer_po_no:
     - numerik saja
     - 8 digit
     - diawali angka 4
   - Contoh valid:
     - 45321768
     - 45321753
     - 45324085
   - Jangan ambil invoice number, PL number, BL number, atau nomor lain.

2. inv_spart_item_no
   - Ambil item code / part code untuk item invoice.
   - Prioritas pencarian:
     1) nilai setelah label "CODE:"
     2) jika tidak ada, cari part code paling jelas pada baris item / deskripsi
   - Untuk vendor HAOMENG, part code biasanya berada pada baris item pertama setelah "CODE:".
   - Contoh:
     - "ChainWheel set CODE:CWSPW244AF0007 ..."
       maka inv_spart_item_no = "CWSPW244AF0007"
   - Jangan ambil model deskripsi seperti "SOLID-244A-F..." sebagai item code.
   - Jangan ambil qty, unit, atau row range.

3. inv_description
   - Ambil deskripsi barang dari line item invoice.
   - Utamakan deskripsi model/barang yang berada di bawah baris pertama item.
   - Gabungkan seluruh baris deskripsi item sampai sebelum "REMARK:".
   - Jangan masukkan:
     - "ChainWheel set"
     - "CODE:..."
     - qty
     - unit
     - unit price
     - amount
     - remark
   - Contoh hasil:
     - "SOLID-244A-F,3/32*44T*170mm(JIS),CR S.A.SIL,CK S.PTD.SIL,CG AL SIL(AG37)"
     - "RMZ-MD25S-TT,32T*170MM,STEEL CHAINRING BLACK, ALLOY CRANK SAND BLACK ANO., W/LOGO, W/BSA BB, ONE-PIECE THRU AXLE CRANKSET"

4. inv_gw
   - HANYA boleh diambil dari invoice.
   - Jika invoice tidak menyediakan gross weight per line item, isi "null".
   - Jangan ambil dari packing list atau COO untuk mengisi inv_gw.

5. inv_gw_unit
   - HANYA boleh diambil dari invoice.
   - Jika invoice tidak menyediakan gross weight per line item, isi "null".
   - Jika ada gross weight dan unitnya tercantum, ambil unitnya seperti "KG" / "KGS".

6. inv_quantity
   - Ambil nilai quantity line item pada invoice.
   - Ambil dari kolom Qty pada baris item invoice.
   - Contoh:
     - "30.00 SET" -> inv_quantity = 30
     - "398.00 PCS" -> inv_quantity = 398

7. inv_quantity_unit
   - Ambil unit quantity yang menempel pada Qty di invoice.
   - Contoh:
     - "30.00 SET" -> inv_quantity_unit = "SET"
     - "398.00 PCS" -> inv_quantity_unit = "PCS"

8. inv_unit_price
   - Ambil dari kolom Unit Price line item invoice.
   - Nilai harus numeric saja.
   - Contoh:
     - "11.8000" -> 11.8
     - "3.2500" -> 3.25

9. inv_amount
   - Ambil dari kolom Amount line item invoice.
   - Nilai harus numeric saja.
   - Contoh:
     - "354.00" -> 354
     - "1,293.50" -> 1293.5

PACKING LIST (PL)

Struktur umum packing list HAOMENG:
- Ada grouping "P/O NO: xxxxxxxx"
- Header utama:
  Mark & Nos | Description | Qty | N.W (KGS) | G.W (KGS) | Volume (CUFT)
- Satu item biasanya berbentuk:
  "1-3 Chainwheel set CODE:CWSPW244AF0007"
  "@10SET @7.70 @8.62 @1.02"
  "SOLID-244A-F,3/32*44T*170mm(JIS)..."
  "30SET 23.10 25.86 3.06"
  "REMARK:..."
- Mark & Nos pada vendor ini umumnya berupa rentang nomor karton, misalnya 1-3, 31-54, 147-396.

1. pl_customer_po_no
   - Ambil dari "P/O NO:" terdekat yang menaungi line item tersebut.
   - Satu P/O NO berlaku untuk item-item di bawahnya sampai P/O NO berikutnya.

2. pl_item_no
   - Ambil part code / item code line item packing list.
   - Prioritas:
     1) nilai setelah "CODE:"
     2) jika tidak ada, cari product code paling jelas pada baris item / deskripsi
   - Contoh:
     - "Chainwheel set CODE:CWSPW244AF0007" -> pl_item_no = "CWSPW244AF0007"
   - Jangan ambil range karton seperti 1-3.
   - Jangan ambil model deskripsi seperti SOLID-244A-F sebagai item_no bila CODE ada.

3. pl_description
   - Ambil deskripsi barang dari packing list.
   - Gabungkan teks deskripsi item.
   - Jangan masukkan:
     - range Mark & Nos (mis. 1-3, 31-54)
     - "Chainwheel set"
     - "CODE:..."
     - baris rasio per karton seperti "@10SET @7.70 @8.62 @1.02"
     - baris total angka "30SET 23.10 25.86 3.06"
     - REMARK
   - Contoh hasil:
     - "SOLID-244A-F,3/32*44T*170mm(JIS),CR S.A.SIL,CK S.PTD.SIL,CG AL SIL(AG37)"
     - "PRO-R42,1/8*42T*170mm,CR ST BK,CK S.P.BK(A00C)"

4. pl_quantity
   - Ambil total quantity barang untuk line item packing list.
   - Pada vendor HAOMENG, gunakan nilai total di kolom Qty, misalnya:
     - "30SET" -> pl_quantity = 30
     - "333SET" -> pl_quantity = 333
     - "398PCS" -> pl_quantity = 398
   - JANGAN salah ambil nilai "@10SET" karena itu quantity per package, bukan total quantity.
   - Jika hanya tersedia quantity-per-package dan package_count, maka:
     pl_quantity = quantity_per_package × pl_package_count

5. pl_package_unit
   - pl_package_unit hanya boleh diambil dari BUKTI package, bukan dari quantity unit.
   - lokasi pl_package_unit biasanya ada di akhir ketika package di total contoh: TOTAL= 1,985.00 cartons. Maka pl_package_unit yaitu "CT"
   - Canonical value yang diperbolehkan hanya:
     ["CT", "PX", "BL", "PXCT", "null"]
   - Mapping canonical:
     - CTN / CARTON / CARTONS -> CT
     - PLT / PALLET / PALLETS -> PX
     - BALE / BALES -> BL
     - Jika lebih dari 1 tipe package unit -> PXCT
   - Khusus vendor HAOMENG:
     - Mark & Nos berupa rentang nomor karton (contoh 1-3, 31-54, 147-396)
     - Ada total summary "1,985.00 cartons"
     - Ada referensi "C/NO.:A" yang menunjukkan carton numbering
     Maka pl_package_unit untuk line item seperti ini = "CT"
   - Jangan ambil SET / PCS sebagai pl_package_unit.
   - Jika tidak ada bukti package unit, isi "null".

6. pl_package_count
   - Hitung jumlah package fisik line item.
   - Untuk vendor HAOMENG, sumber utama adalah rentang pada kolom Mark & Nos.
   - Aturan:
     - "1-3" -> 3
     - "31-54" -> 24
     - "147-396" -> 250
     - "149-149" -> 1
   - Rumus rentang inklusif:
     akhir - awal + 1
   - Jika ada lebih dari satu range untuk satu item yang sama, jumlahkan semuanya.
   - Jangan ambil dari total summary seluruh dokumen.

7. pl_nw
   - Ambil dari kolom N.W (KGS) line item.
   - Nilai numeric saja.
   - Contoh:
     - "23.10" -> 23.1
     - "191.88" -> 191.88

8. pl_gw
   - Ambil dari kolom G.W (KGS) line item.
   - Nilai numeric saja.
   - Contoh:
     - "25.86" -> 25.86
     - "212.79" -> 212.79

9. pl_volume
   - Ambil dari kolom Volume (CUFT) line item.
   - Nilai numeric saja.
   - Contoh:
     - "3.06" -> 3.06
     - "25.50" -> 25.5
   - Jika yang tersedia adalah volume per package, maka:
     pl_volume = volume_per_package × pl_package_count
   - Untuk vendor HAOMENG, baris "@... @... @... @1.02" adalah rasio per package.
     Jangan utamakan itu jika sudah ada total volume line item di kolom terakhir.
     Prioritas utama tetap total volume line item.

BILL OF LADING (BL)

Struktur umum BL HAOMENG:
- Pada deskripsi goods terdapat beberapa line deskripsi barang
- Masing-masing diikuti "HS NUMBER: xxxxx.xx"
- Contoh:
  - CHAINWHEEL AND CRANK TA-CQ68 HS NUMBER: 8714.96
  - CHAINWHEEL AND CRANK TB-CY01 HS NUMBER: 8714.96
  - CHAINWHEEL AND CRANK TN-CY10 HS NUMBER: 8714.96
  - CHAINWHEEL AND CRANK PRO-A38 HS NUMBER: 8714.96
  - CHAINWHEEL AND CRANK TY-CQ01 HS NUMBER: 8714.96

1. bl_description
   - Ambil hanya deskripsi barang pada BL.
   - Ambil teks sebelum "HS NUMBER:".
   - Contoh:
     - "CHAINWHEEL AND CRANK TA-CQ68"
     - "CHAINWHEEL AND CRANK TB-CY01"
   - Jangan menambah detail dari invoice / packing list.
   - Jangan ambil container info, vessel, freight terms, package total, atau mark shipment.

2. bl_hs_code
   - Ambil HS code yang menempel pada bl_description yang sama.
   - Ambil value setelah "HS NUMBER:".
   - Contoh:
     - "HS NUMBER: 8714.96" -> bl_hs_code = "8714.96"
   - Hanya boleh mengambil dari BL.

Catatan tambahan BL:
- Jika proses Anda membutuhkan mapping ke invoice/PL item, maka lakukan matching hanya berdasarkan model utama yang benar-benar muncul di BL.
- Jika model invoice/PL tidak muncul di BL, maka bl_description = "null" dan bl_hs_code = "null" untuk item tersebut.
- Jangan memaksa matching berdasarkan kemiripan parsial yang lemah.

CERTIFICATE OF ORIGIN (COO)

Struktur umum COO HAOMENG:
- Dokumen berbentuk Form RCEP
- Kolom penting:
  6. Item number
  7. Marks and numbers on packages
  8. Number and kind of packages; and description of goods
  9. HS Code of the goods
  10. Origin Conferring Criterion
  11. RCEP Country of Origin
  12. Quantity / Gross weight / value and FOB where RVC is applied
  13. Invoice number(s) and date of invoice(s)

Setiap line COO biasanya berisi:
- item number
- frasa package seperti:
  "THREE (3) CARTONS OF BICYCLE PARTS"
- quantity seperti:
  "30SETS"
- deskripsi goods seperti:
  "CHAINWHEEL AND CRANK"
  "SOLID-244A-F,3/32*44T*170MM"
- HS code seperti:
  "8714.96"
- criteria seperti:
  "PE"
- quantity/gw seperti:
  "30SETS"
  "25.86KG G.W."
- invoice no/date:
  "SHXM22-2512000393"
  "DEC. 31, 2025"

1. coo_mark_number
   - Ambil dari kolom "Marks and numbers on packages" jika ada value item-level yang jelas.
   - Jika kolom marks kosong untuk line item, isi "null".
   - Jika hanya ada shipment marks umum di luar line item seperti:
     - PT.IS
     - PO#
     - P/I NO.
     - C/NO.:A
     - MADE IN CHINA
     dan tidak jelas terikat ke satu item tertentu,
     maka JANGAN pakai untuk coo_mark_number item-level.
   - Dalam kondisi seperti itu, isi "null".

2. coo_description
   - Ambil deskripsi barang dari kolom 8 (description of goods).
   - Fokus pada goods description.
   - Hilangkan bagian package phrase di atasnya jika package_count dan package_unit sudah bisa dipisahkan.
   - Jangan masukkan:
     - item number
     - HS code
     - criteria
     - country of origin
     - quantity
     - GW
     - invoice no/date
   - Contoh hasil:
     - "CHAINWHEEL AND CRANK SOLID-244A-F,3/32*44T*170MM"
     - "CHAINWHEEL AND CRANK PRO-R42,1/8*42T*170MM"
   - Jika deskripsi terpotong ke banyak baris, gabungkan menjadi satu string.

3. coo_hs_code
   - Ambil dari kolom 9 "HS Code of the goods".
   - Contoh:
     - "8714.96"

4. coo_quantity
   - Ambil quantity barang dari kolom 12.
   - Ambil angka sebelum unit.
   - Contoh:
     - "30SETS" -> 30
     - "398SETS" -> 398

5. coo_unit
   - Ambil unit quantity yang menempel pada coo_quantity.
   - Contoh:
     - "30SETS" -> "SETS"
     - "398PCS" -> "PCS" jika ada

6. coo_package_count
   - Sumber utama: frasa package pada kolom 8.
   - Contoh:
     - "THREE (3) CARTONS OF BICYCLE PARTS" -> coo_package_count = 3
     - "THIRTY (30) CARTONS OF BICYCLE PARTS" -> 30
     - "ONE HUNDRED AND THIRTY FIVE (135) CARTONS OF BICYCLE PARTS" -> 135
   - Prioritaskan angka dalam tanda kurung jika ada.
   - Jika tidak ada frasa package di description, baru cari fallback value package di bawah area quantity/GW.
   - Jangan tertukar dengan coo_quantity.

7. coo_package_unit
   - Ambil package unit yang menempel pada coo_package_count dari frasa package di kolom 8.
   - Contoh:
     - "THREE (3) CARTONS OF BICYCLE PARTS" -> coo_package_unit = "CARTONS"
     - "ONE (1) CARTON OF ..." -> coo_package_unit = "CARTON"
   - Ambil sesuai yang tertulis pada COO.
   - Jangan ambil SETS / PCS karena itu quantity unit, bukan package unit.

8. coo_gw
   - Ambil gross weight dari kolom 12.
   - Ambil angka sebelum "KG G.W." atau "KGS G.W.".
   - Contoh:
     - "25.86KG G.W." -> 25.86
     - "240KG G.W." -> 240
     - "446.25KG G.W." -> 446.25

9. coo_amount
   - Ambil nilai amount / FOB / value HANYA jika benar-benar tercantum pada kolom 12.
   - Jika kolom 12 hanya berisi quantity dan G.W. tanpa value/FOB, maka coo_amount = null.
   - Jangan ambil amount dari invoice untuk mengisi coo_amount.
   - Jangan menebak.

10. coo_criteria
   - Ambil dari kolom 10 "Origin Conferring Criterion".
   - Contoh:
     - "PE"

11. coo_customer_po_no
   - Field ini hanya diisi jika dokumen berasal dari vendor Shimano dan ada Customer PO Number yang jelas.
   - Vendor pada dokumen ini adalah HAOMENG BICYCLE (SHANGHAI) CO., LTD, BUKAN Shimano.
   - Karena itu, untuk vendor HAOMENG:
     coo_customer_po_no = "null"
"""