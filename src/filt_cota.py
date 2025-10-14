"""
Módulo para cálculo de filtraciones y linearización PWL para el Embalse El Toro.

Este módulo contiene:
- Tabla de conversión volumen-cota original (71 puntos)
- Función polinomial de 4to grado para filtraciones basada en cota
- Segmentos PWL (Piecewise Linear) para linearización de filtraciones
- Funciones de conversión, cálculo y visualización
- Testing y comparación de métodos de linearización

OBJETIVO: Linearizar la función no-lineal de filtraciones f(V) = polinomio(cota(V))
usando segmentación PWL optimizada para minimizar error de aproximación.
"""
from typing import Dict, Any, List
import numpy as np
import matplotlib.pyplot as plt

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


def filtraciones_from_cota(cota: float) -> float:
    """
    Función polinomial de 4to grado para filtraciones basada en cota.
    Coeficientes derivados de la función original del embalse El Toro.
    Args:
        cota: Cota del embalse en metros
    Returns:
        Filtraciones en m³/s
    """
    a0 = -133471.205667
    a1 = 251.668765787
    a2 = -0.112314280288
    a3 = -0.000031180464
    a4 = 0.000000022628942
    return a0 + (a1 * cota) + (a2 * cota**2) + (a3 * cota**3) + (a4 * cota**4)


def filtraciones_from_volumen(volumen: float) -> float:
    """
    Calcula filtraciones (m³/s) basado en volumen (Hm³).
    Combina la conversión volumen->cota->filtraciones.
    Args:
        volumen: Volumen del embalse en Hm3
    Returns:
        Filtraciones en m³/s
    """
    cota = cota_from_volumen(volumen)
    return filtraciones_from_cota(cota)








def analyze_curvature_adaptive(V_max: float, target_error: float = 0.15) -> List[float]:
    """
    Analiza la curvatura de la función de filtración y genera breakpoints adaptativos
    para minimizar el error, especialmente en segmentos 1, 4, 5.
    
    Args:
        V_max: Volumen máximo
        target_error: Error objetivo por segmento (m³/s)
        
    Returns:
        Lista de breakpoints optimizados
    """
    # Puntos estratégicos base (colchones críticos)
    strategic_points = [0.0, 1200.0, 1370.0, 1900.0, V_max]
    
    # Analizar cada intervalo y subdividir si es necesario
    final_breaks = [0.0]
    
    for i in range(len(strategic_points) - 1):
        start, end = strategic_points[i], strategic_points[i + 1]
        
        # Evaluar si necesita subdivisión
        current_breaks = analyze_segment_for_subdivision(start, end, target_error)
        
        # Agregar puntos intermedios (excluyendo start que ya está)
        for bp in current_breaks[1:]:
            if bp not in final_breaks:
                final_breaks.append(bp)
    
    return sorted(final_breaks)


def analyze_segment_for_subdivision(v_start: float, v_end: float, 
                                  target_error: float) -> List[float]:
    """
    Analiza un segmento específico y determina si necesita subdivisión.
    
    Args:
        v_start: Volumen inicial
        v_end: Volumen final
        target_error: Error máximo permitido
        
    Returns:
        Lista de breakpoints para este segmento
    """
    def calculate_segment_error(start: float, end: float) -> float:
        """Calcula error máximo en un segmento"""
        f1 = filtraciones_from_volumen(start)
        f2 = filtraciones_from_volumen(end)
        slope = (f2 - f1) / (end - start)
        intercept = f1 - slope * start
        
        max_error = 0.0
        test_points = np.linspace(start, end, 50)
        for v in test_points:
            f_real = filtraciones_from_volumen(v)
            f_pwl = slope * v + intercept
            error = abs(f_real - f_pwl)
            max_error = max(max_error, error)
        
        return max_error
    
    # Verificar si el segmento actual necesita subdivisión
    current_error = calculate_segment_error(v_start, v_end)
    
    if current_error <= target_error or (v_end - v_start) < 100:
        return [v_start, v_end]
    
    # Necesita subdivisión - encontrar mejor punto de división
    best_split = None
    min_max_error = float('inf')
    
    # Buscar mejor punto de división evaluando múltiples opciones
    n_candidates = min(20, int((v_end - v_start) / 50))  # Máximo 20 candidatos
    
    for i in range(1, n_candidates):
        split_point = v_start + (v_end - v_start) * i / n_candidates
        
        # Calcular error máximo si dividimos aquí
        error1 = calculate_segment_error(v_start, split_point)
        error2 = calculate_segment_error(split_point, v_end)
        max_error_with_split = max(error1, error2)
        
        if max_error_with_split < min_max_error:
            min_max_error = max_error_with_split
            best_split = split_point
    
    if best_split is None:
        return [v_start, v_end]
    
    # Recursivamente subdividir si es necesario
    left_breaks = analyze_segment_for_subdivision(v_start, best_split, target_error)
    right_breaks = analyze_segment_for_subdivision(best_split, v_end, target_error)
    
    # Combinar resultados eliminando duplicados
    all_breaks = left_breaks + right_breaks[1:]  # Excluir primer punto de right_breaks
    return sorted(list(set(all_breaks)))


def optimize_pwl_breakpoints(V_max: float) -> List[float]:
    """
    Genera breakpoints altamente optimizados usando análisis adaptativo de curvatura.
    Enfoque especial en reducir error en segmentos problemáticos (1, 4, 5).
    
    Args:
        V_max: Volumen máximo del embalse
        
    Returns:
        Lista de breakpoints optimizados
    """
    # Usar análisis adaptativo con error objetivo más estricto
    return analyze_curvature_adaptive(V_max, target_error=0.15)


def build_pwl_final_segments(V_max: float = 5582.0) -> Dict[int, Dict[str, Any]]:
    """
    Genera segmentos PWL ultra-optimizados con análisis adaptativo de curvatura.
    Incluye soporte para aproximaciones SOS2 con variables alpha.
    
    Returns:
        Dict con segmentos {k: {v_min, v_max, slope, intercept, ...}}
    """
    # Generar breakpoints con análisis adaptativo
    breaks = optimize_pwl_breakpoints(V_max)
    n_segments = len(breaks) - 1
    
    segments: Dict[int, Dict[str, Any]] = {}
    total_error = 0.0
    
    # Calcular puntos de aproximación SOS2 para cada breakpoint
    sos2_points = []
    sos2_values = []
    
    for bp in breaks:
        sos2_points.append(bp)
        sos2_values.append(filtraciones_from_volumen(bp))
    
    for i in range(n_segments):
        v1, v2 = breaks[i], breaks[i + 1]
        
        # Calcular segmento lineal estándar
        f1 = filtraciones_from_volumen(v1)
        f2 = filtraciones_from_volumen(v2)
        slope = (f2 - f1) / (v2 - v1)
        intercept = f1 - slope * v1
        
        # Calcular error máximo con muestreo muy fino
        max_error = 0.0
        max_error_at_v = v1
        error_samples = []
        
        for j in range(201):  # Muestreo ultra-fino
            v_test = v1 + (v2 - v1) * j / 200
            f_real = filtraciones_from_volumen(v_test)
            f_pwl = slope * v_test + intercept
            error = abs(f_real - f_pwl)
            error_samples.append(error)
            
            if error > max_error:
                max_error = error
                max_error_at_v = v_test
        
        total_error += max_error
        
        # Estadísticas adicionales del error
        error_mean = np.mean(error_samples)
        error_std = np.std(error_samples)
        error_rmse = np.sqrt(np.mean([e**2 for e in error_samples]))
        
        # Determinar tipo de colchón con más granularidad
        if v1 < 600:
            colchon_type = "Inferior_Bajo"
        elif v1 < 1200:
            colchon_type = "Inferior_Alto"
        elif v1 < 1370:
            colchon_type = "Transición"
        elif v1 < 1900:
            colchon_type = "Intermedio"
        elif v1 < 3500:
            colchon_type = "Superior_Medio"
        else:
            colchon_type = "Superior_Alto"
        
        segments[i + 1] = {
            "v_min": v1,
            "v_max": v2,
            "slope": slope,
            "intercept": intercept,
            "max_error": max_error,
            "max_error_at_v": max_error_at_v,
            "error_mean": error_mean,
            "error_std": error_std,
            "error_rmse": error_rmse,
            "range_size": v2 - v1,
            "avg_filtration": (f1 + f2) / 2,
            "colchon_type": colchon_type,
            # Datos para SOS2
            "breakpoint_left": v1,
            "breakpoint_right": v2,
            "f_left": f1,
            "f_right": f2
        }
    
    # Metadatos expandidos
    segments["_metadata"] = {
        "total_error": total_error,
        "method": "adaptive_curvature_analysis",
        "breakpoints": breaks,
        "n_segments": n_segments,
        "sos2_points": sos2_points,
        "sos2_values": sos2_values,
        "supports_sos2": True,
        "error_target": 0.15,
        "total_breakpoints": len(breaks)
    }

    return segments


def get_sos2_formulation(segments: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    """
    Genera la formulación SOS2 para aproximación PWL ultra-precisa.
    
    Args:
        segments: Diccionario de segmentos PWL
        
    Returns:
        Dict con datos para implementar SOS2 en Gurobi
    """
    metadata = segments.get("_metadata", {})
    
    if not metadata.get("supports_sos2", False):
        raise ValueError("Los segmentos no soportan formulación SOS2")
    
    sos2_points = metadata["sos2_points"]
    sos2_values = metadata["sos2_values"]
    
    return {
        "breakpoints": sos2_points,
        "function_values": sos2_values,
        "n_points": len(sos2_points),
        "formulation_type": "SOS2_with_alpha_variables",
        "usage_example": {
            "variables": "alpha_k for k in range(n_points)",
            "constraints": [
                "sum(alpha_k) == 1",
                "V == sum(alpha_k * breakpoints[k])",
                "F == sum(alpha_k * function_values[k])",
                "SOS2(alpha_0, alpha_1, ..., alpha_n)"
            ]
        }
    }


def eval_pwl_final(vol: float, segments: Dict[int, Dict[str, Any]]) -> float:
    """Evalúa la PWL final ultra-precisa en un volumen dado."""
    # Filtrar metadatos
    numeric_segs = {k: v for k, v in segments.items() if isinstance(k, int)}
    
    # Buscar segmento que contiene el volumen
    for seg in numeric_segs.values():
        if seg["v_min"] - 1e-9 <= vol <= seg["v_max"] + 1e-9:
            return seg["slope"] * vol + seg["intercept"]
    
    # Extrapolación si está fuera del rango
    if vol < 0:
        seg = numeric_segs[1]  # Primer segmento
    else:
        seg = numeric_segs[max(numeric_segs.keys())]  # Último segmento
    
    return seg["slope"] * vol + seg["intercept"]


# Generar los segmentos PWL FINALES al importar el módulo
PWL_SEGMENTS = build_pwl_final_segments(V_max=5582.0)


def get_pwl_segments() -> Dict[int, Dict[str, Any]]:
    """
    Obtiene los segmentos PWL precalculados.

    Returns:
        Diccionario con los segmentos PWL
    """
    return PWL_SEGMENTS





def test_funciones():
    """
    Función de prueba para verificar el funcionamiento de las conversiones.
    """
    print("🧪 Pruebas de funciones de filtración y cota:")

    volumenes_prueba = [0, 500, 1000, 1500, 2000, 2500, 3000, 3628]

    for vol in volumenes_prueba:
        cota = cota_from_volumen(vol)
        filtr = filtraciones_from_volumen(vol)
        print(
            (
                f"V={vol:4.0f} Hm³ -> Cota={cota:6.1f} m "
                f"-> Filtr={filtr:6.2f} m3/s"
            )
        )

    # Filtrar solo segmentos numéricos (sin metadatos)
    numeric_segments = {k: v for k, v in PWL_SEGMENTS.items() if isinstance(k, int)}
    print(f"\n📊 Segmentos PWL generados: {len(numeric_segments)}")
    for k, seg in numeric_segments.items():
        print(f"  Segmento {k}: V=[{seg['v_min']:4.0f}, {seg['v_max']:4.0f}] "
              f"-> slope={seg['slope']:.6f}, intercept={seg['intercept']:.2f}")


def plot_filtration_comparison(V_max: float = 3628.0, 
                              segments: Dict[int, Dict[str, Any]] = None,
                              save_path: str = None) -> None:
    """
    Genera gráfico comparativo de función original vs PWL linearizada.
    
    Args:
        V_max: Volumen máximo para el gráfico
        segments: Segmentos PWL (usa PWL_SEGMENTS si None)
        save_path: Ruta para guardar el gráfico (opcional)
    """
    if segments is None:
        segments = PWL_SEGMENTS
    
    # Rango de volúmenes para evaluar
    volumes = np.linspace(0, V_max, 2000)
    
    # Función original
    filtr_original = [filtraciones_from_volumen(v) for v in volumes]
    
    # Función PWL
    filtr_pwl = [eval_pwl_final(v, segments) for v in volumes]
    
    # Crear gráfico
    plt.figure(figsize=(12, 8))
    
    # Plot principal
    plt.subplot(2, 1, 1)
    plt.plot(volumes, filtr_original, 'b-', linewidth=2, 
             label='Función Original f(V)', alpha=0.8)
    plt.plot(volumes, filtr_pwl, 'r--', linewidth=2, 
             label='PWL Linearizada', alpha=0.8)
    
    # Marcar breakpoints
    numeric_segs = {k: v for k, v in segments.items() if isinstance(k, int)}
    breakpoints = []
    for seg in numeric_segs.values():
        if seg["v_min"] not in breakpoints:
            breakpoints.append(seg["v_min"])
        if seg["v_max"] not in breakpoints:
            breakpoints.append(seg["v_max"])
    
    for bp in sorted(set(breakpoints)):
        if bp <= V_max:
            f_val = filtraciones_from_volumen(bp)
            plt.axvline(x=bp, color='gray', linestyle=':', alpha=0.6)
            plt.plot(bp, f_val, 'go', markersize=6, alpha=0.8)
    
    plt.xlabel('Volumen (Hm³)')
    plt.ylabel('Filtraciones (m³/s)')
    plt.title('Comparación: Función Original vs PWL Linearizada')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xlim(0, V_max)
    
    # Plot de error
    plt.subplot(2, 1, 2)
    errors = [abs(fo - fp) for fo, fp in zip(filtr_original, filtr_pwl)]
    plt.plot(volumes, errors, 'r-', linewidth=1.5, label='Error Absoluto')
    plt.xlabel('Volumen (Hm³)')
    plt.ylabel('Error (m³/s)')
    plt.title('Error de Aproximación PWL')
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.xlim(0, V_max)
    
    # Estadísticas del error
    max_error = max(errors)
    mean_error = np.mean(errors)
    plt.text(0.02, 0.95, f'Error máximo: {max_error:.4f} m³/s\n'
                         f'Error medio: {mean_error:.4f} m³/s', 
             transform=plt.gca().transAxes, 
             verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    plt.tight_layout()
    
    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        print(f"📊 Gráfico guardado en: {save_path}")
    
    plt.show()


def compare_pwl_precision(volume_points: List[float] = None) -> None:
    """
    Compara precisión en puntos específicos de volumen.
    
    Args:
        volume_points: Puntos específicos a evaluar (usa defaults si None)
    """
    if volume_points is None:
        volume_points = [0, 500, 1000, 1200, 1600, 2000, 2400, 3000, 3628]
    
    print("\n🔍 COMPARACIÓN DE PRECISIÓN PWL")
    print("=" * 70)
    print(f"{'Vol (Hm³)':>10} {'Original':>12} {'PWL':>12} {'Error':>12} {'Error %':>10}")
    print("-" * 70)
    
    total_error = 0.0
    max_error = 0.0
    max_error_vol = 0.0
    
    for vol in volume_points:
        if vol <= 3628:  # Dentro del rango válido
            f_orig = filtraciones_from_volumen(vol)
            f_pwl = eval_pwl_final(vol, PWL_SEGMENTS)
            error = abs(f_orig - f_pwl)
            error_pct = (error / f_orig) * 100 if f_orig > 0 else 0
            
            total_error += error
            if error > max_error:
                max_error = error
                max_error_vol = vol
            
            print(f"{vol:10.0f} {f_orig:12.4f} {f_pwl:12.4f} "
                  f"{error:12.4f} {error_pct:9.2f}%")
    
    print("-" * 70)
    print(f"Error promedio: {total_error/len(volume_points):.4f} m³/s")
    print(f"Error máximo: {max_error:.4f} m³/s en V={max_error_vol:.0f} Hm³")
    print(f"Precisión general: {((1 - total_error/len(volume_points)/30)*100):.2f}%")


def generate_pwl_summary():
    """
    Genera resumen completo de la linearización PWL de filtraciones.
    """
    print("🎯 LINEARIZACIÓN PWL DE FILTRACIONES - RESUMEN TÉCNICO")
    print("=" * 65)
    
    V_max = 5582.0
    segments = build_pwl_final_segments(V_max)
    metadata = segments.get("_metadata", {})
    
    print("📊 ESPECIFICACIONES TÉCNICAS:")
    print(f"   • Método: {metadata.get('method', 'N/A')}")
    print(f"   • Error total: {metadata.get('total_error', 0):.6f} m³/s")
    print(f"   • Puntos de quiebre: {metadata.get('breakpoints', [])}")
    print(f"   • Función original: f(V) = polinomio_4°(cota(V))")
    
    print("\n🔧 SEGMENTOS PWL OPTIMIZADOS:")
    numeric_segs = {k: v for k, v in segments.items() if isinstance(k, int)}
    
    for k, seg in numeric_segs.items():
        v_min, v_max = seg["v_min"], seg["v_max"]
        slope, intercept = seg["slope"], seg["intercept"]
        colchon = seg["colchon_type"]
        error = seg["max_error"]
        
        print(f"   S{k}: [{v_min:4.0f}-{v_max:4.0f}] Hm³ | {colchon:>12}")
        print(f"       └─ f(V) = {slope:.6f}·V + {intercept:.3f}")
        print(f"       └─ Error máximo: {error:.5f} m³/s")
    
    # Calcular estadísticas básicas de error
    total_samples = 0
    total_absolute_error = 0.0
    max_error_global = 0.0
    
    for seg in numeric_segs.values():
        v_min, v_max = seg["v_min"], seg["v_max"]
        slope, intercept = seg["slope"], seg["intercept"]
        
        for j in range(101):
            v = v_min + (v_max - v_min) * j / 100
            f_real = filtraciones_from_volumen(v)
            f_pwl = slope * v + intercept
            error = abs(f_real - f_pwl)
            
            total_absolute_error += error
            total_samples += 1
            max_error_global = max(max_error_global, error)
    
    mae = total_absolute_error / total_samples
    
    print(f"\n🎯 ANÁLISIS DE ERROR:")
    print(f"   • Error absoluto medio (MAE): {mae:.4f} m³/s")
    print(f"   • Error máximo global: {max_error_global:.4f} m³/s")
    
    print(f"\n💻 USO EN MODELO DE OPTIMIZACIÓN:")
    print(f"   • Importar: from filt_cota import get_pwl_segments")
    print(f"   • Obtener segmentos: segments = get_pwl_segments()")
    print(f"   • Implementar restricciones PWL en Gurobi (ver model.py)")
    
    print(f"\n✅ LINEARIZACIÓN LISTA - Función no-lineal aproximada con precisión")


if __name__ == "__main__":
    print("🧪 TESTING COMPLETO: LINEARIZACIÓN PWL DE FILTRACIONES")
    print("=" * 60)
    
    # 1. Pruebas básicas de conversión
    print("\n1️⃣ PRUEBAS DE CONVERSIÓN VOLUMEN→COTA→FILTRACIONES:")
    test_funciones()
    
    # 2. Comparación de precisión
    print("\n2️⃣ ANÁLISIS DE PRECISIÓN PWL:")
    compare_pwl_precision()
    
    # 3. Resumen técnico completo
    print("\n3️⃣ RESUMEN TÉCNICO:")
    print("=" * 60)
    generate_pwl_summary()
    
    # 4. Generar gráfico comparativo
    print("\n4️⃣ GENERANDO GRÁFICO COMPARATIVO...")
    try:
        plot_filtration_comparison(V_max=5582.0,
                                 save_path="resultados/filtration_comparison.png")
        print("✅ Gráfico generado exitosamente")
    except Exception as e:
        print(f"⚠️  Error generando gráfico: {e}")
        print("   (Asegúrate de tener matplotlib instalado)")
    
    print("\n🚀 TESTING COMPLETO - Linearización PWL lista para uso en modelo")
