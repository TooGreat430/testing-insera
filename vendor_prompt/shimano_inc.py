SHIMANO_INC_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari teks "P/O No." yang berada di dalam blok "MARKS NOS" di sebelah kiri (misalnya "45320517").
2. `inv_spart_item_no`: Ekstrak nilai teks setelah kata "PART#" atau S.PART# di dalam blok deskripsi (misalnya "KU60302DLF6RX100" atau "KSMMAR160DDB").
3. `inv_description`: Ekstrak teks deskripsi barang utama (misalnya "DISC BRAKE ASSEMBLED SET..."). Abaikan teks PART# atau keterangan detail lain di bawahnya.
4. `inv_gw` & `inv_gw_unit`:
    - Ekstrak nilai angka total dari kolom "Gross Weight" pada baris atas untuk line item tersebut (misalnya dari "14.40Kg", ekstrak 14.40 untuk gw dan "Kg" untuk unit).
    - Apabila pada 1 line item terdapat beberapa baris dengan kolom "Gross Weight" yang terisi, maka jumlahkan semua nilai angka tersebut untuk mendapatkan `inv_gw`.
5. `inv_quantity`: Ekstrak angka dari kolom "Quantity" yang ditandai dengan clue "TOTAL". Apabila terdapat beberapa baris dengan clue "TOTAL", maka jumlahkan semua nilai angka pada line item tersebut untuk mendapatkan `inv_quantity`.
6. `inv_quantity_unit`: Ekstrak unit dari kolom "Quantity Unit" (misalnya "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Amount Unit Price" pada baris bawah yang diawali dengan simbol "@" (misalnya dari "@JPY75", ekstrak 75).
8. `inv_amount`: 
- Ekstrak nilai angka dari kolom "Amount Unit Price" pada baris atas yang tidak memiliki simbol "@" (misalnya dari "JPY69,600", ekstrak 69600).

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari teks "P/O No." yang berada di dalam blok "MARKS NOS".
2. `pl_item_no`: Ekstrak nilai teks setelah kata "PART#" atau "S.PART#".
3. `pl_description`: Ekstrak teks deskripsi barang utama.
4. `pl_quantity`: Ekstrak angka dari kolom "Quantity" yang ditandai dengan clue "TOTAL". Apabila terdapat beberapa baris dengan clue "TOTAL", maka jumlahkan semua nilai angka pada line item tersebut untuk mendapatkan `inv_quantity`.
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
      DILARANG KERAS RETURN SELAIN VALUE-VALUE TERSEBUT!


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
    - Apabila pada 1 line item terdapat beberapa baris dengan nilai jumlah kemasan, maka jumlahkan semua nilai angka tersebut untuk mendapatkan `pl_package_count`.
    - Contoh:
        Line item A:
        CTN No. 1
        (       20 C/T)
        CTN No. 2
        (       30 C/T)
        Maka: pl_package_count untuk line item A adalah 20 + 30 = 50.
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
1. `coo_mark_number`: 
    - Ekstrak dari "7. Marks and numbers on packages".
    - Apabila tidak ada informasi marks and numbers pada kolom 7 atau tertlulis "N/M" (Not Mentioned), maka biarkan null.
2. `coo_description`: Ekstrak deskripsi teks dari kolom "6. Description of goods" (ambil murni deskripsi barangnya saja, misal "SMALL PARTS SMMA-R 160 D/D", abaikan teks "Invoice No", "PO No", dan "PART#").
3. `coo_hs_code`: Ekstrak dari kolom "7. HS Code".
4. `coo_package_count`: Biarkan null.
5. `coo_package_unit`: Biarkan null.
6. `coo_gw` & `coo_quantity`: Ekstrak nilai angka dari kolom "10. Quantity" untuk `coo_quantity`, biarkan `coo_gw` null karena dokumen ini menggunakan satuan kuantitas item (PCS), bukan berat.
7. `coo_unit`: Ekstrak unit dari kolom "10. Quantity" (misalnya "PCS") dan bukan nilai numeriknya.
8. `coo_criteria`: Ekstrak dari kolom "8. Origin conferring criterion" dan hanya ekstrak kode alphabetic-nya tanpa nomor numeriknya (misalnya "RVC40", maka ekstrak "RVC").
9. `coo_customer_po_no`: Ekstrak teks setelah "PO No:" di dalam kolom "6. Description of goods", biasanya diawali dengan angka 4 (misal: "43018041").
"""