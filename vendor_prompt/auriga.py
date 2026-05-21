AURIGA_PROMPT = """
INVOICE (INV)

Aturan umum ekstraksi vendor AURIGA:
- Vendor pada sampel adalah AURIGA (HUIZHOU) TECHNOLOGY CO., LTD.
- Dokumen invoice berjudul "Commercial Invoice".
- Dokumen packing list berjudul "PACKING LIST".
- Dokumen BL berjudul "BILL OF LADING".
- Dokumen COO berjudul "CERTIFICATE OF ORIGIN" / "Form RCEP".
- Jika field bertipe string dan tidak ada bukti yang jelas, isi "null".
- Jika field bertipe number dan tidak ada bukti yang jelas, isi null.
- Jangan mengisi field dari dokumen lain jika field tersebut harus berasal dari dokumen spesifik.
- Gabungkan teks yang terpotong baris / line wrap menjadi satu value yang utuh.
- Jika item terpotong ke halaman berikutnya, tetap anggap sebagai item yang sama, bukan item baru.
- Jangan halusinasi nilai yang tidak tercetak jelas pada dokumen.

Struktur umum invoice AURIGA:
- Header utama line item:
  ITEM NO. | PART NO. | PO No. | DESCRIPTION | Q'TY | PRICE | AMOUNT
- Pada vendor AURIGA, customer PO number tercetak jelas di kolom "PO No."
- Part number tercetak jelas di kolom "PART NO."
- Quantity pada invoice sering menempel dengan unit.
  Contoh:
  - 38.000PR
  - 12600.000PC
  - 353.000PC

1. inv_customer_po_no
   - Ambil customer PO number dari kolom "PO No."
   - Nilai yang diambil adalah nomor PO-nya saja.
   - Contoh:
     - "45324574" -> inv_customer_po_no = "45324574"
     - "45325077" -> inv_customer_po_no = "45325077"
   - Jangan ambil:
     - invoice no.
     - ref no.
     - BL no.
     - container no.
     - vessel / shipment no.

2. inv_seq
   - Ambil dari kolom "ITEM NO."
   - Ini adalah nomor urut item yang tercetak jelas di sisi kiri.
   - Nilai harus numeric.
   - Contoh:
     - 1
     - 12
     - 34
   - Jangan ambil quantity, price, amount, atau PO number sebagai inv_seq.

3. inv_spart_item_no
   - Ambil part number dari kolom "PART NO."
   - Part number pada vendor AURIGA biasanya berupa alphanumeric panjang.
   - Jika part number terpotong ke beberapa line, gabungkan menjadi satu string utuh tanpa spasi tambahan.
   - Contoh:
     - "BRLTTJL510TS01"
     - "BRKTTHDR285RR001"
     - "BRXTTTR160016003"
   - Jangan ambil:
     - seq
     - model pendek di description
     - quantity
     - unit price
     - amount

4. inv_description
   - Ambil deskripsi barang dari kolom "DESCRIPTION".
   - Gabungkan seluruh line description item sampai sebelum item berikutnya.
   - Masukkan spesifikasi barang yang memang bagian dari description.
   - Jangan masukkan:
     - seq
     - part number
     - PO no.
     - quantity
     - unit
     - unit price
     - amount
   - Contoh hasil:
     - "BRAKE LEVER; TEKTRO; JL-510TS;BLACK/SILVER LEVER;ALLOY BRACKET/ALLOY LEVER,LEFT/RIGHT,4 FINGERS,FOR LINEAR PULL BRAKES,FOR TWIST/REV OSHIFTER W/ TEKTRO LOGO"
     - "BRAKE SET; TEKTRO; MD-C510; BLACK; MECHANICAL FLAT MOUNT ALLOY W/O ROTOR ORGANIC COMPOUND PAD REAR W/O ADAPTOR WITH FLAT MOUNT BOLT M5X32MM"

5. inv_gw
   - HANYA boleh diambil dari invoice.
   - Pada invoice AURIGA sampel, tidak ada gross weight per line item.
   - Karena itu:
     inv_gw = "null"

6. inv_gw_unit
   - HANYA boleh diambil dari invoice.
   - Pada invoice AURIGA sampel, tidak ada gross weight unit per line item.
   - Karena itu:
     inv_gw_unit = "null"

7. inv_quantity
   - Ambil nilai quantity dari kolom "Q'TY".
   - Ambil angka numeriknya saja.
   - Unit jangan dimasukkan ke field ini.
   - Contoh:
     - "38.000PR" -> 38
     - "12600.000PC" -> 12600
     - "353.000PC" -> 353

8. inv_quantity_unit
   - Ambil unit yang menempel pada quantity di invoice.
   - Pada sampel AURIGA, unit yang muncul antara lain:
     - PR
     - PC
   - Contoh:
     - "38.000PR" -> "PR"
     - "12600.000PC" -> "PC"

9. inv_unit_price
   - Ambil dari kolom "PRICE".
   - Nilai harus numeric saja.
   - Hapus pemisah ribuan jika ada.
   - Contoh:
     - "16.19" -> 16.19
     - "18.00" -> 18
     - "102.13" -> 102.13

10. inv_amount
   - Ambil dari kolom "AMOUNT".
   - Nilai harus numeric saja.
   - Hapus pemisah ribuan jika ada.
   - Contoh:
     - "615.22" -> 615.22
     - "226,800.00" -> 226800
     - "19,323.22" -> 19323.22


PACKING LIST (PL)

Struktur umum packing list AURIGA:
- Dokumen berjudul "PACKING LIST".
- Header utama:
  PACKING NO | DESCRIPTION | QUANTITY | NET WEIGHT | GROSS WEIGHT | MEASURE

STRUKTUR DUAL @-LINE PER BLOK (SANGAT PENTING — sumber utama kesalahan):
Setiap blok item packing list AURIGA memiliki DUA baris angka yang sama-sama diawali simbol "@":
  Baris ke-1 (BARIS PER-CARTON): muncul di line yang sama dengan "PACKING NO" + customer PO.
    Berisi nilai PER SATU CARTON (rate per carton), bukan total row.
    Contoh: "2-253 45325077 @50PC @10.078KG @11.066KG @0.024" → @50PC = 50 PC per carton.
  Baris ke-2 (BARIS TOTAL): muncul di line yang sama dengan part number (di bawah baris ke-1).
    Berisi nilai TOTAL untuk SELURUH range carton di baris itu (per-carton × jumlah carton).
    Contoh: "BRKTTMDM280F08 @12600PC @2539.656KG @2788.632KG @6.048" → @12600PC = total.

ATURAN MUTLAK pengisian pl_quantity / pl_nw / pl_gw / pl_volume:
  → AMBIL HANYA DARI BARIS KE-2 (BARIS TOTAL).
  → DILARANG KERAS menggunakan baris ke-1 (per-carton) untuk field ini.
  → DILARANG KERAS menjumlahkan baris ke-1 + baris ke-2 dalam blok yang sama (itu akan menghasilkan double-counting).
  Verifikasi visual: pada blok dengan range >1 carton, nilai baris ke-2 jauh lebih besar dari baris ke-1 (misal @12600PC vs @50PC). Selalu pilih yang besar.
  Pada blok dengan range 1 carton (mis. "1-1" atau "261-261"), baris ke-1 dan baris ke-2 BERNILAI SAMA — tetap ambil baris ke-2 (atau salah satu, karena identik).

Terkadang satu item logical terpecah ke beberapa packing range yang berurutan (umumnya 1 range "besar" + 1 range "ekor" 1-carton untuk sisa quantity).
  Contoh:
  - "254-260 45325077 ... @50PC ..." → per-carton baris ke-1
    "BRKTTMDC510R01 @350PC @57.575KG @64.491KG @0.168" → TOTAL baris ke-2 (7 ctn × 50PC = 350 PC)
  - "261-261 45325077 ... @3PC ..." → per-carton baris ke-1 (juga = total karena 1 carton)
    "BRKTTMDC510R01 @3PC @0.494KG @0.624KG @0.004" → TOTAL baris ke-2
  Kedua blok ini adalah item yang sama (part number + PO + description match) → digabung jadi 1 baris invoice yang quantity-nya 353 PC, 8 carton, 58.069 KG NW, 65.115 KG GW.

ATURAN PENCOCOKAN INV ↔ PL PER-PO (PENTING):
Beberapa part number yang sama muncul di banyak PO (mis. BRKTTMDC400F09 ada di PO 45325077 dan PO 45325086, BRKTTHDM280RF001 ada di PO 45325078 dan PO 45325082).
  → Saat mencocokkan baris invoice ke PL, WAJIB cocokkan kombinasi (pl_customer_po_no + pl_item_no), bukan hanya pl_item_no.
  → DILARANG KERAS menjumlahkan blok PL dari PO yang BERBEDA ke baris invoice yang sama.
  Contoh konkret:
    - Invoice item 4 (PO 45325077, MD-C400, 791 PC): hanya gabungkan PL "262-276" (PO 45325077) + "277-277" (PO 45325077) → 16 carton.
    - Invoice item 44 (PO 45325086, MD-C400, 294 PC): hanya gabungkan PL "2338-2342" (PO 45325086) + "2343-2343" (PO 45325086) → 6 carton.
    SALAH: mencampur "262-276" + "277-277" + "2338-2342" + "2343-2343" → 22 carton (double-count antar PO).

1. pl_customer_po_no
   - Ambil customer PO number dari angka yang muncul setelah "PACKING NO" pada line pertama blok item.
   - Nilai yang diambil adalah angka PO-nya saja.
   - Contoh:
     - "1-1 45324574 @38PR ..." -> pl_customer_po_no = "45324574"
     - "2-253 45325077 @50PC ..." -> pl_customer_po_no = "45325077"
   - Jangan ambil:
     - packing range
     - part number
     - quantity
     - invoice no.
     - ref no.

2. pl_item_no
   - Ambil part number item dari line kedua blok item, yaitu line alphanumeric sebelum description.
   - Pada vendor AURIGA, part number muncul jelas setelah line packing range.
   - Jika part number terpotong ke beberapa line, gabungkan menjadi satu string utuh.
   - Contoh:
     - "BRLTTJL510TS01"
     - "BRKTTMDM280F08"
     - "BRKTTHDM280LR001"
   - Jangan ambil:
     - packing range seperti "1-1" atau "254-260"
     - customer PO
     - quantity
     - weight
     - volume

3. pl_description
   - Ambil deskripsi barang setelah line part number di blok description.
   - Gabungkan seluruh line description item sampai sebelum item berikutnya.
   - Jika satu logical item terpecah ke beberapa packing rows tetapi part number, PO, dan description sama, gunakan satu description utuh saja.
   - Jangan masukkan:
     - part number
     - packing range
     - customer PO
     - quantity
     - net weight
     - gross weight
     - measure
   - Contoh hasil:
     - "BRAKE LEVER; TEKTRO; JL-510TS;BLACK/SILVER LEVER;ALLOY BRACKET/ALLOY LEVER,LEFT/RIGHT,4 FINGERS,FOR LINEAR PULL BRAKES,FOR TWIST/REV OSHIFTER W/ TEKTRO LOGO"
     - "BRAKE SET; TEKTRO; MD-C400 (MIRA);BRIGHT BLACK,MECHANICAL DISK BRAKE,ALLOY,W/O ROTOR,ORGANIC COMPOUND PAD,W/O ADAPTOR"

4. pl_quantity
   - Ambil nilai quantity TOTAL dari BARIS KE-2 (BARIS TOTAL) setiap blok. JANGAN dari baris ke-1 (per-carton rate).
   - Ambil angka numeriknya saja (tanpa unit).
   - Jika satu logical item terpecah ke beberapa packing rows DENGAN PO + part number yang sama, jumlahkan nilai BARIS KE-2 dari tiap blok.
   - Contoh:
     - Blok "1-1": baris ke-2 "@38PR" → pl_quantity = 38 (untuk range 1 carton, baris ke-1 dan ke-2 nilainya identik).
     - Blok "2-253": baris ke-1 "@50PC" (per-carton, ABAIKAN), baris ke-2 "@12600PC" → pl_quantity = 12600.
     - Blok "254-260" + "261-261" (PO+item sama): baris ke-2 blok 1 "@350PC" + baris ke-2 blok 2 "@3PC" → pl_quantity = 353.
     - Blok "278-282" + "283-283" (PO+item sama, HD-R285 RR): baris ke-2 blok 1 "@125PC" + baris ke-2 blok 2 "@5PC" → pl_quantity = 130.

5. pl_package_unit
   - pl_package_unit hanya boleh diambil dari bukti package, bukan dari quantity unit.
   - Canonical value yang diperbolehkan:
     ["CT", "null"]
   - Pada packing list AURIGA, "PACKING NO" menunjukkan range nomor package / carton.
   - Maka untuk row yang valid pada packing list AURIGA:
     pl_package_unit = "CT"
   - Jangan ambil:
     - PR
     - PC
     - SET
     sebagai pl_package_unit.

6. pl_package_count
   - SATU-SATUNYA SUMBER nilai pl_package_count adalah ARITMATIKA RANGE pada kolom "PACKING NO".
   - Rumus: pl_package_count = (angka akhir range) − (angka awal range) + 1. Inclusive.
   - Contoh:
     - "1-1"     → 1 − 1 + 1 = 1
     - "2-253"   → 253 − 2 + 1 = 252
     - "254-260" → 260 − 254 + 1 = 7
     - "278-282" → 282 − 278 + 1 = 5
     - "571-677" → 677 − 571 + 1 = 107
     - "678-678" → 678 − 678 + 1 = 1
   - Jika satu logical item terpecah ke beberapa packing rows DENGAN PO YANG SAMA DAN PART NUMBER YANG SAMA, jumlahkan seluruh package_count blok-bloknya.
   - Contoh:
     - "254-260" + "261-261" (keduanya PO 45325077, item BRKTTMDC510R01) → 7 + 1 = 8
     - "278-282" + "283-283" (keduanya PO 45325078, item BRKTTHDR285RR001) → 5 + 1 = 6
     - "571-677" + "678-678" (keduanya PO 45325079, item BRXTTTR180018003) → 107 + 1 = 108
   - DILARANG KERAS:
     - Menurunkan pl_package_count dari pl_quantity / per-carton rate (mis. 130 / 5 = 26 → SALAH). Selalu pakai aritmatika range.
     - Mengambil per-carton rate (mis. "@50PC", "@25PC", "@5PC") sebagai pl_package_count.
     - Menjumlahkan range carton dari PO yang BERBEDA, atau dari part number yang BERBEDA (mis. JANGAN gabung HD-R285 RR + HD-R285 LF; mereka adalah dua item invoice berbeda dengan kode part berbeda).

7. pl_nw
   - Ambil dari kolom "NET WEIGHT" pada BARIS KE-2 (BARIS TOTAL) setiap blok. JANGAN dari baris ke-1 (per-carton).
   - Nilai harus numeric saja. Hapus suffix unit seperti KG.
   - Jika satu logical item terpecah ke beberapa rows (PO + part number sama), jumlahkan nilai BARIS KE-2 dari tiap blok.
   - Contoh:
     - Blok "2-253": baris ke-1 "@10.078KG" (per-carton, ABAIKAN), baris ke-2 "@2539.656KG" → 2539.656.
     - Blok "1-1": baris ke-2 "@7.174KG" → 7.174.
     - Blok "278-282" + "283-283" (HD-R285 RR): baris ke-2 "@38.650KG" + baris ke-2 "@1.546KG" → pl_nw = 40.196.

8. pl_gw
   - Ambil dari kolom "GROSS WEIGHT" pada BARIS KE-2 (BARIS TOTAL) setiap blok. JANGAN dari baris ke-1 (per-carton).
   - Nilai harus numeric saja. Hapus suffix unit seperti KG.
   - Jika satu logical item terpecah ke beberapa rows (PO + part number sama), jumlahkan nilai BARIS KE-2 dari tiap blok.
   - Contoh:
     - Blok "2-253": baris ke-1 "@11.066KG" (per-carton, ABAIKAN), baris ke-2 "@2788.632KG" → 2788.632.
     - Blok "278-282" + "283-283" (HD-R285 RR): baris ke-2 "@49.550KG" + baris ke-2 "@1.866KG" → pl_gw = 51.416.

9. pl_volume
   - Ambil dari kolom "MEASURE" pada BARIS KE-2 (BARIS TOTAL) setiap blok. JANGAN dari baris ke-1 (per-carton).
   - Nilai harus numeric saja.
   - Jika satu logical item terpecah ke beberapa rows (PO + part number sama), jumlahkan nilai BARIS KE-2 dari tiap blok.
   - Contoh:
     - Blok "2-253": baris ke-1 "@0.024" (per-carton, ABAIKAN), baris ke-2 "@6.048" → 6.048.
     - Blok "278-282" + "283-283" (HD-R285 RR): baris ke-2 "@0.335" + baris ke-2 "@0.012" → pl_volume = 0.347.


BILL OF LADING (BL)

Struktur umum BL AURIGA:
- Dokumen berjudul "BILL OF LADING".
- Deskripsi barang berada pada area goods / marks & numbers.
- Pada sampel AURIGA, terdapat line-line goods seperti:
  - V-BRAKE SET:8714.94
  - BRAKE LEVER : 8714.94
  - BRAKE ROTOR : 8714.94
  - BRAKE SET:8714.94
  - BRAKE PART : 8714.94
- "BICYCLE PARTS" adalah grouping umum shipment, bukan item description final yang perlu diambil sendiri.
- "P/O NO." pada BL bukan field BL yang diminta di sini.

1. bl_description
   - Ambil hanya deskripsi barang per line pada BL.
   - Ambil teks di sebelah kiri sebelum ":" yang berpasangan dengan HS code.
   - Jika ada spasi / koma penutup berlebih sebelum titik dua, buang karakter penutup yang tidak perlu.
   - Jika deskripsi terpotong ke lebih dari satu line, gabungkan menjadi satu string utuh.
   - Contoh:
     - "V-BRAKE SET:8714.94" -> bl_description = "V-BRAKE SET"
     - "BRAKE LEVER : 8714.94" -> bl_description = "BRAKE LEVER"
     - "BRAKE PART : 8714.94" -> bl_description = "BRAKE PART"
   - Jangan ambil:
     - "BICYCLE PARTS"
     - P/O NO.
     - MADE IN CHINA
     - total package 2414 CTN
     - gross weight
     - CBM
     - vessel / freight terms / container info

2. bl_hs_code
   - Ambil nilai di sebelah kanan setelah ":" pada line goods tersebut.
   - Hapus spasi berlebih.
   - Contoh:
     - "V-BRAKE SET:8714.94" -> bl_hs_code = "8714.94"
     - "BRAKE LEVER : 8714.94" -> bl_hs_code = "8714.94"

Catatan tambahan BL:
- Pada vendor AURIGA, BL menuliskan family description barang yang lebih ringkas dibanding invoice / packing list.
- Karena itu, saat matching BL ke invoice/PL:
  - jangan memaksa full part number harus sama persis
  - cocokkan berdasarkan family / stem description yang sama
- Contoh kecocokan family:
  - BL "BRAKE LEVER" dapat cocok ke item invoice/PL yang description-nya brake lever
  - BL "BRAKE ROTOR" dapat cocok ke item invoice/PL yang description-nya brake rotor
  - BL "BRAKE PART" dapat cocok ke item invoice/PL yang description-nya brake part


CERTIFICATE OF ORIGIN (COO)

Struktur umum COO AURIGA:
- Dokumen COO vendor AURIGA menggunakan format RCEP / Form RCEP.
- Tabel item-level COO berisi kolom:
  Item number | Marks and numbers on packages | Number and kind of packages; and description of goods | HS Code | Origin Conferring Criterion | RCEP Country of Origin | Quantity (Gross weight or other measurement), and value (FOB) where RVC is applied | Invoice number(s) and date of invoice(s)
- Pada sampel AURIGA:
  - item number tercetak jelas
  - description item-level tercetak jelas
  - HS code tercetak jelas
  - criterion tercetak jelas seperti PE / RVC
  - quantity sering menempel dengan unit, mis. 38SETS
  - gross weight muncul sebagai "...KGS G.W."
  - amount kadang muncul sebagai "CNY:xxxx" terutama saat RVC
  - invoice number/date tercetak, tetapi customer PO tidak tercetak item-level secara jelas

1. coo_seq
   - Ambil dari kolom "Item number".
   - Nilai numeric.
   - Item number tercetak jelas seperti:
     - 1
     - 2
     - 3
     - ...

2. coo_mark_number
   - Ambil dari "Marks and numbers on packages" HANYA jika ada mark item-level yang spesifik.
   - Jika kolom kosong, tidak terisi, atau tidak ada mark yang jelas untuk row tersebut:
     coo_mark_number = "null"
   - Jangan mengisi generic text dokumen atau mark shipment-level.

3. coo_description
   - Ambil description of goods item-level dari COO.
   - Gabungkan seluruh line description item yang memang milik row tersebut.
   - Jangan masukkan:
     - item number
     - marks
     - HS code
     - quantity
     - gross weight
     - amount / FOB / CNY
     - origin criterion
     - invoice number/date
     - customer PO
   - Contoh hasil:
     - "BRAKE LEVER; TEKTRO; JL-510TS;BLACK/SILVER LEVER;ALLOY BRACKET/ALLOY LEVER,LEFT/RIGHT,4 FINGERS,FOR LINEAR PULL BRAKES,FOR TWIST/REV OSHIFTER W/ TEKTRO LOGO"
     - "BRAKE SET;TEKTRO;MD-M280;BRIGHT BLACK;MECHANICAL ALLOY,W/O ROTOR,METAL PAD (W/O FIN),W/O ADAPTOR"

4. coo_hs_code
   - Ambil dari kolom HS code item-level pada COO.
   - Simpan sebagai string.
   - Contoh:
     - "8714.94"
     - "9029.90"

5. coo_quantity
   - Ambil quantity item-level dari COO.
   - Ambil angka numeriknya saja.
   - Quantity biasanya berada di awal isi kolom quantity/value.
   - Contoh:
     - "38SETS" -> 38
     - "12600SETS" -> 12600
     - "133SETS" -> 133

6. coo_unit
   - Ambil unit quantity yang menempel pada coo_quantity.
   - Contoh:
     - "38SETS" -> "SETS"
     - "133SETS" -> "SETS"
   - Jika unit tidak ada atau tidak jelas:
     coo_unit = "null"

7. coo_package_count
   - Hanya isi jika COO benar-benar mencantumkan package count per item secara jelas dan item-level.
   - Pada sampel AURIGA, package count item-level tidak tercetak jelas di COO.
   - Karena itu:
     coo_package_count = null

8. coo_package_unit
   - Hanya isi jika COO benar-benar mencantumkan package unit per item secara jelas dan item-level.
   - Pada sampel AURIGA, package unit item-level tidak tercetak jelas di COO.
   - Karena itu:
     coo_package_unit = "null"

9. coo_gw
   - Ambil gross weight item-level dari COO.
   - Ambil angka numeriknya saja dari text seperti "...KGS G.W."
   - Contoh:
     - "7.97KGS G.W." -> 7.97
     - "2788.63KGS G.W." -> 2788.63
     - "0.92KGS G.W." -> 0.92
   - Jangan ambil shipment-level gross weight.

10. coo_amount
   - Ambil value / amount item-level dari COO jika tercetak jelas.
   - Pada sampel AURIGA, amount biasanya muncul sebagai "CNY:xxxx".
   - Ambil angka numeriknya saja.
   - Contoh:
     - "CNY:226800.00" -> 226800
     - "CNY:19323.22" -> 19323.22
   - Jika row COO tidak mencantumkan amount item-level:
     coo_amount = null
   - Jangan ambil amount dari invoice untuk mengisi coo_amount.

11. coo_criteria
   - Ambil dari kolom origin criterion / origin conferring criterion pada COO.
   - Contoh value yang mungkin muncul:
     - PE
     - RVC
   - Jika tidak ada criterion yang jelas:
     coo_criteria = "null"

12. coo_customer_po_no
   - Field ini hanya diisi jika COO secara eksplisit mencantumkan customer PO number item-level atau row-level.
   - Pada sampel AURIGA, yang tercetak adalah invoice number/date, bukan customer PO.
   - Karena itu:
     coo_customer_po_no = "null"
   - Jangan ambil:
     - invoice no.
     - invoice date
     - PO dari invoice
     - PO dari packing list
     untuk mengisi field ini.
"""