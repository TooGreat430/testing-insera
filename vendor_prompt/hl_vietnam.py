HL_VIETNAM_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari kolom "Order No" (misalnya "45324105" atau "45324678"). Abaikan kolom "PO No" karena berisi kode produksi internal vendor.
2. `inv_spart_item_no`: Ekstrak dari kolom "Item No" (misalnya "FRPVTPV21M0000-R" atau "HBRHLAL300BT02").
3. `inv_description`: Ekstrak teks deskripsi spesifikasi barang dari kolom "Description of goods". Gabungkan teks menjadi satu kalimat utuh jika terpecah ke dalam beberapa baris.
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak nilai angka dari kolom "Q'Ty" (misal dari "20,000 PCS", ambil angka 20000). Hapus tanda koma ribuan.
6. `inv_quantity_unit`: Ekstrak satuan kemasan dari kolom "Q'Ty" yang posisinya berada setelah angka (misalnya "PCS" atau "SET").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom harga satuan (kolom ini posisinya di sebelah kiri kolom Amount, terkadang tajuk kolomnya terbaca oleh OCR sebagai huruf "e" atau spasi kosong).
8. `inv_amount`: Ekstrak nilai angka dari kolom "Amount" atau "Amount USD)" (hapus koma ribuan).
*Instruksi Pemetaan Vertikal (Merged-Row):* Apabila dalam satu baris tabel visual terdapat beberapa item teks yang disusun sejajar secara vertikal pada kolom Order No, Item No, Description, Q'Ty, dan Amount, pisahkan teks tersebut secara paralel (line-by-line) menjadi beberapa objek mandiri agar nilainya berkorelasi tepat satu sama lain.

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari kolom "Order No" (misalnya "45324105").
2. `pl_item_no`: Ekstrak dari kolom "Item No" (misalnya "FRPVTPV21M0000-R").
3. `pl_description`: Ekstrak teks deskripsi dari kolom "Description of goods".
4. `pl_quantity`: 
    - Ekstrak nilai angka dari kolom "Qn'ty".
    - Perhatikan bahwa sel pada kolom ini memuat dua baris nilai (misal baris atas "274 PCS" dan baris bawah "50"). Ambil HANYA angka pada baris atas ("274") sebagai total kuantitas item. Abaikan angka di baris bawahnya.
    - Bersihkan tanda titik/koma ribuan (misal "20.000" menjadi 20000).
5. `pl_package_unit`: Simpulkan sebagai "CTN" atau "CTNS" berdasarkan tajuk kolom kemasan.
6. `pl_package_count`: Ekstrak nilai angka dari kolom "CTN" yang terletak di sebelah kanan kolom rentang C/NO (misalnya "10", "6", atau "12").
7. `pl_nw`: Ekstrak nilai angka dari kolom "N.W (Kgs)".
8. `pl_gw`: Ekstrak nilai angka dari kolom "G.W (Kgs)".
9. `pl_volume`: Biarkan null karena dokumen ini tidak mencantumkan informasi CBM/Measure di tingkat line item.
*Instruksi Pemetaan Vertikal (Merged-Row):* Terapkan aturan pemisahan vertikal line-by-line yang sama persis seperti pada dokumen Invoice apabila menemukan beberapa baris item tergabung dalam satu sel/blok tabel.

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
1. `coo_mark_number`: Ekstrak dari kolom "Marks and Numbers" (misalnya "NO MARK").
2. `coo_description`: Ekstrak teks nama/deskripsi barang dari kolom "Description" (misalnya "HANDLEBAR MTB-AL-300BTFOV(ISO-M)"). Gabungkan kata yang terputus spasi/baris baru di tengah teks.
3. `coo_hs_code`: Ekstrak dari kolom "HS Number" (misalnya "87149991").
4. `coo_package_count`: Ekstrak nilai angka dari baris bawah pada kolom "Quantity" (misal jika isi sel adalah "274.0000 \\n 6", maka ekstrak angka "6").
5. `coo_package_unit`: Ekstrak string/keterangan unit dari baris bawah pada kolom "Quantity Code" (misal jika isi sel adalah "H87 \\n CT", ekstrak sebagai "CT" atau "CTNS").
6. `coo_quantity`: Ekstrak nilai angka utama dari baris atas pada kolom "Quantity" (misal dari sel "274.0000 \\n 6", ekstrak angka "274").
7. `coo_gw`: Ekstrak nilai angka dari kolom "Gross weight or Other Quantity" (misal dari "89.6400", ambil 89.64).
8. `coo_unit`: Ekstrak satuan berat dari kolom "Weight Code or Unit of Measurement" (misalnya "KGM").
9. `coo_criteria`: Ekstrak dari kolom "Origin Criterion". Ambil hanya kode utamanya saja tanpa angka persentase di bawahnya (misalnya jika tertulis "RVC \\n 56.60%", maka ekstrak "RVC").
10. `coo_customer_po_no`: Biarkan null karena dokumen e-COO ini tidak memuat referensi nomor PO per baris item.
"""