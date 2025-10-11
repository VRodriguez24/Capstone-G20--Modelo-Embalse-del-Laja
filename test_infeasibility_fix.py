#!/usr/bin/env python3
"""
Test con años que causan infactibilidad secuencial.
Recrear el problema y aplicar la solución.
"""

import sys
sys.path.append('src')

from fix_sequential_infeasibility import run_deterministic_robust, compare_strategies
from model import build_model_for_one_year
from sensitivity import extract_kpis

def test_problematic_sequence():
    """
    Recrear el problema de infactibilidad secuencial usando una cascada artificial.
    """
    print("🔬 RECREANDO PROBLEMA DE INFACTIBILIDAD SECUENCIAL")
    print("=" * 70)
    
    # Vamos a forzar una situación problemática empezando con volumen muy bajo
    # y años que requieren mucho volumen
    problematic_years = [1960, 1961, 1962]
    low_V0 = 1220.0  # Volumen muy bajo para crear problema
    
    print(f"📅 Años de prueba: {problematic_years}")
    print(f"💧 V0 problemático: {low_V0} Hm³ (muy bajo)")
    print("-" * 70)
    
    # Simulación de run_deterministic original (sin recuperación)
    print("\n📊 SIMULACIÓN ORIGINAL (sin recuperación):")
    results_original = []
    current_V0 = low_V0
    total_energy = 0
    
    for year in problematic_years:
        print(f"\n🗓️  Año {year} | V0 = {current_V0:.1f} Hm³")
        
        model = build_model_for_one_year(target_year=year, V0=current_V0)
        model.optimize()
        kpis = extract_kpis(model)
        
        if kpis['status'] == 2:  # ÓPTIMO
            energy = kpis.get('obj_MWh', 0)
            v_final = kpis.get('V_end', current_V0)
            
            print(f"   ✅ ÓPTIMO: {energy:.1f} MWh | V_final: {v_final:.1f} Hm³")
            total_energy += energy
            current_V0 = v_final  # Actualizar para siguiente año
            
            results_original.append({
                'year': year, 'status': 'ÓPTIMO', 'energy': energy,
                'v_initial': current_V0, 'v_final': v_final
            })
            
        else:
            print(f"   ❌ INFACTIBLE (status: {kpis['status']})")
            # EN ORIGINAL: V0 NO SE ACTUALIZA, causando cascada
            results_original.append({
                'year': year, 'status': 'INFACTIBLE', 'energy': 0,
                'v_initial': current_V0, 'v_final': None
            })
        
        model.dispose()
    
    print(f"\n📊 RESULTADO ORIGINAL:")
    optimal_count = len([r for r in results_original if r['status'] == 'ÓPTIMO'])
    print(f"   ✅ Años óptimos: {optimal_count}/{len(problematic_years)}")
    print(f"   ⚡ Energía total: {total_energy:.1f} MWh")
    
    # Ahora aplicar solución robusta
    print("\n" + "=" * 70)
    print("🛡️  APLICANDO SOLUCIÓN ROBUSTA:")
    
    results_robust = run_deterministic_robust(
        years=problematic_years,
        V0=low_V0,
        recovery_strategy="safe_volume"
    )
    
    return results_original, results_robust

def test_worst_case_cascade():
    """
    Crear escenario de cascada extrema para probar recuperación.
    """
    print("\n🔥 TEST DE CASCADA EXTREMA")
    print("=" * 70)
    
    # Usar años secos consecutivos con volumen inicial crítico
    cascade_years = [2007, 2008, 2009, 2010, 2011]  # Período potencialmente seco
    critical_V0 = 1205.0  # Justo sobre V_min
    
    print(f"📅 Años de cascada: {min(cascade_years)}-{max(cascade_years)}")
    print(f"💧 V0 crítico: {critical_V0} Hm³")
    
    # Aplicar cada estrategia de recuperación
    strategies = ["safe_volume", "previous", "interpolate"]
    
    for strategy in strategies:
        print(f"\n🔧 Estrategia: {strategy}")
        print("-" * 40)
        
        results = run_deterministic_robust(
            years=cascade_years,
            V0=critical_V0,
            recovery_strategy=strategy
        )
        
        optimal_count = len([r for r in results if r['status'].startswith('ÓPTIMO')])
        total_energy = sum(r['energy'] for r in results)
        recovery_count = len([r for r in results if r.get('recovery_used', False)])
        
        print(f"   📊 Resumen: {optimal_count}/{len(cascade_years)} óptimos")
        print(f"   ⚡ Energía: {total_energy:,.1f} MWh")
        print(f"   🔧 Recuperaciones: {recovery_count}")

if __name__ == "__main__":
    print("🧪 SUITE DE PRUEBAS PARA INFACTIBILIDAD SECUENCIAL")
    print("=" * 80)
    
    # Test 1: Recrear problema conocido
    original, robust = test_problematic_sequence()
    
    # Test 2: Cascada extrema
    test_worst_case_cascade()
    
    print("\n" + "=" * 80)
    print("✅ SUITE DE PRUEBAS COMPLETADA")
    print("=" * 80)