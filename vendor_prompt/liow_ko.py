LIOW_KO_PROMPT = """
INVOICE (INV)

Aturan umum ekstraksi vendor LIOW KO:
- Vendor pada sampel adalah LIOW KO ELECTRONIC TECHNOLOGY (SHENZHEN) CO., LTD.
- Dokumen invoice berjudul "INVOICE".
- Dokumen packing list berjudul "PACKING LIST".
- Dokumen BL berjudul "BILL OF LADING".
- Dokumen COO berjudul "REGIONAL COMPREHENSIVE ECONOMIC PARTNERSHIP AGREEMENT CERTIFICATE OF ORIGIN".
- Jika field bertipe string dan tidak ada bukti yang jelas, isi "null".
- Jika field bertipe number dan tidak ada bukti yang jelas, isi null.
- Jangan mengisi field dari dokumen lain jika field tersebut harus berasal dari dokumen spesifik.
- Gabungkan teks yang terpotong baris / line wrap menjadi satu value yang utuh.
- Jika satu row/item terpotong ke halaman berikutnya, tetap anggap sebagai item yang sama, bukan item baru.
- Jangan menggabungkan dua row berbeda hanya karena part number atau description-nya sama.
- Jangan halusinasi nilai yang tidak tercetak jelas pada dokumen.
- Rapikan whitespace berlebih akibat OCR, tetapi jangan mengubah isi sebenarnya.

Struktur umum invoice LIOW KO:
- Header utama line item:
  Purchase order Number | PART NUMBER | DESCRIPTION | UNIT | QUANTITY | UNIT PRICE(USD) | AMOUNT
- Pada invoice LIOW KO, customer PO ada per row pada kolom pertama.
- Tidak ada kolom nomor urut item / seq yang jelas pada sampel invoice.
- Tidak ada gross weight per item pada sampel invoice.

1. inv_customer_po_no
   - Ambil dari kolom "Purchase order Number" pada row item yang sama.
   - Customer PO berbentuk angka dan berlaku per row, bukan grouping block.
   - Ambil angka PO-nya saja sebagai string.
   - Contoh:
     - "45327072" -> inv_customer_po_no = "45327072"
     - "49021355" -> inv_customer_po_no = "49021355"
   - Jangan ambil:
     - invoice number
     - BL number
     - container number
     - tanggal invoice

2. inv_seq
   - Hanya ambil jika invoice benar-benar mencetak nomor item / seq yang eksplisit.
   - Pada sampel invoice LIOW KO, tidak ada kolom seq item-level yang jelas.
   - Jangan menggunakan urutan row sebagai seq.
   - Karena itu, jika tidak ada nomor item yang tercetak jelas:
     inv_seq = null

3. inv_spart_item_no
   - Ambil dari kolom "PART NUMBER".
   - Gabungkan jika part number terpotong ke dua baris.
   - Contoh:
     - "FRXLKIS21PHG0100" -> inv_spart_item_no = "FRXLKIS21PHG0100"
     - "FREZZINSRE1204" -> inv_spart_item_no = "FREZZINSRE1204"
     - "FRPLKIS21PFP1600" -> inv_spart_item_no = "FRPLKIS21PFP1600"
   - Jangan ambil:
     - customer PO
     - description
     - unit
     - quantity
     - price
     - amount

4. inv_description
   - Ambil dari kolom "DESCRIPTION" pada row item yang sama.
   - Gabungkan seluruh description yang ter-wrap sampai sebelum kolom unit/quantity item itu berakhir.
   - Jika description terpotong baris, gabungkan menjadi satu string utuh.
   - Pertahankan spesifikasi yang memang tercetak sebagai bagian description.
   - Contoh:
     - "FRAME PART;LIOW KO;IS21PHG01_V1"
     - "FRAME PART; REPLACEABLE DROP OUT 8910-0000P BK DA"
     - "FRAME PART;LIOW KO;IS21PRE03-1-R_F2 AND IS21PRE03-L_F3;-;AL6061;"
   - Jangan masukkan:
     - customer PO
     - part number
     - unit
     - quantity
     - unit price
     - amount
     - header dokumen
     - alamat shipper / consignee

5. inv_gw
   - HANYA boleh diambil dari invoice.
   - Pada sampel invoice LIOW KO, tidak ada gross weight per item.
   - Karena itu:
     inv_gw = "null"

6. inv_gw_unit
   - HANYA boleh diambil dari invoice.
   - Pada sampel invoice LIOW KO, tidak ada unit gross weight per item.
   - Karena itu:
     inv_gw_unit = "null"

7. inv_quantity
   - Ambil nilai quantity dari kolom "QUANTITY".
   - Ambil angka numeriknya saja.
   - Hapus separator ribuan jika ada.
   - Contoh:
     - "64" -> 64
     - "3500" -> 3500
     - "700" -> 700

8. inv_quantity_unit
   - Ambil dari kolom "UNIT".
   - Gunakan unit yang tercetak pada invoice.
   - Contoh:
     - "SET" -> "SET"
     - "PCS" -> "PCS"
     - "PRS" -> "PRS"

9. inv_unit_price
   - Ambil dari kolom "UNIT PRICE(USD)".
   - Nilai harus numeric saja.
   - Jangan bawa teks "USD".
   - Contoh:
     - "3.14" -> 3.14
     - "1.55" -> 1.55
     - "18.30" -> 18.3

10. inv_amount
   - Ambil dari kolom "AMOUNT".
   - Nilai harus numeric saja.
   - Hapus separator ribuan jika ada.
   - Contoh:
     - "200.96" -> 200.96
     - "5,425.00" -> 5425.0
     - "3,668.00" -> 3668.0


PACKING LIST (PL)

Struktur umum packing list LIOW KO:
- Dokumen berjudul "PACKING LIST".
- Header item pada sampel berbentuk:
  PART NUMBER | DESCRIPTION | QUANTITY | [carton no./range] | TOTAL CTN | NW | GW
- Pada packing list LIOW KO, tidak ada customer PO per item yang tercetak jelas.
- Pada packing list sampel, tidak ada kolom volume item-level yang jelas.
- Setelah quantity biasanya ada carton mark / carton range seperti:
  - LK-1
  - LK-2-8
  - LK-19-27
  Ini adalah marks/range carton, bukan package_count.
- Angka setelah carton mark/range adalah jumlah karton / total ctn item-level.
- Packing list bisa menggabungkan beberapa invoice row menjadi satu row berdasarkan part number.
  Karena itu, jangan memecah row packing list menjadi beberapa customer PO hanya karena invoice memiliki beberapa PO.
- Semua field pl_* harus diekstrak dari dokumen PACKING LIST saja.
- Dilarang menggunakan data Invoice untuk mengisi field PL.

- Jika satu item PACKING LIST yang sama ter-match ke beberapa row invoice/customer PO, jangan menduplikasi nilai numerik PL.
  Nilai numerik PL hanya muncul pada kemunculan pertama.
  Kemunculan berikutnya untuk item PL yang sama isi 0 pada field numerik aditif PL:
  pl_quantity, pl_package_count, pl_nw, pl_gw, pl_volume.
- Jangan split nilai PL mengikuti quantity invoice.
  Contoh: 
  jika PL mencetak 469 SET, lalu invoice memecah menjadi 64, 225, 180, 
  maka output PL harus 469, 0, 0; bukan 64, 225, 180 atau 469, 469, 469.

1. pl_customer_po_no
   - HANYA isi jika packing list secara eksplisit mencantumkan customer PO untuk item tersebut.
   - Pada sampel packing list LIOW KO, tidak ada customer PO item-level yang jelas.
   - Jangan copy PO dari invoice ke field packing list.
   - Karena itu, jika PO tidak tercetak jelas di packing list:
     pl_customer_po_no = "null"

2. pl_item_no
   - Ambil dari kolom "PART NUMBER".
   - Gabungkan jika part number terpotong ke beberapa line.
   - Contoh:
     - "FRXLKIS21PHG0100"
     - "FRPLKIS21PFP1600"
     - "FRXLKIS23PFK0300"
   - Jangan ambil:
     - description
     - carton mark
     - quantity
     - NW
     - GW

3. pl_description
   - Ambil dari kolom "DESCRIPTION".
   - Gabungkan line wrap yang masih milik item yang sama.
   - Pertahankan teks spesifikasi yang memang tercetak.
   - Contoh:
     - "FRAME PART;LIOW KO;IS21PHG01_V1"
     - "FRAME PART; END FRAME;ZZ;DW18 DROPOUTS(R￾1);AL6061;"
     - "FRAME PART; LIOW KO;IS23PFK03-A;SABK;ALLOY 6061"
   - Jangan masukkan:
     - part number
     - quantity
     - carton mark/range seperti LK-19-27
     - total ctn
     - NW
     - GW
     - total dokumen

4. pl_quantity
   - Ambil angka quantity item-level dari kolom "QUANTITY".
   - Ambil angka numeriknya saja.
   - Quantity unit seperti PCS/SET/PRS tidak ikut dimasukkan ke field ini.
   - Hapus separator ribuan jika ada.
   - Contoh:
     - "469 SET" -> 469
     - "1,060 PCS" -> 1060
     - "81 PRS" -> 81
   - Jangan memakai inv_quantity untuk mengisi pl_quantity.

5. pl_package_unit
   - pl_package_unit hanya boleh diambil dari bukti package, bukan dari quantity unit.
   - Bukti package pada packing list LIOW KO berasal dari kolom "TOTAL CTN".
   - Canonical rule:
     - CTN / CTNS / CARTON / CARTONS -> "CT"
   - Untuk row item yang memang memiliki jumlah karton:
     pl_package_unit = "CT"
   - Jangan ambil PCS / PRS / SET sebagai pl_package_unit.

6. pl_package_count
   - Ambil dari angka jumlah karton setelah carton mark/range.
   - Ini adalah nilai di kolom "TOTAL CTN".
   - Contoh:
     - "LK-1 1" -> pl_package_count = 1
     - "LK-2-8 7" -> pl_package_count = 7
     - "LK-19-27 9" -> pl_package_count = 9
   - Jangan ambil carton mark/range seperti LK-2-8 sebagai package_count.
   - Jangan ambil total shipment seperti "47 CTN" sebagai package_count item-level.
   - Jangan memakai data invoice untuk mengisi pl_package_count.

7. pl_nw
   - Ambil dari kolom "NW".
   - Nilai harus numeric saja.
   - Contoh:
     - "9.38" -> 9.38
     - "118.30" -> 118.3
     - "49.55" -> 49.55
   - Jika ada kasus seperti ini:
   PART NUMBER      | DESCRIPTION                                |  QUANTITY |  CTN   | TOTAL CTN | NW    | GW    |
   FRXLKIS21PFP1800 | FRAME PART; LIOW KO;IS21PFP18_F5;-;AL6061; |  5 PCS    |        |           | 0.63  | 0.83  |
   FRXLKIS21PFP1800 | FRAME PART; LIOW KO;IS21PFP18_F5;-;AL6061; |  200 PCS  |  LK-31 | 1         | 25.00 | 25.40|
   maka pl_nw = 25.63
   - Jangan memakai data invoice, BL, atau COO untuk mengisi pl_nw.


8. pl_gw
   - Ambil dari kolom "GW".
   - Nilai harus numeric saja.
   - Contoh:
     - "10.58" -> 10.58
     - "120.30" -> 120.3
     - "51.15" -> 51.15
     - Jika ada kasus seperti ini:
   PART NUMBER      | DESCRIPTION                                |  QUANTITY |  CTN   | TOTAL CTN | NW    | GW    |
   FRXLKIS21PFP1800 | FRAME PART; LIOW KO;IS21PFP18_F5;-;AL6061; |  5 PCS    |        |           | 0.63  | 0.83  |
   FRXLKIS21PFP1800 | FRAME PART; LIOW KO;IS21PFP18_F5;-;AL6061; |  200 PCS  |  LK-31 | 1         | 25.00 | 25.40 |
   maka pl_gw = 26.23
   - Jangan memakai data invoice, BL, atau COO untuk mengisi pl_gw.


9. pl_volume
   - HANYA boleh diambil dari packing list.
   - Pada sampel packing list LIOW KO, tidak ada kolom volume item-level yang jelas.
   - Jangan ambil volume 1.2 M3 dari BL untuk mengisi field packing list.
   - Karena itu, jika volume item-level tidak tercetak jelas:
     pl_volume = null


BILL OF LADING (BL)

Struktur umum BL LIOW KO:
- Dokumen berjudul "BILL OF LADING".
- Area deskripsi goods berada di section:
  "Number and Kind of packages / Description of Goods"
- Pada sampel BL, line goods tercetak ringkas seperti:
  - FRAME PART IS16PFP08 HS NUMBER : 8714.91
  - FRAME PART IS16PFP07 HS NUMBER : 8714.91
  - FRAME PART IS24PFP10 HS NUMBER : 8714.91
  - FRAME PART IS24PFP07 HS NUMBER : 8714.91
  - FRAME PART IS23PFK50 HS NUMBER : 8714.91
- "BICYCLE PARTS" hanyalah grouping umum shipment, bukan item description final.
- BL hanya menuliskan item yang benar-benar tercetak di area goods description.
- Jangan backfill item BL dari invoice/packing list jika item tersebut tidak tertulis di BL.

1. bl_description dan bl_hs_code:
   - Field bl_description dan bl_hs_code merupakan SATU PAKET dan WAJIB selalu terisi (TIDAK BOLEH NULL).
   - Sumber data HANYA boleh dari dokumen Bill Of Lading (BL) saja, TIDAK BOLEH mengambil dari dokumen lain.

   =========================
   LOGIC MAPPING (BERURUTAN)
   =========================
   - STEP 1 - Mapping berdasarkan inv_description:
     - Cari apakah inv_description MATCH dengan tipe barang dan kode barang pada deskripsi item pada BL.
     - Jika ditemukan:
       - bl_description = description item pada BL yang sesuai
       - bl_hs_code = HS CODE yang terkait dengan bl_description tersebut
  - STEP 2 - Jika STEP 2 tidak ditemukan:
     - Karena bl_description dan bl_hs_code TIDAK BOLEH NULL,
   - Maka PILIH SECARA ACAK (RANDOM) satu pasangan data dari item BL:
     - bl_description = salah satu description item dari BL
     - bl_hs_code = HS CODE yang sesuai dengan item tersebut
   - JANGAN MEMBUAT BL DESCRIPTION DAN BL HS CODE BARU YANG TIDAK ADA DI DOKUMEN BILL OF LADING (BL). GUNAKAN RANDOM ITEM YANG ADA SAJA DI DOKUMEN BILL OF LADING (BL).
     Contoh:
     DATA DI BL SEPERTI INI:
     FRAME PART IS16PFP08 HS NUMBER : 8714.91
     FRAME PART IS16PFP07 HS NUMBER : 8714.91
     FRAME PART IS24PFP10 HS NUMBER : 8714.91
     FRAME PART IS24PFP07 HS NUMBER : 8714.91
     FRAME PART IS23PFK50 HS NUMBER : 8714.91
     
     JANGAN BUAT DATA BARU SEPERTI = FRAME PART IS23PFK03, YANG TIDAK ADA PADA DOKUMEN BILL OF LADING SEBAGAI HASIL EKSTRAKSI DAN MAPPING.
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
       3. random BL item (last resort, WAJIB jika tidak match)

   =========================
   CONTOH
   =========================
   BL:
     - FRAME PART IS16PFP08 HS NUMBER : 8714.91
     - FRAME PART IS24PFP10 HS NUMBER : 8714.91

   Case 1:
     inv_description = FRAME PART;LIOW KO;IS16PFP08;AL6061
     → MATCH STEP 1
     → bl_description = FRAME PART IS16PFP08 
     → bl_hs_code = 8714.91

   Case 2:
     inv_description = FRAME PART; LIOW KO;IS23PFK03-A;SABK;ALLOY 6061
     inv_description tidak ada di BL
     → STEP 3 (RANDOM)
     → bl_description = FRAME PART IS24PFP10 (contoh random)
     → bl_hs_code = 8714.91

CERTIFICATE OF ORIGIN (COO)

Catatan penting COO vendor LIOW KO:
- Sampel COO tersedia dan memuat item-level table.
- Struktur kolom COO pada sampel:
  item number | marks and numbers on packages | number and kind of packages; and description of goods | HS code | origin conferring criterion | RCEP country of origin | quantity | invoice number(s) and date of invoice(s)
- Pada sampel COO:
  - marks item-level yang terlihat adalah "N/M" (generic)
  - criterion yang tercetak adalah "PE"
  - country of origin yang tercetak adalah "CHINA"
  - quantity tercetak bersama unit seperti 64SETS / 3500PIECES / 50PAIRS
  - kolom invoice berisi invoice number dan date, bukan customer PO
- Description item dapat terpotong ke line berikutnya atau halaman berikutnya.
- Jika satu item COO terpotong antar halaman, gabungkan tetap sebagai item yang sama.
  Contoh: "INS-RE-" di akhir halaman harus digabung dengan "2012-02;AL6061;" di halaman berikutnya.
- Jangan memindahkan nilai dari invoice / packing list / BL ke field COO bila COO sendiri tidak mencantumkannya.

1. coo_seq
   - Ambil dari kolom "Item number".
   - Nilai numeric.
   - coo_seq pasti tersedia atau tidak boleh "null", kecuali tidak termapping dengan line item invoice.
   - Item number tercetak jelas seperti:
     - 1
     - 2
     - 3
     - ...
     
2. coo_mark_number
   - Ambil dari marks and numbers on packages HANYA jika ada mark item-level yang spesifik.
   - Jika hanya berisi generic mark seperti:
     - "N/M"
     - "NO MARK"
     - kosong
     maka:
     coo_mark_number = "null"

3. coo_description
   - Ambil description of goods item-level dari COO.
   - Gabungkan semua line description yang memang milik row tersebut.
   - Jika description wrap ke baris berikutnya atau halaman berikutnya, gabungkan utuh.
   - Pertahankan teks yang memang bagian description, termasuk qualifier yang tercetak seperti "(SAMPLE)" bila ada.
   - Contoh:
     - "FRAME PART;LIOW KO;IS21PHG01_V1"
     - "FRAME PART; REPLACEABLE DROP OUT 8910-0000P BK DA"
     - "FRAME PART;LIOW KO;INS-RE-2012-02;AL6061;"
   - Jangan masukkan:
     - item number
     - marks
     - HS code
     - quantity / QTY
     - criterion
     - country of origin
     - invoice number/date
     - BL number
     - total shipment remarks seperti "FORTY-SEVEN(47) CTNS ONLY"

4. coo_hs_code
   - Ambil dari kolom HS code item-level pada COO.
   - Jika layout OCR melebur, ambil nilai HS CODE yang jelas terkait ke row item itu.
   - Contoh:
     - "8714.91" -> coo_hs_code = "8714.91"

5. coo_quantity
   - Ambil quantity item-level dari COO.
   - Ambil angka numeriknya saja.
   - Jika tertulis menyatu seperti:
     - "64SETS" -> 64
     - "3500PIECES" -> 3500
     - "50PAIRS" -> 50

6. coo_unit
   - Ambil unit quantity yang menempel pada coo_quantity.
   - coo_unit pasti tersedia atau tidak boleh "null", kecuali tidak termapping dengan line item invoice.
   - Gunakan unit sebagaimana tercetak pada COO.
   - Contoh:
     - "64SETS" -> "SETS"
     - "3500PIECES" -> "PIECES"
     - "50PAIRS" -> "PAIRS"
     - "1PIECE" -> "PIECE"
   - Jangan menormalkan ke unit dokumen lain.

7. coo_package_count
   - Hanya isi jika COO benar-benar mencantumkan package count per item secara jelas dan item-level.
   - Pada sampel COO LIOW KO, tidak ada package count item-level yang jelas.
   - Total shipment seperti "FORTY-SEVEN(47) CTNS ONLY" bukan package_count item-level.
   - Karena itu, bila tidak tercetak jelas:
     coo_package_count = null

8. coo_package_unit
   - Hanya isi jika COO benar-benar mencantumkan package unit per item secara jelas dan item-level.
   - Total shipment seperti "CTNS ONLY" di remark akhir bukan package unit item-level.
   - Karena itu, bila tidak tercetak jelas:
     coo_package_unit = "null"

9. coo_gw
   - Hanya isi jika COO benar-benar mencantumkan gross weight per item.
   - Pada sampel COO LIOW KO, kolom quantity berisi quantity + unit, bukan gross weight item-level.
   - Karena itu:
     coo_gw = null

10. coo_amount
   - Hanya isi jika COO benar-benar mencantumkan value / FOB / amount per item.
   - Pada sampel COO LIOW KO, tidak ada amount item-level yang jelas untuk row-row PE ini.
   - Jangan ambil amount dari invoice untuk mengisi coo_amount.
   - Karena itu:
     coo_amount = null

11. coo_criteria
   - Ambil dari kolom "Origin Conferring Criterion".
   - Contoh pada sampel:
     - "PE" -> coo_criteria = "PE"
   - Jika tidak ada criterion yang jelas, isi "null".

12. coo_customer_po_no
   - Field ini hanya diisi jika COO secara eksplisit mencantumkan customer PO number item-level atau row-level.
   - Kolom invoice number/date pada COO BUKAN customer PO.
   - Jangan ambil PO dari invoice untuk mengisi field COO ini.
   - Karena itu, jika customer PO tidak tercantum jelas pada COO:
     coo_customer_po_no = "null"
"""