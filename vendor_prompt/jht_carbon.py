TANGSHAN_JINHENGTONG_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari kolom "PO No.".
2. `inv_spart_item_no`: Ekstrak dari kolom "Material".
3. `inv_description`: Ekstrak dari kolom "Description".
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak dari kolom "qty".
6. `inv_quantity_unit`: Ekstrak dari kolom "unit" (misalnya "SET" atau "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Unit Price" (hapus simbol mata uang seperti $).
8.  `inv_amount`: Ekstrak nilai angka dari kolom "Amount" (hapus koma dan simbol mata uang).

PACKING LIST (PL):
INSTRUKSI PENTING:
Pada vendor ini, value setiap line item sudah bersifat ATOMIC sehingga DILARANG KERAS untuk menambahkan value numerik pada satu line item ke line item lain TANPA TERKECUALI!
Apabila ada line item pada PL yang TIDAK MEMILIKI pl_customer_po_no, pl_item_no, dan pl_description; maka ABAIKAN LINE ITEM TERSEBUT!
Contoh:
Line item yang tidak memiliki pl_customer_po_no, pl_item_no (misal hanya ada keterangan "Spare parts"), dan pl_description namun memiliki nilai numerik pada pl_quantity, pl_package_count, pl_nw, pl_gw, atau pl_volume; maka line item tersebut HARUS DIABAIKAN dan TIDAK BOLEH DITAMBAHKAN ke line item lain.
Line item ini biasanya terletak di bagian bawah tabel PL dengan keterangan yang sangat umum seperti "Spare parts" tanpa informasi detail lainnya. Meskipun memiliki nilai numerik pada beberapa kolom, line item ini TIDAK BOLEH DIGABUNGKAN dengan line item lain MANAPUN karena tidak memiliki informasi yang cukup untuk diidentifikasi secara unik.

1. `pl_customer_po_no`: Ekstrak dari kolom "PO No.".
2. `pl_item_no`: Ekstrak dari kolom "Material".
3. `pl_description`: Ekstrak dari kolom "DESCRIPTION".
4. `pl_quantity`: Ekstrak nilai angka dari kolom "Qty".
5. `pl_package_unit`: Simpulkan sebagai "CARTONS" berdasarkan konteks header "Number of Carton".
6. `pl_package_count`: Ekstrak dari kolom "Number of Carton".
7. `pl_nw`: Ekstrak dari kolom "N.W(KG)" dengan sub-kolom 'total'.
8. `pl_gw`: Ekstrak dari kolom "G.W(KG)" dengan sub-kolom 'total'.
9. `pl_volume`: Ekstrak nilai angka dari kolom "CBM" dengan sub-kolom 'total'.

BILL OF LADING (BL):
1. `bl_description`: 
    - Dimapping dengan inv_description berdasarkan kemiripan. Jika inv_description tidak exist pada dokumen BL, maka bl_description fill null aja.
    - Apabila ada deskripsi yang mirip namun tidak 100% (misal angkanya berbeda), tetap dimapping dengan mengambil deskripsi yang paling mirip tersebut.
    Contoh:
    Pada inv_description ada value:
    FORK RIGID IS-FC02-53MM
    FRAME RIGID IS-RB06-610
    FRAME RIGID IS-RB05-520
    FRAME RIGID IS-RB05-560
    FRAME RIGID IS-RB06-430
    FRAME RIGID IS-RB05-720
    BIKE HANDLE

    Pada BL ada deskripsi item:
    FORK RIGID
    FRAME RIGID 610
    FRAME RIGID 520
    FRAME RIGID 560
    FRAME RIGID 430

    Maka mappingnya bl_desriptionnya adalah:
    FORK RIGID
    FRAME RIGID 610
    FRAME RIGID 520
    FRAME RIGID 560
    FRAME RIGID 430
    FRAME RIGID 520 (Ambil yang terdekat)
    null (Karena tidak ada deskripsi yang sama sekali dengan BIKE HANDLE)
    -bl_description sebisa mungkin TIDAK BOLEH NULL kecuali memang tidak ada deskripsi yang mirip sama sekali dengan inv_description pada dokumen BL.

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
    - Apabila tidak ada informasi marks and numbers pada kolom 7 atau tertlulis "N/M" (Not Mentioned), maka biarkan null.s
2. `coo_description`: Ekstrak deskripsi teks dari kolom "8. Number and kind of packages; and description of goods." Abaikan keterangan jumlah paket (angka dan kata) pada field ini.
3. `coo_hs_code`: Ekstrak dari "9. HS Code of the goods".
4. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "FIFTY SIX (56) CARTONS" ambil angka 56).
5. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "CARTONS").
6. `coo_gw` & `coo_quantity`: Ekstrak berat angka dari kolom "12. Quantity...".
7. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KGS").
8. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion".
9. `coo_customer_po_no`: Biarkan null kecuali ada nomor PO yang secara spesifik ditulis per baris item.
"""