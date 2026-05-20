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
    PRINSIP UTAMA — KOLOM "C/NO" ADALAH ID/LABEL NOMOR KARTON, BUKAN ANGKA JUMLAH KARTON.
    Setiap nilai unik pada kolom C/NO mewakili SATU karton fisik. Angka "19" di kolom C/NO adalah ID karton ke-19, BUKAN "19 karton".

    ATURAN PARSING NILAI KOLOM C/NO PER BARIS:
    - Jika sel C/NO berisi 1 angka tunggal (contoh: "1", "5", "19")
        → pl_package_count = 1
        (Baris ini memakai 1 karton. JANGAN output 19 hanya karena teks selnya "19".)
    - Jika sel C/NO berisi rentang dengan dash (contoh: "1-2", "10-12", "5-8")
        → pl_package_count = (angka akhir) − (angka awal) + 1
        contoh: "1-2" → 2;  "10-12" → 3;  "5-8" → 4.
    - Jika sel C/NO KOSONG / BLANK (baris kelanjutan dari karton di atasnya)
        → pl_package_count = 0
        Hal ini mencegah double-counting. Hanya baris invoice PERTAMA dari setiap karton yang "mengklaim" 1 karton.

    CONTOH KONKRET DARI DOKUMEN INI (sangat penting untuk diingat):
    Cuplikan PL untuk C/NO 7 berisi 4 baris item (1 baris pertama bernilai "7" pada kolom C/NO, 3 baris berikutnya kosong):
        C/NO=7 | 45326934 | ZDMR26DS2AR1-R | DCMR26DS2AR1 MARIN 2026 DSX 2 HRNT       | 100/set | NW 23.00  GW 24.00  VOL 1.60
        C/NO=  | 45326934 | ZDMR26DS2AR1-R | DCMR26DS2AR1 MARIN 2026 DSX 2 HRNT       |   5/set |
        C/NO=  | 45326934 | ZDMR26DSBAR1-R | DCMR26DSBAR1 MARIN 2026 DSX BASE HRNT    |   5/set |
        C/NO=  | 45326934 | ZDMR26DSBAR1-R | DCMR26DSBAR1 MARIN 2026 DSX BASE HRNT    |  60/set |
    Output yang BENAR:
        Baris #1 (100/set):  pl_package_count = 1   ← BUKAN 7. "7" adalah label karton, hasilnya tetap 1.
        Baris #2 (5/set):    pl_package_count = 0
        Baris #3 (5/set):    pl_package_count = 0
        Baris #4 (60/set):   pl_package_count = 0
    Verifikasi: jumlah pl_package_count dari SELURUH baris (88 baris) harus = total karton dokumen = 19 (sesuai keterangan "SAY TOTAL NINETEEN CARTONS ONLY" di bawah tabel PL).

    DILARANG KERAS:
    - Mengambil nilai literal angka di sel C/NO sebagai pl_package_count. Untuk C/NO "19", JANGAN output 19; output yang BENAR adalah 1.
    - Menjumlahkan pl_package_count pada lebih dari satu baris dalam grup karton yang sama.

7. `pl_nw`:
    Ekstrak nilai angka dari kolom "N.W. (KGS)".
    ATURAN PER-KARTON (sama persis seperti pl_package_count): nilai N.W. tertulis HANYA SEKALI pada baris pertama setiap blok C/NO. Untuk baris kelanjutan (C/NO kosong), pl_nw = null (atau 0 jika sistem menolak null).
    Contoh untuk C/NO 7 (lihat di atas): Baris #1 pl_nw = 23.00; Baris #2/#3/#4 pl_nw = null.

8. `pl_gw`:
    Ekstrak nilai angka dari kolom "G.W. (KGS)". Terapkan aturan per-karton yang sama persis seperti pl_nw — hanya baris pertama setiap blok C/NO yang terisi, sisanya null.
    Contoh C/NO 7: Baris #1 pl_gw = 24.00; Baris #2/#3/#4 pl_gw = null.

9. `pl_volume`:
    Ekstrak nilai angka dari kolom "Measurement (Cu.Ft)". Terapkan aturan per-karton yang sama persis — hanya baris pertama setiap blok C/NO yang terisi, sisanya null.
    Contoh C/NO 7: Baris #1 pl_volume = 1.60; Baris #2/#3/#4 pl_volume = null.

CATATAN URUTAN PENCOCOKAN INV ↔ PL:
Urutan baris di Invoice (urut per Order No. lalu paid+F.O.C.) sering BERBEDA dari urutan di Packing List (urut per karton). Saat memetakan tiap baris invoice ke baris PL-nya:
- Jodohkan dulu berdasarkan kombinasi (pl_customer_po_no + pl_item_no + pl_quantity) yang paling cocok.
- Setelah pasangan PL ketemu, BARU tentukan apakah baris PL itu adalah baris PERTAMA dalam blok C/NO-nya (pl_package_count = 1, pl_nw/gw/volume terisi) atau baris kelanjutan (pl_package_count = 0, pl_nw/gw/volume = null).

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