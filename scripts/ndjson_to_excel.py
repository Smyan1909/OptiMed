import json, ndjson, pathlib
import pandas as pd
from tqdm import tqdm

SRC_DIR = pathlib.Path("mimic-fhir")   # adjust if needed
OUT_XLSX = "mimic_demo.xlsx"
MAX_ROWS = 1_000_000                        # Excel hard-limit is 1 048 576

def flatten_ndjson(path):
    """Stream-read an NDJSON file and flatten each object to 1-level dict."""
    # 👉  Force UTF-8 so Windows doesn’t fall back to cp1252
    with path.open("r", encoding="utf-8", errors="replace") as f:         
        reader = ndjson.reader(f)
        rows = (pd.json_normalize(obj, sep="__") for obj in reader)
        return pd.concat(rows, ignore_index=True)

with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as xl:
    for ndj_file in tqdm(sorted(SRC_DIR.glob("*.ndjson")), desc="Sheets"):
        sheet_name = ndj_file.stem[:31]  # Excel max sheet name length
        df = flatten_ndjson(ndj_file)

        if len(df) > MAX_ROWS:
            print(f"⚠️  {sheet_name} has {len(df):,} rows; truncating to first "
                  f"{MAX_ROWS:,} for Excel compatibility.")
            df = df.iloc[:MAX_ROWS]

        df.to_excel(xl, sheet_name=sheet_name, index=False)

print(f"✅  Workbook {OUT_XLSX} written.")
