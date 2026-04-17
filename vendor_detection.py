import json
import os
import re
import importlib.util
from pathlib import Path
from PyPDF2 import PdfReader
from google import genai

from config import PROJECT_ID, LOCATION

genai_client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location=LOCATION,
)

VENDOR_LIST = [
    "jht_carbon",
    "jht",
    "tangsan_jinhengtong",
    "joy",
    "kunshan_landon",
    "shimano_inc",
    "novatec",
    "suntour_shenzhen",
    "suntour_vietnam",
    "bafang_motor",
    "ningbo_fordario",
    "ningbo_julong",
    "jiangsiu_huajiu",
    "fox",
    "haomeng",
    "to_ho",
    "velo_kunshan",
    "velo_enterprise",
    "shimano_singapore",
    "liow_ko",
    "auriga",
    "hl_shenzhen",
]

BASE_DIR = Path(__file__).resolve().parent
VENDOR_PROMPT_DIR = Path(
    os.getenv("VENDOR_PROMPT_DIR", str(BASE_DIR / "vendor_prompt"))
)

def _read_first_invoice_text(pdf_path: str, max_pages: int = 2) -> str:
    reader = PdfReader(pdf_path)
    texts = []
    for i in range(min(max_pages, len(reader.pages))):
        try:
            texts.append(reader.pages[i].extract_text() or "")
        except Exception:
            pass
    return "\n".join(texts)

def _extract_json_safe(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = raw.replace("```json", "").replace("```", "").strip()

    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if match:
        raw = match.group(0)

    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise Exception("Vendor detector output bukan JSON object")
    return obj

def detect_vendor_from_invoice_text(invoice_text: str) -> str:
    prompt = f"""
ROLE:
Anda hanya bertugas mendeteksi vendor dari dokumen invoice.

TUGAS:
Pilih SATU vendor_id yang paling cocok dari daftar berikut.
Jika benar-benar tidak ada yang cocok, pilih "default".

DAFTAR vendor_id VALID:
{json.dumps(VENDOR_LIST, ensure_ascii=False)}

ATURAN:
- Hanya boleh memilih SATU nilai dari daftar vendor_id di atas, atau "default".
- Jangan membuat nama vendor_id baru.
- Gunakan konteks nama perusahaan, seller, shipper, manufacturer, exporter, alamat, branding, dan pola dokumen invoice.
- Fokus pada vendor/supplier utama dokumen invoice.
- Jika ada beberapa nama perusahaan, pilih yang paling mungkin adalah vendor utama.
- Jika tidak yakin, pilih "default".
- Output HANYA JSON object valid.

OUTPUT SCHEMA:
{{
  "vendor_id": "string"
}}

INVOICE TEXT:
\"\"\"
{invoice_text[:25000]}
\"\"\"
"""
    last_err = None

    for _ in range(3):
        try:
            response = genai_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )

            raw = getattr(response, "text", "") or ""
            obj = _extract_json_safe(raw)
            vendor_id = str(obj.get("vendor_id", "default")).strip().lower()

            if vendor_id not in VENDOR_LIST:
                return "default"
            return vendor_id

        except Exception as e:
            last_err = e

    print(f"[VENDOR DETECTOR ERROR] {last_err}")
    return "default"

def detect_vendor_from_invoice_pdf(pdf_path: str) -> str:
    invoice_text = _read_first_invoice_text(pdf_path, max_pages=2)
    if not invoice_text.strip():
        return "default"
    return detect_vendor_from_invoice_text(invoice_text)

def _load_module_from_path(py_path: str):
    module_name = f"_vendor_prompt_{Path(py_path).stem}"
    spec = importlib.util.spec_from_file_location(module_name, py_path)
    if spec is None or spec.loader is None:
        raise Exception(f"Gagal load module: {py_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def load_vendor_prompt_text(vendor_id: str) -> str:
    if not vendor_id or vendor_id == "default":
        print("[VENDOR PROMPT] vendor_id=default -> pakai prompt bawaan")
        return ""

    py_path = VENDOR_PROMPT_DIR / f"{vendor_id}.py"
    if not py_path.exists():
        print(f"[VENDOR PROMPT] file tidak ditemukan untuk vendor_id={vendor_id} path={py_path}")
        return ""

    module = _load_module_from_path(str(py_path))

    for attr_name in dir(module):
        if attr_name.endswith("_PROMPT"):
            value = getattr(module, attr_name)
            if isinstance(value, str) and value.strip():
                print(f"[VENDOR PROMPT] loaded constant={attr_name} vendor_id={vendor_id}")
                return value.strip()

    return ""