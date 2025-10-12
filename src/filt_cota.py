"""
Módulo para cálculo de filtraciones y conversión volumen-cota
para el Embalse El Toro.

Este módulo contiene:
- Tabla de conversión volumen-cota original (71 puntos)
- Función polinomial de 4to grado para filtraciones basada en cota
- Segmentos PWL (Piecewise Linear) para aproximación lineal
- Funciones de conversión y cálculo
"""
from typing import Dict, Any

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


def calculate_pwl_segments() -> Dict[int, Dict[str, Any]]:
    """
    Calcula segmentos PWL basados en rango operativo completo (0-5582 Hm3).

    Divide el rango en segmentos alineados con la configuración de colchones:
    1. Inferior: 0-1200 Hm3
    2. Transición: 1200-1370 Hm3
    3. Intermedio: 1370-1900 Hm3
    4. Superior: 1900-5582 Hm3

    Returns:
        Diccionario con segmentos PWL, cada uno conteniendo:
        - v_min, v_max: rango de volumen del segmento
        - slope: pendiente de la línea en el segmento
        - intercept: intercepto de la línea en el segmento
    """
    segments = {}

    # Puntos de ruptura alineados con configuración definitiva de colchones
    breakpoints = [0, 1200, 1370, 1900, 5582]

    for i in range(len(breakpoints) - 1):
        v_min, v_max = breakpoints[i], breakpoints[i + 1]

        # Calcular filtraciones en los extremos del segmento
        filtr_min = filtraciones_from_volumen(v_min)
        filtr_max = filtraciones_from_volumen(v_max)

        # Calcular pendiente e intercepto
        if v_max > v_min:
            slope = (filtr_max - filtr_min) / (v_max - v_min)
            intercept = filtr_min - slope * v_min
        else:
            slope = 0.0
            intercept = filtr_min

        segments[i + 1] = {
            "v_min": v_min,
            "v_max": v_max,
            "slope": slope,
            "intercept": intercept
        }

    return segments


# Generar los segmentos PWL al importar el módulo
PWL_SEGMENTS = calculate_pwl_segments()


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

    print(f"\n📊 Segmentos PWL generados: {len(PWL_SEGMENTS)}")
    for k, seg in PWL_SEGMENTS.items():
        print(f"  Segmento {k}: V=[{seg['v_min']:4.0f}, {seg['v_max']:4.0f}] "
              f"-> slope={seg['slope']:.6f}, intercept={seg['intercept']:.2f}")


if __name__ == "__main__":
    test_funciones()
