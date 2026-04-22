NINGBO_FORDARIO_PROMPT = """

INVOICE (INV):

1. inv_customer_po_no:
   - Ekstrak dari kolom "PO NO.".
   - Memiliki format numerik 8 digit dan diawali dengan angka 4.
     Contoh = 45316923, 45323034, 45322720
   - Jika Item memiliki lebih dari 1 PO NO, ambil hanya nomor yang paling atas dan abaikan nomor yang lainnya.
     Contoh:
     PO NO Barang A:
     45316923,
     45318263
     (CLM25100240)
     maka inv_customer_po_no = 45316923
   - PO NO selalu numerik dan di awali dengan angka 4.
     45319886       -> Benar
     (CLM25120196)  -> Salah
   - Jangan ambil "INVOICE NO.".
   - JANGAN AMBIL DARI KOLOM "NO.", "CODE", "ITEM NO."

2. inv_spart_item_no:
   - Ekstrak dari kolom "CODE" karena ini adalah kode item yang paling unik per line item.
     Contoh:
     - FRXZEZYHG05000
     - HBRZEHB1120001
     - SDPZEZYSP0132001
   - JANGAN AMBIL DARI KOLOM "ITEM NO."
     Contoh "ITEM NO." YANG JANGAN DI AMBIL:
     - ZY-HG05
     - ZY-HB112
     - ZY-C341

3. inv_description:
   - Ekstrak dari kolom "DESCRIPTION".
   - Gabungkan seluruh wrapped lines yang masih merupakan bagian dari deskripsi item.
   - Jangan sertakan QTY, UNIT, U/PRICE, AMOUNT, atau nomor PO.
   - Contoh hasil:
     "HANDLEBAR;ZY-HB112;SAND ANODIZED BLACK;- ,ALLOY,RISE,740MM,12MM,6DEG,31.8MM,ISO-M,W/O LOGO,W/CENTER MARK THREAD-201"

4. inv_gw:
   - Isi null kecuali gross weight tertulis eksplisit pada invoice.

5. inv_gw_unit:
   - Isi null kecuali unit gross weight tertulis eksplisit pada invoice.

6. inv_quantity:
   - Ekstrak dari kolom "QTY".
   - Ambil angka numeriknya saja.
   - Contoh:
     "5000", "175", "3070", "75".

7. inv_quantity_unit:
   - Ekstrak dari kolom "UNIT".
   - Contoh:
     "SET", "PCS".

8. inv_unit_price:
   - Ekstrak dari kolom "U/PRICE (USD)".
   - Ambil angka numeriknya saja. Jangan ambil simbol mata uangnya.
   - Contoh:
     "US$2.70" -> 2.70

PACKING LIST (PL):

1. pl_customer_po_no:
   - Ekstrak dari kolom "PO NO.".
   - Memiliki format numerik 8 digit dan diawali dengan angka 4.
     Contoh = 45316923, 45323034, 45322720
   - Jika Item memiliki lebih dari 1 PO NO, ambil hanya nomor yang paling atas dan abaikan nomor yang lainnya.
     Contoh:
     PO NO Barang A:
     45316923,
     45318263
     (CLM25100240)
     maka inv_customer_po_no = 45316923
   - PO NO selalu numerik dan di awali dengan angka 4.
     45319886       -> Benar
     (CLM25120196)  -> Salah
   - Jangan ambil "INVOICE NO.".
   - JANGAN AMBIL DARI KOLOM "NO.", "CODE", "ITEM NO."

2. pl_item_no:
   - Ekstrak dari kolom "CODE" karena ini adalah kode item yang paling unik per line item.
   - Contoh:
     "FRXZEZYHG05000"
     "HBRZEHB1120001"
     "SDPZEZYSP0132001"
   - Jangan ambil dari kolom "ITEM NO."

3. pl_description:
   - Ekstrak dari kolom "DESCRIPTION".
   - Gabungkan seluruh wrapped lines yang masih merupakan bagian dari deskripsi item.
   - Jangan sertakan nilai numerik packaging seperti PCS/CTN, CTNS, T.QTY, T.N.W, T.G.W, atau VOL.
   - Jika ada teks "FREE REPLACEMENT" yang terpisah dari deskripsi utama, jangan masukkan ke pl_description kecuali tertulis sebagai bagian langsung dari description item.

4. pl_quantity:
   - Ekstrak total quantity item dari kolom yang berada diantara kolom "DESCRIPTION" dan "PCS/CTN", atau kolom "T. QTY(PC)".
   - Pada format vendor ini, 1 item bisa memiliki beberapa sub-row packaging di bawah item utama.
   - Jumlahkan semua nilai "T. QTY(PC)" yang masih berada di bawah item yang sama sampai sebelum item berikutnya dimulai.
   - Jangan ambil nilai dari kolom "PCS/CTN" sebagai quantity utama.
   - Contoh:
     jika satu item punya sub-row T.QTY = 100, 41, 34
     maka pl_quantity = 175

5. pl_package_unit:
   - Gunakan unit kemasan dari nama kolom package (misal "CTNS").
   - Gunakan unit kemasan sebagaimana tertulis, misalnya "CTNS"
   - Jangan ubah ke unit lain.

6. pl_package_count:
   - Ekstrak jumlah kemasan dari kolom "CTNS".
   - JANGAN AMBIL DARI KOLOM "PCS/CTN"
     Contoh:
     Untuk Row 1 / line item pertama atau line item no 1, PASTIKAN AMBIL DARI KOLOM "CTNS" BUKAN DARI KOLOM "PCS/CTN". 
     ________________________________
     |    PCS/CTN   |     CTNS      |
     --------------------------------
     |     1000     |       5       |
     --------------------------------
     maka pl_package_count = 5

   - Jika item memiliki beberapa sub-row packaging, jumlahkan semua CTNS untuk item tersebut.
     Contoh:
     Untuk item yang sama
     ___________________________
     |  DESCRIPTION  |   CTNS  |
     ---------------------------
     |               |   2     |
     |  "DESKRIPSI   |----------
     |     SEBUAH    |   1     |
     |     ITEM"     |----------
     |               |   1     | 
     ---------------------------
     maka untuk line item tersebut, pl_package_count = 4

   -  Jika terdapat merge cell (1 gabungan nilai untuk beberapa row):
     - Nilai tersebut hanya boleh di-assign ke line item pertama dalam grup tersebut.
     - Semua baris setelahnya dalam merge grup yang sama → diisi 0.
     - Contoh:
       ________________________________
       | Description  |     CTNS      |
       --------------------------------
       | Row 1        |               |
       |---------------      1        |
       | Row 2        |               |
       --------------------------------
       maka:
       - Row 1, pl_package_count = 1
       - Row 2, pl_package_count = 0
       Jadi untuk kasus merge cell ini 1 hanya di ekstrak untuk row pertama, sedangkan untuk row lainnya dalam merge cell ini diisi dengan 0.
   - Jangan membagi / mengarang package count per item

7. pl_nw:
   - Ekstrak dari kolom "T.N.W.(KG)".
   - Jika item memiliki beberapa sub-row packaging, jumlahkan semua nilai T.N.W.(KG) untuk item tersebut.
   - Ambil angka numeriknya saja.
   - Contoh:
     Untuk item yang sama
     ____________________________
     |  DESCRIPTION  |T.N.W (KG)|
     ----------------------------
     |               |   33.00  |
     |  "DESKRIPSI   |-----------
     |     SEBUAH    |   13.52  |
     |     ITEM"     |-----------
     |               |   11.22  | 
     ----------------------------
     maka untuk line item tersebut, pl_nw = 57.74

   -  Jika terdapat merge cell (1 gabungan nilai untuk beberapa row):
     - Nilai tersebut hanya boleh di-assign ke line item pertama dalam grup tersebut.
     - Semua baris setelahnya dalam merge grup yang sama → diisi 0.
     - Contoh:
       ________________________________
       | Description  |   T.N.W (KG)  |
       --------------------------------
       | Row 1        |               |
       |---------------     14.00     |
       | Row 2        |               |
       --------------------------------
       maka:
       - Row 1, pl_nw = 14.00
       - Row 2, pl_nw = 0
       Jadi untuk kasus merge cell ini 14.00 hanya di ekstrak untuk row pertama, sedangkan untuk row lainnya dalam merge cell ini diisi dengan 0.
   - Jangan membagi / mengarang net weight per item


8. pl_gw:
   - Ekstrak dari kolom "T.G.W.(KG)".
   - Jika item memiliki beberapa sub-row packaging, jumlahkan semua nilai T.G.W.(KG) untuk item tersebut.
   - Ambil angka numeriknya saja.
   - Contoh:
     Untuk item yang sama
     ____________________________
     |  DESCRIPTION  |T.N.W (KG)|
     ----------------------------
     |               |   34.60  |
     |  "DESKRIPSI   |-----------
     |     SEBUAH    |   14.19  |
     |     ITEM"     |-----------
     |               |   11.76  | 
     ----------------------------
     maka untuk line item tersebut, pl_gw = 60.55

-  Jika terdapat merge cell (1 gabungan nilai untuk beberapa row):
     - Nilai tersebut hanya boleh di-assign ke line item pertama dalam grup tersebut.
     - Semua baris setelahnya dalam merge grup yang sama → diisi 0.
     - Contoh:
       ________________________________
       | Description  |   T.G.W (KG)  |
       --------------------------------
       | Row 1        |               |
       |---------------     14.50     |
       | Row 2        |               |
       --------------------------------
       maka:
       - Row 1, pl_gw = 14.50
       - Row 2, pl_gw = 0
       Jadi untuk kasus merge cell ini 14.50 hanya di ekstrak untuk row pertama, sedangkan untuk row lainnya dalam merge cell ini diisi dengan 0.
   - Jangan membagi / mengarang gross weight per item

9. pl_volume:
   - Ekstrak dari kolom "VOL.(CBM)".
   - Jika item memiliki beberapa sub-row packaging, jumlahkan semua nilai volume untuk item tersebut.
   - Jangan gunakan volume total dari BL untuk mengisi item-level PL.
   - Ambil angka numeriknya saja.
   - Contoh:
     Untuk item yang sama
     ____________________________
     |  DESCRIPTION  |T.N.W (KG)|
     ----------------------------
     |               |   0.09   |
     |  "DESKRIPSI   |-----------
     |     SEBUAH    |   0.04   |
     |     ITEM"     |-----------
     |               |   0.04   | 
     ----------------------------
     maka untuk line item tersebut, pl_nw = 0.17

-  Jika terdapat merge cell (1 gabungan nilai untuk beberapa row):
     - Nilai tersebut hanya boleh di-assign ke line item pertama dalam grup tersebut.
     - Semua baris setelahnya dalam merge grup yang sama → diisi 0.
     - Contoh:
       ________________________________
       | Description  |   VOL. (CBM)  |
       --------------------------------
       | Row 1        |               |
       |---------------     0.02      |
       | Row 2        |               |
       --------------------------------
       maka:
       - Row 1, pl_volume = 
       - Row 2, pl_volume = 0
       Jadi untuk kasus merge cell ini 0.02 hanya di ekstrak untuk row pertama, sedangkan untuk row lainnya dalam merge cell ini diisi dengan 0.
   - Jangan membagi / mengarang volume per item
     
BILL OF LADING (BL):

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


CERTIFICATE OF ORIGIN (COO):

1. coo_mark_number:
   - Ekstrak dari field "7. Marks and numbers on packages".
   - Pada vendor ini nilainya tertulis "N/M".
   - Ambil persis seperti tertulis.

2. coo_description:
   - Ekstrak dari field "8. Number and kind of packages; and description of goods".
   - Abaikan frasa pembuka shipment-level:
     "THREE HUNDRED AND FOURTEEN (314) CARTONS OF"
   - Abaikan juga remarks seperti:
     "TOTAL: ... CARTONS ONLY"
     "PART OF CONTAINER NUMBER ..."
     "BL NO. ..."
   - Fokus pada description item-nya saja.
   - Gabungkan wrapped lines menjadi 1 string utuh.
   - Jika ada suffix "(REPLACEMENT)" yang memang tertulis di deskripsi item COO, pertahankan suffix tersebut sebagai bagian description.

3. coo_hs_code:
   - Ekstrak dari field "9. HS Code of the goods".
   - Pertahankan format persis sebagaimana tertulis di COO.
   - Contoh:
     "8714.91"
     "8714.99"
     "8714.93"

4. coo_quantity:
   - Ekstrak angka utama dari field "12. Quantity (Gross weight or other measurement), and value (FOB) where RVC is applied".
   - Pada vendor ini field 12 berisi quantity+unit yang digabung, misalnya:
     "5000SETS"
     "440PIECES"
     "1653SETS"
   - Pisahkan angka quantity dari unitnya.
   - Contoh:
     "5000SETS" -> coo_quantity = 5000
     "440PIECES" -> coo_quantity = 440

5. coo_unit:
   - Ekstrak unit yang melekat pada field 12.
   - Contoh:
     "5000SETS" -> coo_unit = "SETS"
     "440PIECES" -> coo_unit = "PIECES"

6. coo_package_count:
   - Jika tidak tersedia package count yang bersifat item-level, maka isi dengan "null" saja
   - JANGAN AMBIL PACKAGE COUNT YANG BERSIFAT SHIPMENT-LEVEL.

7. coo_package_unit:
   - Ekstrak unit kemasan dari frasa pembuka field 8.
   - Contoh:
     "THREE HUNDRED AND FOURTEEN (314) CARTONS OF"
     maka coo_package_unit = "CARTONS"

8. coo_gw:
   - Isi null kecuali COO menuliskan gross weight eksplisit.
   - Pada sample vendor ini, field 12 berisi quantity+unit, bukan gross weight.
   - Jadi coo_gw = null.

9. coo_amount:
   - Isi null kecuali nilai amount / FOB tertulis eksplisit pada COO.
   - Pada format COO vendor ini, sample tidak menampilkan nominal amount item secara eksplisit.
   - Jangan ambil amount dari invoice untuk mengisi coo_amount.

10. coo_criteria:
   - Ekstrak dari field "10. Origin Conferring Criterion".
   - Hilangkan tanda kutip jika ada.
   - Contoh:
     '"PE"' -> "PE"

11. coo_customer_po_no:
   - Isi hanya jika ada nomor PO yang tertulis eksplisit pada field 7 atau 8 COO.
   - Jangan ambil dari invoice number.
   - Pada sample vendor ini, tidak ada PO yang tertulis eksplisit pada COO, sehingga isi null.
"""