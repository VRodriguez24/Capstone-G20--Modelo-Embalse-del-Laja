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
    print_performance_stats
)
from kpi import aggregate_kpis, print_kpis
from model import YEARS_HORIZON


def print_monte_carlo_summary(
    results: Dict,
    n_years: int,
    n_scenarios: int,
    V0: float,
    start_year: int
) -> None:
    """
    Imprime resumen detallado de resultados Monte Carlo.

    Args:
        results: Diccionario con resultados de la simulación
        n_years: Número de años simulados por escenario
        n_scenarios: Número total de escenarios
        V0: Volumen inicial
        start_year: Año inicial de la simulación
    """
    if not results.get("successful_scenarios"):
        print("\n⚠️ No hay escenarios exitosos para resumir")
        return

    print("\n" + "=" * 60)
    print(f"📋 RESUMEN SIMULACIÓN MONTE CARLO ({start_year}-"
          f"{start_year + n_years - 1})")
    print("=" * 60)

    successful_scenarios = results["successful_scenarios"]
    n_successful = len(successful_scenarios)

    # Calcular métricas agregadas
    energias = [s["total_energy"] for s in successful_scenarios]
    toro_usages = [s["total_toro_usage"] for s in successful_scenarios]
    final_volumes = [s["final_volume"] for s in successful_scenarios]

    # Estadísticas de energía
    energia_total_promedio = np.mean(energias)
    energia_std = np.std(energias) if len(energias) > 1 else 0
    energia_anual_promedio = energia_total_promedio / n_years
    energia_anual_std = energia_std / n_years

    # Estadísticas de uso del Toro
    toro_total_promedio = np.mean(toro_usages)
    toro_std = np.std(toro_usages) if len(toro_usages) > 1 else 0
    toro_anual_promedio = toro_total_promedio / n_years
    toro_anual_std = toro_std / n_years

    print(f"🎯 Escenarios procesados: {n_scenarios} | "
          f"✅ Exitosos: {n_successful} ({results['success_rate']:.1f}%)")

    print("\n⚡ GENERACIÓN ENERGÉTICA:")
    print(f"   • Total promedio: {energia_total_promedio:,.1f} ± "
          f"{energia_std:,.1f} MWh")
    print(f"   • Promedio anual: {energia_anual_promedio:,.1f} ± "
          f"{energia_anual_std:,.1f} MWh/año")

    print("\n🌊 EXTRACCIÓN DEL EMBALSE:")
    print(f"   • Total promedio: {toro_total_promedio:,.1f} ± "
          f"{toro_std:,.1f} Hm³")
    print(f"   • Promedio anual: {toro_anual_promedio:,.1f} ± "
          f"{toro_anual_std:,.1f} Hm³/año")

    # Balance volumétrico Monte Carlo
    if final_volumes:
        v_initial_mc = V0
        v_final_mc = np.mean(final_volumes)
        v_final_std = np.std(final_volumes) if len(final_volumes) > 1 else 0
        volume_change_mc = v_final_mc - v_initial_mc
        tasa_cambio = volume_change_mc / n_years
        change_sign_mc = "📈" if volume_change_mc >= 0 else "📉"

        print("\n💧 BALANCE VOLUMÉTRICO HISTÓRICO:")
        print(f"   • Inicial (Dic'{start_year - 1:02d}): "
              f"{v_initial_mc:,.1f} Hm³")
        print(f"   • Final (Nov'{start_year + n_years - 1:02d}): "
              f"{v_final_mc:,.1f} ± {v_final_std:,.1f} Hm³")
        print(f"   • {change_sign_mc} Cambio neto: "
              f"{volume_change_mc:+,.1f} Hm³")
        print(f"   • Tasa de cambio: {tasa_cambio:+,.1f} Hm³/año")

    print("\n🔄 Calculando KPIs históricos agregados...")
    print("   (Esto tomará algunos segundos)")


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
    identifiers = []  # Lista de identificadores (Escenario X - Año Y)
    v0_values = []    # Valores V0 correspondientes

    for scenario in successful_scenarios:
        scenario_id = scenario.get("scenario_id", "?")
        for year_result in scenario["results"]:
            if "kpis" in year_result and year_result["kpis"]:
                all_kpis.append(year_result["kpis"])
                year = year_result.get("year", "?")
                identifiers.append(f"Esc {scenario_id} - Año {year}")
                v0_values.append(year_result["kpis"].get("V0", 0.0))

    if all_kpis:
        # Agregar KPIs usando la función del módulo kpi
        # Para Monte Carlo, cada escenario tiene múltiples años
        # Aquí agregamos TODOS los KPIs de TODAS las simulaciones
        kpis_agregados = aggregate_kpis(
            all_kpis,
            identifiers=identifiers,
            v0_values=v0_values
        )

        # Mostrar KPIs agregados en consola (sin exportar)
        print_kpis(kpis_agregados, "Monte Carlo")
    else:
        print("⚠️ No se pudieron calcular KPIs para los escenarios exitosos")


def generate_montecarlo_evolution_plots(
    results_by_year: Dict[int, List[Dict]],
    output_dir: str = "resultados"
) -> List[str]:
    """
    Genera gráficos de evolución histórica para Monte Carlo.

    Crea 2 archivos PNG:
    1. Principal: 4 subplots (cota, energía, dependencia, déficits)
    2. Análisis: tasa de éxito por año

    Args:
        results_by_year: Resultados por año
        output_dir: Directorio de salida

    Returns:
        Lista de rutas de archivos PNG generados
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
    deficit_promedio = []
    deficit_std = []

    for year in years:
        year_results = results_by_year[year]
        successful_results = [r for r in year_results if r["status"] == "OK"]

        if successful_results:
            # Estadísticas del año
            volumen_promedio_year = []  # Volumen promedio (Hm³)
            energias_year = []  # Energía (MWh)
            extraccion_eltoro_year = []  # Extracción riego (Hm³)
            deficit_total_year = []  # Déficit total (Hm³)

            for result in successful_results:
                # Obtener KPIs si existen
                kpis = result.get("kpis", {})

                # Cota: promedio mensual (fallback a v_final)
                volumenes_data = kpis.get('volumenes_mensuales', {})
                if volumenes_data:
                    values = list(volumenes_data.values())
                    v_promedio = sum(values) / len(values)
                else:
                    v_promedio = result.get("v_final", 0)
                volumen_promedio_year.append(v_promedio)

                # Energía total anual (MWh) - CORREGIDO: clave consistente
                energias_year.append(result.get("energy", 0))

                # Extracción total del embalse: déficits 1R+2R
                # (coherente con ui_model.py y modelo determinista)
                def1 = kpis.get('deficit_sum_hm3', {}).get('1R', 0.0)
                def2 = kpis.get('deficit_sum_hm3', {}).get('2R', 0.0)
                extraccion_eltoro_year.append(def1 + def2)

                # Déficit total 1R + 2R (Hm³)
                deficit_total_year.append(def1 + def2)

            # Convertir volúmenes promedios a cotas
            # Cota [msnm] ≈ 1230 + (Volumen [Hm³] / 100)
            cotas_year = [1230 + (v / 100) for v in volumen_promedio_year]

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

            # Dependencia: Solo agua para cubrir déficits (1R+2R) en Hm³
            if extraccion_eltoro_year:
                dependencia_promedio.append(np.mean(extraccion_eltoro_year))
                dependencia_std.append(np.std(extraccion_eltoro_year))
            else:
                dependencia_promedio.append(0)
                dependencia_std.append(0)

            # Déficit total (1R + 2R) en Hm³
            if deficit_total_year:
                deficit_promedio.append(np.mean(deficit_total_year))
                deficit_std.append(np.std(deficit_total_year))
            else:
                deficit_promedio.append(0)
                deficit_std.append(0)

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
            deficit_promedio.append(0)
            deficit_std.append(0)
            tasas_exito.append(0)

    # ========================================================================
    # GRÁFICO PRINCIPAL: 4 subplots comparables con modelo determinista
    # ========================================================================
    fig1, axes = plt.subplots(4, 1, figsize=(14, 16))
    fig1.suptitle(
        'Evolución Histórica - Monte Carlo (Maximización Energía)',
        fontsize=14,
        fontweight='bold'
    )

    ax1, ax2, ax3, ax4 = axes

    # Convertir a arrays para facilitar cálculos
    cotas_promedio = np.array(cotas_promedio)
    cotas_std = np.array(cotas_std)
    energia_promedio = np.array(energia_promedio)
    energia_std = np.array(energia_std)
    dependencia_promedio = np.array(dependencia_promedio)
    dependencia_std = np.array(dependencia_std)
    deficit_promedio = np.array(deficit_promedio)
    deficit_std = np.array(deficit_std)

    # Subplot 1: Evolución de cota con bandas de confianza
    ax1.fill_between(
        years,
        cotas_promedio - cotas_std,
        cotas_promedio + cotas_std,
        alpha=0.2,
        color='lightblue',
        label='±1 desviación estándar'
    )
    ax1.plot(
        years,
        cotas_promedio,
        'b-',
        linewidth=2,
        marker='o',
        markersize=3,
        label='Cota promedio'
    )
    ax1.set_title(
        'Evolución Histórica del Nivel del Lago',
        fontweight='bold',
        fontsize=12
    )
    ax1.set_xlabel('Año', fontsize=10)
    ax1.set_ylabel('Cota promedio (msnm)', fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc='upper right', fontsize=8)

    # Subplot 2: Evolución de energía con bandas de confianza
    # Área de confianza (±1σ)
    ax2.fill_between(
        years,
        energia_promedio - energia_std,
        energia_promedio + energia_std,
        alpha=0.2,
        color='#E74C3C',
        label='±1 desviación estándar'
    )
    # Línea promedio
    ax2.plot(
        years,
        energia_promedio,
        color='#E74C3C',
        linewidth=2.5,
        marker='o',
        markersize=3,
        label='Generación promedio'
    )
    # Línea de promedio global
    gen_promedio_global = np.mean(energia_promedio)
    ax2.axhline(
        y=gen_promedio_global, color='#C0392B', linestyle='--',
        linewidth=1.5,
        label=f'Promedio global: {gen_promedio_global:,.0f} MWh/año'
    )

    ax2.set_title(
        'Generación Energética Anual (Monte Carlo)',
        fontweight='bold',
        fontsize=12
    )
    ax2.set_xlabel('Año', fontsize=10)
    ax2.set_ylabel('Energía Total (MWh/año)', fontsize=10)
    ax2.grid(True, alpha=0.3)
    ax2.legend(loc='upper right', fontsize=8)

    # Subplot 3: Dependencia del Embalse (Extracción por El Toro)
    # Área sombreada con banda de confianza ±1σ
    ax3.fill_between(
        years,
        dependencia_promedio - dependencia_std,
        dependencia_promedio + dependencia_std,
        alpha=0.25,
        color='steelblue',
        label='±1 desviación estándar'
    )
    # Línea de extracción promedio
    ax3.plot(
        years,
        dependencia_promedio,
        color='steelblue',
        linewidth=2.5,
        marker='o',
        markersize=3,
        label='Extracción promedio'
    )
    # Línea de promedio global
    dependencia_global = np.mean(dependencia_promedio)
    ax3.axhline(
        y=dependencia_global,
        color='darkblue',
        linestyle='--',
        linewidth=1.5,
        alpha=0.7,
        label=f'Promedio global: {dependencia_global:,.0f} Hm³/año'
    )

    ax3.set_title(
        'Dependencia Anual del Embalse para Cubrir Déficits',
        fontweight='bold',
        fontsize=12
    )
    ax3.set_xlabel('Año', fontsize=10)
    ax3.set_ylabel('Extracción para Riego (Hm³/año)', fontsize=10)
    ax3.grid(True, alpha=0.3)
    ax3.legend(loc='upper right', fontsize=8)

    # Subplot 4: Déficit total anual (1R + 2R) con bandas de confianza
    # Área de confianza (±1σ)
    ax4.fill_between(
        years,
        deficit_promedio - deficit_std,
        deficit_promedio + deficit_std,
        alpha=0.15,
        color='#95A5A6',
        label='Déficit Total ± 1σ'
    )
    # Línea de déficit total promedio
    ax4.plot(
        years,
        deficit_promedio,
        color='#E74C3C',
        linewidth=2.5,
        marker='o',
        markersize=3,
        label='Déficit Total (1R + 2R)'
    )
    ax4.set_title(
        'Evolución de Déficits de Riego Totales (Monte Carlo)',
        fontweight='bold',
        fontsize=12
    )
    ax4.set_xlabel('Año', fontsize=10)
    ax4.set_ylabel('Déficit Total (Hm³/año)', fontsize=10)
    ax4.grid(True, alpha=0.3)
    ax4.legend(loc='upper right', fontsize=8)

    # Mejorar etiquetas del eje X
    if len(years) > 10:
        ax4.set_xticks(years[::5])  # Cada 5 años
        ax4.set_xticklabels([str(y) for y in years[::5]], rotation=0)

    plt.tight_layout()

    # Guardar gráfico principal
    plot_file_main = output_path / "montecarlo_evolucion_historica.png"
    plt.savefig(plot_file_main, dpi=300, bbox_inches='tight')
    plt.close(fig1)
    files_created.append(str(plot_file_main))

    # ========================================================================
    # GRÁFICO SEPARADO: Tasa de éxito por año
    # ========================================================================
    fig2, ax_tasa = plt.subplots(1, 1, figsize=(14, 6))

    # Convertir a array
    tasas_exito = np.array(tasas_exito)

    # Gráfico de barras con color según tasa de éxito
    colors = ['green' if t >= 80 else 'orange' if t >= 50 else 'red'
              for t in tasas_exito]

    ax_tasa.bar(
        years,
        tasas_exito,
        alpha=0.7,
        color=colors,
        edgecolor='black',
        linewidth=0.5
    )

    # Línea de referencia al 100%
    ax_tasa.axhline(y=100, color='gray', linestyle='--',
                    linewidth=1, alpha=0.5, label='100% éxito')
    ax_tasa.axhline(y=80, color='orange', linestyle=':',
                    linewidth=1, alpha=0.5, label='80% umbral')

    ax_tasa.set_title(
        'Tasa de Éxito por Año - Simulaciones Monte Carlo',
        fontweight='bold',
        fontsize=14
    )
    ax_tasa.set_xlabel('Año', fontsize=12)
    ax_tasa.set_ylabel('Tasa de éxito [%]', fontsize=12)
    ax_tasa.set_ylim(0, 105)
    ax_tasa.grid(True, alpha=0.3, axis='y')
    ax_tasa.legend(loc='lower right')

    plt.tight_layout()

    # Guardar gráfico de tasa de éxito
    plot_file_tasa = output_path / "montecarlo_tasa_exito.png"
    plt.savefig(plot_file_tasa, dpi=300, bbox_inches='tight')
    plt.close(fig2)
    files_created.append(str(plot_file_tasa))

    return files_created


def run_monte_carlo():
    """
    Función principal para ejecutar simulaciones Monte Carlo.

    Proporciona interfaz interactiva para configurar y ejecutar
    simulaciones híbridas Monte Carlo + Modelo Determinista.
    """
    from montecarlo import HybridSimulator

    print("=" * 70)
    print(" 🔄 SIMULACIÓN HÍBRIDA: MONTE CARLO + MODELO DETERMINISTA")
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
                if start_year < min_year or start_year > max_year:
                    raise ValueError(
                        f"Año debe estar entre {min_year} y {max_year}"
                    )
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
        print_monte_carlo_summary(
            results, n_years, n_scenarios, V0, start_year
        )

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
                    f"archivos PNG"
                )
                for plot_file in plot_files:
                    print(f"   ✓ {Path(plot_file).name}")
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
