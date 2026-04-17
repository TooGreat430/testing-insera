NINGBO_JULONG_PROMPT = """"

INVOICE (INV):

1. inv_customer_po_no:
   - Ekstrak dari baris PO number yang berdiri sendiri di atas item.
   - Pada format vendor ini, PO tidak ada di kolom tetap, tetapi muncul sebagai angka tersendiri sebelum baris item.
   - Contoh:
     "45323438"
     "45324180"
     "45324625"
   - Jika 1 PO menaungi beberapa item berikutnya dan PO tidak diulang, maka semua item berikutnya mewarisi PO terakhir sampai ada PO baru.

2. inv_spart_item_no:
   - Ekstrak dari kolom "MODEL NO." kode item panjang alfanumerik.
   - Jangan ambil dari kolom "NO."
   - Contoh:
     "FP-HW-20"
     "FP-B902E-2NL"
     "FP-H885E1"

3. inv_description:
   - Ekstrak deskripsi item dari kolom "DESCRIPTION OF GOODS"
   - Gabungkan seluruh wrapped lines yang masih merupakan bagian dari deskripsi item.
   - Jangan sertakan Model No, PO No, quantity, unit price, atau amount.
   - Contoh hasil:
     PART OF HEAD PART ; FEIMIN ; HW-20 FLAT CAP ; SAND BLAST BLACK ; ALLOY 28.6, BLACK BOLT, W/STAR NUT,W/O LOGO"

4. inv_gw:
   - Isi null kecuali gross weight tertulis eksplisit pada invoice.

5. inv_gw_unit:
   - Isi null kecuali unit gross weight tertulis eksplisit pada invoice.

6. inv_quantity:
   - Ekstrak dari kolom "QUANTITY".
   - Contoh:
     "5000", "200", "3600", "582", "1470".

7. inv_quantity_unit:
   - Ekstrak unit quantity setelah angka quantity dari kolom "QUANTITY".
   - Contoh:
     "SETS", "PRS", "PCS".

8. inv_unit_price:
   - Ekstrak dari kolom "UNIT PRICE IN US$".
   - Ambil angka numeriknya saja.
   - Contoh:
     "US$0.260" -> 0.260
     "US$1.990" -> 1.990

PACKING LIST (PL):

Pada format vendor ini, satu row item memiliki pola:
"<carton_count> <item_no> <description> @ <pcs_per_ctn> / <total_qty> <unit> @ <nw_per_ctn> / <total_nw> KGS @ <gw_per_ctn> / <total_gw> KGS <volume>"

1. pl_customer_po_no:
   - Ekstrak dari sub kolom paling kiri dari kolom "DESCRIPTION OF GOODS AND QUANTITY".
   - Ekstrak yang merupakan kode numerik 8 digit yang diawali dengan angka 4 dan angkanya di bold.
   - Contoh:
     "45323438"
     "45324180"
     "45324625"
   - Jika beberapa baris item berikutnya tidak mengulang PO, maka item-item tersebut mewarisi PO terakhir sampai ada PO baru.

2. pl_item_no:
   - Ekstrak dari sub kolom paling kiri dari kolom "DESCRIPTION OF GOODS AND QUANTITY".
   - Ekstrak kode model pendek alfanumerik.
   - Jangan esktrak dari kolom "PACKAGE".
   - Contoh:
     "FP-HW-20"
     "FP-B902E-2NL"
     "FP-803"
     "FP-H868JX"

3. pl_description:
   - Ekstrak dari sub kolom tengah dari kolom "DESCRIPTION OF GOODS AND QUANTITY"
   - Ekstrak teks deskripsi setelah pl_item_no sampai sebelum pola kuantitas/berat/volume.
   - Jangan sertakan angka package count di awal.
   - Jangan sertakan pola numerik setelah simbol "@", seperti:
     "@ 300 / 4800 SETS @ 8.40 / 134.40 KGS @ 8.68 / 138.88 KGS 0.16"
   - Abaikan "BICYCLE PARTS"
   - Contoh hasil:
     "PART OF HEAD PART ; FEIMIN ; HW-20 FLAT CAP ; SAND BLAST BLACK ; ALLOY 28.6, BLACK BOLT, W/STAR NUT,W/O LOGO"

4. pl_quantity:
   - Ekstrak dari sub kolom paling kanan dari kolom "DESCRIPTION OF GOODS AND QUANTITY"
   - Ambil total quantity setelah slash pertama pada segmen quantity.
   - Contoh:
     "@ 300 / 4800 SETS" -> pl_quantity = 4800
   - Jika item yang sama muncul di beberapa row, jumlahkan semua total_qty untuk item tersebut.
   - Contoh:
     4800 + 200 = 5000.

5. pl_package_unit:
   - Cek pada footer tabel yaitu kolom kedua dari kiri, esktrak unit packagenya.
   
   - Contoh:
     Footer tabel
     |TOTAL:   |   673CTNS/49105PRS/SETS   |   9809.93 KGS |   10147.67 KGS    |   12.43   |
     maka, pl_package_unit = CTNS

   - Gunakan unit kemasan sebagaimana tertulis, misalnya "CTNS"
   - Jangan ubah ke unit lain.

6. pl_package_count:
   - Ekstrak dari kolom "PACKAGE"
   - Jika item yang sama muncul di beberapa row, jumlahkan semua package count.
   - Contoh:
     16 + 1 = 17.

7. pl_nw:
   - Ekstrak total net weight setelah slash pada kolom "NET WEIGHT".
   - Contoh:
     "@ 8.40 / 134.40 KGS" -> pl_nw = 134.40
   - Jika item yang sama muncul di beberapa row, jumlahkan semua total_nw.
   - Contoh:
     134.40 + 5.60 = 140.00

8. pl_gw:
   - Ekstrak total gross weight setelah slash pada kolom "GROSS WEIGHT"
   - Contoh:
     "@ 8.68 / 138.88 KGS" -> pl_gw = 138.88
   - Jika item yang sama muncul di beberapa row, jumlahkan semua total_gw.
   - Contoh:
     138.88 + 5.79 = 144.67

9. pl_volume:
   - Ekstrak total volume dari kolom "MEASUREMENTS CBM"
   - Jika item yang sama muncul di beberapa row, jumlahkan semua volume.
   - Contoh:
     0.16 + 0.01 = 0.17


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
   - Jika field 7 kosong / tidak terisi jelas pada item, isi null.
   - Jangan mengambil "PO. NO.", "MATERIAL CODE", atau "C/ NO." dari remarks sebagai mark number.

2. coo_description:
   - Ekstrak dari field "8. Number and kind of packages; and description of goods".
   - Hapus frasa pembuka package count di awal description, misalnya:
     "SEVENTEEN (17) CARTONS OF"
     "ONE (1) CARTON OF"
     "SEVENTY-TWO (72) CARTONS OF"
   - Sisakan hanya deskripsi barang.
   - Contoh:
     "PART OF HEAD PART; FEIMIN; FP-HW-20 FLAT CAP; SAND BLAST BLACK ;"
     "BB PART; FEIMIN; FP-B902E; BLACK;"
     "PEDAL; FEIMIN; FP-803; BLACK ;"
   - Abaikan remarks di bawah seperti:
     "BL:SHGS26010030A"
     "CONTAINER NO:EGHU9883547"
     "PO. NO.:"
     "MATERIAL CODE:"
     "C/ NO.:"
     "MADE IN CHINA"

3. coo_hs_code:
   - Ekstrak dari field "9. HS Code of the goods".
   - Pertahankan format persis seperti tertulis.
   - Contoh:
     "8714.91"
     "8714.99"
     "8714.96"

4. coo_quantity:
   - Pada format vendor ini, field 12 berisi quantity dan gross weight dalam 2 baris bertumpuk.
   - Ambil quantity dari bagian pertama.
   - Contoh:
     "5000SETS" + "144.67KGS G.W." -> coo_quantity = 5000
     "3600PAIRS" + "1123.2KGS G.W." -> coo_quantity = 3600
     "200PIECES" + "3.48KGS G.W." -> coo_quantity = 200

5. coo_unit:
   - Ambil unit yang melekat pada quantity di field 12.
   - Contoh:
     "5000SETS" -> "SETS"
     "3600PAIRS" -> "PAIRS"
     "200PIECES" -> "PIECES"

6. coo_package_count:
   - Ambil angka numerik dari frasa pembuka package count di awal field 8.
   - Contoh:
     "SEVENTEEN (17) CARTONS OF ..." -> 17
     "ONE (1) CARTON OF ..." -> 1
     "SEVENTY-TWO (72) CARTONS OF ..." -> 72

7. coo_package_unit:
   - Ambil unit package dari frasa pembuka di awal field 8.
   - Jika tertulis "CARTONS", isi "CARTONS".
   - Jika tertulis "CARTON", isi "CARTON".

8. coo_gw:
   - Ambil gross weight dari bagian kedua field 12.
   - Contoh:
     "5000SETS" + "144.67KGS G.W." -> coo_gw = 144.67
     "3600PAIRS" + "1123.2KGS G.W." -> coo_gw = 1123.2
   - Ambil angka numeriknya saja.

9. coo_amount:
   - Isi null kecuali nilai FOB / amount tertulis eksplisit di COO.
   - Pada sample vendor ini, field 12 hanya menampilkan quantity dan gross weight, bukan amount.
   - Jangan ambil nilai dari invoice untuk mengisi coo_amount.

10. coo_criteria:
   - Ekstrak dari field "10. Origin Conferring Criterion".
   - Hilangkan tanda kutip jika ada.
   - Contoh:
     '"PE"' -> "PE"

11. coo_customer_po_no:
   - Isi hanya jika nomor PO tertulis eksplisit pada field 7 atau 8 COO.
   - Jangan ambil dari invoice number.
   - Jangan ambil dari remarks kosong seperti "PO. NO.:" tanpa value.
   - Jika tidak ada referensi PO yang jelas, isi null.
"""