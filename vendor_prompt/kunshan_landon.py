KUNSHAN_LANDON_PROMPT = """

CLUE PENTING:

URUTAN KOLOM PADA DOKUMEN INVOICE (INV) — DARI KIRI KE KANAN (9 kolom):
1. Marks
2. PO Number
3. Item
4. Material
5. Descriptions
6. Quantity
7. Unit
8. Unit Price
9. Amount

URUTAN KOLOM PADA DOKUMEN PACKING LIST (PL) — DARI KIRI KE KANAN (12 kolom):
1.  Marks
2.  PO Number
3.  Item
4.  Material
5.  Descriptions
6.  QTY        ← angka quantity baris
7.  UNIT       ← satuan quantity (PCS/SET/PCE/PRS/BT/dst)
8.  Packing    ← jumlah kemasan untuk baris ini (umumnya angka kecil: 1, 2, 3, dst)
9.  N.W        ← net weight baris
10. G.W        ← gross weight baris
11. VOL        ← volume baris
12. C/NO#      ← RENTANG nomor karton untuk baris ini (contoh: "1-10", "1-58", "1-280")

PERINGATAN PENTING TENTANG KOLOM C/NO# (kolom ke-12, paling kanan):
- C/NO# berisi RENTANG nomor karton dalam format "X-Y" (contoh: "1-10" artinya karton ke-1 sampai karton ke-10).
- C/NO# BUKAN jumlah kemasan dan TIDAK BOLEH digunakan untuk mengisi pl_package_count.
- C/NO# hanya muncul sekali untuk sekelompok baris yang berbagi rentang karton yang sama, jadi banyak baris memiliki C/NO# kosong.

INVOICE (INV):

1. `inv_customer_po_no`: 
    - Ekstrak HANYA dari kolom "PO Number" (Kolom ke-2 dari kiri, di sebelah kanan kolom "Marks" dan di sebelah kiri kolom "Item").
    - Value HARUS numerik 8 digit DAN HARUS DIMULAI dengan angka 4. (Bukan value numerik 1 digit seperti "8")
      Contoh: 45324149
    - Apabila pada kolom "PO Number" terdapat lebih dari 1 value dengan format seperti:
        PO Number: 45324149/CLM26030220
        Maka ekstrak value numerik sebelum tanda slash (/),
        Jadi inv_customer_po_no line tersebut = 45324149
    - DILARANG KERAS mengambil value PO Number selain dari kolom "PO Number".
    - DILARANG KERAS mengambil dari kolom "Item".

2. `inv_spart_item_no`:
    - Ekstrak HANYA dari kolom "Material" (Kolom ke-4 dari kiri, di sebelah kanan kolom 'Item' dan di sebelah kiri kolom 'Descriptions).
    - Value berupa alphanumerik (Bukan value numerik 1 digit seperti "8")
      Contoh: BSBSJBSL000009
    - DILARANG KERAS mengambil value dari kolom lain yang bukan "Material" 
    - Dilarang KERAS mengambil value dari kolom "Item" DAN "Description". 

3. `inv_description`: Ekstrak teks deskripsi dari kolom "DESCRIPTION".
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak nilai angka dari kolom "Q'TY" atau "Quantity".
6. `inv_quantity_unit`: Ekstrak dari kolom "UNIT" (misalnya "PCS" atau "SET"). Jika tergabung di kolom QTY, pisahkan dari angkanya.
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "UNIT PRICE" (hapus simbol mata uang).
8. `inv_amount`: Ekstrak nilai angka dari kolom "AMOUNT" (hapus simbol mata uang).

PACKING LIST (PL):
1. `pl_customer_po_no`:
    - Ekstrak HANYA dari kolom "PO Number" (Kolom ke-2 dari kiri, di sebelah kanan kolom "Marks" dan di sebelah kiri kolom "Item").
    - Value HARUS numerik 8 digit DAN HARUS DIMULAI dengan angka 4. (Bukan value numerik 1 digit seperti "8")
      Contoh: 45324149
    - Apabila pada kolom "PO Number" terdapat lebih dari 1 value dengan format seperti:
        PO Number: 45324149/CLM26030220
        Maka ekstrak value numerik sebelum tanda slash (/),
        Jadi inv_customer_po_no line tersebut = 45324149
    - DILARANG KERAS mengambil value PO Number selain dari kolom "PO Number".
    - DILARANG KERAS mengambil dari kolom "Item".

2. `pl_item_no`:
    - Ekstrak HANYA dari kolom "Material" (Kolom ke-4 dari kiri, di sebelah kanan kolom 'Item' dan di sebelah kiri kolom 'Descriptions).
    - Value berupa alphanumerik (Bukan value numerik 1 digit seperti "8")
      Contoh: BSBSJBSL000009
    - DILARANG KERAS mengambil value dari kolom lain yang bukan "Material" 
    - Dilarang KERAS mengambil value dari kolom "Item" DAN "Description". 
    
3. `pl_description`: Ekstrak teks deskripsi dari kolom "DESCRIPTION".
4. `pl_quantity`: Ekstrak nilai angka dari kolom "Q'TY" atau "Quantity".
5. `pl_package_unit`: Simpulkan sebagai "CTNS" atau "CARTONS" berdasarkan header kolom kemasan.
6. `pl_package_count`:
    - Ekstrak HANYA dari kolom "Packing" (kolom ke-8 dari kiri, BERADA DI ANTARA kolom "UNIT" (kolom 7) dan kolom "N.W" (kolom 9)).
    - Value berupa angka tunggal yang umumnya kecil (1, 2, 3, 4, 6, 10, 27, 40, dst), BUKAN rentang.
    - DILARANG KERAS mengambil dari kolom "C/NO#" (kolom paling kanan / kolom ke-12) yang berisi rentang karton seperti "1-10", "1-58", "1-280".
    - Jika kolom "Packing" tampak kosong untuk baris tersebut (misalnya baris yang berbagi blok C/NO# dengan baris di atasnya), TETAP BACA ULANG karena nilai Packing per baris hampir selalu terisi pada vendor ini.
    - CONTOH KASUS JEBAKAN (HARUS DIPAHAMI):
      Baris asli pada Packing List:
        "79 | 45330414 | 9 | FRXUAB12250000 | REPLACEABLE DROP OUT... | 20 | PCS | 1 | 0.30 | 0.50 | 0.010 | 1-10"
      Penjelasan kolom:
        QTY=20, UNIT=PCS, Packing=1, N.W=0.30, G.W=0.50, VOL=0.010, C/NO#=1-10
      Maka pl_package_count = 1 (dari kolom Packing).
      SALAH: pl_package_count = 10 (mengambil ujung kanan dari rentang C/NO# "1-10").
      SALAH: pl_package_count = 1-10 (mengambil string rentang C/NO# secara langsung).
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
1. `coo_seq`:
   - Ambil dari kolom "Item number".
   - Nilai numeric.
   - Item number tercetak jelas seperti:
     - 1
     - 2
     - 3
     - ...
2. `coo_mark_number`:
    - Ekstrak dari "7. Marks and numbers on packages".
    - Apabila tidak ada informasi marks and numbers pada kolom 7 atau tertlulis "N/M" (Not Mentioned), maka biarkan null.
3. `coo_description`: Ekstrak deskripsi teks dari kolom "8. Number and kind of packages; and description of goods." Abaikan keterangan jumlah paket (angka dan kata) pada field ini.
4. `coo_hs_code`: Ekstrak dari "9. HS Code of the goods".
5. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "TEN (10) CARTONS" ambil angka 10).
6. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "CARTONS").
7. `coo_gw` & `coo_quantity`: Ekstrak berat angka dari kolom "12. Quantity..." (biasanya ditulis dengan format seperti "255.6KGS G.W.").
8. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KGS").
9. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
10. `coo_customer_po_no`: Biarkan null kecuali ada nomor PO yang secara spesifik ditulis per baris item.
"""