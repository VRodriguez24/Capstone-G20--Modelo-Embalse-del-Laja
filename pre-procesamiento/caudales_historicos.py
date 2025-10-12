from pathlib import Path
import pandas as pd
import re
import unicodedata

"""
Pre-procesamiento: Caudales históricos (semanal → mensual)
- Lee pre-procesamiento/data/Caudales_historicos.xlsx
- Usa primeras 50 columnas, elimina 3 primeras filas y toma la fila
  siguiente como encabezado
- Estandariza encabezados
- Wide→Long por semanas, obtiene el mes y promedia por mes
- Filtra por centrales de interés (opcional)
- Completa el panel mensual por central (todos los meses entre min y max año)
- Orden: por central (a-z), luego por fecha ascendente (mm-aaaa)
- Exporta: central, fecha (mm-aaaa), caudal (m^3/s)
"""

CENTRALES_KEEP = [
    "ELTORO", "ABANICO", "ANTUCO", "CANECOL", "TUCAPEL", "LAJA_I"
    ]

MONTH_MAP = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12
}


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def norm_header(s: str) -> str:
    s = strip_accents(s).lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def to_float(x):
    if pd.isna(x):
        return pd.NA
    s = str(x).strip().replace("\xa0", "")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    s = s.replace(" ", "")
    return pd.to_numeric(s, errors="coerce")


def correct_year(year):
    y = pd.to_numeric(year, errors="coerce")
    if pd.isna(y):
        return pd.NA
    y = int(y)
    if y < 100:
        return 1900 + y if y >= 60 else 2000 + y
    return y


def month_from_token(tok: str):
    t = strip_accents(tok).lower().strip()
    t = re.sub(r"\s+", " ", t)
    parts = re.split(r"[^a-z0-9]+", t)
    for p in parts:
        m = MONTH_MAP.get(p[:3])
        if m:
            return m
    return None


def run():
    base = Path(__file__).resolve().parents[1]
    in_path = base / "pre-procesamiento" / "data" / "Caudales_historicos.xlsx"
    out_dir = base / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) leer
    xls = pd.ExcelFile(in_path)
    sheet = xls.sheet_names[0]
    df_raw = pd.read_excel(xls, sheet_name=sheet)

    # 2) primeras 50 columnas
    df = df_raw.iloc[:, :50].copy()

    # 3) eliminar 3 primeras filas y usar la siguiente como encabezado
    df = df.iloc[3:, :].reset_index(drop=True)
    df.columns = df.iloc[0]
    df = df.iloc[1:, :].reset_index(drop=True)

    # 4) estandarizar encabezados
    df.columns = [norm_header(c) for c in df.columns]

    col_central = "central" if "central" in df.columns else None
    year_col = "ano" if "ano" in df.columns else None
    if not col_central:
        raise ValueError(
            "No se encontró columna 'Central' luego de normalizar encabezados."
            )
    if not year_col:
        raise ValueError(
            "No se encontró columna 'AÑO' luego de normalizar encabezados."
        )

    # 5) wide → long (semanas)
    value_cols = [c for c in df.columns if c not in (col_central, year_col)]
    if not value_cols:
        raise ValueError("No se detectaron columnas semanales.")
    long = df.melt(id_vars=[col_central, year_col],
                   value_vars=value_cols,
                   var_name="semana",
                   value_name="caudal")

    long["caudal"] = long["caudal"].apply(to_float)
    long[year_col] = long[year_col].apply(correct_year)
    long["mes"] = long["semana"].map(month_from_token)
    long = long.dropna(subset=["caudal", "mes", year_col]).copy()
    long["mes"] = long["mes"].astype(int)
    long[year_col] = long[year_col].astype(int)

    # Filtrar por centrales (opcional)
    if CENTRALES_KEEP:
        keep_norm = {
            "".join(strip_accents(x).upper().split())
            for x in CENTRALES_KEEP
        }
        long["_central_norm"] = long[col_central].astype(str).apply(
            lambda s: "".join(strip_accents(s).upper().split())
        )
        long = long[long["_central_norm"].isin(keep_norm)].copy()

    # 6) promedio mensual por central
    mensual = (long
               .groupby([col_central, year_col, "mes"],
                        as_index=False)["caudal"]
               .mean())

    # 7) construir panel completo por central (todos los meses entre los años)
    # a) crear columna periodo mensual tipo Period('M') para ordenar/expandir
    mensual["periodo"] = pd.PeriodIndex(year=mensual[year_col],
                                        month=mensual["mes"], freq="M")

    #    b) para cada central, crear rango mensual completo y reindexar
    outs = []
    for central, g in mensual.groupby(col_central, sort=True):
        pmin, pmax = g["periodo"].min(), g["periodo"].max()
        full = pd.DataFrame({"periodo": pd.period_range(pmin, pmax, freq="M")})
        g2 = full.merge(g[["periodo", "caudal"]], on="periodo", how="left")
        g2[col_central] = central
        # Si quieres rellenar meses faltantes con el último valor disponible:
        # g2["caudal"] = g2["caudal"].ffill()
        outs.append(g2)

    panel = pd.concat(outs, ignore_index=True)

    # 8) formateo final y orden
    panel["central"] = panel[col_central].astype(str).str.strip().str.lower()
    panel = panel.sort_values(["central", "periodo"], kind="stable")
    panel["fecha (mm-aaaa)"] = panel["periodo"].dt.strftime("%m-%Y")
    panel.rename(columns={"caudal": "caudal (m^3/s)"}, inplace=True)

    out = panel[["central", "fecha (mm-aaaa)", "caudal (m^3/s)"]]

    # 9) exportar
    out_path = out_dir / "Caudales_historicos_filtrado.csv"
    out.to_csv(out_path, index=False)

    print()
    print("📊 Semanal → Mensual completado")
    centrales = out['central'].unique()
    n_centrales = out['central'].nunique()
    periodos = out['fecha (mm-aaaa)'].nunique()
    print(f"\n🏭 {n_centrales} centrales x {periodos} periodos")
    print(f"{centrales}\n")
    print(f"📈 Total: {len(out):,} filas")
    print(f"💾 {out_path}")
    print()


if __name__ == "__main__":
    run()
