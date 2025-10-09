# data_loader.py
import pandas as pd
from typing import Dict, Tuple
from embalse import (
    T, ARCS, A_generacion, A_inyeccion
)

# --- Mapeos robustos de nombres de central ↔ arco ---
# CSV 1: data/CaudalMax_filtrado.csv  (centrales con MÁX y rendimiento)
# Formato central (mayúsculas):
# ELTORO, ABANICO, ANTUCO, RUCUE, QUILLECO, LAJA_I, EL_DIUTO
CENTRAL_TO_GEN_ARC: Dict[str, Tuple[str, str]] = {
    "ELTORO":   ("Embalse", "ElToro"),
    "ABANICO":  ("control_Abanico", "Abanico"),
    "ANTUCO":   ("control_Antuco", "Antuco"),
    "RUCUE":    ("control_Rucue", "Rucue"),
    "QUILLECO": ("control_Quilleco", "Quilleco"),
    "LAJA_I":   ("control_Laja_I", "Laja_I"),
    "EL_DIUTO": ("control_ElDiuto", "ElDiuto"),
}

# CSV 2: data/Caudales_historicos_filtrado.csv
# (inyecciones mensuales por “central”)
# Aquí mapeamos el alias que trae el CSV
# hacia el arco de inyección correspondiente afluente_* → control_*
CENTRAL_TO_INJ_ARC: Dict[str, Tuple[str, str]] = {
    "alto_polc": ("afluente_AltoPolc", "AltoPolc"),
    "abanico":   ("afluente_Abanico",  "control_Abanico"),
    "antuco":    ("afluente_Antuco",   "control_Antuco"),
    "canecol":   ("afluente_Canecol",  "control_Canecol"),
    "tucapel":   ("afluente_Tucapel",  "control_Tucapel"),
    "laja_i":    ("afluente_Laja_I",   "control_Laja_I"),
}


def _norm_central_for_gen(name: str) -> str:
    return name.strip().upper()


def _norm_central_for_inj(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def load_caudalmax(path_csv: str):
    """
    Lee 'data/CaudalMax_filtrado.csv' y arma:
    - eta[(i,j)] = rendimiento_mwh_m3s  (solo para A_generacion)
    - cap_max[(i,j)] = caudal_maximo    (solo para A_generacion)
    Retorna (eta, cap_max, potencia_max) para registro.
    """
    df = pd.read_csv(path_csv)
    req_cols = {"central", "rendimiento_mwh_m3s",
                "potencia_maxima", "caudal_maximo"}
    missing = req_cols - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas en {path_csv}: {missing}")

    eta = {e: 0.0 for e in ARCS}
    cap_max = {e: None for e in ARCS}
    potencia_max = {}

    for row in df.itertuples(index=False):
        k = _norm_central_for_gen(row.central)
        if k not in CENTRAL_TO_GEN_ARC:
            # ignora centrales no mapeadas
            continue
        arc = CENTRAL_TO_GEN_ARC[k]
        if arc not in A_generacion:
            # seguridad extra: solo setear en arcos de generación
            continue
        eta[arc] = float(row.rendimiento_mwh_m3s)
        cap_max[arc] = float(row.caudal_maximo)
        potencia_max[arc] = float(row.potencia_maxima)

    return eta, cap_max, potencia_max


def _parse_mm_yyyy(s: str) -> Tuple[int, int]:
    # "01-1960" -> (1, 1960)
    mm, yyyy = s.strip().split("-")
    return int(mm), int(yyyy)


def load_injections_for_year(path_csv: str, target_year: int):
    """
    Lee 'data/Caudales_historicos_filtrado.csv' y construye
    I_arc[(i,j,t)] = caudal_m3s para los arcos en A_inyeccion,
    para el año 'target_year'.
    Espera columnas: 'central', 'fecha (mm-aaaa)', 'caudal (m^3/s)'.
    """
    df = pd.read_csv(path_csv)
    # normaliza nombres
    colmap = {
        "central": "central",
        "fecha (mm-aaaa)": "fecha",
        "caudal (m^3/s)": "caudal_m3s"
    }
    df = df.rename(columns=colmap)

    I_arc = {}  # (i, j, t) -> float

    for row in df.itertuples(index=False):
        cent_key = _norm_central_for_inj(row.central)
        if cent_key not in CENTRAL_TO_INJ_ARC:
            # Si viene otra "central" no usada para inyección, saltar
            continue

        month, year = _parse_mm_yyyy(row.fecha)
        if year != target_year:
            continue  # filtramos año aquí

        i, j = CENTRAL_TO_INJ_ARC[cent_key]
        if (i, j) not in A_inyeccion:
            # seguridad
            continue
        if month not in T:
            raise ValueError(f"Mes fuera de rango 1..12: {month}")

        I_arc[(i, j, month)] = float(row.caudal_m3s)

    # Relleno 0.0 donde no haya dato explícito
    for (i, j) in A_inyeccion:
        for t in T:
            I_arc.setdefault((i, j, t), 0.0)

    return I_arc
