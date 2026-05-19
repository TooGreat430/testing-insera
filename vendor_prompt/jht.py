JHT_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari teks referensi awalan "PO:" yang berada sebelum/di atas list barang (misalnya "PO:45326462").
2. `inv_spart_item_no`: Ekstrak dari kolom ke-dua dari kiri (di sebelah kanan 'Shipping Marks' dan di sebelah kiri 'Description of Goods').
3. `inv_description`: 
    - Ekstrak deskripsi spesifikasi lengkap barang dari kolom "DESCRIPTION OF GOODS" (Abaikan yang sifatnya code, part number, atau serial number).
    - Contoh:
    DESCRIPTION OF GOODS:RIM, HLQC-GA63-1,  DOUBLE WALL BLACK  20*1.5 AV  32H W/ SAFETY LINE W/O DECAL,RIMJE20HLQCGA005
    Maka inv_description adalah DOUBLE WALL BLACK  20*1.5 AV  32H W/ SAFETY LINE W/O DECAL.
4. `inv_gw` & `inv_gw_unit`: Biarkan null kecuali dinyatakan secara eksplisit di baris tersebut.
5. `inv_quantity`: Ekstrak nilai angka dari kolom "Quantity".
6. `inv_quantity_unit`: Ekstrak unit dari kolom "Quantity" yang letaknya di samping angka (misalnya "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom "Unit Price" (secara posisi sejajar ke bawah).
8. `inv_amount`: 
    - Ekstrak nilai angka dari kolom "Amount" (secara posisi sejajar ke bawah).
    - Apabila terdapat value 'FOC' pada kolom "Amount", maka inv_amount HARUS 0.

PACKING LIST (PL):
1. `pl_customer_po_no`: Ekstrak dari teks referensi awalan "PO:" (misalnya "PO:45326462").
2. `pl_item_no`: 
    - Ekstrak kode barang unik jika tercantum di dalam teks "DESCRIPTION OF GOODS" dan terletak di sebelah paling kanan.
    - Contoh:
    DESCRIPTION OF GOODS:RIM, HLQC-GA63-1,  DOUBLE WALL BLACK  20*1.5 AV  32H W/ SAFETY LINE W/O DECAL,RIMJE20HLQCGA005
    Maka pl_item_no adalah RIMJE20HLQCGA005 (bukan HLQC-GA63-1).
3. `pl_description`:
    - Ekstrak deskripsi spesifikasi lengkap barang dari kolom "DESCRIPTION OF GOODS" (Abaikan yang sifatnya code, part number, atau serial number).
    - Contoh:
    DESCRIPTION OF GOODS:RIM, HLQC-GA63-1,  DOUBLE WALL BLACK  20*1.5 AV  32H W/ SAFETY LINE W/O DECAL,RIMJE20HLQCGA005
    Maka pl_description adalah DOUBLE WALL BLACK  20*1.5 AV  32H W/ SAFETY LINE W/O DECAL.
4. `pl_quantity`: Ekstrak nilai angka dari kolom "QTY".
5. `pl_package_unit`: Apabila tidak ada kolom unit kemasan yang spesifik dan tidak ada clue package unit seperti: "Carton/CTN/CTN/CT", "Pallet/plt", "Bal/Bale", "PXCT/PK"  dll, maka return null.
6. ATURAN MERGED-CELL (berlaku untuk `pl_package_count`, `pl_nw`, `pl_gw`, `pl_volume`):

    Definisi "grup merged": dua atau lebih baris item berurutan yang SECARA VISUAL
    berbagi SATU baris nilai pada kolom PACKING PKGS / N.W. KGS / G.W. KGS / VOL/PKGS.
    Ciri-cirinya: kolom-kolom tersebut hanya berisi angka di SATU baris fisik, sedangkan
    baris-baris item lain di grup itu kosong pada kolom tersebut.

    Contoh tata letak nyata (perhatikan: nilai package/NW/GW/VOL hanya muncul SEKALI
    untuk SDXJESHIMAL002 + SDXXYSHIMAL001 secara bersamaan):

      ITEM              QTY  UNIT  QTY/PKGS  PKGS  NW/PKGS  NW KGS  GW/PKGS  GW KGS  VOL
      SDXJESHIMAL002    90   PCS   90        ──┐
      SDXXYSHIMAL001    100  PCS   100       ──┴── 1    5.00    5.00    6.00    6.00   0.05

    Aturan ekstraksi:
    - Item PERTAMA dalam grup: ambil nilai apa adanya dari baris merged
        → pl_package_count = 1, pl_nw = 5.00, pl_gw = 6.00, pl_volume = 1 * 0.05 = 0.05
    - Item KEDUA dan seterusnya: WAJIB diisi 0 untuk keempat field
        → pl_package_count = 0, pl_nw = 0, pl_gw = 0, pl_volume = 0
    - DILARANG menggantikan nilai kosong dengan angka dari kolom lain (QTY, QTY/PKGS,
      NW/PKGS, atau GW/PKGS BUKAN sumber untuk pl_package_count / pl_nw / pl_gw).
    - DILARANG membagi rata nilai merged ke semua item di grup.
    - DILARANG menyalin nilai merged ke item kedua dst.

    Sumber kolom yang BENAR untuk tiap field:
    - `pl_package_count` ← kolom "PACKING PKGS" SAJA (bukan QTY, bukan QTY/PKGS)
    - `pl_nw`            ← kolom "N.W. KGS" SAJA   (bukan N.W./PKGS)
    - `pl_gw`            ← kolom "G.W. KGS" SAJA   (bukan G.W./PKGS)
    - `pl_volume`        ← kolom "VOL/PKGS" × pl_package_count baris itu
                           (untuk item kedua dst dalam grup, otomatis = 0)

    Untuk item TUNGGAL (bukan bagian grup merged), ambil nilai langsung dari kolomnya
    masing-masing seperti biasa, dan hitung pl_volume = VOL/PKGS × pl_package_count.

BILL OF LADING (BL):
1. `bl_description`: 
    - bl_description DILARANG KERAS untuk diisi null.
    - Dimapping dengan inv_description berdasarkan kemiripan. Jika inv_description tidak exist pada dokumen BL, maka PILIH SALAH SATU ITEM RANDOM YANG SEKIRANYA PALING MIRIP.
    Contoh:
    Pada inv_description ada value:
    RIM, HLQC-GA63-1
    RIM, HLQC-08A
    RIM, HLQC-23Y
    RIM, HLQC-08A
    RIM, HLQC-23Y
    RIM, HLQC-04

    Pada BL ada deskripsi item:
    RIM, HLQC-08A
    RIM, HLQC-23Y
    BASKET
    CARRIER
    FORK END

    Maka mapping value bl_desriptionnya adalah:
    [PILIH SECARA RANDOM YANG SEKIRANYA PALING MIRIP]
    RIM, HLQC-08A
    RIM, HLQC-23Y
    RIM, HLQC-08A
    RIM, HLQC-23Y
    [PILIH SECARA RANDOM YANG SEKIRANYA PALING MIRIP]

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
3. `coo_description`: Ekstrak deskripsi teks dari kolom "8. Number and kind of packages; and description of goods." Abaikan keterangan jumlah paket (angka dan kata) pada field ini.
4. `coo_hs_code`: Ekstrak dari "9. HS Code of the goods".
5. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "TWENTY (20) PKGS" ambil angka 20).
6. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "PKGS").
7. `coo_gw` & `coo_quantity`: Ekstrak berat angka dari kolom "12. Quantity...".
8. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KG").
9. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
10. `coo_customer_po_no`: Biarkan null kecuali ada referensi nomor PO yang secara spesifik ditulis dalam kolom 7 atau 8.
"""