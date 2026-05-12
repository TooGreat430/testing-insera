CHENGS_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari baris teks berawalan "Customer P/O No." yang berada di dalam blok deskripsi. Nilainya memuat nomor referensi internal diikuti garis miring "/" lalu nomor PO utama (misalnya "Customer P/O No.C25-1155T/45318739"). Ambil HANYA angka PO yang terletak setelah garis miring "/" (misalnya ekstrak "45318739").
2. `inv_spart_item_no`: Ekstrak dari teks kode unik barang. Bisa diambil dari baris "Item No." di atas deskripsi (misal "CWSSXD44A001-44T170") atau dari baris terbawah pada blok deskripsi yang diawali dengan "** CODE:" / "** Code:" (misalnya dari "** CODE:SPXIMPLYX00000-R", ekstrak string kodenya saja).
3. `inv_description`: Ekstrak teks deskripsi spesifikasi barang dari blok kolom "Description". Abaikan baris referensi Customer P/O No, Seq, Item No, dan baris ** CODE di bawahnya.
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak nilai angka numerik dari kolom "Quantity" (misalnya dari teks "98 GRO" atau "200 SET", ambil angka 98 atau 200).
6. `inv_quantity_unit`: Ekstrak satuan string dari kolom "Quantity" yang letaknya berdampingan dengan angka (misalnya "GRO", "SET", "PCE").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Unit Price".
8. `inv_amount`: Ekstrak nilai angka dari kolom "Amount" (hapus teks tajuk mata uang seperti "(NT$)" dan tanda koma ribuan).

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari baris teks berawalan "Customer P/O No." di dalam blok kolom "Item No./Description". Ambil HANYA angka PO yang terletak setelah garis miring "/" (misal "45318739").
2. `pl_item_no`: Ekstrak string kode barang yang tertera di dalam blok kolom "Item No./Description" (misalnya dari baris awalan "** CODE:" atau referensi Item No utama).
3. `pl_description`: Ekstrak teks deskripsi barang utama dari kolom "Item No./Description".
4. `pl_quantity`: 
    - Ekstrak nilai angka dari kolom "Quantity".
    - Apabila dalam satu sel terdapat baris atas dengan simbol "@" (misal "@20.0 SET") dan baris bawah tanpa simbol "@" (misal "200 SET"), maka ambil HANYA angka numerik pada baris yang TIDAK memiliki simbol "@" (baris bawah) sebagai total kuantitas. Abaikan sepenuhnya baris yang mengandung simbol "@".
5. `pl_package_unit`: Simpulkan sebagai "CTNS" atau "CARTONS" berdasarkan konteks dokumen.
6. `pl_package_count`: 
    - Ekstrak nilai angka dari keterangan di dalam tanda kurung pada kolom "Carton No." yang terletak tepat di bawah rentang kemasan (misalnya dari teks "CW1-CW10 \\n (10)", ekstrak angka 10).
    - Apabila pada baris item tersebut tidak terdapat tanda kurung (misalnya kemasan tunggal seperti "CA114" atau "SP1"), maka isi `pl_package_count` dengan angka 1.
7. `pl_nw`: 
    - Ekstrak nilai angka dari kolom "N.W. (KGS)".
    - Terapkan pemfilteran simbol "@" yang sama persis seperti pada kolom kuantitas: ambil HANYA nilai di baris bawah yang TIDAK memiliki simbol "@" (mewakili total Net Weight). Abaikan baris bersimbol "@".
8. `pl_gw`: 
    - Ekstrak nilai angka dari kolom "G.W. (KGS)".
    - Ambil HANYA nilai di baris bawah yang TIDAK memiliki simbol "@" (mewakili total Gross Weight). Abaikan baris bersimbol "@".
9. `pl_volume`: 
    - Ekstrak nilai angka dari kolom "Meas'mt (CUFT)".
    - Ambil HANYA nilai di baris bawah yang TIDAK memiliki simbol "@" (mewakili total volume/pengukuran). Abaikan baris bersimbol "@".

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

"""