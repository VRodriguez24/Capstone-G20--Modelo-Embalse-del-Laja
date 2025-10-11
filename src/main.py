# src/main.py
from __future__ import annotations
import argparse
import sys
import os
from typing import List, Optional
from gurobipy import GRB
from embalse import T
from model import build_model_for_one_year, YEARS_HORIZON
from montecarlo import BlockBootstrapSampler
from sensitivity import sweep_V0, extract_kpis

INJ_CSV = "data/Caudales_historicos_filtrado.csv"

def run_deterministic(years: List[int], V0: float, robust: bool = False):
    """
    Ejecuta optimización determinística con opción de recuperación robusta.
    
    Args:
        years: Lista de años a procesar
        V0: Volumen inicial en Hm³
        robust: Si True, aplica estrategia de recuperación ante infactibilidades
    """
    strategy_text = "🛡️  ROBUSTO" if robust else "📊 ESTÁNDAR"
    print(f"▶ Determinístico {strategy_text} | años={years} | V0={V0}")
    print("=" * 80)
    
    results = []
    total_energy = 0
    current_V0 = V0
    safe_volume = 1400.0  # Volumen seguro confirmado por análisis
    recoveries = 0
    
    for i, y in enumerate(years):
        print(f"\n🗓️  PROCESANDO AÑO {y} ({i+1}/{len(years)})")
        print(f"💧 V0: {current_V0:,.1f} Hm³")
        print("-" * 50)
        
        m = build_model_for_one_year(target_year=y, V0=current_V0)
        m.optimize()
        k = extract_kpis(m)
        
        # Interpretación del status
        status_msg = {
            2: "✅ ÓPTIMO",
            3: "❌ INFACTIBLE", 
            4: "❌ INFACTIBLE O NO ACOTADO",
            5: "⏱️  LÍMITE DE TIEMPO",
            9: "⚠️  INTERRUMPIDO"
        }.get(k['status'], f"❓ STATUS {k['status']}")
        
        if k['status'] == 2:  # Óptimo
            energy = k.get('obj_MWh', 0)
            v_final = k.get('V_end', 0)
            def_ab = k.get('DefAb_sum', 0)
            def_tu = k.get('DefTu_sum', 0)
            
            print(f"📊 RESULTADO: {status_msg}")
            print(f"⚡ Energía generada: {energy:,.1f} MWh")
            print(f"💧 Volumen inicial: {current_V0:,.1f} Hm³")
            print(f"💧 Volumen final: {v_final:,.1f} Hm³")
            print(f"📉 Déficit Abanico: {def_ab:,.2f} Hm³")
            print(f"📉 Déficit Tucapel: {def_tu:,.2f} Hm³")
            
            total_energy += energy
            results.append({
                'year': y,
                'status': 'ÓPTIMO',
                'energy': energy,
                'v_initial': current_V0,
                'v_final': v_final,
                'deficit_ab': def_ab,
                'deficit_tu': def_tu,
                'recovery_used': False
            })
            
            # Actualizar V0 para el siguiente año si hay múltiples años
            if len(years) > 1:
                current_V0 = v_final
                print(f"🔄 V0 para próximo año: {current_V0:,.1f} Hm³")
                
        else:
            print(f"📊 RESULTADO: {status_msg}")
            
            # Aplicar estrategia de recuperación si está habilitada
            if robust and len(years) > 1:
                print(f"🛡️  APLICANDO RECUPERACIÓN: V0 → {safe_volume:.1f} Hm³")
                print("🔄 Re-intentando optimización...")
                
                # Limpiar modelo anterior
                m.dispose()
                
                # Re-intentar con volumen seguro
                m_recovery = build_model_for_one_year(target_year=y, V0=safe_volume)
                m_recovery.optimize()
                k_recovery = extract_kpis(m_recovery)
                
                if k_recovery['status'] == 2:  # Recuperación exitosa
                    energy = k_recovery.get('obj_MWh', 0)
                    v_final = k_recovery.get('V_end', safe_volume)
                    def_ab = k_recovery.get('DefAb_sum', 0)
                    def_tu = k_recovery.get('DefTu_sum', 0)
                    
                    print(f"✅ RECUPERACIÓN EXITOSA!")
                    print(f"⚡ Energía generada: {energy:,.1f} MWh")
                    print(f"💧 Volumen inicial: {safe_volume:,.1f} Hm³")
                    print(f"💧 Volumen final: {v_final:,.1f} Hm³")
                    print(f"📉 Déficit Abanico: {def_ab:,.2f} Hm³")
                    print(f"📉 Déficit Tucapel: {def_tu:,.2f} Hm³")
                    
                    total_energy += energy
                    recoveries += 1
                    results.append({
                        'year': y,
                        'status': 'ÓPTIMO (RECUPERADO)',
                        'energy': energy,
                        'v_initial': safe_volume,
                        'v_final': v_final,
                        'deficit_ab': def_ab,
                        'deficit_tu': def_tu,
                        'recovery_used': True
                    })
                    
                    current_V0 = v_final
                    print(f"🔄 V0 para próximo año: {current_V0:,.1f} Hm³")
                    
                else:
                    print(f"❌ Recuperación falló: {status_msg}")
                    results.append({
                        'year': y,
                        'status': f'{status_msg} (IRRECUPERABLE)',
                        'energy': 0,
                        'v_initial': current_V0,
                        'v_final': None,
                        'recovery_used': False
                    })
                
                m_recovery.dispose()
            else:
                print("❌ No se pudo obtener solución factible")
                results.append({
                    'year': y,
                    'status': status_msg,
                    'energy': 0,
                    'v_initial': current_V0,
                    'v_final': None,
                    'recovery_used': False
                })
        
        m.dispose()
    
    # Resumen final
    print("\n" + "=" * 80)
    header = "ROBUSTO" if robust else "DETERMINÍSTICO"
    print(f"📋 RESUMEN {header}")
    print("=" * 80)
    
    # Contar estados y recuperaciones
    optimal_results = [r for r in results if r['status'].startswith('ÓPTIMO')]
    recovered_results = [r for r in results if r.get('recovery_used', False)]
    
    print(f"🎯 Años procesados: {len(results)}")
    print(f"✅ Años óptimos: {len(optimal_results)}")
    if robust and recoveries > 0:
        print(f"🛡️  Recuperaciones exitosas: {recoveries}")
        recovered_energy = sum(r['energy'] for r in recovered_results)
        print(f"🔧 Energía por recuperación: {recovered_energy:,.1f} MWh")
    print(f"⚡ Energía total: {total_energy:,.1f} MWh")
    print(f"📊 Tasa de éxito: {len(optimal_results)/len(results)*100:.1f}%")
    
    if optimal_results:
        avg_energy = total_energy / len(optimal_results)
        print(f"📊 Energía promedio: {avg_energy:,.1f} MWh/año")
    
    print("\n📊 DETALLE POR AÑO:")
    header_detail = "Año    Estado                    Energía      V_final    Déficits      Recup."
    print(header_detail)
    print("-" * len(header_detail))
    
    for r in results:
        recovery_icon = "🛡️ " if r.get('recovery_used', False) else "   "
        if r['status'].startswith('ÓPTIMO'):
            print(f"{r['year']}   {r['status']:<20} {r['energy']:>8,.1f} MWh  "
                  f"{r['v_final']:>6,.1f}  Ab={r['deficit_ab']:.1f}/Tu={r['deficit_tu']:.1f}  {recovery_icon}")
        else:
            print(f"{r['year']}   {r['status']:<20} {'---':>8} MWh  {'---':>6}  {'---':>15}  {recovery_icon}")
    
    print("=" * 80)

def run_montecarlo(n_scenarios: int, years: List[int], V0: float, seed: int, 
                  block_len: int, noise_sigma: float = 0.0):
    print(f"▶ Monte Carlo | N={n_scenarios} | V0={V0} | seed={seed}")
    print(f"📦 Bootstrap: bloques={block_len} | ruido={noise_sigma}")
    print("=" * 80)
    
    sampler = BlockBootstrapSampler(INJ_CSV, random_state=seed)
    all_results = []
    optimal_count = 0
    energies = []
    
    for s in range(1, n_scenarios + 1):
        print(f"\n🎲 ESCENARIO {s}/{n_scenarios}")
        print("-" * 40)
        
        # Generar escenario de afluentes
        if noise_sigma == 0.0:
            I_arc = sampler.sample_year(block_len=block_len)
        else:
            I_arc = sampler.sample_year_with_noise(block_len=block_len, 
                                                  sigma=noise_sigma)
        
        scenario_results = []
        scenario_energy = 0
        current_V0 = V0
        
        for y in years:
            m = build_model_for_one_year(target_year=y, V0=current_V0, 
                                       I_arc_override=I_arc)
            m.optimize()
            k = extract_kpis(m)
            
            status_icon = "✅" if k['status'] == 2 else "❌"
            energy = k.get('obj_MWh', 0) if k['status'] == 2 else 0
            v_final = k.get('V_end', current_V0) if k['status'] == 2 else current_V0
            
            print(f"  {status_icon} {y}: {energy:>6,.1f} MWh | "
                  f"V_end: {v_final:>6,.1f} Hm³")
            
            scenario_results.append({
                'year': y,
                'status': k['status'],
                'energy': energy,
                'v_final': v_final
            })
            
            scenario_energy += energy
            current_V0 = v_final  # Para siguiente año
            m.dispose()
        
        all_results.append({
            'scenario': s,
            'total_energy': scenario_energy,
            'years': scenario_results
        })
        
        if scenario_energy > 0:
            optimal_count += 1
            energies.append(scenario_energy)
            
        print(f"📊 Total escenario: {scenario_energy:,.1f} MWh")
    
    # Análisis estadístico final
    print("\n" + "=" * 80)
    print("📈 ANÁLISIS MONTE CARLO")
    print("=" * 80)
    
    print(f"🎯 Escenarios simulados: {n_scenarios}")
    print(f"✅ Escenarios factibles: {optimal_count}")
    print(f"📊 Tasa de factibilidad: {optimal_count/n_scenarios*100:.1f}%")
    
    if energies:
        import numpy as np
        mean_energy = np.mean(energies)
        std_energy = np.std(energies)
        min_energy = np.min(energies)
        max_energy = np.max(energies)
        
        print(f"\n⚡ ESTADÍSTICAS DE ENERGÍA:")
        print(f"  📊 Promedio: {mean_energy:,.1f} MWh")
        print(f"  📏 Desv. estándar: {std_energy:,.1f} MWh")
        print(f"  📉 Mínimo: {min_energy:,.1f} MWh")
        print(f"  📈 Máximo: {max_energy:,.1f} MWh")
        print(f"  🎯 CV: {std_energy/mean_energy*100:.1f}%")
        
        # Percentiles
        p10 = np.percentile(energies, 10)
        p50 = np.percentile(energies, 50)
        p90 = np.percentile(energies, 90)
        
        print(f"\n📊 PERCENTILES:")
        print(f"  P10: {p10:,.1f} MWh")
        print(f"  P50: {p50:,.1f} MWh") 
        print(f"  P90: {p90:,.1f} MWh")
    
    print("=" * 80)


def run_sensitivity(years: List[int], v0_min: float, v0_max: float, 
                   v0_step: float, seed: int, block_len: int, noise_sigma: float):
    print(f"▶ Sensibilidad V0 | años={years}")
    print(f"📊 Rango: [{v0_min}, {v0_max}] step={v0_step} | seed={seed}")
    print("=" * 80)
    
    sampler = BlockBootstrapSampler(INJ_CSV, random_state=seed)
    
    # Generar escenario de afluentes
    if noise_sigma == 0.0:
        I_arc = sampler.sample_year(block_len=block_len)
        print("🌊 Usando datos históricos (sin ruido)")
    else:
        I_arc = sampler.sample_year_with_noise(block_len=block_len, 
                                              sigma=noise_sigma)
        print(f"🎲 Usando datos con ruido lognormal (σ={noise_sigma})")

    # Construir grid de V0
    v0_grid = []
    v = v0_min
    while v <= v0_max + 1e-9:
        v0_grid.append(round(v, 6))
        v += v0_step

    print(f"📊 Evaluando {len(v0_grid)} valores de V0...")
    print("-" * 80)

    res = sweep_V0(years=years, v0_grid=v0_grid, I_arc_override=I_arc)
    
    # Análisis de resultados
    feasible_points = []
    optimal_energies = []
    
    print("\n📋 RESULTADOS DETALLADOS:")
    print("-" * 80)
    
    for V0 in v0_grid:
        print(f"\n💧 V0 = {V0:,.1f} Hm³")
        
        total_energy = 0
        all_optimal = True
        year_details = []
        
        for y in years:
            k = res[(V0, y)]
            status = k['status']
            energy = k.get('obj_MWh', 0) if status == 2 else 0
            v_end = k.get('V_end', 0) if status == 2 else 0
            def_ab = k.get('DefAb_sum', 0)
            def_tu = k.get('DefTu_sum', 0)
            
            status_icon = "✅" if status == 2 else "❌"
            
            print(f"  {status_icon} {y}: {energy:>8,.1f} MWh | "
                  f"V_final: {v_end:>6,.1f} | "
                  f"Déficits: Ab={def_ab:.1f}, Tu={def_tu:.1f}")
            
            total_energy += energy
            if status != 2:
                all_optimal = False
            
            year_details.append({
                'year': y,
                'energy': energy,
                'v_final': v_end,
                'optimal': status == 2
            })
        
        if all_optimal:
            feasible_points.append({
                'V0': V0,
                'total_energy': total_energy,
                'years': year_details
            })
            optimal_energies.append(total_energy)
            
        print(f"  📊 TOTAL: {total_energy:,.1f} MWh ({'✅ Factible' if all_optimal else '❌ Infactible'})")

    # Resumen final
    print("\n" + "=" * 80)
    print("📈 ANÁLISIS DE SENSIBILIDAD")
    print("=" * 80)
    
    print(f"🎯 Puntos evaluados: {len(v0_grid)}")
    print(f"✅ Puntos factibles: {len(feasible_points)}")
    print(f"📊 Tasa factibilidad: {len(feasible_points)/len(v0_grid)*100:.1f}%")
    
    if optimal_energies:
        import numpy as np
        best_idx = np.argmax(optimal_energies)
        best_point = feasible_points[best_idx]
        
        print(f"\n🏆 MEJOR RESULTADO:")
        print(f"  💧 V0 óptimo: {best_point['V0']:,.1f} Hm³")
        print(f"  ⚡ Energía máxima: {best_point['total_energy']:,.1f} MWh")
        
        print(f"\n📊 ESTADÍSTICAS ENERGÍA:")
        print(f"  📈 Máximo: {np.max(optimal_energies):,.1f} MWh")
        print(f"  📉 Mínimo: {np.min(optimal_energies):,.1f} MWh")
        print(f"  📊 Promedio: {np.mean(optimal_energies):,.1f} MWh")
        print(f"  📏 Rango: {np.max(optimal_energies) - np.min(optimal_energies):,.1f} MWh")
        
        # Tabla resumen compacta
        print(f"\n📋 RESUMEN COMPACTO:")
        print("V0 (Hm³)     Energía (MWh)    Estado")
        print("-" * 40)
        for fp in feasible_points[:10]:  # Mostrar solo primeros 10
            print(f"{fp['V0']:>8.1f}     {fp['total_energy']:>10,.1f}     ✅")
        if len(feasible_points) > 10:
            print(f"... y {len(feasible_points)-10} puntos más")
    
    print("=" * 80)

def parse_years(s: str) -> List[int]:
    # ejemplo: "1960-1963" -> [1960, 1961, 1962, 1963]; "1960,1962" -> [1960,1062]
    if "-" in s:
        a, b = s.split("-")
        a, b = int(a), int(b)
        return list(range(min(a, b), max(a, b) + 1))
    return [int(x) for x in s.split(",")]


def print_banner():
    """Muestra el banner de bienvenida del sistema."""
    print("=" * 70)
    print("🌊 EMBALSE DEL LAJA - Sistema de Optimización Modular 🌊")
    print("=" * 70)
    print("📊 Modos disponibles:")
    print("  1️⃣  Determinístico - Optimización con datos históricos")
    print("  2️⃣  Monte Carlo - Simulación estocástica con bootstrap")
    print("  3️⃣  Sensibilidad - Análisis paramétrico de V0")
    print("  4️⃣  Modo CLI - Usar argumentos de línea de comandos")
    print("  0️⃣  Salir")
    print("=" * 70)


def get_user_input(prompt: str, default=None, input_type=str):
    """Solicita input del usuario con validación y valor por defecto."""
    while True:
        try:
            if default is not None:
                user_input = input(f"{prompt} [{default}]: ").strip()
                if not user_input:
                    return default
            else:
                user_input = input(f"{prompt}: ").strip()
                if not user_input:
                    print("❌ Este campo es obligatorio. Intenta nuevamente.")
                    continue
            
            if input_type == int:
                return int(user_input)
            elif input_type == float:
                return float(user_input)
            else:
                return user_input
                
        except ValueError:
            print(f"❌ Entrada inválida. Ingresa un {input_type.__name__} válido.")


def get_years_interactive() -> List[int]:
    """Permite al usuario seleccionar años de manera interactiva."""
    print("\n📅 Selección de años:")
    print("  Ejemplos: '1985' (un año), '1980-1985' (rango), '1980,1985,1990' (específicos)")
    
    # Crear rango completo de años disponibles
    min_year, max_year = min(YEARS_HORIZON), max(YEARS_HORIZON)
    available_years = list(range(min_year, max_year + 1))
    
    while True:
        try:
            years_str = get_user_input(f"Años a simular (disponibles: {min_year}-{max_year})",
                                     default="1985")
            years = parse_years(years_str)
            
            # Validar que los años estén en el rango disponible
            invalid_years = [y for y in years if y not in available_years]
            if invalid_years:
                print(f"❌ Años fuera del rango disponible: {invalid_years}")
                continue
                
            return years
            
        except Exception as e:
            print(f"❌ Error procesando años: {e}")
def run_interactive_deterministic():
    """Ejecuta modo determinístico de forma interactiva."""
    print("\n🎯 MODO DETERMINÍSTICO")
    print("Optimización con datos históricos reales.")
    
    years = get_years_interactive()
    V0 = get_user_input("💧 Volumen inicial V0 (Hm³)", default=1400.0, input_type=float)
    
    # Pregunta si usar modo robusto para secuencias largas
    robust = False
    if len(years) > 3:
        robust_input = get_user_input("🛡️  ¿Usar modo robusto? (recomendado para secuencias largas) [s/N]", 
                                    default="N", input_type=str)
        robust = robust_input.lower() in ['s', 'sí', 'si', 'y', 'yes']
    
    mode_text = "robusto 🛡️" if robust else "estándar 📊"
    print(f"\n🚀 Ejecutando optimización determinística {mode_text}...")
    print(f"📋 Configuración: años={years}, V0={V0} Hm³")
    if robust:
        print("🛡️  Modo robusto: aplicará recuperación automática ante infactibilidades")
    
    run_deterministic(years=years, V0=V0, robust=robust)


def run_interactive_montecarlo():
    """Ejecuta modo Monte Carlo de forma interactiva."""
    print("\n🎲 MODO MONTE CARLO")
    print("Simulación estocástica con muestreo bootstrap.")
    
    years = get_years_interactive()
    V0 = get_user_input("💧 Volumen inicial V0 (Hm³)", default=50.0, input_type=float)
    N = get_user_input("🔢 Número de escenarios", default=50, input_type=int)
    seed = get_user_input("🌱 Semilla aleatoria", default=42, input_type=int)
    block_len = get_user_input("📦 Longitud de bloques bootstrap", default=3, input_type=int)
    
    print("\n🔊 Ruido lognormal:")
    print("  0.0 = Sin ruido, 0.1 = Ruido bajo, 0.3 = Ruido alto")
    noise = get_user_input("📊 Sigma del ruido lognormal", default=0.0, input_type=float)
    
    print(f"\n🚀 Ejecutando simulación Monte Carlo...")
    print(f"📋 Configuración: N={N}, V0={V0}, seed={seed}, block={block_len}, noise={noise}")
    
    run_montecarlo(n_scenarios=N, years=years, V0=V0, seed=seed, 
                  block_len=block_len, noise_sigma=noise)


def run_interactive_sensitivity():
    """Ejecuta análisis de sensibilidad de forma interactiva."""
    print("\n🔍 MODO SENSIBILIDAD")
    print("Análisis paramétrico del volumen inicial V0.")
    
    years = get_years_interactive()
    
    print("\n💧 Configuración del barrido de V0:")
    V0_min = get_user_input("Volumen mínimo V0 (Hm³)", default=20.0, input_type=float)
    V0_max = get_user_input("Volumen máximo V0 (Hm³)", default=100.0, input_type=float)
    V0_step = get_user_input("Paso del barrido (Hm³)", default=10.0, input_type=float)
    
    print("\n🎲 Configuración estocástica:")
    seed = get_user_input("🌱 Semilla aleatoria", default=42, input_type=int)
    block_len = get_user_input("📦 Longitud de bloques bootstrap", default=3, input_type=int)
    noise = get_user_input("📊 Sigma del ruido lognormal", default=0.0, input_type=float)
    
    print(f"\n🚀 Ejecutando análisis de sensibilidad...")
    print(f"📋 Configuración: V0=[{V0_min}, {V0_max}] step={V0_step}")
    
    run_sensitivity(years=years, v0_min=V0_min, v0_max=V0_max, v0_step=V0_step,
                   seed=seed, block_len=block_len, noise_sigma=noise)


def interactive_mode():
    """Modo interactivo principal."""
    while True:
        print_banner()
        
        try:
            choice = get_user_input("Selecciona una opción", input_type=int)
            
            if choice == 0:
                print("👋 ¡Hasta luego!")
                break
            elif choice == 1:
                run_interactive_deterministic()
            elif choice == 2:
                run_interactive_montecarlo()
            elif choice == 3:
                run_interactive_sensitivity()
            elif choice == 4:
                print("\n📋 MODO CLI - Ejemplos de uso:")
                print("# Determinístico:")
                print("python src/main.py det --years 1985 --V0 50")
                print("\n# Monte Carlo:")
                print("python src/main.py mc --years 1985 --V0 50 --N 100 --seed 42")
                print("\n# Sensibilidad:")
                print("python src/main.py sens --years 1985 --V0min 20 --V0max 100 --V0step 10")
                print("\nUsa 'python src/main.py --help' para más detalles.")
                break
            else:
                print("❌ Opción inválida. Selecciona un número del 0 al 4.")
                
        except KeyboardInterrupt:
            print("\n\n👋 Saliendo del programa...")
            break
        except Exception as e:
            print(f"❌ Error inesperado: {e}")
        
        # Pausa antes de volver al menú
        input("\n⏸️  Presiona Enter para continuar...")


if __name__ == "__main__":
    # Si no hay argumentos, ejecutar modo interactivo
    if len(sys.argv) == 1:
        interactive_mode()
    else:
        # Modo CLI tradicional
        p = argparse.ArgumentParser(
            description="Control de ejecución — Embalse del Laja",
            epilog="💡 Ejecuta sin argumentos para modo interactivo: python src/main.py"
        )
        sub = p.add_subparsers(dest="cmd", required=True)

        # determinístico
        pd = sub.add_parser("det", help="Correr determinístico")
        pd.add_argument("--years", type=str, default="1985")
        pd.add_argument("--V0", type=float, default=50.0)

        # montecarlo
        pm = sub.add_parser("mc", help="Correr Monte Carlo")
        pm.add_argument("--years", type=str, default="1985")
        pm.add_argument("--V0", type=float, default=50.0)
        pm.add_argument("--N", type=int, default=50)
        pm.add_argument("--seed", type=int, default=42)
        pm.add_argument("--block", type=int, default=3)
        pm.add_argument("--noise", type=float, default=0.0,
                       help="sigma lognormal (0=sin ruido)")

        # sensibilidad
        ps = sub.add_parser("sens", help="Barrido de sensibilidad en V0")
        ps.add_argument("--years", type=str, default="1985")
        ps.add_argument("--V0min", type=float, default=20.0)
        ps.add_argument("--V0max", type=float, default=100.0)
        ps.add_argument("--V0step", type=float, default=10.0)
        ps.add_argument("--seed", type=int, default=42)
        ps.add_argument("--block", type=int, default=3)
        ps.add_argument("--noise", type=float, default=0.0)

        try:
            args = p.parse_args()
            years = parse_years(args.years)

            if args.cmd == "det":
                run_deterministic(years=years, V0=args.V0)

            elif args.cmd == "mc":
                run_montecarlo(
                    n_scenarios=args.N,
                    years=years,
                    V0=args.V0,
                    seed=args.seed,
                    block_len=args.block,
                    noise_sigma=args.noise
                )

            elif args.cmd == "sens":
                run_sensitivity(
                    years=years,
                    v0_min=args.V0min,
                    v0_max=args.V0max,
                    v0_step=args.V0step,
                    seed=args.seed,
                    block_len=args.block,
                    noise_sigma=args.noise
                )
        except KeyboardInterrupt:
            print("\n👋 Ejecución cancelada por el usuario.")
        except Exception as e:
            print(f"❌ Error en la ejecución: {e}")
            sys.exit(1)
