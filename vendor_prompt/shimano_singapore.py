SHIMANO_SINGAPORE_PROMPT = """
INVOICE (INV)

Struktur umum invoice SHIMANO (SINGAPORE):
- Dokumen berjudul "*INVOICE*".
- Satu PDF bisa berisi banyak invoice berbeda seperti:
  - INS-...
  - INSPM-...
- Header utama line item:
  MARKS | DESCRIPTION | SPART / CPART | QTY & UNIT | UNIT PRICE (USD) | AMOUNT (USD)
- Dalam satu line item biasanya ada:
  1) product/material code di awal block, contoh:
     - 22E9901D036
     - 20RJ1480126
     - 239P2000356
  2) description multi-line
  3) SPART / CPART, contoh:
     - AMT401EJHFPRX085 / AMT401EJHFPRX085
     - ACSLG30010148 / ACSLG30010148
     - ARDTZ31AGSD / ARDTZ31AGSD
  4) quantity + unit
  5) marks block:
     - PT.IS
     - P/O No....
     - SURABAYA
     - optional PLT NO....
     - CTN NO....
- Pada vendor SHIMANO, item yang sama bisa muncul berulang sebagai beberapa printed row terpisah dengan CTN/PLT berbeda.
- Jika dokumen mencetaknya sebagai block/row terpisah, anggap itu item terpisah dan JANGAN merge hanya karena description atau spart sama.

1. inv_customer_po_no
   - Ambil dari line "P/O No." pada marks block item tersebut.
   - Ambil angka PO-nya saja.
   - Contoh:
     - "P/O No.45324353" -> inv_customer_po_no = "45324353"
     - "P/O No. 45322131" -> inv_customer_po_no = "45322131"
   - Jangan ambil:
     - invoice number seperti INS-2QB0542
     - LC number
     - CTN NO
     - PLT NO

2. inv_seq
   - Pada invoice SHIMANO sampel, tidak ada kolom seq numerik item yang tercetak jelas.
   - Product/material code seperti "22E9901D036" BUKAN seq numerik.
   - Karena itu:
     inv_seq = null
   - Jangan membuat nomor urut sendiri.

3. inv_spart_item_no
   - HANYA ambil dari kolom "SPART / CPART" pada row item yang sama.
   - JANGAN AMBIL dari kolom DESCRIPTION, meskipun ada kode alfanumerik yang terlihat jelas di sana.
   - JANGAN AMBIL product/material code di awal block description seperti:
     - 22E9901D036
     - 20RJ1480126
     - 239P2000356
     tapi ambil dari kolom "SPART / CPART"
   - inv_spart_item_no harus berasal dari kolom "SPART / CPART", bukan dari token pertama yang terbaca pada row.
   - Jika OCR membaca DESCRIPTION lebih dulu lalu SPART / CPART belakangan, tetap pilih value dari kolom "SPART / CPART".
   - Jika value pada kolom "SPART / CPART" berbentuk:
     - AMT401EJHFPRX085 / AMT401EJHFPRX085
     maka ambil 1 nilai spart saja:
     - "AMT401EJHFPRX085"
   - Jika kiri dan kanan berbeda, ambil value sebelah kiri slash sebagai inv_spart_item_no.
   - inv_spart_item_no tidak boleh diawali angka.
   - Jika candidate diawali angka, candidate tersebut PASTI SALAH untuk inv_spart_item_no dan harus ditolak.
   - Jika tidak ada bukti yang jelas pada kolom "SPART / CPART", isi "null".
   - Jangan fallback ke DESCRIPTION.

4. inv_description
   - Ambil deskripsi barang dari kolom DESCRIPTION saja.
   - Gabungkan seluruh line description item menjadi satu string utuh.
   - Jangan masukkan:
     - product/material code di awal row
     - SPART / CPART
     - PT.IS
     - P/O No.
     - SURABAYA
     - PLT NO.
     - CTN NO.
     - quantity
     - unit price
     - amount
   - Jika ada kata yang pecah karena line wrap / OCR yang sangat jelas, normalisasi seperlunya.
     Contoh:
     - "BLAC K" -> "BLACK"
     - "B ULK" -> "BULK"
     - "CO VER" -> "COVER"
   - Contoh hasil:
     - "DISC BRAKE ASSEMBLED SET/J-KIT; BL-MT401(L); BR-MT420(F); BLACK(BLACK LEVER); W/O ADAPTER; RESIN PAD(W/O FIN); 850MM HOSE(SM-BH90-SS BLACK); BULK"
     - "CASSETTE SPROCKET; CS-LG300-10; CUES; 10-SPEED; 11-13-15-17-20-23-28-34-41-48T; BULK"
     - "REAR DERAILLEUR; TZ-SERIES; RD-TZ31A; GS 6/7-SPEED; DIRECT ATTACHMENT; BULK"

5. inv_gw
   - HANYA boleh diambil dari invoice.
   - Pada invoice SHIMANO sampel, gross weight hanya ada di total footer dokumen, bukan per line item.
   - Karena itu:
     inv_gw = "null"

6. inv_gw_unit
   - HANYA boleh diambil dari invoice.
   - Pada invoice SHIMANO sampel, gross weight per line item tidak tersedia.
   - Karena itu:
     inv_gw_unit = "null"

7. inv_quantity
   - Ambil angka quantity dari kolom "QTY & UNIT".
   - Contoh:
     - "20 PCS" -> 20
     - "28 SET" -> 28
     - "2650 PCS" -> 2650

8. inv_quantity_unit
   - Ambil unit yang menempel pada quantity.
   - Pada sampel SHIMANO, unit yang muncul antara lain:
     - PCS
     - SET
   - Contoh:
     - "20 PCS" -> "PCS"
     - "28 SET" -> "SET"

9. inv_unit_price
   - Ambil dari kolom "UNIT PRICE (USD)".
   - Nilai harus numeric saja.
   - Contoh:
     - "29.2900" -> 29.29
     - "16.3300" -> 16.33
     - "1.8600" -> 1.86

10. inv_amount
   - Ambil dari kolom "AMOUNT (USD)".
   - Nilai harus numeric saja.
   - Contoh:
     - "585.8000" -> 585.8
     - "45903.6300" -> 45903.63
     - "1302.0000" -> 1302.0


PACKING LIST (PL)

Struktur umum packing list SHIMANO (SINGAPORE):
- Dokumen berjudul "PACKING LIST".
- Header utama:
  MARKS | DESCRIPTION | SPART / CPART | QTY & UNIT | PACKING TYPE | NET/GROSS WEIGHT(KG) | DIMENSION(CM,M3)
- Satu item packing list biasanya terdiri dari:
  1) product/material code
  2) description multi-line
  3) SPART / CPART
  4) qty & unit
  5) marks block:
     - PT.IS
     - P/O No....
     - SURABAYA
     - optional PLT NO....
     - CTN NO....
  6) beberapa detail packing component, misalnya:
     - 4 Full Carton (100pcs)
     - 1 Loose Carton (5pcs)
     - 1 Pallet (400pcs)
  7) satu total line item, misalnya:
     - 5 Carton 42.0000/46.6100 0.1270
     - 1 Pallet & 6 Carton 152.5400/214.7900 1.6060
     - 4 Pallet & 4 Carton 983.1600/1149.3000 4.9840
- Satu printed block item adalah satu item packing list.
- Jangan merge block berbeda hanya karena description atau spart sama.

1. pl_customer_po_no
   - Ambil dari line "P/O No." pada marks block item tersebut.
   - Ambil angka PO-nya saja.
   - Contoh:
     - "P/O No.45324353" -> pl_customer_po_no = "45324353"
     - "P/O No. 45322131" -> pl_customer_po_no = "45322131"

2. pl_item_no
   - HANYA ambil dari kolom "SPART / CPART" pada row item yang sama.
   - JANGAN AMBIL dari kolom DESCRIPTION, meskipun ada kode alfanumerik yang terlihat jelas di sana.
   - JANGAN AMBIL product/material code di awal block description seperti:
     - 22E9901D036
     - 20RJ1480126
     - 239P2000356
     tapi ambil dari kolom "SPART / CPART"
   - inv_spart_item_no harus berasal dari kolom "SPART / CPART", bukan dari token pertama yang terbaca pada row.
   - Jika OCR membaca kolom "DESCRIPTION" lebih dulu lalu kolom "SPART / CPART" setelahnya, tetap pilih value dari kolom "SPART / CPART".
   - Jika value pada kolom "SPART / CPART" berbentuk:
     - AMT401EJHFPRX085 / AMT401EJHFPRX085
     maka ambil 1 nilai spart saja:
     - "AMT401EJHFPRX085"
   - Jika kiri dan kanan berbeda, ambil value sebelah kiri slash sebagai inv_spart_item_no.
   - Jika candidate diawali angka, candidate tersebut PASTI SALAH untuk inv_spart_item_no dan harus ditolak.
   - Jika tidak ada bukti yang jelas pada kolom "SPART / CPART", isi "null".
   - Jangan fallback ke DESCRIPTION.

      - Jika OCR reading order mem-flatten kolom dan DESCRIPTION terbaca lebih dulu, tetap pilih value dari kolom "SPART / CPART", bukan token alfanumerik pertama.
   - Jika value berbentuk:
     - AMT401EJHFPRX085 / AMT401EJHFPRX085
     maka pl_item_no = "AMT401EJHFPRX085"
   - pl_item_no tidak boleh diawali angka.
   - Jika candidate diawali angka, candidate tersebut salah dan harus ditolak.
   - Jika tidak ada bukti jelas pada kolom "SPART / CPART", isi "null".
   - Jangan fallback ke DESCRIPTION.

3. pl_description
   - Ambil deskripsi barang dari kolom DESCRIPTION saja.
   - Gabungkan semua line description item.
   - Jangan masukkan:
     - product/material code
     - SPART / CPART
     - PT.IS
     - P/O No.
     - SURABAYA
     - PLT NO.
     - CTN NO.
     - detail packing seperti "4 Full Carton (100pcs)"
     - total line seperti "5 Carton 42.0000/46.6100 0.1270"
     - angka NW/GW/volume
   - Normalisasi kata pecah yang jelas bila perlu.
   - Contoh hasil:
     - "FREEHUB; FH-RS470; CENTER LOCK DISC(W/O LOCK RING) 10/11-SPEED FOR 12MM THRU TYPE AXLE(W/O AXLE); 32H OLD:142MM; W/O ROTOR MOUNT COVER; BLACK; BULK"
     - "DISC BRAKE ASSEMBLED SET/J-KIT; BL-MT201(L); BR-UR300(F); BLACK; FOR 160MM ROTOR; RESIN PAD(W/O FIN); 850MM HOSE(SM-BH59 BLACK); BULK"

4. pl_quantity
   - Ambil value numerik/angka quantity dari kolom "QTY & UNIT".
   - Contoh:
     - "20 PCS" -> 20
     - "28 SET" -> 28
     - "530 PCS" -> 530

5. pl_package_unit
   - pl_package_unit hanya boleh diambil dari kolom "PACKING TYPE"
   - JANGAN AMBIL dari kolom "QTY & UNIT"
   - Canonical value yang diperbolehkan hanya:
     ["CT", "PX", "BL", "PXCT", "null"]
   - Aturan mapping:
     - Carton / Full Carton / Loose Carton / CTN -> "CT"
     - Pallet / PLT -> "PX"
     - Bale -> "BL"
     - Jika satu item menggunakan lebih dari 1 package unit -> "PXCT"
       Contoh: 4 Pallet & 4 Carton
               maka pl_package_unit = "PXCT", karena memiliki lebih dari 1 package unit (PX dan CT).
   - Prioritas bukti:
     1) total line package item dari kolom "PACKING TYPE", misalnya:
        - "5 Carton"
        - "1 Pallet & 6 Carton"
        - "2 Pallet"
     2) jika total line tidak jelas, fallback ke marks block pada kolom "MARKS" yaitu PLT NO. / CTN NO.
   - Contoh:
     - CTN NO.23-25-> pl_package_unit = "CT"
     - PLT NO.21-22 -> pl_package_unit = "PX"
     - PLT NO.21-22
       CTN NO.23-25
       maka pl_package_unit = "PXCT"

6. pl_package_count
   - Ambil jumlah total line package untuk item tersebut.
   - Prioritas:
     1) gunakan total line package item, dari kolom "PACKING TYPE"
     2) jika total line tidak ada, hitung dari PLT NO / CTN NO pada marks block dari kolom "MARKS"
   - Aturan hitung dari total line:
     - "1 Carton" -> 1
     - "5 Carton" -> 5
     - "2 Pallet" -> 2
     - "1 Pallet & 6 Carton" -> 7
     - "4 Pallet & 4 Carton" -> 8
   - Aturan hitung dari range marks bila total line tidak tersedia:
     - "CTN NO.1-1" -> 1
     - "CTN NO.34-46" -> 13
     - "PLT NO.30-33" -> 4
     - "PLT NO.30-33" + "CTN NO.34-46" -> 4 + 13 = 17
   - Jangan ambil total packages dari footer dokumen sebagai package_count item-level.

7. pl_nw
   - Ambil net weight item-level dari kolom "NET/GROSS WEIGHT".
   - Gunakan pl_nw pada sel total line item sebelum tanda '/' (Terletak di bagian bawah), bukan dari component line.
   - Prioritas:
     1) gunakan volume pada total line item
     2) jika total line tidak ada, jumlahkan semua M3 component line untuk item itu
   - Contoh:
    |NET/GROSS WEIGHT(KG)|
    |====================|
    |     12.7600         |
    |     16.4700        |
    |     1.9100         |
    |     3.6000         |
    ---------------------|
    |   14.6700/20.0700  |
    ---------------------|
    Maka pl_nw untuk item tersebut adalah 14.6700 (gunakan angka pada total line) dan BUKAN 12.76 ataupun 1.9100.

8. pl_gw
   - Ambil gross weight item-level dari kolom "NET/GROSS WEIGHT".
   - Gunakan pl_gw pada sel total line item setelah tanda '/' (Terletak di bagian bawah), bukan dari component line.
   - Contoh:
    |NET/GROSS WEIGHT(KG)|
    |====================|
    |     12.7600         |
    |     16.4700        |
    |     1.9100         |
    |     3.6000         |
    ---------------------|
    |   14.6700/20.0700  |
    ---------------------|
    Maka pl_gw untuk item tersebut adalah 20.0700 (gunakan angka pada total line) dan BUKAN 16.47 ataupun 3.6000.

9. pl_volume
   - Ambil volume item-level dalam M3 dari kolom "DIMENSION (CM, M3)".
   - Gunakan volume pada sel total line item (Terletak di bagian bawah), bukan dari component line.
   - Contoh:
    |DIMENSION(CM,M3)|
    |================|
    |   108X110X90   |
    |   1.0690       |
    |   52X33X39     |
    |   0.2680       |
    |   54X35X24     |
    |   .0450        |
    ------------------
    |   1.3820       |
    ------------------
    Maka pl_volume untuk item tersebut adalah 1.382 (gunakan angka pada total line).
   - Jika total line item tidak ada, jumlahkan semua M3 component line untuk item itu.
   - Contoh:
     - "0.1270" -> pl_volume = 0.127
     - "1.6060" -> pl_volume = 1.606
     - "4.9840" -> pl_volume = 4.984

BILL OF LADING (BL)

Struktur umum BL SHIMANO (SINGAPORE):
- Page 1 adalah ocean bill of lading shipment summary.
- Page 2 adalah "B/L ATTACHMENT" dan ini yang berisi item/category-level description.
- Pada page 1, deskripsi utama hanya bersifat umum seperti:
  - SHIPPER'S LOAD, COUNT & SEALED
  - 1X20'GP & 2X40'HC CONTAINERS SAID TO CONTAIN:
  - AS PER ATTACHED LIST
- Pada page 2 attachment, item-level category yang muncul antara lain:
  - FRONT DERAILLEUR HS NUMBER: 8714.99
  - REAR DERAILLEUR HS NUMBER: 8714.99
  - SHIFT LEVER HS NUMBER: 8714.99
  - SHIFT/BRAKE LEVER HS NUMBER: 8714.99
  - CASSETTE SPROCKET HS NUMBER: 8714.93
- BL SHIMANO bersifat summary-level, bukan detail spart/item penuh seperti invoice atau COO.

Dokumen BL dimapping terhadap invoice berdasarkan kemiripan dari inv_description dan bl_description.

1. bl_description dan bl_hs_code:
   - bl_description dimapping dengan inv_description. Jika inv_description tidak exist pada dokumen BL, maka bl_description fill null saja.
   - Value bl_hs_code diisi sesuai dengan bl_descriptionnya.
   - Hanya boleh mengambil dari dokumen Bill Of Lading (BL), TIDAK BOLEH dari dokumen yang lain

   - Contoh:
     - "FRONT DERAILLEUR HS NUMBER: 8714.99"
     - "REAR DERAILLEUR HS NUMBER: 8714.99"
     - "SHIFT LEVER HS NUMBER: 8714.99"
     - "SHIFT/BRAKE LEVER HS NUMBER: 8714.99"
     - "CASSETTE SPROCKET HS NUMBER: 8714.93

     - Misalkan pada inv_description ada value:
       SPROCKET FOR INTERNAL HUB;
       18T(2.3MM) SILVER(DX); BULK
       dimana itu tidak ada pada description item BL jika dibandingkan berdasarkan kemiripan. 
       Maka bl_description dan bl_hs_code isi null saja.

     - Misalkan pada inv_description ada value:
       SHIFT LEVER; SL-M315-8R; RIGHT;
       8-SPEED RAPIDFIRE PLUS 2400MM
       STAINLESS INNER; W/ OPTICAL GEAR
       DISPLAY; BULK
       dimana itu ada pada description item BL jika dibandingkan berdasarkan kemiripan (SHIFT LEVER HS NUMBER: 8714.99).
       Maka bl_description isi "SHIFT LEVER" dan bl_hs_code isi "8714.99"
     
     - Item pada BL dapat dimapping beberapa kali atau dimapping pada banyak item pada invoice, tidak one to one.

CERTIFICATE OF ORIGIN (COO)

Struktur umum COO SHIMANO (SINGAPORE):
- COO bisa berbentuk:
  - ORIGIN DECLARATION (AWSC)
  - DECLARATION OF ORIGIN (Regional Comprehensive Economic Partnership Agreement)
  - BACK-TO-BACK DECLARATION OF ORIGIN
- Producer country pada sampel bisa berbeda:
  - INDONESIA
  - MALAYSIA
  - CHINA
- Meskipun form title berbeda, struktur item block konsisten.
- Satu item COO umumnya berisi urutan:
  1) marks block:
     - PT.IS
     - P/O No....
     - SURABAYA
     - optional PLT NO....
     - CTN NO....
  2) INVOICE NUMBER
  3) INVOICE DATE
  4) product/material code
  5) short code / model code
  6) SPART code
  7) description
  8) HS CODE
  9) ORIGIN REF NO
  10) DATE OF ISSUANCE
  11) PRODUCER AUTHORISATION CODE
  12) COUNTRY OF FIRST EXPORTING PARTY
  13) criterion + country + unit + quantity + FOB value
- Jika item dicetak sebagai block terpisah, anggap sebagai row/item terpisah.

Dokumen COO dimapping terhadap invoice berdasarkan kemiripan dari inv_description dan coo_description.

1. coo_seq
   - Pada COO SHIMANO, tidak ada item number / seq numerik yang tercetak jelas.
   - Product/material code seperti "239P2000356" BUKAN coo_seq.
   - Karena itu:
     coo_seq = null
   - Jangan membuat nomor urut sendiri.

2. coo_mark_number
   - Ambil seluruh isi marks block dari kolom "MARKIN" sebagai satu string ter-normalisasi.
   - Marks block diambil dari awal item sampai sebelum "INVOICE NUMBER:".
   - Sertakan elemen berikut jika memang ada:
     - PT.IS
     - P/O No....
     - SURABAYA
     - PLT NO....
     - CTN NO....
   - Contoh hasil:
     - "PT.IS P/O No.45324415 SURABAYA PLT NO.1-1 CTN NO.2-22"
     - "PT.IS P/O No.45324269 SURABAYA CTN NO.1-1"
     - "PT.IS P/O No.45323288 SURABAYA PLT NO.33-33 CTN NO.34-35"
   - Jika marks block benar-benar tidak ada, isi "null".

3. coo_description
   - Ambil hanya deskripsi barang naratif.
   - Gabungkan semua line description item menjadi satu string utuh.
   - Jangan masukkan:
     - marks block
     - INVOICE NUMBER
     - INVOICE DATE
     - product/material code
     - short code / model code
     - SPART code
     - HS CODE
     - ORIGIN REF NO
     - DATE OF ISSUANCE
     - PRODUCER AUTHORISATION CODE
     - COUNTRY OF FIRST EXPORTING PARTY
     - criterion
     - quantity
     - amount
   - Contoh hasil:
     - "REAR DERAILLEUR; TZ-SERIES; RD-TZ31A; GS 6/7-SPEED; DIRECT ATTACHMENT; BULK"
     - "DISC BRAKE ASSEMBLED SET/J-KIT; BL-MT401(L); BR-MT420(F); BLACK(BLACK LEVER); W/O ADAPTER; RESIN PAD(W/O FIN); 850MM HOSE(SM-BH90-SS BLACK); BULK"
     - "CASSETTE SPROCKET; CS-LG300-10; CUES; 10-SPEED; 11-13-15-17-20-23-28-34-41-48T; BULK"

4. coo_hs_code
   - Ambil dari line "HS CODE:".
   - Contoh:
     - "HS CODE: 871499" -> coo_hs_code = "871499"
     - "HS CODE: 871494" -> coo_hs_code = "871494"
     - "HS CODE: 871493" -> coo_hs_code = "871493"

5. coo_quantity
   - Ambil value numerik/angka quantity dari kolom "QUANTITY".
   - Contoh:
     - "RVC 100% CHINA PCS 2650 $ 4,929.00" -> coo_quantity = 2650
     - "RVC 96.12% MALAYSIA PCS 20 $ 585.80" -> coo_quantity = 20
     - "RVC 76.41% MALAYSIA SET 50 $ 282.50" -> coo_quantity = 50

6. coo_unit
   - Ambil unit dari kolom "UNIT".
   - Contoh:
     - "RVC 100% CHINA PCS 2650 $ 4,929.00" -> coo_unit = "PCS"
     - "RVC 76.41% MALAYSIA SET 50 $ 282.50" -> coo_unit = "SET"

7. coo_package_count
   - Hitung dari marks block dari kolom "MARKING" berdasarkan range PLT NO. dan CTN NO.
   - Aturan:
     - "CTN NO.1-1" -> 1
     - "CTN NO.10-21" -> 12
     - "PLT NO.1-1" -> 1
     - "PLT NO.30-33" -> 4
   - Jika item memiliki PLT dan CTN sekaligus, jumlahkan keduanya.
   - Contoh:
     - "PLT NO.1-1" + "CTN NO.2-22" -> 1 + 21 = 22
     - "PLT NO.30-33" + "CTN NO.34-46" -> 4 + 13 = 17
     - "PLT NO.60-60" + "CTN NO.61-68" -> 1 + 8 = 9
   - Jika tidak ada package evidence yang jelas, isi null.

8. coo_package_unit
   - Ambil dari marking block dari kolom "MARKING".
   - Canonical value yang diperbolehkan hanya:
     ["CT", "PX", "BL", "PXCT", "null"]
   - Aturan:
     - hanya ada CTN NO. -> "CT"
     - hanya ada PLT NO. -> "PX"
     - jika ada PLT NO. dan CTN NO. -> "PXCT"
     - jika tidak ada package evidence -> "null"
   - Contoh:
     - "CTN NO.10-21" -> "CT"
     - "PLT NO.33-33" -> "PX"
     - "PLT NO.1-1" + "CTN NO.2-22" -> "PXCT"

9. coo_gw
   - Pada COO SHIMANO, tidak ada gross weight item-level yang tercantum eksplisit.
   - Kolom akhir hanya menunjukkan:
     - criterion
     - country
     - unit
     - quantity
     - FOB value
   - Karena itu:
     coo_gw = null
   - Jangan ambil GW dari invoice atau packing list untuk mengisi coo_gw.

10. coo_amount
   - Ambil FOB value / amount dari kolom "FOB VALUE (USD)"
   - Ambil angka numeric saja, tanpa "$" dan tanpa koma ribuan.
   - Contoh:
     - "$ 4,929.00" -> 4929.0
     - "$ 585.80" -> 585.8
     - "$ 45,903.63" -> 45903.63

11. coo_criteria
   - Ambil origin conferring criterion dari kolom "ORIGIN CONFERING CRITERION".
   - Untuk vendor SHIMANO pada sampel, criterion muncul sebagai bentuk lengkap:
     - "RVC 100%"
     - "RVC 96.12%"
     - "RVC 85.51%"
     - "RVC 65.56%"
   - Contoh:
     - "RVC 100% CHINA PCS 2650 $ 4,929.00" -> coo_criteria = "RVC"
     - "RVC 96.12% MALAYSIA PCS 20 $ 585.80" -> coo_criteria = "RVC"
   - Jangan masukkan persentase, country, unit, quantity, atau amount ke dalam coo_criteria.

12. coo_customer_po_no
   - Ambil dari line "P/O No." pada marks block dari kolom "MARKING" pada COO.
   - Ambil angka PO saja.
   - Contoh:
     - "P/O No.45324415" -> coo_customer_po_no = "45324415"
     - "P/O No. 45323288" -> coo_customer_po_no = "45323288"
"""