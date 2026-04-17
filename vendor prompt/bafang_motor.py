BAFANG_MOTOR_PROMPT = """

INVOICE (INV):

1. inv_customer_po_no:
   - Ekstrak dari kolom "PO".
   - Contoh: "43018071", "43018072".

2. inv_spart_item_no:
   - Ekstrak dari kolom "Customer Article No.".
   - Jangan ambil dari kolom "Item", "Model", atau "BF Article No."
   - Contoh:
     "BATBFEELMINI04-R"
     "BAXBFBTF291004-R"
     "BATBFHEGIIPRCS00-R"

3. inv_description:
   - Ekstrak dari kolom "Insera Description".
   - Gabungkan seluruh wrapped lines yang masih merupakan bagian dari deskripsi item.
   - Jangan sertakan Price, Quantity, Amount, Brand, atau PO.
   - Contoh hasil:
     "EEL-MINI battery casing, 36V CAN, 10.5Ah, 378Wh, 30 CELLS, EVE 3.5Ah cell, produced in China"

4. inv_gw & inv_gw_unit:
   - Isi null kecuali ada gross weight yang tertulis eksplisit pada invoice.

5. inv_quantity:
   - Ekstrak dari kolom "Quantity".
   - Contoh: "455", "700"

6. inv_quantity_unit:
   - Isi null kecuali ada unit quantity yang tertulis eksplisit pada baris item invoice.
   - Jangan mengasumsikan PCS/SET jika tidak tertulis.

7. inv_unit_price:
   - Ekstrak dari kolom "Price (USD)".
   - Ambil angka numeriknya saja. Jangan ambil simbol mata uangnya.
   - Contoh:
     "$106.10" -> 106.10

PACKING LIST (PL)

1. pl_customer_po_no:
   - Ekstrak dari kolom "PO".
   - Contoh: "43018071", "43018072".

2. pl_item_no:
   - Ekstrak dari kolom "Customer Article No.".
   - Jangan ambil dari kolom "Item", "Model", atau "BF Article No."
   - Contoh:
     "BATBFEELMINI04-R"
     "BAXBFBTF291004-R"
     "BATBFHEGIIPRCS00-R"

3. pl_description:
   - Ekstrak dari kolom "Insera Description".
   - Gabungkan seluruh wrapped lines yang masih merupakan bagian dari deskripsi item.
   - Jangan sertakan CTNS, Quantity, G.W, N.W, Brand, atau PO.
   - Contoh hasil:
     "EEL-MINI battery casing, 36V CAN, 10.5Ah, 378Wh, 30 CELLS, EVE 3.5Ah cell, produced in China"


4. pl_quantity:
   - Ekstrak dari kolom "Quantity".
   - Contoh: "455", "700"

5. pl_package_unit:
   - Ekstrak jenis kemasan dari nama kolom package (misal "CTNS").
   - Gunakan unit kemasan sebagaimana tertulis, misalnya "CTNS"
   - Jangan ubah ke unit lain.

6. pl_package_count:
   - Ekstrak dari kolom "CTNS".
   - Contoh: "455", "11", "234"

7. pl_nw:
   - Ekstrak dari kolom "N.W(KGS)".
   - Ambil angka numeriknya saja.

8. pl_gw:
   - Ekstrak dari kolom "G.W(KGS)".
   - Ambil angka numeriknya saja.

9. pl_volume:
   - Ekstrak dari kolom "MEASUREMENT"
   - Jika value volume adalah merge untuk beberapa line item, value volume hanya di ekstrak untuk line item teratas dari merge value tersebut, sedangkan sisa value lainnya di isi dengan 0.
     - Contoh:
       | Description  |   Measurement |
       | Barang 1     |               |
       | Barang 2     |     13.500    |
       | Barang 3     |               |
       | Barang 4     |               |
       maka:
       - Barang 1, pl_volume = 13.500
       - Barang 2, pl_volume = 0
       - Barang 3, pl_volume = 0
       - Barang 4, pl_volume = 0
   - Jangan membagi / mengarang volume per item

BILL OF LADING (BL)

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

CERTIFICATE OF ORIGIN (COO)

1. coo_mark_number
   - Ekstrak dari field "7. Marks and numbers on packages".
   - Pada format vendor ini bisa berupa "N/M".
   - Ambil persis seperti tertulis.
   - Jika tidak tersedia, isi dengan "null".

2. coo_description:
   - Ekstrak dari field "8. Number and kind of packages; and description of goods".
   - Abaikan frasa jumlah kemasan di awal/akhir seperti:
     "FIVE HUNDRED AND SIXTY (560) CTNS".
   - Abaikan juga informasi BL No. dan Container No. bila muncul setelah deskripsi.
   - Fokus pada deskripsi barangnya saja.
   - Contoh hasil:
     "BICYCLE PARTS FORK SUSPENSION GSFXCM32DZ000036;SUNTOUR;SF23-XCM32DS;MATTEBLACKBLADE/CP STANCHION/MATTEBLACK CROWN;-;DISC PM160 QR/NUT,ALLOY BLADE/ALLOY CROWN, 27.5 THREADLESS 28(1-1/8") 255.00MMSTEEL STEERER 100.00 COIL W/ PRELOADADJUSTER - - W/ SEPARATEDECAL"
   - Jika tidak tersedia, isi dengan "null".
3. coo_hs_code:
   - Ekstrak dari field "9. HS Code of the goods".
   - Contoh: "8714.91".
   - Jika tidak tersedia, isi dengan "null".

4. coo_package_count:
   - Ekstrak angka numerik dari frasa jumlah kemasan dalam field 8.
   - Contoh:
     dari "FIVE HUNDRED AND SIXTY (560) CTNS"
     maka coo_package_count = 560
   - Jika tidak tersedia, isi dengan "null".

5. coo_package_unit:
   - Ekstrak unit kemasan dari frasa jumlah kemasan dalam field 8.
   - Contoh: "CTNS".
   - Jika tidak tersedia, isi dengan "null".

6. coo_gw & coo_quantity:
   - Untuk vendor ini, cek isi field "12. Quantity (Gross weight or other measurement)..."
   - Jika field 12 berisi quantity + unit, misalnya "3355SETS", maka:
     - coo_quantity = 3355
     - coo_gw = null
   - Hanya isi coo_gw jika ada nilai berat eksplisit dengan unit seperti KG/KGS.
   - Jika tidak tersedia, isi dengan "null".

7. coo_unit:
   - Ekstrak unit yang melekat pada field 12.
   - Jika field 12 berisi quantity, ambil unit quantity tersebut.
   - Contoh: "SETS".
   - Jika field 12 berisi berat, ambil unit beratnya, misalnya "KG".
   - Jika tidak tersedia, isi dengan "null".

8. coo_criteria:
   - Ekstrak dari field "10. Origin Conferring Criterion".
   - Jika ada tanda kutip, hilangkan tanda kutipnya.
   - Contoh: "RVC".
   - Jika tidak tersedia, isi dengan "null".
9. coo_customer_po_no:
   - Isi hanya jika ada nomor PO yang tertulis eksplisit.
   - Jika tidak ada referensi PO yang jelas, isi null.
   - Jika tidak tersedia, isi dengan "null". 
"""