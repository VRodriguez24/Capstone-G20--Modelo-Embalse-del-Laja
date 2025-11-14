"""
Módulo para cálculo de filtraciones y linearización PWL para el Embalse.

OBJETIVO: Linearizar la función no-lineal de filtraciones
f(V) = polinomio(cota(V))
usando segmentación PWL optimizada para minimizar error de aproximación.

Funciones principales:
- cota_from_volumen(): Convierte volumen a cota
- filtraciones_from_volumen(): Calcula filtraciones desde volumen
- build_pwl_final_segments(): Genera segmentos PWL optimizados
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

    Args:
        volumen: Volumen del embalse en Hm³
    Returns:
        Filtraciones en m³/s
    """
    cota = cota_from_volumen(volumen)
    return filtraciones_from_cota(cota)


def _calculate_segment_error(v_start: float, v_end: float) -> float:
    """Calcula error máximo de aproximación lineal en un segmento."""
    f1 = filtraciones_from_volumen(v_start)
    f2 = filtraciones_from_volumen(v_end)
    slope = (f2 - f1) / (v_end - v_start)
    intercept = f1 - slope * v_start

    max_error = 0.0
    test_points = np.linspace(v_start, v_end, 50)
    for v in test_points:
        f_real = filtraciones_from_volumen(v)
        f_pwl = slope * v + intercept
        error = abs(f_real - f_pwl)
        max_error = max(max_error, error)

    return max_error


def _subdivide_segment(v_start: float, v_end: float,
                       target_error: float) -> List[float]:
    """
    Subdivide un segmento si el error excede la tolerancia.

    Proceso de selección de segmentos:
    1. Evalúa error de aproximación lineal
    2. Si error > target_error → busca mejor punto de división
    3. Subdivide recursivamente hasta cumplir tolerancia
    """
    current_error = _calculate_segment_error(v_start, v_end)

    if current_error <= target_error or (v_end - v_start) < 100:
        return [v_start, v_end]

    # Buscar mejor punto de división
    best_split = None
    min_max_error = float('inf')
    n_candidates = min(10, int((v_end - v_start) / 100))

    for i in range(1, n_candidates):
        split_point = v_start + (v_end - v_start) * i / n_candidates
        error1 = _calculate_segment_error(v_start, split_point)
        error2 = _calculate_segment_error(split_point, v_end)
        max_error_with_split = max(error1, error2)

        if max_error_with_split < min_max_error:
            min_max_error = max_error_with_split
            best_split = split_point

    if best_split is None:
        return [v_start, v_end]

    # Subdivisión recursiva
    left_breaks = _subdivide_segment(v_start, best_split, target_error)
    right_breaks = _subdivide_segment(best_split, v_end, target_error)

    return left_breaks + right_breaks[1:]  # Evitar duplicar punto medio


def _generate_breakpoints(V_max: float, target_error: float) -> List[float]:
    """
    Genera breakpoints optimizados usando análisis de curvatura.

    Estrategia de selección:
    - Puntos base en límites de colchones operativos
    - Análisis adaptativo de curvatura para subdivisión
    - Minimización de error de aproximación lineal
    """
    # Puntos estratégicos base (límites de colchones)
    strategic_points = [0.0, 1200.0, 1370.0, 1900.0, V_max]

    final_breaks = [0.0]
    for i in range(len(strategic_points) - 1):
        start, end = strategic_points[i], strategic_points[i + 1]
        segment_breaks = _subdivide_segment(start, end, target_error)

        # Agregar puntos intermedios
        for bp in segment_breaks[1:]:
            if bp not in final_breaks:
                final_breaks.append(bp)

    return sorted(final_breaks)


def build_pwl_final_segments(
    V_max: float = 5582.0
) -> Dict[int, Dict[str, Any]]:
    """
    Genera segmentos PWL optimizados para linearizar función de filtraciones.

    Args:
        V_max: Volumen máximo del embalse (Hm³)

    Returns:
        Dict con segmentos {k: {v_min, v_max, slope, intercept, ...}}

    Proceso:
    1. Genera breakpoints usando análisis adaptativo de curvatura
    2. Calcula parámetros lineales (pendiente, intercepto) por segmento
    3. Evalúa error de aproximación para validación
    """
    # Generar breakpoints optimizados
    breaks = _generate_breakpoints(V_max, target_error=0.05)
    n_segments = len(breaks) - 1

    segments: Dict[int, Dict[str, Any]] = {}
    total_error = 0.0

    for i in range(n_segments):
        v1, v2 = breaks[i], breaks[i + 1]

        # Calcular parámetros del segmento lineal
        f1 = filtraciones_from_volumen(v1)
        f2 = filtraciones_from_volumen(v2)
        slope = (f2 - f1) / (v2 - v1)
        intercept = f1 - slope * v1

        # Calcular error máximo del segmento
        max_error = _calculate_segment_error(v1, v2)
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
        "method": "adaptive_curvature_analysis",
        "breakpoints": breaks,
        "n_segments": n_segments
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


# Generar segmentos PWL al importar el módulo
PWL_SEGMENTS = build_pwl_final_segments(V_max=5582.0)


def get_pwl_segments() -> Dict[int, Dict[str, Any]]:
    """
    Obtiene los segmentos PWL precalculados.

    Returns:
        Diccionario con los segmentos PWL optimizados
    """
    return PWL_SEGMENTS


# =============================
# INTEGRACIÓN CON MODELO GUROBI
# =============================
def add_pwl_filtration_constraints(
    model,
    Filtr_vars,
    Vprev_vars,
    time_periods: list,
    filtr_arc: tuple,
    segments: Dict[int, Dict[str, Any]],
    bigM: float,
    v_max: float = 5582.0,
):
    """
    Agrega restricciones PWL para filtraciones con variables binarias.

    Implementa la linearización de la función no-lineal de filtraciones
    usando segmentación PWL con variables binarias δ_{k,t}.

    Esta función pertenece a filt_cota.py porque:
    - Encapsula la lógica específica de filtraciones PWL
    - Trabaja directamente con los segmentos generados aquí
    - Permite reutilización en múltiples modelos (model.py, caso_base.py)
    - Mantiene cohesión: datos (segmentos) + operaciones (restricciones)

    Args:
        model: Modelo de Gurobi
        Filtr_vars: Variables de filtración por período
        Vprev_vars: Variables de volumen previo por período
        time_periods: Lista de períodos de tiempo
        filtr_arc: Tupla (origen, destino) del arco de filtración
        segments: Diccionario de segmentos PWL
        bigM: Valor Big-M para linearización
        v_max: Volumen máximo del embalse (Hm³)

    Returns:
        dict: Variables auxiliares creadas (deltas y segmentos usados)

    Example:
        >>> from filt_cota import:
            build_pwl_final_segments, add_pwl_filtration_constraints
        >>> segments = build_pwl_final_segments(V_max=5582.0)
        >>> pwl_vars = add_pwl_filtration_constraints(
        ...     model=m,
        ...     Filtr_vars=Filtr,
        ...     Vprev_vars=Vprev_vars,
        ...     time_periods=T,
        ...     filtr_arc=("Embalse", "control_FiltracionesLaja"),
        ...     segments=segments,
        ...     bigM=6000
        ... )
    """
    # Importar GRB solo cuando se necesite (evita dependencia circular)
    try:
        from gurobipy import GRB
    except ImportError:
        raise ImportError(
            "Gurobi no está instalado. "
            "Esta función requiere gurobipy."
        )

    f_i, f_j = filtr_arc

    # Filtrar metadatos y obtener segmentos numéricos
    numeric_segments = {
        k: v
        for k, v in segments.items()
        if isinstance(k, int)
    }
    seg_ids = list(numeric_segments.keys())

    # Igualar arco de filtración con variable
    for t in time_periods:
        model.addConstr(
            model._y[f_i, f_j, t] == Filtr_vars[t],
            name=f"R5a_filtr_arc_{t}"
        )

    # Variables binarias δ_{k,t} para selección de segmento
    delta = model.addVars(
        seg_ids, time_periods,
        vtype=GRB.BINARY,
        name="delta_pwl_seg"
    )

    # CRITICAL: Update model to commit variables
    model.update()

    for t in time_periods:
        # Un único segmento activo por período
        model.addConstr(
            sum(delta[k, t] for k in seg_ids) == 1,
            name=f"R5b_one_seg_{t}"
        )

        Vprev = Vprev_vars[t]

        # Restricciones por segmento PWL
        for k in seg_ids:
            seg = numeric_segments[k]
            vmin, vmax = seg["v_min"], seg["v_max"]
            slope, b = seg["slope"], seg["intercept"]

            # Volumen debe estar en el rango del segmento cuando δ_k=1
            # Si δ_k=1: vmin ≤ Vprev ≤ vmax
            # Si δ_k=0: restricciones desactivadas con Big-M
            model.addConstr(
                Vprev >= vmin - bigM * (1 - delta[k, t]),
                name=f"R5c_vol_lb_{k}_{t}"
            )
            model.addConstr(
                Vprev <= vmax + bigM * (1 - delta[k, t]),
                name=f"R5d_vol_ub_{k}_{t}"
            )

            # Filtración = función lineal del segmento cuando δ_k=1
            model.addConstr(
                Filtr_vars[t] >= (
                    slope * Vprev + b - bigM * (1 - delta[k, t])
                ),
                name=f"R5e_filtr_lb_{k}_{t}"
            )
            model.addConstr(
                Filtr_vars[t] <= (
                    slope * Vprev + b + bigM * (1 - delta[k, t])
                ),
                name=f"R5f_filtr_ub_{k}_{t}"
            )

    return {"delta_pwl": delta, "segments_used": numeric_segments}


# =============================
# FUNCIONES DE TESTING (OPCIONALES)
# =============================
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
    print(f"{'':4s}{'Rango Volumen':^23s} │ {'Colchón':^13s} │ {'Error':^15s}")
    print(f"    {'─'*24}┼{'─'*15}┼{'─'*17}")

    for k, seg in numeric_segments.items():
        v_min = seg['v_min']
        v_max = seg['v_max']
        colchon = seg['colchon_type']
        error = seg['max_error']

        print(f"  S{k:02d}: V=[{v_min:5.0f}, {v_max:5.0f}] Hm³ │ "
              f"{colchon:13s} │ {error:6.4f} m³/s")


def plot_filtration_comparison(
        V_max: float = 5582.0,
        save_path: str = "resultados/filtration_comparison_005.png"
):
    """
    Genera gráfico comparativo de función original vs PWL linearizada.

    Args:
        V_max: Volumen máximo para el gráfico (Hm³)
        save_path: Ruta para guardar el gráfico
    """
    # Rango de volúmenes para evaluar
    volumes = np.linspace(0, V_max, 2000)

    # Función original
    filtr_original = [filtraciones_from_volumen(v) for v in volumes]

    # Función PWL
    filtr_pwl = [eval_pwl_final(v, PWL_SEGMENTS) for v in volumes]

    # Crear gráfico
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

    # Plot principal
    ax1.plot(volumes, filtr_original, 'b-', linewidth=2,
             label='Función Original f(V)', alpha=0.8)
    ax1.plot(volumes, filtr_pwl, 'r--', linewidth=2,
             label='PWL Linearizada', alpha=0.8)

    # Marcar breakpoints
    numeric_segs = {
        k: v
        for k, v in PWL_SEGMENTS.items()
        if isinstance(k, int)
    }
    breakpoints = []
    for seg in numeric_segs.values():
        if seg["v_min"] not in breakpoints:
            breakpoints.append(seg["v_min"])
        if seg["v_max"] not in breakpoints:
            breakpoints.append(seg["v_max"])

    for bp in sorted(set(breakpoints)):
        if bp <= V_max:
            f_val = filtraciones_from_volumen(bp)
            ax1.axvline(x=bp, color='gray', linestyle=':', alpha=0.6)
            ax1.plot(bp, f_val, 'go', markersize=6, alpha=0.8)

    ax1.set_xlabel('Volumen (Hm³)')
    ax1.set_ylabel('Filtraciones (m³/s)')
    ax1.set_title('Comparación: Función Original vs PWL Linearizada')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    ax1.set_xlim(0, V_max)

    # Plot de error
    errors = [abs(fo - fp) for fo, fp in zip(filtr_original, filtr_pwl)]
    ax2.plot(volumes, errors, 'r-', linewidth=1.5, label='Error Absoluto')
    ax2.set_xlabel('Volumen (Hm³)')
    ax2.set_ylabel('Error (m³/s)')
    ax2.set_title('Error de Aproximación PWL')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    ax2.set_xlim(0, V_max)

    # Estadísticas del error
    max_error = max(errors)
    mean_error = np.mean(errors)
    ax2.text(0.02, 0.95, f'Error máximo: {max_error:.4f} m³/s\n'
                         f'Error medio: {mean_error:.4f} m³/s',
             transform=ax2.transAxes,
             verticalalignment='top',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    plt.tight_layout()

    # Guardar gráfico
    plt.savefig(save_path, dpi=300, bbox_inches='tight')
    print(f"📊 Gráfico guardado en: {save_path}")
    plt.show()

    return max_error, mean_error


def generate_summary():
    """Genera resumen técnico de la linearización PWL."""
    print("🎯 LINEARIZACIÓN PWL - RESUMEN TÉCNICO")
    print("=" * 50)

    metadata = PWL_SEGMENTS.get("_metadata", {})

    print("📊 ESPECIFICACIONES:")
    print(f"   • Método: {metadata.get('method', 'N/A')}")
    print(f"   • Número de segmentos: {metadata.get('n_segments', 0)}")
    print(f"   • Error total: {metadata.get('total_error', 0):.4f} m³/s")
    print(f"   • Breakpoints: {len(metadata.get('breakpoints', []))} puntos")

    print("🔧 CRITERIOS DE SELECCIÓN DE SEGMENTOS:")
    print("   1. Puntos base en límites de colchones "
          "(0, 1200, 1370, 1900, 5582)")
    print("   2. Análisis adaptativo de curvatura")
    print("   3. Subdivisión si error > 0.05 m³/s")
    print("   4. Optimización recursiva hasta tolerancia")

    print("\n💻 USO EN MODELO:")
    print("   from filt_cota import build_pwl_final_segments")
    print("   segments = build_pwl_final_segments()")


if __name__ == "__main__":
    print("=" * 50)
    print("🧪 TESTING: LINEARIZACIÓN PWL DE FILTRACIONES")
    print("=" * 50 + "\n")

    # Pruebas básicas
    test_funciones()

    print("\n" + "=" * 50)
    generate_summary()

    # Generar gráfico comparativo
    print("\n📊 GENERANDO GRÁFICO COMPARATIVO...")
    try:
        max_err, mean_err = plot_filtration_comparison()
        print(f"✅ Gráfico generado con error máx: {max_err:.4f} m³/s")
    except Exception as e:
        print(f"⚠️ Error generando gráfico: {e}")
        print("   (Asegúrate de tener matplotlib instalado)")

    print("\n✅ Archivo optimizado - Linearización PWL con mayor precisión")
