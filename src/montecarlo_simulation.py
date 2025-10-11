# src/montecarlo.py
"""
Módulo de simulación Monte Carlo para el modelo Embalse del Laja.
Implementa bootstrap por bloques y análisis estocástico.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any
from embalse import T, A_inyeccion
from data_loader import load_injections_for_year


class BlockBootstrapSampler:
    """
    Implementa bootstrap por bloques para series temporales de caudales.
    """
    
    def __init__(self, csv_path: str, random_state: int = 42):
        """
        Inicializa el sampler con datos históricos.
        
        Args:
            csv_path: Ruta al CSV con caudales históricos
            random_state: Semilla para reproducibilidad
        """
        self.csv_path = csv_path
        self.rng = np.random.default_rng(random_state)
        self.data = self._load_historical_data()
        
    def _load_historical_data(self) -> pd.DataFrame:
        """Carga datos históricos de caudales."""
        try:
            df = pd.read_csv(self.csv_path)
            return df
        except Exception as e:
            print(f"❌ Error cargando {self.csv_path}: {e}")
            return pd.DataFrame()
    
    def sample_year(self,
                    block_len: int = 3
                    ) -> Dict[Tuple[str, str, int], float]:
        """
        Genera un año de caudales usando bootstrap por bloques.
        
        Args:
            block_len: Longitud de bloques para bootstrap
            
        Returns:
            Dict con inyecciones por arco y mes
        """
        if self.data.empty:
            return {}
            
        # Obtener años disponibles
        years_available = (self.data['año'].unique() 
                          if 'año' in self.data.columns else [])
        if len(years_available) == 0:
            return {}
        
        # Bootstrap por bloques: seleccionar año aleatorio para cada bloque
        I_arc = {}
        months = list(T)
        
        for start_month in range(0, len(months), block_len):
            # Seleccionar año aleatorio para este bloque
            random_year = self.rng.choice(years_available)
            
            # Obtener meses del bloque
            block_months = months[start_month:start_month + block_len]
            
            # Cargar datos para ese año
            year_data = load_injections_for_year(self.csv_path, random_year)
            
            # Asignar valores del bloque
            for month in block_months:
                for (i, j) in A_inyeccion:
                    if (i, j, month) in year_data:
                        I_arc[(i, j, month)] = year_data[(i, j, month)]
                    else:
                        I_arc[(i, j, month)] = 0.0
        
        return I_arc
    
    def sample_year_with_noise(self, block_len: int = 3, 
                             sigma: float = 0.1) -> Dict[Tuple[str, str, int], float]:
        """
        Genera un año de caudales con ruido lognormal adicional.
        
        Args:
            block_len: Longitud de bloques para bootstrap
            sigma: Desviación estándar del ruido lognormal
            
        Returns:
            Dict con inyecciones perturbadas
        """
        base_flows = self.sample_year(block_len)
        
        # Aplicar ruido lognormal
        noisy_flows = {}
        for key, value in base_flows.items():
            if value > 0:
                # Multiplicar por factor lognormal
                noise_factor = self.rng.lognormal(mean=0, sigma=sigma)
                noisy_flows[key] = value * noise_factor
            else:
                noisy_flows[key] = value
                
        return noisy_flows


def run_single_year_montecarlo(target_year: int, n_iterations: int,
                              V0: float, seed: int) -> List[Dict[str, Any]]:
    """
    Ejecuta simulación Monte Carlo para un año específico.
    
    Args:
        target_year: Año objetivo
        n_iterations: Número de iteraciones
        V0: Volumen inicial
        seed: Semilla aleatoria
        
    Returns:
        Lista con resultados de cada iteración
    """
    from model import build_model_for_one_year
    from sensitivity import extract_kpis
    
    print(f"🎲 Monte Carlo un año | año={target_year} | N={n_iterations} | V0={V0}")
    
    # Inicializar sampler
    sampler = BlockBootstrapSampler("data/Caudales_historicos_filtrado.csv", seed)
    
    results = []
    optimal_count = 0
    
    for iteration in range(1, n_iterations + 1):
        print(f"   🎯 Iteración {iteration}/{n_iterations}", end=" ")
        
        try:
            # Generar escenario estocástico
            I_arc_scenario = sampler.sample_year(block_len=3)
            
            # Construir y optimizar modelo
            model = build_model_for_one_year(
                target_year=target_year,
                V0=V0,
                I_arc_override=I_arc_scenario
            )
            model.optimize()
            
            # Extraer KPIs
            kpis = extract_kpis(model)
            kpis['iteration'] = iteration
            
            if kpis['status'] == 2:  # GRB.OPTIMAL
                optimal_count += 1
                print(f"✅ {kpis['obj_MWh']:.1f} MWh")
            else:
                print(f"❌ Status {kpis['status']}")
            
            results.append(kpis)
            model.dispose()
            
        except Exception as e:
            print(f"❌ Error: {e}")
            results.append({
                'iteration': iteration,
                'status': -1,
                'obj_MWh': None,
                'error': str(e)
            })
    
    # Resumen final
    print(f"\n📊 Resumen Monte Carlo:")
    print(f"   ✅ Iteraciones óptimas: {optimal_count}/{n_iterations}")
    print(f"   📈 Tasa factibilidad: {optimal_count/n_iterations*100:.1f}%")
    
    if optimal_count > 0:
        optimal_values = [r['obj_MWh'] for r in results if r.get('obj_MWh')]
        print(f"   ⚡ Energía promedio: {np.mean(optimal_values):.1f} MWh")
        print(f"   📊 Desviación estándar: {np.std(optimal_values):.1f} MWh")
    
    return results


def run_multi_year_montecarlo(start_year: int, n_years: int, n_iterations: int,
                             V0: float, seed: int) -> List[Dict[str, Any]]:
    """
    Ejecuta simulación Monte Carlo multi-año con volúmenes recursivos.
    
    Args:
        start_year: Año inicial
        n_years: Número de años a simular
        n_iterations: Número de iteraciones
        V0: Volumen inicial
        seed: Semilla aleatoria
        
    Returns:
        Lista con resultados por iteración
    """
    from model import build_model_for_one_year
    from sensitivity import extract_kpis
    
    print(f"🎲 Monte Carlo multi-año | {start_year}-{start_year+n_years-1} | N={n_iterations}")
    
    # Inicializar sampler
    sampler = BlockBootstrapSampler("data/Caudales_historicos_filtrado.csv", seed)
    
    iteration_results = []
    
    for iteration in range(1, n_iterations + 1):
        print(f"\n🎯 Iteración {iteration}/{n_iterations}:")
        
        # Volumen inicial para esta trayectoria
        current_V0 = V0
        year_results = []
        
        for year_offset in range(n_years):
            current_year = start_year + year_offset
            print(f"   📅 Año {current_year} (V0={current_V0:.1f})", end=" ")
            
            try:
                # Generar escenario para este año
                I_arc_scenario = sampler.sample_year(block_len=3)
                
                # Construir modelo
                model = build_model_for_one_year(
                    target_year=current_year,
                    V0=current_V0,
                    I_arc_override=I_arc_scenario
                )
                model.optimize()
                
                # Extraer KPIs
                kpis = extract_kpis(model)
                kpis['year'] = current_year
                kpis['iteration'] = iteration
                
                if kpis['status'] == 2:  # GRB.OPTIMAL
                    print(f"✅ {kpis['obj_MWh']:.1f} MWh")
                    # Usar volumen final como V0 del siguiente año
                    current_V0 = kpis.get('V_end', current_V0)
                else:
                    print(f"❌ Status {kpis['status']}")
                    # Si falla, mantener volumen
                
                year_results.append(kpis)
                model.dispose()
                
            except Exception as e:
                print(f"❌ Error: {e}")
                year_results.append({
                    'year': current_year,
                    'iteration': iteration,
                    'status': -1,
                    'obj_MWh': None,
                    'error': str(e)
                })
        
        # Guardar resultados de esta iteración
        iteration_results.append({
            'iteration': iteration,
            'years': year_results,
            'total_energy': sum(r.get('obj_MWh', 0) for r in year_results if r.get('obj_MWh')),
            'final_volume': year_results[-1].get('V_end') if year_results else None
        })
    
    # Análisis final
    print(f"\n📊 Resumen Multi-Año:")
    successful_iterations = [r for r in iteration_results 
                           if r['total_energy'] > 0]
    
    if successful_iterations:
        total_energies = [r['total_energy'] for r in successful_iterations]
        print(f"   ✅ Iteraciones exitosas: {len(successful_iterations)}/{n_iterations}")
        print(f"   ⚡ Energía promedio total: {np.mean(total_energies):.1f} MWh")
        print(f"   📊 Desviación estándar: {np.std(total_energies):.1f} MWh")
    
    return iteration_results