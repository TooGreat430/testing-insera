NOVATEC_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari kolom "PO.NO.".
2. `inv_spart_item_no`: Ekstrak dari kolom "CODE" (misalnya "RIMNT28R4RIM0001" atau "BNXNT-44MM00000").
3. `inv_description`: Ekstrak teks deskripsi dari kolom "DESCRIPTION".
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak nilai angka dari kolom "QTY".
6. `inv_quantity_unit`: Ekstrak dari kolom "UNIT" (misalnya "PCS" atau "SET").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "UNIT PRICE".
8. `inv_amount`: Ekstrak nilai angka dari kolom "AMOUNT".

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari kolom "PO NO.".
2. `pl_item_no`: Ekstrak dari kolom "CODE".
3. `pl_description`: Ekstrak teks deskripsi dari kolom "DESCRIPTION".
4. `pl_quantity`: Ekstrak nilai angka dari kolom "QTY".
5. `pl_package_unit`: Simpulkan sebagai "CT" berdasarkan header kolom "TOTAL CTNS".
6. `pl_package_count`: 
    - Ekstrak nilai angka dari kolom "TOTAL CTNS".
    - Apabila ada beberapa line item yang tergabung dalam satu TOTAL CTNS merged-cell, maka pl_package_count yang tertera adalah untuk line item dalam group tersebut yang paling bawah, dan sisanya 0.
        Contoh:
        |   ITEM  |  TOTAL  |
        |         |  CTNS   |
        |   A     |         |
        |   B     |   3     |
        |   C     |         |
        Maka:
        - Line item A: quantity = 0
        - Line item B: quantity = 0
        - Line item C: quantity = 3
7. `pl_nw`: 
    - Ekstrak nilai angka dari kolom "TOTAL N.W.".
    - Apabila ada beberapa line item yang tergabung dalam satu TOTAL N.W. merged-cell, maka pl_nw yang tertera adalah untuk line item dalam group tersebut yang paling bawah, dan sisanya 0.
        Contoh:
        |   ITEM  |  TOTAL  |
        |         |  N.W.   |
        |   A     |         |
        |   B     |  6.51   |
        |   C     |         |
        Maka:
        - Line item A: nw = 0
        - Line item B: nw = 0
        - Line item C: nw = 6.51
8. `pl_gw`:
    - Ekstrak nilai angka dari kolom "TOTAL G.W.".
    - Apabila ada beberapa line item yang tergabung dalam satu TOTAL G.W. merged-cell, maka pl_gw yang tertera adalah untuk line item dalam group tersebut yang paling bawah, dan sisanya 0.
        Contoh:
        |   ITEM  |  TOTAL  |
        |         |  G.W.   |
        |   A     |         |
        |   B     |  7.20   |
        |   C     |         |
        Maka:
        - Line item A: gw = 0
        - Line item B: gw = 0
        - Line item C: gw = 7.20
9. `pl_volume`:
    - Ekstrak nilai angka dari kolom "TOTAL CBM".
    - Apabila ada beberapa line item yang tergabung dalam satu TOTAL CBM merged-cell, maka pl_volume yang tertera adalah untuk line item dalam group tersebut yang paling bawah, dan sisanya 0.
        Contoh:
        |   ITEM  |  TOTAL  |
        |         |  CBM    |
        |   A     |         |
        |   B     |  1.15   |
        |   C     |         |
        Maka:
        - Line item A: volume = 0
        - Line item B: volume = 0
        - Line item C: volume = 1.15

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
4. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "TWO (2) CARTONS" ambil angka 2).
5. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "CARTONS").
6. `coo_gw` & `coo_quantity`: 
    - Ekstrak nilai berat dari kolom "12. Quantity..." untuk mengisi `coo_gw` (misalnya dari "41.09KGS G.W. 70PIECES", ekstrak "41.09").
    - Ekstrak nilai jumlah barang dari baris yang sama untuk mengisi `coo_quantity` (misalnya dari "70PIECES", ekstrak "70").
7. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KGS").
8. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
9. `coo_customer_po_no`: Biarkan null kecuali ada referensi nomor PO yang secara spesifik ditulis di dalam kolom 7 atau 8.
"""