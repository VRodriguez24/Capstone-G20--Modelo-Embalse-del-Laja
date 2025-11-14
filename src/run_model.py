"""
Interfaz unificada de ejecución para todos los modelos del Embalse del Laja.

Este módulo centraliza la lógica de ejecución, menús interactivos y análisis
de resultados para todos los modelos (determinístico, caso base, montecarlo).

Uso típico:
    from run_model import run
    from model import build_model_for_one_year, YEARS_HORIZON, T, Conv

    if __name__ == "__main__":
        run(
            build_model_func=build_model_for_one_year,
            years_horizon=YEARS_HORIZON,
            time_periods=T,
            conv_factor=Conv,
            model_name="Modelo Determinístico"
        )
"""

import sys
import time
import psutil
from typing import Callable, List
from collections import defaultdict

from ui_helpers import (
    get_input,
    get_performance_stats,
    print_performance_stats
)
from kpi import (
    extract_kpis,
    aggregate_kpis,
    print_kpis,
    generate_historical_plots
)


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


def run_custom_range(
    build_model_func: Callable,
    years_horizon: List[int],
    time_periods: List[int],
    conv_factor: float,
    default_v0: float = 1400.0
):
    """
    Ejecuta el modelo para un año específico o rango de años.

    Args:
        build_model_func: Función que construye el modelo
        years_horizon: [año_min, año_max] disponibles
        time_periods: Lista de períodos de tiempo (meses)
        conv_factor: Factor de conversión m³/s*mes -> Hm³
        default_v0: Volumen inicial por defecto (Hm³)
    """
    min_year, max_year = min(years_horizon), max(years_horizon)

    print("\n📅 AÑO/RANGO ESPECÍFICO")
    print(f"📊 Datos disponibles: {min_year}-{max_year}")
    print("📅 Cada 'año' = período hidrológico Dic->Nov")
    print("    (ej: 1985 = Dic'84 a Nov'85)")
    print("💡 Ejemplos:")
    print("   • Un año: '1985' (Dic'84 -> Nov'85)")
    print("   • Rango: '1980-1990' (11 períodos hidrológicos)")
    print("   • Década: '1990-1999' (10 períodos hidrológicos)")

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
        print(f"\n🚀 Ejecutando modelo para el año {years[0]}...")
    else:
        print(
            f"\n🚀 Ejecutando modelo para {years_count} años "
            f"({years[0]}-{years[-1]})..."
        )

    print(f"💧 Volumen inicial: {V0:,.1f} Hm³")
    print("=" * 60)

    # Inicializar medición de rendimiento
    start_time = time.time()
    process = psutil.Process()

    # Ejecutar simulación
    results = []
    current_V0 = V0
    total_energy = 0
    total_toro_usage = 0

    for i, year in enumerate(years):
        print(f"\n📅 Procesando año {year} ({i+1}/{years_count})")
        print(f"💧 V0: {current_V0:,.1f} Hm³")

        try:
            model = build_model_func(target_year=year, V0=current_V0)
            model.optimize()

            if model.status == 2:  # Óptimo
                energy = model.objVal
                V_vars = model._V
                final_month = max(time_periods)
                v_final = V_vars[final_month].x

                # Calcular uso del Toro (si existe en el modelo)
                x_vars = model._x
                toro_usage = 0
                # x_vars tiene claves (origen, destino, periodo)
                # Verificar si existe alguna clave con ("Embalse", "ElToro")
                if any(k[:2] == ("Embalse", "ElToro") for k in x_vars.keys()):
                    toro_usage = sum(
                        x_vars["Embalse", "ElToro", t].x
                        for t in time_periods
                    ) * conv_factor

                print(
                    f"✅ Energía: {energy:,.1f} MWh | "
                    f"V_final: {v_final:,.1f} Hm³ | "
                    f"Uso Toro: {toro_usage:,.1f} Hm³"
                )

                total_energy += energy
                total_toro_usage += toro_usage
                current_V0 = v_final  # Recursivo
                results.append({
                    'year': year,
                    'energy': energy,
                    'v_final': v_final,
                    'toro_usage': toro_usage,
                    'status': 'OK'
                })
            else:
                print("❌ No factible - usando V0 de seguridad (1400 Hm³)")
                current_V0 = 1400.0
                results.append({
                    'year': year,
                    'energy': 0,
                    'v_final': None,
                    'toro_usage': 0,
                    'status': 'FAIL'
                })

            model.dispose()

        except Exception as e:
            print(f"❌ Error en año {year}: {e}")
            results.append({
                'year': year,
                'energy': 0,
                'v_final': None,
                'toro_usage': 0,
                'status': 'ERROR'
            })

    # Resumen
    print("\n" + "=" * 60)
    print("📋 RESUMEN DETALLADO")
    print("=" * 60)

    successful = [r for r in results if r['status'] == 'OK']
    if years_count > 0:
        success_rate = len(successful) / years_count * 100
    else:
        success_rate = 0

    print(f"🎯 Años procesados: {years_count}")
    print(f"✅ Años exitosos: {len(successful)} ({success_rate:.1f}%)")
    print(f"⚡ Energía total: {total_energy:,.1f} MWh")
    print(f"🌊 Uso total El Toro: {total_toro_usage:,.1f} Hm³")

    if successful:
        avg_energy = total_energy / len(successful)
        avg_toro = total_toro_usage / len(successful)
        print(f"📊 Energía promedio: {avg_energy:,.1f} MWh/año")
        print(f"📊 Uso promedio El Toro: {avg_toro:,.1f} Hm³/año")

        # Balance volumétrico
        v_initial = V0
        v_final_last = successful[-1]['v_final'] if successful else V0
        volume_change = v_final_last - v_initial
        change_sign = "📈" if volume_change >= 0 else "📉"

        print("\n💧 BALANCE DE VOLUMEN:")
        print(f"   Inicial: {v_initial:,.1f} Hm³")
        print(f"   Final: {v_final_last:,.1f} Hm³")
        print(f"   {change_sign} Cambio: {volume_change:+,.1f} Hm³")

        # KPIs DETALLADOS
        print("\n🔄 Calculando KPIs detallados...")
        kpis_list = []
        for result in successful:
            year = result['year']
            try:
                model = build_model_func(target_year=year, V0=V0)
                model.Params.OutputFlag = 0
                model.optimize()

                if model.status == 2:
                    kpis = extract_kpis(model)
                    kpis_list.append(kpis)

                    # Mostrar KPIs para primer año
                    if len(kpis_list) == 1:
                        print_kpis(kpis, f"Año {year}")

                model.dispose()
            except Exception as e:
                print(f"   ⚠️ Error calculando KPIs para {year}: {e}")

        # KPIs agregados para múltiples años
        if len(kpis_list) > 1:
            print(f"\n📊 KPIs AGREGADOS ({len(kpis_list)} años exitosos):")
            print("=" * 60)

            cota_sums = defaultdict(float)
            cota_counts = defaultdict(int)
            deficit_maxs = []
            deficit_proms = []
            confiabilidades = []

            for kpis in kpis_list:
                for mes, cota in kpis.get("cota_mensual", {}).items():
                    cota_sums[mes] += cota
                    cota_counts[mes] += 1

                deficit_maxs.append(kpis.get("deficit_max_m3s", 0.0))
                deficit_proms.append(kpis.get("deficit_prom_m3s", 0.0))
                confiabilidades.append(kpis.get("confiabilidad_%", 100.0))

            cota_prom_agregada = {
                mes: cota_sums[mes] / cota_counts[mes]
                for mes in cota_sums.keys()
            }
            avg_cota_total = (
                sum(cota_prom_agregada.values()) / len(cota_prom_agregada)
                if cota_prom_agregada else 0
            )

            print("📏 TRAYECTORIA PROMEDIO AGREGADA:")
            print(f"   Cota promedio multi-año: {avg_cota_total:6.1f} msnm")

            if deficit_maxs:
                deficit_max_prom = sum(deficit_maxs) / len(deficit_maxs)
                deficit_max_worst = max(deficit_maxs)
                deficit_prom_prom = sum(deficit_proms) / len(deficit_proms)
                n_confiab = len(confiabilidades)
                confiabilidad_prom = sum(confiabilidades) / n_confiab

                print("\n🚱 DÉFICITS AGREGADOS:")
                print(
                    f"   Déficit máximo promedio: "
                    f"{deficit_max_prom:8.2f} m³/s"
                )
                print(
                    f"   Déficit máximo peor año: "
                    f"{deficit_max_worst:8.2f} m³/s"
                )
                print(f"   Déficit promedio: {deficit_prom_prom:8.2f} m³/s")
                print(
                    f"   Confiabilidad promedio: "
                    f"{confiabilidad_prom:8.1f}%"
                )

    # Tabla detallada
    if years_count > 1:
        print("\n📊 DETALLE POR AÑO:")
        print("━" * 80)
        print("Año   Estado  Energía (MWh)  V_final (Hm³)  Uso Toro (Hm³)")
        print("━" * 80)

        for r in results:
            status_icon = "✅" if r['status'] == 'OK' else "❌"
            if r['status'] == 'OK':
                print(
                    f"{r['year']}   {status_icon}    "
                    f"{r['energy']:>12,.1f}  {r['v_final']:>13,.1f}  "
                    f"{r['toro_usage']:>14,.1f}"
                )
            else:
                print(
                    f"{r['year']}   {status_icon}       "
                    f"---          ---          ---"
                )
        print("━" * 80)

    # Estadísticas de rendimiento
    performance_stats = get_performance_stats(start_time, process)
    if years_count > 1:
        context = f"({years_count} años)"
    else:
        context = f"(año {years[0]})"
    print_performance_stats(performance_stats, context)


def run_all_years(
    build_model_func: Callable,
    years_horizon: List[int],
    time_periods: List[int],
    conv_factor: float,
    default_v0: float = 1400.0
):
    """
    Ejecuta el modelo para todos los años disponibles.

    Args:
        build_model_func: Función que construye el modelo
        years_horizon: [año_min, año_max] disponibles
        time_periods: Lista de períodos de tiempo
        conv_factor: Factor de conversión
        default_v0: Volumen inicial por defecto
    """
    min_year, max_year = min(years_horizon), max(years_horizon)
    total_years = max_year - min_year + 1

    print("\n🚀 SIMULACIÓN COMPLETA")
    print(f"📊 Período: {min_year}-{max_year} ({total_years} períodos)")
    print("📅 Cada período: Diciembre -> Noviembre (fin temporada 30-Nov)")

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
    print("=" * 60)

    start_time = time.time()
    process = psutil.Process()

    results = []
    current_V0 = V0
    total_energy = 0
    total_toro_usage = 0

    for year in range(min_year, max_year + 1):
        year_num = year - min_year + 1
        print(f"\n📅 Año {year} ({year_num}/{total_years})")
        print(f"💧 V0: {current_V0:,.1f} Hm³")

        try:
            model = build_model_func(target_year=year, V0=current_V0)
            model.optimize()

            if model.status == 2:  # Óptimo
                energy = model.objVal
                V_vars = model._V
                final_month = max(time_periods)
                v_final = V_vars[final_month].x

                x_vars = model._x
                toro_usage = 0
                # Verificar existencia del arco El Toro
                if any(k[:2] == ("Embalse", "ElToro") for k in x_vars.keys()):
                    toro_usage = sum(
                        x_vars["Embalse", "ElToro", t].x
                        for t in time_periods
                    ) * conv_factor

                print(
                    f"✅ E: {energy:,.0f} MWh | "
                    f"V_f: {v_final:,.0f} | "
                    f"Toro: {toro_usage:,.1f} Hm³"
                )

                total_energy += energy
                total_toro_usage += toro_usage
                current_V0 = v_final
                results.append({
                    'year': year,
                    'energy': energy,
                    'v_final': v_final,
                    'toro_usage': toro_usage,
                    'status': 'OK'
                })
            else:
                print("❌ No factible - reset a 1400 Hm³")
                current_V0 = 1400.0
                results.append({
                    'year': year,
                    'energy': 0,
                    'v_final': None,
                    'toro_usage': 0,
                    'status': 'FAIL'
                })

            model.dispose()

        except Exception as e:
            print(f"❌ Error: {e}")
            results.append({
                'year': year,
                'energy': 0,
                'v_final': None,
                'toro_usage': 0,
                'status': 'ERROR'
            })

    # Resumen completo
    print("\n" + "=" * 60)
    print(f"📋 RESUMEN SIMULACIÓN COMPLETA ({min_year}-{max_year})")
    print("=" * 60)

    successful = [r for r in results if r['status'] == 'OK']
    success_rate = len(successful) / total_years * 100

    print(f"🎯 Años procesados: {total_years}")
    print(f"✅ Años exitosos: {len(successful)} ({success_rate:.1f}%)")
    print(f"⚡ Energía total: {total_energy:,.1f} MWh")
    print(f"🌊 Uso total El Toro: {total_toro_usage:,.1f} Hm³")

    if successful:
        avg_energy = total_energy / len(successful)
        avg_toro = total_toro_usage / len(successful)
        print(f"📊 Energía promedio: {avg_energy:,.1f} MWh/año")
        print(f"📊 Uso promedio El Toro: {avg_toro:,.1f} Hm³/año")

        # Balance volumétrico histórico
        v_initial = V0
        v_final_last = successful[-1]['v_final'] if successful else V0
        volume_change = v_final_last - v_initial
        change_sign = "📈" if volume_change >= 0 else "📉"

        print("\n💧 BALANCE VOLUMÉTRICO HISTÓRICO:")
        print(f"   Inicial (Dic'59): {v_initial:,.1f} Hm³")
        print(f"   Final (Nov'23): {v_final_last:,.1f} Hm³")
        print(f"   {change_sign} Cambio neto: {volume_change:+,.1f} Hm³")

        # KPIs históricos detallados
        print("\n🔄 Calculando KPIs históricos detallados...")
        print("   (Esto puede tomar varios minutos)")

        kpis_historicos = []
        all_years = list(range(min_year, max_year + 1))
        current_V0_sample = V0

        for year in all_years:
            try:
                model = build_model_func(
                    target_year=year,
                    V0=current_V0_sample
                )
                model.Params.OutputFlag = 0
                model.optimize()

                if model.status == 2:
                    kpis = extract_kpis(model)
                    kpis_historicos.append(kpis)

                    if hasattr(model, '_V'):
                        final_month = max(time_periods)
                        current_V0_sample = model._V[final_month].x

                model.dispose()
            except Exception:
                current_V0_sample = 1400.0

        if kpis_historicos:
            kpis_agregados = aggregate_kpis(kpis_historicos)
            print_kpis(kpis_agregados, "Histórico")

            try:
                plot_files = generate_historical_plots(
                    kpis_historicos,
                    all_years,
                    output_dir="resultados",
                    plot_name="evolucion_historica_lago"
                )
                print(f"📊 Gráficos: {len(plot_files)} PNG")
            except Exception as e:
                print(f"   ⚠️ Error generando gráficos: {e}")
        else:
            print("\n⚠️ No se pudieron calcular KPIs históricos detallados")

    performance_stats = get_performance_stats(start_time, process)
    print_performance_stats(performance_stats, "(simulación completa)")


def run(
    build_model_func: Callable,
    years_horizon: List[int],
    time_periods: List[int],
    conv_factor: float,
    model_name: str = "Modelo Embalse del Laja",
    default_v0: float = 1400.0
):
    """
    Interfaz principal unificada para ejecutar modelos del Embalse del Laja.

    Args:
        build_model_func: Función que construye el modelo.
            Debe aceptar: target_year (int), V0 (float)
            Debe retornar: modelo Gurobi con atributos _V, _x, _y
        years_horizon: [año_min, año_max] de datos disponibles
        time_periods: Lista de períodos de tiempo (ej: [12,1,2,...,11])
        conv_factor: Factor de conversión m³/s*mes -> Hm³
        model_name: Nombre descriptivo del modelo para el menú
        default_v0: Volumen inicial por defecto (Hm³)

    Example:
        >>> from model import build_model_for_one_year, YEARS_HORIZON, T, Conv
        >>> run(
        ...     build_model_func=build_model_for_one_year,
        ...     years_horizon=YEARS_HORIZON,
        ...     time_periods=T,
        ...     conv_factor=Conv,
        ...     model_name="Modelo Determinístico"
        ... )
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
