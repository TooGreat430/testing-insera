SHIMANO_INC_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: - Ekstrak dari teks "P/O No." yang berada di dalam blok "MARKS NOS" di sebelah kiri (misalnya "45320517").
                         - Jika inv_customer_po_no tidak ditemukan, gunakan nilai terakhir yang valid sebelumnya (backward lookup). Jangan pernah mengambil nilai dari setelahnya (forward lookup).
2. `inv_spart_item_no`: Ekstrak nilai teks setelah kata "PART#" atau S.PART# di dalam blok deskripsi (misalnya "KU60302DLF6RX100" atau "KSMMAR160DDB").
3. `inv_description`: Ekstrak teks deskripsi barang utama (misalnya "DISC BRAKE ASSEMBLED SET..."). Abaikan teks PART# atau keterangan detail lain di bawahnya.
4. `inv_gw` & `inv_gw_unit`:
    - Ekstrak nilai angka total dari kolom "Gross Weight" pada baris atas untuk line item tersebut (misalnya dari "14.40Kg", ekstrak 14.40 untuk gw dan "Kg" untuk unit).
    - Apabila pada 1 line item terdapat beberapa baris dengan kolom "Gross Weight" yang terisi, maka jumlahkan semua nilai angka tersebut untuk mendapatkan `inv_gw`.
5. `inv_quantity`: Ekstrak angka dari kolom "Quantity" yang ditandai dengan clue "TOTAL" MILIK LINE ITEM INI SENDIRI.

   ATURAN BINDING KETAT (WAJIB DITURUTI):
   - Setiap line item Shimano memiliki SATU baris "TOTAL" yang terletak di bawah daftar carton/pallet milik item itu, SEBELUM dimulainya line item berikutnya.
   - Penanda awal line item baru adalah blok baru "[2006772] ... P/O No. ..." ATAU munculnya header CODE/PART# baru (misal "PART# KFCR8100CX04").
   - Baris TOTAL milik item ini WAJIB dibaca DARI list carton item ini saja. JANGAN ambil baris TOTAL milik item LAIN walaupun visually berdekatan.
   - DILARANG KERAS menyamakan TOTAL antar item dengan kode item yang mirip. Contoh KESALAHAN BERAT:
     * KFCR**7**100CX04 (FC-R7100, PO 43018042) → TOTAL 386 SETS
     * KFCR**8**100CX04 (FC-R8100, PO 43018056) → TOTAL 42 SETS
     Walaupun keduanya "FRONT CHAINWHEEL" dan kode-nya mirip, qty-nya BERBEDA. Bind TOTAL ke kode item exact match-nya.

   SANITY CHECK (WAJIB diverifikasi):
   - inv_quantity HARUS = jumlah semua qty per carton/pallet pada line item ini.
   - Contoh A: CTN NO. 13 (715 PCS) → TOTAL 715 PCS → inv_quantity = 715 (sanity: 715=715 ✓).
   - Contoh B: CTN NO. 14-15 (400 PCS) + CTN NO. 16 (130 PCS) → TOTAL 530 PCS → inv_quantity = 530 (sanity: 400+130=530 ✓).
   - Contoh C: PLT NO. 15-16 (320 SETS) + CTN NO. 17-22 (60 SETS) + CTN NO. 23 (6 SETS) → TOTAL 386 SETS → inv_quantity = 386 (sanity: 320+60+6=386 ✓).
   - Jika sanity check GAGAL, kemungkinan besar Anda mengambil TOTAL dari item LAIN — perbaiki dengan bind ke list carton item ini.
   - SANITY CHECK TAMBAHAN (anti salah baca digit): inv_quantity x inv_unit_price HARUS = angka amount yang TERCETAK pada baris TOTAL item ini.
     Jika tidak sama, berarti ada digit quantity yang salah baca (digit pada dokumen ini mudah tertukar, mis. 6↔8, 4↔9, 3↔8) — baca ulang angka quantity pada baris TOTAL; quantity yang benar = amount tercetak / unit price (bila pembagiannya bulat).

   ATURAN PAGE BREAK (ITEM NYAMBUNG ANTAR HALAMAN — WAJIB):
   - Satu line item bisa TERPOTONG page break: baris carton/pallet (CTN NO. / PLT NO.) LANJUTAN milik item yang sama bisa muncul di BAGIAN ATAS halaman berikutnya, dan baris TOTAL item itu bisa berada di halaman berikutnya juga.
   - Blok sebuah item berakhir HANYA pada baris TOTAL miliknya — BUKAN pada batas halaman.
   - Jika di awal halaman ada baris carton/pallet TANPA blok header item baru (tanpa PART# baru dan tanpa blok "P/O No. ..." baru) sebelum baris TOTAL, maka baris itu adalah LANJUTAN item dari halaman sebelumnya dan qty-nya WAJIB ikut dijumlahkan ke inv_quantity item tersebut.
   - JANGAN menutup item lebih awal hanya karena berganti halaman; telusuri sampai ketemu baris TOTAL item itu, baru ambil inv_quantity dari baris TOTAL tersebut.

   PAGE BREAK + UNIT PRICE/AMOUNT (KRITIS — SERING SALAH, WAJIB DITURUTI):
   - Baris TOTAL item (yang berisi "<qty> <unit>  JPY<amount>  @JPY<unit_price>") bisa
     muncul SENDIRIAN di BAGIAN ATAS halaman berikutnya, terpisah dari baris carton item
     itu yang berada di BAGIAN BAWAH halaman sebelumnya.
   - Saat ini terjadi, inv_unit_price dan inv_amount HANYA tercetak di baris TOTAL halaman
     berikutnya itu — TIDAK ada di baris carton. Anda WAJIB melanjutkan membaca ke baris
     TOTAL di halaman berikutnya untuk mengambil unit_price (@JPY) dan amount (JPY).
   - DILARANG KERAS mengisi inv_unit_price = 0 / inv_amount = 0 hanya karena baris carton
     item itu di akhir halaman dan baris TOTAL-nya belum terlihat di halaman yang sama —
     baris TOTAL pasti ada di awal halaman berikutnya (sebelum blok PART# item baru).
   - Contoh KESALAHAN NYATA (qty benar, tapi price/amount salah ke-0):
     * KEWSD300IL080: CTN 84 (63 PCS) di bawah halaman, baris TOTAL "63 PCS JPY74,529
       @JPY1,183" di atas halaman berikutnya. BENAR: unit_price=1183, amount=74529. SALAH: 0/0.
     * KR71202DLF6SX095: carton di bawah halaman, TOTAL "152 PCS JPY1,951,680 @JPY12,840"
       di halaman berikutnya. BENAR: unit_price=12840, amount=1951680. SALAH: 0/0.
     * KRX6005DRRDRX170: TOTAL "120 PCS JPY1,504,080 @JPY12,534" di halaman berikutnya.
       BENAR: unit_price=12534, amount=1504080.
     * KRX6005DLF6RX100: TOTAL "49 PCS JPY612,010 @JPY12,490" di halaman berikutnya.
       BENAR: unit_price=12490, amount=612010.

   DILARANG KERAS:
   - Mengambil nilai dari baris "@..." (per-carton rate) — itu BUKAN TOTAL.
   - Menjumlahkan TOTAL lintas line item (mis. 386 + 42 untuk dua FRONT CHAINWHEEL berbeda).
   - Membiarkan inv_quantity di-set sama dengan po_quantity tanpa verifikasi visual ke dokumen.
   - Mengambil qty parsial (hanya carton di halaman pertama) untuk item yang terpotong page break.

   ATURAN ANTI-SPLIT BLOK (KRITIS — KESALAHAN FATAL JIKA DILANGGAR):
   - 1 blok PART#/SEQ# = TEPAT 1 row output. Baris "CTN NO. ..." / "PLT NO. ..."
     adalah rincian karton DI DALAM blok, BUKAN item terpisah.
   - DILARANG memecah satu blok menjadi 2 row (mis. satu row berisi qty carton pertama
     dengan price 0, lalu satu row lagi berisi sisanya). qty, unit_price, dan amount
     WAJIB berada di SATU row yang sama.
   - Contoh KESALAHAN NYATA yang dilarang:
     * Blok KCSHG50010134 (CTN 6 → 50 PCS, CTN 7 → 5 PCS, TOTAL 55 PCS JPY82,060
       @JPY1,492) dipecah jadi row qty=50 (price 0, amount 0) + row qty=55.
       SALAH — output HANYA 1 row: qty=55, unit_price=1492, amount=82060.
     * Blok KSMBCC16 (CTN 17-21 → 500, CTN 22 → 20, TOTAL 520 PCS JPY147,680)
       dipecah jadi row qty=500 (price 0) + row qty=20 (amount 5680).
       SALAH — output HANYA 1 row: qty=520, unit_price=284, amount=147680.
     * Blok KCSM620012051 (TOTAL 400 PCS JPY1,817,200 @JPY4,543) dipecah jadi
       row qty=400 (price 0, amount 0) + row qty=0 (price 4543, amount 0).
       SALAH — output HANYA 1 row: qty=400, unit_price=4543, amount=1817200.
   - Memecah blok membuat jumlah row MELEBIHI jumlah item asli sehingga item lain
     ikut TERGUSUR/HILANG dari output. Jumlah row output = jumlah blok PART#/SEQ#.
6. `inv_quantity_unit`: Ekstrak unit dari kolom "Quantity Unit" (misalnya "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Amount Unit Price" pada baris bawah yang diawali dengan simbol "@" (misalnya dari "@JPY75", ekstrak 75).
   - WAJIB terisi (bukan 0) untuk SETIAP row yang inv_quantity-nya terbaca — setiap blok Shimano SELALU mencetak "@JPY..." di baris TOTAL-nya. inv_unit_price = 0 padahal qty > 0 berarti Anda memecah blok / berhenti membaca sebelum baris TOTAL — perbaiki.
8. `inv_amount`:
- Ekstrak nilai angka dari kolom "Amount Unit Price" pada baris atas yang tidak memiliki simbol "@" (misalnya dari "JPY69,600", ekstrak 69600).
- inv_amount WAJIB nilai yang TERCETAK pada baris TOTAL milik item ini. DILARANG KERAS menghitung sendiri inv_amount dari inv_quantity x inv_unit_price.
- Untuk item yang terpotong page break, baris TOTAL (berisi quantity dan amount) bisa berada di halaman SETELAH baris carton pertama item itu — gunakan baris TOTAL tercetak tersebut, jangan menjumlahkan carton sebagian lalu mengalikan unit price.
- SANITY CHECK: inv_amount harus = inv_quantity x inv_unit_price. Jika tidak konsisten, yang hampir selalu salah adalah bacaan QUANTITY (digit tertukar) — perbaiki inv_quantity dari amount tercetak / unit price, JANGAN mengubah inv_amount mengikuti quantity yang salah.

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari teks "P/O No." yang berada di dalam blok "MARKS NOS".
2. `pl_item_no`: Ekstrak nilai teks setelah kata "PART#" atau "S.PART#".
3. `pl_description`: Ekstrak teks deskripsi barang utama.
4. `pl_quantity`: Ekstrak angka dari kolom "Quantity" yang ditandai dengan clue "TOTAL" MILIK LINE ITEM INI SENDIRI.

   ATURAN BINDING KETAT (sama seperti inv_quantity):
   - Setiap line item PL memiliki SATU baris "TOTAL" di bawah daftar carton/pallet item itu, SEBELUM line item berikutnya dimulai.
   - ATURAN PAGE BREAK berlaku sama seperti inv_quantity: baris carton/pallet lanjutan milik item yang sama bisa berada di bagian atas halaman berikutnya (dan baris TOTAL-nya juga bisa di halaman berikutnya). Blok item berakhir HANYA pada baris TOTAL-nya, bukan pada batas halaman; qty lanjutan WAJIB ikut dijumlahkan.
   - Bind TOTAL ke kode item exact match (PART#/S.PART#) — JANGAN ambil TOTAL milik item lain.
   - DILARANG menyamakan TOTAL antar item dengan kode mirip (mis. KFCR7100CX04 ≠ KFCR8100CX04).
   - SANITY CHECK: pl_quantity HARUS = jumlah qty per carton/pallet pada line item ini.
     Contoh: PLT 15-16 (320 SETS) + CTN 17-22 (60 SETS) + CTN 23 (6 SETS) → TOTAL 386 SETS → pl_quantity = 386.
   - DILARANG ambil nilai dari baris "@..." (per-carton rate).
5. pl_package_unit:
    - pl_package_unit HANYA boleh diambil dari BUKTI PACKAGE, bukan dari quantity unit.
    - Sumber bukti yang VALID untuk pl_package_unit hanya:
      1) kolom/header package, packing, pkgs, cartons, ctn, pallet, plt, bale, package detail (Contoh: pada dokumen ada header bernama "Carton No.")
      2) unit yang menempel langsung pada package_count
      3) header rasio kemasan seperti PCS/CTN, SET/CTN, QTY/CARTON -> ambil unit packagenya, BUKAN unit quantity
      4) CLUE PENTING: Untuk menentukan pl_package_unit, lihat pada bagian kiri penomoran paket (Misal: CTN No.)
         Apabila penomoran paket:
         CTN -> pl_package_unit line tersebut = CT
         PLT -> pl_package_unit line tersebut = PX
         Ada PLT dan CTN -> pl_package_unit line tersebut = PK

    - Sumber bukti yang TIDAK VALID untuk pl_package_unit:
      1) kolom quantity / qty / pcs / sets / units
      2) inv_quantity_unit
      3) unit penjualan barang
      4) unit yang hanya menjelaskan isi per kemasan

    - Jika satuan yang ditemukan berasal dari quantity column, quantity header, atau quantity-per-package header, MAKA JANGAN gunakan untuk pl_package_unit.

    - pl_package_unit harus final dalam canonical value berikut saja: ["CT", "PX", "BL", "PXCT", "null"]
      pl_package_unit TIDAK BISA DILUAR UNIT INI. JIKA DILUAR UNIT YANG DISEDIAKAN MAKA BUKAN UNIT DARI pl_package_unit.
      DILARANG KERAS MELAKUKAN RETURN SELAIN VALUE-VALUE TERSEBUT!


    - Mapping canonical:
      - CTN / CARTON / CARTONS -> CT
      - PLT / PALLET / PALLETS -> PX
      - BALE / BALES -> BL
      - Jika lebih dari 1 tipe package unit -> PXCT
        - Contoh:
          - 2 P/T &  32 C/T
            maka pl_package_unit = PXCT, karena memiliki lebih dari 1 tipe package unit (P/T -> Pallet dan C/T -> Carton) 
            
6. `pl_package_count`:
    - Ekstrak angka jumlah kemasan yang tertera sebelum unit kemasan di bawah nomor package (misalnya dari "(       20 C/T)", ekstrak 20).
    - ATURAN SANGAT PENTING: Jika pada dokumen terdapat dua value dengan UNIT yang beda yang tergabung dalam satu UNIT dengan satuan yang lebih besar, seperti:
      PLT No. 15- 16
      (       2 P/T...      32 C/T)
      CTN No. 17- 22
      (       6 C/T)
      CTN No. 23
      (       1 C/T)
      Maka:
      pl_package_count untuk line item tersebut adalah 2 P/T + 6 C/T + 1 C/T = 2 + 6 + 1 = 9 (Totalkan dari satuan terbesarnya yaitu PLT, baru kemudian totalkan dengan satuan yang lebih kecil yaitu CTN).
      Gunakan 2 P/T, JANGAN GUNAKAN 32 C/T karena satuan 2 P/T lebih besar dari 32 C/T.

    - Apabila pada 1 line item terdapat beberapa baris dengan nilai jumlah kemasan, maka jumlahkan semua nilai angka tersebut untuk mendapatkan `pl_package_count`.
    - Contoh:
        Line item A:
        CTN No. 1
        (       20 C/T)
        CTN No. 2
        (       30 C/T)
        Maka: pl_package_count untuk line item A adalah 20 + 30 = 50.
    - Jika pada suatu line item tidak ditemukan angka jumlah kemasan yang valid, maka biarkan `pl_package_count` = 0 (meskipun value lainnya ada) dan line tersebut jangan diskip.

7. `pl_nw`: 
    - Ekstrak nilai angka dari kolom "Net Weight" baris atas yang tidak ada simbol "@" (Misal: ada "3.5Kg" dan "@0.5Kg", maka ekstrak yang "3.5").
    - Apabila pada 1 line item terdapat beberapa baris dengan nilai "Net Weight", maka jumlahkan semua nilai angka tersebut untuk mendapatkan `pl_nw`.
    - Contoh:
        Line item A:
        3.5Kg
        @0.5Kg
        
        2.5Kg
        @0.25Kg

        Maka: pl_nw untuk line item A adalah 3.5 + 2.5 = 6.0 (ignore yang ada simbol "@").
    - Jika pada suatu line item tidak ditemukan nilai angka Net Weight yang valid, maka biarkan `pl_nw` = 0 (meskipun value lainnya ada) dan line tersebut jangan diskip.

8. `pl_gw`: 
    - Ekstrak nilai angka dari kolom "Gross Weight" baris atas.
    - Apabila pada 1 line item terdapat beberapa baris dengan nilai "Gross Weight", maka jumlahkan semua nilai angka tersebut untuk mendapatkan `pl_gw`.
    - Contoh:
        Line item A:
        14.40Kg
        @0.5Kg

        10.00Kg
        @0.25Kg

        Maka: pl_gw untuk line item A adalah 14.40 + 10.00 = 24.40 (ignore yang ada simbol "@").
    - Jika pada suatu line item tidak ditemukan nilai angka Gross Weight yang valid, maka biarkan `pl_gw` = 0 (meskipun value lainnya ada) dan line tersebut jangan diskip.
    
9. `pl_volume`: 
    - Ekstrak nilai angka dari kolom "Measure" baris atas (misalnya dari "0.080M3", ekstrak 0.080).
    - Biasanya pl_volume ditandai dengan satuan M3.
    - Apabila pada 1 line item terdapat beberapa baris dengan nilai "Measure", maka jumlahkan semua nilai angka tersebut untuk mendapatkan `pl_volume`.
    - Contoh:
        Line item A:
        0.080M3
        @0.005M3   

        0.050M3
        @0.002M3

        Maka: pl_volume untuk line item A adalah 0.080 + 0.050 = 0.130 (ignore yang ada simbol "@").
    - Jika pada suatu line item tidak ditemukan nilai angka Measure yang valid, maka biarkan `pl_volume` = 0 (meskipun value lainnya ada) dan line tersebut jangan diskip.

BILL OF LADING (BL):

1. `bl_description`: 
    - bl_description DILARANG KERAS untuk diisi null.
    - Dimapping dengan inv_description berdasarkan kemiripan. Jika inv_description tidak exist pada dokumen BL, maka PILIH SALAH SATU ITEM RANDOM YANG SEKIRANYA PALING MIRIP.
    Contoh:
    Pada inv_description ada value:
    DISC BRAKE ASSEMBLED ...
    MOUNT ADAPTER FOR ROAD DISC BRAKE ...
    FRONT CHAINWHEEL ... ; 170MM; ...
    FRONT DERAILLEUR ...
    REAR DERAILLEUR ... 
    FRONT CHAINWHEEL ... ; 165MM; ...

    Pada BL ada deskripsi item:
    FRONT CHAINWHEEL 165MM
    FRONT CHAINWHEEL 170MM
    FRONT DERAILLEUR
    REAR DERAILLEUR
    DISC BRAKE

    Maka mapping value bl_desriptionnya adalah:
    DISC BRAKE
    [PILIH SECARA RANDOM YANG SEKIRANYA PALING MIRIP]
    FRONT CHAINWHEEL 170MM
    FRONT DERAILLEUR
    REAR DERAILLEUR
    FRONT CHAINWHEEL 165MM

2. `bl_hs_code`: 
    - Value bl_hs_code diisi sesuai dengan bl_descriptionnya
        Contoh:
        FRONT CHAINWHEEL 165MM HS NUMBER: 8714.96 
        FRONT CHAINWHEEL 170MM HS NUMBER: 8714.96
        FRONT DERAILLEUR HS NUMBER: 8714.99
        REAR DERAILLEUR HS NUMBER: 8714.96
        DISC BRAKE HS NUMBER: 8714.94

        Maka:
        bl_hs_code untuk DISC BRAKE adalah 8714.94, maka bl_hs_code isi 8714.94.
    - Hanya boleh mengambil dari dokumen Bill Of Lading (BL), TIDAK BOLEH dari dokumen yang lain.

3. `bl_mark_number`:
    - Lihat pada bagian halaman 2 (page 2) dari dokumen BL. Anda akan melihat:
      PT. IS
      P/O No. -> PO Number
      SURABAYA
      MADE IN [Negara Asal]
      PLT No. -> Palette numbers
      CTN No. -> Carton numbers
      (Dalam satu item bisa hanya terdapat salah satu palette/carton atau bisa terdapat keduanya)
    
    - Untuk bl_mark_number, map dengan inv_customer_po_no dan package number yang sama dengan value: "PT. IS PO# [PO Number] P/L No.: [Palette Numbers] C/T No.: [Carton Numbers] MADE IN [NEGARA ASAL]". Untuk package numbers, HANYA RETURN PACKAGE NUMBERS YANG ADA!
    - Contoh:
      PT. IS
      P/O No. -> 43018041
      SURABAYA
      MADE IN JAPAN
      CTN No. -> 1-5, 13, 33-80
      Maka bl_mark_number UNTUK SEMUA LINE ITEM DENGAN inv_customer_po_no DAN CTN NUMBERS YANG SAMA: "PT. IS PO# 43018041 C/T No.: 1-5, 13, 33-80 MADE IN JAPAN"
      
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
3. `coo_description`: Ekstrak deskripsi teks dari kolom "6. Description of goods" (ambil murni deskripsi barangnya saja, misal "SMALL PARTS SMMA-R 160 D/D", abaikan teks "Invoice No", "PO No", dan "PART#").
4. `coo_hs_code`: Ekstrak dari kolom "7. HS Code".
5. `coo_package_count`: Biarkan null.
6. `coo_package_unit`: Biarkan null.
7. `coo_gw` & `coo_quantity`: Ekstrak nilai angka dari kolom "10. Quantity" untuk `coo_quantity`, biarkan `coo_gw` null karena dokumen ini menggunakan satuan kuantitas item (PCS), bukan berat.
8. `coo_unit`: Ekstrak unit dari kolom "10. Quantity" (misalnya "PCS") dan bukan nilai numeriknya.
9. `coo_criteria`: Ekstrak dari kolom "8. Origin conferring criterion" dan hanya ekstrak kode alphabetic-nya tanpa nomor numeriknya (misalnya "RVC40", maka ekstrak "RVC").
10. `coo_customer_po_no`: Ekstrak teks setelah "PO No:" di dalam kolom "6. Description of goods", biasanya diawali dengan angka 4 (misal: "43018041").
"""