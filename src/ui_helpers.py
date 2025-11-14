"""
HELPERS DE INTERFAZ DE USUARIO (UI HELPERS)

Funciones reutilizables para interfaz de consola, medición de rendimiento,
entrada de usuario y visualización consistente entre todos los módulos.

Evita duplicación de código entre:
- model.py (modelo determinista)
- montecarlo.py (simulación Monte Carlo)
- analisis_sensibilidad_v0.py (análisis de sensibilidad)
- caso_base.py (caso base)

Uso:
    from ui_helpers import (
        get_input, format_time, print_performance_stats,
        print_header, print_separator, configure_console
    )
"""

from __future__ import annotations

import time
import psutil
from typing import Optional, Any


# ============================================================================
# ENTRADA DE USUARIO
# ============================================================================

def get_input(
    prompt: str,
    default: Optional[Any] = None,
    input_type: type = str
) -> Any:
    """
    Solicita entrada del usuario con valor por defecto y validación.

    Función unificada para capturar entrada de usuario con manejo de
    errores y conversión de tipos. Usada en todas las interfaces
    interactivas.

    Args:
        prompt: Mensaje a mostrar al usuario
        default: Valor por defecto si el usuario presiona Enter
        input_type: Tipo esperado (str, int, float, bool)

    Returns:
        Valor ingresado convertido al tipo especificado

    Raises:
        KeyboardInterrupt: Si el usuario cancela con Ctrl+C

    Examples:
        >>> year = get_input(
        ...     "Año inicial", default=1960, input_type=int
        ... )
        >>> V0 = get_input(
        ...     "Volumen inicial V0 (Hm³)",
        ...     default=1400.0,
        ...     input_type=float
        ... )
        >>> confirm = get_input(
        ...     "¿Continuar? (s/n)", default="s", input_type=str
        ... )
    """
    while True:
        try:
            if default is not None:
                user_input = input(f"{prompt} [{default}]: ").strip()
                if not user_input:
                    return input_type(default)
            else:
                user_input = input(f"{prompt}: ").strip()
                if not user_input:
                    print("⚠️ Este campo es obligatorio. Intenta nuevamente.")
                    continue

            return input_type(user_input)
        except ValueError:
            print(
                f"❌ Entrada inválida. Se esperaba {input_type.__name__}. "
                "Intenta nuevamente."
            )
        except KeyboardInterrupt:
            print("\n\n👋 Operación cancelada por el usuario.")
            raise


# ============================================================================
# MEDICIÓN Y FORMATO DE RENDIMIENTO
# ============================================================================

def get_performance_stats(
    start_time: float,
    process: psutil.Process
) -> dict:
    """
    Calcula estadísticas de rendimiento del sistema.

    Recopila métricas de tiempo de ejecución, memoria RAM utilizada,
    y estado general del sistema para análisis de eficiencia.

    Args:
        start_time: Tiempo de inicio de la ejecución (time.time())
        process: Proceso actual de psutil (psutil.Process())

    Returns:
        dict: Estadísticas de rendimiento con claves:
            - execution_time_seconds: Tiempo en segundos (float)
            - execution_time_formatted: Tiempo formateado (str)
            - memory_rss_mb: Memoria RSS en MB (float)
            - memory_vms_mb: Memoria VMS en MB (float)
            - memory_percent: % de memoria del proceso (float)
            - system_memory_total_gb: Memoria total en GB (float)
            - system_memory_available_gb: Memoria disponible GB
            - system_memory_used_percent: % de memoria usada

    Examples:
        >>> import time, psutil
        >>> start = time.time()
        >>> process = psutil.Process()
        >>> # ... ejecutar código ...
        >>> stats = get_performance_stats(start, process)
        >>> print(stats['execution_time_formatted'])
        '2h 15m 30s'
    """
    execution_time = time.time() - start_time

    # Obtener información de memoria del proceso
    memory_info = process.memory_info()
    memory_percent = process.memory_percent()

    # Información del sistema
    system_memory = psutil.virtual_memory()

    return {
        "execution_time_seconds": execution_time,
        "execution_time_formatted": format_time(execution_time),
        "memory_rss_mb": memory_info.rss / (1024 * 1024),
        "memory_vms_mb": memory_info.vms / (1024 * 1024),
        "memory_percent": memory_percent,
        "system_memory_total_gb": system_memory.total / (1024 * 1024 * 1024),
        "system_memory_available_gb": (
            system_memory.available / (1024 * 1024 * 1024)
        ),
        "system_memory_used_percent": system_memory.percent
    }


def format_time(seconds: float) -> str:
    """
    Formatea tiempo en segundos a un formato legible.

    Convierte tiempos de ejecución a formato humano:
    - Menos de 60s: "45.2s"
    - Menos de 1h: "15m 30.5s"
    - Más de 1h: "2h 15m 30s"

    Args:
        seconds: Tiempo en segundos (float)

    Returns:
        str: Tiempo formateado para lectura humana

    Examples:
        >>> format_time(45.234)
        '45.2s'
        >>> format_time(930.5)
        '15m 30.5s'
        >>> format_time(8130.2)
        '2h 15m 30s'
    """
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {minutes}m {secs:.1f}s"


def print_performance_stats(stats: dict, context: str = ""):
    """
    Imprime estadísticas de rendimiento en formato unificado.

    Muestra resumen visual de rendimiento con métricas clave:
    tiempo de ejecución, memoria utilizada, y estado del sistema.

    Args:
        stats: Diccionario con estadísticas de rendimiento
               (obtenido de get_performance_stats)
        context: Contexto adicional (ej: "Monte Carlo")

    Examples:
        >>> stats = get_performance_stats(start_time, process)
        >>> print_performance_stats(
        ...     stats, "(Análisis Sensibilidad)"
        ... )
        ==================================================
        ⚡ RENDIMIENTO (Análisis Sensibilidad)
        ==================================================
        🕒 Tiempo de ejecución: 2h 15m 30s
        💾 RAM utilizada: 234.5 MB
        💻 Memoria sistema utilizada: 65.3%
        ==================================================
    """
    print(f"\n{'=' * 50}")
    print(f"⚡ RENDIMIENTO {context}")
    print(f"{'=' * 50}")
    print(f"🕒 Tiempo de ejecución: {stats['execution_time_formatted']}")
    print(f"💾 RAM utilizada: {stats['memory_rss_mb']:.1f} MB")
    print(
        f"💻 Memoria sistema utilizada: "
        f"{stats['system_memory_used_percent']:.1f}%"
    )
    print(f"{'=' * 50}")


# ============================================================================
# ELEMENTOS VISUALES DE CONSOLA
# ============================================================================

def print_header(
    title: str,
    subtitle: Optional[str] = None,
    width: int = 70,
    emoji: str = "📊"
):
    """
    Imprime encabezado visual consistente.

    Crea encabezados estandarizados para diferentes secciones
    del programa con separadores y formato unificado.

    Args:
        title: Título principal del encabezado
        subtitle: Subtítulo opcional
        width: Ancho del separador (default: 70)
        emoji: Emoji decorativo (default: 📊)

    Examples:
        >>> print_header(
        ...     "MODELO DETERMINISTA",
        ...     "Optimización multi-año"
        ... )
        ==================================================
        📊 MODELO DETERMINISTA
        ==================================================
        Optimización multi-año
    """
    print("=" * width)
    print(f"{emoji} {title}")
    print("=" * width)
    if subtitle:
        print(subtitle)


def print_separator(width: int = 70, char: str = "="):
    """
    Imprime separador visual.

    Args:
        width: Ancho del separador (default: 70)
        char: Carácter del separador (default: "=")

    Examples:
        >>> print_separator()
        ==================================================
        >>> print_separator(50, "-")
        --------------------------------------------------
    """
    print(char * width)


def print_section(title: str, width: int = 70):
    """
    Imprime título de sección con separadores.

    Args:
        title: Título de la sección
        width: Ancho del separador (default: 70)

    Examples:
        >>> print_section("RESULTADOS DEL ANÁLISIS")

        ==================================================
        RESULTADOS DEL ANÁLISIS
        ==================================================
    """
    print("\n" + "=" * width)
    print(title)
    print("=" * width)


def print_progress_inline(
    message: str,
    end: str = '',
    flush: bool = True
):
    """
    Imprime mensaje de progreso en la misma línea (con \\r).

    Útil para loaders y barras de progreso que se actualizan
    sin generar nuevas líneas.

    Args:
        message: Mensaje a mostrar
        end: Carácter final (default: '' para mantener cursor)
        flush: Forzar escritura inmediata (default: True)

    Examples:
        >>> for i in range(100):
        ...     print_progress_inline(f"Progreso: {i}%")
        ...     time.sleep(0.1)
        >>> print()  # Nueva línea al finalizar
    """
    print(f"\r{message}", end=end, flush=flush)


def print_info(message: str, emoji: str = "ℹ️"):
    """
    Imprime mensaje informativo con formato consistente.

    Args:
        message: Mensaje informativo
        emoji: Emoji decorativo (default: ℹ️)

    Examples:
        >>> print_info("Cargando datos históricos...")
        ℹ️ Cargando datos históricos...
    """
    print(f"{emoji} {message}")


def print_success(message: str, emoji: str = "✅"):
    """
    Imprime mensaje de éxito con formato consistente.

    Args:
        message: Mensaje de éxito
        emoji: Emoji decorativo (default: ✅)

    Examples:
        >>> print_success(
        ...     "Optimización completada exitosamente"
        ... )
        ✅ Optimización completada exitosamente
    """
    print(f"{emoji} {message}")


def print_warning(message: str, emoji: str = "⚠️"):
    """
    Imprime mensaje de advertencia con formato consistente.

    Args:
        message: Mensaje de advertencia
        emoji: Emoji decorativo (default: ⚠️)

    Examples:
        >>> print_warning("Algunos escenarios fallaron")
        ⚠️ Algunos escenarios fallaron
    """
    print(f"{emoji} {message}")


def print_error(message: str, emoji: str = "❌"):
    """
    Imprime mensaje de error con formato consistente.

    Args:
        message: Mensaje de error
        emoji: Emoji decorativo (default: ❌)

    Examples:
        >>> print_error(
        ...     "No se pudo cargar el archivo de datos"
        ... )
        ❌ No se pudo cargar el archivo de datos
    """
    print(f"{emoji} {message}")


def configure_console():
    """
    Configura la consola para visualización de caracteres UTF-8.

    Necesario en Windows para mostrar correctamente emojis y
    caracteres especiales en PowerShell y CMD.

    Examples:
        >>> configure_console()  # Configurar al inicio del programa
    """
    try:
        import os
        os.system("chcp 65001 > nul 2>&1")
    except Exception:
        pass  # Silencioso si falla (no-Windows o error no crítico)


# ============================================================================
# VALIDADORES COMUNES
# ============================================================================

def validate_year(year: int, min_year: int, max_year: int) -> int:
    """
    Valida que el año esté en el rango disponible.

    Args:
        year: Año a validar
        min_year: Año mínimo permitido
        max_year: Año máximo permitido

    Returns:
        int: Año validado

    Raises:
        ValueError: Si el año está fuera del rango

    Examples:
        >>> validate_year(2015, 1960, 2023)
        2015
        >>> validate_year(1950, 1960, 2023)
        ValueError: Año debe estar entre 1960 y 2023
    """
    if year < min_year or year > max_year:
        raise ValueError(f"Año debe estar entre {min_year} y {max_year}")
    return year


def validate_positive(value: float, name: str = "Valor") -> float:
    """
    Valida que un valor sea positivo.

    Args:
        value: Valor a validar
        name: Nombre del parámetro (para mensaje de error)

    Returns:
        float: Valor validado

    Raises:
        ValueError: Si el valor es <= 0

    Examples:
        >>> validate_positive(1400.0, "V0")
        1400.0
        >>> validate_positive(-100, "V0")
        ValueError: V0 debe ser positivo
    """
    if value <= 0:
        raise ValueError(f"{name} debe ser positivo")
    return value


def validate_range(
    value: float,
    min_val: float,
    max_val: float,
    name: str = "Valor"
) -> float:
    """
    Valida que un valor esté dentro de un rango.

    Args:
        value: Valor a validar
        min_val: Valor mínimo permitido
        max_val: Valor máximo permitido
        name: Nombre del parámetro (para mensaje de error)

    Returns:
        float: Valor validado

    Raises:
        ValueError: Si el valor está fuera del rango

    Examples:
        >>> validate_range(2500, 0, 5582, "V0")
        2500.0
        >>> validate_range(6000, 0, 5582, "V0")
        ValueError: V0 debe estar entre 0 y 5582
    """
    if value < min_val or value > max_val:
        raise ValueError(f"{name} debe estar entre {min_val} y {max_val}")
    return value


# ============================================================================
# FORMATEO DE DATOS
# ============================================================================

def format_number(
    value: float,
    decimals: int = 0,
    thousands_sep: str = ","
) -> str:
    """
    Formatea número con separadores de miles y decimales.

    Args:
        value: Número a formatear
        decimals: Cantidad de decimales (default: 0)
        thousands_sep: Separador de miles (default: ",")

    Returns:
        str: Número formateado

    Examples:
        >>> format_number(1234567.89, decimals=2)
        '1,234,567.89'
        >>> format_number(1400, decimals=0)
        '1,400'
    """
    return f"{value:,.{decimals}f}".replace(",", thousands_sep)


def format_percentage(value: float, decimals: int = 1) -> str:
    """
    Formatea valor como porcentaje.

    Args:
        value: Valor a formatear (0-100)
        decimals: Cantidad de decimales (default: 1)

    Returns:
        str: Porcentaje formateado

    Examples:
        >>> format_percentage(95.678, decimals=1)
        '95.7%'
        >>> format_percentage(100, decimals=0)
        '100%'
    """
    return f"{value:.{decimals}f}%"


# ============================================================================
# TABLA DE RESUMEN
# ============================================================================

def print_table_row(columns: list, widths: list, alignment: str = '>'):
    """
    Imprime una fila de tabla alineada.

    Args:
        columns: Lista de valores de columnas
        widths: Lista de anchos por columna
        alignment: Alineación ('>': derecha, '<': izquierda)

    Examples:
        >>> print_table_row(["V0", "Energía", "Éxito"], [10, 15, 10])
        V0        Energía         Éxito
    """
    row = " ".join(
        f"{str(col):{alignment}{width}}"
        for col, width in zip(columns, widths)
    )
    print(row)


def print_table_separator(widths: list, char: str = "-"):
    """
    Imprime separador de tabla.

    Args:
        widths: Lista de anchos por columna
        char: Carácter del separador (default: "-")

    Examples:
        >>> print_table_separator([10, 15, 10])
        ---------------------------------
    """
    total_width = sum(widths) + len(widths) - 1  # espacios entre columnas
    print(char * total_width)
