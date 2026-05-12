VN_TOP_POINT_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari kolom "PO NO:". Apabila dalam satu sel terdapat beberapa nomor PO yang dipisahkan oleh garis miring "/" (misalnya "45321386/45321766/45322726/"), ekstrak seluruh string tersebut atau pisahkan sesuai pemetaan baris.
2. `inv_spart_item_no`: Ekstrak dari kolom "PRODUCT NO:" (misalnya "HG078(TP-T-9012 BLACK)" atau "IS18PRE03-1(JD-9F-0493)-R/L"). Abaikan teks pada kolom "ITEM NAME:" karena merupakan kode internal pabrik.
3. `inv_description`: Ekstrak deskripsi barang dari kolom "DESCRIPTION" (misalnya "FRAME PART").
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena dokumen invoice ini tidak mencantumkan informasi berat pada tingkat baris item.
5. `inv_quantity`: Ekstrak nilai angka numerik dari kolom "Q'TY".
6. `inv_quantity_unit`: Ekstrak satuan dari kolom "UNIT" (misalnya "SET", "PRS", "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "U/PRICE USD".
8. `inv_amount`: Ekstrak nilai angka dari kolom "AMOUNT USD" (hapus tanda koma ribuan).

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari kolom "PO NO:".
2. `pl_item_no`: Ekstrak dari kolom "PRODUCT NO:".
3. `pl_description`: Ekstrak dari teks kolom "ITEM NAME:" atau "PRODUCT NO:" yang mendefinisikan identitas barang.
4. `pl_quantity`: Ekstrak nilai angka dari kolom "QUANTITY" sub-kolom "Q'TY" atau teks kuantitas baris.
5. `pl_package_unit`: Simpulkan sebagai "CTN" atau "CARTONS" berdasarkan tajuk sub-kolom kemasan.
6. `pl_package_count`: 
    - Ekstrak nilai angka dari kolom kemasan/karton yang tertera di bawah tajuk "TTL CTN" atau sejenisnya.
    - PENTING (Grouped Rows Logic): Dokumen ini mendaftar item yang sama berulang kali untuk PO yang berbeda, dan meletakkan total data kemasan pada baris subtotal/terakhir di blok grup tersebut. Ambil nilai `pl_package_count` dari baris rangkuman/subtotal grup tersebut untuk memetakan total karton per item.
7. `pl_nw`: Ekstrak nilai angka dari kolom "N.W KGS" yang terletak pada baris rangkuman/subtotal grup item bersangkutan.
8. `pl_gw`: Ekstrak nilai angka dari kolom "G.W KGS" yang terletak pada baris rangkuman/subtotal grup item bersangkutan.
9. `pl_volume`: Ekstrak nilai angka dari kolom "CFT" yang terletak pada baris rangkuman/subtotal grup item bersangkutan.

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
1. `coo_mark_number`: Ekstrak teks dari kolom "6. Marks and numbers on packages" (misalnya "NO MARK").
2. `coo_description`: Ekstrak murni teks nama/deskripsi barang dari baris atas pada kolom "7. Number and type of packages, description of goods" (misalnya "FRAME PART HG078(TP-T-9012 BLACK)"). Abaikan string baris referensi nomor invoice, HS CODE, dan tanggal yang berada di bawahnya.
3. `coo_hs_code`: Ekstrak string angka yang berawalan teks "HS CODE:" di dalam kolom 7 (misalnya dari teks "HS CODE: 87149199", ekstrak "87149199").
4. `coo_package_count`: Biarkan null karena tidak selalu dideklarasikan di tingkat item.
5. `coo_package_unit`: Biarkan null.
6. `coo_gw` & `coo_quantity`: 
    - Ekstrak nilai angka numerik dari kolom "9. Gross weight or other quantity..." untuk mengisi `coo_quantity` (misal dari teks "5,540.00 SET", ekstrak angka 5540).
    - Biarkan `coo_gw` bernilai null karena dokumen Form D ini mencantumkan besaran kuantitas satuan barang (SET/PAIR/PIECE), bukan berat fisik.
7. `coo_unit`: Ekstrak satuan string dari kolom 9 yang berada setelah angka (misalnya "SET", "PAIR", "PIECE").
8. `coo_criteria`: Ekstrak dari kolom "8. Origin criterion" (misalnya dari teks "RVC 96.77%", ekstrak "RVC").
9. `coo_customer_po_no`: Biarkan null kecuali terdapat referensi eksplisit penamaan PO pada baris item bersangkutan.
"""