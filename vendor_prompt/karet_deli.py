KARET_DELI_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari teks di dalam kolom "Description Uraian" yang berawalan "PO.INS-" atau "PO. INS-". Ambil HANYA angka PO-nya saja (misalnya dari "PO.INS-45318349/NEW LABEL", ekstrak "45318349").
2. `inv_spart_item_no`: Ekstrak dari teks di dalam kolom "Description Uraian" yang berawalan abjad alfabet diikuti dengan strip (-) dan angka (misalnya "DL-540", "SA-206", atau "S-199"). Jika terdapat lebih dari satu pola yang cocok, ambil yang pertama kali muncul di teks.
3. `inv_description`: Ekstrak teks lengkap dari kolom "Description Uraian" (termasuk ukuran ban dan jenisnya, abaikan teks keterangan PO di dalamnya jika memungkinkan).
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada invoice ini.
5. `inv_quantity`: Ekstrak nilai angka dari kolom "Quantity Jumlah".
6. `inv_quantity_unit`: Ekstrak unit kemasan yang terletak di sebelah kanan angka kuantitas pada kolom "Quantity Jumlah" (misalnya "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Unit Price Hrg Satuan".
8. `inv_amount`: Ekstrak nilai angka dari kolom "Amount Jumlah".

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari teks di dalam kolom "Description Uraian" yang berawalan "PO.INS-" (misalnya "45318349").
2. `pl_item_no`: Ekstrak dari teks di dalam kolom "Description Uraian" yang berawalan abjad alfabet diikuti dengan strip (-) dan angka (misalnya "DL-540", "SA-206", atau "S-199"). Jika terdapat lebih dari satu pola yang cocok, ambil yang pertama kali muncul di teks.
3. `pl_description`: Ekstrak teks dari kolom "Description Uraian".
4. `pl_quantity`:
    KASUS A — STANDAR (1 baris invoice cocok 1 baris PL untuk pasangan PO + item yang sama):
        - Ekstrak nilai angka dari kolom "Quantity Jumlah" pada baris PL yang sesuai.
        - Jika angka diawali simbol seperti "{ =" (contoh: "{ = 1,300.00"), abaikan simbol dan ekstrak angka murninya.
        - PERHATIAN BACA ANGKA: tanda koma "," adalah pemisah RIBUAN (contoh: "1,960.00" = 1960.00, BUKAN 1970 atau 1.960). Tanda titik "." adalah pemisah desimal. Jangan menebak digit.

    KASUS B — INVOICE PECAH, PL DIGABUNG (PENTING — sering terjadi pada Karet Deli):
        Karet Deli sering MEMECAH satu item menjadi beberapa baris invoice (karena nomor PO atau label berbeda), TETAPI menggabungkan kuantitas tersebut menjadi SATU baris di Packing List.
        Contoh nyata dari dokumen:
            Invoice (PO.INS-45324581, item S-610 BK-nonPAH):
                - Baris #38: 20 PCS
                - Baris #39: 400 PCS
            Packing List (PO.INS-45324581, item S-610 BK-nonPAH):
                - HANYA SATU baris: "{ 17 BAL x @ 20 = 420.00 PCS BLS 24X2.00 S-610 BK-nonPAH..."
        ATURAN: Untuk kasus seperti ini, isi pl_quantity setiap baris invoice = inv_quantity baris tersebut (MIRROR).
        Hasil yang BENAR:
            - Baris #38: pl_quantity = 20 (mirror dari inv_quantity baris itu)
            - Baris #39: pl_quantity = 400 (mirror dari inv_quantity baris itu)
        Verifikasi: jumlah pl_quantity dari seluruh baris invoice yang merujuk ke 1 baris PL gabungan HARUS sama dengan kuantitas baris PL gabungan tersebut (20 + 400 = 420 ✓).

        SALAH (jangan lakukan):
            - Baris #38: pl_quantity = 420 (mengambil total gabungan), Baris #39: pl_quantity = 0
            - Baris #38: pl_quantity = 420, Baris #39: pl_quantity = 420 (duplikasi)

        DILARANG KERAS mencampur baris PL dari PO yang berbeda. Pastikan pencocokan PO.INS-... per baris dilakukan dulu sebelum mirroring; baris PL dari PO lain TIDAK BOLEH ikut dijumlahkan ke baris invoice ini.
5. `pl_package_unit`: Ekstrak unit kemasan yang terletak di sebelah kanan pl_quantity (misalnya "{ = 200.00 PCS" maka pl_package_unit = "PCS").
6. `pl_package_count`:
    - Terdapat di sebelah paling kiri sebelum tanda "BAL" (contoh: "17 BAL x @ 20", maka pl_package_count = 17).
    - Apabila baris PL TIDAK memiliki prefix "N BAL x @ M" (umumnya item BDS yang dijual lepas tanpa pengemasan BAL), set pl_package_count = null. JANGAN isi 0.
    - Pada KASUS B (invoice pecah, PL digabung — lihat aturan pl_quantity di atas), pl_package_count diisi pada baris invoice PERTAMA saja sesuai jumlah BAL pada baris PL gabungan. Baris invoice berikutnya yang merujuk ke baris PL gabungan yang sama diisi null.
        Contoh: untuk PO.INS-45324581 item S-610 (PL: "17 BAL x @ 20 = 420.00 PCS"):
            - Baris #38 (inv 20 PCS): pl_package_count = 17
            - Baris #39 (inv 400 PCS): pl_package_count = null
7. `pl_nw`: Biarkan null karena tidak dicantumkan di tingkat line item.
8. `pl_gw`: Biarkan null karena tidak dicantumkan di tingkat line item.
9. `pl_volume`: Biarkan null karena tidak dicantumkan di tingkat line item.
"""