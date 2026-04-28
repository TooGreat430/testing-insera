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
4. `pl_quantity`: Ekstrak nilai angka dari kolom "Quantity Jumlah". Jika angka diawali dengan simbol seperti "$=" (contoh: "$=1,300.00$"), abaikan simbol tersebut dan ekstrak angka murninya saja ("1300.00").
5. `pl_package_unit`: Ekstrak unit kemasan yang terletak di sebelah kanan pl_quantity (misalnya "$= 200.00 PCS" maka pl_quantity_unit = "PCS").
6. `pl_package_count`:
    - Terdapat di sebelah paling kiri (misal 17 Bal x @20, maka pl_package_count adalah 17).
    - Apabila di sebelah kiri tidak ada nilainya atau koson, maka pl_package_count line tersebut adalah 0.
7. `pl_nw`: Biarkan null karena tidak dicantumkan di tingkat line item.
8. `pl_gw`: Biarkan null karena tidak dicantumkan di tingkat line item.
9. `pl_volume`: Biarkan null karena tidak dicantumkan di tingkat line item.
"""