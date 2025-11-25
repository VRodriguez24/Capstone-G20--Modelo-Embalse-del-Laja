"""
ANÁLISIS DE SENSIBILIDAD DEL VOLUMEN INICIAL (V0)

Evalúa cómo diferentes volúmenes iniciales afectan el desempeño
del sistema usando simulación Monte Carlo multi-año.

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
import warnings
import numpy as np
import pandas as pd
import matplotlib
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

# Suprimir warnings de matplotlib y unicode
warnings.filterwarnings('ignore', category=UserWarning)
matplotlib.rcParams['axes.unicode_minus'] = False


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

    def to_dict(self) -> Dict:
        """Convierte resultado a diccionario para análisis."""
        return {
            "V0": self.V0,
            "success_rate": self.success_rate,
            "avg_total_energy": self.avg_total_energy,
            "avg_annual_energy": self.avg_annual_energy,
            "avg_toro_usage": self.avg_toro_usage,
            "avg_final_volume": self.avg_final_volume,
            "std_final_volume": self.std_final_volume,
            **self.kpis_agregados
        }


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

            # Inicializar Gurobi silenciosamente
            # (muestra warnings antes del progreso)
            try:
                import gurobipy as gp
                dummy = gp.Model()
                dummy.Params.OutputFlag = 0
                dummy.optimize()
                del dummy
            except Exception:
                pass

            print()

        if verbose:
            print("\n🔄 Procesando puntos V0...\n")

        # Ejecutar simulaciones para cada V0
        for idx, V0 in enumerate(V0_values):
            if verbose:
                # Barra de progreso estilo montecarlo
                progress_pct = (idx + 1) / n_points * 100
                bar_len = 40
                filled = int(bar_len * (idx + 1) / n_points)
                bar = '█' * filled + '░' * (bar_len - filled)
                msg = f"\r[{bar}] {progress_pct:5.1f}% "
                msg += f"({idx + 1}/{n_points}) V0={V0:.0f} Hm³\n"
                print(msg, end='', flush=True)

            try:
                # Ejecutar simulación Monte Carlo
                # (sin verbose para output limpio)
                result = self._evaluate_single_V0(V0, verbose=False)
                self.results.append(result)

                # Mostrar estadísticas de éxito inmediatamente
                if verbose:
                    # Contar modelos exitosos
                    n_modelos_exitosos = sum(
                        len(s.get("results", []))
                        for s in result.scenarios_data
                    )
                    n_modelos_totales = (
                        len(result.scenarios_data) * self.n_years
                    )
                    pct_modelos = (
                        (n_modelos_exitosos / n_modelos_totales * 100)
                        if n_modelos_totales > 0 else 0
                    )

                    # Contar escenarios exitosos
                    n_escenarios_exitosos = len(result.scenarios_data)
                    n_escenarios_totales = self.n_scenarios
                    pct_escenarios = (
                        (n_escenarios_exitosos / n_escenarios_totales * 100)
                        if n_escenarios_totales > 0 else 0
                    )

                    print(
                        f"🎯 Escenarios: {n_escenarios_exitosos}/"
                        f"{n_escenarios_totales} "
                        f"({pct_escenarios:.1f}%) | "
                        f"Modelos: {n_modelos_exitosos}/"
                        f"{n_modelos_totales} "
                        f"({pct_modelos:.1f}%)\n"
                    )

            except Exception as e:
                if verbose:
                    error_msg = str(e)
                    # Extraer año crítico si está en el mensaje
                    if "año" in error_msg.lower():
                        print(f"\n⚠️ {error_msg}")
                    else:
                        msg_truncado = error_msg[:60]
                        print(f"\n❌ Error en V0={V0:.0f} Hm³: {msg_truncado}")
                continue

        if verbose:
            print("✅ ANÁLISIS DE SENSIBILIDAD COMPLETADO")
            print(f"\t📊 Puntos evaluados: {len(self.results)}/{n_points}")

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

        return SensitivityResult(
            V0=V0,
            success_rate=success_rate,
            avg_total_energy=avg_total_energy,
            avg_annual_energy=avg_annual_energy,
            avg_toro_usage=avg_toro_usage,
            avg_final_volume=avg_final_volume,
            std_final_volume=std_final_volume,
            kpis_agregados=kpis_agregados,
            scenarios_data=successful
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

    def generate_sensitivity_plots(
        self,
        output_dir: str = "resultados/analisis_sensibilidad"
    ) -> List[str]:
        """
        Genera visualizaciones profesionales de análisis de sensibilidad.

        Crea 5 gráficos especializados:
        1. V0 vs Generación Energética
        2. V0 vs Dependencia del Embalse
        3. V0 vs Uso de Presupuestos
        4. Sensibilidad Comparativa de KPIs
        5. Panel de KPIs (sin radar chart)

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
        output_path.mkdir(parents=True, exist_ok=True)
        files_created = []

        # Extraer datos para gráficos
        V0_values = np.array([r.V0 for r in self.results])
        success_rates = np.array([r.success_rate for r in self.results])
        avg_energies = np.array([r.avg_annual_energy for r in self.results])

        # Extraer KPIs estratégicos según especificación
        # KPI 1: Tiempo en colchones operativos
        tiempo_inferior = []
        tiempo_transicion = []
        tiempo_intermedio = []
        tiempo_superior = []

        # KPI 2: Uso de presupuestos
        uso_presupuesto_riego = []
        uso_presupuesto_gen = []

        # KPI 3: Déficits de riego
        deficits_1r = []  # Primeros regantes
        deficits_2r = []  # Segundos regantes
        deficit_pct_1r = []  # Porcentaje de demanda 1R

        # KPI 4: Factor de utilización
        factor_utilizacion = []

        # KPI adicional: Cota promedio (indicador de estado)
        cotas_prom = []

        for r in self.results:
            kpis = r.kpis_agregados if r.kpis_agregados else {}

            # KPI 1: Tiempo en colchones
            colchones = kpis.get("tiempo_colchones_%", {})
            tiempo_inferior.append(colchones.get("Inferior", 0))
            tiempo_transicion.append(colchones.get("Transicion", 0))
            tiempo_intermedio.append(colchones.get("Intermedio", 0))
            tiempo_superior.append(colchones.get("Superior", 0))

            # KPI 2: Uso de presupuestos (convertir strings "X.X%" a float)
            presupuestos = kpis.get("uso_presupuestos_%", {})
            riego_val = presupuestos.get("riego", 0)
            gen_val = presupuestos.get("generacion", 0)

            # Convertir strings "X.X%" o "N/A" a float
            if isinstance(riego_val, str):
                if riego_val.upper() == 'N/A':
                    riego_val = 0.0
                else:
                    riego_val = float(riego_val.replace('%', ''))
            if isinstance(gen_val, str):
                if gen_val.upper() == 'N/A':
                    gen_val = 0.0
                else:
                    gen_val = float(gen_val.replace('%', ''))

            uso_presupuesto_riego.append(float(riego_val))
            uso_presupuesto_gen.append(float(gen_val))

            # KPI 3: Déficits de riego
            deficit_prom = kpis.get("deficit_prom_hm3", {})
            deficits_1r.append(deficit_prom.get("1R", 0))
            deficits_2r.append(deficit_prom.get("2R", 0))

            deficit_pct = kpis.get("deficit_pct", {})
            deficit_pct_1r.append(deficit_pct.get("1R", 0))

            # KPI 4: Factor de utilización
            fu = kpis.get("factor_utilizacion_%", {})
            factor_utilizacion.append(fu.get("sistema", 0))

            # Cota promedio (indicador adicional)
            cota_data = kpis.get("cota_mensual", {})
            if cota_data:
                cota_prom = sum(cota_data.values()) / len(cota_data)
            else:
                cota_prom = 0
            cotas_prom.append(cota_prom)

        # Convertir a arrays
        tiempo_inferior = np.array(tiempo_inferior)
        tiempo_transicion = np.array(tiempo_transicion)
        tiempo_intermedio = np.array(tiempo_intermedio)
        tiempo_superior = np.array(tiempo_superior)
        uso_presupuesto_riego = np.array(uso_presupuesto_riego)
        uso_presupuesto_gen = np.array(uso_presupuesto_gen)
        deficits_1r = np.array(deficits_1r)
        deficits_2r = np.array(deficits_2r)
        deficit_pct_1r = np.array(deficit_pct_1r)
        factor_utilizacion = np.array(factor_utilizacion)
        cotas_prom = np.array(cotas_prom)

        # Configurar estilo profesional
        plt.rcParams['font.size'] = 11
        plt.rcParams['axes.labelsize'] = 12
        plt.rcParams['axes.titlesize'] = 14
        plt.rcParams['xtick.labelsize'] = 10
        plt.rcParams['ytick.labelsize'] = 10
        plt.rcParams['legend.fontsize'] = 10
        plt.rcParams['figure.titlesize'] = 16
        plt.rcParams['text.color'] = 'black'
        plt.rcParams['axes.labelcolor'] = 'black'
        plt.rcParams['xtick.color'] = 'black'
        plt.rcParams['ytick.color'] = 'black'

        # Paleta de colores profesional
        colors = {
            'primary': '#1f77b4',    # Azul científico
            'success': '#2ca02c',    # Verde
            'warning': '#ff7f0e',    # Naranja
            'danger': '#d62728',     # Rojo
            'azul': '#2e5f8a',       # Azul oscuro
            'cyan': '#17becf'        # Cyan
        }

        # ================================================================
        # GRÁFICO 1: V0 VS GENERACIÓN ENERGÉTICA
        # ================================================================
        fig1, ax1 = plt.subplots(figsize=(12, 7))

        # Línea principal con marcadores
        ax1.plot(V0_values, avg_energies, 'o-',
                 color=colors['primary'], linewidth=2.5, markersize=8,
                 label='Energía anual promedio', zorder=3)

        # Área sombreada bajo la curva
        ax1.fill_between(V0_values, 0, avg_energies,
                         alpha=0.2, color=colors['primary'])

        # Marcar valor máximo
        max_energy_idx = np.argmax(avg_energies)
        ax1.plot(V0_values[max_energy_idx], avg_energies[max_energy_idx], '*',
                 color=colors['warning'], markersize=20,
                 markeredgecolor='black', markeredgewidth=1.5,
                 label=f'Óptimo: {V0_values[max_energy_idx]:.0f} Hm³',
                 zorder=5)

        # Configuración de ejes
        ax1.set_xlabel(
            'Volumen Inicial (V0) [Hm³]',
            fontweight='bold', color='black'
        )
        ax1.set_ylabel(
            'Energía Promedio Anual [MWh/año]',
            fontweight='bold', color='black'
        )
        ax1.set_title('Sensibilidad: Volumen Inicial vs Generación Energética',
                      fontweight='bold', pad=25, color='black')
        ax1.grid(True, alpha=0.3, linestyle='--')
        ax1.legend(loc='best', framealpha=0.95)

        # Formato de números en eje Y
        ax1.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, p: f'{x:,.0f}')
        )

        plt.tight_layout()
        plot1_file = output_path / "sensibilidad_energia.png"
        plt.savefig(plot1_file, dpi=300, bbox_inches='tight')
        plt.close()
        files_created.append(str(plot1_file))

        # ================================================================
        # GRÁFICO 2: V0 VS APORTE DE EL TORO A RIEGO
        # ================================================================
        fig2, ax2 = plt.subplots(figsize=(12, 7))

        # Calcular aporte de El Toro EXCLUSIVAMENTE a riego
        # (déficit consolidado Def1 + Def2) como % de demanda total
        aporte_riego_pct = deficit_pct_1r  # Ya calculado arriba (% demanda)

        # Línea principal con marcadores
        ax2.plot(V0_values, aporte_riego_pct, 'o-',
                 color='#7b2cbf', linewidth=2.5, markersize=8,
                 label='Dependencia de riego', zorder=3)

        # Área sombreada bajo la curva
        ax2.fill_between(V0_values, 0, aporte_riego_pct,
                         alpha=0.2, color='#7b2cbf')

        # Marcar valor óptimo (mínima dependencia = mejor)
        min_dep_idx = np.argmin(aporte_riego_pct)
        ax2.plot(V0_values[min_dep_idx], aporte_riego_pct[min_dep_idx], '*',
                 color=colors['warning'], markersize=20,
                 markeredgecolor='black', markeredgewidth=1.5,
                 label=f'Óptimo: {V0_values[min_dep_idx]:.0f} Hm³',
                 zorder=5)

        # Configuración de ejes
        ax2.set_xlabel(
            'Volumen Inicial (V0) [Hm³]',
            fontweight='bold', color='black'
        )
        ax2.set_ylabel(
            'Aporte de El Toro a Riego [% de demanda total]',
            fontweight='bold', color='black'
        )
        ax2.set_title(
            'Sensibilidad: V0 vs Dependencia de Riego del Embalse',
            fontweight='bold', pad=25, color='black'
        )
        ax2.grid(True, alpha=0.3, linestyle='--')
        ax2.legend(loc='best', framealpha=0.95)

        # Formato de porcentajes en eje Y
        ax2.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, p: f'{x:.1f}%')
        )

        plt.tight_layout()
        plot2_file = output_path / "sensibilidad_aporte_riego.png"
        plt.savefig(plot2_file, dpi=300, bbox_inches='tight')
        plt.close()
        files_created.append(str(plot2_file))

        # ================================================================
        # GRÁFICO 3: V0 VS USO DE PRESUPUESTOS (SIN LÍNEA 100%)
        # ================================================================
        fig3, ax3 = plt.subplots(figsize=(12, 7))

        x = np.arange(len(V0_values))
        width = 0.35

        # Barras agrupadas
        ax3.bar(x - width/2, uso_presupuesto_riego, width,
                label='Presupuesto Riego', color=colors['success'],
                alpha=0.8, edgecolor='black', linewidth=1.2)
        ax3.bar(x + width/2, uso_presupuesto_gen, width,
                label='Presupuesto Generación', color=colors['primary'],
                alpha=0.8, edgecolor='black', linewidth=1.2)

        ax3.set_xlabel('Volumen Inicial (V0) [Hm³]', fontweight='bold',
                       color='black')
        ax3.set_ylabel('Uso de Presupuesto [%]', fontweight='bold',
                       color='black')
        ax3.set_title('Sensibilidad: Volumen Inicial vs Uso de Presupuestos',
                      fontweight='bold', pad=15, color='black')
        ax3.set_xticks(x)
        ax3.set_xticklabels([f'{v:.0f}' for v in V0_values],
                            rotation=45, ha='right')
        ax3.legend(loc='upper left', fontsize=11, framealpha=0.9)
        ax3.grid(True, alpha=0.3, linestyle='--', linewidth=0.8, axis='y')
        ax3.set_ylim(0, max(uso_presupuesto_riego.max(),
                            uso_presupuesto_gen.max()) * 1.1)

        plt.tight_layout()
        plot3_file = output_path / "sensibilidad_presupuestos.png"
        plt.savefig(plot3_file, dpi=300, bbox_inches='tight')
        plt.close()
        files_created.append(str(plot3_file))

        # ================================================================
        # GRÁFICO 4: PANEL DETALLADO DE LOS 4 KPIs ESTRATÉGICOS
        # ================================================================
        fig4 = plt.figure(figsize=(16, 12))
        gs = fig4.add_gridspec(3, 6, hspace=0.4, wspace=1.0)

        # =================================================================
        # FILA 1: KPI 1 - TIEMPO EN COLCHONES OPERATIVOS
        # =================================================================

        # Subplot 1.1: Distribución por colchones (stacked area)
        ax41 = fig4.add_subplot(gs[0, :])
        ax41.fill_between(V0_values, 0, tiempo_inferior,
                          alpha=0.7, color='#d62728', label='Inferior')
        ax41.fill_between(V0_values, tiempo_inferior,
                          tiempo_inferior + tiempo_transicion,
                          alpha=0.7, color='#ff7f0e', label='Transición')
        # Calcular acumulados para evitar líneas demasiado largas
        cum_trans = tiempo_inferior + tiempo_transicion
        cum_inter = cum_trans + tiempo_intermedio
        ax41.fill_between(V0_values, cum_trans,
                          cum_inter,
                          alpha=0.7, color='#2ca02c', label='Intermedio')
        ax41.fill_between(V0_values, cum_inter, 100,
                          alpha=0.7, color='#1f77b4', label='Superior')
        ax41.set_title('KPI 1: Distribución de Tiempo en Colchones Operativos',
                       fontweight='bold', color='black', fontsize=12)
        ax41.set_ylabel('Tiempo [%]', fontsize=10, color='black')
        ax41.set_xlabel('V0 [Hm³]', fontsize=10, color='black')
        ax41.set_ylim(0, 100)
        ax41.set_xlim(V0_values.min(), V0_values.max())  # Ajustar límites X
        ax41.margins(x=0.01)  # Reducir margen horizontal

        # Leyenda mejorada con porcentajes (promedio de todos los V0)
        prom_inferior = tiempo_inferior.mean()
        prom_transicion = tiempo_transicion.mean()
        prom_intermedio = tiempo_intermedio.mean()
        prom_superior = tiempo_superior.mean()

        # Crear leyenda con colores y porcentajes
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor='#d62728', alpha=0.7,
                  label=f'Inferior ({prom_inferior:.1f}%)'),
            Patch(facecolor='#ff7f0e', alpha=0.7,
                  label=f'Transición ({prom_transicion:.1f}%)'),
            Patch(facecolor='#2ca02c', alpha=0.7,
                  label=f'Intermedio ({prom_intermedio:.1f}%)'),
            Patch(facecolor='#1f77b4', alpha=0.7,
                  label=f'Superior ({prom_superior:.1f}%)')
        ]
        ax41.legend(handles=legend_elements, loc='upper right',
                    fontsize=9, ncol=4, framealpha=0.95)
        ax41.grid(True, alpha=0.3, axis='y')

        # =================================================================
        # FILA 2: KPI 2 Y KPI 3 (CENTRADOS)
        # =================================================================

        # Subplot 2.1: KPI 2 - Uso de Presupuestos (columnas 0-2)
        ax42 = fig4.add_subplot(gs[1, 0:3])
        x_pos = np.arange(len(V0_values))
        width = 0.35
        ax42.bar(x_pos - width/2, uso_presupuesto_riego, width,
                 label='Riego', color=colors['success'], alpha=0.8,
                 edgecolor='black', linewidth=0.8)
        ax42.bar(x_pos + width/2, uso_presupuesto_gen, width,
                 label='Generación', color=colors['primary'], alpha=0.8,
                 edgecolor='black', linewidth=0.8)
        # REMOVIDO: ax42.axhline(y=100, ...) según solicitud
        ax42.set_title('KPI 2: Uso de Presupuestos', fontweight='bold',
                       color='black', fontsize=11)
        ax42.set_ylabel('Uso [%]', fontsize=9, color='black')
        ax42.set_xlabel('V0 [Hm³]', fontsize=9, color='black')
        ax42.set_xticks(x_pos)
        ax42.set_xticklabels([f'{int(v)}' for v in V0_values],
                             rotation=0, ha='center', fontsize=9)
        ax42.legend(fontsize=9, loc='upper right', framealpha=0.95)
        ax42.grid(True, alpha=0.3, axis='y')
        ax42.set_ylim(0, max(uso_presupuesto_riego.max(),
                             uso_presupuesto_gen.max()) * 1.15)

        # Subplot 2.2: KPI 3 - Déficit de Riego Consolidado (columnas 3-5)
        ax43 = fig4.add_subplot(gs[1, 3:6])

        # Graficar déficit de primeros y segundos regantes
        ax43.plot(V0_values, deficits_1r, linewidth=2.5,
                  color='#dc2626', label='Déficit 1R (Primeros)',
                  alpha=0.9)
        ax43.plot(V0_values, deficits_2r, linewidth=2.5,
                  color='#f97316', label='Déficit 2R (Segundos)',
                  alpha=0.9)

        # Área sombreada para déficit total
        deficit_total = deficits_1r + deficits_2r
        ax43.fill_between(V0_values, 0, deficit_total,
                          color='#fecaca', alpha=0.3,
                          label='Déficit Total')

        ax43.set_title('KPI 3: Déficit de Riego (1R + 2R)',
                       fontweight='bold', color='black', fontsize=11)
        ax43.set_ylabel('Déficit [% de demanda]', fontsize=9,
                        color='black')
        ax43.set_xlabel('V0 [Hm³]', fontsize=9, color='black')
        ax43.grid(True, alpha=0.3)
        ax43.legend(fontsize=8, loc='best', framealpha=0.9)
        ax43.yaxis.set_major_formatter(
            plt.FuncFormatter(lambda x, p: f'{x:.1f}%')
        )

        # =================================================================
        # FILA 3: KPI 4 Y MÉTRICAS COMPLEMENTARIAS (CENTRADOS)
        # =================================================================

        # Subplot 3.1: KPI 4 - Factor de Utilización (columnas 0-1)
        ax44 = fig4.add_subplot(gs[2, 0:2])
        ax44.plot(V0_values, factor_utilizacion, 'o-',
                  color=colors['primary'], linewidth=2, markersize=6)
        ax44.fill_between(V0_values, 0, factor_utilizacion,
                          alpha=0.3, color=colors['primary'])
        ax44.set_title('KPI 4: Factor de Utilización Sistema',
                       fontweight='bold', color='black', fontsize=11)
        ax44.set_ylabel('Factor Utilización [%]', fontsize=9, color='black')
        ax44.set_xlabel('V0 [Hm³]', fontsize=9, color='black')
        ax44.grid(True, alpha=0.3)

        # Subplot 3.2: Nivel del Lago (columnas 2-3, centrado)
        ax45 = fig4.add_subplot(gs[2, 2:4])
        ax45.plot(V0_values, cotas_prom, 'o-',
                  color=colors['azul'], linewidth=2, markersize=6)
        ax45.fill_between(V0_values, cotas_prom.min(), cotas_prom,
                          alpha=0.3, color=colors['azul'])
        ax45.set_title('Nivel Promedio del Lago',
                       fontweight='bold', color='black', fontsize=11)
        ax45.set_ylabel('Cota [msnm]', fontsize=9, color='black')
        ax45.set_xlabel('V0 [Hm³]', fontsize=9, color='black')
        ax45.grid(True, alpha=0.3)

        # Subplot 3.3: Confiabilidad del Sistema (columnas 4-5)
        ax46 = fig4.add_subplot(gs[2, 4:6])
        ax46.plot(V0_values, success_rates, 'o-',
                  color=colors['success'], linewidth=2, markersize=6)
        ax46.fill_between(V0_values, 0, success_rates,
                          alpha=0.3, color=colors['success'])
        ax46.axhline(y=100, color='green', linestyle='--',
                     linewidth=1, alpha=0.5)
        ax46.set_title('Confiabilidad del Sistema',
                       fontweight='bold', color='black', fontsize=11)
        ax46.set_ylabel('Tasa de Éxito [%]', fontsize=9, color='black')
        ax46.set_xlabel('V0 [Hm³]', fontsize=9, color='black')
        ax46.set_ylim(0, 105)
        ax46.grid(True, alpha=0.3)

        # Título general
        fig4.suptitle(
            'Panel de los 4 KPIs Estratégicos: '
            'Análisis de Sensibilidad al Volumen Inicial',
            fontsize=15, fontweight='bold', y=0.995, color='black'
        )

        plt.savefig(output_path / "panel_kpis_multivariado.png",
                    dpi=300, bbox_inches='tight')
        plt.close()
        files_created.append(str(output_path / "panel_kpis_multivariado.png"))

        return files_created

    def print_summary(self):
        """
        Imprime resumen conciso del análisis de sensibilidad hidrológica.

        Muestra:
        - Rango analizado y configuración
        - Métricas clave: energía, cotas, confiabilidad
        - Evaluación rápida de sensibilidad
        - V0 óptimo recomendado
        """

        if not self.results:
            print("⚠️ No hay resultados para mostrar")
            return

        # Extraer datos
        V0_values = [r.V0 for r in self.results]
        energies = [r.avg_annual_energy for r in self.results]
        success_rates = [r.success_rate for r in self.results]

        # Extraer cotas promedio de KPIs
        cotas_prom = []
        for r in self.results:
            if r.kpis_agregados:
                cotas_prom.append(r.kpis_agregados.get("cota_prom_msnm", 0))
            else:
                cotas_prom.append(0)

        print("\n" + "═" * 80)
        print(
            "📊 RESUMEN: ANÁLISIS DE SENSIBILIDAD "
            "HIDROLÓGICA - VOLUMEN INICIAL"
        )
        print("═" * 80)

        # Contexto resumido
        v0_min = min(V0_values)
        v0_max = max(V0_values)
        print("\n📌 Configuración:")
        print(
            f"   • Rango V0: {v0_min:.0f} - {v0_max:.0f} Hm³ "
            f"({len(self.results)} puntos)"
        )
        print(
            f"   • Período: {self.start_year}-"
            f"{self.start_year + self.n_years - 1} "
            f"({self.n_years} años)"
        )
        print(f"   • Escenarios/punto: {self.n_scenarios}")

        # Métricas clave
        print("\n📈 Métricas Clave:")
        print(
            f"   • Energía: {min(energies):,.0f} - "
            f"{max(energies):,.0f} MWh/año"
        )

        if any(cotas_prom):
            min_cota = min([c for c in cotas_prom if c > 0])
            max_cota = max(cotas_prom)
            print(f"   • Cota: {min_cota:.1f} - {max_cota:.1f} msnm")
        print(
            f"   • Confiabilidad: {min(success_rates):.1f}% - "
            f"{max(success_rates):.1f}%"
        )

        # Métricas adicionales del modelo
        volumenes_finales = [r.avg_final_volume for r in self.results]
        uso_toro = [r.avg_toro_usage for r in self.results]

        print("\n📊 Métricas del Sistema:")
        print(
            f"   • Volumen final: {min(volumenes_finales):.0f} - "
            f"{max(volumenes_finales):.0f} Hm³"
        )
        print(
            f"   • Uso El Toro: {min(uso_toro):.0f} - "
            f"{max(uso_toro):.0f} Hm³ (acumulado)"
        )

        # Evaluación de sensibilidad
        print("\n🔍 Evaluación de Sensibilidad:")

        # Correlación V0 vs Energía
        corr_energia = safe_correlation(V0_values, energies)
        if corr_energia is None:
            print("   • Energía: Sin variación (todos los valores iguales)")
        else:
            if abs(corr_energia) > 0.7:
                sens_energia = "ALTA"
            elif abs(corr_energia) > 0.4:
                sens_energia = "MODERADA"
            else:
                sens_energia = "BAJA"
            print(
                f"   • Energía: Sensibilidad {sens_energia} "
                f"(corr: {corr_energia:+.2f})"
            )

        # Correlación V0 vs Cotas
        if any(cotas_prom):
            cotas_validas = [c for c in cotas_prom if c > 0]
            if len(cotas_validas) == len(V0_values):
                corr_cota = safe_correlation(V0_values, cotas_validas)
                if corr_cota is None:
                    print(
                        "   • Cota: Sin variación "
                        "(todos los valores iguales)"
                    )
                else:
                    if abs(corr_cota) > 0.7:
                        sens_cota = "ALTA"
                    elif abs(corr_cota) > 0.4:
                        sens_cota = "MODERADA"
                    else:
                        sens_cota = "BAJA"
                    print(
                        f"   • Cota: Sensibilidad {sens_cota} "
                        f"(corr: {corr_cota:+.2f})"
                    )

        # Correlación V0 vs Confiabilidad
        corr_conf = safe_correlation(V0_values, success_rates)
        if corr_conf is None:
            print(
                "   • Confiabilidad: Sin variación (100% éxito en todos "
                "los casos)"
            )
        else:
            if abs(corr_conf) > 0.7:
                sens_conf = "ALTA"
            elif abs(corr_conf) > 0.4:
                sens_conf = "MODERADA"
            else:
                sens_conf = "BAJA"
            print(
                f"   • Confiabilidad: Sensibilidad {sens_conf} "
                f"(corr: {corr_conf:+.2f})"
            )

        # Interpretación general
        print("\n💡 Interpretación General:")
        sensibilidades = []
        if corr_energia is not None and abs(corr_energia) > 0.4:
            sensibilidades.append("energía")
        cotas_validas_count = len([c for c in cotas_prom if c > 0])
        if any(cotas_prom) and cotas_validas_count == len(V0_values):
            if corr_cota is not None and abs(corr_cota) > 0.4:
                sensibilidades.append("nivel del lago")
        if corr_conf is not None and abs(corr_conf) > 0.4:
            sensibilidades.append("confiabilidad")

        if sensibilidades:
            sens_str = ', '.join(sensibilidades)
            print(
                f"   • El sistema muestra sensibilidad significativa "
                f"al V0 en: {sens_str}"
            )
        else:
            print(
                "   • El sistema es relativamente estable "
                "frente a cambios en V0"
            )

        if corr_energia is not None:
            if corr_energia > 0.4:
                print(
                    "   • Mayor V0 tiende a aumentar "
                    "la generación energética"
                )
            elif corr_energia < -0.4:
                print(
                    "   • Mayor V0 tiende a reducir "
                    "la generación energética"
                )

        # V0 óptimo
        print("\n🎯 V0 Óptimo Recomendado:")

        # Determinar V0 óptimo por energía
        max_energy_idx = np.argmax(energies)
        v0_max_energia = V0_values[max_energy_idx]

        print(f"   • V0 = {v0_max_energia:.0f} Hm³")
        print(
            f"     - Energía esperada: "
            f"{energies[max_energy_idx]:,.0f} MWh/año"
        )
        if any(cotas_prom) and cotas_prom[max_energy_idx] > 0:
            print(
                f"     - Cota promedio: "
                f"{cotas_prom[max_energy_idx]:.1f} msnm"
            )
        print(
            f"     - Confiabilidad: "
            f"{success_rates[max_energy_idx]:.1f}%"
        )

        print("\n" + "═" * 80)

        # Resumen ejecutivo final
        print("\n" + "=" * 80)
        print("" + " " * 25 + "📋 RESUMEN EJECUTIVO FINAL")
        print("=" * 80)

        # Hallazgo principal
        print("\n🎯 HALLAZGO PRINCIPAL:")
        max_idx = np.argmax(energies)
        min_idx = np.argmin(energies)
        delta_energia = energies[max_idx] - energies[min_idx]
        pct_mejora = (delta_energia / energies[min_idx]) * 100

        print(
            f"   Un aumento de V0 desde {V0_values[min_idx]:.0f} Hm³ "
            f"hasta {V0_values[max_idx]:.0f} Hm³"
        )
        print(
            f"   incrementa la energía anual en {delta_energia:,.0f} "
            f"MWh/año ({pct_mejora:.1f}%)"
        )

        # Recomendación operativa
        print("\n🎯 RECOMENDACIÓN OPERATIVA:")
        print(
            f"   V0 óptimo para máxima energía: "
            f"{V0_values[max_idx]:.0f} Hm³"
        )

        # Rango óptimo
        if len(energies) >= 5:
            # Encontrar valores cercanos al máximo (>95% del máximo)
            threshold = energies[max_idx] * 0.95
            optimos_idx = [i for i, e in enumerate(energies) if e >= threshold]
            if len(optimos_idx) > 1:
                v0_min_opt = V0_values[min(optimos_idx)]
                v0_max_opt = V0_values[max(optimos_idx)]
                print(
                    f"   Rango óptimo (>95% energía máxima): "
                    f"{v0_min_opt:.0f} - {v0_max_opt:.0f} Hm³"
                )

        # Confiabilidad del sistema
        avg_success = np.mean(success_rates)
        if avg_success == 100.0:
            print(
                "\n✅ CONFIABILIDAD: Sistema robusto - 100% éxito "
                "en todo el rango analizado"
            )
        elif avg_success >= 80:
            print(
                f"\n✅ CONFIABILIDAD: Sistema confiable - "
                f"{avg_success:.1f}% éxito promedio"
            )
        else:
            print(
                f"\n⚠️  CONFIABILIDAD: Sistema variable - "
                f"{avg_success:.1f}% éxito promedio"
            )

        # Balance hídrico
        delta_vol = np.mean(volumenes_finales) - np.mean(V0_values)
        if abs(delta_vol) < 100:
            balance = "EQUILIBRADO"
        elif delta_vol > 0:
            balance = "POSITIVO (acumula agua)"
        else:
            balance = "NEGATIVO (pierde agua)"
        print(f"   Balance hídrico promedio: {balance}")

        print("\n" + "=" * 80)


# =============================================================================
# HELPERS INTERNOS
# =============================================================================

def safe_correlation(x, y):
    """
    Calcula correlación de Pearson manejando casos especiales.

    Args:
        x, y: Arrays de valores

    Returns:
        Correlación o None si no se puede calcular
    """
    # Verificar si hay variación en ambas variables
    if np.std(x) == 0 or np.std(y) == 0:
        return None

    # Calcular correlación
    corr_matrix = np.corrcoef(x, y)
    return corr_matrix[0, 1]


# =============================================================================
# HELPERS DE INTERFAZ
# =============================================================================
# NOTA: Funciones movidas a ui_helpers.py
# Importar desde: from ui_helpers import get_input, format_time


def main():
    """Función principal - interfaz interactiva."""

    print("=" * 70)
    print(" 🔬 ANÁLISIS DE SENSIBILIDAD DEL VOLUMEN INICIAL (V0)")
    print("=" * 70)
    print("Evalúa cómo diferentes V0 afectan el desempeño del sistema")
    print("usando simulaciones Monte Carlo multi-año.")
    print("=" * 70)

    try:
        # Parámetros de simulación
        print("\n📋 CONFIGURACIÓN DEL ANÁLISIS")
        print("-" * 70)

        start_year = get_input(
            "📅 Año inicial",
            default=1960,
            input_type=int
        )
        n_years = get_input(
            "📆 Número de años por escenario",
            default=64,
            input_type=int
        )
        n_scenarios = get_input(
            "🎲 Escenarios Monte Carlo por V0",
            default=100,
            input_type=int
        )

        print("\n📏 RANGO DE VOLUMEN INICIAL")
        print("-" * 70)
        V0_min = get_input("💧 V0 mínimo (Hm³)", default=1000, input_type=float)
        V0_max = get_input("💧 V0 máximo (Hm³)", default=3586, input_type=float)

        print("\n💡 Los puntos se distribuyen uniformemente en el rango.")
        print(
            "Ejemplo: 5 puntos en [1000-3000] → "
            "[1000, 1500, 2000, 2500, 3000]"
        )
        n_points = get_input(
            "📍 Número de puntos a evaluar",
            default=5,
            input_type=int
        )

        # Advertencia si el análisis será extenso
        total_simulations = n_points * n_scenarios
        # ~ 40 seg por simulación
        estimated_time = total_simulations * 4 / 60

        print(f"\n⚠️  Se ejecutarán {total_simulations} simulaciones totales")
        print(f"   ({n_points} puntos x {n_scenarios} escenarios)")
        print(f"⏱️  Tiempo estimado: {estimated_time:.1f} minutos")
        print("\n💭 Esto va a demorar un poco... perfecto para:")
        print("   ☕ Prepararte un café")
        print("   🍕 Pedir una pizza")
        print("   🧘 Meditar sobre el sentido de la vida")

        confirm = get_input(
            "\n¿Continuar con el análisis? [s/N]",
            default="N"
        )
        if confirm.lower() not in ['s', 'sí', 'si', 'y', 'yes']:
            print("❌ Análisis cancelado. Quizás la próxima vez 😢")
            return

        print("\n🚀 Iniciando análisis de sensibilidad...")

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

        # Imprimir resumen
        analyzer.print_summary()

        # Exportar resultados
        print("\n💾 Exportando resultados...")
        csv_path = analyzer.export_results_to_csv()
        print(f"   ✅ CSV guardado: {csv_path}")

        # Generar gráficos
        print("\n📊 Generando visualizaciones...")
        plot_files = analyzer.generate_sensitivity_plots()
        print(f"   ✅ Gráficos generados: {len(plot_files)} archivos")
        for plot_file in plot_files:
            print(f"      📈 {Path(plot_file).name}")

        # Estadísticas de rendimiento
        execution_time = time.time() - start_time
        memory_mb = process.memory_info().rss / (1024 * 1024)

        print("\n" + "=" * 70)
        print("⚡ RENDIMIENTO")
        print("=" * 70)
        print(f"🕒 Tiempo total: {format_time(execution_time)}")
        print(f"💾 Memoria utilizada: {memory_mb:.1f} MB")
        print(f"📊 Simulaciones completadas: {total_simulations}")
        avg_time_per_sim = execution_time / total_simulations
        print(
            f"⏱️ Tiempo promedio por simulación: "
            f"{avg_time_per_sim:.2f}s"
        )
        print("=" * 70)

        print("\n✅ Análisis de sensibilidad completado exitosamente")

    except KeyboardInterrupt:
        print("\n\n👋 Análisis interrumpido por el usuario")
    except Exception as e:
        print(f"\n❌ Error durante el análisis: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
