SRAM_PROMPT = """
INVOICE (INV):
1. `inv_customer_po_no`: Ekstrak dari teks awalan "P.O.#" di kolom "DESCRIPTION". Ambil angka utamanya saja sebelum tanda kurung (misalnya dari "P.O.# 43018080 (251772921)", ekstrak "43018080").
2. `inv_spart_item_no`: Ekstrak kode Part Number (berformat angka dengan titik) dari baris pertama di blok deskripsi (misalnya "00.3018.201.000" atau "00.5318.033.000").
3. `inv_description`: Ekstrak teks deskripsi barang yang berada persis di bawah Part Number (misalnya "EP POWERPACK 1 BATTERY").
4. `inv_gw` & `inv_gw_unit`: Biarkan null karena tidak terdapat informasi berat pada tingkat baris di invoice ini.
5. `inv_quantity`: Ekstrak nilai angka dari kolom kuantitas di sebelah kanan deskripsi (misalnya "42").
6. `inv_quantity_unit`: Ekstrak unit dari kolom kuantitas (misalnya "PCS").
7. `inv_unit_price`: Ekstrak nilai angka dari kolom 'Unit Price' di bawah teks FOB (misalnya dari "48.950", ambil 48.950).
8. `inv_amount`: Ekstrak nilai angka dari kolom 'Amount' di sebelah paling kanan / kolom mata uang USD (misalnya "2,055.90", hapus koma ribuan).

PACKING LIST (PL):

CATATAN STRUKTUR PL SRAM — BACA DULU SEBELUM MENGEKSTRAK:
- C/NO. (nomor karton) bersifat LOKAL per PO. Setiap bagian "P.O.#" baru mereset urutan C/NO.-nya sendiri.
  Contoh: PO 43018080 punya C/NO. 1, lalu PO 43018083 juga punya C/NO. 1 sendiri — ini bukan duplikat.
- Beberapa item muncul TANPA C/NO. eksplisit di kolom kiri (hanya Part Number dan Q'TY/NW tanpa nomor karton).
  Ini berarti item tersebut berbagi karton dengan item di atasnya — JANGAN hitung sebagai karton tambahan.
- Kolom MEAS'T selalu kosong di seluruh PL SRAM. pl_volume dan pl_volume_unit SELALU null.
- Jumlah baris output yang dihasilkan HARUS SAMA PERSIS dengan jumlah baris invoice. Jangan membuat baris ekstra.

1. `pl_customer_po_no`: Ekstrak dari teks awalan "P.O.#" di dalam blok "DESCRIPTION" (misalnya "43018080").
2. `pl_item_no`: Ekstrak kode Part Number (berformat angka dengan titik) dari kolom "DESCRIPTION" (misalnya "00.3018.201.000").
3. `pl_description`: Ekstrak teks deskripsi barang yang berada di bawah Part Number.
4. `pl_package_unit`: Simpulkan sebagai "CTNS" berdasarkan header "C/NO.".
5. `pl_package_count`:
    - Hitung jumlah kemasan dari rentang C/NO. untuk baris ini (dalam konteks PO yang sama).
    - Rentang "1-5" → 5 CTNs. "1-2" → 2. Angka tunggal "46" → 1.
    - ITEM TANPA C/NO. (berbagi karton): Jika item muncul tanpa nomor di kolom C/NO., pl_package_count = 0.
    - SATU ARTIKEL DENGAN BEBERAPA KELOMPOK C/NO. DALAM SATU PO — PEMETAAN KE BARIS INVOICE:
      Jika satu artikel dalam satu PO memiliki beberapa kelompok C/NO. di PL (mis. C/NO. 1-5 dan C/NO. 6-10
      dan C/NO. 11 dan C/NO. 12), DAN invoice juga memiliki beberapa baris untuk artikel + PO yang sama,
      maka cocokkan kelompok C/NO. secara berurutan ke baris invoice berdasarkan kuantitas invoice:
        * Baris invoice 1 (mis. 50 PCS) → kelompok C/NO. pertama yang Q'TY-nya = 50 PCS
        * Baris invoice 2 (mis. 50 PCS) → kelompok C/NO. berikutnya yang Q'TY-nya = 50 PCS
        * Baris invoice N (mis. 17 PCS) → GABUNGKAN sisa kelompok C/NO. yang jumlah Q'TY-nya = 17 PCS
          (mis. C/NO. 11: 10 PCS + C/NO. 12: 7 PCS → pl_package_count = 1+1 = 2, pl_quantity = 17)
      PENTING: Hasilkan TEPAT sebanyak baris invoice yang ada — jangan lebih, jangan kurang.

6. `pl_quantity`:
    - Ekstrak nilai dari kolom "Q'TY".
    - Jika ada simbol "@" (mis. "@20"), kalikan dengan jumlah karton dalam kelompok ini untuk mendapat total.
      Baris ringkasan total (mis. "100 PCS") langsung di bawah baris "@" adalah angka yang sudah dikalikan — gunakan itu.
    - Tanpa "@", ambil langsung.
    - Jika satu baris output menggabungkan beberapa kelompok C/NO. (lihat aturan pl_package_count di atas),
      JUMLAHKAN kuantitas semua kelompok tersebut.

7. `pl_nw`:
    - Ekstrak dari kolom "N.W. KGS". Jika "@", kalikan dengan jumlah karton kelompok ini.
    - Jika menggabungkan beberapa kelompok C/NO., JUMLAHKAN NW semua kelompok.
    - Item tanpa NW → 0.

8. `pl_gw`:
    - Ekstrak dari kolom "G.W. KGS". Jika "@", kalikan dengan jumlah karton kelompok ini.
    - Jika menggabungkan beberapa kelompok C/NO., JUMLAHKAN GW semua kelompok.
    - Item tanpa GW (tidak tercantum di dokumen) → 0. JANGAN mengasumsikan nilai GW.

9. `pl_volume`:
    - Kolom MEAS'T SELALU KOSONG di PL SRAM. SELALU isi pl_volume = null dan pl_volume_unit = null.
    - DILARANG KERAS mengasumsikan atau mengarang nilai pl_volume.

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
1. `coo_seq`:
   - Ambil dari kolom "Item number".
   - Nilai numeric.
   - Item number tercetak jelas seperti:
     - 1
     - 2
     - 3
     - ...
2. `coo_mark_number`: Ekstrak dari "7. Marks and numbers on packages" (misalnya, "N/M").
3. `coo_description`: Ekstrak deskripsi teks dari kolom "8. Number and kind of packages; and description of goods." Abaikan keterangan jumlah paket (angka dan kata) pada field ini.
4. `coo_hs_code`: Ekstrak dari "9. HS Code of the goods".
5. `coo_package_count`: Ekstrak kata/angka numerik dari kalimat awal di kolom 8 (misalnya, dari "TEN (10) CARTONS" ambil angka 10).
6. `coo_package_unit`: Ekstrak jenis kemasan dari kalimat awal di kolom 8 (misalnya, "CARTONS").
7. `coo_gw` & `coo_quantity`: Ekstrak berat angka dari kolom "12. Quantity..." (biasanya ditulis dengan format seperti "255.6KGS G.W.").
8. `coo_unit`: Ekstrak unit berat dari kolom 12 (misalnya, "KGS").
9. `coo_criteria`: Ekstrak dari "10. Origin Conferring Criterion" (misalnya "PE").
10. `coo_customer_po_no`: Biarkan null kecuali ada nomor PO yang secara spesifik ditulis per baris item.
"""