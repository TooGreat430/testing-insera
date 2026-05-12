TRANSART_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari sel gabungan bertumpuk pada kolom pertama yang memuat tajuk Order No. dan SN. Ambil HANYA rangkaian angka PO-nya saja (misalnya dari visual sel bertumpuk "1 \\n 45326930", ekstrak string "45326930").
2. `inv_spart_item_no`: Ekstrak dari sel gabungan pada kolom kedua yang memuat Item No. dan deskripsi. Ambil HANYA string kode barang uniknya (biasanya berakhiran teks "-R" atau berawalan huruf "Z" seperti "ZDMR25FSE2R0-R" atau "ZMRN22W000-R.").
3. `inv_description`: Ekstrak teks deskripsi spesifikasi stiker/decal dari sel gabungan pada kolom kedua (misalnya "DCMR25FSE2R0 MARIN 2025 FAIRFAX SE GOLD HRNT"). Pisahkan secara cermat dari baris string kode barang.
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena dokumen invoice ini tidak mencantumkan informasi berat fisik pada tingkat baris item.
5. `inv_quantity`: Ekstrak murni nilai angka numerik dari kolom "Quantity" (misalnya "115", "6", "100").
6. `inv_quantity_unit`: Ekstrak satuan dari kolom "Unit" (misalnya "SET").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "UnitPrice" (hapus simbol mata uang seperti $).
8. `inv_amount`: 
    - Ekstrak nilai angka dari kolom "Amount" (hapus simbol mata uang seperti $ dan koma ribuan).
    - PENTING: Apabila sel pada kolom Amount bertuliskan teks string "F.O.C" (Free of Charge), maka outputkan nilai `inv_amount` sebagai angka 0.

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari kolom "Order No." (misalnya "45327360").
2. `pl_item_no`: Ekstrak string kode barang dari kolom "Item No." (misalnya "ZRE23CTYL1R1-R").
3. `pl_description`: Ekstrak teks deskripsi dari kolom "Description".
4. `pl_quantity`: Ekstrak nilai angka dari kolom "QTY". Perhatikan bahwa nilainya selalu ditulis menempel dengan string garis miring (misalnya "565/set" atau "28/set"), maka ekstrak HANYA angka numerik utamanya saja sebelum garis miring ("565" atau "28").
5. `pl_package_unit`: Simpulkan sebagai "CTNS" atau "CARTONS" berdasarkan tajuk kolom kemasan fisik "C/NO".
6. `pl_package_count`: 
    - Ekstrak jumlah fisik kemasan berdasarkan representasi di kolom "C/NO".
    - PENTING (Merged/Grouped Carton Logic): Berbagai line item yang berbeda sering dikelompokkan ke dalam satu kemasan fisik atau rentang karton yang sama (misalnya penulisan nomor karton tunggal "1", atau rentang bertumpuk vertikal "3 \\n 4"). Jika formatnya rentang kemasan, hitung total kuantitas karton dalam rentang tersebut.
    - Guna menghindari duplikasi agregasi (double-counting) pada grup item yang dimuat di dalam karton fisik yang sama, tetapkan output pemetaan `pl_package_count` hanya pada baris item paling atas dalam grup kemasan tersebut, dan biarkan baris item sisanya di bawahnya dalam grup yang sama bernilai null.
7. `pl_nw`: Ekstrak nilai angka dari kolom "N.W. (KGS)". Terapkan aturan pemetaan grup kemasan fisik yang sama persis seperti package count: nilainya hanya tertera satu kali untuk mewakili satu grup fisik kemasan, sehingga ambil murni angka pada baris visual yang terisi dan biarkan null untuk baris kosong di bawahnya.
8. `pl_gw`: Ekstrak nilai angka dari kolom "G.W. (KGS)". Terapkan aturan agregasi pemetaan grup kemasan fisik yang sama.
9. `pl_volume`: Ekstrak nilai angka numerik dari kolom "Measurement (Cu.Ft)". Terapkan aturan agregasi pemetaan grup kemasan fisik yang sama.

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
1. `coo_mark_number`: Ekstrak dari teks pada kolom "7. Marks and numbers on packages" (misalnya "N/M").
2. `coo_description`: Ekstrak murni uraian teks deskripsi barang dari kolom "8. Number and kind of packages; and description of goods." (misalnya "DECAL DCMR25FSE2RO MARIN 2025 FAIRFAX SE GOLD HRNT"). Abaikan string keterangan pembuka kuantitas paket di awal pengiriman serta string rujukan komersial di bawahnya seperti "(EXTRA DECAL OF NO COMMERCIAL VALUE)".
3. `coo_hs_code`: Ekstrak dari kolom "9. HS Code of the goods" (misalnya "4908.90").
4. `coo_package_count`: Ekstrak nilai angka dari untaian pembuka deklarasi kemasan di kolom 8 jika ada (misalnya dari teks "NINETEEN (19) CARTONS OF", ambil angka 19), atau biarkan null apabila tidak dideklarasikan spesifik pada rincian baris bersangkutan.
5. `coo_package_unit`: Ekstrak jenis kemasan dari rujukan di dalam kolom 8 (misalnya "CARTONS").
6. `coo_gw` & `coo_quantity`: 
    - Ekstrak murni nilai angka numerik dari kolom "12. Quantity..." untuk mengisi `coo_quantity` (misalnya dari string rapat "115SETS" atau susunan sel bertumpuk "6SETS \\n 100SETS", pisahkan dan ambil murni angka numeriknya saja secara berkorelasi sejajar dengan itemnya).
    - Biarkan `coo_gw` bernilai null karena skema Form RCEP ini mendeklarasikan besaran kuantitas kepingan satuan barang (SETS), bukan entitas berat fisik.
7. `coo_unit`: Ekstrak untaian teks satuan dari kolom 12 yang menempel langsung setelah angka (misalnya "SETS") dan bukan nilai numeriknya.
8. `coo_criteria`: Ekstrak string acuan kriteria asal dari kolom "10. Origin Conferring Criterion" (misalnya "PE").
9. `coo_customer_po_no`: Biarkan null kecuali terdapat rujukan penamaan PO secara eksplisit pada baris rincian bersangkutan.
"""