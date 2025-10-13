"""
SIMULACIÓN MONTE CARLO - Embalse del Laja
==========================================

Simulación estocástica unificada con bootstrap por bloques estacional
para optimización bajo incertidumbre del Embalse del Laja.

Incluye:
- Bootstrap por bloques para preservar correlaciones temporales
- Análisis Monte Carlo single-year y multi-year
- Interface interactiva para ejecución directa
- Análisis estadístico y de riesgo

Uso: python src/montecarlo.py
"""
from __future__ import annotations

import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, Tuple, List, Optional
from dataclasses import dataclass

# Importaciones del modelo
from data_loader import CENTRAL_TO_INJ_ARC
from embalse import A_inyeccion
from model import build_model_for_one_year, T, YEARS_HORIZON, Conv
from filt_cota import cota_from_volumen
# KPIs
from kpi import (extract_kpis_montecarlo, print_kpis_montecarlo,
                 export_kpis_to_csv)

try:
    from kpi import extract_kpis
except ImportError:
    # Fallback simple si no existe sensitivity.py
    def extract_kpis(model):
        """Extractor básico de KPIs."""
        if hasattr(model, 'status'):
            return {
                'status': model.status,
                'obj_MWh': model.objVal if hasattr(model, 'objVal') else None,
                'V_end': max(model._V[t].x for t in T) if hasattr(
                    model, '_V') else None
            }
        return {'status': -1, 'obj_MWh': None, 'V_end': None}


def find_data_path() -> str:
    """
    Encuentra automáticamente la ruta al archivo de datos históricos.
    
    Returns:
        Ruta válida al archivo Caudales_historicos_filtrado.csv
    """
    # Posibles ubicaciones del archivo
    possible_paths = [
        # Desde src/ (cuando se ejecuta montecarlo.py desde src/)
        "../data/Caudales_historicos_filtrado.csv",
        # Desde raíz del proyecto (cuando se ejecuta desde la raíz)
        "data/Caudales_historicos_filtrado.csv",
        # Ruta absoluta basada en la ubicación del script
        Path(__file__).parent.parent / "data" / "Caudales_historicos_filtrado.csv"
    ]
    
    for path in possible_paths:
        if isinstance(path, Path):
            if path.exists():
                return str(path)
        else:
            if os.path.exists(path):
                return path
    
    # Si no encuentra nada, probar desde el directorio actual
    current_dir = Path.cwd()
    
    # Buscar hacia arriba hasta encontrar el directorio data/
    for parent in [current_dir] + list(current_dir.parents):
        data_file = parent / "data" / "Caudales_historicos_filtrado.csv"
        if data_file.exists():
            return str(data_file)
    
    # Fallback: usar la ruta relativa original
    return "../data/Caudales_historicos_filtrado.csv"


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

    def sample_with_noise(
        self,
        block_len: int = 3,
        sigma: float = 0.1
    ) -> Dict[Tuple[str, str, int], float]:
        """
        Genera escenario con variabilidad lognormal adicional.

        Args:
            block_len: Longitud de bloques temporales
            sigma: Desviación estándar del ruido lognormal

        Returns:
            Escenario con ruido multiplicativo aplicado
        """
        base_scenario = self.sample_year(block_len)

        noisy_scenario = {}
        for key, flow in base_scenario.items():
            if flow > 0:
                noise_factor = self.rng.lognormal(mean=0.0, sigma=sigma)
                noisy_scenario[key] = float(flow * noise_factor)
            else:
                noisy_scenario[key] = 0.0

        return noisy_scenario

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


# =============================
# CLASES DE DATOS MONTE CARLO
# =============================

@dataclass
class SimulationResult:
    """Resultado de una simulación Monte Carlo."""
    iteration: int
    year: int
    status: int
    energy_mwh: Optional[float]
    final_volume: Optional[float]
    toro_usage: Optional[float] = None  # Uso del Toro en Hm³
    error: Optional[str] = None

    @property
    def is_optimal(self) -> bool:
        """Verifica si la iteración fue óptima."""
        return self.status == 2  # GRB.OPTIMAL

    @property
    def is_feasible(self) -> bool:
        """Verifica si la iteración fue factible."""
        return self.status in [2, 3]  # OPTIMAL o SUBOPTIMAL


@dataclass
class SimulationSummary:
    """Resumen estadístico de simulación Monte Carlo."""
    total_iterations: int
    feasible_count: int
    optimal_count: int
    mean_energy: float
    std_energy: float
    min_energy: float
    max_energy: float
    feasibility_rate: float
    mean_toro_usage: float = 0.0
    mean_volume: float = 0.0
    mean_cota: float = 0.0
    max_deficit: float = 0.0
    mean_deficit: float = 0.0
    years_with_deficit: int = 0

    def __str__(self) -> str:
        return (
            f"📊 Resumen Monte Carlo:\n"
            f"   Iteraciones: {self.total_iterations}\n"
            f"   Factibilidad: {self.feasibility_rate:.1%}\n"
            f"   Energía promedio: {self.mean_energy:.1f} MWh\n"
            f"   Desviación estándar: {self.std_energy:.1f} MWh\n"
            f"   Uso promedio El Toro: {self.mean_toro_usage:.1f} Hm³\n"
            f"   Cota promedio: {self.mean_cota:.1f} msnm"
        )


# =============================
# SIMULADOR MONTE CARLO
# =============================

class MonteCarloSimulator:
    """
    Simulador Monte Carlo unificado para análisis estocástico del embalse.

    Responsabilidades:
    - Ejecutar simulaciones single-year y multi-year
    - Manejar escenarios estocásticos con bootstrap
    - Generar análisis estadísticos y de riesgo
    """

    def __init__(
        self,
        data_path: Optional[str] = None,
        random_state: int = 42
    ) -> None:
        """
        Inicializa el simulador Monte Carlo.

        Args:
            data_path: Ruta a datos históricos de caudales (None=autodetectar)
            random_state: Semilla para reproducibilidad
        """
        if data_path is None:
            data_path = find_data_path()
        
        self.sampler = BlockBootstrapSampler(data_path, random_state)
        self.random_state = random_state

    def run_single_year(
        self,
        target_year: int,
        V0: float,
        n_iterations: int = 100,
        block_len: int = 3,
        noise_sigma: float = 0.1,
        verbose: bool = True
    ) -> Tuple[List[SimulationResult], SimulationSummary]:
        """
        Ejecuta simulación Monte Carlo para un año específico.

        Args:
            target_year: Año objetivo de simulación
            V0: Volumen inicial en Hm³
            n_iterations: Número de iteraciones Monte Carlo
            block_len: Longitud de bloques para bootstrap
            noise_sigma: Desviación estándar del ruido lognormal
            verbose: Mostrar progreso en consola

        Returns:
            Tupla con (resultados_detallados, resumen_estadístico)
        """
        if verbose:
            print(f"🎲 Monte Carlo | Año: {target_year} | "
                  f"V0: {V0:.1f} Hm³ | Iteraciones: {n_iterations}")

        results = []

        for i in range(1, n_iterations + 1):
            if verbose and i % 20 == 0:
                print(f"   Progreso: {i}/{n_iterations}")

            result = self._run_single_iteration(
                target_year, V0, i, block_len, noise_sigma
            )
            results.append(result)

        summary = self._compute_summary(results)

        if verbose:
            print(f"\n{summary}")

        return results, summary

    def run_multi_year(
        self,
        start_year: int,
        n_years: int,
        V0: float,
        n_iterations: int = 50,
        block_len: int = 3,
        noise_sigma: float = 0.1,
        verbose: bool = True
    ) -> List[List[SimulationResult]]:
        """
        Ejecuta simulación Monte Carlo multi-año con volúmenes recursivos.

        Args:
            start_year: Año inicial
            n_years: Número de años a simular
            V0: Volumen inicial en Hm³
            n_iterations: Número de trayectorias Monte Carlo
            block_len: Longitud de bloques para bootstrap
            noise_sigma: Desviación estándar del ruido
            verbose: Mostrar progreso en consola

        Returns:
            Lista de trayectorias, cada una con resultados anuales
        """
        if verbose:
            print(f"🎲 Monte Carlo Multi-Año | "
                  f"{start_year}-{start_year + n_years - 1} | "
                  f"Trayectorias: {n_iterations}")

        trajectories = []

        for iteration in range(1, n_iterations + 1):
            if verbose:
                print(f"\n🎯 Trayectoria {iteration}/{n_iterations}:")

            trajectory = self._run_multi_year_trajectory(
                start_year, n_years, V0, iteration,
                block_len, noise_sigma, verbose
            )
            trajectories.append(trajectory)

        if verbose:
            self._print_multi_year_summary(trajectories, n_years)

        return trajectories

    def _run_single_iteration(
        self,
        target_year: int,
        V0: float,
        iteration: int,
        block_len: int,
        noise_sigma: float
    ) -> SimulationResult:
        """Ejecuta una iteración individual de simulación."""
        try:
            # Generar escenario estocástico
            scenario = self.sampler.sample_with_noise(block_len, noise_sigma)

            # Construir y optimizar modelo
            model = build_model_for_one_year(
                target_year=target_year,
                V0=V0,
                I_arc_override=scenario
            )

            # Silenciar salida de Gurobi
            model.Params.OutputFlag = 0
            model.optimize()

            # Extraer KPIs
            kpis = extract_kpis(model)

            # Calcular uso del Toro
            toro_usage = 0.0
            if hasattr(model, '_x'):
                x_vars = model._x
                toro_usage = sum(
                    x_vars["Embalse", "ElToro", t].x
                    for t in T
                ) * Conv  # Convertir a Hm³

            result = SimulationResult(
                iteration=iteration,
                year=target_year,
                status=kpis['status'],
                energy_mwh=kpis.get('obj_MWh'),
                final_volume=kpis.get('V_end'),
                toro_usage=toro_usage
            )

            model.dispose()
            return result

        except Exception as e:
            return SimulationResult(
                iteration=iteration,
                year=target_year,
                status=-1,
                energy_mwh=None,
                final_volume=None,
                toro_usage=0.0,
                error=str(e)
            )

    def _run_multi_year_trajectory(
        self,
        start_year: int,
        n_years: int,
        initial_V0: float,
        iteration: int,
        block_len: int,
        noise_sigma: float,
        verbose: bool
    ) -> List[SimulationResult]:
        """Ejecuta una trayectoria multi-año completa."""
        trajectory = []
        current_V0 = initial_V0

        for year_offset in range(n_years):
            current_year = start_year + year_offset

            result = self._run_single_iteration(
                current_year, current_V0, iteration, block_len, noise_sigma
            )

            if verbose:
                status_emoji = "✅" if result.is_optimal else "❌"
                energy_str = (f"{result.energy_mwh:.0f} MWh"
                              if result.energy_mwh else "N/A")
                print(f"   {current_year}: {status_emoji} {energy_str}")

            trajectory.append(result)

            # Actualizar V0 para siguiente año
            if result.final_volume is not None:
                current_V0 = result.final_volume
            # Si falla, mantener volumen actual

        return trajectory

    def _compute_summary(self,
                         results: List[SimulationResult]) -> SimulationSummary:
        """Computa resumen estadístico de resultados."""
        total = len(results)
        feasible_results = [r for r in results if r.is_feasible]
        optimal_results = [r for r in results if r.is_optimal]

        feasible_count = len(feasible_results)
        optimal_count = len(optimal_results)

        # Métricas de energía
        if optimal_results:
            energies = [
                r.energy_mwh
                for r in optimal_results
                if r.energy_mwh
            ]
            mean_energy = np.mean(energies) if energies else 0.0
            std_energy = np.std(energies) if len(energies) > 1 else 0.0
            min_energy = np.min(energies) if energies else 0.0
            max_energy = np.max(energies) if energies else 0.0
        else:
            mean_energy = std_energy = min_energy = max_energy = 0.0

        # Métricas del Toro
        toro_usages = [r.toro_usage for r in optimal_results
                       if r.toro_usage is not None]
        mean_toro_usage = np.mean(toro_usages) if toro_usages else 0.0

        # Métricas de volumen y cota
        volumes = [r.final_volume for r in optimal_results
                   if r.final_volume is not None]
        mean_volume = np.mean(volumes) if volumes else 0.0
        mean_cota = cota_from_volumen(mean_volume) if mean_volume > 0 else 0.0

        # Métricas de déficits (usando El Toro como proxy)
        if toro_usages:
            # Convertir de Hm³/año a m³/s promedio
            toro_annual_m3s = [usage / (12 * Conv) for usage in toro_usages]
            non_zero_usage = [u for u in toro_annual_m3s if u > 0.1]

            max_deficit = max(non_zero_usage) if non_zero_usage else 0.0
            mean_deficit = (np.mean(non_zero_usage) if non_zero_usage
                            else 0.0)
            years_with_deficit = len(non_zero_usage)
        else:
            max_deficit = mean_deficit = 0.0
            years_with_deficit = 0

        return SimulationSummary(
            total_iterations=total,
            feasible_count=feasible_count,
            optimal_count=optimal_count,
            mean_energy=mean_energy,
            std_energy=std_energy,
            min_energy=min_energy,
            max_energy=max_energy,
            feasibility_rate=feasible_count / total if total > 0 else 0.0,
            mean_toro_usage=mean_toro_usage,
            mean_volume=mean_volume,
            mean_cota=mean_cota,
            max_deficit=max_deficit,
            mean_deficit=mean_deficit,
            years_with_deficit=years_with_deficit
        )

    def _print_multi_year_summary(
        self,
        trajectories: List[List[SimulationResult]],
        n_years: int
    ) -> None:
        """Imprime resumen de simulación multi-año."""
        print("\n📊 Resumen Multi-Año:")

        # Calcular energías totales por trayectoria
        total_energies = []
        successful_trajectories = 0

        for trajectory in trajectories:
            trajectory_energy = sum(
                r.energy_mwh for r in trajectory
                if r.energy_mwh is not None
            )
            if trajectory_energy > 0:
                total_energies.append(trajectory_energy)
                successful_trajectories += 1

        if total_energies:
            print(f"   ✅ Trayectorias exitosas: "
                  f"{successful_trajectories}/{len(trajectories)}")
            print(f"   ⚡ Energía total promedio: "
                  f"{np.mean(total_energies):.0f} MWh")
            print(f"   📊 Desviación estándar: "
                  f"{np.std(total_energies):.0f} MWh")
            print(f"   📈 Rango: [{np.min(total_energies):.0f}, "
                  f"{np.max(total_energies):.0f}] MWh")


# =============================
# INTERFAZ INTERACTIVA PRINCIPAL
# =============================

if __name__ == "__main__":
    """
    Interfaz interactiva para simulación Monte Carlo.
    Uso: python src/montecarlo.py
    """
    
    # Configurar codificación para Windows
    try:
        # Configurar terminal para UTF-8 en Windows
        os.system('chcp 65001 > nul 2>&1')
    except Exception:
        pass

    def print_monte_carlo_menu():
        print("=" * 60)
        print(" 🎲 SIMULACIÓN MONTE CARLO - Embalse del Laja")
        print("=" * 60)
        min_year, max_year = min(YEARS_HORIZON), max(YEARS_HORIZON)
        print(f"\n📊 Datos disponibles: {min_year} - {max_year}")
        print("📅 Período hidrológico: Diciembre → Noviembre")
        print("🎯 Bootstrap por bloques estacional con ruido lognormal")
        print("\n🎲 Opciones de Simulación:")
        print("1️⃣  Simulación año específico (Monte Carlo single-year)")
        print("2️⃣  Simulación multi-año (trayectorias recursivas)")
        print("0️⃣  Salir")
        print("-" * 64)

    def get_input(prompt, default=None, input_type=str):
        while True:
            try:
                if default is not None:
                    value = input(f"{prompt} [{default}]: ").strip()
                    if not value:
                        return default
                else:
                    value = input(f"{prompt}: ").strip()

                if input_type == int:
                    return int(value)
                elif input_type == float:
                    return float(value)
                return value
            except (ValueError, KeyboardInterrupt):
                if input_type == int:
                    print("❌ Ingresa un número entero válido")
                elif input_type == float:
                    print("❌ Ingresa un número decimal válido")
                else:
                    return ""  # Retornar string vacío para salir del bucle

    def validate_year(year):
        """Valida que el año esté en el rango disponible."""
        min_year, max_year = min(YEARS_HORIZON), max(YEARS_HORIZON)
        if year < min_year or year > max_year:
            raise ValueError(f"Año debe estar entre {min_year} y {max_year}")
        return year

    def run_single_year_simulation():
        """Ejecuta simulación Monte Carlo para un año específico."""
        print("\n🎲 SIMULACIÓN MONTE CARLO - AÑO ESPECÍFICO")
        print("=" * 60)

        # Parámetros de entrada
        while True:
            try:
                year = get_input("📅 Año objetivo", input_type=int)
                validate_year(year)
                break
            except ValueError as e:
                print(f"❌ {e}")

        V0 = get_input("💧 Volumen inicial V0 (Hm³)",
                       default=1400.0, input_type=float)
        n_iter = get_input("🔢 Número de iteraciones",
                           default=100, input_type=int)
        block_len = get_input("🧩 Longitud de bloques temporales",
                              default=3, input_type=int)
        noise = get_input("🎛️ Ruido lognormal (sigma)",
                          default=0.1, input_type=float)

        print("\n🚀 Iniciando simulación Monte Carlo...")
        print(f"📅 Año: {year} (período hidrológico Dic{year-1}→Nov{year})")
        print(f"💧 V0: {V0:.1f} Hm³")
        print(f"🎲 Iteraciones: {n_iter}")
        print(f"🧩 Bloques: {block_len} meses")
        print(f"🎛️ Ruido: σ={noise:.2f}")
        print("=" * 60)

        # Ejecutar simulación
        try:
            simulator = MonteCarloSimulator()
            results, summary = simulator.run_single_year(
                target_year=year,
                V0=V0,
                n_iterations=n_iter,
                block_len=block_len,
                noise_sigma=noise,
                verbose=True
            )

            # KPIs DETALLADOS MONTE CARLO
            print("\nRe-ejecutando muestra para KPIs detallados...")

            # Re-ejecutar modelos para muestra representativa (para eficiencia)
            sample_size = min(20, n_iter // 5)  # Máximo 20 modelos
            sample_models = []

            for i in range(sample_size):
                try:
                    # Generar escenario
                    scenario = simulator.sampler.sample_with_noise(
                        block_len, noise
                    )

                    # Construir modelo
                    model = build_model_for_one_year(
                        target_year=year,
                        V0=V0,
                        I_arc_override=scenario
                    )

                    model.Params.OutputFlag = 0
                    model.optimize()

                    if model.status == 2:  # Óptimo
                        sample_models.append(model)

                except Exception as e:
                    print(f"   ⚠️ Error en muestra {i+1}: {e}")

            # Calcular y mostrar KPIs Monte Carlo
            if sample_models:
                print(
                    f"\n KPIs MONTE CARLO "
                    f"(muestra de {len(sample_models)} modelos):"
                )

                kpis_mc = extract_kpis_montecarlo(
                    sample_models,
                    detailed_output=True
                )
                print_kpis_montecarlo(kpis_mc, year)

                # Exportar resultados
                try:
                    export_files = export_kpis_to_csv(
                        kpis_mc,
                        prefix=f"mc_year_{year}"
                    )
                    print(
                        f"\n📁 Resultados Monte Carlo exportados: "
                        f"{len(export_files)} archivos CSV"
                    )
                except Exception as e:
                    print(f"   ⚠️ Error exportando: {e}")

                # Limpiar memoria
                for model in sample_models:
                    model.dispose()
            else:
                print("\n⚠️ No se pudieron calcular KPIs detallados")
                print("Monte Carlo")

            # Análisis de riesgo agregado  
            print("\n🎯 ANÁLISIS DE RIESGO:")
            optimal_results = [r for r in results if r.is_optimal]
            success_rate = len(optimal_results) / len(results) * 100
            print(f"   Tasa de éxito: {success_rate:.1f}%")
            feasible_count = len([r for r in results if r.is_feasible])
            failed_count = len([r for r in results if not r.is_feasible])
            print(f"   Escenarios factibles: {feasible_count}")
            print(f"   Escenarios fallidos: {failed_count}")

            # Estadísticas básicas de energía
            if optimal_results:
                energies = [
                    r.energy_mwh
                    for r in optimal_results
                    if r.energy_mwh
                ]
                if energies:
                    print(f"   Energía promedio: {np.mean(energies):,.1f} MWh")
                    print(f"   Energía rango: [{np.min(energies):,.1f}, {np.max(energies):,.1f}] MWh")

        except Exception as e:
            print(f"❌ Error en simulación: {e}")

    def run_multi_year_simulation():
        """Ejecuta simulación Monte Carlo multi-año."""
        print("\n🎲 SIMULACIÓN MONTE CARLO - MULTI-AÑO")
        print("=" * 60)

        # Parámetros de entrada
        while True:
            try:
                start_year = get_input("📅 Año inicial", input_type=int)
                validate_year(start_year)
                break
            except ValueError as e:
                print(f"❌ {e}")

        n_years = get_input("📆 Número de años", default=5, input_type=int)

        # Validar que el rango esté disponible
        end_year = start_year + n_years - 1
        max_available = max(YEARS_HORIZON)
        if end_year > max_available:
            print(f"⚠️ Ajustando período final a {max_available}")
            n_years = max_available - start_year + 1
            end_year = max_available

        V0 = get_input("💧 Volumen inicial V0 (Hm³)",
                       default=2500, input_type=float)
        n_traj = get_input("🔢 Número de trayectorias",
                           default=50, input_type=int)
        block_len = get_input("🧩 Longitud de bloques temporales",
                              default=3, input_type=int)
        noise = get_input("🎛️ Ruido lognormal (sigma)",
                          default=0.1, input_type=float)

        print("\n🚀 Iniciando simulación multi-año...")
        print(f"📅 Período: {start_year}-{end_year} ({n_years} años)")
        print(f"💧 V0: {V0:.1f} Hm³")
        print(f"🎲 Trayectorias: {n_traj}")
        print(f"🧩 Bloques: {block_len} meses")
        print(f"🎛️ Ruido: σ={noise:.2f}")
        print("=" * 60)

        # Ejecutar simulación
        try:
            simulator = MonteCarloSimulator()
            trajectories = simulator.run_multi_year(
                start_year=start_year,
                n_years=n_years,
                V0=V0,
                n_iterations=n_traj,
                block_len=block_len,
                noise_sigma=noise,
                verbose=True
            )

            # Análisis de trayectorias
            print("\n📊 ANÁLISIS DE TRAYECTORIAS:")
            print("=" * 60)

            # Estadísticas por año
            year_stats = {}
            for year_idx in range(n_years):
                year = start_year + year_idx
                year_results = [traj[year_idx] for traj in trajectories
                                if year_idx < len(traj)]

                energies = [r.energy_mwh for r in year_results
                            if r.energy_mwh is not None]
                optimal_count = len([r for r in year_results
                                    if r.is_optimal])
                success_rate = optimal_count / len(year_results) * 100
                
                year_stats[year] = {
                    'success_rate': success_rate,
                    'mean_energy': np.mean(energies) if energies else 0,
                    'total_scenarios': len(year_results)
                }

            print("Año    | Éxito (%) | Energía Prom. | Escenarios")
            print("-" * 50)
            for year, stats in year_stats.items():
                success_pct = stats['success_rate']
                mean_energy = stats['mean_energy']
                total_scen = stats['total_scenarios']
                print(f"{year}   | {success_pct:5.1f}%   | "
                      f"{mean_energy:8,.0f} MWh | {total_scen:3d}")

            # Resumen agregado multi-año (formato compatible con model.py)
            all_results = [result for traj in trajectories
                          for result in traj]
            successful_results = [r for r in all_results if r.is_optimal]

            if successful_results:
                # Energía total
                total_energy = sum(
                    r.energy_mwh for r in successful_results
                    if r.energy_mwh
                )
                # Uso total del Toro
                total_toro = sum(
                    r.toro_usage for r in successful_results
                    if r.toro_usage
                )

                print(f"\n📋 RESUMEN MULTI-AÑO ({start_year}-{end_year}):")
                print("=" * 64)
                print(f"🎯 Años procesados: {n_years}")
                print(f"✅ Trayectorias exitosas: {len(trajectories)}")
                print(f"⚡ Energía total promedio: {total_energy:,.1f} MWh")
                print(f"🌊 Uso total El Toro: {total_toro:,.1f} Hm³")

                # Promedios
                avg_energy = total_energy / len(successful_results)
                avg_toro = total_toro / len(successful_results)
                print(f"📊 Energía promedio: {avg_energy:,.1f} MWh/año")
                print(f"📊 Uso promedio El Toro: {avg_toro:,.1f} Hm³/año")

                # KPIs DETALLADOS MULTI-AÑO
                print("\n🔄 Calculando KPIs detallados multi-año...")

                # Generar muestra representativa de modelos
                sample_models = []
                sample_size = min(15, len(trajectories))  # Máximo 15

                for traj_idx in range(sample_size):
                    if traj_idx < len(trajectories):
                        trajectory = trajectories[traj_idx]

                        # Tomar el primer año exitoso de cada 
                        # trayectoria para muestra
                        for result in trajectory:
                            if result.is_optimal:
                                try:
                                    # Re-ejecutar modelo para ese año
                                    # específico
                                    scenario = simulator.sampler.sample_with_noise(
                                        block_len, noise)

                                    model = build_model_for_one_year(
                                        target_year=result.year,
                                        V0=V0,  # para consistencia
                                        I_arc_override=scenario
                                    )

                                    model.Params.OutputFlag = 0
                                    model.optimize()

                                    if model.status == 2:
                                        sample_models.append(model)
                                        break  # Solo un modelo por trayectoria

                                except Exception:
                                    continue

                # Análisis KPIs multi-año
                if sample_models:
                    print(
                        f"\n📊 KPIs MULTI-AÑO (muestra de "
                        f"{len(sample_models)} modelos):"
                    )

                    kpis_multi = extract_kpis_montecarlo(
                        sample_models,
                        detailed_output=True
                    )
                    print_kpis_montecarlo(kpis_multi)

                    # Exportar resultados multi-año
                    try:
                        export_files = export_kpis_to_csv(
                            kpis_multi,
                            prefix=f"mc_multiyear_{start_year}-{end_year}"
                        )
                        print(f"\n� KPIs multi-año exportados: {len(export_files)} archivos CSV")
                    except Exception as e:
                        print(f"   ⚠️ Error exportando multi-año: {e}")
                    
                    # Limpiar memoria
                    for model in sample_models:
                        model.dispose()
                else:
                    print("\n⚠️ No se pudieron calcular KPIs detallados multi-año")

        except Exception as e:
            print(f"❌ Error en simulación multi-año: {e}")


# Bucle principal
    while True:
        try:
            print_monte_carlo_menu()
            
            choice = get_input("\nSelecciona una opción", input_type=int)
            
            if choice == 0:
                print("👋 ¡Hasta luego!")
                break
            elif choice == 1:
                run_single_year_simulation()
            elif choice == 2:
                run_multi_year_simulation()
            else:
                print("❌ Opción inválida. Selecciona 0, 1 o 2.")
            
            # Pausa antes de volver al menú
            input("\n⏸️  Presiona Enter para continuar...")
            print("\n")
            
        except KeyboardInterrupt:
            print("\n\n👋 Saliendo del programa...")
            break
        except Exception as e:
            print(f"❌ Error inesperado: {e}")
    
    sys.exit(0)
