# src/debug_infeasible.py
"""
Herramientas de diagnóstico para analizar años infactibles en el modelo
"""

import gurobipy as gp
from gurobipy import GRB
from model import build_model_for_one_year
from data_loader import load_injections_for_year
import pandas as pd

def diagnose_infeasible_year(year: int, V0: float = 1400.0):
    """
    Analiza por qué un año específico es infactible
    """
    print(f"\n🔍 DIAGNÓSTICO DE INFACTIBILIDAD - AÑO {year}")
    print("=" * 60)
    
    # Construir modelo
    model = build_model_for_one_year(target_year=year, V0=V0)
    
    # Intentar optimizar
    model.optimize()
    
    if model.Status == GRB.INFEASIBLE:
        print(f"❌ MODELO INFACTIBLE para año {year}")
        
        # Calcular IIS (Irreducible Inconsistent Subsystem)
        print("\n🔍 Calculando IIS (conjunto inconsistente irreducible)...")
        model.computeIIS()
        
        # Guardar IIS a archivo
        iis_file = f"infeasible_{year}.ilp"
        model.write(iis_file)
        print(f"💾 IIS guardado en: {iis_file}")
        
        # Mostrar restricciones en conflicto
        print("\n🚨 RESTRICCIONES EN CONFLICTO:")
        conflict_count = 0
        for constr in model.getConstrs():
            if constr.IISConstr:
                conflict_count += 1
                print(f"  - {constr.ConstrName}")
                
        print(f"\n📊 Total restricciones en conflicto: {conflict_count}")
        
        # Analizar datos de entrada específicos
        analyze_input_data(year)
        
    elif model.Status == GRB.INF_OR_UNBD:
        print(f"⚠️  MODELO INFACTIBLE O NO ACOTADO para año {year}")
        
        # Intentar con método dual simplex
        model.setParam('Method', 1)  # Dual simplex
        model.optimize()
        
        if model.Status == GRB.INFEASIBLE:
            print("✅ Confirmado: INFACTIBLE")
            model.computeIIS()
            iis_file = f"infeasible_{year}.ilp"
            model.write(iis_file)
            analyze_input_data(year)
        elif model.Status == GRB.UNBOUNDED:
            print("📈 Confirmado: NO ACOTADO")
            
    else:
        print(f"✅ Modelo factible para año {year} (Status: {model.Status})")
        
    model.dispose()

def analyze_input_data(year: int):
    """
    Analiza los datos de entrada para un año específico
    """
    print(f"\n📊 ANÁLISIS DE DATOS DE ENTRADA - AÑO {year}")
    print("-" * 50)
    
    try:
        # Cargar inyecciones del año
        injections = load_injections_for_year("data/Caudales_historicos_filtrado.csv", year)
        
        # Calcular estadísticas por mes
        monthly_totals = {}
        for month in range(1, 13):
            monthly_total = 0
            for (i, j, t) in injections.keys():
                if t == month:
                    monthly_total += injections[(i, j, t)]
            monthly_totals[month] = monthly_total
            
        print("💧 CAUDALES MENSUALES TOTALES (m³/s):")
        for month in range(1, 13):
            total = monthly_totals.get(month, 0)
            print(f"  Mes {month:2d}: {total:>8.1f} m³/s")
            
        # Identificar meses críticos (muy bajos)
        avg_flow = sum(monthly_totals.values()) / 12
        critical_months = [m for m, flow in monthly_totals.items() if flow < avg_flow * 0.3]
        
        if critical_months:
            print(f"\n⚠️  MESES CRÍTICOS (< 30% del promedio): {critical_months}")
            print(f"📊 Caudal promedio anual: {avg_flow:.1f} m³/s")
            
        # Análisis específico por fuente
        print(f"\n🏞️  ANÁLISIS POR FUENTE DE INYECCIÓN:")
        sources = {}
        for (i, j, t) in injections.keys():
            source = i.replace("afluente_", "")
            if source not in sources:
                sources[source] = 0
            sources[source] += injections[(i, j, t)]
            
        for source, total in sources.items():
            print(f"  {source:15s}: {total:>8.1f} m³/s (anual)")
            
    except Exception as e:
        print(f"❌ Error analizando datos: {e}")

def check_constraint_bounds():
    """
    Verifica los límites y parámetros del modelo que podrían causar infactibilidad
    """
    print(f"\n🔧 VERIFICACIÓN DE PARÁMETROS DEL MODELO")
    print("-" * 50)
    
    from model import (V_min, V_max, TUCAPEL_MIN, ABANICO_MIN, SALTOS_MIN,
                      FIRST_REGANTES_FACTOR, SECOND_REGANTES_FACTOR,
                      SECOND_REGANTES_BASE, COLCHONES)
    
    print(f"💧 Volúmenes del embalse:")
    print(f"  V_min: {V_min:>8.1f} Hm³")
    print(f"  V_max: {V_max:>8.1f} Hm³")
    
    print(f"\n🌊 Caudales mínimos:")
    print(f"  Tucapel: {TUCAPEL_MIN:>6.1f} m³/s")
    print(f"  Abanico: {ABANICO_MIN:>6.1f} m³/s") 
    print(f"  Saltos:  {SALTOS_MIN:>6.1f} m³/s")
    print(f"  2dos Regantes: {SECOND_REGANTES_BASE:>6.1f} m³/s")
    
    print(f"\n📅 Factores estacionales críticos:")
    print("Primeros regantes:")
    for mes in range(1, 13):
        factor = FIRST_REGANTES_FACTOR.get(mes, 1.0)
        if factor == 0.0:
            print(f"  Mes {mes:2d}: {factor:4.2f} (SIN DEMANDA)")
        elif factor < 1.0:
            print(f"  Mes {mes:2d}: {factor:4.2f}")
            
    print("Segundos regantes:")
    for mes in range(1, 13):
        factor = SECOND_REGANTES_FACTOR.get(mes, 1.0)
        if factor == 0.0:
            print(f"  Mes {mes:2d}: {factor:4.2f} (SIN DEMANDA)")
        elif factor < 1.0:
            print(f"  Mes {mes:2d}: {factor:4.2f}")
    
    print(f"\n🏗️  Colchones del embalse:")
    for name, config in COLCHONES.items():
        lo, hi = config["lo"], config["hi"]
        shares = config["shares"]
        print(f"  {name:12s}: [{lo:>6.1f}, {hi:>6.1f}] Hm³ | shares: {shares}")

def run_comprehensive_diagnosis():
    """
    Ejecuta un diagnóstico completo de los años infactibles
    """
    print("🔍 DIAGNÓSTICO COMPLETO DE INFACTIBILIDAD")
    print("=" * 80)
    
    # Verificar parámetros del modelo
    check_constraint_bounds()
    
    # Años problemáticos identificados
    problematic_years = [1962, 1999, 2008, 2013, 2014, 2015, 2016, 2017]
    
    print(f"\n🎯 Analizando {len(problematic_years)} años problemáticos...")
    
    for year in problematic_years:
        diagnose_infeasible_year(year)
        print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    run_comprehensive_diagnosis()