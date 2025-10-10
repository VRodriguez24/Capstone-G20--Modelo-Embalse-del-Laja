"""
Módulo de análisis de sensibilidad y KPIs para el modelo Embalse del Laja.
Incluye funciones para análisis paramétrico, estadísticas y métricas de desempeño.
"""

from typing import List, Optional, Dict, Any, Tuple
import statistics
import numpy as np
from gurobipy import GRB

from model import build_model_for_one_year, YEARS_HORIZON


# =============================
# 🔍 ANÁLISIS DE SENSIBILIDAD
# =============================

def run_sensitivity_analysis(
    parameter: str, 
    values: List[float], 
    base_year: int = None,
    time_limit: Optional[float] = None
) -> Dict[float, Dict]:
    """
    Análisis de sensibilidad para un parámetro específico.
    
    Args:
        parameter: Nombre del parámetro ('V0', 'M', 'TUCAPEL_MIN', etc.)
        values: Lista de valores a probar
        base_year: Año base para el análisis
        time_limit: Límite de tiempo por optimización (segundos)
    
    Returns:
        Dict con resultados por valor del parámetro
    """
    if base_year is None:
        base_year = min(YEARS_HORIZON)
    
    print(f"🔍 Análisis de sensibilidad para {parameter}")
    print(f"   Valores: {values}")
    print(f"   Año base: {base_year}\n")
    
    results = {}
    
    for i, val in enumerate(values, 1):
        print(f"⚙️  Probando {parameter}={val} ({i}/{len(values)})...")
        
        # Construir modelo con parámetro modificado
        try:
            if parameter == 'V0':
                m = build_model_for_one_year(base_year, V0=val)
            else:
                # Para otros parámetros, necesitaríamos modificar la función
                # del modelo o crear variantes específicas
                print(f"⚠️  Parámetro {parameter} no implementado aún")
                continue
                
            if time_limit is not None:
                m.Params.TimeLimit = float(time_limit)
                
            m.optimize()
            
            obj = m.ObjVal if m.Status == GRB.OPTIMAL else None
            gap = m.MIPGap if hasattr(m, 'MIPGap') else None
            solve_time = m.Runtime if hasattr(m, 'Runtime') else None
            
            results[val] = {
                "status": m.Status,
                "obj_MWh": obj,
                "gap": gap,
                "solve_time": solve_time,
                "model": m if m.Status == GRB.OPTIMAL else None
            }
            
            status_str = "ÓPTIMO" if m.Status == GRB.OPTIMAL else f"Status {m.Status}"
            obj_str = f"{obj:.1f} MWh" if obj else "N/A"
            gap_str = f"(Gap: {gap*100:.2f}%)" if gap else ""
            print(f"   Resultado: {status_str} - {obj_str} {gap_str}")
            
        except Exception as e:
            print(f"   ❌ Error: {e}")
            results[val] = {
                "status": "ERROR",
                "obj_MWh": None,
                "gap": None,
                "solve_time": None,
                "model": None,
                "error": str(e)
            }
    
    return results


def analyze_sensitivity_results(parameter: str, results: Dict[float, Dict]) -> Dict[str, Any]:
    """
    Analiza resultados de sensibilidad y calcula KPIs.
    
    Args:
        parameter: Nombre del parámetro analizado
        results: Resultados del análisis de sensibilidad
    
    Returns:
        Dict con estadísticas y KPIs del análisis
    """
    print(f"\n🔍 === ANÁLISIS SENSIBILIDAD {parameter.upper()} ===")
    
    optimal_results = {k: v for k, v in results.items() 
                      if v["status"] == GRB.OPTIMAL}
    
    if not optimal_results:
        print("❌ No hay resultados óptimos para analizar")
        return {"error": "No optimal results"}
    
    # Extraer valores para análisis
    param_values = list(optimal_results.keys())
    objectives = [v["obj_MWh"] for v in optimal_results.values()]
    gaps = [v["gap"] for v in optimal_results.values() if v["gap"] is not None]
    solve_times = [v["solve_time"] for v in optimal_results.values() if v["solve_time"] is not None]
    
    # Encontrar mejor y peor caso
    best_val = max(optimal_results.keys(), 
                   key=lambda k: optimal_results[k]["obj_MWh"])
    worst_val = min(optimal_results.keys(), 
                    key=lambda k: optimal_results[k]["obj_MWh"])
    
    best_obj = optimal_results[best_val]["obj_MWh"]
    worst_obj = optimal_results[worst_val]["obj_MWh"]
    
    # Calcular estadísticas
    obj_mean = statistics.mean(objectives)
    obj_std = statistics.stdev(objectives) if len(objectives) > 1 else 0.0
    obj_range = best_obj - worst_obj
    obj_cv = (obj_std / obj_mean) * 100 if obj_mean != 0 else 0.0  # Coeficiente de variación
    
    # Análisis de sensibilidad (elasticidad)
    param_range = max(param_values) - min(param_values)
    param_mean = statistics.mean(param_values)
    
    elasticity = 0.0
    if param_range != 0 and param_mean != 0 and obj_mean != 0:
        # Elasticidad aproximada: (ΔObj/Obj_mean) / (ΔParam/Param_mean)
        elasticity = (obj_range / obj_mean) / (param_range / param_mean)
    
    # Crear resumen de KPIs
    kpis = {
        "parameter": parameter,
        "n_cases": len(optimal_results),
        "best_case": {"value": best_val, "objective": best_obj},
        "worst_case": {"value": worst_val, "objective": worst_obj},
        "objective_stats": {
            "mean": obj_mean,
            "std": obj_std,
            "min": worst_obj,
            "max": best_obj,
            "range": obj_range,
            "cv_percent": obj_cv
        },
        "parameter_stats": {
            "values": param_values,
            "min": min(param_values),
            "max": max(param_values),
            "mean": param_mean,
            "range": param_range
        },
        "sensitivity_metrics": {
            "elasticity": elasticity,
            "relative_impact": (obj_range / obj_mean) * 100 if obj_mean != 0 else 0.0
        },
        "performance_stats": {
            "avg_gap": statistics.mean(gaps) * 100 if gaps else None,
            "avg_solve_time": statistics.mean(solve_times) if solve_times else None
        }
    }
    
    # Imprimir resumen
    print(f"🏆 Mejor caso: {parameter}={best_val} → {best_obj:.1f} MWh")
    print(f"📉 Peor caso: {parameter}={worst_val} → {worst_obj:.1f} MWh")
    print(f"📊 Rango: {obj_range:.1f} MWh ({(obj_range/worst_obj)*100:.1f}%)")
    print(f"📈 Objetivo promedio: {obj_mean:.1f} ± {obj_std:.1f} MWh")
    print(f"🎯 Coef. variación: {obj_cv:.2f}%")
    print(f"⚡ Elasticidad: {elasticity:.3f}")
    
    if gaps:
        print(f"🎯 Gap promedio: {statistics.mean(gaps)*100:.2f}%")
    if solve_times:
        print(f"⏱️  Tiempo promedio: {statistics.mean(solve_times):.2f}s")
    
    return kpis


def run_multi_parameter_sensitivity(
    parameters: List[str],
    values_dict: Dict[str, List[float]],
    base_year: int = None
) -> Dict[str, Dict]:
    """
    Ejecuta análisis de sensibilidad para múltiples parámetros.
    
    Args:
        parameters: Lista de nombres de parámetros
        values_dict: Dict con valores para cada parámetro
        base_year: Año base para el análisis
    
    Returns:
        Dict con resultados para cada parámetro
    """
    print(f"🔍 Análisis multi-paramétrico para: {parameters}")
    
    all_results = {}
    
    for param in parameters:
        if param not in values_dict:
            print(f"⚠️  No hay valores definidos para {param}")
            continue
            
        print(f"\n--- Analizando {param} ---")
        param_results = run_sensitivity_analysis(param, values_dict[param], base_year)
        all_results[param] = analyze_sensitivity_results(param, param_results)
    
    # Comparación entre parámetros
    print(f"\n🏆 === COMPARACIÓN MULTI-PARAMÉTRICA ===")
    
    for param, kpis in all_results.items():
        if "error" not in kpis:
            impact = kpis["sensitivity_metrics"]["relative_impact"]
            elasticity = kpis["sensitivity_metrics"]["elasticity"]
            print(f"{param:15}: Impacto={impact:6.2f}%, Elasticidad={elasticity:7.3f}")
    
    return all_results


# =============================
# 📊 KPIs Y MÉTRICAS
# =============================

def calculate_yearly_kpis(results: Dict[int, Dict]) -> Dict[str, Any]:
    """
    Calcula KPIs agregados para resultados anuales.
    
    Args:
        results: Dict con resultados por año
    
    Returns:
        Dict con KPIs calculados
    """
    optimal_results = {k: v for k, v in results.items() 
                      if v.get("status") == GRB.OPTIMAL}
    
    if not optimal_results:
        return {"error": "No optimal results"}
    
    # Extraer métricas
    years = list(optimal_results.keys())
    objectives = [v["obj_MWh"] for v in optimal_results.values()]
    gaps = [v["gap"] for v in optimal_results.values() if v.get("gap") is not None]
    
    # Estadísticas básicas
    n_years = len(optimal_results)
    n_total = len(results)
    success_rate = (n_years / n_total) * 100
    
    obj_stats = {
        "mean": statistics.mean(objectives),
        "median": statistics.median(objectives),
        "std": statistics.stdev(objectives) if len(objectives) > 1 else 0.0,
        "min": min(objectives),
        "max": max(objectives),
        "total": sum(objectives)
    }
    
    # Percentiles
    percentiles = {}
    if objectives:
        for p in [5, 25, 75, 95]:
            percentiles[f"P{p}"] = np.percentile(objectives, p)
    
    # Tendencia temporal (si hay suficientes datos)
    trend = None
    if len(years) > 2:
        # Regresión lineal simple: y = ax + b
        x = np.array(years)
        y = np.array(objectives)
        n = len(x)
        
        x_mean = np.mean(x)
        y_mean = np.mean(y)
        
        numerator = np.sum((x - x_mean) * (y - y_mean))
        denominator = np.sum((x - x_mean) ** 2)
        
        if denominator != 0:
            slope = numerator / denominator
            intercept = y_mean - slope * x_mean
            
            # R-squared
            y_pred = slope * x + intercept
            ss_res = np.sum((y - y_pred) ** 2)
            ss_tot = np.sum((y - y_mean) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
            
            trend = {
                "slope": slope,
                "intercept": intercept,
                "r_squared": r_squared,
                "direction": "creciente" if slope > 0 else "decreciente" if slope < 0 else "estable"
            }
    
    kpis = {
        "summary": {
            "n_optimal": n_years,
            "n_total": n_total,
            "success_rate": success_rate,
            "year_range": [min(years), max(years)] if years else None
        },
        "objective_stats": obj_stats,
        "percentiles": percentiles,
        "performance": {
            "avg_gap": statistics.mean(gaps) * 100 if gaps else None,
            "gap_std": statistics.stdev(gaps) * 100 if len(gaps) > 1 else None
        },
        "trend_analysis": trend
    }
    
    return kpis


def print_yearly_kpis(kpis: Dict[str, Any]):
    """Imprime KPIs anuales de forma estructurada."""
    if "error" in kpis:
        print(f"❌ {kpis['error']}")
        return
    
    summary = kpis["summary"]
    obj_stats = kpis["objective_stats"]
    percentiles = kpis["percentiles"]
    
    print("\n📊 === KPIs ANUALES ===")
    print(f"✅ Éxito: {summary['n_optimal']}/{summary['n_total']} años ({summary['success_rate']:.1f}%)")
    print(f"📅 Período: {summary['year_range'][0]}-{summary['year_range'][1]}")
    
    print(f"\n⚡ ENERGÍA (MWh):")
    print(f"   Total: {obj_stats['total']:,.0f}")
    print(f"   Media: {obj_stats['mean']:,.1f}")
    print(f"   Mediana: {obj_stats['median']:,.1f}")
    print(f"   Desv.Est: {obj_stats['std']:,.1f}")
    print(f"   Rango: [{obj_stats['min']:,.0f}, {obj_stats['max']:,.0f}]")
    
    if percentiles:
        print(f"\n📈 PERCENTILES:")
        for p, val in percentiles.items():
            print(f"   {p}: {val:,.1f} MWh")
    
    if kpis["performance"]["avg_gap"]:
        print(f"\n🎯 DESEMPEÑO:")
        print(f"   Gap promedio: {kpis['performance']['avg_gap']:.2f}%")
    
    if kpis["trend_analysis"]:
        trend = kpis["trend_analysis"]
        print(f"\n📈 TENDENCIA TEMPORAL:")
        print(f"   Dirección: {trend['direction']}")
        print(f"   Pendiente: {trend['slope']:.2f} MWh/año")
        print(f"   R²: {trend['r_squared']:.3f}")


def compare_scenarios(scenarios: Dict[str, Dict[int, Dict]], 
                     scenario_names: List[str] = None) -> Dict[str, Any]:
    """
    Compara múltiples escenarios y calcula KPIs comparativos.
    
    Args:
        scenarios: Dict con resultados por escenario
        scenario_names: Nombres descriptivos para los escenarios
    
    Returns:
        Dict con comparación de KPIs
    """
    if scenario_names is None:
        scenario_names = list(scenarios.keys())
    
    print("\n🔄 === COMPARACIÓN DE ESCENARIOS ===")
    
    scenario_kpis = {}
    
    # Calcular KPIs para cada escenario
    for name, results in scenarios.items():
        scenario_kpis[name] = calculate_yearly_kpis(results)
    
    # Comparación directa
    comparison = {}
    
    for name, kpis in scenario_kpis.items():
        if "error" not in kpis:
            comparison[name] = {
                "energia_media": kpis["objective_stats"]["mean"],
                "energia_total": kpis["objective_stats"]["total"],
                "tasa_exito": kpis["summary"]["success_rate"],
                "gap_promedio": kpis["performance"]["avg_gap"]
            }
            
            print(f"\n📊 {name}:")
            print(f"   Energía media: {kpis['objective_stats']['mean']:,.1f} MWh")
            print(f"   Éxito: {kpis['summary']['success_rate']:.1f}%")
    
    # Encontrar mejor escenario
    if comparison:
        best_scenario = max(comparison.keys(), 
                           key=lambda k: comparison[k]["energia_media"])
        print(f"\n🏆 Mejor escenario: {best_scenario}")
    
    return {
        "individual_kpis": scenario_kpis,
        "comparison": comparison,
        "best_scenario": best_scenario if comparison else None
    }