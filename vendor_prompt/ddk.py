DDK_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: 
    - Ekstrak dari baris block header di dalam tabel yang mendahului grup line item. Baris ini memuat referensi teks "Customer P/O No." atau "Customer P/O No" (misalnya dari baris teks "S/C NO. DE20251014001 Customer P/O No. 45322397", ekstrak HANYA angka "45322397").
    - Terapkan logika Contextual Inheritance: Setiap line item yang posisinya berada di bawah baris block header tersebut otomatis mewarisi (inherit) nilai `inv_customer_po_no` dari block header terakhir di atasnya.
2. `inv_spart_item_no`: Ekstrak dari kolom "Item No.". Ambil string kode utama/model pada baris pertama (misalnya "D5090/VXTB708B9BA2MRSA23" atau "DGT-2400/2400-1/BB") dan abaikan kode internal di dalam tanda kurung pada baris bawahnya (misal "(SDLFMD50900005)").
3. `inv_description`: Ekstrak teks deskripsi spesifikasi barang dari kolom "Description".
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak nilai angka numerik dari kolom "Quantity" (misalnya dari "500 PCS" atau teks bertumpuk "PCS \\n 303", ambil angka murninya saja seperti 500 atau 303).
6. `inv_quantity_unit`: Ekstrak satuan kemasan dari string pada kolom "Quantity" (misalnya "PCS", "PRS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Unit Price".
8. `inv_amount`: 
    - Ekstrak nilai angka dari kolom "Amount" (hapus koma ribuan).
    - PENTING: Apabila sel pada kolom Amount bertuliskan teks "FOC" (Free of Charge), maka outputkan nilai `inv_amount` sebagai angka 0.

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari baris block header yang memuat referensi "Customer P/O No." (misal "45322397") menggunakan logika Contextual Inheritance (pewarisan baris ke bawah) yang sama persis seperti pada dokumen Invoice.
2. `pl_item_no`: Ekstrak string kode barang utama dari kolom "Item No. (Cust item No.)/Desc" (misalnya "D5090/VXTB708B9BA2MRSA23").
3. `pl_description`: Ekstrak teks deskripsi barang yang berada di bawah item code pada kolom "Item No. (Cust item No.)/Desc".
4. `pl_quantity`: 
    - Ekstrak nilai angka dari kolom "Quantity".
    - PENTING (Stacked/Per-Carton Filtering Logic): Apabila dalam satu sel terdapat dua baris angka bertumpuk di mana baris atas memuat kapasitas per karton yang ditandai simbol "@" (misal "@30 PCS") dan baris bawah memuat total riil keseluruhan (misal "420 PCS"), maka ambil HANYA nilai angka pada baris bawah yang TIDAK memiliki simbol "@" sebagai total kuantitas akhir. Abaikan sepenuhnya baris teks/angka yang mengandung simbol "@".
    - Apabila baris item tersebut hanya memuat satu baris angka (kemasan tunggal), ambil angka tersebut secara langsung.
5. `pl_package_unit`: Simpulkan sebagai "CTNS" atau "CARTONS" berdasarkan tajuk kolom kemasan utama.
6. `pl_package_count`: 
    - Ekstrak nilai angka dari dalam tanda kurung yang terletak tepat di bawah rentang penamaan karton pada kolom "Carton No." (misalnya dari teks "B1-B14 \\n (14)", ekstrak angka 14).
    - Apabila pada baris tersebut tidak terdapat tanda kurung (mewakili karton tunggal seperti "B15"), maka isi `pl_package_count` dengan angka 1.
7. `pl_nw`: 
    - Ekstrak nilai angka dari kolom "N.W. (KGS)".
    - Terapkan aturan pemfilteran simbol "@" yang konsisten: ambil HANYA nilai di baris bawah yang TIDAK memiliki simbol "@" (mewakili total Net Weight riil). Abaikan baris yang bersimbol "@".
8. `pl_gw`: 
    - Ekstrak nilai angka dari kolom "G.W. (KGS)".
    - Ambil HANYA nilai di baris bawah yang TIDAK memiliki simbol "@" (misal dari teks "@10.10 \\n 141.40", ekstrak murni angka 141.40). Abaikan baris bersimbol "@".
9. `pl_volume`: 
    - Ekstrak nilai angka dari kolom "Meas'm (CUFT)" atau "Meas".
    - Ambil HANYA nilai di baris bawah yang TIDAK memiliki simbol "@" (misal dari teks "@2.491 \\n 34.868", ekstrak murni angka 34.868). Abaikan baris bersimbol "@".

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
1. `coo_mark_number`: Ekstrak dari kolom "Marks and Numbers" jika memuat penanda spesifik per item, atau biarkan null jika berupa teks gabungan pengiriman umum.
2. `coo_description`: Ekstrak teks deskripsi barang utama dari kolom "Description" (misalnya "BICYCLE PARTS-BICYCLE SADDLE D5090/VXTB708B9BA2MRSA23").
3. `coo_hs_code`: Ekstrak dari kolom "HS Number" (misalnya "87149590").
4. `coo_package_count`: Biarkan null karena dokumen e-COO ATIGA ini tidak memuat perincian jumlah karton di tingkat baris item secara terpisah.
5. `coo_package_unit`: Biarkan null.
6. `coo_quantity`: Ekstrak nilai angka numerik riil dari kolom "Quantity" (misalnya dari format "500.0000", ekstrak murni angka 500).
7. `coo_gw`: Ekstrak nilai angka riil dari kolom "Gross weight or Other Quantity" (misal dari "167.3300", ekstrak angka 167.33).
8. `coo_unit`: Ekstrak satuan string dari kolom "Weight Code or Unit of Measurement" (misalnya "KGM") atau dari kolom "Quantity Code" (misal "H87" atau "PR") jika relevan untuk konteks pemetaan kuantitas.
9. `coo_criteria`: Ekstrak dari kolom "Origin Criterion". Ambil hanya string kode kriteria utamanya saja tanpa persentase (misalnya jika tertulis "RVC \\n 66.79%", maka ekstrak teks "RVC").
10. `coo_customer_po_no`: Biarkan null karena dokumen e-COO INSW ini memuat kumpulan referensi PO di tingkat rincian pengiriman umum dan tidak dipetakan langsung per sel baris item.
"""