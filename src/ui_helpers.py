"""
Funciones auxiliares para la interfaz de usuario (UI) de los modelos.

Este módulo contiene utilidades para:
- Entrada de datos del usuario con validación
- Medición de rendimiento y uso de recursos
- Formateo de estadísticas de ejecución
"""

import time
import psutil
from typing import Any, Dict, Union


def get_input(
    prompt: str,
    default: Any = None,
    input_type: type = str
) -> Any:
    """
    Solicita entrada del usuario con valor por defecto y validación de tipo.

    Args:
        prompt: Mensaje a mostrar al usuario
        default: Valor por defecto si el usuario solo presiona Enter
        input_type: Tipo de dato esperado (str, int, float, etc.)

    Returns:
        Valor ingresado por el usuario convertido al tipo especificado

    Example:
        >>> year = get_input("Año", default=2020, input_type=int)
        Año [2020]: 2021
        >>> # Retorna: 2021
    """
    # Preparar prompt con valor por defecto
    if default is not None:
        full_prompt = f"{prompt} [{default}]: "
    else:
        full_prompt = f"{prompt}: "

    while True:
        try:
            user_input = input(full_prompt).strip()

            # Si está vacío, usar valor por defecto
            if not user_input:
                if default is not None:
                    if input_type != str:
                        return input_type(default)
                    return default
                else:
                    print("❌ Este campo es obligatorio.")
                    continue

            # Convertir al tipo especificado
            return input_type(user_input)

        except ValueError:
            print(f"❌ Por favor ingresa un valor válido tipo "
                  f"{input_type.__name__}")
        except KeyboardInterrupt:
            print("\n⚠️  Operación cancelada por el usuario")
            raise
        except Exception as e:
            print(f"❌ Error: {e}")


def get_performance_stats(
    start_time: float,
    process: psutil.Process
) -> Dict[str, Union[float, str]]:
    """
    Calcula estadísticas de rendimiento de la ejecución.

    Args:
        start_time: Timestamp de inicio (time.time())
        process: Proceso de psutil para medir memoria

    Returns:
        Dict con métricas de rendimiento:
        - elapsed_time: Tiempo transcurrido (segundos)
        - elapsed_str: Tiempo formateado (ej: "1m 23s")
        - memory_mb: Memoria RAM usada por el proceso (MB)
        - memory_pct: % de memoria del sistema utilizada

    Example:
        >>> start = time.time()
        >>> process = psutil.Process()
        >>> # ... ejecutar código ...
        >>> stats = get_performance_stats(start, process)
        >>> print(stats['elapsed_str'])
        '1m 23.5s'
    """
    # Tiempo transcurrido
    elapsed_time = time.time() - start_time

    # Formatear tiempo transcurrido
    if elapsed_time < 60:
        elapsed_str = f"{elapsed_time:.1f}s"
    elif elapsed_time < 3600:
        minutes = int(elapsed_time // 60)
        seconds = elapsed_time % 60
        elapsed_str = f"{minutes}m {seconds:.1f}s"
    else:
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        elapsed_str = f"{hours}h {minutes}m"

    # Memoria del proceso
    try:
        mem_info = process.memory_info()
        memory_mb = mem_info.rss / (1024 * 1024)  # Bytes a MB
    except Exception:
        memory_mb = 0.0

    # Memoria del sistema
    try:
        mem_system = psutil.virtual_memory()
        memory_pct = mem_system.percent
    except Exception:
        memory_pct = 0.0

    return {
        'elapsed_time': elapsed_time,
        'elapsed_str': elapsed_str,
        'memory_mb': memory_mb,
        'memory_pct': memory_pct
    }


def print_performance_stats(
    stats: Dict[str, Union[float, str]],
    context: str = ""
) -> None:
    """
    Imprime estadísticas de rendimiento en formato legible.

    Args:
        stats: Diccionario de estadísticas (de get_performance_stats)
        context: Contexto adicional para el título (opcional)

    Example:
        >>> stats = get_performance_stats(start_time, process)
        >>> print_performance_stats(stats, "(64 años)")
        ==================================================
        ⚡ RENDIMIENTO (64 años)
        ==================================================
        🕒 Tiempo de ejecución: 2m 15.3s
        💾 RAM utilizada: 145.2 MB
        💻 Memoria sistema utilizada: 68.5%
        ==================================================
    """
    title = f"⚡ RENDIMIENTO {context}".strip()
    separator = "=" * 50

    print(f"\n{separator}")
    print(title)
    print(separator)
    print(f"🕒 Tiempo de ejecución: {stats['elapsed_str']}")
    print(f"💾 RAM utilizada: {stats['memory_mb']:.1f} MB")
    print(f"💻 Memoria sistema utilizada: {stats['memory_pct']:.1f}%")
    print(separator)
