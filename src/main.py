from typing import List, Optional, Dict, Any
import argparse
import sys
import os
import csv
import matplotlib.pyplot as plt
from gurobipy import GRB

# Importar módulos del proyecto
try:
    # Imports relativos (cuando se ejecuta como módulo: python -m src.main)
    from .model import build_model_for_one_year
    from .data_loader import T
    from .filt_cota import cota_from_volumen
    from .sensitivity_analysis import (
        run_sensitivity_analysis,
        analyze_sensitivity_results,
        calculate_yearly_kpis
    )
    from .montecarlo_simulation import (
        run_single_year_montecarlo,
        run_multi_year_montecarlo
    )
    from .utils import print_summary_from_kpis
    from .config import YEARS_HORIZON, DEFAULT_V0, DEFAULT_N_SIMS, DEFAULT_SEED
except ImportError:
    # Imports absolutos (cuando se ejecuta directamente: python src/main.py)
    from model import build_model_for_one_year
    from data_loader import T
    from filt_cota import cota_from_volumen
    from sensitivity_analysis import (
        run_sensitivity_analysis,
        analyze_sensitivity_results,
        calculate_yearly_kpis
    )
    from montecarlo_simulation import (
        run_single_year_montecarlo,
        run_multi_year_montecarlo
    )
    from utils import print_summary_from_kpis
    from config import YEARS_HORIZON, DEFAULT_V0, DEFAULT_N_SIMS, DEFAULT_SEED

"""
Entry point CLI modularizado para el modelo Embalse del Laja.
Control principal que coordina todos los módulos especializados.

Usage examples:
  python src/main.py --years 1960 1961 1962 --v0 1200
  python -m src.main --montecarlo --year 1960 --n-sims 100
  python src/main.py --best-year --years 1960 1961 1962 --v0 2500  
  python src/main.py --sensitivity --param V0 --values 800,900,1000
"""

# Configurar path para imports - agregar directorio src
_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)


# =============================
# 🚀 FUNCIONES DE EJECUCIÓN PRINCIPAL
# =============================

def run_years(years_horizon: List[int],
              V0: Optional[float] = None,
              time_limit: Optional[float] = None) -> Dict[int, Dict[str, Any]]:
    """
    Ejecuta optimización determinística para un rango de años.
    
    Args:
        years_horizon: Lista de años a optimizar
        V0: Volumen inicial opcional
        time_limit: Límite de tiempo por optimización
    
    Returns:
        Dict con resultados por año
    """
    y_min, y_max = min(years_horizon), max(years_horizon)
    total_years = y_max - y_min + 1

    print("\n🌊 === MODELO EMBALSE DEL LAJA ===")
    print(f"📅 Optimizando años: {y_min}-{y_max} ({total_years} años)")
    print(f"💧 Volumen inicial: {V0 if V0 else 'Automático'}")
    if time_limit:
        print(f"⏱️  Límite tiempo: {time_limit}s por año")
    print()

    results = {}
    optimal_count = 0

    for i, y in enumerate(range(y_min, y_max + 1), 1):
        print(f"⚙️  Construyendo modelo año {y} ({i}/{total_years})...")
        m = build_model_for_one_year(y, V0=V0)

        if time_limit:
            m.Params.TimeLimit = float(time_limit)

        print(f"🔍 Optimizando año {y}...")
        m.optimize()

        if m.Status == GRB.INFEASIBLE:
            print(f"❌ Año {y}: INFACTIBLE - generando diagnóstico")
            m.computeIIS()
            m.write(f"infeasible_{y}.ilp")
        elif m.Status == GRB.OPTIMAL:
            optimal_count += 1
            print(f"✅ Año {y}: ÓPTIMO - {m.ObjVal:.1f} MWh")
        else:
            print(f"⚠️  Año {y}: Status {m.Status}")

        obj_mwh = m.ObjVal if m.Status == GRB.OPTIMAL else None
        gap = m.MIPGap if hasattr(m, 'MIPGap') else None
        
        results[y] = {
            "status": m.Status,
            "obj_MWh": obj_mwh,
            "gap": gap,
            "model": m  # Guardamos el modelo para análisis posterior
        }
        
        # Exportar resultados si es óptimo
        if m.Status == GRB.OPTIMAL:
            export_results(m, y)

    # Calcular y mostrar KPIs usando módulo especializado
    kpis = calculate_yearly_kpis(results)
    print_summary_from_kpis(kpis)
    
    return results


def export_results(model, year: int):
    """Exporta resultados de un modelo óptimo a archivos CSV y PNG."""
    try:
        os.makedirs("results", exist_ok=True)
        
        # Extraer volúmenes y cotas
        V_vars = [model.getVarByName(f"V[{t}]") for t in T]
        vols = [v.x for v in V_vars]
        cotas = [cota_from_volumen(v) for v in vols]

        # Guardar cotas mensuales
        csv_path = os.path.join("results", f"cota_{year}.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["mes"] + [f"mes{t}" for t in T])
            writer.writerow(["cota_m"] + [f"{c:.3f}" for c in cotas])

        # Gráfico de cotas
        png_path = os.path.join("results", f"cota_{year}.png")
        plt.figure(figsize=(10, 4))
        plt.plot(T, cotas, marker="o")
        plt.xticks(T)
        plt.xlabel("Mes (1..12)")
        plt.ylabel("Cota (m)")
        plt.title(f"Cota mensual - año {year}")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(png_path, dpi=150)
        plt.close()
        
        print(f"📈 Guardado cota mensual en: {csv_path}, {png_path}")
        
        # Exportar flujos detallados
        export_flows(model, year)
        
    except Exception as e:
        print(f"⚠️ Error guardando resultados para {year}: {e}")


def export_flows(model, year: int):
    """Exporta flujos por arco y resumen por central."""
    try:
        flows_path = os.path.join("results", f"flows_{year}.csv")
        summary_path = os.path.join("results", f"summary_central_{year}.csv")

        y_vars = model._y
        x_vars = model._x
        eta = model._meta["eta"]
        Conv = model._meta["Conv"]
        A_gen = set(model._meta["A_generacion"])
        ARCS = model._meta["ARCS"]

        # Flujos detallados por arco
        with open(flows_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["i", "j", "mes", "caudal_m3s", "vol_Hm3", "energia_MWh"])
            
            for (i, j) in ARCS:
                for t in T:
                    caudal = 0.0
                    if (i, j) in A_gen and (i, j, t) in x_vars:
                        caudal = x_vars[(i, j, t)].x
                    elif (i, j, t) in y_vars:
                        caudal = y_vars[(i, j, t)].x

                    vol_hm3 = caudal * Conv
                    energy = eta.get((i, j), 0.0) * caudal if (i, j) in A_gen else 0.0
                    
                    writer.writerow([i, j, t, f"{caudal:.6f}", f"{vol_hm3:.6f}", f"{energy:.6f}"])

        # Resumen por central desde Embalse
        embalse_out = [j for (i, j) in ARCS if i == "Embalse"]
        
        with open(summary_path, "w", newline="") as f:
            writer = csv.writer(f)
            header = (["central"] + [f"vol_mes{t}_Hm3" for t in T] + 
                     [f"eng_mes{t}_MWh" for t in T] + ["total_vol_Hm3", "total_eng_MWh"])
            writer.writerow(header)
            
            for j in embalse_out:
                vols_mes = []
                eng_mes = []
                total_vol = 0.0
                total_eng = 0.0
                
                for t in T:
                    caud = 0.0
                    if ("Embalse", j, t) in x_vars:
                        caud = x_vars[("Embalse", j, t)].x
                    elif ("Embalse", j, t) in y_vars:
                        caud = y_vars[("Embalse", j, t)].x
                    
                    vol = caud * Conv
                    eng = eta.get(("Embalse", j), 0.0) * caud

                    vols_mes.append(f"{vol:.6f}")
                    eng_mes.append(f"{eng:.6f}")
                    total_vol += vol
                    total_eng += eng

                row = ([j] + vols_mes + eng_mes + 
                      [f"{total_vol:.6f}", f"{total_eng:.6f}"])
                writer.writerow(row)

        print(f"💾 Guardados flows & summary en: {flows_path}, {summary_path}")

    except Exception as e:
        print(f"⚠️ Error guardando flows/summary para {year}: {e}")


def print_summary(results: Dict[int, Dict], optimal_count: int, total_years: int):
    """Imprime resumen final de la optimización."""
    print()
    print("🎯 === RESUMEN OPTIMIZACIÓN ===")
    print(f"✅ Soluciones óptimas: {optimal_count}/{total_years}")

    if optimal_count > 0:
        total_energy = sum(r["obj_MWh"] for r in results.values() 
                          if r["obj_MWh"] is not None)
        avg_energy = total_energy / optimal_count
        print(f"⚡ Energía total: {total_energy:,.0f} MWh")
        print(f"📊 Promedio anual: {avg_energy:,.0f} MWh")

        # Estadísticas de gap
        gaps = [r["gap"] for r in results.values() if r["gap"] is not None]
        if gaps:
            import statistics
            print(f"🎯 Gap promedio: {statistics.mean(gaps)*100:.2f}%")
    print()


# =============================
# 🎲 MONTE CARLO - USANDO MÓDULO ESPECIALIZADO
# =============================
# Las funciones de Monte Carlo ahora están en montecarlo_simulation.py

# =============================
# 🔍 ANÁLISIS DE SENSIBILIDAD - USANDO MÓDULO ESPECIALIZADO
# =============================
# Las funciones de análisis de sensibilidad ahora están en sensitivity_analysis.py
# =============================
# 🏆 SELECCIÓN MEJOR AÑO - USANDO FUNCIONES AUXILIARES
# =============================

def pick_best_year(years: List[int], V0: Optional[float] = None, 
                   time_limit: Optional[float] = None) -> Optional[int]:
    """
    Evalúa múltiples años y selecciona el mejor usando run_years existente.

    Args:
        years: Lista de años a evaluar
        V0: Volumen inicial
        time_limit: Límite de tiempo por optimización

    Returns:
        Mejor año encontrado o None
    """
    print(f"🏆 Buscando mejor año entre: {years}")
    
    # Usar función existente para optimizar todos los años
    results = run_years(years, V0=V0, time_limit=time_limit)
    
    # Encontrar el año con mayor generación
    best_year = None
    best_obj = None
    
    for year, result in results.items():
        if result.get("status") == GRB.OPTIMAL:
            obj = result.get("obj_MWh")
            if obj and (best_obj is None or obj > best_obj):
                best_obj = obj
                best_year = year
    
    if best_year:
        print(f"\n🏆 Mejor año: {best_year} ({best_obj:.1f} MWh)")
    else:
        print("\n❌ No se encontró año óptimo")
    
    return best_year


# =============================
# 🖥️  CLI
# =============================

def parse_args():
    """Configuración de argumentos CLI usando módulos especializados."""
    p = argparse.ArgumentParser(
        description="CLI para modelo de optimización Embalse del Laja",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  # Optimización determinística básica
  python main.py --years 2010 2011 2012 --v0 1200

  # Monte Carlo un año
  python main.py --montecarlo --year 2015 --n-sims 100 --seed 42

  # Monte Carlo multi-año
  python main.py --montecarlo --year 2015 --multi-year --n-years 5 --n-sims 50

  # Análisis de sensibilidad
  python main.py --sensitivity --param V0 --values 800 900 1000 1100 1200

  # Encontrar mejor año
  python main.py --best-year --years 2010 2015 2020
        """
    )

    # Argumentos generales
    p.add_argument('--v0', type=float, default=DEFAULT_V0, 
                   help=f'Volumen inicial V0 en Hm³ (default: {DEFAULT_V0})')
    p.add_argument('--time-limit', type=float, default=None, 
                   help='Límite tiempo por optimización en segundos')

    # Modos de ejecución (mutuamente excluyentes)
    modes = p.add_mutually_exclusive_group()
    modes.add_argument('--montecarlo', action='store_true', 
                       help='Ejecutar simulación Monte Carlo')
    modes.add_argument('--best-year', action='store_true', 
                       help='Encontrar mejor año entre opciones')
    modes.add_argument('--sensitivity', action='store_true', 
                       help='Ejecutar análisis de sensibilidad')

    # Parámetros Monte Carlo
    mc_group = p.add_argument_group('Monte Carlo', 'Parámetros para simulación estocástica')
    mc_group.add_argument('--n-sims', type=int, default=DEFAULT_N_SIMS, 
                          help=f'Número de simulaciones (default: {DEFAULT_N_SIMS})')
    mc_group.add_argument('--year', type=int, default=None, 
                          help='Año base para Monte Carlo (default: primer año disponible)')
    mc_group.add_argument('--seed', type=int, default=DEFAULT_SEED, 
                          help=f'Semilla para reproducibilidad (default: {DEFAULT_SEED})')
    mc_group.add_argument('--multi-year', action='store_true',
                          help='Simulación multi-año con volúmenes recursivos')
    mc_group.add_argument('--n-years', type=int, default=5,
                          help='Número de años para simulación multi-año (default: 5)')

    # Parámetros selección de años
    years_group = p.add_argument_group('Años', 'Selección de años para optimizar')
    years_group.add_argument('--years', type=int, nargs='+', default=None, 
                             help='Lista de años específicos (ej: --years 2010 2015 2020)')

    # Parámetros análisis de sensibilidad
    sens_group = p.add_argument_group('Sensibilidad', 'Parámetros para análisis de sensibilidad')
    sens_group.add_argument('--param', type=str, default='V0', 
                            choices=['V0', 'factor_segundos', 'factor_primeros'],
                            help='Parámetro a analizar (default: V0)')
    sens_group.add_argument('--values', type=str, default=None,
                            help='Valores separados por comas (ej: --values 800,900,1000)')

    # Opciones avanzadas
    adv_group = p.add_argument_group('Avanzado', 'Opciones de configuración avanzada')
    adv_group.add_argument('--stress-test', action='store_true',
                           help='Activar modo de prueba de estrés con parámetros extremos')
    adv_group.add_argument('--export-detailed', action='store_true',
                           help='Exportar resultados detallados adicionales')

    # Procesar argumentos
    args = p.parse_args()
    
    # Post-procesamiento de argumentos
    if args.values and isinstance(args.values, str):
        # Convertir string separado por comas a lista de floats
        args.values = [float(x.strip()) for x in args.values.split(',')]
    
    if not args.year:
        args.year = min(YEARS_HORIZON)
    
    return args


def main():
    """Función principal que coordina la ejecución según argumentos CLI."""
    args = parse_args()

    if args.montecarlo:
        print(f"🎲 Ejecutando Monte Carlo usando módulo especializado...")
        print(f"   Simulaciones: {args.n_sims}")
        print(f"   Año base: {args.year}")
        print(f"   Semilla: {args.seed}")
        print(f"   V0: {args.v0}")
        
        # Usar módulo Monte Carlo especializado
        if hasattr(args, 'multi_year') and args.multi_year:
            # Simulación multi-año
            results = run_multi_year_montecarlo(
                start_year=args.year,
                n_years=getattr(args, 'n_years', 5),
                n_iterations=args.n_sims,
                V0=args.v0,
                seed=args.seed
            )
        else:
            # Simulación un año
            results = run_single_year_montecarlo(
                target_year=args.year,
                n_iterations=args.n_sims,
                V0=args.v0,
                seed=args.seed
            )
        
        print("✅ Simulación Monte Carlo completada")

    elif args.best_year:
        years = args.years if args.years else YEARS_HORIZON[:5]
        print(f"🏆 Buscando mejor año entre: {years}")
        best_year = pick_best_year(years, V0=args.v0, time_limit=args.time_limit)
        
        if best_year:
            print(f"🎯 Año recomendado: {best_year}")
        else:
            print("❌ No se pudo determinar el mejor año")

    elif args.sensitivity:
        if not hasattr(args, 'param') or not hasattr(args, 'values'):
            print("❌ Se requieren --param y --values para análisis de sensibilidad")
            print("   Ejemplo: --param V0 --values 800,900,1000,1100,1200")
            return
            
        print(f"🔍 Ejecutando análisis de sensibilidad usando módulo especializado...")
        
        # Usar módulo de análisis de sensibilidad
        results = run_sensitivity_analysis(
            parameter=args.param,
            param_values=args.values,
            base_year=args.year or min(YEARS_HORIZON),
            V0=args.v0 if args.param != 'V0' else None
        )
        
        # Analizar resultados
        analyze_sensitivity_results(results, args.param)
        print("✅ Análisis de sensibilidad completado")

    else:
        # Ejecución estándar determinística
        years = args.years if args.years else YEARS_HORIZON[:10]  # Limitar por defecto
        print(f"🚀 Ejecutando optimización determinística estándar")
        print(f"   Años: {len(years)} ({min(years)}-{max(years)})")
        print(f"   V0: {args.v0 or DEFAULT_V0} Hm³")
        
        results = run_years(years, V0=args.v0, time_limit=args.time_limit)
        print("✅ Optimización determinística completada")


if __name__ == '__main__':
    main()
