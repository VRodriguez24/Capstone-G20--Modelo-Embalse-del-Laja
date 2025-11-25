"""
=============================================================================
Interfaz específica para el Caso Base - Minimización de Déficit de Regantes
=============================================================================

Este módulo proporciona una interfaz optimizada para el caso base que:
- Muestra métricas enfocadas en déficits y cobertura de riego
- Oculta información de generación energética (no relevante)
- Reporta extracción de El Toro específicamente para riego
- Genera visualizaciones adaptadas al caso base

Uso:
    python src/caso_base.py
"""


import sys
import time
import psutil
import numpy as np
from pathlib import Path
from typing import Callable, List, Optional

from ui_helpers import (
    get_input,
    get_performance_stats,
    print_performance_stats
)
from kpi import aggregate_kpis, print_kpis, extract_kpis


def parse_years_input(years_str: str, years_horizon: List[int]) -> List[int]:
    """
    Parsea entrada de años: '1985' o '1980-1990'.

    Args:
        years_str: String con año único o rango
        years_horizon: Lista con [año_mínimo, año_máximo] disponibles
    Returns:
        Lista de años válidos

    Raises:
        ValueError: Si el formato es inválido o está fuera de rango
    """
    min_year, max_year = min(years_horizon), max(years_horizon)

    try:
        if '-' in years_str:
            # Formato de rango: "1980-1990"
            parts = years_str.split('-')
            if len(parts) != 2:
                raise ValueError("Formato de rango inválido")

            start_year = int(parts[0].strip())
            end_year = int(parts[1].strip())

            if start_year > end_year:
                start_year, end_year = end_year, start_year  # Intercambiar

            # Validar rango
            if start_year < min_year or end_year > max_year:
                raise ValueError(
                    f"Rango fuera de límites ({min_year}-{max_year})"
                )

            return list(range(start_year, end_year + 1))
        else:
            # Año único: "1985"
            year = int(years_str.strip())
            if year < min_year or year > max_year:
                raise ValueError(
                    f"Año fuera de rango ({min_year}-{max_year})"
                )
            return [year]

    except ValueError as e:
        if "invalid literal" in str(e):
            raise ValueError("Formato inválido. Use '1985' o '1980-1990'")
        raise e


def print_kpis_caso_base(
    kpis: dict,
    context: str = "",
    years: Optional[List[int]] = None
) -> None:
    """
    Imprime KPIs del caso base usando el formateo unificado de kpi.py.
    """
    if not kpis or kpis.get('status', -1) != 2:
        print("⚠️ No hay KPIs disponibles para mostrar")
        return
    print_kpis(kpis, context, is_caso_base=True, years=years)


def generate_caso_base_plots(
    kpis_historicos: List[dict],
    years: List[int],
    output_dir: str = "resultados"
) -> List[str]:
    """
    Genera gráficos específicos para caso base (sin generación).

    Args:
        kpis_historicos: Lista de KPIs por año
        years: Lista de años correspondientes
        output_dir: Directorio de salida

    Returns:
        Lista de rutas a archivos PNG generados
    """

    import matplotlib
    matplotlib.use('Agg')  # Backend sin GUI
    import matplotlib.pyplot as plt

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Extraer datos históricos
    cotas = []
    deficits_1r = []
    extraccion_toro = []
    volumenes_final = []

    for kpi in kpis_historicos:
        # Cota promedio anual
        cota_mensual = kpi.get('cota_mensual', {})
        if cota_mensual:
            cota_prom = sum(cota_mensual.values()) / len(cota_mensual)
            cotas.append(cota_prom)
        else:
            cotas.append(None)

        # Déficit total 1R
        def1 = kpi.get('deficit_sum_hm3', {}).get('1R', 0.0)
        deficits_1r.append(def1)

        # Extracción El Toro (x[Embalse, ElToro] - sin filtraciones)
        agua_eltoro = kpi.get('agua_eltoro_total', 0.0)
        extraccion_toro.append(agua_eltoro)

        # Volumen final
        v_end = kpi.get('V_end', 0.0)
        volumenes_final.append(v_end)

    # Crear figura con 3 subplots (sin generación)
    fig, axes = plt.subplots(3, 1, figsize=(12, 10))
    fig.suptitle(
        'Evolución Histórica - Caso Base (Minimización Déficit Riego)',
        fontsize=14,
        fontweight='bold'
    )

    # 1. Nivel del Lago (Cota)
    ax1 = axes[0]
    cotas_valid = [c for c in cotas if c is not None]
    years_valid = [y for y, c in zip(years, cotas) if c is not None]

    if cotas_valid:
        ax1.plot(years_valid, cotas_valid, 'b-', linewidth=1.5)
        ax1.set_ylabel('Cota promedio (msnm)', fontsize=10)
        ax1.set_title('Evolución Histórica del Nivel del Lago', fontsize=11)
        ax1.grid(True, alpha=0.3)

    # 2. Extracción de El Toro (déficit + tránsito)
    ax2 = axes[1]
    if extraccion_toro:
        ax2.bar(years, extraccion_toro, color='steelblue', alpha=0.7)
        ax2.set_ylabel('Extracción Total (Hm³/año)', fontsize=10)
        ax2.set_title(
            'Extracción Total por Canal El Toro (Déficit + Tránsito)',
            fontsize=11
        )
        ax2.grid(True, alpha=0.3, axis='y')

    # 3. Déficit Total Anual de Riego (1R)
    ax3 = axes[2]
    if deficits_1r:
        ax3.bar(years, deficits_1r, color='coral', alpha=0.7)
        ax3.set_ylabel('Déficit Total (Hm³/año)', fontsize=10)
        ax3.set_xlabel('Año', fontsize=10)
        ax3.set_title(
            'Déficit Total Anual de Riego (1R = Primeros Regantes)',
            fontsize=11
        )
        ax3.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()

    # Guardar
    filename = output_path / "evolucion_historica_lago_caso_base.png"
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()

    return [str(filename)]


def run_custom_range(
    build_model_func: Callable,
    years_horizon: List[int],
    time_periods: List[int],
    conv_factor: float,
    default_v0: float = 1400.0
):
    """
    Ejecuta el caso base para un año específico o rango de años.

    Args:
        build_model_func: Función que construye el modelo
        years_horizon: [año_min, año_max] disponibles
        time_periods: Lista de períodos de tiempo (meses)
        conv_factor: Factor de conversión m³/s*mes -> Hm³
        default_v0: Volumen inicial por defecto (Hm³)
    """
    min_year, max_year = min(years_horizon), max(years_horizon)

    print("\n📅 AÑO/RANGO ESPECÍFICO - CASO BASE")
    print(f"📊 Datos disponibles: {min_year}-{max_year}")
    print("📅 Cada 'año' = período hidrológico Dic->Nov")
    print("    (ej: 1985 = Dic'84 a Nov'85)")
    print("💡 Ejemplos:")
    print("   • Un año: '1985' (Dic'84 -> Nov'85)")
    print("   • Rango: '1980-1990' (11 períodos hidrológicos)")

    while True:
        try:
            years_input = get_input("Especifica año(s)")
            years = parse_years_input(years_input, years_horizon)
            break
        except ValueError as e:
            print(f"❌ {e}")
            continue

    V0 = get_input(
        "💧 Volumen inicial V0 (Hm³)",
        default=default_v0,
        input_type=float
    )

    years_count = len(years)
    if years_count == 1:
        print(f"\n🚀 Ejecutando caso base para el año {years[0]}...")
    else:
        print(
            f"\n🚀 Ejecutando caso base para {years_count} años "
            f"({years[0]}-{years[-1]})..."
        )

    print(f"💧 Volumen inicial: {V0:,.1f} Hm³")
    print("🎯 Objetivo: Minimizar déficit de primeros regantes (1R)")
    print("=" * 60)

    # Inicializar medición de rendimiento
    start_time = time.time()
    process = psutil.Process()

    # Ejecutar simulación
    results = []
    current_V0 = V0
    total_deficit = 0
    total_toro_usage = 0

    for i, year in enumerate(years):
        print(f"\n📅 Procesando año {year} ({i+1}/{years_count})")
        print(f"💧 V0: {current_V0:,.1f} Hm³")

        try:
            model = build_model_func(target_year=year, V0=current_V0)
            model.optimize()

            if model.status == 2:  # Óptimo
                # CORRECCIÓN: Extraer déficit real desde Def1, NO objVal
                # objVal = 1000*MaxDef + ExtraccionTotal (no es déficit total)
                deficit_val = sum(
                    model._Def1[t].x for t in time_periods
                )

                V_vars = model._V
                final_month = max(time_periods)
                v_final = V_vars[final_month].x

                # Extraer KPIs completos para cálculos precisos
                kpis = extract_kpis(model, include_detailed=False)
                agua_eltoro_total = kpis.get('agua_eltoro_total', 0.0)

                print(f"   ✅ Déficit: {deficit_val:.2f} Hm³  |  "
                      f"V_final: {v_final:,.1f} Hm³  |  "
                      f"Flujo El Toro: {agua_eltoro_total:>6,.1f} Hm³")

                total_deficit += deficit_val
                total_toro_usage += agua_eltoro_total
                current_V0 = v_final

                results.append({
                    'year': year,
                    'deficit': deficit_val,
                    'v_final': v_final,
                    'toro_usage': agua_eltoro_total,
                    'kpis': kpis,  # Guardar KPIs completos
                    'status': 'OK'
                })
            else:
                print("❌ No factible - usando V0 de seguridad (1400 Hm³)")
                current_V0 = 1400.0
                results.append({
                    'year': year,
                    'deficit': 0,
                    'v_final': None,
                    'toro_usage': 0,
                    'status': 'FAIL'
                })

            model.dispose()

        except Exception as e:
            print(f"❌ Error ({year}): {e}")
            results.append({
                'year': year,
                'deficit': 0,
                'v_final': None,
                'toro_usage': 0,
                'status': 'ERROR'
            })

    # Resumen
    print("\n" + "=" * 60)
    print("📋 RESUMEN CASO BASE")
    print("=" * 60)

    successful = [r for r in results if r['status'] == 'OK']
    success_rate = (
        len(successful) / years_count * 100 if years_count > 0 else 0
    )

    print(f"🎯 Años procesados: {years_count}")
    print(f"✅ Años exitosos: {len(successful)} ({success_rate:.1f}%)")

    if len(results) > len(successful):
        failed_years = [r['year'] for r in results if r['status'] != 'OK']
        print(f"❌ Años con problemas: {failed_years}")

    print("\n🌊 AGUA PROVISTA POR EL EMBALSE:")
    print(f"   • Déficit total 1R (Def1):    {total_deficit:,.2f} Hm³")
    print("     └─ Agua del embalse necesaria para cubrir demanda")
    print("        no satisfecha por filtraciones + afluentes naturales")

    print("\n💧 FLUJO TOTAL POR EL TORO:")
    print(f"   • Extracción total:           {total_toro_usage:,.1f} Hm³")
    # Calcular componentes usando KPIs (déficits compensados)
    total_agua_deficit = sum(
        r['kpis'].get('agua_eltoro_deficit_1r', 0.0) for r in successful
    )
    total_transito_rango = total_toro_usage - total_agua_deficit
    print(f"     ├─ Cobertura déficit (1R): {total_agua_deficit:,.1f} Hm³")
    print(f"     └─ Tránsito afluentes:    {total_transito_rango:,.1f} Hm³")

    if successful:
        avg_deficit = total_deficit / len(successful)
        deficits = [r['deficit'] for r in successful]
        toro_usages = [r['toro_usage'] for r in successful]

        # Estadísticas de variabilidad
        deficit_std = np.std(deficits) if len(deficits) > 1 else 0.0
        deficit_max = max(deficits)
        deficit_min = min(deficits)

        print("\n📊 PROMEDIOS ANUALES:")
        print(f"   • Déficit promedio:           {avg_deficit:,.2f} Hm³/año")
        print(f"   • Desviación estándar:       {deficit_std:,.2f} Hm³")
        print(f"   • Rango de déficits:         "
              f"[{deficit_min:,.1f}, {deficit_max:,.1f}] Hm³")

        if toro_usages:
            avg_toro = sum(toro_usages) / len(toro_usages)
            print(f"   • Flujo El Toro promedio:     {avg_toro:,.1f} Hm³/año")

        # Balance volumétrico mejorado
        v_initial = V0
        v_final_last = successful[-1]['v_final'] if successful else V0
        volume_change = v_final_last - v_initial
        change_sign = "📈" if volume_change >= 0 else "📉"
        change_rate = volume_change / len(successful) if successful else 0.0

        print("\n💧 BALANCE VOLUMÉTRICO:")
        print(f"   • Inicial: {v_initial:,.1f} Hm³")
        print(f"   • Final:   {v_final_last:,.1f} Hm³")
        print(f"   • {change_sign} Cambio neto: {volume_change:+,.1f} Hm³")
        print(f"   • Tasa de cambio: {change_rate:+,.1f} Hm³/año")

        # Eficiencia del embalse
        if total_deficit > 0:
            agua_extra = total_toro_usage - total_deficit
            efficiency = agua_extra / total_deficit * 100
            print(f"   • Agua de tránsito: {efficiency:+.1f}% "
                  "adicional al déficit")

        # Validación de cobertura mejorada
        print("\n📊 VALIDACIÓN DE COBERTURA:")
        if total_deficit > 0:
            ratio_coverage = total_toro_usage / total_deficit
            agua_transito = total_toro_usage - total_deficit
            print(f"   • Ratio El Toro / Déficit: {ratio_coverage:.2f}x")
            print(f"   • Agua de tránsito: {agua_transito:,.1f} Hm³")

            if abs(ratio_coverage - 1.0) < 0.05:
                print("      ✅ CORRECTO: Cobertura exacta del déficit")
            elif ratio_coverage > 1.05:
                exceso_pct = (ratio_coverage - 1.0) * 100
                print(
                    f"      ℹ️ El Toro liberó {exceso_pct:.1f}% "
                    "más (agua de tránsito ecológico)"
                )
            else:
                deficit_pct = (1.0 - ratio_coverage) * 100
                print(
                    f"      ⚠️ El Toro liberó {deficit_pct:.1f}% "
                    "menos que el déficit"
                )

            # Intensidad del déficit
            deficit_intensity = (
                total_deficit / len(successful) if successful else 0
            )
            if deficit_intensity > 50:
                print("      🔴 Intensidad de déficit: ALTA (>50 Hm³/año)")
            elif deficit_intensity > 20:
                print("      🟡 Intensidad de déficit: "
                      "MODERADA (20-50 Hm³/año)")
            else:
                print("      🟢 Intensidad de déficit: BAJA (<20 Hm³/año)")
        else:
            print("   • Sin déficit en el periodo - "
                  "Riego completamente cubierto")
            print("      🟢 Estado óptimo: Demanda satisfecha "
                  "por fuentes naturales")

    # Tabla detallada
    if years_count > 1:
        print("\n📊 DETALLE POR AÑO:")
        print("━" * 80)
        print("Año   Estado  Déficit (Hm³)  V_final (Hm³)  Uso Toro (Hm³)")
        print("━" * 80)

        for r in results:
            status_icon = "✅" if r['status'] == 'OK' else "❌"
            if r['status'] == 'OK':
                print(
                    f"{r['year']}  {status_icon}     "
                    f"{r['deficit']:11.2f}  {r['v_final']:13,.1f}  "
                    f"{r['toro_usage']:14,.1f}"
                )
            else:
                print(
                    f"{r['year']}  {status_icon}     {'FALLO':>11}  "
                    f"{'-':>13}  {'-':>14}"
                )
        print("━" * 80)

    # Estadísticas de rendimiento
    performance_stats = get_performance_stats(start_time, process)
    context = (
        f"({years_count} años)" if years_count > 1
        else f"(año {years[0]})"
    )
    print_performance_stats(performance_stats, context)


def run_all_years(
    build_model_func: Callable,
    years_horizon: List[int],
    time_periods: List[int],
    conv_factor: float,
    default_v0: float = 1400.0
):
    """
    Ejecuta el caso base para todos los años disponibles.

    Args:
        build_model_func: Función que construye el modelo
        years_horizon: [año_min, año_max] disponibles
        time_periods: Lista de períodos de tiempo
        conv_factor: Factor de conversión
        default_v0: Volumen inicial por defecto
    """
    min_year, max_year = min(years_horizon), max(years_horizon)
    total_years = max_year - min_year + 1

    print("\n🚀 SIMULACIÓN COMPLETA - CASO BASE")
    print(f"📊 Período: {min_year}-{max_year} ({total_years} períodos)")
    print("📅 Cada período: Diciembre -> Noviembre")
    print("🎯 Objetivo: Minimizar déficit de primeros regantes (1R)")

    confirm_msg = f"¿Confirmas ejecutar {total_years} años? [s/N]"
    confirm = get_input(confirm_msg, default="N")
    if confirm.lower() not in ['s', 'sí', 'si', 'y', 'yes']:
        print("❌ Operación cancelada")
        return

    V0 = get_input(
        "💧 Volumen inicial V0 (Hm³)",
        default=default_v0,
        input_type=float
    )

    print("\n🚀 Iniciando simulación completa...")
    print("="*60)
    print(f"📅 Periodo: {min_year}-{max_year}")
    print(f"💧 V0: {V0:.1f} Hm³")
    print(f"🎯 Años totales: {total_years}")
    print("📊 Modelo: Minimización de déficit (1R)")
    print("="*60)
    print()

    start_time = time.time()
    process = psutil.Process()

    results = []
    current_V0 = V0
    total_deficit = 0
    total_toro_usage = 0

    for year in range(min_year, max_year + 1):
        year_num = year - min_year + 1

        try:
            model = build_model_func(target_year=year, V0=current_V0)
            # Suprimir completamente la salida de Gurobi
            model.Params.OutputFlag = 0
            model.Params.LogToConsole = 0
            model.optimize()

            if model.status == 2:
                # CORRECCIÓN: Extraer déficit real desde Def1, NO objVal
                # objVal = 1000*MaxDef + ExtraccionTotal (no es déficit total)
                deficit_val = sum(
                    model._Def1[t].x for t in time_periods
                )

                V_vars = model._V
                final_month = max(time_periods)
                v_final = V_vars[final_month].x

                # Extraer KPIs completos para cálculos precisos
                kpis = extract_kpis(model, include_detailed=False)

                agua_eltoro_total = kpis.get('agua_eltoro_total', 0.0)

                # Formato alineado: campos de ancho fijo
                # [year_num/total] ocupa 8 caracteres
                # "Año XXXX" ocupa 9 caracteres
                # Déficit con 2 decimales, alineado a derecha en 9 caracteres
                # V_final con 1 decimal y separador de miles
                year_num = year - min_year + 1
                print(
                    f"📅 [{year_num:2d}/{total_years}] Año {year}... "
                    f"✅ Déficit: {deficit_val:9.1f} Hm³  |  "
                    f"V_final: {v_final:>8,.1f} Hm³  |  "
                    f"Flujo El Toro: {agua_eltoro_total:>6,.1f} Hm³"
                )

                total_deficit += deficit_val
                total_toro_usage += agua_eltoro_total
                current_V0 = v_final

                results.append({
                    'year': year,
                    'deficit': deficit_val,
                    'v_final': v_final,
                    'toro_usage': agua_eltoro_total,
                    'kpis': kpis,  # Guardar KPIs completos
                    'status': 'OK'
                })
            else:
                year_num = year - min_year + 1
                print(
                    f"📅 [{year_num:2d}/{total_years}] Año {year}... "
                    f"❌ No factible (status={model.status})"
                )
                current_V0 = 1400.0
                results.append({
                    'year': year,
                    'deficit': 0,
                    'v_final': None,
                    'toro_usage': 0,
                    'status': 'FAIL'
                })

            model.dispose()

        except Exception as e:
            year_num = year - min_year + 1
            print(
                f"📅 [{year_num:2d}/{total_years}] Año {year}... "
                f"❌ Error: {e}"
            )
            results.append({
                'year': year,
                'deficit': 0,
                'v_final': None,
                'toro_usage': 0,
                'status': 'ERROR'
            })

    # Resumen completo
    print("\n" + "=" * 60)
    print(f"📋 RESUMEN SIMULACIÓN COMPLETA ({min_year}-{max_year})")
    print("=" * 60)

    successful = [r for r in results if r['status'] == 'OK']
    success_rate = (
        len(successful) / total_years * 100
    ) if total_years > 0 else 0

    print(
        f"🎯 Años procesados: {total_years} | "
        f"✅ Exitosos: {len(successful)} ({success_rate:.1f}%)"
    )

    # SECCIÓN 1: GENERACIÓN ENERGÉTICA (N/A para caso base)
    print("\n⚡ GENERACIÓN ENERGÉTICA:")
    print("   • N/A (modelo de minimización de déficit)")

    # SECCIÓN 2: USO ACTIVO DEL EMBALSE (flujos controlados para riego)
    if successful:
        print("\n🌊 USO ACTIVO DEL EMBALSE:")
        print(
            f"   • Extracción total (Canal El Toro): "
            f"{total_toro_usage:,.1f} Hm³"
        )
        # Desglosar componentes usando KPIs correctos
        total_agua_deficit = sum(
            r['kpis'].get('agua_eltoro_deficit_1r', 0.0) for r in successful
        )
        total_transito = total_toro_usage - total_agua_deficit

        print(f"     ├─ Cobertura déficit (1R): {total_agua_deficit:,.1f} Hm³")
        print(f"     └─ Tránsito afluentes:    {total_transito:,.1f} Hm³")
        avg_toro = total_toro_usage / len(successful)
        print(f"   • Promedio anual: {avg_toro:,.1f} Hm³/año")

        # Balance volumétrico histórico
        v_initial = V0
        v_final_last = successful[-1]['v_final'] if successful else V0
        volume_change = v_final_last - v_initial
        change_sign = "📈" if volume_change >= 0 else "📉"
        if len(successful) > 0:
            change_rate = volume_change / len(successful)
        else:
            change_rate = 0.0

        print("\n💧 BALANCE VOLUMÉTRICO HISTÓRICO:")
        print(f"   • Inicial (Dic'59): {v_initial:,.1f} Hm³")
        print(f"   • Final (Nov'23): {v_final_last:,.1f} Hm³")
        print(f"   • {change_sign} Cambio neto: {volume_change:+,.1f} Hm³")
        print(f"   • Tasa de cambio: {change_rate:+,.1f} Hm³/año")

    # KPIs históricos detallados
    print("\n🔄 Calculando KPIs históricos detallados...")
    print("   (Esto tomará algunos segúndos)")
    kpis_historicos = []
    years_exitosos = []  # Tracking de años exitosos
    all_years = list(range(min_year, max_year + 1))
    current_V0_sample = V0

    for year in all_years:
        try:
            model = build_model_func(
                target_year=year, V0=current_V0_sample
            )
            model.Params.OutputFlag = 0
            model.optimize()

            if model.status == 2:
                kpis = extract_kpis(model, include_detailed=True)
                kpis_historicos.append(kpis)
                years_exitosos.append(year)  # Registrar año exitoso

                # Actualizar V0 para siguiente año
                V_vars = model._V
                final_month = max(time_periods)
                current_V0_sample = V_vars[final_month].x
            else:
                current_V0_sample = 1400.0

            model.dispose()
        except Exception:
            current_V0_sample = 1400.0

    if kpis_historicos:
        # Calcular lista de V0 usado en cada año
        v0_list = [default_v0]  # Primer año
        for idx in range(1, len(years_exitosos)):
            try:
                prev_kpis = kpis_historicos[idx - 1]
                v0_list.append(prev_kpis.get('V_end', default_v0))
            except (IndexError, KeyError):
                v0_list.append(default_v0)

        kpis_agregados = aggregate_kpis(
            kpis_historicos, years=years_exitosos, v0_values=v0_list
        )
        context = f"Histórico ({len(kpis_historicos)} casos)"
        years_list = all_years[:len(kpis_historicos)]
        print_kpis_caso_base(kpis_agregados, context, years=years_list)

        # Generar gráficos específicos caso base
        try:
            print("\n📊 Generando gráficos de evolución histórica...")
            plot_files = generate_caso_base_plots(
                kpis_historicos,
                all_years[:len(kpis_historicos)],
                output_dir="resultados"
            )
            print(f"📊 Gráficos generados: {len(plot_files)} archivos PNG")
            for pf in plot_files:
                filename = Path(pf).name
                print(f"   ✓ {filename}")
        except Exception as e:
            print(f"⚠️ Error generando gráficos: {e}")
    else:
        print("\n⚠️ No se pudieron calcular KPIs históricos detallados")

    performance_stats = get_performance_stats(start_time, process)
    print_performance_stats(performance_stats, "(simulación completa)")


def run(
    build_model_func: Callable,
    years_horizon: List[int],
    time_periods: List[int],
    conv_factor: float,
    model_name: str = "Caso Base - Minimización Déficit Regantes",
    default_v0: float = 1400.0
):
    """
    Interfaz principal para ejecutar el caso base.

    Args:
        build_model_func: Función que construye el modelo
        years_horizon: [año_min, año_max] de datos disponibles
        time_periods: Lista de períodos de tiempo
        conv_factor: Factor de conversión m³/s*mes -> Hm³
        model_name: Nombre descriptivo del modelo
        default_v0: Volumen inicial por defecto (Hm³)
    """

    def print_simple_menu():
        print("=" * 60)
        print(f"  🌊 {model_name.upper()}")
        print("=" * 60)
        min_year, max_year = min(years_horizon), max(years_horizon)
        print(f"📊 Datos disponibles: {min_year} - {max_year}")
        print("📅 Período hidrológico: Diciembre -> Noviembre")
        print("    (fin temporada 30-Nov)")
        print("\n🎯 Opciones:")
        print("1️⃣  Año/Rango específico (ej: '1985' o '1980-1990')")
        print(f"2️⃣  Todos los años disponibles ({min_year}-{max_year})")
        print("0️⃣  Salir")
        print("-" * 60)

    # Bucle principal
    while True:
        try:
            print_simple_menu()

            choice = get_input("\nSelecciona una opción", input_type=int)

            if choice == 0:
                print("👋 ¡Hasta luego!")
                break
            elif choice == 1:
                run_custom_range(
                    build_model_func=build_model_func,
                    years_horizon=years_horizon,
                    time_periods=time_periods,
                    conv_factor=conv_factor,
                    default_v0=default_v0
                )
            elif choice == 2:
                run_all_years(
                    build_model_func=build_model_func,
                    years_horizon=years_horizon,
                    time_periods=time_periods,
                    conv_factor=conv_factor,
                    default_v0=default_v0
                )
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
