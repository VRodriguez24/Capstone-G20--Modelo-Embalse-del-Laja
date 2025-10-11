# src/sensitivity.py
"""
Módulo de análisis de sensibilidad para el modelo Embalse del Laja.
Proporciona funciones para análisis paramétrico y extracción de KPIs.
"""

from __future__ import annotations
from typing import Dict, List, Any, Optional
import gurobipy as gp
from gurobipy import GRB
from embalse import T


def extract_kpis(model: gp.Model) -> Dict[str, Any]:
    """
    Extrae KPIs (indicadores clave) de un modelo optimizado.
    
    Args:
        model: Modelo de Gurobi ya optimizado
        
    Returns:
        Dict con KPIs extraídos
    """
    kpis = {
        'status': model.Status,
        'obj_MWh': None,
        'gap': None,
        'V_end': None,
        'DefAb_sum': 0.0,
        'DefTu_sum': 0.0,
        'Def2_sum': 0.0,
        'energy_total': 0.0
    }
    
    try:
        if model.Status == GRB.OPTIMAL:
            kpis['obj_MWh'] = model.ObjVal
            
            # Gap si está disponible
            if hasattr(model, 'MIPGap'):
                kpis['gap'] = model.MIPGap
            
            # Volumen final si existe variable V
            if hasattr(model, '_V') and model._V:
                last_month = max(T)
                if last_month in model._V:
                    kpis['V_end'] = model._V[last_month].x
            
            # Déficits si existen las variables
            if hasattr(model, 'DefAb'):
                kpis['DefAb_sum'] = sum(model.getVarByName(f"DeficitAbanico[{t}]").x for t in T)
            
            if hasattr(model, 'DefTu'):
                kpis['DefTu_sum'] = sum(model.getVarByName(f"DeficitTucapel[{t}]").x for t in T)
                
            if hasattr(model, 'Def2'):
                kpis['Def2_sum'] = sum(model.getVarByName(f"Deficit2dosRegantes[{t}]").x for t in T)
            
            # Energía total
            if hasattr(model, '_G') and model._G:
                kpis['energy_total'] = sum(model._G[t].x for t in T)
                
    except Exception as e:
        print(f"⚠️ Error extrayendo KPIs: {e}")
    
    return kpis


def sweep_V0(years: List[int], v0_grid: List[float], 
             I_arc_override: Optional[Dict] = None) -> Dict[tuple, Dict[str, Any]]:
    """
    Realiza barrido de sensibilidad sobre el parámetro V0.
    
    Args:
        years: Lista de años a evaluar
        v0_grid: Lista de valores V0 a probar
        I_arc_override: Inyecciones específicas (para Monte Carlo)
        
    Returns:
        Dict con resultados por (V0, año)
    """
    from model import build_model_for_one_year
    
    results = {}
    
    for V0 in v0_grid:
        for year in years:
            print(f"  🔍 Evaluando V0={V0:.1f}, año={year}")
            
            try:
                # Construir modelo
                model = build_model_for_one_year(
                    target_year=year,
                    V0=V0,
                    I_arc_override=I_arc_override
                )
                
                # Optimizar
                model.optimize()
                
                # Extraer KPIs
                kpis = extract_kpis(model)
                results[(V0, year)] = kpis
                
                # Limpiar modelo
                model.dispose()
                
            except Exception as e:
                print(f"    ❌ Error en V0={V0}, año={year}: {e}")
                results[(V0, year)] = {
                    'status': -1,
                    'obj_MWh': None,
                    'error': str(e)
                }
    
    return results


def analyze_sensitivity_results(results: Dict[tuple, Dict[str, Any]], 
                               parameter: str = "V0") -> None:
    """
    Analiza y presenta resultados de análisis de sensibilidad.
    
    Args:
        results: Resultados del análisis de sensibilidad
        parameter: Nombre del parámetro analizado
    """
    print(f"\n📊 === ANÁLISIS DE SENSIBILIDAD - {parameter.upper()} ===")
    
    # Separar por parámetro
    param_values = sorted(set(key[0] for key in results.keys()))
    years = sorted(set(key[1] for key in results.keys()))
    
    # Estadísticas por valor del parámetro
    for param_val in param_values:
        year_results = [results[(param_val, year)] for year in years]
        
        # Contar estados
        optimal_count = sum(1 for r in year_results if r['status'] == GRB.OPTIMAL)
        total_energy = sum(r['obj_MWh'] or 0 for r in year_results if r['obj_MWh'])
        
        print(f"\n🎯 {parameter}={param_val:.1f}:")
        print(f"   ✅ Años óptimos: {optimal_count}/{len(years)}")
        print(f"   ⚡ Energía total: {total_energy:.1f} MWh")
        
        if optimal_count > 0:
            avg_energy = total_energy / optimal_count
            print(f"   📊 Energía promedio: {avg_energy:.1f} MWh")
    
    # Mejor configuración
    best_result = None
    best_key = None
    best_energy = 0
    
    for key, result in results.items():
        if result['status'] == GRB.OPTIMAL and result['obj_MWh']:
            if result['obj_MWh'] > best_energy:
                best_energy = result['obj_MWh']
                best_result = result
                best_key = key
    
    if best_result:
        print(f"\n🏆 MEJOR CONFIGURACIÓN:")
        print(f"   {parameter}={best_key[0]:.1f}, Año={best_key[1]}")
        print(f"   Energía: {best_energy:.1f} MWh")
        print(f"   Volumen final: {best_result.get('V_end', 'N/A'):.1f} Hm³")


def calculate_yearly_kpis(results: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calcula KPIs agregados para múltiples años.
    
    Args:
        results: Resultados por año
        
    Returns:
        Dict con KPIs agregados
    """
    if not results:
        return {
            'total_years': 0,
            'optimal_years': 0,
            'feasibility_rate': 0.0,
            'total_energy_MWh': 0.0,
            'avg_energy_MWh': 0.0,
            'max_energy_MWh': 0.0,
            'best_year': None
        }
    
    optimal_results = [r for r in results.values() 
                      if r.get('status') == GRB.OPTIMAL]
    
    total_years = len(results)
    optimal_years = len(optimal_results)
    
    total_energy = sum(r.get('obj_MWh', 0) for r in optimal_results)
    max_energy = max((r.get('obj_MWh', 0) for r in optimal_results), default=0)
    
    # Encontrar mejor año
    best_year = None
    if optimal_results:
        for year, result in results.items():
            if (result.get('status') == GRB.OPTIMAL and 
                result.get('obj_MWh') == max_energy):
                best_year = year
                break
    
    return {
        'total_years': total_years,
        'optimal_years': optimal_years,
        'feasibility_rate': optimal_years / total_years if total_years > 0 else 0.0,
        'total_energy_MWh': total_energy,
        'avg_energy_MWh': total_energy / optimal_years if optimal_years > 0 else 0.0,
        'max_energy_MWh': max_energy,
        'best_year': best_year
    }


def run_sensitivity_analysis(parameter: str, param_values: List[float],
                           base_year: int, V0: Optional[float] = None) -> Dict[tuple, Dict[str, Any]]:
    """
    Ejecuta análisis de sensibilidad para un parámetro específico.
    
    Args:
        parameter: Nombre del parámetro ('V0', etc.)
        param_values: Lista de valores a probar
        base_year: Año base para el análisis
        V0: Valor V0 fijo (si el parámetro no es V0)
        
    Returns:
        Dict con resultados del análisis
    """
    print(f"🔍 Ejecutando análisis de sensibilidad para {parameter}")
    print(f"   Valores: {param_values}")
    print(f"   Año base: {base_year}")
    
    if parameter == 'V0':
        return sweep_V0(years=[base_year], v0_grid=param_values)
    else:
        # Para otros parámetros, se puede extender aquí
        print(f"⚠️ Parámetro {parameter} no implementado todavía")
        return {}
