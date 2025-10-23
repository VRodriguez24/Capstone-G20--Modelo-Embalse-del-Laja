"""
=====================================
MÓDULO DE ANÁLISIS DE SENSIBILIDAD
=====================================

Sistema avanzado de análisis de sensibilidad para el Embalse del Laja.
Evalúa el impacto de parámetros críticos en diferentes metodologías de modelado
con énfasis en cambio climático y variabilidad hidrológica.

FUNCIONALIDADES PRINCIPALES:
✅ Análisis comparativo entre caso_base.py, model.py y montecarlo.py
✅ Evaluación sistemática de escenarios de volumen inicial
✅ Interpretación automática de resultados y sensibilidades
✅ Exportación de resultados con análisis estadístico
✅ Escenarios de cambio climático integrados

PARÁMETROS DE SENSIBILIDAD:
- Volumen inicial (V0): 800-2200 Hm³ (impacto cambio climático)

Autor: Capstone G20 - UC
Versión: 2.0 - Optimizada e Interpretativa
"""

# Importaciones estándar
import time
import sys
import os
from pathlib import Path
from typing import Dict, List, Any
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Configuración de visualización
plt.style.use('default')
sns.set_palette("husl")
plt.rcParams['figure.figsize'] = (12, 8)
plt.rcParams['font.size'] = 10

# Importaciones del proyecto
sys.path.append('src')

# =============================
# CONFIGURACIÓN DE PARÁMETROS
# =============================

# Escenarios de volumen inicial: Impacto del cambio climático
VOLUME_SCENARIOS = {
    "Muy_Seco": 800.0,      # Sequía extrema (-43% del normal)
    "Seco": 1000.0,         # Año seco típico (-29% del normal)
    "Normal": 1400.0,       # Condiciones históricas promedio (referencia)
    "Humedo": 1800.0,       # Año húmedo típico (+29% del normal)
    "Muy_Humedo": 2200.0    # Condiciones excepcionales (+57% del normal)
}

# Años de análisis histórico
ANALYSIS_YEARS = list(range(1980, 2021))  # 41 años de datos confiables

# Configuración Monte Carlo
MONTECARLO_N_SCENARIOS = 10  # Número de escenarios estocásticos


class SensitivityAnalysisEngine:
    """
    Motor principal del análisis de sensibilidad con interpretación automática.
    """
    
    def __init__(self, output_dir: str = "resultados"):
        """
        Inicializa el motor de análisis.
        
        Args:
            output_dir: Directorio para guardar resultados
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Crear subdirectorios por tipo de análisis
        (self.output_dir / "caso_base").mkdir(exist_ok=True)
        (self.output_dir / "model").mkdir(exist_ok=True)
        (self.output_dir / "montecarlo").mkdir(exist_ok=True)
    
    def analyze_caso_base(self, verbose: bool = True) -> Dict[str, Any]:
        """
        Análisis de sensibilidad sobre caso_base.py para todos los años.
        
        Args:
            verbose: Mostrar progreso detallado
            
        Returns:
            Dict con resultados completos del análisis
        """
        if verbose:
            print("\n📊 ANÁLISIS DE SENSIBILIDAD: CASO_BASE.PY")
            print("=" * 60)
            print("🎯 Metodología: Análisis histórico determinístico")
            print(f"📅 Años analizados: {len(ANALYSIS_YEARS)} años ({min(ANALYSIS_YEARS)}-{max(ANALYSIS_YEARS)})")
            print(f"🌊 Escenarios de volumen: {len(VOLUME_SCENARIOS)}")
            print("=" * 60)
        
        try:
            # Importar módulos necesarios
            from caso_base import run_single_year_analysis
            
            results = {}
            all_results = []
            start_time = time.time()
            
            for scenario_name, volume in VOLUME_SCENARIOS.items():
                if verbose:
                    print(f"\n🔄 Analizando escenario: {scenario_name} (V0={volume:.0f} Hm³)")
                
                scenario_results = []
                scenario_energies = []
                scenario_volumes = []
                
                # Ejecutar para todos los años
                for i, year in enumerate(ANALYSIS_YEARS):
                    if verbose and i % 10 == 0:
                        progress = (i + 1) / len(ANALYSIS_YEARS) * 100
                        print(f"   📈 Progreso: {progress:.1f}% (año {year})")
                    
                    try:
                        # Ejecutar caso base para el año específico
                        year_result = run_single_year_analysis(
                            target_year=year,
                            volume_inicial=volume,
                            verbose=False
                        )
                        
                        if year_result and year_result.get('status') == 'OK':
                            scenario_results.append(year_result)
                            scenario_energies.append(year_result.get('energy_total', 0))
                            scenario_volumes.append(year_result.get('volume_final', 0))
                            
                    except Exception as e:
                        if verbose and i < 3:  # Solo mostrar primeros errores
                            print(f"      ❌ Error año {year}: {e}")
                
                # Calcular estadísticas del escenario
                if scenario_energies:
                    scenario_stats = {
                        'scenario_name': scenario_name,
                        'volume_inicial': volume,
                        'n_years_successful': len(scenario_energies),
                        'energy_mean': np.mean(scenario_energies),
                        'energy_std': np.std(scenario_energies),
                        'energy_min': np.min(scenario_energies),
                        'energy_max': np.max(scenario_energies),
                        'volume_final_mean': np.mean(scenario_volumes),
                        'volume_final_std': np.std(scenario_volumes),
                        'success_rate': len(scenario_energies) / len(ANALYSIS_YEARS) * 100
                    }
                    
                    results[scenario_name] = scenario_stats
                    all_results.extend(scenario_results)
                    
                    if verbose:
                        print(f"   ✅ Completado: {len(scenario_energies)}/{len(ANALYSIS_YEARS)} años")
                        print(f"      ⚡ Energía promedio: {scenario_stats['energy_mean']:,.0f} MWh")
                        print(f"      💧 Volumen final promedio: {scenario_stats['volume_final_mean']:,.0f} Hm³")
            
            # Análisis de sensibilidad e interpretación
            analysis_summary = self._interpret_caso_base_results(results, verbose)
            
            # Guardar resultados
            timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
            
            # Guardar resumen estadístico
            df_summary = pd.DataFrame(results).T
            summary_file = self.output_dir / "caso_base" / f"sensitivity_summary_{timestamp}.csv"
            df_summary.to_csv(summary_file)
            
            # Guardar resultados detallados
            df_detailed = pd.DataFrame(all_results)
            detail_file = self.output_dir / "caso_base" / f"sensitivity_detailed_{timestamp}.csv"
            df_detailed.to_csv(detail_file, index=False)
            
            # Generar gráficos interpretativos
            plotter = SensitivityPlotter(str(self.output_dir))
            plotter.create_sensitivity_plots(
                {'results': results}, 'caso_base', timestamp
            )
            
            execution_time = time.time() - start_time
            
            if verbose:
                print(f"\n📁 RESULTADOS GUARDADOS:")
                print(f"   📊 Resumen: {summary_file.name}")
                print(f"   📋 Detallado: {detail_file.name}")
                print(f"⏱️ Tiempo total: {execution_time:.1f}s")
            
            return {
                'method': 'caso_base',
                'results': results,
                'analysis_summary': analysis_summary,
                'files_generated': [str(summary_file), str(detail_file)],
                'execution_time': execution_time
            }
            
        except Exception as e:
            print(f"❌ Error en análisis caso_base: {e}")
            return {'method': 'caso_base', 'status': 'ERROR', 'error': str(e)}
    
    def analyze_model(self, verbose: bool = True) -> Dict[str, Any]:
        """
        Análisis de sensibilidad sobre model.py para todos los años.
        
        Args:
            verbose: Mostrar progreso detallado
            
        Returns:
            Dict con resultados completos del análisis
        """
        if verbose:
            print("\n🏗️ ANÁLISIS DE SENSIBILIDAD: MODEL.PY")
            print("=" * 60)
            print("🎯 Metodología: Optimización directa por año")
            print(f"📅 Años analizados: {len(ANALYSIS_YEARS)} años ({min(ANALYSIS_YEARS)}-{max(ANALYSIS_YEARS)})")
            print(f"🌊 Escenarios de volumen: {len(VOLUME_SCENARIOS)}")
            print("=" * 60)
        
        try:
            # Importar módulos necesarios
            from model import build_model_for_one_year
            import gurobipy as gp
            
            results = {}
            all_results = []
            start_time = time.time()
            
            for scenario_name, volume in VOLUME_SCENARIOS.items():
                if verbose:
                    print(f"\n🔄 Analizando escenario: {scenario_name} (V0={volume:.0f} Hm³)")
                
                scenario_energies = []
                scenario_volumes = []
                scenario_years = []
                
                # Ejecutar para todos los años
                for i, year in enumerate(ANALYSIS_YEARS):
                    if verbose and i % 10 == 0:
                        progress = (i + 1) / len(ANALYSIS_YEARS) * 100
                        print(f"   📈 Progreso: {progress:.1f}% (año {year})")
                    
                    try:
                        # Construir y resolver modelo
                        model = build_model_for_one_year(target_year=year, V0=volume)
                        model.setParam('OutputFlag', 0)  # Silenciar Gurobi
                        model.optimize()
                        
                        if model.status == gp.GRB.OPTIMAL:
                            energy = model.objVal
                            # Obtener volumen final
                            V_vars = model._V
                            v_final = V_vars[11].x  # Noviembre (último mes del período)
                            
                            scenario_energies.append(energy)
                            scenario_volumes.append(v_final)
                            scenario_years.append(year)
                            
                            all_results.append({
                                'scenario': scenario_name,
                                'volume_inicial': volume,
                                'year': year,
                                'energy_total': energy,
                                'volume_final': v_final,
                                'status': 'OK'
                            })
                        
                        model.dispose()  # Liberar memoria
                        
                    except Exception as e:
                        if verbose and i < 3:  # Solo mostrar primeros errores
                            print(f"      ❌ Error año {year}: {e}")
                        
                        all_results.append({
                            'scenario': scenario_name,
                            'volume_inicial': volume,
                            'year': year,
                            'status': 'ERROR',
                            'error': str(e)
                        })
                
                # Calcular estadísticas del escenario
                if scenario_energies:
                    scenario_stats = {
                        'scenario_name': scenario_name,
                        'volume_inicial': volume,
                        'n_years_successful': len(scenario_energies),
                        'energy_mean': np.mean(scenario_energies),
                        'energy_std': np.std(scenario_energies),
                        'energy_min': np.min(scenario_energies),
                        'energy_max': np.max(scenario_energies),
                        'volume_final_mean': np.mean(scenario_volumes),
                        'volume_final_std': np.std(scenario_volumes),
                        'success_rate': len(scenario_energies) / len(ANALYSIS_YEARS) * 100
                    }
                    
                    results[scenario_name] = scenario_stats
                    
                    if verbose:
                        print(f"   ✅ Completado: {len(scenario_energies)}/{len(ANALYSIS_YEARS)} años")
                        print(f"      ⚡ Energía promedio: {scenario_stats['energy_mean']:,.0f} MWh")
                        print(f"      💧 Volumen final promedio: {scenario_stats['volume_final_mean']:,.0f} Hm³")
            
            # Análisis de sensibilidad e interpretación
            analysis_summary = self._interpret_model_results(results, verbose)
            
            # Guardar resultados
            timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
            
            # Guardar resumen estadístico
            df_summary = pd.DataFrame(results).T
            summary_file = self.output_dir / "model" / f"sensitivity_summary_{timestamp}.csv"
            df_summary.to_csv(summary_file)
            
            # Guardar resultados detallados
            df_detailed = pd.DataFrame(all_results)
            detail_file = self.output_dir / "model" / f"sensitivity_detailed_{timestamp}.csv"
            df_detailed.to_csv(detail_file, index=False)
            
            # Generar gráficos interpretativos
            plotter = SensitivityPlotter(str(self.output_dir))
            generated_plots = plotter.create_sensitivity_plots(
                {'results': results}, 'model', timestamp
            )
            
            execution_time = time.time() - start_time
            
            if verbose:
                print(f"\n📁 RESULTADOS GUARDADOS:")
                print(f"   📊 Resumen: {summary_file.name}")
                print(f"   📋 Detallado: {detail_file.name}")
                print(f"⏱️ Tiempo total: {execution_time:.1f}s")
            
            return {
                'method': 'model',
                'results': results,
                'analysis_summary': analysis_summary,
                'files_generated': [str(summary_file), str(detail_file)],
                'execution_time': execution_time
            }
            
        except Exception as e:
            print(f"❌ Error en análisis model: {e}")
            return {'method': 'model', 'status': 'ERROR', 'error': str(e)}
    
    def analyze_montecarlo(self, verbose: bool = True) -> Dict[str, Any]:
        """
        Análisis de sensibilidad sobre montecarlo.py con escenarios estocásticos.
        
        Args:
            verbose: Mostrar progreso detallado
            
        Returns:
            Dict con resultados completos del análisis
        """
        if verbose:
            print("\n🎲 ANÁLISIS DE SENSIBILIDAD: MONTECARLO.PY")
            print("=" * 60)
            print("🎯 Metodología: Simulación estocástica")
            print(f"🎲 Escenarios por volumen: {MONTECARLO_N_SCENARIOS}")
            print(f"🌊 Escenarios de volumen: {len(VOLUME_SCENARIOS)}")
            print("=" * 60)
        
        try:
            # Importar módulos necesarios
            from montecarlo import HybridSimulator
            
            results = {}
            all_results = []
            start_time = time.time()
            
            for scenario_name, volume in VOLUME_SCENARIOS.items():
                if verbose:
                    print(f"\n🔄 Analizando escenario: {scenario_name} (V0={volume:.0f} Hm³)")
                    print(f"   🎲 Ejecutando {MONTECARLO_N_SCENARIOS} simulaciones estocásticas...")
                
                try:
                    # Crear simulador
                    simulator = HybridSimulator()
                    
                    # Ejecutar simulación Monte Carlo
                    mc_results = simulator.run_simulation(
                        start_year=1990,  # Año base representativo
                        n_years=5,       # 5 años de simulación por escenario
                        V0=volume,
                        n_scenarios=MONTECARLO_N_SCENARIOS,
                        block_len=3,
                        verbose=False
                    )
                    
                    if mc_results['successful_scenarios']:
                        # Extraer estadísticas
                        energies = [s['total_energy'] for s in mc_results['successful_scenarios']]
                        final_volumes = [s['final_volume'] for s in mc_results['successful_scenarios']]
                        
                        scenario_stats = {
                            'scenario_name': scenario_name,
                            'volume_inicial': volume,
                            'n_scenarios_successful': len(energies),
                            'energy_mean': np.mean(energies),
                            'energy_std': np.std(energies),
                            'energy_min': np.min(energies),
                            'energy_max': np.max(energies),
                            'volume_final_mean': np.mean(final_volumes),
                            'volume_final_std': np.std(final_volumes),
                            'success_rate': mc_results['success_rate']
                        }
                        
                        results[scenario_name] = scenario_stats
                        
                        # Guardar resultados detallados
                        for i, scenario in enumerate(mc_results['successful_scenarios']):
                            all_results.append({
                                'scenario': scenario_name,
                                'volume_inicial': volume,
                                'simulation_id': i,
                                'energy_total': scenario['total_energy'],
                                'volume_final': scenario['final_volume'],
                                'status': 'OK'
                            })
                        
                        if verbose:
                            print(f"   ✅ Completado: {len(energies)}/{MONTECARLO_N_SCENARIOS} simulaciones")
                            print(f"      ⚡ Energía promedio: {scenario_stats['energy_mean']:,.0f} ± {scenario_stats['energy_std']:,.0f} MWh")
                            print(f"      💧 Volumen final promedio: {scenario_stats['volume_final_mean']:,.0f} ± {scenario_stats['volume_final_std']:,.0f} Hm³")
                            print(f"      📊 Tasa de éxito: {scenario_stats['success_rate']:.1f}%")
                    
                    else:
                        if verbose:
                            print(f"   ❌ No se obtuvieron simulaciones exitosas")
                        
                        results[scenario_name] = {
                            'scenario_name': scenario_name,
                            'volume_inicial': volume,
                            'n_scenarios_successful': 0,
                            'success_rate': 0.0,
                            'status': 'NO_SUCCESSFUL_SCENARIOS'
                        }
                
                except Exception as e:
                    if verbose:
                        print(f"   ❌ Error: {e}")
                    
                    results[scenario_name] = {
                        'scenario_name': scenario_name,
                        'volume_inicial': volume,
                        'status': 'ERROR',
                        'error': str(e)
                    }
            
            # Análisis de sensibilidad e interpretación
            analysis_summary = self._interpret_montecarlo_results(results, verbose)
            
            # Guardar resultados
            timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
            
            # Guardar resumen estadístico
            df_summary = pd.DataFrame(results).T
            summary_file = self.output_dir / "montecarlo" / f"sensitivity_summary_{timestamp}.csv"
            df_summary.to_csv(summary_file)
            
            # Guardar resultados detallados si existen
            if all_results:
                df_detailed = pd.DataFrame(all_results)
                detail_file = self.output_dir / "montecarlo" / f"sensitivity_detailed_{timestamp}.csv"
                df_detailed.to_csv(detail_file, index=False)
            else:
                detail_file = None
            
            # Generar gráficos interpretativos
            plotter = SensitivityPlotter(str(self.output_dir))
            plotter.create_sensitivity_plots(
                {'results': results}, 'montecarlo', timestamp
            )
            
            execution_time = time.time() - start_time
            
            if verbose:
                print(f"\n📁 RESULTADOS GUARDADOS:")
                print(f"   📊 Resumen: {summary_file.name}")
                if detail_file:
                    print(f"   📋 Detallado: {detail_file.name}")
                print(f"⏱️ Tiempo total: {execution_time:.1f}s")
            
            return {
                'method': 'montecarlo',
                'results': results,
                'analysis_summary': analysis_summary,
                'files_generated': [str(summary_file)] + ([str(detail_file)] if detail_file else []),
                'execution_time': execution_time
            }
            
        except Exception as e:
            print(f"❌ Error en análisis montecarlo: {e}")
            return {'method': 'montecarlo', 'status': 'ERROR', 'error': str(e)}
    
    def _interpret_caso_base_results(self, results: Dict, verbose: bool = True) -> Dict[str, Any]:
        """Interpreta y analiza los resultados del caso base."""
        if not results:
            return {'interpretation': 'No hay resultados para interpretar'}
        
        # Extraer energías promedio para análisis de sensibilidad
        scenarios = list(results.keys())
        energies = [results[s]['energy_mean'] for s in scenarios]
        volumes_inicial = [results[s]['volume_inicial'] for s in scenarios]
        
        # Calcular sensibilidad
        energy_range = max(energies) - min(energies)
        volume_range = max(volumes_inicial) - min(volumes_inicial)
        sensitivity = energy_range / volume_range if volume_range > 0 else 0
        
        # Encontrar escenario más eficiente
        best_scenario = max(scenarios, key=lambda s: results[s]['energy_mean'])
        worst_scenario = min(scenarios, key=lambda s: results[s]['energy_mean'])
        
        interpretation = {
            'sensitivity_MWh_per_Hm3': sensitivity,
            'energy_range_MWh': energy_range,
            'volume_range_Hm3': volume_range,
            'best_scenario': best_scenario,
            'worst_scenario': worst_scenario,
            'best_energy': results[best_scenario]['energy_mean'],
            'worst_energy': results[worst_scenario]['energy_mean'],
            'relative_improvement': (results[best_scenario]['energy_mean'] - results[worst_scenario]['energy_mean']) / results[worst_scenario]['energy_mean'] * 100
        }
        
        if verbose:
            print(f"\n📊 INTERPRETACIÓN - CASO BASE:")
            print("=" * 50)
            print(f"🎯 Sensibilidad: {sensitivity:.2f} MWh por Hm³ adicional")
            print(f"📈 Rango de energía: {energy_range:,.0f} MWh")
            print(f"🏆 Mejor escenario: {best_scenario} ({results[best_scenario]['energy_mean']:,.0f} MWh)")
            print(f"📉 Peor escenario: {worst_scenario} ({results[worst_scenario]['energy_mean']:,.0f} MWh)")
            print(f"📊 Mejora relativa: {interpretation['relative_improvement']:.1f}%")
        
        return interpretation
    
    def _interpret_model_results(self, results: Dict, verbose: bool = True) -> Dict[str, Any]:
        """Interpreta y analiza los resultados del modelo directo."""
        if not results:
            return {'interpretation': 'No hay resultados para interpretar'}
        
        # Extraer energías promedio para análisis de sensibilidad
        scenarios = list(results.keys())
        energies = [results[s]['energy_mean'] for s in scenarios]
        volumes_inicial = [results[s]['volume_inicial'] for s in scenarios]
        
        # Calcular sensibilidad
        energy_range = max(energies) - min(energies)
        volume_range = max(volumes_inicial) - min(volumes_inicial)
        sensitivity = energy_range / volume_range if volume_range > 0 else 0
        
        # Encontrar escenario más eficiente
        best_scenario = max(scenarios, key=lambda s: results[s]['energy_mean'])
        worst_scenario = min(scenarios, key=lambda s: results[s]['energy_mean'])
        
        interpretation = {
            'sensitivity_MWh_per_Hm3': sensitivity,
            'energy_range_MWh': energy_range,
            'volume_range_Hm3': volume_range,
            'best_scenario': best_scenario,
            'worst_scenario': worst_scenario,
            'best_energy': results[best_scenario]['energy_mean'],
            'worst_energy': results[worst_scenario]['energy_mean'],
            'relative_improvement': (results[best_scenario]['energy_mean'] - results[worst_scenario]['energy_mean']) / results[worst_scenario]['energy_mean'] * 100
        }
        
        if verbose:
            print(f"\n🏗️ INTERPRETACIÓN - MODEL.PY:")
            print("=" * 50)
            print(f"🎯 Sensibilidad: {sensitivity:.2f} MWh por Hm³ adicional")
            print(f"📈 Rango de energía: {energy_range:,.0f} MWh")
            print(f"🏆 Mejor escenario: {best_scenario} ({results[best_scenario]['energy_mean']:,.0f} MWh)")
            print(f"📉 Peor escenario: {worst_scenario} ({results[worst_scenario]['energy_mean']:,.0f} MWh)")
            print(f"📊 Mejora relativa: {interpretation['relative_improvement']:.1f}%")
        
        return interpretation
    
    def _interpret_montecarlo_results(self, results: Dict, verbose: bool = True) -> Dict[str, Any]:
        """Interpreta y analiza los resultados de Monte Carlo."""
        successful_results = {k: v for k, v in results.items() 
                            if v.get('n_scenarios_successful', 0) > 0}
        
        if not successful_results:
            return {'interpretation': 'No hay resultados exitosos para interpretar'}
        
        # Extraer energías promedio para análisis de sensibilidad
        scenarios = list(successful_results.keys())
        energies = [successful_results[s]['energy_mean'] for s in scenarios]
        volumes_inicial = [successful_results[s]['volume_inicial'] for s in scenarios]
        uncertainties = [successful_results[s]['energy_std'] for s in scenarios]
        
        # Calcular sensibilidad
        energy_range = max(energies) - min(energies)
        volume_range = max(volumes_inicial) - min(volumes_inicial)
        sensitivity = energy_range / volume_range if volume_range > 0 else 0
        
        # Encontrar escenario más eficiente
        best_scenario = max(scenarios, key=lambda s: successful_results[s]['energy_mean'])
        worst_scenario = min(scenarios, key=lambda s: successful_results[s]['energy_mean'])
        
        # Análisis de incertidumbre
        avg_uncertainty = np.mean(uncertainties)
        max_uncertainty = max(uncertainties)
        
        interpretation = {
            'sensitivity_MWh_per_Hm3': sensitivity,
            'energy_range_MWh': energy_range,
            'volume_range_Hm3': volume_range,
            'best_scenario': best_scenario,
            'worst_scenario': worst_scenario,
            'best_energy': successful_results[best_scenario]['energy_mean'],
            'worst_energy': successful_results[worst_scenario]['energy_mean'],
            'relative_improvement': (successful_results[best_scenario]['energy_mean'] - successful_results[worst_scenario]['energy_mean']) / successful_results[worst_scenario]['energy_mean'] * 100,
            'avg_uncertainty_MWh': avg_uncertainty,
            'max_uncertainty_MWh': max_uncertainty,
            'uncertainty_coefficient': avg_uncertainty / np.mean(energies) * 100 if energies else 0
        }
        
        if verbose:
            print(f"\n🎲 INTERPRETACIÓN - MONTE CARLO:")
            print("=" * 50)
            print(f"🎯 Sensibilidad: {sensitivity:.2f} MWh por Hm³ adicional")
            print(f"📈 Rango de energía: {energy_range:,.0f} MWh")
            print(f"🏆 Mejor escenario: {best_scenario} ({successful_results[best_scenario]['energy_mean']:,.0f} ± {successful_results[best_scenario]['energy_std']:,.0f} MWh)")
            print(f"📉 Peor escenario: {worst_scenario} ({successful_results[worst_scenario]['energy_mean']:,.0f} ± {successful_results[worst_scenario]['energy_std']:,.0f} MWh)")
            print(f"📊 Mejora relativa: {interpretation['relative_improvement']:.1f}%")
            print(f"🎲 Incertidumbre promedio: {avg_uncertainty:,.0f} MWh ({interpretation['uncertainty_coefficient']:.1f}%)")
        
        return interpretation


class SensitivityPlotter:
    """
    Generador de gráficos interpretativos para análisis de sensibilidad.
    Se enfoca en el resumen de datos (summary) para crear visualizaciones claras.
    """
    
    def __init__(self, output_dir: str = "resultados"):
        """
        Inicializa el generador de gráficos.
        
        Args:
            output_dir: Directorio base donde guardar gráficos
        """
        self.output_dir = Path(output_dir)
        
        # Configurar colores por escenario
        self.colors = {
            'Muy_Seco': '#d62728',      # Rojo
            'Seco': '#ff7f0e',          # Naranja
            'Normal': '#2ca02c',        # Verde
            'Humedo': '#1f77b4',        # Azul
            'Muy_Humedo': '#9467bd'     # Morado
        }
    
    def create_sensitivity_plots(self, results: Dict, method: str, timestamp: str):
        """
        Crea gráficos de sensibilidad basados en el resumen de resultados.
        
        Args:
            results: Resultados del análisis de sensibilidad
            method: Método usado ('caso_base', 'model', 'montecarlo')
            timestamp: Timestamp para nombres de archivo
        """
        if 'results' not in results or not results['results']:
            print("❌ No hay datos para generar gráficos")
            return []
        
        # Convertir resultados a DataFrame
        df_summary = pd.DataFrame(results['results']).T
        
        # Crear directorio para gráficos
        plots_dir = self.output_dir / method / "plots"
        plots_dir.mkdir(exist_ok=True)
        
        generated_plots = []
        
        try:
            # 1. Gráfico de sensibilidad principal
            plot1 = self._plot_main_sensitivity(df_summary, method, plots_dir, timestamp)
            if plot1:
                generated_plots.append(plot1)
            
            # 2. Gráfico de comparación energía vs volumen
            plot2 = self._plot_energy_vs_volume(df_summary, method, plots_dir, timestamp)
            if plot2:
                generated_plots.append(plot2)
            
            # 3. Gráfico de variabilidad (solo si hay datos de desviación)
            if 'energy_std' in df_summary.columns:
                plot3 = self._plot_variability(df_summary, method, plots_dir, timestamp)
                if plot3:
                    generated_plots.append(plot3)
            
            # 4. Dashboard de resumen
            plot4 = self._plot_summary_dashboard(df_summary, method, plots_dir, timestamp)
            if plot4:
                generated_plots.append(plot4)
            
            print(f"\n📊 GRÁFICOS GENERADOS:")
            for plot_file in generated_plots:
                print(f"   📈 {plot_file.name}")
            
            return generated_plots
            
        except Exception as e:
            print(f"❌ Error generando gráficos: {e}")
            return []
    
    def _plot_main_sensitivity(self, df: pd.DataFrame, method: str, 
                              plots_dir: Path, timestamp: str) -> Path:
        """Gráfico principal de sensibilidad: Energía vs Volumen Inicial."""
        try:
            fig, ax = plt.subplots(figsize=(12, 8))
            
            # Preparar datos
            volumes = df['volume_inicial'].astype(float)
            energies = df['energy_mean'].astype(float)
            scenarios = df['scenario_name']
            
            # Gráfico de línea con puntos
            ax.plot(volumes, energies, 'o-', linewidth=3, markersize=10, 
                   color='#2E86AB', label='Energía promedio')
            
            # Colorear puntos por escenario
            for i, (vol, energy, scenario) in enumerate(zip(volumes, energies, scenarios)):
                color = self.colors.get(scenario, '#333333')
                ax.scatter(vol, energy, s=150, color=color, 
                          edgecolor='white', linewidth=2, zorder=5)
                
                # Etiquetar puntos
                ax.annotate(f'{scenario}\n{energy:,.0f} MWh', 
                           (vol, energy), 
                           textcoords="offset points", 
                           xytext=(0,15), 
                           ha='center', fontsize=9,
                           bbox=dict(boxstyle="round,pad=0.3", 
                                   facecolor=color, alpha=0.3))
            
            # Configurar gráfico
            ax.set_xlabel('Volumen Inicial (Hm³)', fontsize=12, fontweight='bold')
            ax.set_ylabel('Energía Promedio (MWh)', fontsize=12, fontweight='bold')
            ax.set_title(f'Análisis de Sensibilidad - {method.upper()}\n' +
                        f'Impacto del Volumen Inicial en la Generación Energética', 
                        fontsize=14, fontweight='bold', pad=20)
            
            # Añadir línea de tendencia
            z = np.polyfit(volumes, energies, 1)
            p = np.poly1d(z)
            ax.plot(volumes, p(volumes), "--", alpha=0.7, color='red', 
                   label=f'Tendencia (pendiente: {z[0]:.1f} MWh/Hm³)')
            
            # Configurar grid y leyenda
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=10)
            
            # Añadir interpretación
            sensitivity = (max(energies) - min(energies)) / (max(volumes) - min(volumes))
            improvement = (max(energies) - min(energies)) / min(energies) * 100
            
            textstr = f'Sensibilidad: {sensitivity:.2f} MWh/Hm³\n'
            textstr += f'Mejora máxima: {improvement:.1f}%\n'
            textstr += f'Rango energía: {max(energies) - min(energies):,.0f} MWh'
            
            props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
            ax.text(0.02, 0.98, textstr, transform=ax.transAxes, fontsize=10,
                   verticalalignment='top', bbox=props)
            
            plt.tight_layout()
            
            # Guardar
            filename = f"sensitivity_main_{method}_{timestamp}.png"
            filepath = plots_dir / filename
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            return filepath
            
        except Exception as e:
            print(f"❌ Error en gráfico principal: {e}")
            return None
    
    def _plot_energy_vs_volume(self, df: pd.DataFrame, method: str, 
                              plots_dir: Path, timestamp: str) -> Path:
        """Gráfico de barras: Energía por escenario."""
        try:
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
            
            scenarios = df['scenario_name']
            energies = df['energy_mean'].astype(float)
            volumes_initial = df['volume_inicial'].astype(float)
            volumes_final = df['volume_final_mean'].astype(float)
            
            # Gráfico 1: Energía por escenario
            colors = [self.colors.get(scenario, '#333333') for scenario in scenarios]
            bars1 = ax1.bar(scenarios, energies, color=colors, alpha=0.8, 
                           edgecolor='black', linewidth=1)
            
            # Añadir valores en las barras
            for bar, energy in zip(bars1, energies):
                height = bar.get_height()
                ax1.text(bar.get_x() + bar.get_width()/2., height + height*0.01,
                        f'{energy:,.0f}', ha='center', va='bottom', fontweight='bold')
            
            ax1.set_title('Energía Promedio por Escenario', fontsize=12, fontweight='bold')
            ax1.set_ylabel('Energía (MWh)', fontsize=11, fontweight='bold')
            ax1.tick_params(axis='x', rotation=45)
            ax1.grid(True, alpha=0.3, axis='y')
            
            # Gráfico 2: Volúmenes inicial vs final
            x = np.arange(len(scenarios))
            width = 0.35
            
            bars2 = ax2.bar(x - width/2, volumes_initial, width, 
                           label='Volumen Inicial', color='lightblue', 
                           edgecolor='black', alpha=0.8)
            bars3 = ax2.bar(x + width/2, volumes_final, width, 
                           label='Volumen Final Promedio', color='lightcoral', 
                           edgecolor='black', alpha=0.8)
            
            ax2.set_title('Volúmenes Inicial vs Final', fontsize=12, fontweight='bold')
            ax2.set_ylabel('Volumen (Hm³)', fontsize=11, fontweight='bold')
            ax2.set_xticks(x)
            ax2.set_xticklabels(scenarios, rotation=45)
            ax2.legend()
            ax2.grid(True, alpha=0.3, axis='y')
            
            plt.suptitle(f'Análisis Comparativo - {method.upper()}', 
                        fontsize=14, fontweight='bold')
            plt.tight_layout()
            
            # Guardar
            filename = f"energy_volume_comparison_{method}_{timestamp}.png"
            filepath = plots_dir / filename
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            return filepath
            
        except Exception as e:
            print(f"❌ Error en gráfico de comparación: {e}")
            return None
    
    def _plot_variability(self, df: pd.DataFrame, method: str, 
                         plots_dir: Path, timestamp: str) -> Path:
        """Gráfico de variabilidad: Energía con barras de error."""
        try:
            fig, ax = plt.subplots(figsize=(12, 8))
            
            scenarios = df['scenario_name']
            energies_mean = df['energy_mean'].astype(float)
            energies_std = df['energy_std'].astype(float)
            energies_min = df['energy_min'].astype(float)
            energies_max = df['energy_max'].astype(float)
            
            # Gráfico de barras con barras de error
            colors = [self.colors.get(scenario, '#333333') for scenario in scenarios]
            bars = ax.bar(scenarios, energies_mean, yerr=energies_std, 
                         color=colors, alpha=0.7, capsize=5, 
                         edgecolor='black', linewidth=1)
            
            # Añadir rangos min-max como líneas
            for i, (scenario, mean, min_val, max_val) in enumerate(zip(scenarios, energies_mean, energies_min, energies_max)):
                ax.plot([i, i], [min_val, max_val], 'k-', linewidth=2, alpha=0.5)
                ax.plot([i-0.1, i+0.1], [min_val, min_val], 'k-', linewidth=2)
                ax.plot([i-0.1, i+0.1], [max_val, max_val], 'k-', linewidth=2)
            
            # Añadir valores
            for bar, mean, std in zip(bars, energies_mean, energies_std):
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + std + height*0.02,
                       f'{mean:,.0f}\n±{std:,.0f}', ha='center', va='bottom', 
                       fontweight='bold', fontsize=9)
            
            ax.set_title(f'Variabilidad de la Generación Energética - {method.upper()}\n' +
                        'Promedio ± Desviación Estándar (Rango Min-Max)', 
                        fontsize=12, fontweight='bold')
            ax.set_ylabel('Energía (MWh)', fontsize=11, fontweight='bold')
            ax.tick_params(axis='x', rotation=45)
            ax.grid(True, alpha=0.3, axis='y')
            
            # Añadir leyenda explicativa
            ax.text(0.02, 0.98, 'Barras de error: ±1 desviación estándar\nLíneas negras: Rango mín-máx', 
                   transform=ax.transAxes, fontsize=9,
                   verticalalignment='top', 
                   bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.8))
            
            plt.tight_layout()
            
            # Guardar
            filename = f"variability_analysis_{method}_{timestamp}.png"
            filepath = plots_dir / filename
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            return filepath
            
        except Exception as e:
            print(f"❌ Error en gráfico de variabilidad: {e}")
            return None
    
    def _plot_summary_dashboard(self, df: pd.DataFrame, method: str, 
                               plots_dir: Path, timestamp: str) -> Path:
        """Dashboard de resumen con múltiples métricas."""
        try:
            fig = plt.figure(figsize=(16, 12))
            gs = fig.add_gridspec(3, 3, hspace=0.3, wspace=0.3)
            
            scenarios = df['scenario_name']
            volumes_initial = df['volume_inicial'].astype(float)
            energies_mean = df['energy_mean'].astype(float)
            success_rates = df['success_rate'].astype(float)
            
            # 1. Gráfico principal (ocupa 2x2)
            ax1 = fig.add_subplot(gs[0:2, 0:2])
            colors = [self.colors.get(scenario, '#333333') for scenario in scenarios]
            
            scatter = ax1.scatter(volumes_initial, energies_mean, 
                                s=200, c=colors, alpha=0.8, edgecolor='black', linewidth=2)
            
            # Línea de tendencia
            z = np.polyfit(volumes_initial, energies_mean, 1)
            p = np.poly1d(z)
            ax1.plot(volumes_initial, p(volumes_initial), "--", alpha=0.7, color='red', linewidth=2)
            
            # Etiquetas
            for vol, energy, scenario in zip(volumes_initial, energies_mean, scenarios):
                ax1.annotate(scenario, (vol, energy), xytext=(5, 5), 
                           textcoords='offset points', fontsize=9, fontweight='bold')
            
            ax1.set_xlabel('Volumen Inicial (Hm³)', fontweight='bold')
            ax1.set_ylabel('Energía Promedio (MWh)', fontweight='bold')
            ax1.set_title(f'Sensibilidad Energética - {method.upper()}', fontweight='bold', fontsize=14)
            ax1.grid(True, alpha=0.3)
            
            # 2. Tasas de éxito (si están disponibles)
            ax2 = fig.add_subplot(gs[0, 2])
            if success_rates.nunique() > 1:  # Solo si hay variación
                ax2.bar(range(len(scenarios)), success_rates, color=colors, alpha=0.8)
                ax2.set_title('Tasa de Éxito (%)', fontweight='bold')
                ax2.set_ylim(0, 100)
            else:
                ax2.text(0.5, 0.5, f'Tasa de Éxito\nConstante:\n{success_rates.iloc[0]:.1f}%', 
                        ha='center', va='center', transform=ax2.transAxes, 
                        fontsize=12, fontweight='bold')
                ax2.set_title('Tasa de Éxito', fontweight='bold')
            ax2.set_xticks(range(len(scenarios)))
            ax2.set_xticklabels([s[:8] for s in scenarios], rotation=45, fontsize=8)
            
            # 3. Mejora relativa
            ax3 = fig.add_subplot(gs[1, 2])
            base_energy = min(energies_mean)
            improvements = [(e - base_energy) / base_energy * 100 for e in energies_mean]
            bars = ax3.bar(range(len(scenarios)), improvements, color=colors, alpha=0.8)
            ax3.set_title('Mejora Relativa (%)', fontweight='bold')
            ax3.set_xticks(range(len(scenarios)))
            ax3.set_xticklabels([s[:8] for s in scenarios], rotation=45, fontsize=8)
            ax3.axhline(y=0, color='black', linestyle='-', alpha=0.5)
            
            # 4. Estadísticas clave
            ax4 = fig.add_subplot(gs[2, :])
            ax4.axis('off')
            
            # Calcular estadísticas
            sensitivity = (max(energies_mean) - min(energies_mean)) / (max(volumes_initial) - min(volumes_initial))
            best_scenario = scenarios[energies_mean.argmax()]
            worst_scenario = scenarios[energies_mean.argmin()]
            max_improvement = (max(energies_mean) - min(energies_mean)) / min(energies_mean) * 100
            
            stats_text = f"""
            ESTADÍSTICAS CLAVE - {method.upper()}
            {'='*50}
            🎯 Sensibilidad: {sensitivity:.2f} MWh por Hm³ adicional
            🏆 Mejor escenario: {best_scenario} ({max(energies_mean):,.0f} MWh)
            📉 Peor escenario: {worst_scenario} ({min(energies_mean):,.0f} MWh)
            📊 Mejora máxima: {max_improvement:.1f}%
            📈 Rango energético: {max(energies_mean) - min(energies_mean):,.0f} MWh
            💧 Rango volumétrico: {max(volumes_initial) - min(volumes_initial):,.0f} Hm³
            """
            
            ax4.text(0.05, 0.95, stats_text, transform=ax4.transAxes, fontsize=11,
                    verticalalignment='top', fontfamily='monospace',
                    bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))
            
            plt.suptitle(f'Dashboard de Análisis de Sensibilidad - {method.upper()}', 
                        fontsize=16, fontweight='bold')
            
            # Guardar
            filename = f"dashboard_summary_{method}_{timestamp}.png"
            filepath = plots_dir / filename
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            return filepath
            
        except Exception as e:
            print(f"❌ Error en dashboard: {e}")
            return None


def climate_change_scenarios() -> Dict[str, float]:
    """
    Escenarios específicos de cambio climático para análisis futuro.
    
    Returns:
        Dict con escenarios de volumen inicial para proyecciones climáticas
    """
    return {
        'Historical_Wet': 1800.0,      # Percentil 90 histórico
        'Historical_Normal': 1400.0,   # Mediana histórica
        'Historical_Dry': 1000.0,      # Percentil 10 histórico
        'Climate_Change_Optimistic': 1200.0,  # -15% proyección moderada
        'Climate_Change_Moderate': 1000.0,    # -30% proyección intermedia
        'Climate_Change_Pessimistic': 800.0,  # -45% proyección severa
        'Extreme_Drought': 600.0,      # Sequía extrema proyectada
        'Adaptation_Enhanced': 1600.0  # Con medidas de adaptación
    }


def interactive_sensitivity_menu():
    """
    Menú interactivo principal del análisis de sensibilidad.
    """
    engine = SensitivityAnalysisEngine()
    
    while True:
        try:
            print("\n🔍 ANÁLISIS DE SENSIBILIDAD - EMBALSE DEL LAJA")
            print("=" * 60)
            print("Evaluación de impacto de parámetros en diferentes metodologías")
            
            print(f"\n📊 CONFIGURACIÓN ACTUAL:")
            print(f"   🌊 Escenarios de volumen: {len(VOLUME_SCENARIOS)}")
            print(f"   📅 Años de análisis: {len(ANALYSIS_YEARS)} años")
            print(f"   🎲 Escenarios Monte Carlo: {MONTECARLO_N_SCENARIOS}")
            
            print(f"\n🎯 OPCIONES DISPONIBLES:")
            print("1️⃣  Análisis CASO_BASE.PY (análisis histórico determinístico)")
            print("2️⃣  Análisis MODEL.PY (optimización directa)")
            print("3️⃣  Análisis MONTECARLO.PY (simulación estocástica)")
            print("4️⃣  Escenarios de cambio climático (implementación futura)")
            print("0️⃣  Salir")
            
            try:
                choice = input("\n📋 Selecciona opción [0-4]: ").strip()
            except EOFError:
                print("\n👋 ¡Hasta luego!")
                break
            
            if choice == "0":
                print("👋 ¡Hasta luego!")
                break
            
            elif choice == "1":
                print("\n" + "="*60)
                results = engine.analyze_caso_base(verbose=True)
                if results.get('status') != 'ERROR':
                    print("\n✅ ANÁLISIS CASO_BASE COMPLETADO")
                    files_count = len(results.get('files_generated', []))
                    print(f"📁 Archivos generados: {files_count}")
                try:
                    input("\n⏸️ Presiona Enter para continuar...")
                except EOFError:
                    print("\n🔄 Continuando...")
            
            elif choice == "2":
                print("\n" + "="*60)
                results = engine.analyze_model(verbose=True)
                if results.get('status') != 'ERROR':
                    print("\n✅ ANÁLISIS MODEL.PY COMPLETADO")
                    files_count = len(results.get('files_generated', []))
                    print(f"📁 Archivos generados: {files_count}")
                try:
                    input("\n⏸️ Presiona Enter para continuar...")
                except EOFError:
                    print("\n🔄 Continuando...")
            
            elif choice == "3":
                print("\n" + "="*60)
                results = engine.analyze_montecarlo(verbose=True)
                if results.get('status') != 'ERROR':
                    print("\n✅ ANÁLISIS MONTE CARLO COMPLETADO")
                    files_count = len(results.get('files_generated', []))
                    print(f"📁 Archivos generados: {files_count}")
                try:
                    input("\n⏸️ Presiona Enter para continuar...")
                except EOFError:
                    print("\n🔄 Continuando...")
            
            elif choice == "4":
                print("\n🌡️ ESCENARIOS DE CAMBIO CLIMÁTICO")
                print("=" * 50)
                print("📋 FUNCIONALIDAD PLANIFICADA:")
                print("• Análisis de proyecciones climáticas 2030-2050")
                print("• Evaluación de medidas de adaptación")
                print("• Escenarios de precipitación y temperatura")
                print("• Análisis de riesgo climático")
                scenarios_count = len(climate_change_scenarios())
                print(f"\n💡 Escenarios configurados: {scenarios_count}")
                for scenario, volume in climate_change_scenarios().items():
                    print(f"   • {scenario}: {volume:.0f} Hm³")
                print("\n🚧 Estado: Por implementar en versión futura")
                input("\n⏸️ Presiona Enter para continuar...")
            
            else:
                print("❌ Opción no válida")
            
            print("\n" + "="*60 + "\n")
            
        except KeyboardInterrupt:
            print("\n\n⏹️ Proceso interrumpido por el usuario")
            break
        except Exception as e:
            print(f"❌ Error inesperado: {e}")
            input("⏸️ Presiona Enter para continuar...")


if __name__ == "__main__":
    """
    Punto de entrada principal del análisis de sensibilidad.
    """
    print("🚀 SISTEMA DE ANÁLISIS DE SENSIBILIDAD v2.0")
    print("=" * 60)
    print("Análisis comparativo de metodologías para el Embalse del Laja")
    print("Enfoque: Variabilidad hidrológica y cambio climático")
    print("=" * 60)
    
    # Ejecutar menú interactivo
    interactive_sensitivity_menu()


# Constantes para importación en otros módulos
CLIMATE_SCENARIOS = climate_change_scenarios()