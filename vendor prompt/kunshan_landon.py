KUNSHAN_LANDON_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari referensi "PO Number".
2. `inv_spart_item_no`: Ekstrak dari kolom "Material", misal: "BELLDZZ0000000".
3. `inv_description`: Ekstrak teks deskripsi dari kolom "DESCRIPTION".
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak nilai angka dari kolom "Q'TY" atau "Quantity".
6. `inv_quantity_unit`: Ekstrak dari kolom "UNIT" (misalnya "PCS" atau "SET"). Jika tergabung di kolom QTY, pisahkan dari angkanya.
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "UNIT PRICE" (hapus simbol mata uang).
8. `inv_amount`: Ekstrak nilai angka dari kolom "AMOUNT" (hapus simbol mata uang).

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari referensi "PO Number:".
2. `pl_item_no`: Ekstrak dari kolom "Material", misal: "BELLDZZ0000000".
3. `pl_description`: Ekstrak teks deskripsi dari kolom "DESCRIPTION".
4. `pl_quantity`: Ekstrak nilai angka dari kolom "Q'TY" atau "Quantity".
5. `pl_package_unit`: Simpulkan sebagai "CTNS" atau "CARTONS" berdasarkan header kolom kemasan.
6. `pl_package_count`: Ekstrak dari kolom "Packing".
7. `pl_nw`: Ekstrak nilai angka dari kolom "N.W.".
8. `pl_gw`: Ekstrak nilai angka dari kolom "G.W.".
9. `pl_volume`: Ekstrak nilai angka dari kolom "VOL".

BILL OF LADING (BL):
1. `bl_description`: 
    - Dimapping dengan inv_description. Jika inv_description tidak exist pada dokumen BL, maka bl_description fill null aja.
2. `bl_hs_code`: 
    - Value bl_hs_code diisi sesuai dengan bl_descriptionnya
        Contoh:
        FRAME PART A-F3306-1 HS NUMBER: 8714.91
        FRAME PART A-HG009 HS NUMBER: 8714.91
        FRAME PART A-HG011 HS NUMBER: 8714.91
        FRAME PART A-HG045 HS NUMBER: 8714.91
        FRAME TUBING HS NUMBER: 8714.91

        Maka:
        Pada inv_description ada value FRAME PART AF-9F-0270 (which is tidak ada), maka bl_description isi null saja.
        Pada inv_description ada value FRAME PART A-HG009 (which is ada), maka bl_description isi FRAME PART A-HG009.
        bl_hs_code untuk FRAME PART A-HG009 adalah 8714.91, maka bl_hs_code isi 8714.91.
    - Hanya boleh mengambil dari dokumen Bill Of Lading (BL), TIDAK BOLEH dari dokumen yang lain.

CERTIFICATE OF ORIGIN (COO):
1. `coo_mark_number`:
    - Ekstrak dari "7. Marks and numbers on packages".
    - Apabila tidak ada informasi marks and numbers pada kolom 7 atau tertlulis "N/M" (Not Mentioned), maka biarkan null.
2. `coo_description`: Ekstrak deskripsi teks dari kolom "8. Number and kind of packages; and description of goods." Abaikan keterangan jumlah paket (angka dan kata) pada field ini.
3. `coo_hs_code`: Ekstrak dari "9. HS Code of the goods".
4. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "TEN (10) CARTONS" ambil angka 10).
5. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "CARTONS").
6. `coo_gw` & `coo_quantity`: Ekstrak berat angka dari kolom "12. Quantity..." (biasanya ditulis dengan format seperti "255.6KGS G.W.").
7. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KGS").
8. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
9. `coo_customer_po_no`: Biarkan null kecuali ada nomor PO yang secara spesifik ditulis per baris item.
"""