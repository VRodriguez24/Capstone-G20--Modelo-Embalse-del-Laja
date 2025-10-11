#!/usr/bin/env python3
"""
Solución para el problema de infactibilidad secuencial.

PROBLEMA IDENTIFICADO:
- En run_deterministic(), cuando un año es infactible, V0 no se actualiza
- Esto causa cascada de infactibilidades en años posteriores
- Los años son individualmente factibles con V0=1400, pero fallan en secuencia

SOLUCIÓN PROPUESTA:
- Implementar estrategia de recuperación cuando hay infactibilidad
- Opciones: reset a V0 seguro, interpolación, o volumen de seguridad

Autor: Sistema de Análisis Capstone G20
"""

from typing import List, Dict, Any, Optional
import gurobipy as gp
from model import build_model_for_one_year
from sensitivity import extract_kpis


def run_deterministic_robust(years: List[int], V0: float, 
                           recovery_strategy: str = "safe_volume"):
    """
    Versión robusta de run_deterministic que maneja infactibilidades.
    
    Args:
        years: Lista de años a procesar
        V0: Volumen inicial
        recovery_strategy: Estrategia para manejar infactibilidades
            - "safe_volume": Reset a 1400 Hm³ (volumen seguro)
            - "previous": Mantener volumen anterior
            - "interpolate": Interpolar entre límites seguros
    """
    print(f"🛡️  OPTIMIZACIÓN DETERMINÍSTICA ROBUSTA")
    print(f"   📅 Años: {min(years)}-{max(years)} ({len(years)} años)")
    print(f"   💧 V0 inicial: {V0:.1f} Hm³")
    print(f"   🔧 Estrategia de recuperación: {recovery_strategy}")
    print("=" * 80)
    
    results = []
    total_energy = 0
    current_V0 = V0
    safe_volume = 1400.0  # Volumen seguro confirmado por análisis
    
    # Contadores de diagnóstico
    optimal_count = 0
    infeasible_count = 0
    recoveries = 0
    
    for i, year in enumerate(years):
        print(f"\n🗓️  AÑO {year} ({i+1}/{len(years)})")
        print(f"   💧 V0: {current_V0:.1f} Hm³")
        print("-" * 50)
        
        # Intentar optimización con V0 actual
        model = build_model_for_one_year(target_year=year, V0=current_V0)
        model.optimize()
        kpis = extract_kpis(model)
        
        status_names = {
            2: "ÓPTIMO",
            3: "INFACTIBLE", 
            4: "INFACTIBLE O NO ACOTADO",
            5: "LÍMITE DE TIEMPO",
            9: "INTERRUMPIDO"
        }
        status_name = status_names.get(kpis['status'], f"STATUS_{kpis['status']}")
        
        if kpis['status'] == 2:  # ÓPTIMO
            optimal_count += 1
            energy = kpis.get('obj_MWh', 0)
            v_final = kpis.get('V_end', current_V0)
            
            print(f"   ✅ {status_name}")
            print(f"   ⚡ Energía: {energy:,.1f} MWh")
            print(f"   💧 V_final: {v_final:.1f} Hm³")
            print(f"   📈 ΔV: {v_final - current_V0:+.1f} Hm³")
            
            total_energy += energy
            results.append({
                'year': year,
                'status': 'ÓPTIMO',
                'energy': energy,
                'v_initial': current_V0,
                'v_final': v_final,
                'recovery_used': False
            })
            
            # Actualizar V0 para siguiente año
            current_V0 = v_final
            
        else:  # INFACTIBLE u otros problemas
            infeasible_count += 1
            print(f"   ❌ {status_name}")
            
            # Aplicar estrategia de recuperación
            v_recovery = None
            recovery_used = False
            
            if recovery_strategy == "safe_volume":
                v_recovery = safe_volume
                recovery_used = True
                recoveries += 1
                print(f"   🔧 Aplicando recuperación: V0 → {v_recovery:.1f} Hm³")
                
            elif recovery_strategy == "previous":
                v_recovery = current_V0  # Mantener el mismo
                print(f"   🔧 Manteniendo V0: {v_recovery:.1f} Hm³")
                
            elif recovery_strategy == "interpolate":
                # Interpolar entre volumen seguro y límites operativos
                v_recovery = (current_V0 + safe_volume) / 2
                recovery_used = True
                recoveries += 1
                print(f"   🔧 Interpolando V0: {current_V0:.1f} → {v_recovery:.1f} Hm³")
            
            # Intentar re-optimizar con volumen de recuperación si es diferente
            if v_recovery != current_V0:
                print(f"   🔄 Re-intentando con V0={v_recovery:.1f} Hm³...")
                model.dispose()  # Limpiar modelo anterior
                
                model_recovery = build_model_for_one_year(
                    target_year=year, V0=v_recovery
                )
                model_recovery.optimize()
                kpis_recovery = extract_kpis(model_recovery)
                
                if kpis_recovery['status'] == 2:
                    optimal_count += 1
                    infeasible_count -= 1
                    
                    energy = kpis_recovery.get('obj_MWh', 0)
                    v_final = kpis_recovery.get('V_end', v_recovery)
                    
                    print(f"   ✅ RECUPERACIÓN EXITOSA!")
                    print(f"   ⚡ Energía: {energy:,.1f} MWh")
                    print(f"   💧 V_final: {v_final:.1f} Hm³")
                    
                    total_energy += energy
                    results.append({
                        'year': year,
                        'status': 'ÓPTIMO (RECUPERADO)',
                        'energy': energy,
                        'v_initial': v_recovery,
                        'v_final': v_final,
                        'recovery_used': True
                    })
                    
                    current_V0 = v_final
                    
                else:
                    print(f"   ❌ Recuperación falló: {status_names.get(kpis_recovery['status'], 'ERROR')}")
                    results.append({
                        'year': year,
                        'status': f'INFACTIBLE ({recovery_strategy})',
                        'energy': 0,
                        'v_initial': current_V0,
                        'v_final': None,
                        'recovery_used': recovery_used
                    })
                
                model_recovery.dispose()
            else:
                results.append({
                    'year': year,
                    'status': status_name,
                    'energy': 0,
                    'v_initial': current_V0,
                    'v_final': None,
                    'recovery_used': recovery_used
                })
        
        model.dispose()
    
    # RESUMEN FINAL
    print("\n" + "=" * 80)
    print("📋 RESUMEN DETERMINÍSTICO ROBUSTO")
    print("=" * 80)
    
    print(f"🎯 Años procesados: {len(results)}")
    print(f"✅ Años óptimos: {optimal_count}")
    print(f"❌ Años infactibles: {infeasible_count}")
    print(f"🔧 Recuperaciones aplicadas: {recoveries}")
    print(f"📊 Tasa de éxito: {optimal_count/len(results)*100:.1f}%")
    print(f"⚡ Energía total: {total_energy:,.1f} MWh")
    
    if optimal_count > 0:
        avg_energy = total_energy / optimal_count
        print(f"📊 Energía promedio: {avg_energy:,.1f} MWh/año")
    
    # Análisis de recuperaciones
    if recoveries > 0:
        recovered_results = [r for r in results if r.get('recovery_used', False)]
        total_recovered_energy = sum(r['energy'] for r in recovered_results)
        print(f"🛡️  Energía por recuperación: {total_recovered_energy:,.1f} MWh")
    
    print("\n📊 DETALLE POR AÑO:")
    print("Año    Estado                    Energía      V_inicial   V_final    Recup.")
    print("-" * 75)
    
    for r in results:
        recovery_icon = "🔧" if r.get('recovery_used', False) else "  "
        if r['status'].startswith('ÓPTIMO'):
            print(f"{r['year']}   {r['status']:<20} {r['energy']:>8,.1f} MWh  "
                  f"{r['v_initial']:>7.1f}   {r['v_final']:>7.1f}    {recovery_icon}")
        else:
            print(f"{r['year']}   {r['status']:<20} {'---':>8} MWh  "
                  f"{r['v_initial']:>7.1f}   {'---':>7}    {recovery_icon}")
    
    print("=" * 80)
    
    return results


def compare_strategies(years: List[int], V0: float) -> Dict[str, Dict[str, Any]]:
    """
    Compara diferentes estrategias de recuperación.
    """
    print("\n🔬 COMPARACIÓN DE ESTRATEGIAS DE RECUPERACIÓN")
    print("=" * 80)
    
    strategies = ["safe_volume", "previous", "interpolate"]
    comparison = {}
    
    for strategy in strategies:
        print(f"\n▶ Evaluando estrategia: {strategy}")
        print("-" * 40)
        
        results = run_deterministic_robust(years, V0, strategy)
        
        # Calcular métricas
        optimal_count = len([r for r in results if r['status'].startswith('ÓPTIMO')])
        total_energy = sum(r['energy'] for r in results)
        recoveries = len([r for r in results if r.get('recovery_used', False)])
        
        comparison[strategy] = {
            'results': results,
            'optimal_count': optimal_count,
            'total_energy': total_energy,
            'recovery_count': recoveries,
            'success_rate': optimal_count / len(results) * 100
        }
    
    # Mostrar comparación
    print("\n📊 COMPARACIÓN FINAL:")
    print("Estrategia       Óptimos    Energía Total    Recuperaciones    Tasa Éxito")
    print("-" * 75)
    
    for strategy, metrics in comparison.items():
        print(f"{strategy:<15} {metrics['optimal_count']:>7}    "
              f"{metrics['total_energy']:>10,.1f} MWh    {metrics['recovery_count']:>11}    "
              f"{metrics['success_rate']:>8.1f}%")
    
    # Mejor estrategia
    best_strategy = max(comparison.keys(), 
                       key=lambda s: comparison[s]['total_energy'])
    
    print(f"\n🏆 MEJOR ESTRATEGIA: {best_strategy}")
    print(f"   ⚡ Energía: {comparison[best_strategy]['total_energy']:,.1f} MWh")
    print(f"   📊 Tasa éxito: {comparison[best_strategy]['success_rate']:.1f}%")
    
    return comparison


if __name__ == "__main__":
    # Caso de prueba con años problemáticos
    problematic_years = [1961, 1962, 1963]  # 1962 era infactible en secuencia
    
    print("🧪 PRUEBA DE SOLUCIÓN DE INFACTIBILIDAD SECUENCIAL")
    print("=" * 60)
    
    # Probar estrategia recomendada
    results = run_deterministic_robust(
        years=problematic_years,
        V0=1400.0,
        recovery_strategy="safe_volume"
    )
    
    # Comparar todas las estrategias
    comparison = compare_strategies(problematic_years, 1400.0)