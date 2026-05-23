KARET_DELI_PROMPT = """
ATURAN EKSTRAKSI KHUSUS VENDOR KARET DELI:

=========================================
PENGECUALIAN LINE ITEM (WAJIB DIABAIKAN):
=========================================
Tabel dokumen ini mencampur item barang dengan informasi rekapitulasi. Anda DILARANG KERAS mengekstrak baris-baris berikut sebagai line item (abaikan sepenuhnya dari output JSON):
1. Baris perhitungan nominal/pajak: "Brutto", "Diskon", "Total tanpa PPN", "PPN", "Total dengan PPN", "Rp.".
2. Baris rekapitulasi kemasan: "JUMLAH SATUAN", "GRAND TOTAL", "TOTAL".
3. Baris informasi pengiriman: "CONTAINER = TAKU", "SHIPPING MARKS", "MEDAN-SURABAYA".

Jika Anda melihat kata-kata di atas pada kolom Description/Uraian, LEWATI baris tersebut. HANYA ekstrak baris yang mendeskripsikan spesifikasi ban/karet (seperti "BDS...", "BLS...", "SETS BLDS...").

=========================================
INVOICE (INV):
=========================================
1. `inv_customer_po_no`:
    BENTUK STANDAR — Ekstrak dari teks di dalam kolom "Description Uraian" yang berawalan "PO.INS-" atau "PO. INS-". Ambil HANYA angka PO-nya saja (misalnya dari "PO.INS-45318349/NEW LABEL", ekstrak "45318349").
    BENTUK NON-STANDAR (KASUS KLAIM / K100) — Beberapa baris menggunakan format PO berbeda dengan separator "/" (BUKAN strip "-") dan mengandung tanggal + kode huruf, contoh: "PO.INS/01/01/26/K100/NEW LABEL". Untuk bentuk ini, ekstrak SELURUH string PO termasuk garis miring dan kode huruf (tanpa awalan "PO." dan tanpa suffix "/NEW LABEL"). Contoh: dari "PO.INS/01/01/26/K100/NEW LABEL" -> inv_customer_po_no = "INS/01/01/26/K100".
    JANGAN melewati / menolak baris dengan format PO non-standar; tetap ekstrak full identifier-nya.
2. `inv_spart_item_no`: Ekstrak dari teks di dalam kolom "Description Uraian" yang berawalan abjad alfabet diikuti dengan strip (-) dan angka (misalnya "DL-540", "SA-206", atau "S-199"). Jika terdapat lebih dari satu pola yang cocok, ambil yang pertama kali muncul di teks.
3. `inv_description`: Ekstrak teks lengkap dari kolom "Description Uraian" (termasuk ukuran ban dan jenisnya, abaikan teks keterangan PO di dalamnya jika memungkinkan).
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada invoice ini.
5. `inv_quantity`: Ekstrak nilai angka dari kolom "Quantity Jumlah".
6. `inv_quantity_unit`: Ekstrak unit kemasan yang terletak di sebelah kanan angka kuantitas pada kolom "Quantity Jumlah" (misalnya "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Unit Price Hrg Satuan".
8. `inv_amount`: Ekstrak nilai angka dari kolom "Amount Jumlah".

=========================================
PACKING LIST (PL):
=========================================
STRUKTUR FILE PL — PENTING:
Satu file Packing List Karet Deli BISA mengandung BEBERAPA sub-section, masing-masing untuk invoice yang berbeda. Pola yang HARUS DIKENALI:
    - Header utama di atas: "No. : INS-XXX/YY" (contoh "INS-009/26") -> menentukan parent invoice file.
    - Setelah daftar baris utama, biasanya muncul "TOTAL X.XX PCS / Y.YY SETS" sebagai pemisah.
    - DI BAWAH pemisah itu BISA muncul SUB-SECTION HEADER bentuk "INS-XXX/YY/ZZZ" (contoh: "INS-009/26/K100", dimana ZZZ adalah kode klaim seperti K100, RH, dst).
    - Setelah sub-section header, ada 1+ baris item yang HARUS diekstrak sebagai pl_* normal.
    - Setelah sub-section, bisa muncul "CLAIM : CLMxxxxxx" dan "TOTAL X.XX PCS" lagi.
    - Paling akhir biasanya ada "GRAND TOTAL ...".

DILARANG KERAS melewatkan baris di bawah sub-section header — meskipun letaknya setelah baris "TOTAL ... PCS / ... SETS", baris-baris itu tetap valid item PL dan WAJIB diekstrak.

1. `pl_customer_po_no`:
    BENTUK STANDAR — Ekstrak dari teks di dalam kolom "Description Uraian" yang berawalan "PO.INS-" diikuti angka 8 digit (misalnya "45318349").
    BENTUK NON-STANDAR (KASUS KLAIM / K100) — Untuk baris di bawah sub-section header, format PO sering pakai "/" sebagai separator dengan tanggal dan kode huruf. Ekstrak full string PO tanpa awalan "PO." dan tanpa "/NEW LABEL". Contoh: "PO.INS/01/01/26/K100/NEW LABEL" -> pl_customer_po_no = "INS/01/01/26/K100".
    Nilai ini HARUS persis sama dengan inv_customer_po_no di sisi invoice (rule simetris).
2. `pl_item_no`: Ekstrak dari teks di dalam kolom "Description Uraian" yang berawalan abjad alfabet diikuti dengan strip (-) dan angka. Ambil yang pertama kali muncul di teks.
3. `pl_description`: Ekstrak teks dari kolom "Description Uraian".
4. `pl_quantity`:
    KASUS A — STANDAR (1 baris invoice cocok 1 baris PL untuk pasangan PO + item yang sama):
        - Ekstrak nilai angka dari kolom "Quantity Jumlah" pada baris PL yang sesuai.
        - Jika angka diawali simbol seperti "{ =" (contoh: "{ = 1,300.00"), abaikan simbol dan ekstrak angka murninya.
        - PERHATIAN BACA ANGKA: tanda koma "," adalah pemisah RIBUAN (contoh: "1,960.00" = 1960.00). Tanda titik "." adalah pemisah desimal. Jangan menebak digit.

    KASUS B — INVOICE PECAH, PL DIGABUNG (PENTING):
        Karet Deli sering MEMECAH satu item menjadi beberapa baris invoice (karena nomor PO/label berbeda), TETAPI menggabungkan kuantitas tersebut menjadi SATU baris di Packing List.
        ATURAN: Untuk kasus seperti ini, isi pl_quantity setiap baris invoice = inv_quantity baris tersebut (MIRROR).
        Contoh benar: Baris #38 (inv 20 PCS) -> pl_quantity = 20. Baris #39 (inv 400 PCS) -> pl_quantity = 400.
        DILARANG KERAS mencampur baris PL dari PO yang berbeda. Pastikan pencocokan PO.INS-... per baris dilakukan dulu sebelum mirroring.
5. `pl_package_unit`: Ekstrak unit kemasan yang terletak di sebelah kanan pl_quantity (misalnya "{ = 200.00 PCS" maka pl_package_unit = "PCS").
6. `pl_package_count`:
    - Terdapat di sebelah paling kiri sebelum tanda "BAL" (contoh: "17 BAL x @ 20", maka pl_package_count = 17).
    - Apabila baris PL TIDAK memiliki prefix "N BAL x @ M", set pl_package_count = null. JANGAN isi 0.
    - Pada KASUS B (invoice pecah, PL digabung), pl_package_count diisi pada baris invoice PERTAMA saja sesuai jumlah BAL pada baris PL gabungan. Baris invoice berikutnya yang merujuk ke baris PL gabungan yang sama diisi null.
7. `pl_nw`, `pl_gw`, `pl_volume`: Biarkan null karena tidak dicantumkan di tingkat line item.
"""