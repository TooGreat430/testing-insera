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

STRUKTUR MERGED CELL DAN KOLOM COMBINED:
    Tabel ini memiliki dua area berbeda di sisi kanan untuk baris-baris yang memiliki merged TOTAL CTNS cell:

    AREA A — nilai per-merge-group (yang digunakan untuk ekstraksi):
    Format: [Combined QTY] [TOTAL CTNS] [Combined N.W] [Combined G.W] [CBM]
    Nilai ini merepresentasikan satu merge group spesifik. Selalu disertai angka TOTAL CTNS (mis. 1, 2).
    AREA A ini adalah yang harus digunakan untuk mengisi pl_package_count, pl_nw, pl_gw, pl_volume.

    AREA B — nilai total seluruh tipe item (HARUS DIABAIKAN):
    Format: [Combined QTY besar] [Combined N.W] [Combined G.W]
    Nilai ini adalah akumulasi dari SEMUA baris dengan item yang sama. TIDAK disertai TOTAL CTNS.
    Nilai ini LEBIH BESAR dari AREA A karena mencakup seluruh item sejenis.
    JANGAN gunakan nilai AREA B untuk mengisi field apapun.

    DISAMBIGUASI AREA A vs AREA B — WAJIB dilakukan terlebih dahulu:
    Dalam satu blok item yang sama, bisa muncul DUA set nilai Combined di area yang berdekatan:
    satu AREA A (untuk sub-group tertentu) dan satu AREA B (untuk total semua baris item tersebut).
    Cara membedakannya:
    - AREA A: Combined QTY = sum QTY hanya beberapa baris berurutan (sub-set). DISERTAI TOTAL CTNS.
    - AREA B: Combined QTY = sum QTY SEMUA baris dengan item yang sama (total keseluruhan). TANPA TOTAL CTNS.
    Jika dua Combined QTY muncul berdekatan pada visual yang sama, pilih yang LEBIH KECIL sebagai AREA A
    dan ABAIKAN yang lebih besar (AREA B).

    POSISI VISUAL AREA A — PERHATIKAN INI:
    Nilai AREA A (Combined QTY, TOTAL CTNS, Combined N.W, Combined G.W, CBM) untuk suatu merge group
    dapat muncul secara visual di posisi baris TERAKHIR dalam group tersebut, atau di antara dua baris,
    bukan selalu di baris pertama. Meskipun demikian, nilai-nilai ini HARUS DIASSIGN ke baris PERTAMA
    (TOP) dari merge group. Posisi visual tidak menentukan ke mana nilai diassign.

    ALGORITMA ASSIGNMENT (jalankan urutan ini setiap kali ada merged cell):
    Langkah 1: Identifikasi semua nilai Combined QTY yang ada di kolom AREA A (yang disertai TOTAL CTNS).
    Langkah 2: Untuk setiap Combined QTY di AREA A, temukan baris-baris berurutan yang jumlah QTY-nya = nilai tersebut.
               Ini adalah merge group yang sesuai.
    Langkah 3: Baris PERTAMA dari merge group → assign pl_package_count=TOTAL CTNS, pl_nw=Combined N.W (AREA A),
               pl_gw=Combined G.W (AREA A), pl_volume=CBM (AREA A).
    Langkah 4: Baris KEDUA dst. dalam merge group → pl_package_count=0, pl_nw=0, pl_gw=0, pl_volume=0.
    Langkah 5: ABAIKAN semua nilai Combined dari AREA B (tidak ada field yang menggunakan AREA B).

    Cara menentukan batas merge group:
    - Hitung jumlah QTY beberapa baris berturut-turut sampai hasilnya cocok dengan Combined QTY AREA A.
    - Contoh: Combined QTY = 754, baris A (qty=320) + B (qty=354) + C (qty=80) = 754 → A, B, C satu group.
    - Contoh: Combined QTY = 3, baris X (qty=2) + Y (qty=1) = 3 → X dan Y satu group.
    - PENTING: kesamaan PO number BUKAN penentu batas group. Verifikasi selalu dengan Combined QTY.
      Contoh: baris dengan PO berbeda bisa berada dalam satu merge group yang sama.

6. `pl_package_count`:
    - Ekstrak dari kolom "TOTAL CTNS" main table.
    - Untuk merged cell group: TOTAL CTNS (nilai AREA A) diberikan ke baris PALING ATAS group, sisanya 0.
    - Batas group ditentukan dengan Combined QTY AREA A = sum QTY baris-baris dalam group.
    - JANGAN gunakan nilai AREA B meskipun visually muncul lebih dekat ke baris yang dimaksud.
7. `pl_nw`:
    - Untuk baris standalone (tidak ada merge): ekstrak dari kolom "TOTAL N.W." main table.
    - Untuk merged cell group: ambil nilai Combined N.W dari AREA A yang sesuai untuk group tersebut.
      Berikan ke baris PALING ATAS group, sisanya 0.
    - JANGAN gunakan Combined N.W dari AREA B (nilainya jauh lebih besar, tidak disertai TOTAL CTNS).
    - Jika dua nilai Combined N.W muncul berdekatan, gunakan yang LEBIH KECIL (AREA A).
8. `pl_gw`:
    - Untuk baris standalone: ekstrak dari kolom "TOTAL G.W." main table.
    - Untuk merged cell group: ambil nilai Combined G.W dari AREA A yang sesuai untuk group tersebut.
      Berikan ke baris PALING ATAS group, sisanya 0.
    - JANGAN gunakan Combined G.W dari AREA B.
    - Jika dua nilai Combined G.W muncul berdekatan, gunakan yang LEBIH KECIL (AREA A).
9. `pl_volume`:
    - Untuk baris standalone: ekstrak dari kolom "TOTAL CBM" main table.
    - Untuk merged cell group: ambil nilai CBM yang mengikuti Combined G.W di AREA A untuk group tersebut.
      Berikan ke baris PALING ATAS group, sisanya 0.

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
5. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "TWO (2) CARTONS" ambil angka 2).
6. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "CARTONS").
7. `coo_gw` & `coo_quantity`: 
    - Ekstrak nilai berat dari kolom "12. Quantity..." untuk mengisi `coo_gw` (misalnya dari "41.09KGS G.W. 70PIECES", ekstrak "41.09").
    - Ekstrak nilai jumlah barang dari baris yang sama untuk mengisi `coo_quantity` (misalnya dari "70PIECES", ekstrak "70").
8. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KGS").
9. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
10. `coo_customer_po_no`: Biarkan null kecuali ada referensi nomor PO yang secara spesifik ditulis di dalam kolom 7 atau 8.
"""