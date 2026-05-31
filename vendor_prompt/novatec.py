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

    AREA A — kolom "Combined QTY", "Combined N.W", "Combined G.W" (dan CBM):
    Berisi ringkasan per-merge-group: [Combined QTY] [Combined N.W] [Combined G.W] [CBM]
    Nilai "Combined N.W" dan "Combined G.W" di sini adalah pl_nw dan pl_gw yang seharusnya
    untuk group tersebut. Nilai CBM muncul setelah Combined G.W.
    Nilai TOTAL CTNS (angka 1, 2, dsb) untuk group ini tetap dari kolom "TOTAL CTNS" main table.

    Cara menentukan batas merge group (WAJIB dilakukan sebelum assign nilai):
    - Hitung jumlah QTY beberapa baris berturut-turut sampai hasilnya cocok dengan "Combined QTY".
    - Contoh: Combined QTY = 754, baris A (qty=320) + B (qty=354) + C (qty=80) = 754 → A, B, C satu group.
    - Contoh: Combined QTY = 3, baris X (qty=2) + Y (qty=1) = 3 → X dan Y satu group.
    - PENTING: kesamaan PO number BUKAN penentu batas group. Verifikasi selalu dengan Combined QTY.
      Contoh: baris dengan PO berbeda bisa berada dalam satu merge group yang sama.

    AREA B — kolom "Combined QTY" + "Combined N.W" + "Combined G.W" tanpa CTNS, nilai besar:
    Ini adalah total keseluruhan untuk satu tipe item (misal semua wheelset = 78 QTY, 173.60 NW, 292.94 GW).
    JANGAN gunakan nilai ini — ini bukan per-group, ini akumulasi seluruh tipe item.
    Cara membedakan: jika Combined QTY = total seluruh baris bertipe sama dan tidak ada CTNS di tengahnya,
    nilai tersebut adalah AREA B dan harus diabaikan.

6. `pl_package_count`:
    - Ekstrak dari kolom "TOTAL CTNS" main table.
    - Untuk merged cell group: TOTAL CTNS diberikan ke baris PALING ATAS group, sisanya 0.
    - Batas group ditentukan dengan Combined QTY = sum QTY baris-baris dalam group (lihat STRUKTUR di atas).
7. `pl_nw`:
    - Untuk baris standalone (tidak ada merge): ekstrak dari kolom "TOTAL N.W." main table.
    - Untuk merged cell group: ambil nilai "Combined N.W" yang sesuai untuk group tersebut (identifikasi
      group dengan Combined QTY = sum QTY baris-baris group). Berikan ke baris PALING ATAS group, sisanya 0.
    - JANGAN gunakan nilai "Combined N.W" dari AREA B (total keseluruhan tipe item yang nilainya jauh lebih besar).
8. `pl_gw`:
    - Untuk baris standalone: ekstrak dari kolom "TOTAL G.W." main table.
    - Untuk merged cell group: ambil nilai "Combined G.W" yang sesuai untuk group tersebut.
      Berikan ke baris PALING ATAS group, sisanya 0.
    - JANGAN gunakan nilai "Combined G.W" dari AREA B.
9. `pl_volume`:
    - Untuk baris standalone: ekstrak dari kolom "TOTAL CBM" main table.
    - Untuk merged cell group: ambil nilai CBM yang muncul setelah "Combined G.W" untuk group tersebut.
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