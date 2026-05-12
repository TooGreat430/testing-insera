TIEN_HSIN_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari teks berawalan "P. O. NO" atau "P. O. NO:" yang berada di dalam blok deskripsi atau di atas/bawah nama barang. Ambil HANYA angka PO-nya saja (misalnya dari "P. O. NO 45321009", ekstrak "45321009").
2. `inv_spart_item_no`: Ekstrak dari kolom "Item/Part no.". Abaikan nomor urut baris (seperti 1, 43, 44) dan ambil murni kode alfanumerik part-nya saja (misalnya "CWSFSSH12001-R" atau "HDPFSAORBIT013-R").
3. `inv_description`: Ekstrak teks deskripsi spesifikasi barang dari kolom "Description".
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak nilai angka dari kolom "Quantity".
6. `inv_quantity_unit`: Ekstrak unit dari kolom "Quantity" (misalnya "SET" atau "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Unit Price" (hapus teks mata uang seperti USD).
8. `inv_amount`: Ekstrak nilai angka dari kolom "Amount" (hapus teks mata uang seperti USD dan koma ribuan).

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari teks berawalan "P. O. NO:" di dalam kolom "DESCRIPTION" (misalnya "45321009").
2. `pl_item_no`: Ekstrak kode barang alfanumerik yang tertera di dalam kolom "DESCRIPTION" tepat di bawah nomor PO (misalnya "CWSFSSH12001-R").
3. `pl_description`: Ekstrak teks deskripsi barang yang berada di bawah part number pada kolom "DESCRIPTION".
4. `pl_quantity`: 
    - Ekstrak nilai angka total dari kolom "QUANTITY".
    - Apabila dalam satu sel terdapat baris atas dengan simbol "@" (misal "40SET @") dan baris bawah tanpa simbol "@" (misal "360"), maka ambil HANYA angka yang bawah ("360") sebagai total kuantitas. Abaikan yang ada simbol "@".
5. `pl_package_unit`: Simpulkan sebagai "CTNS" atau "CARTONS" berdasarkan konteks dokumen.
6. `pl_package_count`: Ekstrak nilai angka dari kolom "CTN" (misalnya jika tertulis "9 @", ekstrak angka 9).
7. `pl_nw`: 
    - Ekstrak nilai angka total dari kolom "N. WEIGHT".
    - Ambil HANYA nilai di baris bawah yang tidak memiliki simbol "@" (misalnya dari teks "7.880KGS @ \\n 70.920", ekstrak "70.920").
8. `pl_gw`: 
    - Ekstrak nilai angka total dari kolom "G. WEIGHT".
    - Ambil HANYA nilai di baris bawah yang tidak memiliki simbol "@" (misalnya dari teks "10.000KGS @ \\n 90.000", ekstrak "90.000").
9. `pl_volume`: Ekstrak nilai angka total dari baris bawah pada kolom "MEASURE'T".

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
1. `coo_seq`:
   - Ambil dari kolom "Item number".
   - Nilai numeric.
   - Item number tercetak jelas seperti:
     - 1
     - 2
     - 3
     - ...
2. `coo_mark_number`: Ekstrak dari "7. Marks and numbers on packages" (misalnya, "N/M").
3. `coo_description`: Ekstrak deskripsi teks dari kolom "8. Number and kind of packages; and description of goods." Abaikan keterangan jumlah paket (angka dan kata) pada field ini.
4. `coo_hs_code`: Ekstrak dari "9. HS Code of the goods".
5. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "TEN (10) CARTONS" ambil angka 10).
6. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "CARTONS").
7. `coo_gw` & `coo_quantity`: Ekstrak berat angka dari kolom "12. Quantity..." (biasanya ditulis dengan format seperti "255.6KGS G.W.").
8. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KGS").
9. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
10. `coo_customer_po_no`: Biarkan null kecuali ada nomor PO yang secara spesifik ditulis per baris item.
"""