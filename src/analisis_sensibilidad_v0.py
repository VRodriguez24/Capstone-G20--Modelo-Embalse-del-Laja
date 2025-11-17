"""
ANÁLISIS DE SENSIBILIDAD DEL VOLUMEN INICIAL (V0)

Evalúa cómo diferentes volúmenes iniciales afectan el desempeño del sistema
usando simulación Monte Carlo multi-año.

Características:
- Rango configurable de V0 (ej: 500-5000 Hm³)
- Métricas comparativas: energía, déficits, confiabilidad
- Visualización de trade-offs y puntos óptimos
- Compatible con arquitectura Monte Carlo existente

Uso: python src/analisis_sensibilidad_v0.py
"""

from __future__ import annotations

import time
import psutil
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass, field

# Importaciones del modelo
from montecarlo import HybridSimulator
from kpi import aggregate_kpis

# UI Helpers
from ui_helpers import (
    get_input,
    format_time
)


@dataclass
class SensitivityResult:
    """Resultados de análisis de sensibilidad para un V0 específico."""

    V0: float
    success_rate: float
    avg_total_energy: float
    avg_annual_energy: float
    avg_toro_usage: float
    avg_final_volume: float
    std_final_volume: float
    kpis_agregados: Dict = field(default_factory=dict)
    scenarios_data: List[Dict] = field(default_factory=list)
    
    # KPIs estratégicos extraídos
    tiempo_colchon_inferior: float = 0.0
    tiempo_colchon_superior: float = 0.0
    uso_presupuesto_riego: float = 0.0
    uso_presupuesto_generacion: float = 0.0
    deficit_max_1r: float = 0.0
    deficit_max_2r: float = 0.0
    deficit_prom_1r: float = 0.0
    deficit_prom_2r: float = 0.0
    factor_utilizacion: float = 0.0
    cota_promedio: float = 0.0
    eficiencia_energetica: float = 0.0

    def to_dict(self) -> Dict:
        """Convierte resultado a diccionario para análisis."""
        base_dict = {
            "V0": self.V0,
            "success_rate": self.success_rate,
            "avg_total_energy": self.avg_total_energy,
            "avg_annual_energy": self.avg_annual_energy,
            "avg_toro_usage": self.avg_toro_usage,
            "avg_final_volume": self.avg_final_volume,
            "std_final_volume": self.std_final_volume,
            # KPIs estratégicos
            "tiempo_colchon_inferior_%": self.tiempo_colchon_inferior,
            "tiempo_colchon_superior_%": self.tiempo_colchon_superior,
            "uso_presupuesto_riego_%": self.uso_presupuesto_riego,
            "uso_presupuesto_generacion_%": self.uso_presupuesto_generacion,
            "deficit_max_1r_hm3": self.deficit_max_1r,
            "deficit_max_2r_hm3": self.deficit_max_2r,
            "deficit_prom_1r_hm3": self.deficit_prom_1r,
            "deficit_prom_2r_hm3": self.deficit_prom_2r,
            "factor_utilizacion_%": self.factor_utilizacion,
            "cota_promedio_msnm": self.cota_promedio,
            "eficiencia_energetica_mwh_hm3": self.eficiencia_energetica,
        }
        # Añadir KPIs agregados completos
        base_dict.update(self.kpis_agregados)
        return base_dict


class SensitivityAnalyzer:
    """
    Analizador de sensibilidad del volumen inicial.

    Ejecuta múltiples simulaciones Monte Carlo con diferentes V0
    para identificar relaciones y puntos óptimos.
    """

    def __init__(
        self,
        start_year: int = 1960,
        n_years: int = 64,
        n_scenarios: int = 50,
        block_len: int = 3,
        random_state: int = 42
    ):
        """
        Inicializa el analizador de sensibilidad.

        Args:
            start_year: Año inicial de simulación
            n_years: Número de años por escenario
            n_scenarios: Escenarios Monte Carlo por punto V0
            block_len: Longitud de bloques temporales
            random_state: Semilla para reproducibilidad
        """
        self.start_year = start_year
        self.n_years = n_years
        self.n_scenarios = n_scenarios
        self.block_len = block_len
        self.random_state = random_state

        # Inicializar simulador
        self.simulator = HybridSimulator(random_state=random_state)

        # Resultados acumulados
        self.results: List[SensitivityResult] = []

    def run_analysis(
        self,
        V0_range: Tuple[float, float] = (500, 5000),
        n_points: int = 10,
        verbose: bool = True
    ) -> List[SensitivityResult]:
        """
        Ejecuta análisis de sensibilidad completo.

        Args:
            V0_range: Tupla (min, max) para rango de V0 en Hm³
            n_points: Número de puntos a evaluar en el rango
            verbose: Imprimir progreso detallado

        Returns:
            Lista de resultados por cada V0 evaluado
        """

        # Generar puntos de V0 a evaluar
        V0_values = np.linspace(V0_range[0], V0_range[1], n_points)

        if verbose:
            print("=" * 70)
            print("🔬 ANÁLISIS DE SENSIBILIDAD DEL VOLUMEN INICIAL (V0)")
            print("=" * 70)
            print(f"📊 Periodo: {self.start_year}-"
                  f"{self.start_year + self.n_years - 1}")
            print(f"📏 Rango V0: {V0_range[0]:.0f} - {V0_range[1]:.0f} Hm³")
            print(f"📍 Puntos: {n_points} (distribuidos uniformemente)")
            print(f"🎲 Escenarios por punto: {self.n_scenarios}")
            print(f"📅 Años por escenario: {self.n_years}")
            print("=" * 70)
            print()

        # Ejecutar simulaciones para cada V0
        for idx, V0 in enumerate(V0_values):
            if verbose:
                # Barra de progreso visual
                progress = (idx + 1) / n_points
                bar_length = 40
                filled = int(bar_length * progress)
                bar = "█" * filled + "░" * (bar_length - filled)
                
                print(f"\n{'─' * 70}")
                print(f"🔄 PUNTO {idx+1}/{n_points}: V0 = {V0:.0f} Hm³")
                print(f"{'─' * 70}")
                print(f"   Progreso general: [{bar}] {progress*100:.1f}%")
                print(f"   🎲 Ejecutando {self.n_scenarios} escenarios Monte Carlo...")

            try:
                # Ejecutar simulación Monte Carlo
                result = self._evaluate_single_V0(V0, verbose=False)
                self.results.append(result)

                if verbose:
                    # Mostrar resultado del punto
                    status = "✅ ÉXITO" if result.success_rate > 0 else "⚠️ FALLO"
                    print(f"\n   {status}")
                    print(f"   📊 Tasa éxito: {result.success_rate:>6.1f}%")
                    print(f"   ⚡ Energía:    {result.avg_annual_energy:>10,.0f} MWh/año")
                    print(f"   💧 Déficit 1R: {result.deficit_prom_1r:>6.2f} Hm³/mes")
                    print(f"   ⚠️  Riesgo:     {result.tiempo_colchon_inferior:>6.1f}% tiempo")

            except Exception as e:
                if verbose:
                    error_msg = str(e)[:60]
                    print(f"\n   ❌ ERROR: {error_msg}")
                continue

        if verbose:
            print("\n" + "═" * 70)
            print("✅ ANÁLISIS DE SENSIBILIDAD COMPLETADO")
            print("═" * 70)
            print(f"\n📊 Resumen de ejecución:")
            print(f"   ✓ Puntos evaluados exitosamente: {len(self.results)}/{n_points}")
            successful = sum(1 for r in self.results if r.success_rate > 0)
            print(f"   ✓ Configuraciones con éxito: {successful}/{len(self.results)}")
            if self.results:
                avg_success = np.mean([r.success_rate for r in self.results])
                print(f"   ✓ Tasa de éxito promedio: {avg_success:.1f}%")
            print("═" * 70)

        return self.results

    def _evaluate_single_V0(
        self,
        V0: float,
        verbose: bool = False
    ) -> SensitivityResult:
        """
        Evalúa un único valor de V0 con simulación Monte Carlo.

        Args:
            V0: Volumen inicial en Hm³
            verbose: Imprimir detalles de simulación

        Returns:
            SensitivityResult con métricas agregadas
        """

        # Ejecutar simulación Monte Carlo
        mc_results = self.simulator.run_simulation(
            start_year=self.start_year,
            n_years=self.n_years,
            V0=V0,
            n_scenarios=self.n_scenarios,
            block_len=self.block_len,
            verbose=verbose
        )

        # Extraer escenarios exitosos
        successful = mc_results.get("successful_scenarios", [])

        if not successful:
            # Sin escenarios exitosos: retornar resultado vacío
            return SensitivityResult(
                V0=V0,
                success_rate=0.0,
                avg_total_energy=0.0,
                avg_annual_energy=0.0,
                avg_toro_usage=0.0,
                avg_final_volume=V0,
                std_final_volume=0.0,
                kpis_agregados={}
            )

        # Calcular métricas agregadas
        total_energies = [s["total_energy"] for s in successful]
        total_toro_usages = [s["total_toro_usage"] for s in successful]
        final_volumes = [s["final_volume"] for s in successful]

        avg_total_energy = np.mean(total_energies)
        avg_annual_energy = avg_total_energy / self.n_years
        avg_toro_usage = np.mean(total_toro_usages)
        avg_final_volume = np.mean(final_volumes)
        std_final_volume = np.std(final_volumes)
        success_rate = mc_results["success_rate"]

        # Recolectar KPIs de todos los escenarios
        all_kpis = []
        for scenario in successful:
            for year_result in scenario["results"]:
                if "kpis" in year_result and year_result["kpis"]:
                    all_kpis.append(year_result["kpis"])

        # Agregar KPIs
        kpis_agregados = {}
        if all_kpis:
            kpis_agregados = aggregate_kpis(all_kpis)
        
        # Extraer KPIs estratégicos para acceso directo
        tiempo_colchones = kpis_agregados.get('tiempo_colchones_%', {})
        uso_presupuestos = kpis_agregados.get('uso_presupuestos_%', {})
        deficit_max = kpis_agregados.get('deficit_max_hm3', {})
        deficit_prom = kpis_agregados.get('deficit_prom_hm3', {})
        factor_util = kpis_agregados.get('factor_utilizacion_%', {})
        cota_mensual = kpis_agregados.get('cota_mensual', {})
        
        # Calcular cota promedio
        cota_prom = np.mean(list(cota_mensual.values())) if cota_mensual else 0.0
        
        # Calcular eficiencia energética
        eficiencia = kpis_agregados.get('eficiencia_energetica_mwh_hm3', 0.0)

        return SensitivityResult(
            V0=V0,
            success_rate=success_rate,
            avg_total_energy=avg_total_energy,
            avg_annual_energy=avg_annual_energy,
            avg_toro_usage=avg_toro_usage,
            avg_final_volume=avg_final_volume,
            std_final_volume=std_final_volume,
            kpis_agregados=kpis_agregados,
            scenarios_data=successful,
            # KPIs estratégicos
            tiempo_colchon_inferior=tiempo_colchones.get('Inferior', 0.0),
            tiempo_colchon_superior=tiempo_colchones.get('Superior', 0.0),
            uso_presupuesto_riego=uso_presupuestos.get('riego', 0.0),
            uso_presupuesto_generacion=uso_presupuestos.get('generacion', 0.0),
            deficit_max_1r=deficit_max.get('1R', 0.0),
            deficit_max_2r=deficit_max.get('2R', 0.0),
            deficit_prom_1r=deficit_prom.get('1R', 0.0),
            deficit_prom_2r=deficit_prom.get('2R', 0.0),
            factor_utilizacion=factor_util.get('sistema', 0.0),
            cota_promedio=cota_prom,
            eficiencia_energetica=eficiencia
        )

    def export_results_to_csv(
        self,
        output_path: str = "resultados/sensibilidad_v0.csv"
    ) -> str:
        """
        Exporta resultados a archivo CSV para análisis externo.

        Args:
            output_path: Ruta del archivo CSV de salida

        Returns:
            Ruta del archivo creado
        """

        # Crear directorio si no existe
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Convertir resultados a DataFrame
        data = [result.to_dict() for result in self.results]
        df = pd.DataFrame(data)

        # Guardar a CSV
        df.to_csv(output_path, index=False, float_format='%.2f')

        return output_path
    
    def export_edge_cases_analysis(
        self,
        output_path: str = "resultados/sensibilidad_v0_casos_borde.csv"
    ) -> str:
        """
        Exporta análisis detallado de casos borde a CSV.
        
        Identifica y documenta escenarios críticos para evaluación de riesgos:
        - V0 mínimo/máximo evaluado
        - Peor caso de déficits
        - Mayor riesgo operativo
        - Mejor/peor tasa de éxito
        - Mejor/peor eficiencia

        Args:
            output_path: Ruta del archivo CSV de salida

        Returns:
            Ruta del archivo creado
        """
        if not self.results:
            print("⚠️ No hay resultados para exportar")
            return ""

        # Crear directorio si no existe
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Identificar casos borde
        casos_borde = []

        # 1. V0 mínimo
        min_v0 = min(self.results, key=lambda r: r.V0)
        casos_borde.append({
            "caso": "V0_minimo",
            "descripcion": "Volumen inicial mínimo evaluado",
            **min_v0.to_dict()
        })

        # 2. V0 máximo
        max_v0 = max(self.results, key=lambda r: r.V0)
        casos_borde.append({
            "caso": "V0_maximo",
            "descripcion": "Volumen inicial máximo evaluado",
            **max_v0.to_dict()
        })

        # 3. Máxima energía
        max_energy = max(self.results, key=lambda r: r.avg_annual_energy)
        casos_borde.append({
            "caso": "maxima_energia",
            "descripcion": "Configuración óptima para generación energética",
            **max_energy.to_dict()
        })

        # 4. Mínima energía (con éxito > 0)
        successful_results = [r for r in self.results if r.success_rate > 0]
        if successful_results:
            min_energy = min(successful_results, key=lambda r: r.avg_annual_energy)
            casos_borde.append({
                "caso": "minima_energia",
                "descripcion": "Peor desempeño energético (con éxito)",
                **min_energy.to_dict()
            })

        # 5. Mayor déficit 1R
        max_deficit_1r = max(self.results, key=lambda r: r.deficit_max_1r)
        casos_borde.append({
            "caso": "mayor_deficit_1R",
            "descripcion": "Peor escenario para primeros regantes",
            **max_deficit_1r.to_dict()
        })

        # 6. Mayor déficit 2R
        max_deficit_2r = max(self.results, key=lambda r: r.deficit_max_2r)
        casos_borde.append({
            "caso": "mayor_deficit_2R",
            "descripcion": "Peor escenario para segundos regantes",
            **max_deficit_2r.to_dict()
        })

        # 7. Mayor riesgo operativo
        max_risk = max(self.results, key=lambda r: r.tiempo_colchon_inferior)
        casos_borde.append({
            "caso": "mayor_riesgo_operativo",
            "descripcion": "Máximo tiempo en colchón inferior",
            **max_risk.to_dict()
        })

        # 8. Menor riesgo operativo
        min_risk = min(self.results, key=lambda r: r.tiempo_colchon_inferior)
        casos_borde.append({
            "caso": "menor_riesgo_operativo",
            "descripcion": "Mínimo tiempo en colchón inferior",
            **min_risk.to_dict()
        })

        # 9. Máxima eficiencia
        max_efficiency = max(self.results, key=lambda r: r.eficiencia_energetica)
        casos_borde.append({
            "caso": "maxima_eficiencia",
            "descripcion": "Mejor relación energía/agua",
            **max_efficiency.to_dict()
        })

        # 10. Mejor tasa de éxito
        max_success = max(self.results, key=lambda r: r.success_rate)
        casos_borde.append({
            "caso": "mejor_exito",
            "descripcion": "Mayor probabilidad de operación exitosa",
            **max_success.to_dict()
        })

        # Crear DataFrame y exportar
        df = pd.DataFrame(casos_borde)
        df.to_csv(output_path, index=False, float_format='%.3f')

        print(f"✅ Análisis de casos borde exportado: {output_path}")
        print(f"   📊 {len(casos_borde)} casos críticos documentados")

        return output_path

    def generate_sensitivity_plots(
        self,
        output_dir: str = "resultados"
    ) -> List[str]:
        """
        Genera visualizaciones de análisis de sensibilidad.

        Crea gráficos mostrando:
        - V0 vs Energía promedio anual
        - V0 vs Tasa de éxito
        - V0 vs KPIs estratégicos (tiempo en colchones, déficits, eficiencia)
        - V0 vs Uso de presupuestos
        - V0 vs Factor de utilización
        - V0 vs Volumen final promedio

        Args:
            output_dir: Directorio para guardar gráficos

        Returns:
            Lista de rutas de archivos PNG generados
        """

        if not self.results:
            print("⚠️ No hay resultados para graficar")
            return []

        # Crear directorio de salida
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        files_created = []

        # Extraer datos para gráficos
        V0_values = [r.V0 for r in self.results]
        success_rates = [r.success_rate for r in self.results]
        avg_energies = [r.avg_annual_energy for r in self.results]
        
        # KPIs estratégicos
        tiempo_inferior = [r.tiempo_colchon_inferior for r in self.results]
        tiempo_superior = [r.tiempo_colchon_superior for r in self.results]
        uso_riego = [r.uso_presupuesto_riego for r in self.results]
        uso_generacion = [r.uso_presupuesto_generacion for r in self.results]
        deficit_max_1r = [r.deficit_max_1r for r in self.results]
        deficit_max_2r = [r.deficit_max_2r for r in self.results]
        deficit_prom_1r = [r.deficit_prom_1r for r in self.results]
        deficit_prom_2r = [r.deficit_prom_2r for r in self.results]
        factor_util = [r.factor_utilizacion for r in self.results]
        cota_prom = [r.cota_promedio for r in self.results]
        eficiencia = [r.eficiencia_energetica for r in self.results]
        
        avg_final_vol = [r.avg_final_volume for r in self.results]
        std_final_vol = [r.std_final_volume for r in self.results]

        # Configurar estilo
        plt.rcParams['font.size'] = 9
        plt.rcParams['figure.figsize'] = (20, 16)

        # ==================================================================
        # FIGURA 1: MÉTRICAS PRINCIPALES (3x3 grid)
        # ==================================================================
        fig1, axes1 = plt.subplots(3, 3, figsize=(20, 16))
        
        # --- FILA 1: RENDIMIENTO ENERGÉTICO Y ÉXITO ---
        
        # Plot 1.1: V0 vs Energía Promedio Anual
        ax = axes1[0, 0]
        ax.plot(V0_values, avg_energies, 'b-o', linewidth=2, markersize=6)
        ax.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax.set_ylabel('Energía Promedio Anual [MWh/año]', fontweight='bold')
        ax.set_title('V0 vs Generación Energética', fontweight='bold', fontsize=11)
        ax.grid(True, alpha=0.3)
        # Marcar máximo
        if avg_energies:
            max_idx = np.argmax(avg_energies)
            ax.plot(V0_values[max_idx], avg_energies[max_idx], 'r*', 
                   markersize=15, label=f'Máximo: V0={V0_values[max_idx]:.0f} Hm³')
            ax.legend()

        # Plot 1.2: V0 vs Tasa de Éxito
        ax = axes1[0, 1]
        ax.plot(V0_values, success_rates, 'g-o', linewidth=2, markersize=6)
        ax.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax.set_ylabel('Tasa de Éxito [%]', fontweight='bold')
        ax.set_title('V0 vs Tasa de Éxito Monte Carlo', fontweight='bold', fontsize=11)
        ax.set_ylim(0, 105)
        ax.grid(True, alpha=0.3)

        # Plot 1.3: V0 vs Eficiencia Energética
        ax = axes1[0, 2]
        if any(eficiencia):
            ax.plot(V0_values, eficiencia, 'purple', marker='o', linewidth=2, markersize=6)
            ax.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
            ax.set_ylabel('Eficiencia [MWh/Hm³]', fontweight='bold')
            ax.set_title('V0 vs Eficiencia Energética', fontweight='bold', fontsize=11)
            ax.grid(True, alpha=0.3)
            # Marcar máximo
            max_idx = np.argmax(eficiencia)
            ax.plot(V0_values[max_idx], eficiencia[max_idx], 'r*', 
                   markersize=15, label=f'Máximo: V0={V0_values[max_idx]:.0f} Hm³')
            ax.legend()
        else:
            ax.text(0.5, 0.5, 'Sin datos', ha='center', va='center', transform=ax.transAxes)

        # --- FILA 2: TIEMPO EN COLCHONES Y USO DE PRESUPUESTOS ---
        
        # Plot 2.1: V0 vs Tiempo en Colchón Inferior
        ax = axes1[1, 0]
        ax.plot(V0_values, tiempo_inferior, 'orange', marker='o', linewidth=2, markersize=6)
        ax.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax.set_ylabel('Tiempo en Colchón Inferior [%]', fontweight='bold')
        ax.set_title('V0 vs Riesgo Operativo (Colchón Inferior)', fontweight='bold', fontsize=11)
        ax.set_ylim(0, 105)
        ax.grid(True, alpha=0.3)
        # Destacar zona crítica (>50%)
        ax.axhline(y=50, color='red', linestyle='--', alpha=0.5, label='Límite crítico (50%)')
        ax.legend()

        # Plot 2.2: V0 vs Tiempo en Colchón Superior
        ax = axes1[1, 1]
        ax.plot(V0_values, tiempo_superior, 'darkgreen', marker='o', linewidth=2, markersize=6)
        ax.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax.set_ylabel('Tiempo en Colchón Superior [%]', fontweight='bold')
        ax.set_title('V0 vs Disponibilidad Hídrica Alta', fontweight='bold', fontsize=11)
        ax.set_ylim(0, 105)
        ax.grid(True, alpha=0.3)
        # Marcar máximo
        if tiempo_superior:
            max_idx = np.argmax(tiempo_superior)
            ax.plot(V0_values[max_idx], tiempo_superior[max_idx], 'r*', 
                   markersize=15, label=f'Máximo: V0={V0_values[max_idx]:.0f} Hm³')
            ax.legend()

        # Plot 2.3: V0 vs Uso de Presupuestos (Dual)
        ax = axes1[1, 2]
        ax.plot(V0_values, uso_riego, 'blue', marker='o', linewidth=2, 
               markersize=6, label='Riego')
        ax.plot(V0_values, uso_generacion, 'green', marker='s', linewidth=2, 
               markersize=6, label='Generación')
        ax.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax.set_ylabel('Uso de Presupuesto [%]', fontweight='bold')
        ax.set_title('V0 vs Uso de Presupuestos (Riego y Generación)', fontweight='bold', fontsize=11)
        ax.axhline(y=100, color='red', linestyle='--', alpha=0.5, label='Presupuesto (100%)')
        ax.grid(True, alpha=0.3)
        ax.legend()

        # --- FILA 3: DÉFICITS Y FACTOR DE UTILIZACIÓN ---
        
        # Plot 3.1: V0 vs Déficits Máximos (1R y 2R)
        ax = axes1[2, 0]
        ax.plot(V0_values, deficit_max_1r, 'red', marker='o', linewidth=2, 
               markersize=6, label='1R (Primeros Regantes)')
        ax.plot(V0_values, deficit_max_2r, 'darkred', marker='s', linewidth=2, 
               markersize=6, label='2R (Segundos Regantes)')
        ax.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax.set_ylabel('Déficit Máximo [Hm³]', fontweight='bold')
        ax.set_title('V0 vs Déficits Máximos (Peor Caso)', fontweight='bold', fontsize=11)
        ax.grid(True, alpha=0.3)
        ax.legend()

        # Plot 3.2: V0 vs Déficits Promedio (1R y 2R)
        ax = axes1[2, 1]
        ax.plot(V0_values, deficit_prom_1r, 'coral', marker='o', linewidth=2, 
               markersize=6, label='1R (Primeros Regantes)')
        ax.plot(V0_values, deficit_prom_2r, 'salmon', marker='s', linewidth=2, 
               markersize=6, label='2R (Segundos Regantes)')
        ax.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax.set_ylabel('Déficit Promedio [Hm³/mes]', fontweight='bold')
        ax.set_title('V0 vs Déficits Promedio Mensual', fontweight='bold', fontsize=11)
        ax.grid(True, alpha=0.3)
        ax.legend()

        # Plot 3.3: V0 vs Factor de Utilización
        ax = axes1[2, 2]
        if any(factor_util):
            ax.plot(V0_values, factor_util, 'teal', marker='o', linewidth=2, markersize=6)
            ax.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
            ax.set_ylabel('Factor de Utilización [%]', fontweight='bold')
            ax.set_title('V0 vs Eficiencia Hidráulica del Sistema', fontweight='bold', fontsize=11)
            ax.grid(True, alpha=0.3)
            # Marcar máximo
            max_idx = np.argmax(factor_util)
            ax.plot(V0_values[max_idx], factor_util[max_idx], 'r*', 
                   markersize=15, label=f'Máximo: V0={V0_values[max_idx]:.0f} Hm³')
            ax.legend()
        else:
            ax.text(0.5, 0.5, 'Sin datos', ha='center', va='center', transform=ax.transAxes)

        plt.tight_layout()
        plot_file1 = output_path / "sensibilidad_v0_kpis_estrategicos.png"
        plt.savefig(plot_file1, dpi=300, bbox_inches='tight')
        plt.close()
        files_created.append(str(plot_file1))

        # ==================================================================
        # FIGURA 2: ANÁLISIS COMPLEMENTARIO (2x2 grid)
        # ==================================================================
        fig2, axes2 = plt.subplots(2, 2, figsize=(16, 12))
        
        # Plot 2.1: V0 vs Cota Promedio
        ax = axes2[0, 0]
        if any(cota_prom):
            ax.plot(V0_values, cota_prom, 'm-o', linewidth=2, markersize=6)
            ax.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
            ax.set_ylabel('Cota Promedio [msnm]', fontweight='bold')
            ax.set_title('V0 vs Cota del Lago', fontweight='bold', fontsize=12)
            ax.grid(True, alpha=0.3)
        else:
            ax.text(0.5, 0.5, 'Sin datos', ha='center', va='center', transform=ax.transAxes)

        # Plot 2.2: V0 vs Volumen Final (con banda de desviación)
        ax = axes2[0, 1]
        ax.fill_between(
            V0_values,
            np.array(avg_final_vol) - np.array(std_final_vol),
            np.array(avg_final_vol) + np.array(std_final_vol),
            alpha=0.3,
            color='lightblue',
            label='±1 desviación estándar'
        )
        ax.plot(V0_values, avg_final_vol, 'b-o', linewidth=2, markersize=6,
               label='Volumen final promedio')
        ax.plot(V0_values, V0_values, 'k--', alpha=0.5, linewidth=1,
               label='Equilibrio (V_final = V0)')
        ax.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax.set_ylabel('Volumen Final Promedio [Hm³]', fontweight='bold')
        ax.set_title('V0 vs Volumen Final', fontweight='bold', fontsize=12)
        ax.grid(True, alpha=0.3)
        ax.legend()

        # Plot 2.3: Trade-off: Energía vs Déficit 1R
        ax = axes2[1, 0]
        scatter = ax.scatter(deficit_prom_1r, avg_energies, c=V0_values, 
                            cmap='viridis', s=100, alpha=0.7, edgecolors='black')
        ax.set_xlabel('Déficit Promedio 1R [Hm³/mes]', fontweight='bold')
        ax.set_ylabel('Energía Promedio Anual [MWh/año]', fontweight='bold')
        ax.set_title('Trade-off: Energía vs Déficit (1R)', fontweight='bold', fontsize=12)
        ax.grid(True, alpha=0.3)
        cbar = plt.colorbar(scatter, ax=ax)
        cbar.set_label('V0 [Hm³]', fontweight='bold')

        # Plot 2.4: Trade-off: Tasa de Éxito vs Tiempo en Colchón Inferior
        ax = axes2[1, 1]
        scatter = ax.scatter(tiempo_inferior, success_rates, c=V0_values, 
                            cmap='plasma', s=100, alpha=0.7, edgecolors='black')
        ax.set_xlabel('Tiempo en Colchón Inferior [%]', fontweight='bold')
        ax.set_ylabel('Tasa de Éxito [%]', fontweight='bold')
        ax.set_title('Trade-off: Éxito vs Riesgo Operativo', fontweight='bold', fontsize=12)
        ax.grid(True, alpha=0.3)
        cbar = plt.colorbar(scatter, ax=ax)
        cbar.set_label('V0 [Hm³]', fontweight='bold')

        plt.tight_layout()
        plot_file2 = output_path / "sensibilidad_v0_analisis_complementario.png"
        plt.savefig(plot_file2, dpi=300, bbox_inches='tight')
        plt.close()
        files_created.append(str(plot_file2))

        # ==================================================================
        # FIGURA 3: DASHBOARD EJECUTIVO (2x2 grid)
        # ==================================================================
        fig3 = plt.figure(figsize=(18, 14))
        gs = fig3.add_gridspec(3, 2, hspace=0.3, wspace=0.25)
        
        # Plot 3.1: Radar Chart - Comparación Multi-dimensional (TOP)
        ax_radar = fig3.add_subplot(gs[0, :], projection='polar')
        
        # Seleccionar 3-5 configuraciones representativas
        if len(self.results) >= 5:
            indices = [0, len(self.results)//4, len(self.results)//2, 
                      3*len(self.results)//4, -1]
            labels_configs = ['V0 Mín', 'V0 25%', 'V0 50%', 'V0 75%', 'V0 Máx']
        else:
            indices = range(len(self.results))
            labels_configs = [f'V0={self.results[i].V0:.0f}' for i in indices]
        
        selected_results = [self.results[i] for i in indices]
        
        # Preparar datos para radar (normalizar 0-100)
        categories = ['Energía', 'Éxito', 'Eficiencia', 
                     'Seguridad\nHídrica', 'Estabilidad\nOperativa']
        
        def normalize_to_100(values):
            min_val, max_val = min(values), max(values)
            if max_val == min_val:
                return [50] * len(values)
            return [(v - min_val) / (max_val - min_val) * 100 for v in values]
        
        all_energies = [r.avg_annual_energy for r in self.results]
        all_success = [r.success_rate for r in self.results]
        all_efficiency = [r.eficiencia_energetica for r in self.results]
        all_deficits = [r.deficit_prom_1r for r in self.results]
        all_risks = [r.tiempo_colchon_inferior for r in self.results]
        
        norm_energies = normalize_to_100(all_energies)
        norm_deficits_inv = [100 - v for v in normalize_to_100(all_deficits)]
        norm_risks_inv = [100 - v for v in normalize_to_100(all_risks)]
        
        angles = np.linspace(0, 2 * np.pi, len(categories), endpoint=False).tolist()
        angles += angles[:1]
        
        ax_radar.set_theta_offset(np.pi / 2)
        ax_radar.set_theta_direction(-1)
        ax_radar.set_xticks(angles[:-1])
        ax_radar.set_xticklabels(categories, size=10, weight='bold')
        ax_radar.set_ylim(0, 100)
        ax_radar.set_yticks([25, 50, 75, 100])
        ax_radar.set_yticklabels(['25', '50', '75', '100'], size=8)
        ax_radar.grid(True, linestyle='--', alpha=0.3)
        
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd']
        
        for idx, (result, label, color) in enumerate(zip(selected_results, labels_configs, colors)):
            result_idx = self.results.index(result)
            values = [
                norm_energies[result_idx],
                all_success[result_idx],
                normalize_to_100(all_efficiency)[result_idx],
                norm_deficits_inv[result_idx],
                norm_risks_inv[result_idx]
            ]
            values += values[:1]
            
            ax_radar.plot(angles, values, 'o-', linewidth=2, 
                         label=f'{label} ({result.V0:.0f} Hm³)', 
                         color=color, markersize=6)
            ax_radar.fill(angles, values, alpha=0.15, color=color)
        
        ax_radar.set_title('Comparación Multi-dimensional de Configuraciones V0', 
                          fontweight='bold', fontsize=14, pad=20)
        ax_radar.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=10)
        
        # Plot 3.2: Heatmap Déficits vs Riesgo
        ax_heat = fig3.add_subplot(gs[1, 0])
        
        # Crear matriz de calor
        deficit_bins = np.linspace(min(deficit_prom_1r), max(deficit_prom_1r), 10)
        risk_bins = np.linspace(min(tiempo_inferior), max(tiempo_inferior), 10)
        
        # Agrupar puntos por bins y calcular energía promedio
        heat_matrix = np.zeros((len(risk_bins)-1, len(deficit_bins)-1))
        count_matrix = np.zeros((len(risk_bins)-1, len(deficit_bins)-1))
        
        for r in self.results:
            d_idx = np.digitize(r.deficit_prom_1r, deficit_bins) - 1
            r_idx = np.digitize(r.tiempo_colchon_inferior, risk_bins) - 1
            
            if 0 <= d_idx < len(deficit_bins)-1 and 0 <= r_idx < len(risk_bins)-1:
                heat_matrix[r_idx, d_idx] += r.avg_annual_energy
                count_matrix[r_idx, d_idx] += 1
        
        # Promedio
        with np.errstate(divide='ignore', invalid='ignore'):
            heat_matrix = np.where(count_matrix > 0, heat_matrix / count_matrix, np.nan)
        
        im = ax_heat.imshow(heat_matrix, cmap='RdYlGn', aspect='auto', origin='lower')
        ax_heat.set_xlabel('Déficit Promedio 1R [Hm³/mes]', fontweight='bold')
        ax_heat.set_ylabel('Riesgo Operativo [% tiempo]', fontweight='bold')
        ax_heat.set_title('Mapa de Generación: Déficit vs Riesgo', fontweight='bold', fontsize=12)
        
        # Etiquetas
        ax_heat.set_xticks(np.arange(len(deficit_bins)-1))
        ax_heat.set_yticks(np.arange(len(risk_bins)-1))
        ax_heat.set_xticklabels([f'{v:.2f}' for v in deficit_bins[:-1]], rotation=45, ha='right', fontsize=8)
        ax_heat.set_yticklabels([f'{v:.1f}' for v in risk_bins[:-1]], fontsize=8)
        
        cbar = plt.colorbar(im, ax=ax_heat)
        cbar.set_label('Energía [MWh/año]', fontweight='bold', rotation=270, labelpad=20)
        
        # Plot 3.3: Pareto Front - Energía vs Déficit
        ax_pareto = fig3.add_subplot(gs[1, 1])
        
        # Scatter con color por V0
        scatter = ax_pareto.scatter(deficit_prom_1r, avg_energies, 
                                   c=V0_values, s=200, alpha=0.7, 
                                   cmap='viridis', edgecolors='black', linewidth=1.5)
        
        # Identificar frontera de Pareto (maximizar energía, minimizar déficit)
        # Puntos no dominados
        pareto_points = []
        for i, r1 in enumerate(self.results):
            is_pareto = True
            for j, r2 in enumerate(self.results):
                if i != j:
                    # r2 domina r1 si tiene mayor energía Y menor déficit
                    if (r2.avg_annual_energy >= r1.avg_annual_energy and 
                        r2.deficit_prom_1r <= r1.deficit_prom_1r and
                        (r2.avg_annual_energy > r1.avg_annual_energy or 
                         r2.deficit_prom_1r < r1.deficit_prom_1r)):
                        is_pareto = False
                        break
            if is_pareto:
                pareto_points.append(i)
        
        # Dibujar frontera de Pareto
        if pareto_points:
            pareto_deficits = [deficit_prom_1r[i] for i in pareto_points]
            pareto_energies = [avg_energies[i] for i in pareto_points]
            
            # Ordenar para línea
            sorted_pairs = sorted(zip(pareto_deficits, pareto_energies))
            pareto_deficits_sorted, pareto_energies_sorted = zip(*sorted_pairs)
            
            ax_pareto.plot(pareto_deficits_sorted, pareto_energies_sorted, 
                          'r--', linewidth=2, label='Frontera de Pareto', alpha=0.7)
            
            # Marcar puntos Pareto
            ax_pareto.scatter([deficit_prom_1r[i] for i in pareto_points],
                            [avg_energies[i] for i in pareto_points],
                            marker='*', s=400, c='red', edgecolors='darkred', 
                            linewidth=2, label='Configuraciones Pareto-óptimas', zorder=5)
        
        ax_pareto.set_xlabel('Déficit Promedio 1R [Hm³/mes]', fontweight='bold')
        ax_pareto.set_ylabel('Energía Promedio Anual [MWh/año]', fontweight='bold')
        ax_pareto.set_title('Frontera de Pareto: Energía vs Seguridad Hídrica', 
                           fontweight='bold', fontsize=12)
        ax_pareto.grid(True, alpha=0.3)
        ax_pareto.legend(loc='best', fontsize=9)
        
        cbar2 = plt.colorbar(scatter, ax=ax_pareto)
        cbar2.set_label('V0 [Hm³]', fontweight='bold', rotation=270, labelpad=20)
        
        # Plot 3.4: Sensibilidad Normalizada (todas las métricas)
        ax_sens = fig3.add_subplot(gs[2, :])
        
        # Normalizar todas las métricas a escala 0-1
        metrics = {
            'Energía': normalize_to_100([r.avg_annual_energy for r in self.results]),
            'Tasa Éxito': [r.success_rate for r in self.results],
            'Eficiencia': normalize_to_100([r.eficiencia_energetica for r in self.results]),
            'Seguridad (inv)': [100 - v for v in normalize_to_100([r.deficit_prom_1r for r in self.results])],
            'Estabilidad (inv)': [100 - v for v in normalize_to_100([r.tiempo_colchon_inferior for r in self.results])]
        }
        
        for name, values in metrics.items():
            ax_sens.plot(V0_values, values, marker='o', linewidth=2, 
                        markersize=6, label=name, alpha=0.8)
        
        ax_sens.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold', fontsize=12)
        ax_sens.set_ylabel('Índice Normalizado [0-100]', fontweight='bold', fontsize=12)
        ax_sens.set_title('Sensibilidad Comparativa de Todos los KPIs (Normalizado)', 
                         fontweight='bold', fontsize=13)
        ax_sens.grid(True, alpha=0.3, linestyle='--')
        ax_sens.legend(loc='best', fontsize=10, ncol=5)
        ax_sens.set_ylim(-5, 105)
        
        # Zona óptima (percentiles 25-75)
        p25 = np.percentile(V0_values, 25)
        p75 = np.percentile(V0_values, 75)
        ax_sens.axvspan(p25, p75, alpha=0.1, color='green', 
                       label='Rango conservador recomendado')
        
        # Usar bbox_inches='tight' en lugar de tight_layout() para evitar warning con polar
        plot_file3 = output_path / "sensibilidad_v0_dashboard_ejecutivo.png"
        plt.savefig(plot_file3, dpi=300, bbox_inches='tight')
        plt.close()
        files_created.append(str(plot_file3))

        return files_created

    def print_summary(self):
        """Imprime resumen de análisis de sensibilidad con insights de KPIs."""

        if not self.results:
            print("⚠️ No hay resultados para mostrar")
            return

        print("\n" + "=" * 80)
        print("📊 RESUMEN DE ANÁLISIS DE SENSIBILIDAD V0")
        print("=" * 80)

        # Crear tabla de resultados
        print(f"\n{'V0':>6} {'Éxito':>7} {'Energía':>10} {'T.Inf%':>7} "
              f"{'Def1R':>8} {'Def2R':>8} {'F.Util':>7} {'Efic':>8}")
        print(f"{'[Hm³]':>6} {'[%]':>7} {'[MWh/a]':>10} {'':>7} "
              f"{'[Hm³]':>8} {'[Hm³]':>8} {'[%]':>7} {'[MWh/Hm³]':>8}")
        print("-" * 80)

        for r in self.results:
            print(f"{r.V0:>6.0f} {r.success_rate:>7.1f} "
                  f"{r.avg_annual_energy:>10.0f} {r.tiempo_colchon_inferior:>7.1f} "
                  f"{r.deficit_prom_1r:>8.2f} {r.deficit_prom_2r:>8.2f} "
                  f"{r.factor_utilizacion:>7.1f} {r.eficiencia_energetica:>8.2f}")

        # =====================================================================
        # PUNTOS ÓPTIMOS POR OBJETIVO
        # =====================================================================
        print("\n" + "=" * 80)
        print("🎯 PUNTOS ÓPTIMOS IDENTIFICADOS POR OBJETIVO")
        print("=" * 80)

        # 1. Máxima energía
        max_energy_result = max(self.results, key=lambda r: r.avg_annual_energy)
        print("\n⚡ MÁXIMA GENERACIÓN ENERGÉTICA:")
        print(f"   V0 óptimo: {max_energy_result.V0:.0f} Hm³")
        print(f"   Energía: {max_energy_result.avg_annual_energy:,.0f} MWh/año")
        print(f"   Eficiencia: {max_energy_result.eficiencia_energetica:.2f} MWh/Hm³")
        print(f"   Tasa éxito: {max_energy_result.success_rate:.1f}%")
        print(f"   Déficit 1R: {max_energy_result.deficit_prom_1r:.2f} Hm³/mes")

        # 2. Máxima tasa de éxito
        max_success_result = max(self.results, key=lambda r: r.success_rate)
        print("\n✅ MÁXIMA TASA DE ÉXITO:")
        print(f"   V0 óptimo: {max_success_result.V0:.0f} Hm³")
        print(f"   Tasa éxito: {max_success_result.success_rate:.1f}%")
        print(f"   Energía: {max_success_result.avg_annual_energy:,.0f} MWh/año")
        print(f"   Tiempo colchón superior: {max_success_result.tiempo_colchon_superior:.1f}%")

        # 3. Mínimo déficit para primeros regantes
        min_deficit_result = min(self.results, key=lambda r: r.deficit_prom_1r)
        print("\n💧 MÍNIMO DÉFICIT PRIMEROS REGANTES (1R):")
        print(f"   V0 óptimo: {min_deficit_result.V0:.0f} Hm³")
        print(f"   Déficit promedio 1R: {min_deficit_result.deficit_prom_1r:.2f} Hm³/mes")
        print(f"   Déficit máximo 1R: {min_deficit_result.deficit_max_1r:.2f} Hm³")
        print(f"   Energía: {min_deficit_result.avg_annual_energy:,.0f} MWh/año")

        # 4. Máxima eficiencia energética
        max_efficiency_result = max(self.results, key=lambda r: r.eficiencia_energetica)
        print("\n🔋 MÁXIMA EFICIENCIA ENERGÉTICA:")
        print(f"   V0 óptimo: {max_efficiency_result.V0:.0f} Hm³")
        print(f"   Eficiencia: {max_efficiency_result.eficiencia_energetica:.2f} MWh/Hm³")
        print(f"   Energía: {max_efficiency_result.avg_annual_energy:,.0f} MWh/año")
        print(f"   Factor utilización: {max_efficiency_result.factor_utilizacion:.1f}%")

        # 5. Mínimo riesgo operativo (menor tiempo en colchón inferior)
        min_risk_result = min(self.results, key=lambda r: r.tiempo_colchon_inferior)
        print("\n🛡️ MÍNIMO RIESGO OPERATIVO:")
        print(f"   V0 óptimo: {min_risk_result.V0:.0f} Hm³")
        print(f"   Tiempo colchón inferior: {min_risk_result.tiempo_colchon_inferior:.1f}%")
        print(f"   Tiempo colchón superior: {min_risk_result.tiempo_colchon_superior:.1f}%")
        print(f"   Cota promedio: {min_risk_result.cota_promedio:.1f} msnm")

        # =====================================================================
        # CASOS BORDE Y ANÁLISIS CRÍTICO
        # =====================================================================
        print("\n" + "=" * 80)
        print("⚠️ CASOS BORDE Y ESCENARIOS CRÍTICOS")
        print("=" * 80)

        # Caso borde 1: V0 mínimo evaluado
        min_v0_result = min(self.results, key=lambda r: r.V0)
        print("\n📉 CASO BORDE: V0 MÍNIMO")
        print(f"   V0: {min_v0_result.V0:.0f} Hm³")
        print(f"   Tasa éxito: {min_v0_result.success_rate:.1f}%")
        print(f"   Energía: {min_v0_result.avg_annual_energy:,.0f} MWh/año")
        print(f"   Tiempo colchón inferior: {min_v0_result.tiempo_colchon_inferior:.1f}%")
        print(f"   Déficit máx 1R: {min_v0_result.deficit_max_1r:.2f} Hm³")
        print(f"   Déficit máx 2R: {min_v0_result.deficit_max_2r:.2f} Hm³")
        if min_v0_result.tiempo_colchon_inferior > 50:
            print(f"   ⚠️ ALERTA: Alto riesgo operativo ({min_v0_result.tiempo_colchon_inferior:.1f}% en colchón inferior)")

        # Caso borde 2: V0 máximo evaluado
        max_v0_result = max(self.results, key=lambda r: r.V0)
        print("\n📈 CASO BORDE: V0 MÁXIMO")
        print(f"   V0: {max_v0_result.V0:.0f} Hm³")
        print(f"   Tasa éxito: {max_v0_result.success_rate:.1f}%")
        print(f"   Energía: {max_v0_result.avg_annual_energy:,.0f} MWh/año")
        print(f"   Tiempo colchón superior: {max_v0_result.tiempo_colchon_superior:.1f}%")
        print(f"   Uso presupuesto riego: {max_v0_result.uso_presupuesto_riego:.1f}%")
        print(f"   Uso presupuesto generación: {max_v0_result.uso_presupuesto_generacion:.1f}%")

        # Caso crítico: Mayor déficit para regantes
        max_deficit_result = max(self.results, key=lambda r: r.deficit_max_1r)
        print("\n🚨 CASO CRÍTICO: MAYOR DÉFICIT HÍDRICO")
        print(f"   V0: {max_deficit_result.V0:.0f} Hm³")
        print(f"   Déficit máx 1R: {max_deficit_result.deficit_max_1r:.2f} Hm³")
        print(f"   Déficit máx 2R: {max_deficit_result.deficit_max_2r:.2f} Hm³")
        print(f"   Déficit prom 1R: {max_deficit_result.deficit_prom_1r:.2f} Hm³/mes")
        print(f"   Déficit prom 2R: {max_deficit_result.deficit_prom_2r:.2f} Hm³/mes")
        print(f"   Energía: {max_deficit_result.avg_annual_energy:,.0f} MWh/año")

        # Caso crítico: Mayor tiempo en colchón inferior
        max_risk_result = max(self.results, key=lambda r: r.tiempo_colchon_inferior)
        print("\n⚠️ CASO CRÍTICO: MAYOR RIESGO OPERATIVO")
        print(f"   V0: {max_risk_result.V0:.0f} Hm³")
        print(f"   Tiempo colchón inferior: {max_risk_result.tiempo_colchon_inferior:.1f}%")
        print(f"   Tasa éxito: {max_risk_result.success_rate:.1f}%")
        print(f"   Cota promedio: {max_risk_result.cota_promedio:.1f} msnm")

        # =====================================================================
        # TRADE-OFFS Y RECOMENDACIONES
        # =====================================================================
        print("\n" + "=" * 80)
        print("⚖️ TRADE-OFFS IDENTIFICADOS")
        print("=" * 80)

        # Analizar correlaciones
        v0_vals = [r.V0 for r in self.results]
        energy_vals = [r.avg_annual_energy for r in self.results]
        deficit_vals = [r.deficit_prom_1r for r in self.results]
        risk_vals = [r.tiempo_colchon_inferior for r in self.results]

        # Correlación V0 vs Energía
        corr_energy = np.corrcoef(v0_vals, energy_vals)[0, 1]
        print(f"\n📊 V0 vs Energía: correlación = {corr_energy:.3f}")
        if corr_energy > 0.5:
            print("   → Mayor V0 tiende a generar MÁS energía")
        elif corr_energy < -0.5:
            print("   → Mayor V0 tiende a generar MENOS energía")
        else:
            print("   → Relación débil o no lineal")

        # Correlación V0 vs Déficit
        corr_deficit = np.corrcoef(v0_vals, deficit_vals)[0, 1]
        print(f"\n💧 V0 vs Déficit 1R: correlación = {corr_deficit:.3f}")
        if corr_deficit > 0.5:
            print("   → Mayor V0 tiende a AUMENTAR déficits (contraintuitivo)")
        elif corr_deficit < -0.5:
            print("   → Mayor V0 tiende a REDUCIR déficits (esperado)")
        else:
            print("   → Relación débil o no lineal")

        # Correlación V0 vs Riesgo
        corr_risk = np.corrcoef(v0_vals, risk_vals)[0, 1]
        print(f"\n⚠️ V0 vs Riesgo Operativo: correlación = {corr_risk:.3f}")
        if corr_risk > 0.5:
            print("   → Mayor V0 tiende a AUMENTAR riesgo (contraintuitivo)")
        elif corr_risk < -0.5:
            print("   → Mayor V0 tiende a REDUCIR riesgo (esperado)")
        else:
            print("   → Relación débil o no lineal")

        # =====================================================================
        # RECOMENDACIONES
        # =====================================================================
        print("\n" + "=" * 80)
        print("💡 RECOMENDACIONES BASADAS EN ANÁLISIS")
        print("=" * 80)

        # Encontrar V0 balanceado (buena energía + bajo déficit + bajo riesgo)
        # Normalizar métricas (0-1) para comparación
        def normalize(vals):
            min_val, max_val = min(vals), max(vals)
            if max_val == min_val:
                return [0.5] * len(vals)
            return [(v - min_val) / (max_val - min_val) for v in vals]

        # Invertir déficit y riesgo (menor es mejor)
        norm_energy = normalize(energy_vals)
        norm_deficit = [1 - v for v in normalize(deficit_vals)]
        norm_risk = [1 - v for v in normalize(risk_vals)]

        # Score balanceado (ponderado: 40% energía, 30% déficit, 30% riesgo)
        balanced_scores = [
            0.40 * e + 0.30 * d + 0.30 * r
            for e, d, r in zip(norm_energy, norm_deficit, norm_risk)
        ]

        best_balanced_idx = np.argmax(balanced_scores)
        best_balanced = self.results[best_balanced_idx]

        print("\n🎯 V0 BALANCEADO RECOMENDADO (40% energía, 30% déficit, 30% riesgo):")
        print(f"   V0: {best_balanced.V0:.0f} Hm³")
        print(f"   Score balanceado: {balanced_scores[best_balanced_idx]:.3f}")
        print(f"   Energía: {best_balanced.avg_annual_energy:,.0f} MWh/año")
        print(f"   Déficit prom 1R: {best_balanced.deficit_prom_1r:.2f} Hm³/mes")
        print(f"   Tiempo colchón inferior: {best_balanced.tiempo_colchon_inferior:.1f}%")
        print(f"   Tasa éxito: {best_balanced.success_rate:.1f}%")

        # Rango operativo recomendado
        percentile_25 = np.percentile(v0_vals, 25)
        percentile_75 = np.percentile(v0_vals, 75)
        print(f"\n📏 RANGO OPERATIVO RECOMENDADO:")
        print(f"   V0 mínimo conservador: {percentile_25:.0f} Hm³ (percentil 25)")
        print(f"   V0 máximo conservador: {percentile_75:.0f} Hm³ (percentil 75)")
        print(f"   V0 balanceado óptimo: {best_balanced.V0:.0f} Hm³")

        print("\n" + "=" * 80)

    def print_interpretive_report(self):
        """
        Imprime reporte interpretativo con conclusiones claras y accionables.
        Diseñado para verificación rápida de coherencia y resultados principales.
        """
        if not self.results:
            print("⚠️ No hay resultados para el reporte")
            return

        print("\n" + "=" * 80)
        print("📋 REPORTE INTERPRETATIVO - ANÁLISIS DE SENSIBILIDAD V0")
        print("=" * 80)

        # Extraer datos clave
        v0_values = [r.V0 for r in self.results]
        v0_min, v0_max = min(v0_values), max(v0_values)
        
        # Resultados con mejor desempeño
        max_energy = max(self.results, key=lambda r: r.avg_annual_energy)
        max_success = max(self.results, key=lambda r: r.success_rate)
        min_deficit = min(self.results, key=lambda r: r.deficit_prom_1r)
        min_risk = min(self.results, key=lambda r: r.tiempo_colchon_inferior)
        
        # Calcular rangos y variabilidad
        energies = [r.avg_annual_energy for r in self.results]
        deficits = [r.deficit_prom_1r for r in self.results]
        risks = [r.tiempo_colchon_inferior for r in self.results]
        
        energy_range = max(energies) - min(energies)
        energy_cv = (np.std(energies) / np.mean(energies) * 100) if energies else 0
        
        print("\n┌─────────────────────────────────────────────────────────────────────────┐")
        print("│ 🔍 CONTEXTO DEL ANÁLISIS                                                │")
        print("└─────────────────────────────────────────────────────────────────────────┘")
        print(f"\n✓ Rango V0 evaluado: {v0_min:.0f} - {v0_max:.0f} Hm³")
        print(f"✓ Número de configuraciones: {len(self.results)}")
        print(f"✓ Escenarios Monte Carlo por configuración: {self.n_scenarios}")
        print(f"✓ Período simulado: {self.n_years} años ({self.start_year}-{self.start_year + self.n_years - 1})")

        print("\n┌─────────────────────────────────────────────────────────────────────────┐")
        print("│ 📊 HALLAZGOS PRINCIPALES                                                │")
        print("└─────────────────────────────────────────────────────────────────────────┘")

        # 1. SENSIBILIDAD ENERGÉTICA
        print("\n1️⃣  GENERACIÓN ENERGÉTICA")
        print(f"   • Rango de producción: {min(energies):,.0f} - {max(energies):,.0f} MWh/año")
        print(f"   • Variabilidad: ±{energy_range/2:,.0f} MWh/año ({energy_cv:.1f}% CV)")
        print(f"   • Configuración óptima: V0 = {max_energy.V0:.0f} Hm³ → {max_energy.avg_annual_energy:,.0f} MWh/año")
        
        if energy_cv < 5:
            print("   ✓ INTERPRETACIÓN: Generación ESTABLE - poco sensible a V0")
        elif energy_cv < 15:
            print("   ⚠ INTERPRETACIÓN: Generación MODERADAMENTE sensible a V0")
        else:
            print("   ⚠️ INTERPRETACIÓN: Generación MUY sensible a V0 - requiere control estricto")

        # 2. CONFIABILIDAD OPERATIVA
        print("\n2️⃣  CONFIABILIDAD Y ÉXITO")
        success_rates = [r.success_rate for r in self.results]
        print(f"   • Tasa de éxito promedio: {np.mean(success_rates):.1f}%")
        print(f"   • Rango: {min(success_rates):.1f}% - {max(success_rates):.1f}%")
        print(f"   • Mejor configuración: V0 = {max_success.V0:.0f} Hm³ → {max_success.success_rate:.1f}% éxito")
        
        if min(success_rates) < 50:
            print("   ⚠️ INTERPRETACIÓN: ALERTA - Algunos V0 tienen baja confiabilidad (<50%)")
        elif min(success_rates) < 80:
            print("   ⚠ INTERPRETACIÓN: Confiabilidad VARIABLE - V0 bajo reduce éxito")
        else:
            print("   ✓ INTERPRETACIÓN: Sistema ROBUSTO - alta confiabilidad en todo el rango")

        # 3. SEGURIDAD HÍDRICA
        print("\n3️⃣  SEGURIDAD HÍDRICA (Déficits)")
        print(f"   • Déficit 1R promedio: {np.mean(deficits):.2f} Hm³/mes")
        print(f"   • Rango déficit: {min(deficits):.2f} - {max(deficits):.2f} Hm³/mes")
        print(f"   • Mejor configuración: V0 = {min_deficit.V0:.0f} Hm³ → {min_deficit.deficit_prom_1r:.2f} Hm³/mes")
        
        max_deficit_val = max(deficits)
        if max_deficit_val > 1.0:
            print(f"   ⚠️ INTERPRETACIÓN: CRÍTICO - V0 bajo genera déficits significativos (>{max_deficit_val:.2f} Hm³/mes)")
        elif max_deficit_val > 0.5:
            print(f"   ⚠ INTERPRETACIÓN: V0 bajo puede generar déficits moderados (~{max_deficit_val:.2f} Hm³/mes)")
        else:
            print(f"   ✓ INTERPRETACIÓN: Déficits CONTROLADOS en todo el rango (<0.5 Hm³/mes)")

        # 4. RIESGO OPERATIVO
        print("\n4️⃣  RIESGO OPERATIVO (Tiempo en Colchón Inferior)")
        print(f"   • Riesgo promedio: {np.mean(risks):.1f}% del tiempo")
        print(f"   • Rango: {min(risks):.1f}% - {max(risks):.1f}%")
        print(f"   • Mejor configuración: V0 = {min_risk.V0:.0f} Hm³ → {min_risk.tiempo_colchon_inferior:.1f}% riesgo")
        
        max_risk_val = max(risks)
        if max_risk_val > 50:
            print(f"   ⚠️ INTERPRETACIÓN: ALTO RIESGO - V0 bajo pasa >{max_risk_val:.0f}% en zona crítica")
        elif max_risk_val > 30:
            print(f"   ⚠ INTERPRETACIÓN: Riesgo MODERADO - V0 bajo aumenta tensión operativa")
        else:
            print(f"   ✓ INTERPRETACIÓN: Riesgo BAJO - operación mayormente en zonas seguras")

        print("\n┌─────────────────────────────────────────────────────────────────────────┐")
        print("│ 🎯 RELACIONES CLAVE IDENTIFICADAS                                       │")
        print("└─────────────────────────────────────────────────────────────────────────┘")

        # Correlaciones
        corr_v0_energy = np.corrcoef(v0_values, energies)[0, 1]
        corr_v0_deficit = np.corrcoef(v0_values, deficits)[0, 1]
        corr_v0_risk = np.corrcoef(v0_values, risks)[0, 1]

        print("\n📈 V0 vs Generación Energética:")
        print(f"   Correlación: {corr_v0_energy:+.3f}")
        if abs(corr_v0_energy) > 0.7:
            direction = "AUMENTA" if corr_v0_energy > 0 else "DISMINUYE"
            print(f"   ✓ Relación FUERTE: Mayor V0 → {direction} energía significativamente")
        elif abs(corr_v0_energy) > 0.4:
            direction = "aumenta" if corr_v0_energy > 0 else "disminuye"
            print(f"   → Relación MODERADA: Mayor V0 → {direction} energía moderadamente")
        else:
            print(f"   → Relación DÉBIL: V0 tiene poco impacto directo en energía")

        print("\n💧 V0 vs Déficit Hídrico (1R):")
        print(f"   Correlación: {corr_v0_deficit:+.3f}")
        if corr_v0_deficit < -0.7:
            print(f"   ✓ Relación FUERTE NEGATIVA: Mayor V0 → REDUCE déficits significativamente")
        elif corr_v0_deficit < -0.4:
            print(f"   → Relación MODERADA: Mayor V0 → reduce déficits moderadamente")
        else:
            print(f"   ⚠ ATENCIÓN: V0 no reduce déficits como se esperaría (revisar restricciones)")

        print("\n⚠️ V0 vs Riesgo Operativo:")
        print(f"   Correlación: {corr_v0_risk:+.3f}")
        if corr_v0_risk < -0.7:
            print(f"   ✓ Relación FUERTE NEGATIVA: Mayor V0 → REDUCE riesgo significativamente")
        elif corr_v0_risk < -0.4:
            print(f"   → Relación MODERADA: Mayor V0 → reduce riesgo moderadamente")
        else:
            print(f"   ⚠ ATENCIÓN: Mayor V0 no reduce riesgo como se esperaría")

        print("\n┌─────────────────────────────────────────────────────────────────────────┐")
        print("│ 💡 RECOMENDACIÓN OPERATIVA                                              │")
        print("└─────────────────────────────────────────────────────────────────────────┘")

        # Calcular V0 balanceado
        norm_energy = [(e - min(energies)) / (max(energies) - min(energies)) if max(energies) != min(energies) else 0.5 for e in energies]
        norm_deficit = [1 - ((d - min(deficits)) / (max(deficits) - min(deficits))) if max(deficits) != min(deficits) else 0.5 for d in deficits]
        norm_risk = [1 - ((r - min(risks)) / (max(risks) - min(risks))) if max(risks) != min(risks) else 0.5 for r in risks]
        
        balanced_scores = [0.40 * e + 0.30 * d + 0.30 * r for e, d, r in zip(norm_energy, norm_deficit, norm_risk)]
        best_idx = np.argmax(balanced_scores)
        best_result = self.results[best_idx]

        print(f"\n🎯 V0 ÓPTIMO BALANCEADO: {best_result.V0:.0f} Hm³")
        print(f"   (Ponderación: 40% energía, 30% déficit, 30% riesgo)")
        print(f"\n   Desempeño esperado:")
        print(f"   • Energía anual: {best_result.avg_annual_energy:,.0f} MWh/año")
        print(f"   • Tasa de éxito: {best_result.success_rate:.1f}%")
        print(f"   • Déficit 1R: {best_result.deficit_prom_1r:.2f} Hm³/mes")
        print(f"   • Riesgo operativo: {best_result.tiempo_colchon_inferior:.1f}% del tiempo")
        print(f"   • Eficiencia: {best_result.eficiencia_energetica:.2f} MWh/Hm³")

        # Rango recomendado
        percentile_25 = np.percentile(v0_values, 25)
        percentile_75 = np.percentile(v0_values, 75)
        
        print(f"\n📊 RANGO OPERATIVO CONSERVADOR:")
        print(f"   • Mínimo recomendado: {percentile_25:.0f} Hm³ (evita riesgos altos)")
        print(f"   • Óptimo balanceado:  {best_result.V0:.0f} Hm³ (mejor trade-off)")
        print(f"   • Máximo recomendado: {percentile_75:.0f} Hm³ (maximiza seguridad)")

        print("\n┌─────────────────────────────────────────────────────────────────────────┐")
        print("│ ✅ VERIFICACIÓN DE COHERENCIA                                           │")
        print("└─────────────────────────────────────────────────────────────────────────┘")

        coherence_checks = []
        
        # Check 1: Mayor V0 → Mayor energía
        if corr_v0_energy > 0:
            coherence_checks.append("✓ Mayor V0 aumenta energía (esperado)")
        else:
            coherence_checks.append("⚠ Mayor V0 NO aumenta energía (revisar)")
        
        # Check 2: Mayor V0 → Menor déficit
        if corr_v0_deficit < 0:
            coherence_checks.append("✓ Mayor V0 reduce déficits (esperado)")
        else:
            coherence_checks.append("⚠ Mayor V0 NO reduce déficits (revisar)")
        
        # Check 3: Mayor V0 → Menor riesgo
        if corr_v0_risk < 0:
            coherence_checks.append("✓ Mayor V0 reduce riesgo (esperado)")
        else:
            coherence_checks.append("⚠ Mayor V0 NO reduce riesgo (revisar)")
        
        # Check 4: Energía en rango razonable
        if 50000 < np.mean(energies) < 200000:
            coherence_checks.append(f"✓ Energía en rango razonable (~{np.mean(energies)/1000:.0f} GWh/año)")
        else:
            coherence_checks.append(f"⚠ Energía fuera de rango esperado ({np.mean(energies)/1000:.0f} GWh/año)")
        
        # Check 5: Déficits razonables
        if np.mean(deficits) < 2.0:
            coherence_checks.append("✓ Déficits en rango aceptable (<2 Hm³/mes)")
        else:
            coherence_checks.append(f"⚠ Déficits elevados ({np.mean(deficits):.2f} Hm³/mes)")

        # Check 6: Tasa de éxito razonable
        if np.mean(success_rates) > 70:
            coherence_checks.append(f"✓ Tasa de éxito alta ({np.mean(success_rates):.1f}%)")
        elif np.mean(success_rates) > 50:
            coherence_checks.append(f"→ Tasa de éxito moderada ({np.mean(success_rates):.1f}%)")
        else:
            coherence_checks.append(f"⚠️ Tasa de éxito baja ({np.mean(success_rates):.1f}%)")

        print()
        for check in coherence_checks:
            print(f"   {check}")

        # Conclusión final
        warnings = sum(1 for check in coherence_checks if '⚠' in check)
        
        print("\n" + "=" * 80)
        if warnings == 0:
            print("✅ COHERENCIA TOTAL: Todos los resultados son consistentes con el comportamiento esperado")
        elif warnings <= 2:
            print(f"⚠️ COHERENCIA PARCIAL: {warnings} verificaciones requieren atención")
        else:
            print(f"⚠️⚠️ REVISAR MODELO: {warnings} verificaciones indican posibles inconsistencias")
        print("=" * 80)


# =============================================================================
# HELPERS DE INTERFAZ
# =============================================================================
# NOTA: Funciones movidas a ui_helpers.py
# Importar desde: from ui_helpers import get_input, format_time


def main():
    """Función principal - interfaz interactiva."""

    print("\n" + "╔" + "═" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  🔬 ANÁLISIS DE SENSIBILIDAD DEL VOLUMEN INICIAL (V0)".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "═" * 68 + "╝")
    print("\n📋 Descripción:")
    print("   Evalúa cómo diferentes volúmenes iniciales afectan el desempeño")
    print("   del sistema usando simulaciones Monte Carlo multi-año.")
    print("\n🎯 Objetivos:")
    print("   • Identificar V0 óptimo para diferentes prioridades")
    print("   • Cuantificar trade-offs entre energía, déficit y riesgo")
    print("   • Generar recomendaciones operativas basadas en datos")
    print("\n" + "─" * 70)

    try:
        # Parámetros de simulación
        print("\n" + "╔" + "═" * 68 + "╗")
        print("║  📋 CONFIGURACIÓN DEL ANÁLISIS" + " " * 37 + "║")
        print("╚" + "═" * 68 + "╝")

        print("\n⏰ Parámetros Temporales:")
        start_year = get_input(
            "   📅 Año inicial",
            default=1960,
            input_type=int
        )
        n_years = get_input(
            "   📆 Número de años por escenario",
            default=64,
            input_type=int
        )
        n_scenarios = get_input(
            "   🎲 Escenarios Monte Carlo por V0",
            default=50,
            input_type=int
        )

        print("\n� Rango de Volumen Inicial:")
        V0_min = get_input(
            "   � V0 mínimo (Hm³)",
            default=500,
            input_type=float
        )
        V0_max = get_input(
            "   � V0 máximo (Hm³)",
            default=5000,
            input_type=float
        )

        print("\n� Resolución del Análisis:")
        print("   �💡 Los puntos se distribuyen uniformemente en el rango.")
        print(f"   💡 Ejemplo: 5 puntos en [{V0_min:.0f}-{V0_max:.0f}] → ", end="")
        example_points = np.linspace(V0_min, V0_max, 5)
        print(f"[{', '.join([f'{p:.0f}' for p in example_points])}]")
        
        n_points = get_input(
            "   🎯 Número de puntos a evaluar",
            default=10,
            input_type=int
        )

        # Resumen de configuración
        total_simulations = n_points * n_scenarios
        estimated_time = total_simulations * 0.5 / 60

        print("\n" + "─" * 70)
        print("📊 RESUMEN DE CONFIGURACIÓN")
        print("─" * 70)
        print(f"   Simulaciones totales:  {total_simulations:,}")
        print(f"   Estructura:            {n_points} puntos × {n_scenarios} escenarios")
        print(f"   Período:               {n_years} años ({start_year}-{start_year + n_years - 1})")
        print(f"   ⏱️  Tiempo estimado:     ~{estimated_time:.1f} minutos")
        print("─" * 70)

        print("\n💭 Mientras esperas, puedes:")
        print("   ☕ Prepararte un café")
        print("   📧 Revisar tus emails")
        print("   🧘 Meditar sobre el sentido de la vida")
        print("   📊 Revisar la documentación del modelo")

        confirm = get_input(
            "\n❓ ¿Continuar con el análisis? [s/N]",
            default="N"
        )
        if confirm.lower() not in ['s', 'sí', 'si', 'y', 'yes']:
            print("\n" + "─" * 70)
            print("❌ Análisis cancelado por el usuario")
            print("💡 Tip: Puedes reducir n_points o n_scenarios para análisis más rápido")
            print("─" * 70)
            return

        print("\n" + "╔" + "═" * 68 + "╗")
        print("║  🚀 INICIANDO ANÁLISIS DE SENSIBILIDAD" + " " * 29 + "║")
        print("╚" + "═" * 68 + "╝")

        # Medición de rendimiento
        start_time = time.time()
        process = psutil.Process()

        # Crear analizador
        analyzer = SensitivityAnalyzer(
            start_year=start_year,
            n_years=n_years,
            n_scenarios=n_scenarios,
            block_len=3,
            random_state=42
        )

        # Ejecutar análisis
        analyzer.run_analysis(
            V0_range=(V0_min, V0_max),
            n_points=n_points,
            verbose=True
        )

        # Imprimir resumen detallado
        analyzer.print_summary()

        # Exportar resultados
        print("\n" + "═" * 70)
        print("💾 EXPORTANDO RESULTADOS")
        print("═" * 70)
        
        csv_path = analyzer.export_results_to_csv()
        print(f"\n✅ Datos completos:")
        print(f"   📄 {Path(csv_path).name}")
        print(f"   📍 {csv_path}")
        
        # Exportar análisis de casos borde
        edge_cases_path = analyzer.export_edge_cases_analysis()
        if edge_cases_path:
            print(f"\n✅ Casos borde (10 escenarios críticos):")
            print(f"   📄 {Path(edge_cases_path).name}")
            print(f"   📍 {edge_cases_path}")

        # Generar gráficos
        print("\n" + "═" * 70)
        print("📊 GENERANDO VISUALIZACIONES")
        print("═" * 70)
        print("\nCreando gráficos de alta calidad (300 DPI)...")
        
        plot_files = analyzer.generate_sensitivity_plots()
        
        print(f"\n✅ {len(plot_files)} gráficos generados exitosamente:")
        for i, plot_file in enumerate(plot_files, 1):
            filename = Path(plot_file).name
            if 'estrategicos' in filename:
                print(f"\n   {i}. 📈 {filename}")
                print(f"      └─ 9 gráficos de KPIs estratégicos (grid 3x3)")
            elif 'complementario' in filename:
                print(f"\n   {i}. 📊 {filename}")
                print(f"      └─ 4 análisis de trade-offs (grid 2x2)")
            elif 'dashboard' in filename:
                print(f"\n   {i}. 🎯 {filename}")
                print(f"      └─ Dashboard ejecutivo multi-dimensional")
            else:
                print(f"\n   {i}. 📉 {filename}")

        # Estadísticas de rendimiento
        execution_time = time.time() - start_time
        memory_mb = process.memory_info().rss / (1024 * 1024)

        print("\n" + "╔" + "═" * 68 + "╗")
        print("║  ⚡ ESTADÍSTICAS DE RENDIMIENTO" + " " * 36 + "║")
        print("╚" + "═" * 68 + "╝")
        
        print(f"\n⏱️  Tiempo de ejecución:")
        print(f"   └─ Total: {format_time(execution_time)}")
        print(f"   └─ Por simulación: {execution_time / total_simulations:.3f}s")
        print(f"   └─ Por punto V0: {execution_time / n_points:.1f}s")
        
        print(f"\n💾 Uso de memoria:")
        print(f"   └─ RAM utilizada: {memory_mb:.1f} MB")
        
        print(f"\n📊 Productividad:")
        print(f"   └─ Simulaciones completadas: {total_simulations:,}")
        print(f"   └─ Tasa: {total_simulations / (execution_time / 60):.1f} sim/min")
        
        print("\n" + "─" * 70)

        # REPORTE FINAL INTERPRETATIVO
        analyzer.print_interpretive_report()

        print("\n" + "╔" + "═" * 68 + "╗")
        print("║" + " " * 68 + "║")
        print("║" + "  ✅ ANÁLISIS COMPLETADO EXITOSAMENTE".center(68) + "║")
        print("║" + " " * 68 + "║")
        print("╚" + "═" * 68 + "╝")
        
        print("\n📁 Archivos generados:")
        print(f"   📄 {len(plot_files)} gráficos PNG")
        print(f"   📊 2 archivos CSV")
        print(f"   📍 Ubicación: {Path('resultados').absolute()}")
        
        print("\n💡 Próximos pasos:")
        print("   1. Revisar gráficos en la carpeta 'resultados'")
        print("   2. Analizar CSV de casos borde para escenarios críticos")
        print("   3. Usar V0 balanceado recomendado en simulaciones futuras")
        print("\n" + "─" * 70 + "\n")

    except KeyboardInterrupt:
        print("\n\n👋 Análisis interrumpido por el usuario")
    except Exception as e:
        print(f"\n❌ Error durante el análisis: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
