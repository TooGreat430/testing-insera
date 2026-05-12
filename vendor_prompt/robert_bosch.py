ROBERT_BOSCH_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak nilai string dari kolom "PO Number" pada baris bersangkutan (misalnya "43017912", "45319382", "43017951").
2. `inv_spart_item_no`: Ekstrak dari kolom "Customer Number" (misalnya "EB11.200.0KD", "EB12.200.0WF", "1270.020.330"). Abaikan string rumit pada kolom "Material Number".
3. `inv_description`: Ekstrak teks deskripsi barang dari kolom "Description". Jika teks terpecah ke dalam beberapa baris, gabungkan menjadi satu string utuh.
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena dokumen invoice ini tidak mencantumkan informasi berat pada tingkat baris item.
5. `inv_quantity`: Ekstrak nilai angka numerik dari kolom "Billed Qty" (misalnya "300", "400").
6. `inv_quantity_unit`: Ekstrak satuan kemasan dari kolom tanpa tajuk yang terletak tepat di sebelah kanan kolom "Billed Qty" (misalnya "PCS", "SET").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Net Value EUR" (hapus tanda koma jika ada).
8. `inv_amount`: Ekstrak nilai angka dari kolom "Amount EUR" (hapus tanda koma ribuan).

PACKING LIST (PL):
1. `pl_customer_po_no`: Dokumen Packing List tidak mencantumkan kolom PO secara langsung. Lakukan cross-reference/mapping nilai PO Number dari dokumen Invoice berdasarkan kesamaan nomor urut "Item" atau "Customer Number". Jika tidak memungkinkan, biarkan null.
2. `pl_item_no`: Ekstrak string part unik dari kolom "Customer Number" (misal "EB12.100.04Z").
3. `pl_description`: 
    - Ekstrak teks deskripsi barang dari kolom gabungan "Material Number / Description".
    - Kolom ini memuat dua baris informasi bertumpuk. Ambil HANYA teks deskripsi murni di bagian bawah (misal "BATTERY FOR ELECTRIC BICYCLE...") dan abaikan baris kode string internal di atasnya (misal "BATBHBBP38800...").
4. `pl_quantity`: Ekstrak nilai angka dari kolom "Billed Qty".
5. `pl_package_unit`: 
    - Analisis string pada kolom "Carton / pallets" di sebelah paling kanan.
    - Apabila memuat kode berawalan huruf 'P' (misal "P26001", "P26002"), maka simpulkan kemasan sebagai "PLT" atau "PALLETS".
    - Apabila memuat kode berawalan huruf 'B' (misal "B26001", "B26011"), maka simpulkan kemasan sebagai "CTN" atau "BOX".
    - Apabila hanya berupa angka murni, sesuaikan dengan konteks tajuk kemasannya.
6. `pl_package_count`: 
    - Ekstrak nilai angka kemasan dari kolom "Carton / pallets". Jika item baris tersebut merupakan bagian dari satu boks/palet yang sama (kodenya berulang seperti P26002), pastikan mapping jumlah boks/paletnya diekstrak secara akurat tanpa duplikasi berlebih. Jika tertera angka eksplisit (misal "3" atau "20"), ambil angka tersebut.
7. `pl_nw`: Ekstrak nilai angka dari kolom "Net Weight" (hapus tanda koma ribuan jika ada, misal "1,197.0000" menjadi 1197.0000).
8. `pl_gw`: Ekstrak nilai angka dari kolom "Gross Weight" (hapus tanda koma ribuan jika ada).
9. `pl_volume`: Biarkan null karena tidak terdapat kolom besaran CBM/Measure pada tingkat baris di Packing List ini.

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

"""