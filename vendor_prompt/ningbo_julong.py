NINGBO_JULONG_PROMPT = """"

INVOICE (INV):

1. inv_customer_po_no:
   - Ekstrak dari baris PO number yang berdiri sendiri di atas item.
   - Jika 1 PO menaungi beberapa item berikutnya dan PO tidak diulang, maka semua item berikutnya mewarisi PO terakhir sampai ada PO baru.
      - Contoh:
                                  45324623
      PLASTIC WASHER;FEIMIN;-;BLACK;-,PLASTIC,ID:1-1/8"MM,OD:34MM,H10MM,W/O LOGO,-
      PLASTIC WASHER;FEIMIN;-;BLACK;-,PLASTIC,ID:1-1/8"MM,OD:34MM,H10MM,W/O LOGO,-
                                  45324624
      ALUMINIUM WASHER; -; -; SAND BLACK; ALLOY, ID:28.6MM,OD:33MM, H:5MM, W/O LOGO
      ALUMINIUM WASHER; -; -; SAND BLACK; ALLOY, ID:28.6MM,OD:33MM, H:5MM, W/O LOGO
      ALUMINIUM WASHER; -; -; SAND BLACK; ALLOY, ID:28.6MM,OD:33MM, H:5MM, W/O LOGO
      ALUMINIUM WASHER; -; -; SAND BLACK; ALLOY, ID:28.6MM,OD:33MM, H:5MM, W/O LOGO                      

      Maka untuk 2 line item teratas inv_customer_po_no = 45324623, karena po no 45324623 menaungi 2 item tersebut.
      Kemudian untuk 4 line item dibawahnya inv_customer_po_no = 45324624, karena po no 45324624 menaungi 4 item tersebut.

2. inv_spart_item_no:
   - Ekstrak dari kolom "NO." kode item panjang alfanumerik.
   - Jangan ambil dari kolom "MODEL NO."
   - Contoh:
     "HDWZZ286X10012"
     "HDWFP00001-R"
     "HDWZZ286X10010"

3. inv_description:
   - Ekstrak deskripsi item dari kolom "DESCRIPTION OF GOODS"
   - Gabungkan seluruh wrapped lines yang masih merupakan bagian dari deskripsi item.
   - ABAIKAN / JANGAN SERTAKAN "BICYCLE PARTS", PO No, quantity, unit price, atau amount.
   - ABAIKAN / JANGAN SERTAKAN "Model No." seperti contoh:
     FP-HW-20, FP-B902E-2NL, FP-H885E1
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
   - Jika beberapa baris item berikutnya tidak mengulang PO, maka item-item tersebut mewarisi PO terakhir sampai ada PO baru.
      - Contoh:
         45324623
        SPACER 10MM
        SPACER 10MM
         45324624
        FP-MH-S61 /5MM
        FP-MH-S61 /5MM
        FP-MH-S61 /5MM
        FP-MH-S61 /5MM

      Maka untuk 2 line item teratas inv_customer_po_no = 45324623, karena po no 45324623 menaungi 2 item tersebut.
      Kemudian untuk 4 line item dibawahnya inv_customer_po_no = 45324624, karena po no 45324624 menaungi 4 item tersebut.

2. pl_item_no:
   - Ekstrak dari sub kolom paling kiri dari kolom "DESCRIPTION OF GOODS AND QUANTITY".
   - Ekstrak kode model pendek alfanumerik.
   - Jangan esktrak dari kolom "PACKAGE".
   - Jangan ekstrak po no (kode numerik 8 digit yang diawali dengan angka 4 dan angkanya di bold)
     Contoh PO NO YANG TIDAK BOLEH DI EKSTRAK DI pl_item_no: 45323439, 45324623, 45324624, 45325590
   - Jika value pl_item_no berbentuk:
     FP-MH-S61 /5MM
     maka pl_item_no = FP-MH-S61
     ABAIKAN GARIS MIRING (/) DAN VALUE SETELAHNYA.

3. pl_description:
   - Ekstrak dari sub kolom tengah dari kolom "DESCRIPTION OF GOODS AND QUANTITY"
   - Ekstrak teks deskripsi setelah pl_item_no sampai sebelum pola kuantitas/berat/volume.
   - Jangan sertakan angka package count di awal.
   - Jangan sertakan pola numerik setelah simbol "@", seperti:
     "@ 300 / 4800 SETS @ 8.40 / 134.40 KGS @ 8.68 / 138.88 KGS 0.16"
   - ABAIKAN "BICYCLE PARTS" DAN NOMOR PO (45323439, 45324623, 45324624, DLL)
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
   - Field bl_description dan bl_hs_code merupakan SATU PAKET dan WAJIB selalu terisi (TIDAK BOLEH NULL).
   - Sumber data HANYA boleh dari dokumen Bill Of Lading (BL) saja, TIDAK BOLEH mengambil dari dokumen lain.

   =========================
   LOGIC MAPPING (BERURUTAN)
   =========================
   STEP 1 — Mapping berdasarkan inv_description:
   - Cari apakah inv_description MATCH dengan deskripsi item pada BL.
   - Jika ditemukan:
     - bl_description = description item pada BL yang sesuai
     - bl_hs_code = HS CODE yang terkait dengan bl_description tersebut

   STEP 2 — Jika TIDAK ditemukan di STEP 1, mapping berdasarkan inv_spart_item_no:
   - Pada deskripsi BL, identifikasi nomor spart item (biasanya berupa kode unik di akhir deskripsi).
     Contoh:
       FORK SUSPENSION GSFM3010APV00034 → spart item = GSFM3010APV00034
   - Jika inv_spart_item_no MATCH dengan spart item pada BL:
     - bl_description = description item pada BL yang mengandung spart item tersebut
     - bl_hs_code = HS CODE yang terkait

   STEP 3 — Jika STEP 1 dan STEP 2 TIDAK ditemukan:
   - Karena bl_description dan bl_hs_code TIDAK BOLEH NULL,
   - Maka PILIH SECARA ACAK (RANDOM) satu pasangan data dari item BL:
     - bl_description = salah satu description item dari BL
     - bl_hs_code = HS CODE yang sesuai dengan item tersebut
   - JANGAN MEMBUAT BL DESCRIPTION DAN BL HS CODE BARU YANG TIDAK ADA DI DOKUMEN BILL OF LADING (BL). GUNAKAN RANDOM ITEM YANG ADA SAJA DI DOKUMEN BILL OF LADING (BL).
     Contoh:
     DATA DI BL SEPERTI INI:
     FORK SUSPENSION GSFM3010APV00034  HS CODE: 8714.91
     FORK SUSPENSION GSFNEXDSV0000261  HS CODE: 8714.91
     FORK SUSPENSION GSFNEXE25DSV0830  HS CODE: 8714.91
     FORK SUSPENSION GSFNEXE25PDV0021  HS CODE: 8714.91
     FORK SUSPENSION GSFNVX30DSV00484  HS CODE: 8714.91
     
     JANGAN BUAT DATA BARU SEPERTI = FORK SUSPENSION GSFXCM32DSV00012, YANG TIDAK ADA PADA DOKUMEN BILL OF LADING SEBAGAI HASIL EKSTRAKSI DAN MAPPING.
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
       2. inv_spart_item_no (fallback)
       3. random BL item (last resort, WAJIB jika tidak match)

   =========================
   CONTOH
   =========================
   BL:
     - ALUMINIUM WASHER HS CODE: 7616.10
     - FORK SUSPENSION GSFM3010APV00034 HS CODE: 8714.91

   Case 1:
     inv_description = ALUMINIUM WASHER; -; -;SAND BLACK; ALLOY, ID:28.6MM,OD:33MM, H:10MM, W/O LOGO
     → MATCH STEP 1
     → bl_description = ALUMUNIUM WASHER
     → bl_hs_code = 7616.10

   Case 2:
     inv_spart_item_no = GSFM3010APV00034
     → MATCH STEP 2
     → bl_description = FORK SUSPENSION GSFM3010APV00034
     → bl_hs_code = 8714.91

   Case 3:
     inv_description & inv_spart_item_no tidak ada di BL
     → STEP 3 (RANDOM)
     → bl_description = FRAME PART A-HG009 (contoh random)
     → bl_hs_code = 8714.91

CERTIFICATE OF ORIGIN (COO):

1. coo_mark_number:
   - Ekstrak dari kolom "Marks and numbers on packages".
   - Jika kolom kosong / tidak terisi jelas pada item, isi null.
   - Jangan mengambil "PO. NO.", "MATERIAL CODE", atau "C/ NO." mark number.

2. coo_description:
   - Ekstrak dari kolom:
     - "7. Number and type of packages, description of products (including quantity where appropriate and HS number in six digit code)" jika tipe form coo = "FORM E"
        ATAU
     - "8. Number and kind of packages; and description of products or goods" jika tipe form coo = "FORM RCEP"
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
   - Abaikan / hapus hs code dari description
     Contoh: Hapus seperti "HS CODE: 3926.90", "HS CODE: 7616.10"

3. coo_hs_code:
   - Ekstrak dari kolom:  
     - "7. Number and type of packages, description of products (including quantity where appropriate and HS number in six digit code)" jika tipe form coo = "FORM E"
        ATAU
     - "9. HS Code of the goods (6 digit-level)" jika tipe form coo = "FORM RCEP"
   - Ekstrak hs code pada akhir deskripsi item.
     - Contoh:
       SIX (6) CARTONS OF PLASTIC WASHER;FEIMIN;-;BLACK;HS CODE: 3926.90
       Maka bl_hs_code = 3926.90

4. coo_quantity:
   - Ekstrak dari kolom:
     - "9. Gross weight or net weight or other quantity, and value (FOB) only when RVC criterion is applied" jika tipe form coo = "FORM E"
     - "12. Quantity (Gross weigh or other measurement), and value (FOB) where RVC is applied" jika tipe form coo = "FORM RCEP" 
   - Field ini berisi quantity dan gross weight dalam 2 baris bertumpuk.
   - Ambil quantity dari bagian pertama.
   - Contoh:
     "5000SETS" + "144.67KGS G.W." -> coo_quantity = 5000
     "3600PAIRS" + "1123.2KGS G.W." -> coo_quantity = 3600
     "200PIECES" + "3.48KGS G.W." -> coo_quantity = 200

5. coo_unit:
   - Ambil unit yang melekat pada quantity dari kolom 9. pada coo dengan form type "FORM E" atau kolom 12. pada coo dengan form type "FORM RCEP"
   - Contoh:
     "5000SETS" -> "SETS"
     "3600PAIRS" -> "PAIRS"
     "200PIECES" -> "PIECES"

6. coo_package_count:
   - Ambil angka numerik dari frasa pembuka package count di awal dari kolom 7. pada coo dengan form type "FORM E" atau kolom 8. pada coo dengan form type "FORM RCEP"
   - Contoh:
     "SEVENTEEN (17) CARTONS OF ..." -> 17
     "ONE (1) CARTON OF ..." -> 1
     "SEVENTY-TWO (72) CARTONS OF ..." -> 72

7. coo_package_unit:
   - Ambil unit package dari frasa pembuka di awal dari kolom 7. pada coo dengan form type "FORM E" atau kolom 8. pada coo dengan form type "FORM RCEP" 
   - Jika tertulis "CARTONS", isi "CARTONS".
   - Jika tertulis "CARTON", isi "CARTON".

8. coo_gw:
   - Ambil gross weight dari bagian kedua dari kolom 9. pada coo dengan form type "FORM E" atau kolom 12. pada coo dengan form type "FORM RCEP"
   - Contoh:
     "5000SETS" + "144.67KGS G.W." -> coo_gw = 144.67
     "3600PAIRS" + "1123.2KGS G.W." -> coo_gw = 1123.2
   - Ambil angka numeriknya saja.

9. coo_amount:
   - Isi null kecuali nilai FOB / amount tertulis eksplisit di COO.
   - Pada sample vendor ini, field 12 hanya menampilkan quantity dan gross weight, bukan amount.
   - Jangan ambil nilai dari invoice untuk mengisi coo_amount.

10. coo_criteria:
   - Ekstrak dari kolom:
     - "8. Origin criteria (see Overleaf Notes)" jika tipe form coo = "FORM E"
     - "10. Origin Conferring Criterion" jika tipe form coo = "FORM RCEP"
   - Hilangkan tanda kutip jika ada.
   - Contoh:
     '"PE"' -> "PE"

11. coo_customer_po_no:
   - Isi hanya jika nomor PO tertulis eksplisit.
   - Jangan ambil dari invoice number.
   - Jangan ambil dari remarks kosong seperti "PO. NO.:" tanpa value.
   - Jika tidak ada referensi PO yang jelas, isi null.
"""