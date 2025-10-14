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
import time
import psutil
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, Tuple, List, Optional

# Importaciones del modelo
from data_loader import CENTRAL_TO_INJ_ARC
from embalse import A_inyeccion
from model import build_model_for_one_year, T, YEARS_HORIZON, Conv
# from kpi import export_kpis_to_csv  # Remoción temporal


def find_data_path() -> str:
    """Encuentra automáticamente la ruta al archivo de datos históricos."""
    possible_paths = [
        "../data/Caudales_historicos_filtrado.csv",
        "data/Caudales_historicos_filtrado.csv",
        (Path(__file__).parent.parent /
         "data" / "Caudales_historicos_filtrado.csv")
    ]

    for path in possible_paths:
        if isinstance(path, Path):
            if path.exists():
                return str(path)
        else:
            if os.path.exists(path):
                return path

    # Buscar hacia arriba hasta encontrar el directorio data/
    current_dir = Path.cwd()
    for parent in [current_dir] + list(current_dir.parents):
        data_file = parent / "data" / "Caudales_historicos_filtrado.csv"
        if data_file.exists():
            return str(data_file)

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
            data_path = find_data_path()

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
            print("🔄 SIMULACIÓN MONTE CARLO HÍBRIDA")
            print("=" * 60)
            print(f"📅 Periodo: {start_year}-{start_year + n_years - 1}")
            print(f"💧 V0: {V0:.1f} Hm³")
            print(f"🎲 Escenarios multi-año: {n_scenarios}")
            print(f"🧩 Bloques: {block_len} meses")
            print("🎛️ Bootstrap puro - sin ruido estocástico")
            print("=" * 60)

        successful_scenarios = []
        failed_scenarios = []
        results_by_year = {}  # Para gráficos históricos

        # Inicializar estructura de resultados
        years = list(range(start_year, start_year + n_years))
        for year in years:
            results_by_year[year] = []

        for scenario_id in range(n_scenarios):
            if verbose:
                print(f"\n🎲 Procesando escenario {scenario_id + 1}/"
                      f"{n_scenarios}")

            try:
                # Generar escenario multi-año completo
                multiyear_flows = self.sampler.sample_multiyear_scenario(
                    start_year, n_years, block_len
                )

                # Simular escenario multi-año con continuidad
                scenario_results = self._run_multiyear_scenario(
                    multiyear_flows, V0, verbose=(scenario_id < 3)
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
                failed_scenarios.append({
                    "scenario_id": scenario_id + 1,
                    "error": str(e)
                })

        total_scenarios = len(successful_scenarios) + len(failed_scenarios)
        success_rate = (len(successful_scenarios) / total_scenarios * 100
                        if total_scenarios > 0 else 0)

        if verbose:
            print("\n📊 ANÁLISIS FINAL MONTE CARLO:")
            print("=" * 50)
            print(f"🎯 Escenarios totales: {total_scenarios}")
            print(f"✅ Escenarios exitosos: {len(successful_scenarios)}")
            print(f"❌ Escenarios fallidos: {len(failed_scenarios)}")
            print(f"📈 Tasa de éxito: {success_rate:.1f}%")

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

                model.Params.OutputFlag = 0
                model.optimize()

                if model.status == 2:  # Óptimo
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

                    results.append({
                        "year": year,
                        "energy": energy,
                        "v_final": v_final,
                        "toro_usage": toro_usage,
                        "status": "OK"
                    })

                    # CONTINUIDAD: V0 del próximo año = V_final de este año
                    current_V0 = v_final

                    if verbose:
                        print(f"      ✅ E: {energy:.1f} MWh, "
                              f"V_f: {v_final:.1f} Hm³, "
                              f"Toro: {toro_usage:.1f} Hm³")
                else:
                    raise Exception(f"Modelo no óptimo: status {model.status}")

                model.dispose()

            except Exception as e:
                raise Exception(f"Error en año {year}: {e}")

        return results


def generate_montecarlo_evolution_plots(
    results_by_year: Dict[int, List[Dict]],
    output_dir: str = "resultados"
) -> List[str]:
    """
    Genera gráficos de evolución histórica para simulaciones Monte Carlo.

    Crea visualizaciones que muestran:
    - Evolución de la cota promedio anual con bandas de confianza
    - Evolución de la tasa de éxito por año
    - Tendencias de generación energética promedio

    Args:
        results_by_year: Dict con años como keys y listas de resultados
                        de simulaciones como values
        output_dir: Directorio donde guardar los gráficos

    Returns:
        List[str]: Lista de rutas de archivos PNG generados
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    files_created = []

    if not results_by_year:
        return files_created

    # Configurar matplotlib para gráficos de calidad
    plt.rcParams['font.size'] = 10
    plt.rcParams['figure.figsize'] = (14, 10)

    # Extraer datos para los gráficos
    years = sorted(results_by_year.keys())
    cotas_promedio = []
    cotas_std = []
    tasas_exito = []
    energia_promedio = []
    energia_std = []
    dependencia_promedio = []
    dependencia_std = []

    for year in years:
        year_results = results_by_year[year]
        successful_results = [r for r in year_results if r["status"] == "OK"]

        if successful_results:
            # Calcular estadísticas del año usando datos reales del Monte Carlo
            volumen_final_year = []
            energias_year = []
            toro_usage_year = []

            for result in successful_results:
                # Usar datos directos del modelo optimizado
                v_final = result.get("v_final", 0)
                energy = result.get("energy", 0)
                toro_usage = result.get("toro_usage", 0)
                
                volumen_final_year.append(v_final)
                energias_year.append(energy)
                toro_usage_year.append(toro_usage)

            # Convertir volúmenes a cotas aproximadas (conversión simplificada)
            # Cota ≈ 1230 + (V / 100)  [relación aproximada del embalse]
            cotas_year = [1230 + (v / 100) for v in volumen_final_year]

            # Estadísticas del año
            if cotas_year:
                cotas_promedio.append(np.mean(cotas_year))
                cotas_std.append(np.std(cotas_year))
            else:
                cotas_promedio.append(1230)  # Cota mínima por defecto
                cotas_std.append(0)

            if energias_year:
                energia_promedio.append(np.mean(energias_year))
                energia_std.append(np.std(energias_year))
            else:
                energia_promedio.append(0)
                energia_std.append(0)

            # Dependencia (uso del Toro en m³/s promedio anual)
            if toro_usage_year:
                # Convertir de Hm³/año a m³/s promedio
                # 1 Hm³/año = 1e6 m³ / (365.25 * 24 * 3600 s) ≈ 31.7 m³/s
                conv_factor = 1e6 / (365.25 * 24 * 3600)
                dependencia_year = [usage * conv_factor
                                    for usage in toro_usage_year]
                dependencia_promedio.append(np.mean(dependencia_year))
                dependencia_std.append(np.std(dependencia_year))
            else:
                dependencia_promedio.append(0)
                dependencia_std.append(0)

            # Tasa de éxito
            tasa_exito = len(successful_results) / len(year_results) * 100
            tasas_exito.append(tasa_exito)
        else:
            cotas_promedio.append(1230)  # Cota mínima por defecto
            cotas_std.append(0)
            energia_promedio.append(0)
            energia_std.append(0)
            dependencia_promedio.append(0)
            dependencia_std.append(0)
            tasas_exito.append(0)

    # Crear figura con 4 subplots
    fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(14, 16))

    # Convertir a arrays para facilitar cálculos
    cotas_promedio = np.array(cotas_promedio)
    cotas_std = np.array(cotas_std)
    energia_promedio = np.array(energia_promedio)
    energia_std = np.array(energia_std)
    dependencia_promedio = np.array(dependencia_promedio)
    dependencia_std = np.array(dependencia_std)

    # Subplot 1: Evolución de cota con bandas de confianza
    ax1.fill_between(years,
                     cotas_promedio - cotas_std,
                     cotas_promedio + cotas_std,
                     alpha=0.3, color='lightblue',
                     label='±1 desviación estándar')
    ax1.plot(years, cotas_promedio, 'b-o', linewidth=2, markersize=4,
             label='Cota promedio')
    ax1.set_title('Evolución Histórica Monte Carlo: Cota del Lago',
                  fontweight='bold', fontsize=12)
    ax1.set_xlabel('Año')
    ax1.set_ylabel('Cota promedio [msnm]')
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    # Subplot 2: Tasa de éxito por año
    ax2.bar(years, tasas_exito, alpha=0.7, color='green',
            label='Tasa de éxito')
    ax2.set_title('Tasa de Éxito por Año - Simulaciones Monte Carlo',
                  fontweight='bold', fontsize=12)
    ax2.set_xlabel('Año')
    ax2.set_ylabel('Tasa de éxito [%]')
    ax2.set_ylim(0, 105)
    ax2.grid(True, alpha=0.3)
    ax2.legend()

    # Subplot 3: Evolución de energía con bandas de confianza
    ax3.fill_between(years,
                     energia_promedio - energia_std,
                     energia_promedio + energia_std,
                     alpha=0.3, color='lightcoral',
                     label='±1 desviación estándar')
    ax3.plot(years, energia_promedio, 'r-o', linewidth=2, markersize=4,
             label='Energía promedio')
    ax3.set_title('Evolución Histórica Monte Carlo: Generación Energética',
                  fontweight='bold', fontsize=12)
    ax3.set_xlabel('Año')
    ax3.set_ylabel('Energía promedio [MWh]')
    ax3.grid(True, alpha=0.3)
    ax3.legend()

    # Subplot 4: Dependencia anual del embalse para cubrir déficits
    ax4.fill_between(years,
                     dependencia_promedio - dependencia_std,
                     dependencia_promedio + dependencia_std,
                     alpha=0.3, color='lightsalmon',
                     label='±1 desviación estándar')
    ax4.bar(years, dependencia_promedio, alpha=0.7, color='coral',
            label='Dependencia promedio')
    ax4.set_title('Dependencia Anual del Embalse para Cubrir Déficits',
                  fontweight='bold', fontsize=12)
    ax4.set_xlabel('Año')
    ax4.set_ylabel('Déficit total anual [m³/s]')
    ax4.grid(True, alpha=0.3)
    ax4.legend()

    plt.tight_layout()

    # Guardar gráfico
    plot_file = output_path / "montecarlo_evolucion_historica.png"
    plt.savefig(plot_file, dpi=300, bbox_inches='tight')
    plt.close()
    files_created.append(str(plot_file))

    return files_created


def get_input(prompt, default=None, input_type=str):
    """Función auxiliar para entrada de usuario."""
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
        except ValueError:
            if input_type == int:
                print("❌ Ingresa un número entero válido")
            elif input_type == float:
                print("❌ Ingresa un número decimal válido")
        except KeyboardInterrupt:
            raise


def validate_year(year):
    """Valida que el año esté en el rango disponible."""
    min_year, max_year = min(YEARS_HORIZON), max(YEARS_HORIZON)
    if year < min_year or year > max_year:
        raise ValueError(f"Año debe estar entre {min_year} y {max_year}")
    return year


def get_performance_stats(start_time: float, process: psutil.Process) -> dict:
    """
    Calcula estadísticas de rendimiento del sistema.
    
    Args:
        start_time: Tiempo de inicio de la ejecución (time.time())
        process: Proceso actual de psutil
        
    Returns:
        dict: Estadísticas de rendimiento incluyendo tiempo y memoria
    """
    execution_time = time.time() - start_time
    
    # Obtener información de memoria
    memory_info = process.memory_info()
    memory_percent = process.memory_percent()
    
    # Información del sistema
    system_memory = psutil.virtual_memory()
    
    return {
        "execution_time_seconds": execution_time,
        "execution_time_formatted": format_time(execution_time),
        "memory_rss_mb": memory_info.rss / (1024 * 1024),  # RSS en MB
        "memory_vms_mb": memory_info.vms / (1024 * 1024),  # VMS en MB
        "memory_percent": memory_percent,
        "system_memory_total_gb": system_memory.total / (1024 * 1024 * 1024),
        "system_memory_available_gb": system_memory.available / (1024 * 1024 * 1024),
        "system_memory_used_percent": system_memory.percent
    }


def format_time(seconds: float) -> str:
    """
    Formatea tiempo en segundos a un formato legible.
    
    Args:
        seconds: Tiempo en segundos
        
    Returns:
        str: Tiempo formateado (ej: "2h 15m 30s" o "45.2s")
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs:.1f}s"


def print_performance_stats(stats: dict, context: str = ""):
    """
    Imprime estadísticas de rendimiento en formato legible.
    
    Args:
        stats: Diccionario con estadísticas de rendimiento
        context: Contexto adicional para el título
    """
    print(f"\n{'=' * 60}")
    print(f"⚡ ESTADÍSTICAS TÉCNICAS DE RENDIMIENTO {context}")
    print(f"{'=' * 60}")
    print(f"🕒 Tiempo de ejecución: {stats['execution_time_formatted']}")
    print("💾 Memoria RAM utilizada:")
    print(f"   • RSS (Resident Set Size): {stats['memory_rss_mb']:.1f} MB")
    print(f"   • VMS (Virtual Memory Size): {stats['memory_vms_mb']:.1f} MB")
    print(f"   • Porcentaje del sistema: {stats['memory_percent']:.2f}%")
    print("🖥️  Memoria del sistema:")
    print(f"   • Total: {stats['system_memory_total_gb']:.1f} GB")
    print(f"   • Disponible: {stats['system_memory_available_gb']:.1f} GB")
    print(f"   • Uso del sistema: {stats['system_memory_used_percent']:.1f}%")
    print(f"{'=' * 60}")


def main():
    """Función principal - interfaz interactiva."""

    try:
        os.system("chcp 65001 > nul 2>&1")
    except Exception:
        pass

    print("=" * 70)
    print(" 🔄 SIMULACIÓN HÍBRIDA: MONTE CARLO + MODELO DETERMINISTA")
    print("=" * 70)
    print("Combina lo mejor de ambos métodos:")
    print("- Monte Carlo: Generación estocástica de escenarios")
    print("- Determinista: Optimización robusta y KPIs consistentes")
    print("=" * 70)

    min_year, max_year = min(YEARS_HORIZON), max(YEARS_HORIZON)
    print(f"\n📊 Datos disponibles: {min_year} - {max_year}")
    print("📅 Periodo hidrológico: Diciembre → Noviembre")
    print("🎯 Bootstrap por bloques estacional")

    try:
        while True:
            try:
                start_year = get_input("\n📅 Año inicial", default=1960,
                                       input_type=int)
                validate_year(start_year)
                break
            except ValueError as e:
                print(f"❌ {e}")

        n_years = get_input("📆 Número de años", default=64, input_type=int)

        end_year = start_year + n_years - 1
        max_available = max(YEARS_HORIZON)
        if end_year > max_available:
            print(f"⚠️ Ajustando periodo final a {max_available}")
            n_years = max_available - start_year + 1

        V0 = get_input(
            "💧 Volumen inicial V0 (Hm³)", default=1400, input_type=float
        )
        n_scenarios = get_input(
            "🎲 Número de escenarios totales", default=100, input_type=int
        )
        block_len = get_input(
            "🧩 Longitud de bloques temporales", default=3, input_type=int
        )

        print("   ✅ Usando bootstrap puro - sin ruido estocástico")

        print("\n🚀 Iniciando simulación híbrida...")

        # Inicializar medición de rendimiento
        start_time = time.time()
        process = psutil.Process()

        simulator = HybridSimulator()
        results = simulator.run_simulation(
            start_year=start_year,
            n_years=n_years,
            V0=V0,
            n_scenarios=n_scenarios,
            block_len=block_len,
            verbose=True
        )

        # RESUMEN DETALLADO ESTILO DETERMINISTA (antes de KPIs)
        if results.get("successful_scenarios"):
            print("\n" + "=" * 60)
            print("📋 RESUMEN DETALLADO MONTE CARLO")
            print("=" * 60)

            successful_scenarios = results["successful_scenarios"]

            # Calcular métricas agregadas
            total_energy_mc = sum(s["total_energy"]
                                  for s in successful_scenarios)
            total_toro_usage_mc = sum(s["total_toro_usage"]
                                      for s in successful_scenarios)
            final_volumes = [s["final_volume"] for s in successful_scenarios]

            n_successful = len(successful_scenarios)

            print(f"🎯 Años por escenario: {n_years}")
            print(f"🎲 Escenarios totales: {n_scenarios}")
            print(f"✅ Escenarios exitosos: {n_successful} "
                  f"({results['success_rate']:.1f}%)")

            avg_total_energy = total_energy_mc / n_successful
            avg_total_toro = total_toro_usage_mc / n_successful
            print(f"⚡ Energía total promedio: {avg_total_energy:,.1f} MWh")
            print(f"🌊 Uso promedio El Toro: {avg_total_toro:,.1f} Hm³")

            if n_successful > 0:
                avg_energy_per_year = total_energy_mc / n_successful / n_years
                avg_toro_per_year = (total_toro_usage_mc /
                                     n_successful / n_years)
                print(f"📊 Energía promedio: "
                      f"{avg_energy_per_year:,.1f} MWh/año")
                print(f"📊 Uso promedio El Toro: "
                      f"{avg_toro_per_year:,.1f} Hm³/año")

                # Balance volumétrico Monte Carlo
                if final_volumes:
                    v_initial_mc = V0
                    v_final_mc = sum(final_volumes) / len(final_volumes)
                    volume_change_mc = v_final_mc - v_initial_mc
                    change_sign_mc = "📈" if volume_change_mc >= 0 else "📉"

                    print("\n💧 BALANCE VOLUMÉTRICO MONTE CARLO:")
                    print(f"   Inicial: {v_initial_mc:,.1f} Hm³")
                    print(f"   Final (promedio): {v_final_mc:,.1f} Hm³")
                    print(f"   {change_sign_mc} Cambio promedio: "
                          f"{volume_change_mc:+,.1f} Hm³")

                    # Estadísticas adicionales Monte Carlo
                    vol_std = (np.std(final_volumes)
                               if len(final_volumes) > 1 else 0)
                    vol_min = min(final_volumes) if final_volumes else 0
                    vol_max = max(final_volumes) if final_volumes else 0

                    print("\n📊 ESTADÍSTICAS VOLUMÉTRICAS:")
                    print(f"   Desviación estándar: {vol_std:,.1f} Hm³")
                    print(f"   Rango: [{vol_min:,.1f}, {vol_max:,.1f}] Hm³")

        # Generar gráficos de evolución histórica si hay múltiples años
        if n_years > 1 and results.get("results_by_year"):
            try:
                print("\n📊 Generando gráficos de evolución histórica...")
                plot_files = generate_montecarlo_evolution_plots(
                    results["results_by_year"],
                    output_dir="resultados"
                )
                print(f"📊 Gráficos generados: "
                      f"{len(plot_files)} archivos PNG")
                for plot_file in plot_files:
                    print(f"   📈 {plot_file}")
            except Exception as e:
                print(f"   ⚠️ Error generando gráficos: {e}")

        # Exportar resultados si hay datos exitosos
        if results.get("successful_scenarios"):
            try:
                # Crear CSV con resumen de escenarios
                import pandas as pd

                scenarios_data = []
                for scenario in results["successful_scenarios"]:
                    scenarios_data.append({
                        "scenario_id": scenario["scenario_id"],
                        "total_energy_MWh": scenario["total_energy"],
                        "total_toro_usage_Hm3": scenario["total_toro_usage"],
                        "final_volume_Hm3": scenario["final_volume"]
                    })

                df_scenarios = pd.DataFrame(scenarios_data)
                output_file = (f"resultados/montecarlo_scenarios_"
                               f"{start_year}-{start_year + n_years - 1}.csv")

                from pathlib import Path
                Path("resultados").mkdir(exist_ok=True)
                df_scenarios.to_csv(output_file, index=False)

                print(f"\n📁 Resultados exportados: {output_file}")

            except Exception as e:
                print(f"   ⚠️ Error exportando: {e}")

        print("\n💡 VENTAJAS DEL MÉTODO HÍBRIDO:")
        print("   ✅ Variabilidad estocástica de Monte Carlo")
        print("   ✅ Optimización robusta del modelo determinista")
        print("   ✅ KPIs consistentes con análisis histórico")
        print(f"   ✅ Alta tasa de éxito: {results['success_rate']:.1f}%")
        print("   ✅ Resultados comparables y reproducibles")

        # Imprimir estadísticas de rendimiento
        performance_stats = get_performance_stats(start_time, process)
        print_performance_stats(performance_stats, "(Monte Carlo)")

    except KeyboardInterrupt:
        print("\n\n👋 Saliendo del programa...")
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
