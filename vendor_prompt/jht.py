JHT_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari teks referensi awalan "PO:" yang berada sebelum/di atas list barang (misalnya "PO:45326462").
2. `inv_spart_item_no`:
    - Ekstrak kode barang unik jika tercantum di dalam teks "DESCRIPTION OF GOODS" dan terletak di sebelah paling kiri.
    - Contoh:
    DESCRIPTION OF GOODS:RIM, HLQC-GA63-1,  DOUBLE WALL BLACK  20*1.5 AV  32H W/ SAFETY LINE W/O DECAL,RIMJE20HLQCGA005
    Maka inv_spart_item_no adalah HLQC-GA63-1 (bukan RIMJE20HLQCGA005).
3. `inv_description`: 
    - Ekstrak deskripsi spesifikasi lengkap barang dari kolom "DESCRIPTION OF GOODS" (Abaikan yang sifatnya code, part number, atau serial number).
    - Contoh:
    DESCRIPTION OF GOODS:RIM, HLQC-GA63-1,  DOUBLE WALL BLACK  20*1.5 AV  32H W/ SAFETY LINE W/O DECAL,RIMJE20HLQCGA005
    Maka inv_description adalah DOUBLE WALL BLACK  20*1.5 AV  32H W/ SAFETY LINE W/O DECAL.
4. `inv_gw` & `inv_gw_unit`: Biarkan null kecuali dinyatakan secara eksplisit di baris tersebut.
5. `inv_quantity`: Ekstrak nilai angka dari kolom "Quantity".
6. `inv_quantity_unit`: Ekstrak unit dari kolom "Quantity" yang letaknya di samping angka (misalnya "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Unit Price" (secara posisi sejajar ke bawah).
8. `inv_amount`: Ekstrak nilai angka dari kolom "Amount" (secara posisi sejajar ke bawah).

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari teks referensi awalan "PO:" (misalnya "PO:45326462").
2. `pl_item_no`: 
    - Ekstrak kode barang unik jika tercantum di dalam teks "DESCRIPTION OF GOODS" dan terletak di sebelah paling kiri.
    - Contoh:
    DESCRIPTION OF GOODS:RIM, HLQC-GA63-1,  DOUBLE WALL BLACK  20*1.5 AV  32H W/ SAFETY LINE W/O DECAL,RIMJE20HLQCGA005
    Maka pl_item_no adalah HLQC-GA63-1 (bukan RIMJE20HLQCGA005).
3. `pl_description`:
    - Ekstrak deskripsi spesifikasi lengkap barang dari kolom "DESCRIPTION OF GOODS" (Abaikan yang sifatnya code, part number, atau serial number).
    - Contoh:
    DESCRIPTION OF GOODS:RIM, HLQC-GA63-1,  DOUBLE WALL BLACK  20*1.5 AV  32H W/ SAFETY LINE W/O DECAL,RIMJE20HLQCGA005
    Maka pl_description adalah DOUBLE WALL BLACK  20*1.5 AV  32H W/ SAFETY LINE W/O DECAL.
4. `pl_quantity`: Ekstrak nilai angka dari kolom "QTY".
5. `pl_package_unit`: Apabila tidak ada kolom unit kemasan yang spesifik dan tidak ada clue package unit seperti: "Carton/CTN/CTN/CT", "Pallet/plt", "Bal/Bale", "PXCT/PK"  dll, maka return null.
6. `pl_package_count`: Ekstrak nilai angka jumlah kemasan spesifik per item dari kolom "PACKING" (misalnya angka "20").
7. `pl_nw`: Ekstrak nilai angka dari kolom "N.W. KGS" dan BUKAN "N.W./PKGS".
8. `pl_gw`: Ekstrak nilai angka dari kolom "G.W. KGS" dan BUKAN "G.W./PKGS".
9. `pl_volume`: Ekstrak nilai angka dari kolom volume "VOL/PKGS" kemudian KALIKAN dengan data pl_package_count line tersebut.

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
4. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "TWENTY (20) PKGS" ambil angka 20).
5. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "PKGS").
6. `coo_gw` & `coo_quantity`: Ekstrak berat angka dari kolom "12. Quantity...".
7. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KG").
8. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
9. `coo_customer_po_no`: Biarkan null kecuali ada referensi nomor PO yang secara spesifik ditulis dalam kolom 7 atau 8.
"""