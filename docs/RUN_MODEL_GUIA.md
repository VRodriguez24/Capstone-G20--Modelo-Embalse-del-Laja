# Guía de Uso: Módulo Unificado de Ejecución (`run_model.py`)

## 📋 Resumen

Se ha creado un módulo centralizado `run_model.py` que contiene toda la lógica de interfaz de usuario, menús interactivos, y análisis de resultados para los modelos del Embalse del Laja. Esto elimina ~500 líneas de código duplicado y facilita el mantenimiento.

## 🎯 Beneficios

### Antes (Código Duplicado)
```
model.py        → 500+ líneas de interfaz UI
caso_base.py    → 550+ líneas de interfaz UI (98% duplicado)
montecarlo.py   → Interfaz personalizada
```

### Después (Centralizado)
```
run_model.py    → 1 módulo con toda la lógica UI
model.py        → 8 líneas usando run()
caso_base.py    → 8 líneas usando run()
montecarlo.py   → Puede usar run() cuando se actualice
```

**Reducción**: ~1000 líneas duplicadas → ~600 líneas centralizadas  
**Ahorro**: 40% de código, 100% menos duplicación

## 🚀 Uso Básico

### Para `model.py` (Modelo Determinístico)
```python
if __name__ == "__main__":
    from run_model import run

    run(
        build_model_func=build_model_for_one_year,
        years_horizon=YEARS_HORIZON,
        time_periods=T,
        conv_factor=Conv,
        model_name="Modelo Determinístico - Embalse del Laja",
        default_v0=V_0
    )
```

### Para `caso_base.py` (Sin Colchones)
```python
if __name__ == "__main__":
    from run_model import run

    run(
        build_model_func=build_model_for_one_year,
        years_horizon=YEARS_HORIZON,
        time_periods=T,
        conv_factor=Conv,
        model_name="Modelo Caso Base - Sin Colchones",
        default_v0=V_0
    )
```

### Para Futuros Modelos
```python
if __name__ == "__main__":
    from run_model import run

    run(
        build_model_func=mi_funcion_de_modelo,
        years_horizon=[1960, 2023],
        time_periods=[12, 1, 2, ..., 11],
        conv_factor=2.592,  # (86400*30)/1e6
        model_name="Mi Modelo Personalizado",
        default_v0=1400.0
    )
```

## 📖 Parámetros de `run()`

| Parámetro | Tipo | Descripción |
|-----------|------|-------------|
| `build_model_func` | `Callable` | Función que construye el modelo para un año. Debe aceptar `target_year` y `V0` |
| `years_horizon` | `List[int]` | `[año_mínimo, año_máximo]` de datos disponibles (ej: `[1960, 2023]`) |
| `time_periods` | `List[int]` | Períodos de tiempo del modelo (ej: `[12,1,2,...,11]` para Dic-Nov) |
| `conv_factor` | `float` | Factor de conversión m³/s×mes → Hm³ (usualmente `(86400*30)/1e6 = 2.592`) |
| `model_name` | `str` | Nombre descriptivo del modelo para mostrar en el menú |
| `default_v0` | `float` | Volumen inicial por defecto en Hm³ (usualmente `1400.0`) |

## 🎨 Requisitos para `build_model_func`

Tu función de construcción del modelo debe:

1. **Firmar**:
   ```python
   def build_model_for_one_year(
       target_year: int,
       V0: float,
       I_arc_override: Optional[dict] = None
   ) -> gp.Model:
   ```

2. **Retornar** un modelo de Gurobi con estos atributos:
   - `model._V`: Variables de volumen por período
   - `model._x`: Variables de flujo de generación por arco y período
   - `model._y`: Variables de flujo por arco y período
   - `model.objVal`: Valor de la función objetivo (tras optimizar)

3. **Aceptar parámetros opcionales**:
   - `I_arc_override`: Para sobreescribir inyecciones (útil en Monte Carlo)

## 🔄 Funcionalidades Incluidas

### 1. Menú Interactivo
```
============================================================
  🌊 MODELO DETERMINÍSTICO - EMBALSE DEL LAJA
============================================================
📊 Datos disponibles: 1960 - 2023
📅 Período hidrológico: Diciembre -> Noviembre
    (fin temporada 30-Nov)

🎯 Opciones:
1️⃣  Año/Rango específico (ej: '1985' o '1980-1990')
2️⃣  Todos los años disponibles (1960-2023)
0️⃣  Salir
------------------------------------------------------------
```

### 2. Ejecución por Rango
- Acepta año único: `1985`
- Acepta rango: `1980-1990`
- Validación automática de rangos
- Volumen inicial configurable

### 3. Análisis Completo
- Resumen de energía total
- Uso total de El Toro
- Promedios por año exitoso
- Balance volumétrico
- KPIs detallados por año
- KPIs agregados multi-año
- Gráficos históricos automáticos

### 4. Estadísticas de Rendimiento
```
⏱️  Tiempo transcurrido: 2h 15m 30s
💾 Memoria usada: 1,234.56 MB
🔧 CPU promedio: 45.2%
```

## 📊 Ejemplo de Salida

### Ejecución de Año Único
```
📅 Procesando año 1985 (1/1)
💧 V0: 1,400.0 Hm³
✅ Energía: 1,234,567.8 MWh | V_final: 1,450.2 Hm³ | Uso Toro: 234.5 Hm³

============================================================
📋 RESUMEN DETALLADO
============================================================
🎯 Años procesados: 1
✅ Años exitosos: 1 (100.0%)
⚡ Energía total: 1,234,567.8 MWh
🌊 Uso total El Toro: 234.5 Hm³

📊 Energía promedio: 1,234,567.8 MWh/año
📊 Uso promedio El Toro: 234.5 Hm³/año

💧 BALANCE DE VOLUMEN:
   Inicial: 1,400.0 Hm³
   Final: 1,450.2 Hm³
   📈 Cambio: +50.2 Hm³
```

### Ejecución de Rango Múltiple
```
📅 Procesando año 1980 (1/11)
✅ E: 1,200,000 MWh | V_f: 1,350 | Toro: 210.5 Hm³
...
📅 Procesando año 1990 (11/11)
✅ E: 1,150,000 MWh | V_f: 1,420 | Toro: 195.3 Hm³

============================================================
📋 RESUMEN DETALLADO
============================================================
🎯 Años procesados: 11
✅ Años exitosos: 11 (100.0%)
⚡ Energía total: 13,250,000.0 MWh
🌊 Uso total El Toro: 2,340.5 Hm³

📊 KPIs AGREGADOS (11 años exitosos):
============================================================
📏 TRAYECTORIA PROMEDIO AGREGADA:
   Cota promedio multi-año: 1,325.4 msnm

🚱 DÉFICITS AGREGADOS:
   Déficit máximo promedio:     12.50 m³/s
   Déficit máximo peor año:     45.30 m³/s
   Déficit promedio:             3.20 m³/s
   Confiabilidad promedio:      98.5%

📊 DETALLE POR AÑO:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Año   Estado  Energía (MWh)  V_final (Hm³)  Uso Toro (Hm³)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1980   ✅       1,200,000.0       1,350.0         210.5
1981   ✅       1,180,000.0       1,320.0         195.8
...
1990   ✅       1,150,000.0       1,420.0         195.3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 🏗️ Arquitectura Interna

### `run_model.py` contiene:

1. **`parse_years_input(years_str, years_horizon)`**
   - Parsea entrada de años: `'1985'` o `'1980-1990'`
   - Valida rangos contra datos disponibles
   - Retorna lista de años válidos

2. **`run_custom_range(...)`**
   - Ejecuta modelo para año(s) específico(s)
   - Análisis detallado con KPIs
   - Tablas y gráficos automáticos

3. **`run_all_years(...)`**
   - Ejecuta simulación completa (todos los años)
   - KPIs históricos agregados
   - Confirmación de usuario antes de ejecutar

4. **`run(...)`** ← **FUNCIÓN PRINCIPAL**
   - Muestra menú interactivo
   - Llama a `run_custom_range()` o `run_all_years()`
   - Maneja errores y interrupciones de usuario

## 🔧 Integración con Otros Módulos

### Dependencias de `run_model.py`:
```python
from ui_helpers import (
    get_input,                  # Entrada validada de usuario
    get_performance_stats,      # Métricas de rendimiento
    print_performance_stats     # Formato de métricas
)

from kpi import (
    extract_kpis,              # Extrae KPIs de un modelo
    aggregate_kpis,            # Agrega KPIs de múltiples años
    print_kpis,                # Imprime KPIs formateados
    generate_historical_plots  # Genera gráficos históricos
)
```

### Diagrama de Dependencias:
```
run_model.py
    ├── ui_helpers.py (entrada, formateo, performance)
    ├── kpi.py (extracción, agregación, visualización)
    └── (modelo específico)
            ├── embalse.py (red, nodos, arcos)
            ├── data_loader.py (CSV)
            ├── filt_cota.py (filtraciones, PWL)
            └── gurobipy (optimización)
```

## 🎯 Casos de Uso

### Caso 1: Probar Nuevo Modelo
```python
# nuevo_modelo.py
def build_mi_modelo(target_year: int, V0: float) -> gp.Model:
    # ... implementación ...
    return model

if __name__ == "__main__":
    from run_model import run
    
    run(
        build_model_func=build_mi_modelo,
        years_horizon=[1960, 2023],
        time_periods=[12,1,2,3,4,5,6,7,8,9,10,11],
        conv_factor=2.592,
        model_name="Mi Nuevo Modelo",
        default_v0=1400.0
    )
```

### Caso 2: Análisis Rápido de Década
```
$ python src/model.py

Selecciona una opción: 1
Especifica año(s): 2010-2019
💧 Volumen inicial V0 (Hm³) [1400.0]: 

🚀 Ejecutando modelo para 10 años (2010-2019)...
[... análisis automático ...]
```

### Caso 3: Simulación Histórica Completa
```
$ python src/model.py

Selecciona una opción: 2
¿Confirmas ejecutar 64 años? [s/N]: s
💧 Volumen inicial V0 (Hm³) [1400.0]: 

🚀 Iniciando simulación completa...
[... procesamiento de 1960-2023 ...]
📊 Gráficos: 2 PNG
   ✓ evolucion_historica_lago_cota.png
   ✓ evolucion_historica_lago_deficit.png
```

## 🚨 Solución de Problemas

### Error: "Modelo no tiene atributo _V"
**Causa**: La función `build_model_func` no asigna `model._V`  
**Solución**: Agregar `model._V = V` después de crear variables de volumen

### Error: "años fuera de rango"
**Causa**: `years_horizon` no coincide con datos disponibles  
**Solución**: Verificar que `years_horizon` sea correcto en tu modelo

### Error: "KeyError: ('Embalse', 'ElToro')"
**Causa**: El modelo no tiene arco El Toro (normal en algunos modelos)  
**Solución**: `run_model.py` maneja esto automáticamente, verifica arcos

## 📝 Migración de Código Legacy

### Antes:
```python
# model.py (~800 líneas)
if __name__ == "__main__":
    def print_simple_menu():
        # ... 20 líneas ...
    
    def get_input(prompt, default=None, input_type=str):
        # ... 15 líneas ...
    
    def parse_years_input(years_str):
        # ... 30 líneas ...
    
    def run_custom_range():
        # ... 200 líneas ...
    
    def run_all_years():
        # ... 250 líneas ...
    
    # Bucle principal
    while True:
        # ... 50 líneas ...
```

### Después:
```python
# model.py (~500 líneas)
if __name__ == "__main__":
    from run_model import run
    
    run(
        build_model_func=build_model_for_one_year,
        years_horizon=YEARS_HORIZON,
        time_periods=T,
        conv_factor=Conv,
        model_name="Modelo Determinístico",
        default_v0=V_0
    )
```

**Reducción**: 300 líneas eliminadas por archivo  
**Total**: ~900 líneas eliminadas del proyecto

## 🎓 Mejores Prácticas

1. **Nombres Descriptivos**: Usa `model_name` para diferenciar modelos en el menú
2. **Validación**: `run_model.py` valida entradas automáticamente
3. **Recursividad**: V0 de cada año = V_final del año anterior
4. **Reset de Seguridad**: Si un año falla, se resetea a 1400 Hm³
5. **KPIs Detallados**: Para análisis profundo, re-ejecuta el modelo con OutputFlag=0

## 📚 Referencias

- **`ui_helpers.py`**: Funciones de interfaz de usuario centralizadas
- **`kpi.py`**: Cálculo y visualización de KPIs estratégicos
- **`filt_cota.py`**: Filtraciones y linearización PWL
- **`model.py`**: Modelo determinístico con colchones
- **`caso_base.py`**: Modelo sin reparto por colchones

---

**Documentación creada**: Noviembre 2025  
**Versión**: 1.0  
**Mantenedor**: Equipo Capstone G20
