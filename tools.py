"""
tools.py
Kumpulan tools untuk chatbot Yele:
- Business calculator tools (deterministik, presisi)
- Tool riset pasar (web search) untuk membantu user awam yang belum
  punya data harga/biaya di daerahnya
"""

from langchain_core.tools import tool
from ddgs import DDGS


@tool
def cari_data_pasar(query: str) -> str:
    """
    Mencari informasi pasar terkini di internet: UMR/UMK suatu daerah,
    kisaran harga bahan baku, harga sewa alat/kendaraan/tempat, harga
    jasa, rata-rata harga jual kompetitor, atau data pendukung bisnis
    lain yang belum diketahui user.

    WAJIB dipakai ketika user awam (belum menyebutkan angka biaya/harga
    sendiri) supaya Yele bisa mengedukasi dengan data nyata, bukan
    menebak-nebak angka dari ingatan sendiri.

    Args:
        query: Kata kunci pencarian yang spesifik dan menyertakan lokasi
            jika relevan. Contoh: "UMR Surabaya 2026", "harga sewa mobil
            pengantin Surabaya per hari", "harga cabai rawit kilogram
            Jakarta hari ini".
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, region="id-id", max_results=5))
    except Exception as e:
        return f"Gagal melakukan pencarian: {e}"

    if not results:
        return f"Tidak ditemukan hasil pencarian untuk: '{query}'."

    formatted = [f"Hasil pencarian untuk '{query}':"]
    for i, r in enumerate(results, start=1):
        title = r.get("title", "")
        body = r.get("body", "")
        href = r.get("href", "")
        formatted.append(f"{i}. {title}\n   {body}\n   Sumber: {href}")

    return "\n\n".join(formatted)


@tool
def hitung_biaya_produksi(
    biaya_bahan_baku: float,
    biaya_tenaga_kerja: float,
    biaya_overhead: float,
    jumlah_unit: float,
) -> str:
    """
    Menghitung total biaya produksi dan biaya produksi per unit.

    Gunakan tool ini ketika user memberi informasi biaya bahan baku,
    biaya tenaga kerja, biaya overhead (listrik, sewa, dll), dan jumlah
    unit yang diproduksi.

    Args:
        biaya_bahan_baku: Total biaya bahan baku (Rupiah).
        biaya_tenaga_kerja: Total biaya tenaga kerja (Rupiah).
        biaya_overhead: Total biaya overhead/operasional (Rupiah).
        jumlah_unit: Jumlah unit yang diproduksi (harus > 0).
    """
    if jumlah_unit <= 0:
        return "Error: jumlah unit produksi harus lebih besar dari 0."

    total_biaya = biaya_bahan_baku + biaya_tenaga_kerja + biaya_overhead
    biaya_per_unit = total_biaya / jumlah_unit

    return (
        f"Total biaya produksi: Rp {total_biaya:,.0f}\n"
        f"Jumlah unit: {jumlah_unit:,.0f}\n"
        f"Biaya produksi per unit: Rp {biaya_per_unit:,.2f}"
    ).replace(",", ".")


@tool
def hitung_harga_jual(
    biaya_produksi_per_unit: float,
    target_margin_persen: float,
) -> str:
    """
    Menghitung rekomendasi harga jual berdasarkan biaya produksi per unit
    dan target margin keuntungan yang diinginkan (dalam persen dari harga jual).

    Gunakan tool ini ketika user sudah tahu biaya produksi per unit dan
    ingin tahu berapa harga jual yang pas untuk mencapai margin tertentu.

    Args:
        biaya_produksi_per_unit: Biaya produksi per unit (Rupiah).
        target_margin_persen: Target margin keuntungan dalam persen (0-99).
    """
    if target_margin_persen < 0 or target_margin_persen >= 100:
        return "Error: target margin harus di antara 0 dan 99 persen."
    if biaya_produksi_per_unit <= 0:
        return "Error: biaya produksi per unit harus lebih besar dari 0."

    # margin dihitung terhadap harga jual: HJ = biaya / (1 - margin%)
    harga_jual = biaya_produksi_per_unit / (1 - target_margin_persen / 100)
    keuntungan_per_unit = harga_jual - biaya_produksi_per_unit

    return (
        f"Biaya produksi per unit: Rp {biaya_produksi_per_unit:,.2f}\n"
        f"Target margin: {target_margin_persen:.1f}%\n"
        f"Rekomendasi harga jual: Rp {harga_jual:,.2f}\n"
        f"Keuntungan per unit: Rp {keuntungan_per_unit:,.2f}"
    ).replace(",", ".")


@tool
def hitung_margin(
    harga_jual: float,
    biaya_produksi: float,
) -> str:
    """
    Menghitung margin keuntungan (dalam persen dan rupiah) dari harga jual
    dan biaya produksi yang sudah diketahui.

    Gunakan tool ini ketika user sudah punya harga jual dan biaya produksi,
    lalu ingin tahu berapa margin keuntungannya.

    Args:
        harga_jual: Harga jual per unit (Rupiah).
        biaya_produksi: Biaya produksi per unit (Rupiah).
    """
    if harga_jual <= 0:
        return "Error: harga jual harus lebih besar dari 0."

    margin_rupiah = harga_jual - biaya_produksi
    margin_persen = (margin_rupiah / harga_jual) * 100

    status = "untung" if margin_rupiah > 0 else ("rugi" if margin_rupiah < 0 else "impas")

    return (
        f"Harga jual: Rp {harga_jual:,.2f}\n"
        f"Biaya produksi: Rp {biaya_produksi:,.2f}\n"
        f"Margin: Rp {margin_rupiah:,.2f} ({margin_persen:.2f}%)\n"
        f"Status: {status}"
    ).replace(",", ".")


@tool
def hitung_bep(
    biaya_tetap: float,
    harga_jual_per_unit: float,
    biaya_variabel_per_unit: float,
) -> str:
    """
    Menghitung Break Even Point (BEP) / titik impas usaha, baik dalam
    satuan unit maupun rupiah.

    Gunakan tool ini ketika user ingin tahu berapa unit atau berapa rupiah
    penjualan yang dibutuhkan agar usahanya balik modal (tidak untung
    tidak rugi).

    Args:
        biaya_tetap: Total biaya tetap per periode, misal sewa, gaji tetap (Rupiah).
        harga_jual_per_unit: Harga jual per unit (Rupiah).
        biaya_variabel_per_unit: Biaya variabel per unit, misal bahan baku (Rupiah).
    """
    margin_kontribusi = harga_jual_per_unit - biaya_variabel_per_unit

    if margin_kontribusi <= 0:
        return (
            "Error: harga jual per unit harus lebih besar dari biaya variabel "
            "per unit, jika tidak BEP tidak akan pernah tercapai."
        )

    bep_unit = biaya_tetap / margin_kontribusi
    bep_rupiah = bep_unit * harga_jual_per_unit

    return (
        f"Biaya tetap: Rp {biaya_tetap:,.0f}\n"
        f"Margin kontribusi per unit: Rp {margin_kontribusi:,.2f}\n"
        f"BEP: {bep_unit:,.1f} unit\n"
        f"BEP dalam rupiah: Rp {bep_rupiah:,.0f}"
    ).replace(",", ".")


# Daftar semua tools yang tersedia untuk agent.
# Tambahkan tool baru ke sini agar otomatis dikenali oleh agent.
ALL_TOOLS = [
    cari_data_pasar,
    hitung_biaya_produksi,
    hitung_harga_jual,
    hitung_margin,
    hitung_bep,
]
