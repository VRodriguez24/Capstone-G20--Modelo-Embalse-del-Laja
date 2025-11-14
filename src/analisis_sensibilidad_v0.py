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
            print()

        # Ejecutar simulaciones para cada V0
        for idx, V0 in enumerate(V0_values):
            if verbose:
                # Loader compacto - solo una línea que se actualiza
                print(f"\r🔄 Progreso: [{idx+1}/{n_points}] V0={V0:.0f} Hm³ | "
                      f"Simulando {self.n_scenarios} escenarios...",
                      end='', flush=True)

            try:
                # Ejecutar simulación Monte Carlo
                # (sin verbose para output limpio)
                result = self._evaluate_single_V0(V0, verbose=False)
                self.results.append(result)

                if verbose:
                    # Mostrar resultado compacto en la misma línea
                    status = "✅" if result.success_rate > 0 else "⚠️"
                    print(f"\r{status} [{idx+1}/{n_points}] "
                          f"V0={V0:.0f} Hm³ | "
                          f"Éxito: {result.success_rate:.0f}% | "
                          f"Energía: {result.avg_annual_energy:,.0f} MWh/año"
                          + " " * 10)

            except Exception as e:
                if verbose:
                    error_msg = str(e)[:40]
                    print(f"\r❌ [{idx+1}/{n_points}] "
                          f"V0={V0:.0f} Hm³ | Error: {error_msg}"
                          + " " * 10)
                continue

        if verbose:
            print("\n" + "=" * 70)
            print("✅ ANÁLISIS DE SENSIBILIDAD COMPLETADO")
            print("=" * 70)
            print(f"📊 Puntos evaluados: {len(self.results)}/{n_points}")

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
        output_dir: str = "resultados"
    ) -> List[str]:
        """
        Genera visualizaciones de análisis de sensibilidad.

        Crea gráficos mostrando:
        - V0 vs Energía promedio anual
        - V0 vs Tasa de éxito
        - V0 vs Uso de El Toro
        - V0 vs Volumen final promedio
        - V0 vs KPIs estratégicos (cotas, déficits, confiabilidad)

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
        avg_toro = [r.avg_toro_usage for r in self.results]
        avg_final_vol = [r.avg_final_volume for r in self.results]
        std_final_vol = [r.std_final_volume for r in self.results]

        # Extraer KPIs si están disponibles
        cotas_prom = []
        deficit_max = []
        confiabilidad = []

        for r in self.results:
            kpis = r.kpis_agregados
            cotas_prom.append(kpis.get("cota_prom_msnm", 0))
            deficit_max.append(kpis.get("deficit_max_m3s", 0))
            confiabilidad.append(kpis.get("confiabilidad_%", 0))

        # Configurar estilo
        plt.rcParams['font.size'] = 10
        plt.rcParams['figure.figsize'] = (16, 12)

        # Crear figura con 6 subplots (3x2)
        fig, axes = plt.subplots(3, 2, figsize=(16, 14))
        ax1, ax2, ax3, ax4, ax5, ax6 = axes.flatten()

        # Plot 1: V0 vs Energía Promedio Anual
        ax1.plot(V0_values, avg_energies, 'b-o', linewidth=2, markersize=6)
        ax1.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax1.set_ylabel('Energía Promedio Anual [MWh/año]', fontweight='bold')
        ax1.set_title('Sensibilidad: V0 vs Generación Energética',
                      fontweight='bold', fontsize=12)
        ax1.grid(True, alpha=0.3)

        # Marcar máximo
        max_energy_idx = np.argmax(avg_energies)
        ax1.plot(
            V0_values[max_energy_idx],
            avg_energies[max_energy_idx],
            'r*',
            markersize=15,
            label=f'Máximo: V0={V0_values[max_energy_idx]:.0f} Hm³'
        )
        ax1.legend()

        # Plot 2: V0 vs Tasa de Éxito
        ax2.plot(V0_values, success_rates, 'g-o', linewidth=2, markersize=6)
        ax2.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax2.set_ylabel('Tasa de Éxito [%]', fontweight='bold')
        ax2.set_title('Sensibilidad: V0 vs Tasa de Éxito Monte Carlo',
                      fontweight='bold', fontsize=12)
        ax2.set_ylim(0, 105)
        ax2.grid(True, alpha=0.3)

        # Plot 3: V0 vs Uso de El Toro
        ax3.plot(V0_values, avg_toro, 'r-o', linewidth=2, markersize=6)
        ax3.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax3.set_ylabel('Uso Promedio El Toro [Hm³]', fontweight='bold')
        ax3.set_title('Sensibilidad: V0 vs Dependencia del Embalse',
                      fontweight='bold', fontsize=12)
        ax3.grid(True, alpha=0.3)

        # Plot 4: V0 vs Volumen Final
        # (con banda de desviación)
        ax4.fill_between(
            V0_values,
            (
                np.array(avg_final_vol) -
                np.array(std_final_vol)
            ),
            (
                np.array(avg_final_vol) +
                np.array(std_final_vol)
            ),
            alpha=0.3,
            color='lightblue',
            label='±1 desviación estándar'
        )
        ax4.plot(
            V0_values,
            avg_final_vol,
            'b-o',
            linewidth=2,
            markersize=6,
            label='Volumen final promedio'
        )
        # Línea de referencia (V_final = V_inicial)
        ax4.plot(
            V0_values,
            V0_values,
            'k--',
            alpha=0.5,
            linewidth=1,
            label='Equilibrio (V_final = V0)'
        )
        ax4.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
        ax4.set_ylabel('Volumen Final Promedio [Hm³]', fontweight='bold')
        ax4.set_title('Sensibilidad: V0 vs Volumen Final',
                      fontweight='bold', fontsize=12)
        ax4.grid(True, alpha=0.3)
        ax4.legend()

        # Plot 5: V0 vs Cota Promedio
        if any(cotas_prom):
            ax5.plot(V0_values, cotas_prom, 'm-o', linewidth=2, markersize=6)
            ax5.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
            ax5.set_ylabel('Cota Promedio [msnm]', fontweight='bold')
            ax5.set_title('Sensibilidad: V0 vs Cota del Lago',
                          fontweight='bold', fontsize=12)
            ax5.grid(True, alpha=0.3)
        else:
            ax5.text(
                0.5,
                0.5,
                'KPIs no disponibles',
                ha='center',
                va='center',
                transform=ax5.transAxes
            )

        # Plot 6: V0 vs Confiabilidad
        if any(confiabilidad):
            ax6.plot(
                V0_values,
                confiabilidad,
                'c-o',
                linewidth=2,
                markersize=6
            )
            ax6.set_xlabel('Volumen Inicial V0 [Hm³]', fontweight='bold')
            ax6.set_ylabel('Confiabilidad [%]', fontweight='bold')
            ax6.set_title(
                'Sensibilidad: V0 vs Confiabilidad',
                fontweight='bold',
                fontsize=12
            )
            ax6.set_ylim(0, 105)
            ax6.grid(True, alpha=0.3)

            # Marcar máximo
            max_conf_idx = np.argmax(confiabilidad)
            ax6.plot(
                V0_values[max_conf_idx],
                confiabilidad[max_conf_idx],
                'r*',
                markersize=15,
                label=f'Máximo: V0={V0_values[max_conf_idx]:.0f} Hm³'
            )
            ax6.legend()
        else:
            ax6.text(
                0.5,
                0.5,
                'KPIs no disponibles',
                ha='center',
                va='center',
                transform=ax6.transAxes
            )

        plt.tight_layout()

        # Guardar figura
        plot_file = output_path / "sensibilidad_v0_completo.png"
        plt.savefig(plot_file, dpi=300, bbox_inches='tight')
        plt.close()
        files_created.append(str(plot_file))

        return files_created

    def print_summary(self):
        """Imprime resumen de análisis de sensibilidad."""

        if not self.results:
            print("⚠️ No hay resultados para mostrar")
            return

        print("\n" + "=" * 70)
        print("📊 RESUMEN DE ANÁLISIS DE SENSIBILIDAD V0")
        print("=" * 70)

        # Crear tabla de resultados
        print(f"\n{'V0 [Hm³]':>10} {'Éxito[%]':>10} {'Energía[MWh/a]':>15} "
              f"{'Toro[Hm³]':>12} {'V_final[Hm³]':>14}")
        print("-" * 70)

        for r in self.results:
            print(f"{r.V0:>10.0f} {r.success_rate:>10.1f} "
                  f"{r.avg_annual_energy:>15.1f} {r.avg_toro_usage:>12.1f} "
                  f"{r.avg_final_volume:>14.1f}")

        # Identificar puntos óptimos
        print("\n" + "=" * 70)
        print("🎯 PUNTOS ÓPTIMOS IDENTIFICADOS")
        print("=" * 70)

        # Máxima energía
        max_energy_result = max(
            self.results, key=lambda r: r.avg_annual_energy
        )
        print("\n⚡ MÁXIMA ENERGÍA:")
        print(f"   V0 óptimo: {max_energy_result.V0:.0f} Hm³")
        print(
            f"   Energía: "
            f"{max_energy_result.avg_annual_energy:,.1f} MWh/año"
        )
        print(
            f"   Tasa éxito: {max_energy_result.success_rate:.1f}%"
        )

        # Máxima tasa de éxito
        max_success_result = max(
            self.results, key=lambda r: r.success_rate
        )
        print("\n✅ MÁXIMA TASA DE ÉXITO:")
        print(f"   V0 óptimo: {max_success_result.V0:.0f} Hm³")
        print(f"   Tasa éxito: {max_success_result.success_rate:.1f}%")
        print(
            f"   Energía: "
            f"{max_success_result.avg_annual_energy:,.1f} MWh/año"
        )

        # Mínimo uso de El Toro
        min_toro_result = min(
            self.results, key=lambda r: r.avg_toro_usage
        )
        print("\n🌊 MÍNIMA DEPENDENCIA DEL EMBALSE:")
        print(f"   V0 óptimo: {min_toro_result.V0:.0f} Hm³")
        print(f"   Uso El Toro: {min_toro_result.avg_toro_usage:.1f} Hm³")
        print(
            f"   Energía: "
            f"{min_toro_result.avg_annual_energy:,.1f} MWh/año"
        )

        # Mejor confiabilidad (si disponible)
        confiabilidades = [
            r.kpis_agregados.get("confiabilidad_%", 0)
            for r in self.results
        ]
        if any(confiabilidades):
            max_conf_result = max(
                self.results,
                key=lambda r: r.kpis_agregados.get(
                    "confiabilidad_%", 0
                )
            )
            conf_value = max_conf_result.kpis_agregados.get(
                "confiabilidad_%", 0
            )
            print("\n🎯 MÁXIMA CONFIABILIDAD:")
            print(f"   V0 óptimo: {max_conf_result.V0:.0f} Hm³")
            print(f"   Confiabilidad: {conf_value:.1f}%")
            print(
                f"   Energía: "
                f"{max_conf_result.avg_annual_energy:,.1f} MWh/año"
            )

        print("\n" + "=" * 70)


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
            default=50,
            input_type=int
        )

        print("\n📏 RANGO DE VOLUMEN INICIAL")
        print("-" * 70)
        V0_min = get_input("💧 V0 mínimo (Hm³)", default=500, input_type=float)
        V0_max = get_input("💧 V0 máximo (Hm³)", default=5000, input_type=float)

        print("\n💡 Los puntos se distribuyen uniformemente en el rango.")
        print(
            "Ejemplo: 5 puntos en [500-5000] → "
            "[500, 1625, 2750, 3875, 5000]"
        )
        n_points = get_input(
            "📍 Número de puntos a evaluar",
            default=10,
            input_type=int
        )

        # Advertencia si el análisis será extenso
        total_simulations = n_points * n_scenarios
        # ~0.5 seg por simulación
        estimated_time = total_simulations * 0.5 / 60

        print(f"\n⚠️ Se ejecutarán {total_simulations} simulaciones totales")
        print(f"   ({n_points} puntos × {n_scenarios} escenarios)")
        print(f"⏱️ Tiempo estimado: {estimated_time:.1f} minutos")
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
