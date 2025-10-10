from typing import List, Optional, Dict, Any, Tuple
import pandas as pd
import numpy as np
import statistics
from gurobipy import GRB

from model import build_model_for_one_year, YEARS_HORIZON, INJ_CSV, A_inyeccion, T
from data_loader import _norm_central_for_inj, _parse_mm_yyyy, CENTRAL_TO_INJ_ARC

"""
Módulo de simulación Monte Carlo para el modelo Embalse del Laja.
Incluye simulación recursiva multi-año con bootstrap de afluentes.
"""


# =============================
# 🎲 MONTE CARLO BÁSICO
# =============================

def run_single_year_montecarlo(
    n_sims: int = 100,
    target_year: Optional[int] = None,
    seed: int = 42,
    V0: Optional[float] = None,
    silent: bool = False
) -> List[Tuple[int, int, Optional[float], Optional[float]]]:
    """
    Ejecuta Monte Carlo para un año específico con bootstrap mensual.

    Args:
        n_sims: Número de simulaciones
        target_year: Año objetivo (default: primer año de YEARS_HORIZON)
        seed: Semilla para reproducibilidad
        V0: Volumen inicial
        silent: Si suprimir mensajes de progreso

    Returns:
        Lista de tuplas (sim_id, status, obj_val, final_volume)
    """
    rng = np.random.default_rng(seed)
    if target_year is None:
        target_year = min(YEARS_HORIZON)

    if not silent:
        print(f"🎲 Monte Carlo: {n_sims} simulaciones para año {target_year}")

    # Cargar y preparar datos históricos
    months_pool = _prepare_monthly_pools(target_year)

    results = []
    if not silent:
        print("Progreso: ", end="", flush=True)

    for s in range(n_sims):
        if not silent and s % max(1, n_sims // 10) == 0:
            progress = int((s / n_sims) * 100)
            print(f"{progress}%", end=" ", flush=True)

        # Generar inyecciones aleatorias
        I_arc_sim = _generate_random_injections(months_pool, rng)

        # Construir y optimizar modelo
        try:
            m = build_model_for_one_year(
                target_year, V0=V0, I_arc_override=I_arc_sim
            )
            m.optimize()

            obj = m.ObjVal if m.Status == GRB.OPTIMAL else None

            # Extraer volumen final
            final_vol = None
            if m.Status == GRB.OPTIMAL:
                try:
                    V_final = m.getVarByName(f"V[{max(T)}]")
                    final_vol = V_final.x if V_final else None
                except Exception:
                    final_vol = None

            results.append((s, int(m.Status), obj, final_vol))

        except Exception as e:
            if not silent:
                print(f"\n⚠️ Error en sim {s}: {e}")
            results.append((s, -1, None, None))  # Status -1 para errores

    if not silent:
        print("100% ✅")

    return results


def run_multi_year_montecarlo(
    years: List[int],
    n_sims: int = 100,
    seed: int = 0,
    V0_initial: Optional[float] = None,
    volume_strategy: str = "deterministic"
) -> Dict[int, List[Tuple[int, int, Optional[float], Optional[float]]]]:
    """
    Ejecuta Monte Carlo recursivo para múltiples años.
    El volumen final de un año se usa como inicial del siguiente.

    Args:
        years: Lista de años a simular
        n_sims: Número de simulaciones por año
        seed: Semilla base para reproducibilidad
        V0_initial: Volumen inicial del primer año
        volume_strategy: Estrategia para volumen entre años:
            - "deterministic": usar volumen final promedio
            - "stochastic": usar volumen final de cada simulación
            - "percentile_X": usar percentil X del volumen final

    Returns:
        Dict con resultados por año
    """
    print(f"🎲 Monte Carlo multi-año: {len(years)} años, {n_sims} sims c/u")
    print(f"📅 Años: {min(years)}-{max(years)}")
    print(f"🔄 Estrategia volumen: {volume_strategy}")

    all_results = {}
    current_V0 = V0_initial

    for i, year in enumerate(sorted(years)):
        print(f"\n--- Año {year} ({i+1}/{len(years)}) ---")
        if current_V0:
            print(f"💧 V0 = {current_V0:.1f} Hm³")
        else:
            print("💧 V0 = Automático")

        # Usar semilla diferente para cada año pero reproducible
        year_seed = seed + year

        # Ejecutar simulaciones para el año actual
        year_results = run_single_year_montecarlo(
            n_sims=n_sims,
            target_year=year,
            seed=year_seed,
            V0=current_V0,
            silent=False
        )

        all_results[year] = year_results

        # Calcular volumen para el siguiente año
        if i < len(years) - 1:  # No es el último año
            current_V0 = _calculate_next_volume(
                year_results, volume_strategy
            )

            if current_V0 is None:
                print("⚠️ No se pudo calcular volumen para siguiente año")
                current_V0 = V0_initial

    return all_results


def _prepare_monthly_pools(target_year: int) -> Dict[Tuple, List[float]]:
    """Prepara pools mensuales de afluentes para bootstrap."""
    # Cargar histórico
    df = pd.read_csv(INJ_CSV)
    df = df.rename(columns={
        "central": "central",
        "fecha (mm-aaaa)": "fecha",
        "caudal (m^3/s)": "caudal_m3s"
    })

    # Construir pools mensuales para el año objetivo
    months_pool = {}
    for row in df.itertuples(index=False):
        cent_key = _norm_central_for_inj(row.central)
        try:
            month, year = _parse_mm_yyyy(row.fecha)
        except Exception:
            continue
        if year != target_year:
            continue
        if cent_key not in CENTRAL_TO_INJ_ARC:
            continue
        i, j = CENTRAL_TO_INJ_ARC[cent_key]
        months_pool.setdefault((i, j, month), []).append(float(row.caudal_m3s))

    # Asegurar pools mínimos
    for (i, j) in A_inyeccion:
        for t in T:
            months_pool.setdefault((i, j, t), [0.0])

    return months_pool


def _generate_random_injections(
    months_pool: Dict[Tuple, List[float]], 
    rng: np.random.Generator
) -> Dict[Tuple, float]:
    """Genera inyecciones aleatorias usando bootstrap."""
    I_arc_sim = {}
    for (i, j) in A_inyeccion:
        for t in T:
            pool = months_pool.get((i, j, t), [0.0])
            I_arc_sim[(i, j, t)] = float(rng.choice(pool))
    return I_arc_sim


def _calculate_next_volume(
    year_results: List[Tuple[int, int, Optional[float], Optional[float]]],
    strategy: str
) -> Optional[float]:
    """Calcula volumen inicial para el siguiente año."""
    # Extraer volúmenes finales válidos
    final_volumes = [
        r[3] for r in year_results 
        if r[1] == GRB.OPTIMAL and r[3] is not None
    ]

    if not final_volumes:
        return None

    if strategy == "deterministic":
        return statistics.mean(final_volumes)
    elif strategy == "stochastic":
        # Para implementación completa, necesitaríamos mantener
        # correspondencia entre simulaciones
        return statistics.mean(final_volumes)
    elif strategy.startswith("percentile_"):
        try:
            percentile = int(strategy.split("_")[1])
            return np.percentile(final_volumes, percentile)
        except Exception:
            return statistics.mean(final_volumes)
    else:
        return statistics.mean(final_volumes)


# =============================
# 📊 ANÁLISIS RESULTADOS MONTE CARLO
# =============================

def analyze_single_year_results(
    results: List[Tuple[int, int, Optional[float], Optional[float]]],
    year: int = None
) -> Dict[str, Any]:
    """Analiza resultados de Monte Carlo para un año."""
    statuses = [r[1] for r in results]
    objs = [r[2] for r in results if r[2] is not None]
    volumes = [r[3] for r in results if r[3] is not None]

    n_total = len(results)
    n_optimal = sum(1 for s in statuses if s == GRB.OPTIMAL)
    n_infeasible = sum(1 for s in statuses if s == GRB.INFEASIBLE)
    n_error = sum(1 for s in statuses if s == -1)

    analysis = {
        "year": year,
        "summary": {
            "n_simulations": n_total,
            "n_optimal": n_optimal,
            "n_infeasible": n_infeasible,
            "n_error": n_error,
            "success_rate": (n_optimal / n_total) * 100 if n_total > 0 else 0
        },
        "objective_stats": {},
        "volume_stats": {}
    }

    # Estadísticas de objetivo
    if objs:
        analysis["objective_stats"] = {
            "mean": statistics.mean(objs),
            "median": statistics.median(objs),
            "std": statistics.stdev(objs) if len(objs) > 1 else 0.0,
            "min": min(objs),
            "max": max(objs),
            "percentiles": {
                "P5": np.percentile(objs, 5),
                "P25": np.percentile(objs, 25),
                "P75": np.percentile(objs, 75),
                "P95": np.percentile(objs, 95)
            }
        }

    # Estadísticas de volumen final
    if volumes:
        analysis["volume_stats"] = {
            "mean": statistics.mean(volumes),
            "median": statistics.median(volumes),
            "std": statistics.stdev(volumes) if len(volumes) > 1 else 0.0,
            "min": min(volumes),
            "max": max(volumes)
        }

    return analysis


def analyze_multi_year_results(
    all_results: Dict[int, List[Tuple[int, int, Optional[float], Optional[float]]]]
) -> Dict[str, Any]:
    """Analiza resultados de Monte Carlo multi-año."""
    print("\n🎲 === ANÁLISIS MONTE CARLO MULTI-AÑO ===")
    
    years = sorted(all_results.keys())
    yearly_analyses = {}
    
    # Analizar cada año individualmente
    for year in years:
        yearly_analyses[year] = analyze_single_year_results(all_results[year], year)
    
    # Estadísticas agregadas
    all_success_rates = [
        a["summary"]["success_rate"] for a in yearly_analyses.values()
    ]
    
    all_objectives = []
    all_volumes = []
    
    for year_results in all_results.values():
        year_objs = [r[2] for r in year_results if r[2] is not None]
        year_vols = [r[3] for r in year_results if r[3] is not None]
        all_objectives.extend(year_objs)
        all_volumes.extend(year_vols)
    
    # Crear análisis agregado
    aggregated = {
        "period": [min(years), max(years)],
        "n_years": len(years),
        "overall_stats": {
            "avg_success_rate": statistics.mean(all_success_rates),
            "min_success_rate": min(all_success_rates),
            "max_success_rate": max(all_success_rates)
        },
        "total_energy_stats": {},
        "volume_evolution": {}
    }
    
    if all_objectives:
        aggregated["total_energy_stats"] = {
            "total_mean": statistics.mean(all_objectives) * len(years),
            "yearly_mean": statistics.mean(all_objectives),
            "overall_std": statistics.stdev(all_objectives) if len(all_objectives) > 1 else 0.0
        }
    
    # Evolución de volúmenes
    if len(years) > 1:
        volume_evolution = []
        for year in years:
            year_analysis = yearly_analyses[year]
            if year_analysis["volume_stats"]:
                volume_evolution.append(year_analysis["volume_stats"]["mean"])
        
        if len(volume_evolution) > 1:
            # Tendencia de volúmenes
            x = np.arange(len(volume_evolution))
            y = np.array(volume_evolution)
            slope = np.polyfit(x, y, 1)[0]
            
            aggregated["volume_evolution"] = {
                "yearly_means": volume_evolution,
                "trend_slope": slope,
                "trend_direction": "creciente" if slope > 0 else "decreciente" if slope < 0 else "estable"
            }
    
    # Imprimir resumen
    print(f"📅 Período: {aggregated['period'][0]}-{aggregated['period'][1]} ({aggregated['n_years']} años)")
    print(f"✅ Tasa éxito promedio: {aggregated['overall_stats']['avg_success_rate']:.1f}%")
    
    if aggregated["total_energy_stats"]:
        total_stats = aggregated["total_energy_stats"]
        print(f"⚡ Energía promedio anual: {total_stats['yearly_mean']:,.1f} MWh")
        print(f"⚡ Energía total promedio: {total_stats['total_mean']:,.1f} MWh")
    
    if aggregated.get("volume_evolution", {}).get("trend_direction"):
        vol_evo = aggregated["volume_evolution"] 
        print(f"💧 Tendencia volúmenes: {vol_evo['trend_direction']} ({vol_evo['trend_slope']:.1f} Hm³/año)")
    
    # Imprimir detalles por año
    print(f"\n📊 DETALLES POR AÑO:")
    for year in years:
        analysis = yearly_analyses[year]
        success = analysis["summary"]["success_rate"]
        
        if analysis["objective_stats"]:
            obj_mean = analysis["objective_stats"]["mean"]
            print(f"   {year}: {success:5.1f}% éxito, {obj_mean:7,.0f} MWh promedio")
        else:
            print(f"   {year}: {success:5.1f}% éxito, sin objetivos válidos")
    
    return {
        "yearly_analyses": yearly_analyses,
        "aggregated": aggregated
    }


# =============================
# 🎯 FUNCIONES ESPECIALIZADAS
# =============================

def run_stress_test(
    base_year: int,
    n_sims: int = 1000,
    stress_factors: Dict[str, float] = None,
    seed: int = 0
) -> Dict[str, Any]:
    """
    Ejecuta prueba de estrés con factores de reducción de afluentes.
    
    Args:
        base_year: Año base para la prueba
        n_sims: Número de simulaciones
        stress_factors: Dict con factores de reducción por tipo de afluente
        seed: Semilla para reproducibilidad
    
    Returns:
        Dict con resultados de la prueba de estrés
    """
    if stress_factors is None:
        stress_factors = {"all": 0.8}  # Reducir todos los afluentes 20%
    
    print(f"🔥 Prueba de estrés año {base_year}")
    print(f"📉 Factores de estrés: {stress_factors}")
    
    # Preparar pools estresados
    months_pool = _prepare_monthly_pools(base_year)
    
    # Aplicar factores de estrés
    stressed_pool = {}
    for key, values in months_pool.items():
        i, j, t = key
        factor = stress_factors.get("all", 1.0)  # Factor por defecto
        
        # Aplicar factor específico si existe
        for stress_key, stress_factor in stress_factors.items():
            if stress_key in i.lower() or stress_key in j.lower():
                factor = stress_factor
                break
        
        stressed_pool[key] = [v * factor for v in values]
    
    # Ejecutar simulaciones con pools estresados
    rng = np.random.default_rng(seed)
    results = []
    
    print("Ejecutando simulaciones estresadas...")
    for s in range(n_sims):
        I_arc_sim = _generate_random_injections(stressed_pool, rng)
        
        try:
            m = build_model_for_one_year(base_year, I_arc_override=I_arc_sim)
            m.optimize()
            
            obj = m.ObjVal if m.Status == GRB.OPTIMAL else None
            results.append((s, int(m.Status), obj, None))
            
        except Exception:
            results.append((s, -1, None, None))
    
    # Analizar resultados
    analysis = analyze_single_year_results(results, base_year)
    analysis["stress_factors"] = stress_factors
    
    print(f"🔥 Resultados prueba de estrés:")
    print(f"   Tasa éxito: {analysis['summary']['success_rate']:.1f}%")
    if analysis["objective_stats"]:
        print(f"   Energía promedio: {analysis['objective_stats']['mean']:,.1f} MWh")
    
    return analysis