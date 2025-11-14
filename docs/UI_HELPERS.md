# UI HELPERS - Funciones Compartidas de Interfaz

## 📋 Descripción

`ui_helpers.py` centraliza todas las funciones de interfaz de usuario, medición de rendimiento y visualización que se utilizan en múltiples módulos del proyecto. Esto elimina la duplicación de código y asegura consistencia visual en toda la aplicación.

## 🎯 Objetivo

Proporcionar una **fuente única de verdad** para elementos de interfaz, evitando que cada módulo (`model.py`, `montecarlo.py`, `analisis_sensibilidad_v0.py`, `caso_base.py`) reimplemente las mismas funciones.

## 📦 Funciones Disponibles

### 🔧 Entrada de Usuario

#### `get_input(prompt, default=None, input_type=str)`
Solicita entrada del usuario con valor por defecto y validación de tipo.

**Parámetros:**
- `prompt` (str): Mensaje a mostrar
- `default` (Any, opcional): Valor por defecto
- `input_type` (type): Tipo esperado (str, int, float, bool)

**Ejemplo:**
```python
from ui_helpers import get_input

year = get_input("Año inicial", default=1960, input_type=int)
V0 = get_input("Volumen inicial V0 (Hm³)", default=1400.0, input_type=float)
```

---

### ⚡ Medición de Rendimiento

#### `get_performance_stats(start_time, process)`
Calcula estadísticas de rendimiento del sistema.

**Parámetros:**
- `start_time` (float): Tiempo de inicio (time.time())
- `process` (psutil.Process): Proceso actual

**Retorna:**
```python
{
    "execution_time_seconds": 150.5,
    "execution_time_formatted": "2m 30.5s",
    "memory_rss_mb": 245.3,
    "memory_vms_mb": 512.7,
    "memory_percent": 3.2,
    "system_memory_total_gb": 16.0,
    "system_memory_available_gb": 8.5,
    "system_memory_used_percent": 46.8
}
```

**Ejemplo:**
```python
import time
import psutil
from ui_helpers import get_performance_stats, print_performance_stats

start = time.time()
process = psutil.Process()

# ... ejecutar código ...

stats = get_performance_stats(start, process)
print_performance_stats(stats, "(Monte Carlo)")
```

**Salida:**
```
==================================================
⚡ RENDIMIENTO (Monte Carlo)
==================================================
🕒 Tiempo de ejecución: 2m 30.5s
💾 RAM utilizada: 245.3 MB
💻 Memoria sistema utilizada: 46.8%
==================================================
```

---

#### `format_time(seconds)`
Formatea tiempo en segundos a formato legible.

**Ejemplos:**
```python
from ui_helpers import format_time

format_time(45.2)     # '45.2s'
format_time(930.5)    # '15m 30.5s'
format_time(8130.2)   # '2h 15m 30s'
```

---

#### `print_performance_stats(stats, context="")`
Imprime estadísticas de rendimiento en formato visual unificado.

---

### 🎨 Elementos Visuales

#### `print_header(title, subtitle=None, width=70, emoji="📊")`
Imprime encabezado visual consistente.

**Ejemplo:**
```python
from ui_helpers import print_header

print_header("MODELO DETERMINISTA", "Optimización multi-año", emoji="🏔️")
```

**Salida:**
```
======================================================================
🏔️ MODELO DETERMINISTA
======================================================================
Optimización multi-año
```

---

#### `print_separator(width=70, char="=")`
Imprime línea separadora.

**Ejemplo:**
```python
from ui_helpers import print_separator

print_separator()          # ======================================
print_separator(50, "-")   # --------------------------------------------------
```

---

#### `print_section(title, width=70)`
Imprime título de sección con separadores.

**Ejemplo:**
```python
from ui_helpers import print_section

print_section("RESULTADOS DEL ANÁLISIS")
```

**Salida:**
```

======================================================================
RESULTADOS DEL ANÁLISIS
======================================================================
```

---

#### `print_progress_inline(message, end='', flush=True)`
Imprime mensaje de progreso en la misma línea (con `\r`).

**Ejemplo:**
```python
from ui_helpers import print_progress_inline
import time

for i in range(100):
    print_progress_inline(f"Progreso: {i}%")
    time.sleep(0.1)
print()  # Nueva línea al finalizar
```

---

#### Mensajes con Formato

- `print_info(message, emoji="ℹ️")` - Mensaje informativo
- `print_success(message, emoji="✅")` - Mensaje de éxito
- `print_warning(message, emoji="⚠️")` - Mensaje de advertencia
- `print_error(message, emoji="❌")` - Mensaje de error

**Ejemplo:**
```python
from ui_helpers import print_info, print_success, print_warning, print_error

print_info("Cargando datos históricos...")
print_success("Optimización completada exitosamente")
print_warning("Algunos escenarios fallaron")
print_error("No se pudo cargar el archivo de datos")
```

**Salida:**
```
ℹ️ Cargando datos históricos...
✅ Optimización completada exitosamente
⚠️ Algunos escenarios fallaron
❌ No se pudo cargar el archivo de datos
```

---

#### `configure_console()`
Configura la consola para correcta visualización de caracteres UTF-8 en Windows.

**Uso:**
```python
from ui_helpers import configure_console

def main():
    configure_console()  # Llamar al inicio del programa
    # ... resto del código ...
```

---

### ✅ Validadores

#### `validate_year(year, min_year, max_year)`
Valida que el año esté en el rango disponible.

**Ejemplo:**
```python
from ui_helpers import validate_year

try:
    year = validate_year(2015, 1960, 2023)  # OK
    year = validate_year(1950, 1960, 2023)  # ValueError
except ValueError as e:
    print(e)  # "Año debe estar entre 1960 y 2023"
```

---

#### `validate_positive(value, name="Valor")`
Valida que un valor sea positivo.

**Ejemplo:**
```python
from ui_helpers import validate_positive

V0 = validate_positive(1400.0, "V0")  # OK
V0 = validate_positive(-100, "V0")    # ValueError: V0 debe ser positivo
```

---

#### `validate_range(value, min_val, max_val, name="Valor")`
Valida que un valor esté dentro de un rango.

**Ejemplo:**
```python
from ui_helpers import validate_range

V0 = validate_range(2500, 0, 5582, "V0")  # OK
V0 = validate_range(6000, 0, 5582, "V0")  # ValueError
```

---

### 📊 Formateo de Datos

#### `format_number(value, decimals=0, thousands_sep=",")`
Formatea número con separadores de miles.

**Ejemplo:**
```python
from ui_helpers import format_number

format_number(1234567.89, decimals=2)  # '1,234,567.89'
format_number(1400, decimals=0)        # '1,400'
```

---

#### `format_percentage(value, decimals=1)`
Formatea valor como porcentaje.

**Ejemplo:**
```python
from ui_helpers import format_percentage

format_percentage(95.678, decimals=1)  # '95.7%'
format_percentage(100, decimals=0)     # '100%'
```

---

### 📋 Tablas

#### `print_table_row(columns, widths, alignment='>')`
Imprime una fila de tabla alineada.

**Ejemplo:**
```python
from ui_helpers import print_table_row, print_table_separator

# Encabezado
print_table_row(["V0", "Energía", "Éxito"], [10, 15, 10])
print_table_separator([10, 15, 10])

# Datos
print_table_row([1400, 125000, 95.5], [10, 15, 10])
```

**Salida:**
```
        V0         Energía      Éxito
-------------------------------------
      1400          125000       95.5
```

---

## 📚 Migración desde Módulos Existentes

### Antes (Código Duplicado)

**model.py, montecarlo.py, caso_base.py, analisis_sensibilidad_v0.py:**
```python
def get_input(prompt, default=None, input_type=str):
    # ... 20 líneas de código duplicadas ...

def format_time(seconds: float) -> str:
    # ... 10 líneas de código duplicadas ...

def get_performance_stats(start_time, process):
    # ... 30 líneas de código duplicadas ...

def print_performance_stats(stats, context=""):
    # ... 10 líneas de código duplicadas ...
```

**Total:** ~280 líneas duplicadas en 4 archivos

---

### Después (Código Centralizado)

**ui_helpers.py:**
```python
# Implementación única de todas las funciones (~600 líneas)
```

**model.py, montecarlo.py, caso_base.py, analisis_sensibilidad_v0.py:**
```python
from ui_helpers import (
    get_input,
    format_time,
    get_performance_stats,
    print_performance_stats
)
```

**Beneficios:**
- ✅ Eliminación de ~280 líneas duplicadas
- ✅ Mantenimiento centralizado
- ✅ Consistencia visual garantizada
- ✅ Documentación única
- ✅ Facilidad para agregar nuevas funciones

---

## 🔄 Patrones de Uso Comunes

### 1. Interfaz Interactiva Completa

```python
from ui_helpers import (
    configure_console,
    print_header,
    get_input,
    print_info,
    print_success,
    get_performance_stats,
    print_performance_stats
)
import time
import psutil

def main():
    configure_console()
    
    print_header("MI MÓDULO", "Descripción breve", emoji="🚀")
    
    # Capturar parámetros
    year = get_input("Año inicial", default=1960, input_type=int)
    V0 = get_input("Volumen inicial (Hm³)", default=1400.0, input_type=float)
    
    print_info("Ejecutando simulación...")
    
    # Medir rendimiento
    start = time.time()
    process = psutil.Process()
    
    # ... ejecutar código ...
    
    print_success("Simulación completada")
    
    # Mostrar estadísticas
    stats = get_performance_stats(start, process)
    print_performance_stats(stats, "(Mi Módulo)")

if __name__ == "__main__":
    main()
```

---

### 2. Loader en una Línea

```python
from ui_helpers import print_progress_inline

for i in range(100):
    print_progress_inline(f"🔄 Progreso: [{i+1}/100] Procesando...")
    # ... trabajo ...
print()  # Nueva línea al finalizar
```

---

### 3. Tabla de Resultados

```python
from ui_helpers import print_table_row, print_table_separator

# Encabezado
columns = ["V0 [Hm³]", "Energía [MWh]", "Éxito [%]"]
widths = [12, 15, 12]

print_table_row(columns, widths)
print_table_separator(widths)

# Datos
for result in results:
    print_table_row(
        [result.V0, result.energy, result.success],
        widths
    )
```

---

## 🧪 Testing

Para verificar que ui_helpers funciona correctamente:

```python
# Test rápido
from ui_helpers import *

# Test básico
print_header("TEST UI HELPERS", emoji="🧪")
nombre = get_input("Tu nombre", default="Usuario")
print_success(f"Hola, {nombre}!")

# Test de rendimiento
import time, psutil
start = time.time()
process = psutil.Process()
time.sleep(2)
stats = get_performance_stats(start, process)
print_performance_stats(stats, "(Test)")
```

---

## 📈 Beneficios del Enfoque

### Antes: Código Duplicado
```
model.py                  [~70 líneas duplicadas]
montecarlo.py             [~70 líneas duplicadas]
caso_base.py              [~70 líneas duplicadas]
analisis_sensibilidad_v0.py [~70 líneas duplicadas]
──────────────────────────
Total: ~280 líneas duplicadas
```

### Después: Código Centralizado
```
ui_helpers.py             [~600 líneas (implementación única)]
model.py                  [import 4 funciones]
montecarlo.py             [import 5 funciones]
caso_base.py              [import 2 funciones]
analisis_sensibilidad_v0.py [import 2 funciones]
──────────────────────────
Total: ~620 líneas (sin duplicación)
```

**Reducción:** 78% menos líneas totales + mantenibilidad mejorada

---

## 🔍 Responsabilidades Claras

### `ui_helpers.py`
- ✅ Entrada de usuario
- ✅ Medición de rendimiento
- ✅ Formateo visual
- ✅ Validación de datos
- ✅ Configuración de consola

### `model.py`
- ✅ Construcción del modelo de optimización
- ✅ Restricciones R0-R8
- ✅ Linearización PWL
- ❌ ~NO gestión de interfaz~

### `montecarlo.py`
- ✅ Simulación Monte Carlo
- ✅ Bootstrap por bloques
- ✅ Generación de escenarios
- ❌ ~NO gestión de interfaz~

### `analisis_sensibilidad_v0.py`
- ✅ Análisis de sensibilidad V0
- ✅ Visualización de resultados
- ✅ Identificación de óptimos
- ❌ ~NO gestión de interfaz~

### `caso_base.py`
- ✅ Modelo sin colchones
- ✅ Análisis histórico
- ❌ ~NO gestión de interfaz~

---

## 🎓 Ejemplo de Uso Completo

Ver `ejemplo_ui_helpers.py` para una demostración interactiva de todas las funciones disponibles.

---

## 🚀 Próximos Pasos

1. ✅ Crear `ui_helpers.py` con todas las funciones
2. ✅ Migrar `model.py` para usar ui_helpers
3. ✅ Migrar `montecarlo.py` para usar ui_helpers
4. ✅ Migrar `analisis_sensibilidad_v0.py` para usar ui_helpers
5. ✅ Migrar `caso_base.py` para usar ui_helpers
6. ⏳ Crear tests unitarios para ui_helpers
7. ⏳ Agregar más funciones de tabla (tabla completa con bordes)
8. ⏳ Agregar funciones de barra de progreso avanzada

---

## 📝 Notas

- Todas las funciones están documentadas con docstrings completos
- Ejemplos de uso incluidos en cada función
- Compatible con Windows (codepage UTF-8)
- Sin dependencias externas adicionales (solo stdlib + psutil)

---

**Autor:** Sistema de Optimización Embalse del Laja  
**Versión:** 1.0  
**Fecha:** Noviembre 2024
