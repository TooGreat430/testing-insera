VN_TOP_POINT_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`:
    Ekstrak dari kolom "PO NO:".
    FORMAT MULTI-PO (banyak baris invoice di vendor ini menggabungkan beberapa PO untuk 1 item):
    - Jika sel "PO NO:" berisi beberapa PO yang dipisahkan slash "/", contoh "45321386/45321766/45322726/45323418/45323665/45323664/" (kadang ada trailing slash di akhir),
    - NORMALISASI: hilangkan trailing slash, lalu ekstrak PO PERTAMA (sebelum slash pertama).
    - Contoh: "45321386/45321766/45322726/" → inv_customer_po_no = "45321386"
    - Contoh: "45323666/45323664/" → inv_customer_po_no = "45323666"
    - Contoh: "45324747" (single PO) → inv_customer_po_no = "45324747"
    Konsisten ini PENTING agar nilai dapat dipasangkan dengan master PO. DILARANG KERAS menyimpan multi-PO sebagai 1 string utuh.
2. `inv_spart_item_no`: Ekstrak dari kolom "PRODUCT NO:" (misalnya "HG078(TP-T-9012 BLACK)" atau "IS18PRE03-1(JD-9F-0493)-R/L"). Abaikan teks pada kolom "ITEM NAME:" karena merupakan kode internal pabrik.
3. `inv_description`: Ekstrak deskripsi barang dari kolom "DESCRIPTION" (misalnya "FRAME PART").
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena dokumen invoice ini tidak mencantumkan informasi berat pada tingkat baris item.
5. `inv_quantity`: Ekstrak nilai angka numerik dari kolom "Q'TY".
6. `inv_quantity_unit`: Ekstrak satuan dari kolom "UNIT" (misalnya "SET", "PRS", "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "U/PRICE USD".
8. `inv_amount`: Ekstrak nilai angka dari kolom "AMOUNT USD" (hapus tanda koma ribuan).

PACKING LIST (PL):

STRUKTUR FILE PL — PENTING:
File Packing List Vietnam Top Point menggunakan format PALLET-GROUPED. Pengiriman dibagi menjadi beberapa PALLET (contoh: TP01, TP02, TP03), dan setiap pallet adalah 1 BLOK rangkuman.

Layout per blok pallet:
- Beberapa baris item per PO (1 item bisa muncul berulang untuk PO berbeda)
- Di sisi kanan blok, ada 1 baris RANGKUMAN PALLET berisi nilai agregat untuk SELURUH pallet itu:
    * Q'TY PCS    : total quantity dalam pallet
    * PCS CTN     : total carton count dalam pallet  ← inilah pl_package_count per-pallet
    * TTL         : 1 (jumlah pallet di baris itu, selalu 1)
    * C/NO        : label pallet, contoh "TP01"
    * N.W KGS     : net weight pallet
    * G.W KGS     : gross weight pallet
    * CFT         : volume pallet (cubic feet)

Contoh dari dokumen ini (3 pallet):
- TP01 — Q'TY=14240, CTN=44, NW=433, GW=441, CFT=1.
    Mencakup invoice item #1 (HG078), #2 (IS18PHG02), #3 sebagian (IS18PRE03-1 yang 3000 SET pertama).
- TP02 — Q'TY=4052, CTN=54, NW=602, GW=610, CFT=1.
    Mencakup invoice item #3 sisa (IS18PRE03-1 yang 2000 SET), #4–#9, #10 sebagian (A-F3620-G 250 PRS).
- TP03 — Q'TY=5462, CTN=55, NW=584, GW=592, CFT≈sisa hingga grand total 4.29.
    Mencakup invoice item #10 sisa, #11–#24.

Baris GRAND TOTAL di paling bawah PL: 23754 PCS, 153 CTN, 3 pallets, NW=1618.99, GW=1642.99, CFT=4.29.

1. `pl_customer_po_no`: Ekstrak nilai PO dari kolom "PO NO:" pada baris item PL yang sesuai. PL ini SUDAH memecah item per PO, jadi nilainya single PO per baris (tanpa slash).

2. `pl_item_no`: Ekstrak dari kolom "PRODUCT NO:".

3. `pl_description`: Ekstrak dari kolom "ITEM NAME:" atau "PRODUCT NO:".

4. `pl_quantity`:
    Ekstrak total quantity untuk pasangan invoice line item tersebut.
    Karena invoice MENGGABUNGKAN quantity dari banyak PO dalam 1 baris, dan PL MEMECAH-nya per PO, maka pl_quantity = jumlah total quantity dari semua sub-baris PL yang memiliki item_no yang sama dengan invoice line tersebut.
    Contoh: Invoice baris #1 HG078 5540 SET. PL memiliki 9 sub-baris HG078 (815+12+1550+100+755+555+1319+400+34 = 5540). → pl_quantity = 5540.

5. `pl_package_unit`: "CTN" atau "CARTONS" sesuai header sub-kolom "PCS CTN".

6. `pl_package_count`:
    ATURAN ALOKASI PALLET (KHUSUS VENDOR INI):
    - Setiap PALLET (TP01, TP02, TP03, dst) memiliki 1 nilai agregat di kolom "PCS CTN" yang merepresentasikan total carton untuk SELURUH pallet itu.
    - Untuk setiap pallet, IDENTIFIKASI baris invoice PERTAMA yang memiliki sub-baris di pallet tersebut (full atau partial). Tempatkan SELURUH nilai CTN pallet pada baris invoice itu.
    - Semua baris invoice LAIN yang termasuk pallet yang sudah terklaim diisi 0.
    - DILARANG KERAS:
        * Mengambil nilai TTL (1) sebagai pl_package_count — itu adalah jumlah pallet, BUKAN carton.
        * Mengambil nilai 3 (grand total pallets) sebagai pl_package_count baris manapun.
        * Membagi/distribusi proporsional nilai carton ke setiap baris invoice.

    CONTOH KONKRET (3 pallet, 24 baris invoice):
        Pallet TP01 (CTN=44):
            → Baris invoice #1 (HG078, item pertama yang ada di TP01): pl_package_count = 44
            → Baris #2 (IS18PHG02), #3 (IS18PRE03-1): pl_package_count = 0
        Pallet TP02 (CTN=54):
            → Baris invoice #4 (IS24PFE01, baris pertama yang sepenuhnya di TP02 karena #3 sudah di-claim TP01): pl_package_count = 54
                (catatan: #3 IS18PRE03-1 sebenarnya juga punya sisa di TP02, tapi karena TP01 sudah terklaim di #1, alokasi TP02 jatuh ke baris berikutnya)
            → Baris #5 sampai #10: pl_package_count = 0
        Pallet TP03 (CTN=55):
            → Baris invoice #11 (IS24PRE03, baris pertama yang sepenuhnya di TP03 karena #10 sudah di area TP02-TP03 boundary): pl_package_count = 55
            → Baris #12 sampai #24: pl_package_count = 0

    VERIFIKASI: jumlah pl_package_count dari semua 24 baris = 44 + 54 + 55 = 153, sesuai grand total PL.

7. `pl_nw`:
    Ekstrak dari kolom "N.W KGS" pada baris rangkuman pallet. Terapkan aturan ALOKASI PALLET yang SAMA PERSIS seperti pl_package_count.
    Contoh untuk dokumen ini:
        → Baris #1 (TP01): pl_nw = 433
        → Baris #4 (TP02): pl_nw = 602
        → Baris #11 (TP03): pl_nw = 584
        → Baris lain: pl_nw = null (atau 0)
    Verifikasi: sum = 433 + 602 + 584 = 1619 ≈ 1618.99 (grand total).

    DILARANG KERAS mengambil nilai grand total NW (1618.99) sebagai pl_nw baris manapun.

8. `pl_gw`:
    Ekstrak dari kolom "G.W KGS" pada baris rangkuman pallet. Aturan alokasi pallet yang sama.
    Contoh:
        → Baris #1: pl_gw = 441
        → Baris #4: pl_gw = 610
        → Baris #11: pl_gw = 592
        → Baris lain: pl_gw = null

9. `pl_volume`:
    Ekstrak dari kolom "CFT" pada baris rangkuman pallet. Aturan alokasi pallet yang sama.
    Contoh:
        → Baris #1: pl_volume = 1 (atau nilai eksak dari CFT TP01)
        → Baris #4: pl_volume = 1 (atau nilai eksak dari CFT TP02)
        → Baris #11: pl_volume = nilai CFT TP03 (sisa hingga total 4.29)
        → Baris lain: pl_volume = null

10. `pl_volume_unit`:
    "CFT" (cubic feet), sesuai header kolom paling kanan PL. JANGAN biarkan null.

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