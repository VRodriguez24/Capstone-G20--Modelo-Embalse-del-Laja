"""
Interfaz unificada de ejecución para simulación Monte Carlo del Embalse del
Laja.

Este módulo centraliza la lógica de ejecución, menús interactivos y análisis
de resultados para la simulación híbrida Monte Carlo + Modelo Determinista.

Uso típico:
    from run_montecarlo import run_monte_carlo
    from montecarlo import HybridSimulator

    if __name__ == "__main__":
        run_monte_carlo()
"""

import time
import psutil
import numpy as np
from pathlib import Path
from typing import Dict, List

from ui_helpers import (
    get_input,
    get_performance_stats,
    print_performance_stats,
    validate_year,
    configure_console
)
from kpi import aggregate_kpis, print_kpis
from model import YEARS_HORIZON


def print_monte_carlo_summary(
    results: Dict,
    n_years: int,
    n_scenarios: int,
    V0: float
) -> None:
    """
    Imprime resumen detallado de resultados Monte Carlo.

    Args:
        results: Diccionario con resultados de la simulación
        n_years: Número de años simulados por escenario
        n_scenarios: Número total de escenarios
        V0: Volumen inicial
    """
    if not results.get("successful_scenarios"):
        print("\n⚠️ No hay escenarios exitosos para resumir")
        return

    print("\n" + "=" * 60)
    print("📋 RESUMEN DETALLADO MONTE CARLO")
    print("=" * 60)

    successful_scenarios = results["successful_scenarios"]
    n_successful = len(successful_scenarios)

    # Calcular métricas agregadas
    total_energy_mc = sum(s["total_energy"] for s in successful_scenarios)
    total_toro_usage_mc = sum(
        s["total_toro_usage"] for s in successful_scenarios
    )
    final_volumes = [s["final_volume"] for s in successful_scenarios]

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
        avg_toro_per_year = total_toro_usage_mc / n_successful / n_years
        print(f"📊 Energía promedio: {avg_energy_per_year:,.1f} MWh/año")
        print(f"📊 Uso promedio El Toro: {avg_toro_per_year:,.1f} Hm³/año")

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
            vol_std = np.std(final_volumes) if len(final_volumes) > 1 else 0
            vol_min = min(final_volumes) if final_volumes else 0
            vol_max = max(final_volumes) if final_volumes else 0

            print("\n📊 ESTADÍSTICAS VOLUMÉTRICAS:")
            print(f"   Desviación estándar: {vol_std:,.1f} Hm³")
            print(f"   Rango: [{vol_min:,.1f}, {vol_max:,.1f}] Hm³")


def print_monte_carlo_kpis(results: Dict) -> None:
    """
    Imprime KPIs agregados de la simulación Monte Carlo en consola.

    Args:
        results: Diccionario con resultados de la simulación
    """
    if not results.get("successful_scenarios"):
        return

    successful_scenarios = results["successful_scenarios"]

    # Recolectar todos los KPIs de todos los escenarios
    all_kpis = []
    for scenario in successful_scenarios:
        for year_result in scenario["results"]:
            if "kpis" in year_result and year_result["kpis"]:
                all_kpis.append(year_result["kpis"])

    if all_kpis:
        # Agregar KPIs usando la función del módulo kpi
        kpis_agregados = aggregate_kpis(all_kpis)

        # Mostrar KPIs agregados en consola (sin exportar)
        print_kpis(kpis_agregados, "Monte Carlo")
    else:
        print("⚠️ No se pudieron calcular KPIs para los escenarios exitosos")


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
    import matplotlib.pyplot as plt

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
            # Calcular estadísticas del año usando datos reales del Monte
            # Carlo
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

            # Convertir volúmenes a cotas aproximadas
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
                # 1 Hm³/año = 1e6 m³/(365.25*24*3600 s) ≈ 31.7 m³/s
                conv_factor = 1e6 / (365.25 * 24 * 3600)
                dependencia_year = [
                    usage * conv_factor for usage in toro_usage_year
                ]
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
    ax1.fill_between(
        years,
        cotas_promedio - cotas_std,
        cotas_promedio + cotas_std,
        alpha=0.3,
        color='lightblue',
        label='±1 desviación estándar'
    )
    ax1.plot(
        years,
        cotas_promedio,
        'b-o',
        linewidth=2,
        markersize=4,
        label='Cota promedio'
    )
    ax1.set_title(
        'Evolución Histórica Monte Carlo: Cota del Lago',
        fontweight='bold',
        fontsize=12
    )
    ax1.set_xlabel('Año')
    ax1.set_ylabel('Cota promedio [msnm]')
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    # Subplot 2: Tasa de éxito por año
    ax2.bar(
        years,
        tasas_exito,
        alpha=0.7,
        color='green',
        label='Tasa de éxito'
    )
    ax2.set_title(
        'Tasa de Éxito por Año - Simulaciones Monte Carlo',
        fontweight='bold',
        fontsize=12
    )
    ax2.set_xlabel('Año')
    ax2.set_ylabel('Tasa de éxito [%]')
    ax2.set_ylim(0, 105)
    ax2.grid(True, alpha=0.3)
    ax2.legend()

    # Subplot 3: Evolución de energía con bandas de confianza
    ax3.fill_between(
        years,
        energia_promedio - energia_std,
        energia_promedio + energia_std,
        alpha=0.3,
        color='lightcoral',
        label='±1 desviación estándar'
    )
    ax3.plot(
        years,
        energia_promedio,
        'r-o',
        linewidth=2,
        markersize=4,
        label='Energía promedio'
    )
    ax3.set_title(
        'Evolución Histórica Monte Carlo: Generación Energética',
        fontweight='bold',
        fontsize=12
    )
    ax3.set_xlabel('Año')
    ax3.set_ylabel('Energía promedio [MWh]')
    ax3.grid(True, alpha=0.3)
    ax3.legend()

    # Subplot 4: Dependencia anual del embalse para cubrir déficits
    ax4.fill_between(
        years,
        dependencia_promedio - dependencia_std,
        dependencia_promedio + dependencia_std,
        alpha=0.3,
        color='lightsalmon',
        label='±1 desviación estándar'
    )
    ax4.bar(
        years,
        dependencia_promedio,
        alpha=0.7,
        color='coral',
        label='Dependencia promedio'
    )
    ax4.set_title(
        'Dependencia Anual del Embalse para Cubrir Déficits',
        fontweight='bold',
        fontsize=12
    )
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


def run_monte_carlo():
    """
    Función principal para ejecutar simulaciones Monte Carlo.

    Proporciona interfaz interactiva para configurar y ejecutar
    simulaciones híbridas Monte Carlo + Modelo Determinista.
    """
    from montecarlo import HybridSimulator

    configure_console()

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
        # Obtener parámetros de simulación
        while True:
            try:
                start_year = get_input(
                    "\n📅 Año inicial",
                    default=1960,
                    input_type=int
                )
                validate_year(start_year, min_year, max_year)
                break
            except ValueError as e:
                print(f"❌ {e}")

        n_years = get_input(
            "📆 Número de años",
            default=64,
            input_type=int
        )

        end_year = start_year + n_years - 1
        max_available = max(YEARS_HORIZON)
        if end_year > max_available:
            print(f"⚠️ Ajustando periodo final a {max_available}")
            n_years = max_available - start_year + 1

        V0 = get_input(
            "💧 Volumen inicial V0 (Hm³)",
            default=1400,
            input_type=float
        )
        n_scenarios = get_input(
            "🎲 Número de escenarios totales",
            default=100,
            input_type=int
        )
        block_len = get_input(
            "🧩 Longitud de bloques temporales",
            default=3,
            input_type=int
        )

        print("✅ Usando bootstrap puro - sin ruido estocástico\n")

        print("\n🚀 Iniciando simulación híbrida...")

        # Inicializar medición de rendimiento
        start_time = time.time()
        process = psutil.Process()

        # Ejecutar simulación
        simulator = HybridSimulator()
        results = simulator.run_simulation(
            start_year=start_year,
            n_years=n_years,
            V0=V0,
            n_scenarios=n_scenarios,
            block_len=block_len,
            verbose=True
        )

        # Imprimir resumen detallado
        print_monte_carlo_summary(results, n_years, n_scenarios, V0)

        # Imprimir KPIs
        print_monte_carlo_kpis(results)

        # Generar gráficos de evolución histórica si hay múltiples años
        if n_years > 1 and results.get("results_by_year"):
            try:
                print(
                    "\n📊 Generando gráficos de evolución histórica..."
                )
                plot_files = generate_montecarlo_evolution_plots(
                    results["results_by_year"],
                    output_dir="resultados"
                )
                print(
                    f"📊 Gráficos Monte Carlo: {len(plot_files)} "
                    f"archivo PNG"
                )
                for plot_file in plot_files:
                    print(f"   📈 {Path(plot_file).name}")
            except Exception as e:
                print(f"   ⚠️ Error generando gráficos: {e}")

        # Imprimir estadísticas de rendimiento
        performance_stats = get_performance_stats(start_time, process)
        print_performance_stats(performance_stats, "(Monte Carlo)")

    except KeyboardInterrupt:
        print("\n\n👋 Saliendo del programa...")
    except Exception as e:
        print(f"❌ Error inesperado: {e}")
        import traceback
        traceback.print_exc()
