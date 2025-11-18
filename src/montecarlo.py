"""
SIMULACIÓN HÍBRIDA MONTE CARLO + MODELO DETERMINISTA

Combina lo mejor de ambos métodos:
- Monte Carlo: Generación estocástica de escenarios de afluentes
- Determinista: Optimización robusta con KPIs consistentes

Características:
- Bootstrap por bloques para preservar correlaciones temporales
- Análisis multi-año con KPIs agregados
- Alta tasa de éxito vs Monte Carlo puro
- Sin ruido estocástico adicional (bootstrap puro)

Uso: python src/montecarlo.py
"""

from __future__ import annotations

import os
import numpy as np
import pandas as pd
from typing import Dict, Tuple, List, Optional

# Importaciones del modelo
from data_loader import CENTRAL_TO_INJ_ARC
from embalse import A_inyeccion
from model import build_model_for_one_year, T, Conv, V_max
from kpi import extract_kpis

# Detección automática de rutas de datos
if os.path.exists("data/Caudales_historicos_filtrado.csv"):
    INJ_CSV = "data/Caudales_historicos_filtrado.csv"
else:
    INJ_CSV = "../data/Caudales_historicos_filtrado.csv"


class BlockBootstrapSampler:
    """
    Generador de escenarios estocásticos para caudales de afluentes.

    Utiliza bootstrap por bloques para preservar:
    - Estacionalidad mensual
    - Correlaciones temporales de corto plazo
    - Distribuciones estadísticas históricas
    """

    def __init__(self, csv_path: str, random_state: int = 42) -> None:
        """
        Inicializa el sampler con datos históricos.

        Args:
            csv_path: Ruta al archivo CSV con caudales históricos
            random_state: Semilla para reproducibilidad
        """
        self.rng = np.random.default_rng(random_state)
        self.alias_tables = self._load_and_process_data(csv_path)
        self.alias_to_arc = {
            alias: arc
            for alias, arc in CENTRAL_TO_INJ_ARC.items()
            if arc in A_inyeccion
        }

    def _load_and_process_data(self, csv_path: str) -> Dict[str, pd.DataFrame]:
        """Carga y procesa datos históricos en tablas pivotadas."""
        try:
            df = pd.read_csv(csv_path)
            df = df.rename(columns={
                "central": "central",
                "fecha (mm-aaaa)": "fecha",
                "caudal (m^3/s)": "caudal"
            })
        except Exception as e:
            raise ValueError(f"Error cargando {csv_path}: {e}")

        # Normalizar nombres y extraer fechas
        df["central_norm"] = (
            df["central"]
            .str.strip()
            .str.lower()
            .str.replace(" ", "_", regex=False)
        )

        date_parts = df["fecha"].str.strip().str.split("-")
        df["mes"] = date_parts.str[0].astype(int)
        df["año"] = date_parts.str[1].astype(int)

        # Crear tablas pivotadas por central
        alias_tables = {}
        for alias, group in df.groupby("central_norm"):
            pivot = group.pivot_table(
                index="año",
                columns="mes",
                values="caudal",
                aggfunc="median"
            )
            pivot = pivot.reindex(columns=range(1, 13))  # Asegurar 12 meses
            alias_tables[alias] = pivot.sort_index()

        return alias_tables

    def sample_year(
        self,
        block_len: int = 3
    ) -> Dict[Tuple[str, str, int], float]:
        """
        Genera escenario anual usando bootstrap por bloques.

        Args:
            block_len: Longitud de bloques temporales (meses)

        Returns:
            Diccionario con inyecciones I_arc[(i,j,t)] en m³/s
        """
        # Descomponer año en bloques
        blocks = self._decompose_year_into_blocks(block_len)
        I_arc = {}

        for alias, (i, j) in self.alias_to_arc.items():
            pivot_table = self.alias_tables.get(alias)

            if pivot_table is None or pivot_table.empty:
                # Sin datos: asignar cero
                for t in T:
                    I_arc[(i, j, t)] = 0.0
                continue

            # Generar serie mensual por bloques
            month_cursor = 1
            for block_size in blocks:
                month_cursor = self._generate_block(
                    pivot_table, block_size, month_cursor, I_arc, (i, j)
                )
                if month_cursor > 12:
                    break

        return I_arc

    def sample_multiyear_scenario(
        self,
        start_year: int,
        n_years: int,
        block_len: int = 3
    ) -> Dict[int, Dict[Tuple[str, str, int], float]]:
        """
        Genera escenario multi-año completo usando bootstrap por bloques.

        Args:
            start_year: Año inicial del escenario
            n_years: Número de años consecutivos
            block_len: Longitud de bloques temporales (meses)

        Returns:
            Dict[año, Dict[(i,j,t), caudal]] - Escenario completo multi-año
        """
        multiyear_scenario = {}

        for year_offset in range(n_years):
            current_year = start_year + year_offset
            year_flows = self.sample_year(block_len)
            multiyear_scenario[current_year] = year_flows

        return multiyear_scenario

    def _decompose_year_into_blocks(self, block_len: int) -> List[int]:
        """Descompone 12 meses en bloques de longitud especificada."""
        n_full_blocks = 12 // block_len
        blocks = [block_len] * n_full_blocks

        remainder = 12 - sum(blocks)
        if remainder > 0:
            blocks.append(remainder)

        return blocks

    def _generate_block(
        self,
        pivot_table: pd.DataFrame,
        block_size: int,
        start_month: int,
        I_arc: Dict[Tuple[str, str, int], float],
        arc: Tuple[str, str]
    ) -> int:
        """Genera un bloque de datos para un arco específico."""
        # Seleccionar año y mes de inicio aleatorios
        year = self.rng.choice(pivot_table.index)
        start_m = self.rng.integers(1, 13)

        # Generar secuencia con wrap-around
        month_sequence = [
            (start_m + k - 1) % 12 + 1
            for k in range(block_size)
        ]

        i, j = arc
        current_month = start_month

        for m in month_sequence:
            if current_month > 12:
                break

            # Obtener valor o fallback a mediana histórica
            value = self._get_flow_value(pivot_table, year, m)
            I_arc[(i, j, current_month)] = float(value)
            current_month += 1

        return current_month

    def _get_flow_value(
        self,
        pivot_table: pd.DataFrame,
        year: int,
        month: int
    ) -> float:
        """Obtiene valor de caudal con fallback a mediana histórica."""
        if month not in pivot_table.columns:
            return 0.0

        value = pivot_table.loc[year, month]

        if pd.isna(value):
            # Fallback: mediana histórica del mes
            monthly_data = pivot_table[month]
            value = np.nanmedian(monthly_data.values)
            if pd.isna(value):
                value = 0.0

        return max(0.0, value)


class HybridSimulator:
    """Simulador híbrido que combina Monte Carlo con modelo determinista."""

    def __init__(
        self,
        data_path: Optional[str] = None,
        random_state: int = 42
    ) -> None:
        if data_path is None:
            data_path = INJ_CSV

        self.sampler = BlockBootstrapSampler(data_path, random_state)

    def run_simulation(
        self,
        start_year: int,
        n_years: int,
        V0: float = 1400.0,
        n_scenarios: int = 100,
        block_len: int = 3,
        verbose: bool = True
    ) -> Dict:
        """
        Ejecuta simulación Monte Carlo con arquitectura correcta.

        Genera N escenarios multi-año y optimiza cada uno completo,
        similar al modelo determinista pero con caudales estocásticos.
        """

        if verbose:
            print("=" * 60)
            print(f"📅 Periodo: {start_year}-{start_year + n_years - 1}")
            print(f"💧 V0: {V0:.1f} Hm³")
            print(f"🎲 Escenarios: {n_scenarios}")
            print(f"🧩 Bloques: {block_len} meses")
            print("🎛️  Bootstrap puro - sin ruido estocástico")
            print("=" * 60)
            print("\n🔄 Procesando escenarios...")

        successful_scenarios = []
        failed_scenarios = []
        results_by_year = {}  # Para gráficos históricos

        # Inicializar estructura de resultados
        years = list(range(start_year, start_year + n_years))
        for year in years:
            results_by_year[year] = []

        for scenario_id in range(n_scenarios):
            if verbose:
                # Barra de progreso simple
                progress_pct = (scenario_id + 1) / n_scenarios * 100
                bar_len = 40
                filled = int(bar_len * (scenario_id + 1) / n_scenarios)
                bar = '█' * filled + '░' * (bar_len - filled)
                msg = f"\r[{bar}] {progress_pct:5.1f}% "
                msg += f"({scenario_id + 1}/{n_scenarios})"
                print(msg, end='', flush=True)

            try:
                # Generar escenario multi-año completo
                multiyear_flows = self.sampler.sample_multiyear_scenario(
                    start_year, n_years, block_len
                )

                # Simular escenario multi-año con continuidad
                scenario_results = self._run_multiyear_scenario(
                    multiyear_flows, V0, verbose=False
                )

                # Organizar resultados por año para gráficos
                for year_result in scenario_results:
                    year = year_result["year"]
                    if year in results_by_year:
                        results_by_year[year].append(year_result)

                successful_scenarios.append({
                    "scenario_id": scenario_id + 1,
                    "results": scenario_results,
                    "total_energy": sum(r.get("energy", 0)
                                        for r in scenario_results),
                    "total_toro_usage": sum(r.get("toro_usage", 0)
                                            for r in scenario_results),
                    "final_volume": (scenario_results[-1].get("v_final", V0)
                                     if scenario_results else V0)
                })

            except Exception as e:
                # Suprimir errores individuales durante simulación
                pass
                failed_scenarios.append({
                    "scenario_id": scenario_id + 1,
                    "error": str(e)
                })

        total_scenarios = len(successful_scenarios) + len(failed_scenarios)
        success_rate = (len(successful_scenarios) / total_scenarios * 100
                        if total_scenarios > 0 else 0)

        if verbose:
            print("\n📊 ANÁLISIS FINAL MONTE CARLO:")
            print(f"   🎯 Escenarios totales: {total_scenarios}")
            print(f"   ✅ Escenarios exitosos: {len(successful_scenarios)}")
            print(f"   ❌ Escenarios fallidos: {len(failed_scenarios)}")
            print(f"   📈 Tasa de éxito: {success_rate:.1f}%")

        return {
            "success_rate": success_rate,
            "successful_scenarios": successful_scenarios,
            "failed_scenarios": failed_scenarios,
            "results_by_year": results_by_year,
            "aggregated_kpis": None  # Se calculará en el resumen
        }

    def _run_multiyear_scenario(
        self,
        multiyear_flows: Dict[int, Dict[Tuple[str, str, int], float]],
        V0: float,
        verbose: bool = False
    ) -> List[Dict]:
        """
        Ejecuta un escenario multi-año con continuidad entre años.

        Replica la lógica del modelo determinista con caudales Monte Carlo.
        """
        results = []
        current_V0 = V0

        for year in sorted(multiyear_flows.keys()):
            year_flows = multiyear_flows[year]

            if verbose:
                print(f"   📅 Año {year}: V0={current_V0:.1f} Hm³")

            try:
                model = build_model_for_one_year(
                    target_year=year,
                    V0=current_V0,
                    I_arc_override=year_flows
                )

                # Configurar parámetros para detectar infactibilidad
                model.Params.OutputFlag = 0
                # Ayuda a distinguir INF vs UNBD
                model.Params.DualReductions = 0

                model.optimize()

                # Status codes: 2=OPTIMAL, 3=INFEASIBLE, 4=INF_OR_UNBD
                if model.status == 4:  # Infactible o No acotado
                    # Re-optimizar con DualReductions=0 para determinar cuál
                    model.Params.DualReductions = 0
                    model.optimize()

                    if model.status == 3:  # Ahora sabemos que es INFEASIBLE
                        # Computar IIS para diagnóstico
                        model.computeIIS()
                        raise Exception(
                            f"Modelo infactible en año {year}. "
                            f"V0={current_V0:.1f} Hm³"
                        )
                    else:
                        raise Exception(
                            f"Modelo no acotado en año {year}. "
                            f"Status={model.status}"
                        )

                elif model.status == 3:  # Directamente infactible
                    raise Exception(
                        f"Modelo infactible en año {year}. "
                        f"V0={current_V0:.1f} Hm³"
                    )

                elif model.status == 2:  # Óptimo
                    energy = model.objVal
                    V_vars = model._V
                    final_month = max(T)  # Noviembre (mes 11)
                    v_final = V_vars[final_month].x

                    # Calcular uso del Toro (agua de déficit)
                    x_vars = model._x
                    toro_usage = sum(
                        x_vars["Embalse", "ElToro", t].x
                        for t in T
                    ) * Conv  # Convertir a Hm³

                    # Extraer KPIs del modelo
                    kpis = extract_kpis(model)

                    results.append({
                        "year": year,
                        "energy": energy,
                        "v_final": v_final,
                        "toro_usage": toro_usage,
                        "kpis": kpis,  # Agregar KPIs
                        "status": "OK"
                    })

                    # CONTINUIDAD: V0 del próximo año = V_final de este año
                    # CORRECCIÓN: Limitar V0 a V_max (capacidad física)
                    current_V0 = min(v_final, V_max)

                    if verbose:
                        print(f"      ✅ E: {energy:.1f} MWh, "
                              f"V_f: {v_final:.1f} Hm³, "
                              f"Toro: {toro_usage:.1f} Hm³")
                else:
                    raise Exception(
                        f"Modelo con status inesperado: {model.status}"
                    )

                model.dispose()

            except Exception as e:
                raise Exception(f"Error en año {year}: {e}")

        return results


if __name__ == "__main__":
    from ui_montecarlo import run_monte_carlo
    run_monte_carlo()
