TAISHAN_SHANGHONG_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari kolom "PO NO". Apabila dalam satu baris/sel terdapat beberapa nomor PO yang ditulis bertumpuk secara vertikal (misalnya "45328183 \\n 45328185 \\n 45328209"), ekstrak seluruh string tersebut atau pisahkan secara sejajar (line-by-line) sesuai item pasangannya.
2. `inv_spart_item_no`: Ekstrak string kode part pendek yang terletak pada kolom setelah PO NO / di area awal kolom deskripsi (misalnya "IS19PHT10-110-A", "IS21PHT03-110-B", "HT-024-170").
3. `inv_description`: Ekstrak uraian teks deskripsi spesifikasi panjang yang terletak di bagian kanan tabel atau di bawah baris item bersangkutan (misalnya "PIPE H/T HONG ZHUO; IS19PHT10-110-A; AL6061; RAW LENGTH..."). Gabungkan teks menjadi satu kalimat utuh jika terputus baris baru.
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena dokumen invoice ini tidak mencantumkan informasi berat fisik pada tingkat baris item.
5. `inv_quantity`: Ekstrak nilai angka numerik dari kolom "QTY" (misalnya "90", "35", "140").
6. `inv_quantity_unit`: Ekstrak satuan string dari kolom di sebelah kanan angka QTY (misalnya "PCS", "SETS", atau teks typo "PARS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "UNIT PRICE IN USD" (hapus simbol mata uang jika terbaca).
8. `inv_amount`: Ekstrak nilai angka dari kolom "TOTAL AMOUNT USD" (hapus awalan string mata uang seperti "US$" dan koma ribuan).

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari kolom "PO NO.". Apabila terdapat beberapa nomor PO bertumpuk, ambil sesuai pemetaan baris item.
2. `pl_item_no`: Ekstrak string kode part dari kolom "DESCRIPTION OF GOODS" (misalnya "IS19PHT10-110-A").
3. `pl_description`: Ekstrak teks dari kolom "DESCRIPTION OF GOODS". Karena dokumen PL ini umumnya hanya mencantumkan part code di tingkat baris, nilainya dapat sama dengan `pl_item_no` atau memuat uraian singkat yang tersedia.
4. `pl_quantity`: Ekstrak nilai angka numerik dari kolom "QTY".
5. `pl_package_unit`: Simpulkan sebagai "CTN" atau "CARTONS" berdasarkan tajuk kolom paling kanan ("CTN").
6. `pl_package_count`: 
    - Ekstrak nilai angka kemasan dari kolom "CTN" (misalnya "1").
    - Apabila beberapa baris item dikelompokkan ke dalam satu sel kemasan yang di-merge secara vertikal, pastikan nilai karton diekstrak secara berkorelasi tanpa menduplikasi total kuantitas kemasan pengiriman.
7. `pl_nw`: Ekstrak nilai angka dari kolom "NW.(KG)" atau "NW.(KGS)".
8. `pl_gw`: Ekstrak nilai angka dari kolom "GW.(KGS)".
9. `pl_volume`: Biarkan null karena tidak terdapat kolom besaran CBM/Measure per baris pada dokumen Packing List ini.

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
1. `coo_mark_number`: Ekstrak teks dari kolom "6. Marks and numbers on packages" (misalnya teks "PT.IS \\n DESTINATION: SURABAYA").
2. `coo_description`: Ekstrak murni teks deskripsi barang dari kolom "7. Number and type of packages, description of goods" (misalnya "FRAME PART; HONG ZHUO; IS19PHT10-110-A;- AL6061...").
3. `coo_hs_code`: Ekstrak string angka dari referensi "HS CODE:" yang tertera di dalam kolom 7 (misalnya dari teks "HS CODE: 8714.91", ekstrak "8714.91").
4. `coo_package_count`: Biarkan null jika tidak dideklarasikan spesifik per item.
5. `coo_package_unit`: Biarkan null.
6. `coo_quantity`: Ekstrak murni nilai angka numerik dari kolom "9. Gross weight or other quantity" (misalnya dari sel bertumpuk "90PIECES", ekstrak angka 90).
7. `coo_unit`: Ekstrak teks satuan dari kolom 9 yang menempel pada angka (misalnya "PIECES", "PAIRS", "SETS") dan bukan nilai numeriknya.
8. `coo_gw`: Ekstrak nilai angka dari sub-baris berat di kolom sebelahnya jika relevan secara pemetaan, atau biarkan null jika rancangan sistem memprioritaskan kuantitas kepingan.
9. `coo_criteria`: Ekstrak string kode dari kolom "8. Origin criterion" (misalnya "PE" atau "RCEP").
10. `coo_customer_po_no`: Biarkan null kecuali terdapat rujukan eksplisit penamaan PO pada baris item bersangkutan di dalam kolom 7.
""" 