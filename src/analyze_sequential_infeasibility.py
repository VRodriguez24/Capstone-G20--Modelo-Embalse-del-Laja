# src/analyze_sequential_infeasibility.py
"""
Analiza por qué algunos años se vuelven infactibles en secuencias
"""

from model import build_model_for_one_year
from sensitivity import extract_kpis

def analyze_year_sequence(start_year: int, end_year: int, initial_V0: float = 1400.0):
    """
    Analiza una secuencia de años para identificar dónde ocurre la infactibilidad
    """
    print(f"🔍 ANÁLISIS SECUENCIAL: {start_year}-{end_year}")
    print(f"💧 V0 inicial: {initial_V0:.1f} Hm³")
    print("=" * 70)
    
    current_V0 = initial_V0
    
    for year in range(start_year, end_year + 1):
        print(f"\n📅 Año {year} | V0 = {current_V0:.1f} Hm³")
        print("-" * 40)
        
        try:
            model = build_model_for_one_year(target_year=year, V0=current_V0)
            model.optimize()
            
            kpis = extract_kpis(model)
            status = kpis['status']
            
            if status == 2:  # Óptimo
                energy = kpis.get('obj_MWh', 0)
                v_final = kpis.get('V_end', current_V0)
                
                print(f"✅ FACTIBLE")
                print(f"   ⚡ Energía: {energy:,.1f} MWh")
                print(f"   💧 V_final: {v_final:.1f} Hm³")
                print(f"   📈 ΔV: {v_final - current_V0:+.1f} Hm³")
                
                # Actualizar V0 para el siguiente año
                current_V0 = v_final
                
            else:
                print(f"❌ INFACTIBLE (Status: {status})")
                print(f"   🔍 V0 crítico: {current_V0:.1f} Hm³")
                
                # Intentar con diferentes V0 para encontrar umbral
                test_volumes = [1200, 1400, 1600, 1800, 2000, 2200, 2400, 2600, 2800, 3000]
                
                print(f"   🧪 Pruebas de V0:")
                feasible_found = False
                for test_V0 in test_volumes:
                    test_model = build_model_for_one_year(target_year=year, V0=test_V0)
                    test_model.optimize()
                    test_kpis = extract_kpis(test_model)
                    
                    if test_kpis['status'] == 2:
                        if not feasible_found:
                            print(f"      💧 V0 mínimo factible: {test_V0:.1f} Hm³")
                            feasible_found = True
                            # Usar este V0 para continuar
                            current_V0 = test_kpis.get('V_end', test_V0)
                        break
                    test_model.dispose()
                
                if not feasible_found:
                    print(f"      ❌ No se encontró V0 factible hasta 3000 Hm³")
                    break
            
            model.dispose()
            
        except Exception as e:
            print(f"❌ Error: {e}")
            break

def analyze_critical_transitions():
    """
    Analiza las transiciones críticas que causan infactibilidad
    """
    print("\n🎯 ANÁLISIS DE TRANSICIONES CRÍTICAS")
    print("=" * 70)
    
    # Secuencias problemáticas identificadas
    critical_sequences = [
        (1961, 1963),  # 1962 problemático después de 1961
        (1998, 2000),  # 1999 problemático después de 1998
        (2007, 2009),  # 2008 problemático después de 2007
        (2012, 2018),  # 2013-2017 problemáticos después de 2012
    ]
    
    for start, end in critical_sequences:
        analyze_year_sequence(start, end)
        print("\n" + "="*70 + "\n")

def check_volume_constraints():
    """
    Verifica si hay problemas con las restricciones de volumen
    """
    print("🔧 VERIFICACIÓN DE RESTRICCIONES DE VOLUMEN")
    print("=" * 50)
    
    from model import V_min, V_max, COLCHONES
    
    print(f"📊 Límites de volumen:")
    print(f"   V_min: {V_min:.1f} Hm³")
    print(f"   V_max: {V_max:.1f} Hm³")
    
    print(f"\n🏗️  Rangos de colchones:")
    for name, config in COLCHONES.items():
        lo, hi = config['lo'], config['hi']
        riego_share, gen_share, _ = config['shares']
        
        print(f"   {name:12s}: [{lo:>6.1f}, {hi:>6.1f}] Hm³")
        print(f"                   Riego: {riego_share*100:4.1f}% | Generación: {gen_share*100:4.1f}%")
    
    # Calcular presupuestos para diferentes V0
    print(f"\n💰 PRESUPUESTOS POR V0:")
    test_volumes = [1200, 1400, 1600, 1800, 2000, 2400, 3000]
    
    print("V0 (Hm³)  | Colchón     | Presup.Riego | Presup.Gen")
    print("-" * 55)
    
    for V0 in test_volumes:
        # Determinar colchón
        colchon = None
        for name, config in COLCHONES.items():
            lo, hi = config['lo'], config['hi']
            eps = 1e-3 if name != 'Inferior' else 0
            if (lo + eps) <= V0 <= hi:
                colchon = name
                break
        
        if colchon:
            shares = COLCHONES[colchon]['shares']
            presup_riego = V0 * shares[0]
            presup_gen = V0 * shares[1]
            
            print(f"{V0:>8.1f}  | {colchon:11s} | {presup_riego:>10.1f}   | {presup_gen:>8.1f}")

if __name__ == "__main__":
    check_volume_constraints()
    analyze_critical_transitions()