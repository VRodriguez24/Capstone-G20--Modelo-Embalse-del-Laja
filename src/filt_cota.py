"""
MÓDULO DE FILTRACIONES CON CALIBRACIÓN AUTOMÁTICA
===============================================

Combina:
1. Linearización PWL de filtraciones (original)
2. Calibración automática de parámetros de filtración
3. Optimización de coeficientes del polinomio

Funciones principales:
- cota_from_volumen(): Convierte volumen a cota
- filtraciones_from_volumen(): Calcula filtraciones desde volumen  
- build_pwl_final_segments(): Genera segmentos PWL optimizados
- calibrate_filtration_coefficients(): Calibración automática

Autor: Capstone G20 - UC
"""

from typing import Dict, Any, List, Callable, Optional, Tuple
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import warnings
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from abc import ABC, abstractmethod

# Imports científicos para calibración
try:
    from scipy.optimize import minimize, differential_evolution
    from scipy.stats import uniform, norm
    from sklearn.model_selection import TimeSeriesSplit
    from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel as C
    CALIBRATION_AVAILABLE = True
except ImportError:
    CALIBRATION_AVAILABLE = False
    print("⚠️ Módulos de calibración no disponibles. Funcionalidad básica activa.")

# Suppress warnings para calibración
warnings.filterwarnings('ignore', category=UserWarning)

# =============================
# TABLA VOLUMEN-COTA ORIGINAL
# =============================

# Tabla volumen-cota original (71 puntos, volúmenes en Hm³)
VOLUMEN_TABLE = [
    0, 48.28954, 97.47766, 147.26746, 197.35679, 248.04517, 299.43508,
    351.82341, 405.0131, 459.20122, 514.48761, 570.97736, 628.56274,
    687.35149, 747.53804, 808.92531, 871.61054, 935.59635, 1000.88273,
    1067.4697, 1135.25477, 1204.23795, 1274.32464, 1345.60945, 1417.89268,
    1491.07712, 1565.25999, 1640.4439, 1716.42655, 1793.41026, 1871.19533,
    1949.97619, 2029.56105, 2110.14171, 2191.52373, 2273.9068, 2357.18845,
    2441.47116, 2526.65244, 2612.83215, 2700.01554, 2788.19472, 2877.37496,
    2967.75593, 3059.03548, 3151.31608, 3244.69758, 3339.17471, 3434.65552,
    3531.13476, 3628.71226, 3727.4905, 3827.36962, 3928.44686, 4030.62499,
    4133.90402, 4238.58084, 4344.35855, 4451.33437, 4559.61076, 4668.98805,
    4779.66329, 4891.53927, 5004.41367, 5118.38896, 5233.46515, 5349.83928,
    5467.31431, 5585.88761, 5705.66164, 5826.53656
]

# =============================
# COEFICIENTES DE FILTRACIÓN
# =============================

# Coeficientes por defecto (pueden ser calibrados)
DEFAULT_FILTRATION_COEFFICIENTS = {
    'a0': -133471.205667,
    'a1': 251.668765787,
    'a2': -0.112314280288,
    'a3': -0.000031180464,
    'a4': 0.000000022628942
}

# Coeficientes actuales (pueden ser actualizados por calibración)
CURRENT_FILTRATION_COEFFICIENTS = DEFAULT_FILTRATION_COEFFICIENTS.copy()

# =============================
# FUNCIONES BÁSICAS
# =============================

def cota_from_volumen(volumen: float) -> float:
    """
    Convierte volumen (Hm³) a cota (m) usando interpolación lineal.
    Args:
        volumen: Volumen del embalse en Hm3
    Returns:
        Cota correspondiente en metros
    """
    if volumen <= 0:
        return 1300.0
    if volumen >= VOLUMEN_TABLE[-1]:
        return 1370.0

    # Buscar índices para interpolación
    for i in range(1, len(VOLUMEN_TABLE)):
        if volumen <= VOLUMEN_TABLE[i]:
            # Interpolación lineal entre puntos i-1 e i
            v1, v2 = VOLUMEN_TABLE[i-1], VOLUMEN_TABLE[i]
            c1, c2 = 1300 + (i-1), 1300 + i
            cota = c1 + (c2-c1) * (volumen-v1)/(v2-v1)
            return min(max(cota, 1300.0), 1370.0)

    return 1370.0


def filtraciones_from_cota(cota: float, coefficients: Dict[str, float] = None) -> float:
    """
    Función polinomial de 4to grado para filtraciones basada en cota.
    
    Args:
        cota: Cota del embalse en metros
        coefficients: Coeficientes opcionales (usa actuales si None)
    Returns:
        Filtraciones en m³/s
    """
    if coefficients is None:
        coefficients = CURRENT_FILTRATION_COEFFICIENTS
    
    a0 = coefficients['a0']
    a1 = coefficients['a1']
    a2 = coefficients['a2']
    a3 = coefficients['a3']
    a4 = coefficients['a4']
    
    return a0 + (a1 * cota) + (a2 * cota**2) + (a3 * cota**3) + (a4 * cota**4)


def filtraciones_from_volumen(volumen: float, coefficients: Dict[str, float] = None) -> float:
    """
    Calcula filtraciones (m³/s) basado en volumen (Hm³).

    Args:
        volumen: Volumen del embalse en Hm³
        coefficients: Coeficientes opcionales de filtración
    Returns:
        Filtraciones en m³/s
    """
    cota = cota_from_volumen(volumen)
    return filtraciones_from_cota(cota, coefficients)


# =============================
# FUNCIONES PWL (ORIGINAL)
# =============================

def _calculate_segment_error(v_start: float, v_end: float, 
                           coefficients: Dict[str, float] = None) -> float:
    """Calcula error máximo de aproximación lineal en un segmento."""
    f1 = filtraciones_from_volumen(v_start, coefficients)
    f2 = filtraciones_from_volumen(v_end, coefficients)
    slope = (f2 - f1) / (v_end - v_start)
    intercept = f1 - slope * v_start

    max_error = 0.0
    test_points = np.linspace(v_start, v_end, 50)
    for v in test_points:
        f_real = filtraciones_from_volumen(v, coefficients)
        f_pwl = slope * v + intercept
        error = abs(f_real - f_pwl)
        max_error = max(max_error, error)

    return max_error


def _subdivide_segment(v_start: float, v_end: float,
                       target_error: float,
                       coefficients: Dict[str, float] = None) -> List[float]:
    """
    Subdivide un segmento si el error excede la tolerancia.
    """
    current_error = _calculate_segment_error(v_start, v_end, coefficients)
    
    if current_error <= target_error or (v_end - v_start) < 100:
        return [v_start, v_end]
    
    # Buscar mejor punto de división
    best_split = None
    min_max_error = float('inf')
    n_candidates = min(10, int((v_end - v_start) / 100))
    
    for i in range(1, n_candidates):
        split_point = v_start + (v_end - v_start) * i / n_candidates
        error1 = _calculate_segment_error(v_start, split_point, coefficients)
        error2 = _calculate_segment_error(split_point, v_end, coefficients)
        max_error_with_split = max(error1, error2)
        
        if max_error_with_split < min_max_error:
            min_max_error = max_error_with_split
            best_split = split_point
    
    if best_split is None:
        return [v_start, v_end]
    
    # Subdivisión recursiva
    left_breaks = _subdivide_segment(v_start, best_split, target_error, coefficients)
    right_breaks = _subdivide_segment(best_split, v_end, target_error, coefficients)
    
    return left_breaks + right_breaks[1:]  # Evitar duplicar punto medio


def _generate_breakpoints(V_max: float, target_error: float, 
                         coefficients: Dict[str, float] = None) -> List[float]:
    """
    Genera breakpoints optimizados usando análisis de curvatura.
    """
    # Puntos estratégicos base (límites de colchones)
    strategic_points = [0.0, 1200.0, 1370.0, 1900.0, V_max]
    
    final_breaks = [0.0]
    for i in range(len(strategic_points) - 1):
        start, end = strategic_points[i], strategic_points[i + 1]
        segment_breaks = _subdivide_segment(start, end, target_error, coefficients)
        
        # Agregar puntos intermedios
        for bp in segment_breaks[1:]:
            if bp not in final_breaks:
                final_breaks.append(bp)
    
    return sorted(final_breaks)


def build_pwl_final_segments(V_max: float = 5582.0, 
                           coefficients: Dict[str, float] = None) -> Dict[int, Dict[str, Any]]:
    """
    Genera segmentos PWL optimizados para linearizar función de filtraciones.
    
    Args:
        V_max: Volumen máximo del embalse (Hm³)
        coefficients: Coeficientes de filtración a usar
        
    Returns:
        Dict con segmentos {k: {v_min, v_max, slope, intercept, ...}}
    """
    # Usar coeficientes actuales si no se especifican
    if coefficients is None:
        coefficients = CURRENT_FILTRATION_COEFFICIENTS
    
    # Generar breakpoints optimizados
    breaks = _generate_breakpoints(V_max, target_error=0.05, coefficients=coefficients)
    n_segments = len(breaks) - 1
    
    segments: Dict[int, Dict[str, Any]] = {}
    total_error = 0.0
    
    for i in range(n_segments):
        v1, v2 = breaks[i], breaks[i + 1]
        
        # Calcular parámetros del segmento lineal
        f1 = filtraciones_from_volumen(v1, coefficients)
        f2 = filtraciones_from_volumen(v2, coefficients)
        slope = (f2 - f1) / (v2 - v1)
        intercept = f1 - slope * v1
        
        # Calcular error máximo del segmento
        max_error = _calculate_segment_error(v1, v2, coefficients)
        total_error += max_error
        
        # Tipo de colchón operativo
        if v1 < 1200:
            colchon_type = "Inferior"
        elif v1 < 1370:
            colchon_type = "Transición"
        elif v1 < 1900:
            colchon_type = "Intermedio"
        else:
            colchon_type = "Superior"
        
        segments[i + 1] = {
            "v_min": v1,
            "v_max": v2,
            "slope": slope,
            "intercept": intercept,
            "max_error": max_error,
            "colchon_type": colchon_type
        }
    
    # Metadatos
    segments["_metadata"] = {
        "total_error": total_error,
        "method": "adaptive_curvature_analysis_with_calibration",
        "breakpoints": breaks,
        "n_segments": n_segments,
        "coefficients_used": coefficients.copy()
    }

    return segments


def eval_pwl_final(vol: float, segments: Dict[int, Dict[str, Any]]) -> float:
    """
    Evalúa la función PWL en un volumen dado.
    
    Args:
        vol: Volumen en Hm³
        segments: Segmentos PWL
        
    Returns:
        Valor de filtración aproximado (m³/s)
    """
    # Filtrar metadatos
    numeric_segs = {k: v for k, v in segments.items() if isinstance(k, int)}
    
    # Buscar segmento que contiene el volumen
    for seg in numeric_segs.values():
        if seg["v_min"] <= vol <= seg["v_max"]:
            return seg["slope"] * vol + seg["intercept"]
    
    # Extrapolación fuera del rango
    if vol < 0:
        seg = numeric_segs[1]  # Primer segmento
    else:
        seg = numeric_segs[max(numeric_segs.keys())]  # Último segmento
    
    return seg["slope"] * vol + seg["intercept"]


# =============================
# CALIBRACIÓN AUTOMÁTICA
# =============================

@dataclass
class CalibrationParameter:
    """
    Definición de un parámetro para calibración.
    """
    name: str
    bounds: tuple
    initial_value: float = None
    parameter_type: str = 'continuous'
    description: str = ""
    
    def __post_init__(self):
        if self.initial_value is None:
            self.initial_value = (self.bounds[0] + self.bounds[1]) / 2


@dataclass
class CalibrationResult:
    """
    Resultado de un proceso de calibración.
    """
    parameters: Dict[str, float]
    objective_value: float
    metrics: Dict[str, float]
    execution_time: float
    algorithm_used: str
    validation_scores: Dict[str, float] = None


class FilterCalibrator:
    """
    Calibrador específico para parámetros de filtración.
    """
    
    def __init__(self, historical_data: Optional[pd.DataFrame] = None):
        """
        Inicializa el calibrador de filtración.
        
        Args:
            historical_data: Datos históricos de filtración (opcional)
        """
        self.historical_data = historical_data
        self.default_parameters = [
            CalibrationParameter(
                name="a0",
                bounds=(-150000.0, -120000.0),
                description="Coeficiente independiente del polinomio"
            ),
            CalibrationParameter(
                name="a1", 
                bounds=(220.0, 280.0),
                description="Coeficiente lineal del polinomio"
            ),
            CalibrationParameter(
                name="a2",
                bounds=(-0.13, -0.10),
                description="Coeficiente cuadrático del polinomio"
            ),
            CalibrationParameter(
                name="a3",
                bounds=(-0.000035, -0.000028),
                description="Coeficiente cúbico del polinomio"
            ),
            CalibrationParameter(
                name="a4",
                bounds=(0.000000020, 0.000000025),
                description="Coeficiente cuártico del polinomio"
            )
        ]
    
    def _objective_function(self, coeffs: List[float]) -> float:
        """
        Función objetivo para calibración (minimizar error).
        
        Args:
            coeffs: Lista de coeficientes [a0, a1, a2, a3, a4]
            
        Returns:
            Error a minimizar
        """
        # Crear diccionario de coeficientes
        coeff_dict = {
            'a0': coeffs[0],
            'a1': coeffs[1], 
            'a2': coeffs[2],
            'a3': coeffs[3],
            'a4': coeffs[4]
        }
        
        # Evaluar función en puntos de prueba
        test_cotas = np.linspace(1300, 1370, 100)
        errors = []
        
        for cota in test_cotas:
            # Función calibrada
            filtr_calibrated = filtraciones_from_cota(cota, coeff_dict)
            
            # Función original  
            filtr_original = filtraciones_from_cota(cota, DEFAULT_FILTRATION_COEFFICIENTS)
            
            # Error relativo
            if abs(filtr_original) > 1e-6:
                error = abs(filtr_calibrated - filtr_original) / abs(filtr_original)
            else:
                error = abs(filtr_calibrated - filtr_original)
            
            errors.append(error)
        
        # Penalizar valores no físicos
        penalty = 0
        for cota in test_cotas:
            filtr = filtraciones_from_cota(cota, coeff_dict)
            if filtr < 0 or filtr > 20:  # Filtraciones fuera de rango físico
                penalty += 1000
        
        return np.mean(errors) + penalty
    
    def calibrate_coefficients(self, algorithm: str = 'differential_evolution') -> CalibrationResult:
        """
        Calibra los coeficientes de filtración.
        
        Args:
            algorithm: Algoritmo de optimización ('differential_evolution', 'minimize')
            
        Returns:
            Resultado de la calibración
        """
        if not CALIBRATION_AVAILABLE:
            raise ImportError("Módulos de calibración no disponibles")
        
        print(f"🔧 CALIBRANDO COEFICIENTES DE FILTRACIÓN")
        print("=" * 50)
        print(f"📊 Algoritmo: {algorithm}")
        
        start_time = datetime.now()
        
        # Preparar límites
        bounds = [param.bounds for param in self.default_parameters]
        
        if algorithm == 'differential_evolution':
            # Optimización con evolución diferencial
            result = differential_evolution(
                self._objective_function,
                bounds,
                maxiter=100,
                popsize=15,
                seed=42
            )
            
            optimal_coeffs = result.x
            final_error = result.fun
            success = result.success
            
        elif algorithm == 'minimize':
            # Optimización con método Nelder-Mead
            x0 = [param.initial_value for param in self.default_parameters]
            
            result = minimize(
                self._objective_function,
                x0,
                method='Nelder-Mead',
                options={'maxiter': 500}
            )
            
            optimal_coeffs = result.x
            final_error = result.fun
            success = result.success
        
        else:
            raise ValueError(f"Algoritmo no soportado: {algorithm}")
        
        # Construir resultado
        optimal_params = {
            param.name: optimal_coeffs[i] 
            for i, param in enumerate(self.default_parameters)
        }
        
        execution_time = (datetime.now() - start_time).total_seconds()
        
        print(f"✅ Calibración completada en {execution_time:.2f}s")
        print(f"📊 Error final: {final_error:.6f}")
        print(f"🎯 Éxito: {'Sí' if success else 'No'}")
        
        return CalibrationResult(
            parameters=optimal_params,
            objective_value=final_error,
            metrics={"success": success, "iterations": 100},
            execution_time=execution_time,
            algorithm_used=algorithm
        )
    
    def apply_calibrated_coefficients(self, calibration_result: CalibrationResult):
        """
        Aplica coeficientes calibrados globalmente.
        
        Args:
            calibration_result: Resultado de calibración
        """
        global CURRENT_FILTRATION_COEFFICIENTS
        
        CURRENT_FILTRATION_COEFFICIENTS.update(calibration_result.parameters)
        
        print(f"✅ Coeficientes actualizados globalmente:")
        for name, value in calibration_result.parameters.items():
            print(f"   {name}: {value:.8f}")


# =============================
# FUNCIONES DE CONVENIENCIA
# =============================

def quick_filtration_calibration(algorithm: str = 'differential_evolution') -> CalibrationResult:
    """
    Calibración rápida de coeficientes de filtración.
    
    Args:
        algorithm: Algoritmo de optimización
        
    Returns:
        Resultado de calibración
    """
    calibrator = FilterCalibrator()
    return calibrator.calibrate_coefficients(algorithm)


def update_filtration_coefficients(new_coefficients: Dict[str, float]):
    """
    Actualiza coeficientes de filtración manualmente.
    
    Args:
        new_coefficients: Diccionario con nuevos coeficientes
    """
    global CURRENT_FILTRATION_COEFFICIENTS
    
    CURRENT_FILTRATION_COEFFICIENTS.update(new_coefficients)
    print(f"✅ Coeficientes actualizados:")
    for name, value in new_coefficients.items():
        print(f"   {name}: {value:.8f}")


def get_current_coefficients() -> Dict[str, float]:
    """
    Obtiene los coeficientes actuales de filtración.
    
    Returns:
        Diccionario con coeficientes actuales
    """
    return CURRENT_FILTRATION_COEFFICIENTS.copy()


def reset_to_default_coefficients():
    """
    Restaura coeficientes a valores por defecto.
    """
    global CURRENT_FILTRATION_COEFFICIENTS
    
    CURRENT_FILTRATION_COEFFICIENTS = DEFAULT_FILTRATION_COEFFICIENTS.copy()
    print("✅ Coeficientes restaurados a valores por defecto")


# Generar segmentos PWL al importar el módulo (con coeficientes actuales)
PWL_SEGMENTS = build_pwl_final_segments(V_max=5582.0)


def get_pwl_segments() -> Dict[int, Dict[str, Any]]:
    """
    Obtiene los segmentos PWL precalculados con coeficientes actuales.
    
    Returns:
        Diccionario con los segmentos PWL optimizados
    """
    global PWL_SEGMENTS
    # Regenerar si los coeficientes han cambiado
    PWL_SEGMENTS = build_pwl_final_segments(V_max=5582.0)
    return PWL_SEGMENTS


# =============================
# FUNCIONES DE TESTING
# =============================

def test_calibration():
    """Prueba el sistema de calibración."""
    if not CALIBRATION_AVAILABLE:
        print("❌ Módulos de calibración no disponibles")
        return
    
    print("🧪 PRUEBA DEL SISTEMA DE CALIBRACIÓN")
    print("=" * 50)
    
    try:
        # Calibración rápida
        result = quick_filtration_calibration()
        
        print(f"\n📊 Parámetros calibrados:")
        for name, value in result.parameters.items():
            print(f"   {name}: {value:.8f}")
        
        # Aplicar coeficientes
        calibrator = FilterCalibrator()
        calibrator.apply_calibrated_coefficients(result)
        
        # Regenerar segmentos PWL con nuevos coeficientes
        new_segments = build_pwl_final_segments()
        
        print(f"\n✅ Calibración exitosa")
        print(f"📊 Segmentos PWL regenerados: {len(new_segments)-1}")
        
    except Exception as e:
        print(f"❌ Error en calibración: {e}")


def test_funciones():
    """Prueba las funciones básicas de conversión."""
    print("🧪 Pruebas de funciones de filtración:")
    
    volumenes_prueba = [0, 500, 1000, 1500, 2000, 3000, 5582]
    
    for vol in volumenes_prueba:
        cota = cota_from_volumen(vol)
        filtr = filtraciones_from_volumen(vol)
        print(f"V={vol:4.0f} Hm³ -> Cota={cota:6.1f} m -> "
              f"Filtr={filtr:6.2f} m³/s")

    # Info de segmentos
    numeric_segments = {k: v for k, v in PWL_SEGMENTS.items()
                        if isinstance(k, int)}
    print(f"\n📊 Segmentos PWL generados: {len(numeric_segments)}")


def generate_summary():
    """Genera resumen técnico de la linearización PWL con calibración."""
    print("🎯 FILT_COTA CON CALIBRACIÓN - RESUMEN TÉCNICO")
    print("=" * 60)
    
    metadata = PWL_SEGMENTS.get("_metadata", {})
    current_coeffs = get_current_coefficients()
    
    print("📊 ESPECIFICACIONES:")
    print(f"   • Método: {metadata.get('method', 'N/A')}")
    print(f"   • Número de segmentos: {metadata.get('n_segments', 0)}")
    print(f"   • Error total: {metadata.get('total_error', 0):.4f} m³/s")
    print(f"   • Calibración disponible: {'Sí' if CALIBRATION_AVAILABLE else 'No'}")
    
    print(f"\n🔧 COEFICIENTES ACTUALES:")
    for name, value in current_coeffs.items():
        print(f"   {name}: {value:.8f}")
    
    print(f"\n💻 USO BÁSICO:")
    print("   from filt_cota import filtraciones_from_volumen")
    print("   filtr = filtraciones_from_volumen(1500.0)")
    
    print(f"\n🔧 USO CON CALIBRACIÓN:")
    print("   from filt_cota import quick_filtration_calibration")
    print("   result = quick_filtration_calibration()")


if __name__ == "__main__":
    print("🧪 TESTING: FILT_COTA CON CALIBRACIÓN INTEGRADA")
    print("=" * 60)
    
    # Pruebas básicas
    test_funciones()
    
    # Prueba de calibración si está disponible
    if CALIBRATION_AVAILABLE:
        test_calibration()
    
    print("\n" + "=" * 60)
    generate_summary()
    
    print("\n✅ Módulo integrado - Filtración PWL con calibración automática")