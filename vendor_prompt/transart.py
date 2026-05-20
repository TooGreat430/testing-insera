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

    ATURAN ALOKASI PER-KARTON (BUKAN PER-ITEM):
    Untuk SETIAP karton C/NO (1, 2, 3, ..., 19), TEPAT SATU baris invoice yang akan mengklaim karton itu dengan pl_package_count = 1. SEMUA baris invoice lain yang menempati karton tersebut (terlepas dari apakah produknya sama atau beda, terlepas dari apakah paid atau F.O.C.) WAJIB pl_package_count = 0.

    Cara memilih baris invoice yang mengklaim karton:
    - Lihat blok karton di PL — baris PL paling atas dalam blok itu (yang sel "C/NO"-nya terisi label angka, bukan blank).
    - Cocokkan baris PL atas itu ke baris invoice yang sama (berdasarkan po_no + item_no + quantity).
    - Baris invoice yang cocok dengan baris PL atas blok karton itulah yang menerima pl_package_count = 1.
    - Baris invoice lain yang termasuk dalam karton yang sama (baik produk yang sama maupun produk yang berbeda di dalam blok karton itu) = 0.

    PARSING NILAI KOLOM C/NO PADA BARIS PL:
    - Sel C/NO berisi 1 angka tunggal (contoh: "1", "5", "19") → karton ini = 1.
    - Sel C/NO berisi rentang dengan dash (contoh: "1-2", "10-12", "5-8") → karton ini = (akhir − awal + 1).
    - Sel C/NO kosong/blank → baris kelanjutan, tidak menambah hitungan karton.

    CONTOH KONKRET #1 — KARTON DENGAN PAID+FOC DARI 1 PRODUK (C/NO 7):
    Cuplikan PL untuk C/NO 7:
        C/NO=7 | 45326934 | ZDMR26DS2AR1-R   | DCMR26DS2AR1 MARIN 2026 DSX 2 HRNT     | 100/set | NW 23  GW 24  VOL 1.6
        C/NO=  | 45326934 | ZDMR26DS2AR1-R   | DCMR26DS2AR1 MARIN 2026 DSX 2 HRNT     |   5/set |
        C/NO=  | 45326934 | ZDMR26DSBAR1-R   | DCMR26DSBAR1 MARIN 2026 DSX BASE HRNT  |   5/set |
        C/NO=  | 45326934 | ZDMR26DSBAR1-R   | DCMR26DSBAR1 MARIN 2026 DSX BASE HRNT  |  60/set |
    Baris invoice yang relevan: #3 (DSX 2 100 paid), #4 (DSX 2 5 FOC), #5 (DSX BASE 60 paid), #6 (DSX BASE 5 FOC).
    Output yang BENAR (hanya #3 yang klaim, sisanya 0 — termasuk DSX BASE walaupun produk berbeda):
        Baris #3 (DSX 2 100 paid): pl_package_count = 1
        Baris #4 (DSX 2 5 FOC):    pl_package_count = 0
        Baris #5 (DSX BASE 60 paid): pl_package_count = 0    ← produk berbeda TAPI di karton yang sama, jadi 0
        Baris #6 (DSX BASE 5 FOC):   pl_package_count = 0

    CONTOH KONKRET #2 — KARTON DENGAN 2 PRODUK YANG TERPISAH JAUH DI INVOICE (C/NO 19, KASUS YANG SERING SALAH):
    Cuplikan PL untuk C/NO 19:
        C/NO=19 | 45326930 | ZDMR25FSE2R0-R | DCMR25FSE2R0 MARIN 2025 FAIRFAX SE GOLD HRNT |   6/set | NW 15  GW 16  VOL 1.6
        C/NO=   | 45326930 | ZDMR25FSE2R0-R | DCMR25FSE2R0 MARIN 2025 FAIRFAX SE GOLD HRNT | 115/set |
        C/NO=   | 45327363 | ZDPL26STSBR1-R | DCPL26STSBR1 POLYGON 2026-STRATTOS S HRTF-HI | 100/set |
        C/NO=   | 45327363 | ZDPL26STSBR1-R | DCPL26STSBR1 POLYGON 2026-STRATTOS S HRTF-HI |   5/set |
    Baris invoice yang relevan: #1 (GOLD HRNT 115 paid), #2 (GOLD HRNT 6 FOC), #75 (STSBR1 100 paid), #76 (STSBR1 5 FOC).
    Catatan: GOLD HRNT ada di awal invoice (#1-2), STSBR1 ada di tengah/akhir invoice (#75-76), TAPI keduanya sama-sama dimuat di C/NO 19.
    Output yang BENAR (hanya 1 baris yang klaim untuk seluruh C/NO 19):
        Baris #1 (GOLD HRNT 115 paid): pl_package_count = 1   ← baris PL atas blok C/NO 19 cocok dengan invoice ini (PO 45326930 + GOLD HRNT)
        Baris #2 (GOLD HRNT 6 FOC):    pl_package_count = 0
        Baris #75 (STSBR1 100 paid):   pl_package_count = 0   ← walaupun produk berbeda, ini masih dalam C/NO 19 yang sudah diklaim baris #1
        Baris #76 (STSBR1 5 FOC):      pl_package_count = 0

    VERIFIKASI: jumlah pl_package_count dari SELURUH baris (88 baris) = total karton dokumen = 19 (sesuai "SAY TOTAL NINETEEN CARTONS ONLY"). Jangan sampai 38 (= 2× over-claim karena tiap produk diklaim sendiri-sendiri di dalam karton yang sama).

    DILARANG KERAS:
    - Mengambil nilai literal angka di sel C/NO sebagai pl_package_count. Untuk C/NO "19", output yang benar adalah 1, BUKAN 19.
    - Memberikan pl_package_count > 0 pada LEBIH DARI SATU baris invoice yang berada di karton C/NO yang sama, walaupun produk-nya berbeda. 1 karton = 1 klaim, titik.

7. `pl_nw`:
    Ekstrak nilai angka dari kolom "N.W. (KGS)" pada baris PL atas blok karton (baris dengan C/NO yang terisi).
    ATURAN ALOKASI PER-KARTON (sama persis seperti pl_package_count): nilai N.W. SATU karton WAJIB ditempatkan HANYA pada SATU baris invoice — yaitu baris invoice yang juga mengklaim pl_package_count untuk karton itu. SEMUA baris invoice lain di karton yang sama (apapun produknya) = null/0.

    CONTOH untuk C/NO 19 (NW=15):
        Baris #1 (GOLD HRNT 115 paid): pl_nw = 15
        Baris #2 (GOLD HRNT 6 FOC):    pl_nw = null
        Baris #75 (STSBR1 100 paid):   pl_nw = null    ← walaupun produk berbeda, NW sudah diklaim baris #1
        Baris #76 (STSBR1 5 FOC):      pl_nw = null
    Verifikasi: sum semua pl_nw = NW masing-masing karton, totalnya = pl_total_nw doc (452 untuk dokumen ini), bukan 2× (888).

    DILARANG KERAS memberikan pl_nw > 0 pada lebih dari satu baris invoice dalam karton yang sama.

8. `pl_gw`:
    Ekstrak dari kolom "G.W. (KGS)". Aturan alokasi PER-KARTON yang sama persis seperti pl_nw — hanya 1 baris invoice per karton yang terisi, sisanya null/0.
    CONTOH C/NO 19 (GW=16): Baris #1 = 16; Baris #2, #75, #76 = null.

9. `pl_volume`:
    Ekstrak dari kolom "Measurement (Cu.Ft)". Aturan alokasi PER-KARTON yang sama persis.
    CONTOH C/NO 19 (CFT=1.6): Baris #1 = 1.6; Baris #2, #75, #76 = null.

CATATAN URUTAN PENCOCOKAN INV ↔ PL:
Urutan baris di Invoice (per Order No. paid+F.O.C.) BERBEDA dari urutan di Packing List (per karton). Banyak karton di PL berisi 2 atau lebih produk yang di invoice letaknya berjauhan.
Langkah pencocokan:
1. Untuk setiap karton C/NO di PL, identifikasi baris PL paling atas dalam blok (yang sel "C/NO"-nya terisi angka).
2. Cari baris invoice yang cocok dengan baris PL atas itu (po_no + item_no + quantity).
3. Baris invoice itulah yang menerima pl_package_count = 1, pl_nw, pl_gw, pl_volume.
4. SEMUA baris invoice lain yang termasuk karton itu (entah lanjutan paid/FOC dari produk yang sama, ATAU produk lain yang dimuat bersama di karton itu) = 0/null untuk SEMUA 4 field tersebut.

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