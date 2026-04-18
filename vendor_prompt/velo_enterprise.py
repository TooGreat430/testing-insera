VELO_ENTERPRISE_PROMPT = """
INVOICE (INV)

Aturan umum ekstraksi vendor VELO ENTERPRISE:
- Vendor pada sampel adalah VELO ENTERPRISE CO., LTD.
- Dokumen invoice berjudul "Commercial Invoice".
- Dokumen packing list berjudul "Packing List".
- Dokumen BL berjudul "Bill Of Lading".
- Jika field bertipe string dan tidak ada bukti yang jelas, isi "null".
- Jika field bertipe number dan tidak ada bukti yang jelas, isi null.
- Jangan mengisi field dari dokumen lain jika field tersebut harus berasal dari dokumen spesifik.
- Gabungkan teks yang terpotong baris / line wrap menjadi satu value yang utuh.
- Jika item terpotong ke halaman berikutnya, tetap anggap sebagai item yang sama, bukan item baru.
- Jangan halusinasi nilai yang tidak tercetak jelas pada dokumen.

Struktur umum invoice VELO:
- Header utama line item:
  Item/Part no. | Description | Quantity | Unit Price | Amount
- Pada vendor VELO, kolom "Item/Part no." berisi:
  1) nomor urut item / seq
  2) part number / spare part number
- Part number sering terpotong ke 2 baris.
  Contoh pola:
  - seq: 60
  - part no terpotong:
      BAXVLPLG38802
      0R
    maka part number utuh = BAXVLPLG388020R
- Di dalam area description sering muncul line "P.O. NO:45322360" atau format serupa.
- Line "P.O. NO:..." adalah penanda grouping customer PO untuk item-item setelahnya, BUKAN bagian description barang.
- Penting untuk layout / OCR reading order:
  - Pada sebagian invoice VELO, part number dari kolom "Item/Part no." dapat ikut terbaca di bawah line "P.O. NO:..." sebelum description barang dimulai.
  - Jika ada alphanumeric panjang tepat di bawah "P.O. NO:..." dan nilainya cocok dengan pola part number item, perlakukan itu sebagai inv_spart_item_no, BUKAN inv_description.
  - Jangan salah menganggap line alphanumeric panjang di bawah "P.O. NO:..." sebagai pl_item_no; konteks invoice ini tetap milik inv_spart_item_no.
  - Jika part number tersebut terpotong ke baris berikutnya, gabungkan seluruh fragmennya menjadi satu value utuh tanpa spasi.
- Pada page pertama juga ada PO NO di area kanan atas. Jika item pertama belum punya line "P.O. NO:..." yang lebih dekat di atasnya, maka gunakan PO header/page tersebut.
- Jika page berikutnya melanjutkan group PO yang sama dan belum ada PO baru, carry forward PO terakhir yang valid dari item sebelumnya.
1. inv_customer_po_no
   - Ambil customer PO number dari "P.O. NO:" / "PO NO." terdekat yang menaungi item tersebut.
   - Prioritas:
     1) line "P.O. NO:xxxxx" yang muncul paling dekat di atas item
     2) jika item adalah item pertama dalam group dan belum ada line internal, gunakan PO header pada page
     3) jika page lanjutan tidak mengulang PO, carry forward PO terakhir yang valid dari page/item sebelumnya
   - Customer PO yang diambil adalah angka PO-nya saja.
   - Contoh:
     - "PO NO. 45322358" -> inv_customer_po_no = "45322358"
     - "P.O. NO:45322360" -> inv_customer_po_no = "45322360"
   - Jangan ambil:
     - invoice no.
     - ref no.
     - BL no.
     - vessel / shipment no.
   - Line "P.O. NO:..." yang berada di antara dua item berlaku untuk item setelah line tersebut, bukan untuk item sebelumnya.

2. inv_seq
   - Ambil dari angka urut pada kolom "Item/Part no.".
   - Ini adalah nomor item yang tercetak jelas di sisi kiri.
   - Contoh:
     - 60
     - 110
     - 172
     - 215
   - Jangan ambil angka quantity, harga, atau PO number sebagai inv_seq.

3. inv_spart_item_no
   - Ambil part number dari kolom "Item/Part no.".
   - Pada vendor VELO, part number berada di bawah seq dan sering wrap ke baris berikutnya.
   - Dalam beberapa hasil OCR / flatten layout, part number yang sama juga bisa ikut muncul tepat di bawah line "P.O. NO:..." sebelum description barang.
   - Jika ada line alphanumeric panjang di bawah "P.O. NO:..." yang jelas merupakan identitas item, line tersebut tetap diperlakukan sebagai inv_spart_item_no.
   - Gabungkan seluruh fragmen part number yang terpotong menjadi satu string tanpa spasi tambahan.
   - Scan 1-2 line lanjutan di bawahnya untuk memastikan suffix part number yang terpotong ikut tergabung penuh.
   - Contoh:
     - BAXVLPLG38802 + 0R -> "BAXVLPLG388020R"
     - HBGVLVLG2154 + 0001R -> "HBGVLVLG21540001R"
     - FRXVLIS24PFK0 + 100R -> "FRXVLIS24PFK0100R"
   - Jika urutan baca OCR menjadi:
     - P.O. NO:45322358
     - BAXVLPLG38802
     - 0R
     - BATTERY HOLDER DI2; VELO; ...
     maka:
     - inv_spart_item_no = "BAXVLPLG388020R"
     - inv_description dimulai dari "BATTERY HOLDER DI2; VELO; ..."
   - Jangan ambil:
     - seq
     - customer PO number
     - model pendek di description seperti PLG-38-802
     - quantity
     - unit price
     - amount

4. inv_description
   - Ambil deskripsi barang dari kolom Description.
   - Gabungkan seluruh line description item sampai sebelum item berikutnya atau sebelum line "P.O. NO:" berikutnya yang menandai group baru.
   - Masukkan spesifikasi barang yang memang bagian dari description.
   - Pada vendor VELO, description sering berupa beberapa line seperti:
     - nama barang
     - brand / VELO
     - model pendek
     - ukuran
     - material
     - warna
     - OEM PACKING
   - "OEM PACKING" dianggap bagian dari description dan boleh disertakan.
   - Jika ada line alphanumeric panjang tepat di bawah "P.O. NO:..." yang sebenarnya adalah part number item, jangan masukkan line itu ke inv_description.
   - inv_description dimulai setelah inv_spart_item_no selesai direkonstruksi penuh.
   - Jangan masukkan:
     - line "P.O. NO:..."
     - seq
     - part number, termasuk part number yang ikut terbaca di bawah PO line karena OCR / reading order
     - quantity
     - unit
     - unit price
     - amount
     - section title "BICYCLE PARTS"
   - Contoh hasil:
     - "BATTERY HOLDER DI2; VELO; PLG-38-802 VLD-II-1638 95.3*22.7MM ABS BLACK, W/M5*8MM INSERT 2PCS OEM PACKING"
     - "DOWN TUBE PROTECTOR; VELO; IS24PFK36 BLACK RUBBER TPR A70 COLLOSUS T DT SHUTLE PAD, W/POLYGON LOGO 140X53mm OEM PACKING"

5. inv_gw
   - HANYA boleh diambil dari invoice.
   - Pada invoice VELO sampel, tidak ada gross weight per line item.
   - Karena itu:
     inv_gw = "null"

6. inv_gw_unit
   - HANYA boleh diambil dari invoice.
   - Pada invoice VELO sampel, tidak ada gross weight per line item.
   - Karena itu:
     inv_gw_unit = "null"

7. inv_quantity
   - Ambil nilai quantity dari kolom Quantity.
   - Ambil angka numeriknya saja.
   - Contoh:
     - "36 PCS" -> 36
     - "17 PRS" -> 17
     - "40 SET" -> 40
     - "498 PCS" -> 498

8. inv_quantity_unit
   - Ambil unit yang menempel pada quantity di invoice.
   - Pada sampel VELO, unit yang muncul antara lain:
     - PCS
     - PRS
     - SET
   - Contoh:
     - "36 PCS" -> "PCS"
     - "17 PRS" -> "PRS"
     - "40 SET" -> "SET"

9. inv_unit_price
   - Ambil dari kolom Unit Price.
   - Hapus prefix mata uang seperti "USD".
   - Nilai harus numeric saja.
   - Contoh:
     - "USD 0.5800" -> 0.58
     - "USD 8.1000" -> 8.1
     - "USD 8.4200" -> 8.42

10. inv_amount
   - Ambil dari kolom Amount.
   - Hapus prefix mata uang seperti "USD".
   - Nilai harus numeric saja.
   - Contoh:
     - "USD 20.88" -> 20.88
     - "USD 137.70" -> 137.7
     - "USD 345.22" -> 345.22


PACKING LIST (PL)

Struktur umum packing list VELO:
- Dokumen berjudul "PACKING LIST".
- Header utama:
  C/NO. | DESCRIPTION | CTN | QUANTITY | N. WEIGHT | G. WEIGHT | MEASURE*CU'FT
- Pada vendor VELO, line item packing list biasanya berisi:
  1) part number di awal blok description
  2) deskripsi barang di line-line setelahnya
  3) angka CTN, quantity, N.W., G.W., dan volume di kolom kanan
- Seperti invoice, line "P.O. NO:xxxxx" di area item adalah penanda group customer PO untuk item berikutnya.
- Jika page berikutnya melanjutkan PO yang sama dan PO tidak diulang, carry forward PO terakhir yang valid.
- Terkadang ada karakter OCR seperti "@" di kolom angka. Abaikan karakter ini; fokus pada angka utamanya.

1. pl_customer_po_no
   - Ambil customer PO number dari "P.O. NO:" / "PO NO." terdekat yang menaungi item tersebut.
   - Prioritas:
     1) line "P.O. NO:xxxxx" yang paling dekat di atas item
     2) jika item pertama dalam group belum punya line internal, gunakan PO header pada page
     3) jika page berikutnya melanjutkan group yang sama, carry forward PO terakhir yang valid
   - Contoh:
     - "PO NO. 45322358" -> pl_customer_po_no = "45322358"
     - "P.O. NO:45322360" -> pl_customer_po_no = "45322360"

2. pl_item_no
   - Ambil part number item dari awal blok description.
   - Lokasi dari pl_item_no dibawah persis Po No:
     BICYCLE PARTS
     P.O. NO: 45322358
     BAXVLPL388020GR
     
     Maka pl_item_no nya adalah BAXVLPL388020GR
   - Pada vendor VELO, part number muncul di awal item block dan sering berupa alphanumeric panjang.
   - Jika part number terpotong ke beberapa line, gabungkan menjadi satu string utuh.
   - Contoh:
     - "BAXVLPLG388020R"
     - "PRXVLPLG3803100R"
     - "FRXVLIS24PFK0100R"
   - Jangan ambil:
     - model pendek seperti PLG-38-802 atau IS24PFK38
     - C/NO.
     - CTN
     - quantity
     - weight
     - volume

3. pl_description
   - Ambil deskripsi barang setelah part number di blok description.
   - Gabungkan seluruh line description item sampai sebelum item berikutnya atau sebelum "P.O. NO:" berikutnya.
   - Masukkan spesifikasi barang yang memang bagian dari description.
   - "OEM PACKING" dianggap bagian dari description dan boleh disertakan.
   - Jangan masukkan:
     - part number
     - C/NO.
     - CTN
     - quantity
     - N. WEIGHT
     - G. WEIGHT
     - MEASURE
     - line "P.O. NO:..."
     - section title "BICYCLE PARTS"
   - Contoh hasil:
     - "BATTERY HOLDER DI2; VELO; PLG-38-802 VLD-II-1638 95.3*22.7MM ABS BLACK, W/M5*8MM INSERT 2PCS OEM PACKING"
     - "BAR TAPE; VELO; VLT-5102; BLK; SUPER ANTI-SLIPPERY DURABLE/SHOCKPROOF MATERIAL 250*3CM; THICKNESS;3MM W/GEL, W/VLP-56 BLK PLUG W/EMBOSSED LINC LOGO POLYGON PRODUCT, OEM PACKING"

4. pl_quantity
   - Ambil nilai quantity dari kolom QUANTITY.
   - Ambil angka numeriknya saja.
   - Jangan ambil unitnya di field ini.
   - Contoh:
     - "36 PCS" -> 36
     - "17 PRS" -> 17
     - "40 SET" -> 40
   - Jika satu logical item terpecah ke lebih dari satu visual row namun masih item yang sama, jumlahkan quantity-nya.

5. pl_package_unit
   - pl_package_unit hanya boleh diambil dari bukti package, bukan dari quantity unit.
   - Canonical value yang diperbolehkan:
     ["CT", "PX", "BL", "PXCT", "null"]
   - Pada packing list VELO, package evidence yang paling jelas berasal dari kolom "CTN" dan total "81 CTNS".
   - Maka:
     - CTN / CTNS / CARTON / CARTONS -> "CT"
   - Untuk sampel vendor VELO ini, gunakan:
     pl_package_unit = "CT"
   - Jangan ambil PCS / PRS / SET sebagai pl_package_unit.

6. pl_package_count
   - Ambil jumlah package fisik dari kolom CTN.
   - Kolom CTN lebih reliable untuk package_count dibanding kolom C/NO.
   - Abaikan simbol OCR seperti "@".
   - Contoh:
     - "1" -> 1
     - "2" -> 2
     - "4" -> 4
   - Jika satu logical item terpecah ke lebih dari satu visual row namun masih item yang sama, jumlahkan CTN-nya.
   - Jangan ambil total dokumen "81 CTNS" sebagai package_count item-level.

7. pl_nw
   - Ambil dari kolom N. WEIGHT.
   - Nilai harus numeric saja.
   - Abaikan karakter OCR seperti "@".
   - Contoh:
     - "0.288" -> 0.288
     - "14.200" -> 14.2
     - "2.870" -> 2.87
   - Jika satu logical item terpecah ke beberapa row, jumlahkan seluruh N.W.-nya.

8. pl_gw
   - Ambil dari kolom G. WEIGHT.
   - Nilai harus numeric saja.
   - Abaikan karakter OCR seperti "@".
   - Contoh:
     - "0.360" -> 0.36
     - "15.200" -> 15.2
     - "3.280" -> 3.28
   - Jika satu logical item terpecah ke beberapa row, jumlahkan seluruh G.W.-nya.

9. pl_volume
   - Ambil dari kolom MEASURE*CU'FT.
   - Nilai harus numeric saja.
   - Abaikan karakter OCR seperti "@".
   - Contoh:
     - "0.180" -> 0.18
     - "1.180" -> 1.18
     - "2.950" -> 2.95
   - Jika satu logical item terpecah ke beberapa row, jumlahkan seluruh volume-nya.


BILL OF LADING (BL)

Struktur umum BL VELO:
- Dokumen berjudul "BILL OF LADING".
- Deskripsi barang berada pada area:
  "DESCRIPTION OF PACKAGES AND GOODS"
- Pada sampel VELO, terdapat line-line goods seperti:
  - GROMMET VLD-I-1286, HS CODE : 8714.99
  - GROMMET VLD-I-1287, HS CODE : 8714.99
  - BAR TAPE VLT-1001, HS CODE : 8714.99
  - PROTECTOR IS24PFK38, HS CODE : 8714.99
  - HANDLE GRIP VLG-2002D2, HS CODE : 8714.99
- "BICYCLE PARTS" adalah grouping umum shipment, bukan item description final yang perlu diambil sendiri.

1. bl_description
   - Ambil hanya deskripsi barang per line pada BL.
   - Ambil teks sebelum "HS CODE".
   - Jika ada koma sebelum HS CODE, buang koma penutupnya.
   - Jika deskripsi terpotong ke lebih dari satu line, gabungkan menjadi satu string utuh.
   - Contoh:
     - "GROMMET VLD-I-1286, HS CODE : 8714.99" -> bl_description = "GROMMET VLD-I-1286"
     - "BAR TAPE VLT-1001, HS CODE : 8714.99" -> bl_description = "BAR TAPE VLT-1001"
     - "HANDLE GRIP VLG-2002D2, HS CODE : 8714.99" -> bl_description = "HANDLE GRIP VLG-2002D2"
   - Jangan ambil:
     - "BICYCLE PARTS"
     - PO NO.
     - C/NO.
     - MADE IN TAIWAN
     - total package 81 CTNS
     - gross weight
     - CBM
     - vessel / freight terms / container info

2. bl_hs_code
   - Ambil nilai setelah "HS CODE".
   - Hapus tanda titik dua / spasi berlebih.
   - Contoh:
     - "HS CODE : 8714.99" -> bl_hs_code = "8714.99"

Catatan tambahan BL:
- Pada vendor VELO, BL menuliskan deskripsi model/family barang yang lebih ringkas dibanding full part number di invoice/packing list.
- Karena itu, saat matching BL ke invoice/PL:
  - jangan memaksa full part number harus sama persis
  - cocokkan berdasarkan family / stem description yang sama
- Contoh kecocokan family:
  - BL "GROMMET VLD-I-1286" dapat cocok ke item invoice/PL dengan family VLD-I-1286
  - BL "PROTECTOR IS24PFK38" dapat cocok ke item invoice/PL yang description/model-nya IS24PFK38
  - BL "HANDLE GRIP VLG-2002D2" dapat cocok ke item invoice/PL yang description/model-nya VLG-2002D2


CERTIFICATE OF ORIGIN (COO)

Catatan penting COO vendor VELO:
- Sampel COO VELO belum tersedia pada paket dokumen ini.
- Karena itu, rule COO di bawah bersifat konservatif / provisional.
- Prinsip utama: hanya isi field COO jika bukti item-level benar-benar tercetak jelas pada COO.
- Jangan memindahkan nilai dari invoice / packing list / BL ke field COO jika COO-nya sendiri tidak mencantumkannya.

1. coo_seq
   - Ambil dari nomor item / item number pada COO jika tercetak jelas.
   - Nilai harus numeric.
   - Jika tidak ada nomor item yang jelas, isi null.

2. coo_mark_number
   - Ambil dari marks and numbers on packages HANYA jika ada mark item-level yang spesifik.
   - Jika hanya berisi generic mark seperti "N/M", "NO MARK", atau kosong:
     coo_mark_number = "null"

3. coo_description
   - Ambil description of goods item-level dari COO.
   - Gabungkan line description item yang memang milik row tersebut.
   - Jangan masukkan:
     - item number
     - marks
     - HS code
     - quantity
     - gross weight
     - value / FOB
     - origin criterion
     - invoice number
     - PO number
   - Jika tidak ada description item-level yang jelas, isi "null".

4. coo_hs_code
   - Ambil dari kolom HS code item-level pada COO jika ada.
   - Jika tidak ada HS code item-level yang jelas, isi "null".

5. coo_quantity
   - Ambil quantity item-level dari COO jika ada.
   - Ambil angka numeriknya saja.
   - Jika tidak ada quantity item-level yang jelas, isi null.

6. coo_unit
   - Ambil unit quantity yang menempel pada coo_quantity jika ada.
   - Contoh:
     - "36 PCS" -> "PCS"
     - "17 PRS" -> "PRS"
     - "40 SET" -> "SET"
   - Jika tidak ada unit yang jelas, isi "null".

7. coo_package_count
   - Hanya isi jika COO benar-benar mencantumkan package count per item secara jelas dan item-level.
   - Jika package count hanya shipment-level total atau tidak jelas:
     coo_package_count = null

8. coo_package_unit
   - Hanya isi jika COO benar-benar mencantumkan package unit per item secara jelas dan item-level.
   - Jika package unit hanya shipment-level total atau tidak jelas:
     coo_package_unit = "null"

9. coo_gw
   - Hanya isi jika COO benar-benar mencantumkan gross weight per item.
   - Ambil angka numeriknya saja.
   - Jika gross weight tidak ada atau hanya shipment-level:
     coo_gw = null

10. coo_amount
   - Hanya isi jika COO benar-benar mencantumkan value / FOB / amount per item.
   - Jika COO tidak mencantumkan amount item-level:
     coo_amount = null
   - Jangan ambil amount dari invoice untuk mengisi coo_amount.

11. coo_criteria
   - Ambil dari origin criterion / origin conferring criterion pada COO jika ada.
   - Contoh value yang mungkin muncul: WO, PE, CTC, CTSH, RVC, dll.
   - Jika tidak ada criterion yang jelas, isi "null".

12. coo_customer_po_no
   - Field ini hanya diisi jika COO secara eksplisit mencantumkan customer PO number item-level atau row-level.
   - Jangan ambil invoice number atau PO dari dokumen lain untuk mengisi field ini.
   - Jika customer PO tidak tercantum jelas pada COO:
     coo_customer_po_no = "null"
"""