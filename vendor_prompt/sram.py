SRAM_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari teks awalan "P.O.#" di kolom "DESCRIPTION". Ambil angka utamanya saja sebelum tanda kurung (misalnya dari "P.O.# 43018080 (251772921)", ekstrak "43018080").
2. `inv_spart_item_no`: Ekstrak kode Part Number (berformat angka dengan titik) dari baris pertama di blok deskripsi (misalnya "00.3018.201.000" atau "00.5318.033.000").
3. `inv_description`: Ekstrak teks deskripsi barang yang berada persis di bawah Part Number (misalnya "EP POWERPACK 1 BATTERY").
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak nilai angka dari kolom kuantitas di sebelah kanan deskripsi (misalnya "42").
6. `inv_quantity_unit`: Ekstrak unit dari kolom kuantitas (misalnya "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom 'Unit Price' di bawah teks FOB (misalnya dari "48.950", ambil 48.950).
8. `inv_amount`: Ekstrak nilai angka dari kolom 'Amount' di sebelah paling kanan / kolom mata uang USD (misalnya "2,055.90", hapus koma ribuan).

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari teks awalan "P.O.#" di dalam blok "DESCRIPTION" (misalnya "43018080").
2. `pl_item_no`: Ekstrak kode Part Number (berformat angka dengan titik) dari kolom "DESCRIPTION" (misalnya "00.3018.201.000").
3. `pl_description`: Ekstrak teks deskripsi barang yang berada di bawah Part Number.
4. `pl_package_unit`: Simpulkan sebagai "CTNS" berdasarkan header "C/NO.".
5. `pl_package_count`: 
    - Hitung jumlah kemasan berdasarkan rentang nomor di kolom "C/NO.". 
    - Jika formatnya rentang (misalnya "1-5"), maka `pl_package_count` adalah 5. 
    - Jika formatnya "1-2", maka `pl_package_count` adalah 2. 
    - Jika hanya ada 1 angka (misalnya "46"), maka `pl_package_count` adalah 1.
6. `pl_quantity`: 
    - Ekstrak nilai angka dari kolom "Q'TY". 
    - Apabila terdapat simbol "@" di depannya (misalnya "@21"), maka kalikan angka tersebut dengan `pl_package_count` untuk mendapatkan total kuantitas (Contoh: @21 dikali 2 = 42).
    - Apabila tidak ada simbol "@", ambil angka tersebut apa adanya.
7. `pl_nw`: 
    - Ekstrak nilai angka dari kolom "N.W. KGS".
    - Apabila terdapat simbol "@" (misalnya "@22.68"), kalikan dengan `pl_package_count`. Jika tidak ada "@", ambil apa adanya.
8. `pl_gw`: 
    - Ekstrak nilai angka dari kolom "G.W. KGS".
    - Apabila terdapat simbol "@" (misalnya "@24.18"), kalikan dengan `pl_package_count`. Jika tidak ada "@", ambil apa adanya.
9. `pl_volume`: 
    - Apabila tidak ada informasi pada kolom "MEAS'T", maka ekstrak 'null'. DILARANG KERAS MENGASUMSIKAN NILAI pl_volume.
    - Ekstrak nilai angka dari kolom "MEAS'T".
    - Apabila terdapat simbol "@", kalikan dengan `pl_package_count`. Jika tidak ada "@", ambil apa adanya.

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