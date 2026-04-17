FOX_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Biarkan null karena tidak ada referensi PO Number secara eksplisit di level baris pada invoice ini.
2. `inv_spart_item_no`: Ekstrak dari kolom "Cust SKU" (misalnya "BAXFX82007177000-R").
3. `inv_description`: Ekstrak teks dari kolom "Description".
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak nilai angka dari kolom "Qty" atau "Qty FOC".
6. `inv_quantity_unit`: Biarkan null karena tidak terdapat informasi unit quantity pada format invoice ini.
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Unit Value" (hapus simbol mata uang).
8. `inv_amount`: Ekstrak nilai angka dari kolom "Ext Value" (hapus koma dan simbol mata uang).

PACKING LIST (PL):
1. `pl_customer_po_no`:
    - Lihat pada kolom Order/Line: Info
    - pl_customer_po_no diisi dengan nomor PO yang tertera pada kolom tersebut yang tertulis lebih kecil di sebelah kiri.
    - pl_customer_po_no biasanya diawali dengan huruf '4'.
    - Contoh:
    | Order/Line: Info          |
    | 4500551234 2045027//1.1   |
    Maka pl_customer_po_no adalah 4500551234.

2. `pl_item_no`: Ekstrak dari kolom "CUST SKU" (misalnya "FFUMZ29BOMBER019-R").
3. `pl_description`:
    - Ekstrak teks dari "Item Description" yang tidak di-highlight abu-abu (clear highlight dengan background putih).
    - Contoh:
    Pallet#1 Size:120CMx100CMx203CM
    Box#:1
    2025, Bomber Z2, 29in, Marzocchi, 140, RAIL 2.0, Sweep-Adj, Shiny 
    Blk, Neutral/Gloss Blk Logo, Kabolt 110, BLK, 1.5 T, 58HT, 44mm 
    Rake, OE
    Maka pl_description adalah 2025, Bomber Z2, 29in, Marzocchi, 140, RAIL 2.0, Sweep-Adj, Shiny Blk, Neutral/Gloss Blk Logo, Kabolt 110, BLK, 1.5 T, 58HT, 44mm Rake, OE.

4. `pl_quantity`: Ekstrak angka dari kolom 'Qty'.
5. `pl_package_unit`: Simpulkan ssebagai 'PX' karena satuan terbesarnya adalah Pallet (Satu pallet bisa memuat beberapa box).
6. `pl_package_count`: 
    - Hitung jumlah pallet dengan menghitung jumlah kemasan yang memiliki informasi "Pallet#..." pada kolom "Item Description".
    - Contoh:

    Pallet#1 Size:120CMx100CMx203CM
    Box#:1
    [DESKRIPSI]

    Pallet#2 Size:120CMx100CMx203CM
    Box#:1
    [DESKRIPSI]
    Box#:2
    [DESKRIPSI]

    Maka pl_package_count adalah 2 (karena yang dihitung adalah satuan terbesarnya).
7. `pl_nw`: 
    - Ambil nilai pl_nw pada header Pallet (misalnya, "NW:170KG").
    - Apabila tidak ada informasi NW di header Pallet, maka biarkan null.
8. `pl_gw`:
    - Ambil nilai pl_gw pada header Pallet (misalnya, "GW:170KG").
    - Apabila tidak ada informasi GW di header Pallet, maka biarkan null.
9. `pl_volume`: 
    - Ambil nilai ukuran pada header Pallet (misalnya, "120CMx100CMx203CM").
    - Kalikan ketiga nilai ukuran tersebut untuk mendapatkan volume dalam satuan CM3, lalu konversikan ke CBM dengan membagi 1.000.000.
    - Apabila tidak ada informasi ukuran di header Pallet, maka biarkan null.

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
1. `coo_mark_number`: Ekstrak dari "7. Marks and numbers on packages" (misalnya, "N/M").
2. `coo_description`: Ekstrak deskripsi teks dari kolom "8. Number and kind of packages; and description of goods." Abaikan keterangan jumlah paket (angka dan kata) pada field ini.
3. `coo_hs_code`: Ekstrak dari "9. HS Code of the goods".
4. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "TEN (10) CARTONS" ambil angka 10).
5. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "CARTONS").
6. `coo_gw` & `coo_quantity`: Ekstrak berat angka dari kolom "12. Quantity..." (biasanya ditulis dengan format seperti "255.6KGS G.W.").
7. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KGS").
8. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
9. `coo_customer_po_no`: Biarkan null kecuali ada nomor PO yang secara spesifik ditulis per baris item.
"""