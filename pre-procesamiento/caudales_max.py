from pathlib import Path
import pandas as pd
import re
import unicodedata

"""
Pre-procesamiento: Caudal Máximo por central (versión simple).
- Carga pre-procesamiento/data/CaudalMax.xlsx
- Estandariza encabezados
- Convierte a numérico (coma/punto)
- Filtra: rendimiento != 1
- Exporta a data/CaudalMax_filtrado.csv con columnas:
  central, rendimiento_mwh_m3s, potencia_maxima, caudal_maximo
"""


def _norm_header(s: str) -> str:
    # quita tildes
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    # minusculas
    s = s.lower().strip()
    # colapsa espacios y saltos de línea a un solo espacio
    s = re.sub(r"\s+", " ", s)
    return s


def to_numeric(x):
    if pd.isna(x):
        return pd.NA
    s = str(x).strip().replace("\xa0", "")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    s = s.replace(" ", "")
    return pd.to_numeric(s, errors="coerce")


def run():
    base = Path(__file__).resolve().parents[1]
    in_path = base / "pre-procesamiento" / "data" / "CaudalMax.xlsx"
    out_dir = base / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    xls = pd.ExcelFile(in_path)
    df = pd.read_excel(xls, sheet_name=xls.sheet_names[0])

    # 1) Normalizar encabezados con saltos de línea/acentos
    norm_map = {c: _norm_header(str(c)) for c in df.columns}
    df = df.rename(columns=norm_map)

    # 2) Map flexible -> nombres estándar snake case que deseas
    # como vienen normalizados -> como quieres exportar
    rename_std = {
        "central": "central",
        "rendimiento [mwh/m3s]": "rendimiento_mwh_m3s",
        "potencia maxima": "potencia_maxima",
        "caudal maximo": "caudal_maximo",
    }

    missing = [k for k in rename_std.keys() if k not in df.columns]
    if missing:
        raise ValueError(
            f"Tras normalizar, faltan columnas: {missing}\n"
            f"Veo: {list(df.columns)}"
        )

    df = df.rename(columns=rename_std)

    # 3) Convertir a numérico
    for c in ["rendimiento_mwh_m3s", "potencia_maxima", "caudal_maximo"]:
        df[c] = df[c].apply(to_numeric)

    # 4) Filtrar rendimiento != 1 (y no NaN)
    df = df[df["rendimiento_mwh_m3s"].notna()]
    df = df[df["rendimiento_mwh_m3s"] != 1]

    # 5) Exportar
    out = df[["central", "rendimiento_mwh_m3s",
              "potencia_maxima", "caudal_maximo"]].copy()
    out.to_csv(out_dir / "CaudalMax_filtrado.csv", index=False)

    print()
    print("🔋 CaudalMax procesado exitosamente")
    print(f"📂 {in_path.name} → {len(out)} filas filtradas")
    print(f"💾 {out_dir / 'CaudalMax_filtrado.csv'}")
    print()


if __name__ == "__main__":
    run()
