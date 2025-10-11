# src/montecarlo.py
from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, Tuple, List
from data_loader import CENTRAL_TO_INJ_ARC, T
from embalse import A_inyeccion

def _parse_mm_yyyy(s: str) -> Tuple[int, int]:
    mm, yyyy = s.strip().split("-")
    return int(mm), int(yyyy)

class BlockBootstrapSampler:
    """
    Block bootstrap estacional sobre afluentes:
    - Preserva estacionalidad por mes.
    - Usa bloques de longitud B (p.ej. 2-3 meses) para mantener rachas.
    - Devuelve I_arc[(i,j,t)] (m3/s) para t=1..12.
    """
    def __init__(self, path_csv: str, random_state: int = 123):
        self.rng = np.random.default_rng(random_state)
        df = pd.read_csv(path_csv).rename(columns={
            "central": "central",
            "fecha (mm-aaaa)": "fecha",
            "caudal (m^3/s)": "q"
        })
        df["central_norm"] = df["central"].str.strip().str.lower().str.replace(" ", "_", regex=False)
        mm_yyyy = df["fecha"].apply(_parse_mm_yyyy)
        df["mes"] = mm_yyyy.apply(lambda x: x[0])
        df["anio"] = mm_yyyy.apply(lambda x: x[1])

        # Estructura por alias → dataframe pivote (rows=anio, cols=mes 1..12)
        self.alias_tables: Dict[str, pd.DataFrame] = {}
        for alias, sub in df.groupby("central_norm"):
            piv = sub.pivot_table(index="anio", columns="mes", values="q", aggfunc="median")
            piv = piv.reindex(columns=range(1, 13))  # asegurar 1..12
            self.alias_tables[alias] = piv.sort_index()

        # Mapa de alias a arcos del modelo (solo los que usamos)
        self.alias_to_arc = {
            alias: arc for alias, arc in CENTRAL_TO_INJ_ARC.items() if arc in A_inyeccion
        }

    def sample_year(self, block_len: int = 3) -> Dict[Tuple[str, str, int], float]:
        """
        Genera un escenario anual por alias usando bloques consecutivos.
        - block_len * k_blocks = 12 (se ajusta el último bloque si sobra)
        """
        I_arc = {}
        # descomposición de 12 en bloques
        L = block_len
        blocks = [L] * (12 // L)
        if sum(blocks) < 12:
            blocks.append(12 - sum(blocks))

        # por cada afluente (alias) construye su serie mensual (12) por bloques
        for alias, (i, j) in self.alias_to_arc.items():
            piv = self.alias_tables.get(alias)
            if piv is None or piv.empty:
                # sin datos: cero
                for t in T:
                    I_arc[(i, j, t)] = 0.0
                continue

            # genera meses del 1..12 en bloques
            t_cursor = 1
            for b_len in blocks:
                # elige aleatoriamente un año "base" y un mes de inicio (estacionalmente coherente)
                year = int(self.rng.choice(piv.index))
                start_m = int(self.rng.integers(1, 13))  # 1..12
                # toma b_len meses consecutivos con wrap sobre 12
                seq = [(start_m + k - 1) % 12 + 1 for k in range(b_len)]
                # valores: para cada mes m, toma valor del año "year" si existe; si NaN, busca sustituto
                for m in seq:
                    val = piv.loc[year, m] if m in piv.columns else np.nan
                    if pd.isna(val):
                        # fallback: mediana histórica del mes
                        col = piv[m] if m in piv.columns else None
                        val = float(np.nanmedian(col.values)) if col is not None else 0.0
                    I_arc[(i, j, t_cursor)] = float(val)
                    t_cursor += 1
                    if t_cursor > 12:
                        break
                if t_cursor > 12:
                    break

            # por si faltó algo (datos pobres)
            for t in T:
                I_arc.setdefault((i, j, t), 0.0)

        return I_arc

    def sample_year_with_noise(self, block_len: int = 3, sigma: float = 0.15) -> Dict[Tuple[str, str, int], float]:
        """
        Igual que sample_year pero aplicando ruido lognormal multiplicativo suave.
        """
        I = self.sample_year(block_len=block_len)
        noisy = {}
        for key, q in I.items():
            mul = float(self.rng.lognormal(mean=0.0, sigma=sigma))
            noisy[key] = max(0.0, q * mul)
        return noisy
