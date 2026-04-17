HL_SHENZHEN_PROMPT = """
INVOICE (INV)

Aturan umum ekstraksi vendor HL SHENZHEN:
- Vendor pada sampel adalah HL CORP ( SHEN ZHEN ) / HL CORP(SHEN ZHEN).
- Dokumen invoice berjudul "COMMERCIAL INVOICE".
- Dokumen packing list berjudul "PACKING LIST".
- Dokumen BL berjudul "BILL OF LADING".
- Dokumen COO berjudul "CERTIFICATE OF ORIGIN" / Form RCEP.
- Jika field bertipe string dan tidak ada bukti yang jelas, isi "null".
- Jika field bertipe number dan tidak ada bukti yang jelas, isi null.
- Jangan mengisi field dari dokumen lain jika field tersebut harus berasal dari dokumen spesifik.
- Gabungkan teks yang terpotong baris / line wrap menjadi satu value yang utuh.
- Jika item terpotong ke halaman berikutnya, tetap anggap sebagai item yang sama, bukan item baru.
- Jangan halusinasi nilai yang tidak tercetak jelas pada dokumen.

Struktur umum invoice HL SHENZHEN:
- Header utama line item:
  ITEM DESCRIPTION | Q'TY | U/PRICE | AMOUNT
- Pada vendor HL SHENZHEN, line item biasanya diawali:
  1) customer PO number 8 digit
  2) spare part / item code alphanumeric
  3) description multiline
  4) numeric line berisi quantity, unit price, amount
- Tidak ada kolom seq/item number khusus yang tercetak pada invoice.
- Nomor urut item perlu dibentuk berdasarkan urutan kemunculan item pada invoice.
- Header quantity pada invoice tercetak sebagai:
  Q'TY (PCS/PRS)
- Pada beberapa item, description bisa terpotong ke beberapa line dan harus digabung utuh.
- Jangan menganggap line "BICYCLE PARTS" sebagai description item.

1. inv_customer_po_no
   - Ambil customer PO number dari angka 8 digit pertama di awal blok item invoice.
   - Pada vendor HL SHENZHEN, angka ini muncul sebelum spare part code.
   - Contoh:
     - "45325168 FFUHL26CH38600" -> inv_customer_po_no = "45325168"
     - "45323722 HBSHLTDSD636B001" -> inv_customer_po_no = "45323722"
   - Jangan ambil:
     - invoice no.
     - reference no.
     - BL no.
     - container no.
     - seal no.

2. inv_seq
   - Karena invoice HL SHENZHEN tidak memiliki kolom seq tercetak, buat nomor urut item berdasarkan urutan kemunculan item pada invoice.
   - Mulai dari 1 dan naik +1 untuk setiap item baru.
   - Contoh:
     - item pertama -> inv_seq = 1
     - item kedua -> inv_seq = 2
     - item ketiga -> inv_seq = 3
   - Jangan mengambil customer PO number sebagai inv_seq.

3. inv_spart_item_no
   - Ambil kode alphanumeric kedua setelah customer PO number.
   - Ini adalah spare part / item number item invoice.
   - Contoh:
     - "45325168 FFUHL26CH38600" -> inv_spart_item_no = "FFUHL26CH38600"
     - "45323722 HBRHLDRAL21102" -> inv_spart_item_no = "HBRHLDRAL21102"
     - "45323723 SDNHLAT1013400" -> inv_spart_item_no = "SDNHLAT1013400"
   - Jangan ambil:
     - customer PO number
     - model pendek di description
     - quantity
     - price
     - amount

4. inv_description
   - Ambil deskripsi barang dari line-line setelah customer PO number + item code.
   - Gabungkan seluruh line description item sampai sebelum item berikutnya.
   - Masukkan spesifikasi barang yang memang bagian dari description.
   - Jangan masukkan:
     - customer PO number
     - item code
     - quantity
     - unit price
     - amount
     - section title "BICYCLE PARTS"
   - Contoh hasil:
     - "FORK CH-386A-26\" Φ28.6*Φ25.4*260L*0T/30 AL+ST YS-728 BLACK LEGS/BED CROWN AND BED STANCHIONS.W/O PIVOT & W/DISCMOUNT.TRAVEL:60MM,W/ZOOM LOGO SEPARATE"
     - "STEM TDS-D636B-8FOV(EN 15194) E:75 10*M5 AL SS.A.BK/"
     - "SEAT POST SP-C255(ISO-M) Φ30.9*350*2.2 BLACK BOLT A356.2/AL BED/BED/S.A.BK/"

5. inv_gw
   - HANYA boleh diambil dari invoice.
   - Pada invoice HL SHENZHEN sampel, tidak ada gross weight per line item.
   - Karena itu:
     inv_gw = "null"

6. inv_gw_unit
   - HANYA boleh diambil dari invoice.
   - Pada invoice HL SHENZHEN sampel, tidak ada gross weight per line item.
   - Karena itu:
     inv_gw_unit = "null"

7. inv_quantity
   - Ambil nilai quantity dari numeric line item invoice.
   - Ambil angka numeriknya saja.
   - Contoh:
     - "200 8.85 1,770.00" -> inv_quantity = 200
     - "1000 6.80 6,800.00" -> inv_quantity = 1000
     - "140 10.00 1,400.00" -> inv_quantity = 140

8. inv_quantity_unit
   - Ambil unit quantity dari bukti yang tercetak pada invoice.
   - Pada invoice HL SHENZHEN, header quantity tercetak sebagai "Q'TY (PCS/PRS)" dan umumnya tidak ada unit per-row yang ditulis ulang.
   - Jika item row secara eksplisit mencantumkan unit, gunakan unit tersebut.
   - Jika tidak ada unit per-row yang lebih spesifik, gunakan "PCS/PRS".
   - Jangan mengisi dari COO atau packing list untuk field invoice ini.

9. inv_unit_price
   - Ambil dari kolom U/PRICE.
   - Nilai harus numeric saja.
   - Hapus tanda pemisah ribuan jika ada.
   - Contoh:
     - "8.85" -> 8.85
     - "6.80" -> 6.8
     - "10.00" -> 10.0

10. inv_amount
   - Ambil dari kolom AMOUNT.
   - Nilai harus numeric saja.
   - Hapus tanda pemisah ribuan.
   - Contoh:
     - "1,770.00" -> 1770.0
     - "6,800.00" -> 6800.0
     - "1,400.00" -> 1400.0


PACKING LIST (PL)

Struktur umum packing list HL SHENZHEN:
- Dokumen berjudul "PACKING LIST".
- Header utama:
  ITEM DESCRIPTION | Q'TY PCS | PCS CTN | TTL CTNS | N.W. CTN | N.W. KGS | G.W. KGS | CUFT
- Pada vendor HL SHENZHEN, line item packing list biasanya berisi:
  1) customer PO number 8 digit
  2) item code alphanumeric
  3) description multiline
  4) satu atau lebih numeric row packaging
- Satu logical item bisa punya lebih dari satu row packaging.
- Row tambahan packaging biasanya tidak mengulang customer PO number dan item code.
- Row tambahan packaging tetap milik item sebelumnya, bukan item baru.
- Jangan menganggap line "BICYCLE PARTS" sebagai description item.

1. pl_customer_po_no
   - Ambil customer PO number dari angka 8 digit pertama di awal blok item packing list.
   - Contoh:
     - "45325168 FFUHL26CH38600" -> pl_customer_po_no = "45325168"
     - "45323722 HBSHLTDSD636B001" -> pl_customer_po_no = "45323722"

2. pl_item_no
   - Ambil item code alphanumeric kedua setelah customer PO number.
   - Contoh:
     - "45325168 FFUHL24CH38608" -> pl_item_no = "FFUHL24CH38608"
     - "45323722 HBRHLDRAL21102" -> pl_item_no = "HBRHLDRAL21102"
   - Jangan ambil:
     - customer PO number
     - C/NO. carton range
     - quantity
     - CTN
     - weight
     - volume

3. pl_description
   - Ambil deskripsi barang dari line-line setelah customer PO number + item code.
   - Gabungkan seluruh line description item sampai sebelum numeric packaging row atau item berikutnya.
   - Jangan masukkan:
     - customer PO number
     - item code
     - quantity/ctn numbers
     - carton range
     - weight
     - volume
     - section title "BICYCLE PARTS"
   - Contoh hasil:
     - "FORK CH-386A-24\" Φ28.6*Φ25.4*260L*0T/30 AL+ST YS-728 BLACK LEGS/BED CROWN AND BED STANCHIONS.W/O PIVOT & W/DISCMOUNT.TRAVEL:50MM,W/ZOOM LOGO SEPARATE"
     - "H/BAR DR-AL-211BTFOV(ISO-R) W:400 LASER THREAD-176 AL S.A.BK/"
     - "SEAT CLAMP AT-115 Φ29.8*Φ27.7 BLACK BOLTS+BL NYLOCK GLUE. LASER BEAR AL SS.A.BK"

4. pl_quantity
   - Ambil total quantity item dari kolom Q'TY PCS.
   - Jika satu item hanya punya satu packaging row, gunakan quantity pada row itu.
   - Jika satu item terpecah ke beberapa packaging row:
     - gunakan total quantity item yang benar berdasarkan seluruh blok item
     - jika quantity memang dipecah per-row, jumlahkan quantity seluruh packaging row milik item tersebut
     - jika quantity total item sudah jelas tercetak sebagai total item dan row berikutnya hanya breakdown packaging, jangan double count
   - Jangan ambil nilai dari kolom PCS CTN sebagai pl_quantity.

5. pl_package_unit
   - pl_package_unit hanya boleh diambil dari bukti package, bukan dari quantity unit.
   - Canonical value yang diperbolehkan:
     ["CT", "PX", "BL", "PXCT", "null"]
   - Pada packing list HL SHENZHEN, package evidence yang paling jelas berasal dari kolom TTL CTNS / CTN.
   - Maka:
     - CTN / CTNS / CARTON / CARTONS -> "CT"
   - Untuk sampel vendor HL SHENZHEN ini, gunakan:
     pl_package_unit = "CT"
   - Jangan ambil PCS / PRS / SET / PIECES sebagai pl_package_unit.

6. pl_package_count
   - Ambil jumlah package fisik dari kolom TTL CTNS.
   - Jika satu item punya lebih dari satu packaging row, jumlahkan seluruh TTL CTNS milik item tersebut.
   - Contoh:
     - row 33 CTNS + row 1 CTN -> pl_package_count = 34
     - row 166 CTNS + row 1 CTN -> pl_package_count = 167
   - Jangan ambil carton range seperti "1-33" atau "34-34" sebagai package count.

7. pl_nw
   - Ambil dari kolom N.W. KGS.
   - Nilai harus numeric saja.
   - Jika satu item terpecah ke beberapa packaging row, jumlahkan seluruh N.W. KGS milik item tersebut.
   - Jangan ambil N.W. CTN untuk field ini.
   - Contoh:
     - "449.86" + "4.54" -> pl_nw = 454.40
     - "2297.77" + "9.23" -> pl_nw = 2307.00

8. pl_gw
   - Ambil dari kolom G.W. KGS.
   - Nilai harus numeric saja.
   - Jika satu item terpecah ke beberapa packaging row, jumlahkan seluruh G.W. KGS milik item tersebut.
   - Contoh:
     - "494.90" + "5.91" -> pl_gw = 500.81
     - "2459.19" + "10.57" -> pl_gw = 2469.76

9. pl_volume
   - Ambil dari kolom CUFT.
   - Nilai harus numeric saja.
   - Jika satu item terpecah ke beberapa packaging row, jumlahkan seluruh volume milik item tersebut.
   - Contoh:
     - "66.07" + "2.00" -> pl_volume = 68.07
     - "296.64" + "1.79" -> pl_volume = 298.43


BILL OF LADING (BL)

Struktur umum BL HL SHENZHEN:
- Dokumen berjudul "BILL OF LADING".
- Deskripsi barang berada pada area description of goods.
- Pada sampel HL SHENZHEN, BL menuliskan deskripsi barang pada level kategori komoditas, bukan per-item invoice detail.
- Pada sampel, line-line goods yang relevan antara lain:
  - SEAT POST , HS CODE : 8714.99
  - HANDLEBAR ,HS CODE:8714.99
  - SEAT CLAMP ,HS CODE:8714.99
  - HANDLE STEM ,HS CODE : 8714.99
  - FORK SUSPENSION,HS CODE :8714.91
- "BICYCLE PARTS" adalah grouping umum shipment, bukan item description final yang perlu diambil sendiri.

1. bl_description
   - Ambil hanya deskripsi barang per line pada BL.
   - Ambil teks sebelum "HS CODE".
   - Jika ada koma sebelum HS CODE, buang koma penutupnya.
   - Jika deskripsi terpotong ke lebih dari satu line, gabungkan menjadi satu string utuh.
   - Contoh:
     - "SEAT POST , HS CODE : 8714.99" -> bl_description = "SEAT POST"
     - "HANDLEBAR ,HS CODE:8714.99" -> bl_description = "HANDLEBAR"
     - "FORK SUSPENSION,HS CODE :8714.91" -> bl_description = "FORK SUSPENSION"
   - Jangan ambil:
     - "BICYCLE PARTS"
     - P/O :
     - C/NO. :
     - MADE IN CHINA
     - total package 798 CTN
     - gross weight
     - volume
     - vessel / freight terms / container info

2. bl_hs_code
   - Ambil nilai setelah "HS CODE".
   - Hapus tanda titik dua / koma / spasi berlebih.
   - Contoh:
     - "HS CODE : 8714.99" -> bl_hs_code = "8714.99"
     - "HS CODE :8714.91" -> bl_hs_code = "8714.91"


CERTIFICATE OF ORIGIN (COO)

Struktur umum COO HL SHENZHEN:
- Dokumen COO vendor HL SHENZHEN tersedia pada sampel.
- Dokumen berbentuk Form RCEP / Certificate of Origin.
- Kolom utama item pada COO:
  Item number | Marks and numbers on packages | Description of goods | HS code | Origin criterion | RCEP Country of Origin | Quantity / Gross weight / other measure / FOB value | Invoice number(s) and date
- Pada sampel HL SHENZHEN, quantity pada COO sering tercetak menyatu dengan unit, misalnya:
  - 500SETS
  - 1000SETS
  - 85PIECES
  - 1SET
  - 180SETS
- Pada sampel ini, COO umumnya mencantumkan:
  - item number
  - description
  - HS code
  - origin criterion
  - country of origin
  - quantity + unit
  - invoice number/date
- Tetapi tidak selalu mencantumkan:
  - package count item-level
  - package unit item-level
  - gross weight item-level
  - amount/FOB item-level
  - customer PO item-level

1. coo_seq
   - Ambil dari nomor item / item number pada COO jika tercetak jelas.
   - Nilai harus numeric.
   - Contoh:
     - "1" -> coo_seq = 1
     - "28" -> coo_seq = 28
     - "69" -> coo_seq = 69

2. coo_mark_number
   - Ambil dari marks and numbers on packages HANYA jika ada mark item-level yang spesifik pada row tersebut.
   - Jika kolom marks kosong, hanya berisi simbol, atau tidak ada mark item-level yang jelas:
     coo_mark_number = "null"
   - Jangan mengambil shipping mark umum dari BL / PL untuk mengisi field COO ini.

3. coo_description
   - Ambil description of goods item-level dari COO.
   - Gabungkan line description item yang memang milik row tersebut.
   - Jangan masukkan:
     - item number
     - marks
     - HS code
     - quantity
     - origin criterion
     - invoice number/date
     - customer PO
   - Contoh hasil:
     - "FORK SUSPENSION CH-386A-24\" Φ28.6*Φ25.4*260L*0T/30 AL+ST YS-728 BLACK LEGS/BED CROWN AND BED STANCHIONS.W/O PIVOT & W/DISCMOUNT.TRAVEL:50MM,W/ZOOM LOGO SEPARATE"
     - "HANDLEBAR DR-AL-211BTFOV (ISO-R) W:420 LASER THREAD-176 AL S.A.BK/"
     - "SEAT POST SP-C255(ISO-M) Φ30.9*350*2.2 BLACK BOLT A356.2/AL BED/BED/S.A.BK/"

4. coo_hs_code
   - Ambil dari kolom HS code item-level pada COO.
   - Contoh:
     - "8714.91" -> "8714.91"
     - "8714.99" -> "8714.99"

5. coo_quantity
   - Ambil quantity item-level dari COO jika ada.
   - Jika quantity tercetak menyatu dengan unit, ambil bagian angkanya saja.
   - Contoh:
     - "500SETS" -> coo_quantity = 500
     - "85PIECES" -> coo_quantity = 85
     - "1SET" -> coo_quantity = 1
     - "180SETS" -> coo_quantity = 180
   - Jika kolom tersebut ternyata berisi gross weight / FOB dan bukan quantity count, jangan paksa isi quantity.

6. coo_unit
   - Ambil unit quantity yang menempel pada coo_quantity jika ada.
   - Contoh:
     - "500SETS" -> coo_unit = "SETS"
     - "85PIECES" -> coo_unit = "PIECES"
     - "1SET" -> coo_unit = "SET"
   - Jika kolom tersebut ternyata berisi gross weight / FOB dan bukan quantity count unit, isi "null".

7. coo_package_count
   - Hanya isi jika COO benar-benar mencantumkan package count per item secara jelas dan item-level.
   - Jika package count tidak ada atau hanya shipment-level:
     coo_package_count = null

8. coo_package_unit
   - Hanya isi jika COO benar-benar mencantumkan package unit per item secara jelas dan item-level.
   - Jika package unit tidak ada atau hanya shipment-level:
     coo_package_unit = "null"

9. coo_gw
   - Hanya isi jika COO benar-benar mencantumkan gross weight per item.
   - Ambil angka numeriknya saja.
   - Pada sampel HL SHENZHEN, kolom quantity biasanya berisi SETS / PIECES, bukan gross weight.
   - Karena itu jika row menampilkan "500SETS", "85PIECES", "1SET", dll:
     coo_gw = null
   - Jangan mengambil gross weight dari packing list untuk mengisi field COO ini.

10. coo_amount
   - Hanya isi jika COO benar-benar mencantumkan value / FOB / amount per item.
   - Jika COO tidak mencantumkan amount item-level:
     coo_amount = null
   - Jangan ambil amount dari invoice untuk mengisi coo_amount.

11. coo_criteria
   - Ambil dari origin criterion / origin conferring criterion pada COO jika ada.
   - Contoh value yang mungkin muncul:
     - WO
     - PE
     - CTC
     - CTSH
     - RVC
   - Pada sampel HL SHENZHEN, banyak item menggunakan "PE".
   - Contoh:
     - "\"PE\"" -> coo_criteria = "PE"

12. coo_customer_po_no
   - Field ini hanya diisi jika COO secara eksplisit mencantumkan customer PO number item-level atau row-level.
   - Jangan ambil invoice number sebagai customer PO.
   - Jangan ambil customer PO dari invoice / packing list untuk mengisi field ini.
   - Jika yang tercetak hanya invoice number seperti:
     - "90162107-08"
     maka itu adalah invoice number, BUKAN customer PO.
   - Jika customer PO tidak tercantum jelas pada COO:
     coo_customer_po_no = "null"
"""