# Modelo de Optimización - Embalse del Laja

## 📋 Descripción

Sistema de optimización avanzado para la gestión del Embalse del Laja utilizando programación lineal entera mixta (MILP) con Gurobi. Incluye simulaciones Monte Carlo, análisis de sensibilidad y optimización multi-año.

## 🏗️ Arquitectura Modular

El código ha sido completamente modularizado en componentes especializados:

### 📁 Estructura de Archivos

```
src/
├── main.py                    # Controlador principal y CLI
├── model.py                   # Modelo de optimización MILP
├── data_loader.py            # Carga y procesamiento de datos
├── sensitivity_analysis.py   # Análisis de sensibilidad y KPIs
├── montecarlo_simulation.py  # Simulaciones estocásticas
├── utils.py                  # Funciones auxiliares
└── config.py                 # Configuración y constantes
```

### 🔧 Módulos Especializados

#### `model.py`
- **Función principal**: `build_model_for_one_year()`
- **Propósito**: Formulación matemática MILP pura
- **Características**:
  - Cálculo correcto de déficits con linearización max{0, ...}
  - Cálculo de excedente para regantes
  - Restricciones de volumen y flujo
  - Variables binarias para Big-M

#### `sensitivity_analysis.py`
- **Funciones principales**: 
  - `run_sensitivity_analysis()`: Análisis paramétrico
  - `calculate_yearly_kpis()`: Cálculo de KPIs
  - `analyze_sensitivity_results()`: Análisis estadístico
- **Parámetros soportados**: V0, factor_segundos, factor_primeros
- **Métricas**: Factibilidad, energía total, promedio, mejores casos

#### `montecarlo_simulation.py`
- **Funciones principales**:
  - `run_single_year_montecarlo()`: Simulación bootstrap un año
  - `run_multi_year_montecarlo()`: Simulación recursiva multi-año
- **Características**:
  - Bootstrap mensual de caudales históricos
  - Transferencia de volúmenes entre años
  - Análisis estadístico completo (percentiles, distribuciones)

#### `main.py`
- **Propósito**: Controlador principal y CLI avanzado
- **Modos de ejecución**:
  - Optimización determinística estándar
  - Simulación Monte Carlo (un año / multi-año)
  - Análisis de sensibilidad
  - Búsqueda de mejor año
- **Interfaz CLI** completa con argumentos organizados

## 🚀 Uso del Sistema

### Instalación de Dependencias

```bash
pip install gurobipy pandas numpy matplotlib argparse
```

### Ejecución Básica

```bash
# Desde la raíz del proyecto
python -m src.main [argumentos]
```

### 📖 Ejemplos de Uso

#### 1. Optimización Determinística
```bash
# Optimizar años específicos
python -m src.main --years 2010 2015 2020 --v0 1200

# Optimizar rango con límite de tiempo
python -m src.main --years 2010 2011 2012 --time-limit 300
```

#### 2. Simulación Monte Carlo
```bash
# Monte Carlo un año (100 simulaciones)
python -m src.main --montecarlo --year 2015 --n-sims 100 --seed 42

# Monte Carlo multi-año (5 años, 50 iteraciones)
python -m src.main --montecarlo --year 2015 --multi-year --n-years 5 --n-sims 50
```

#### 3. Análisis de Sensibilidad
```bash
# Sensibilidad volumen inicial
python -m src.main --sensitivity --param V0 --values 800,900,1000,1100,1200

# Sensibilidad factor segundos regantes
python -m src.main --sensitivity --param factor_segundos --values 0.5,0.7,0.9,1.1,1.3
```

#### 4. Búsqueda Mejor Año
```bash
# Evaluar múltiples años
python -m src.main --best-year --years 2010 2015 2020 --v0 1200
```

### 🔧 Argumentos CLI Principales

| Argumento | Descripción | Default |
|----------|-------------|---------|
| `--v0` | Volumen inicial (Hm³) | 1200 |
| `--time-limit` | Límite tiempo por optimización (seg) | Sin límite |
| `--years` | Lista de años a optimizar | Primeros 10 años |
| `--montecarlo` | Activar modo Monte Carlo | - |
| `--n-sims` | Número de simulaciones | 100 |
| `--multi-year` | Simulación multi-año recursiva | - |
| `--sensitivity` | Activar análisis de sensibilidad | - |
| `--param` | Parámetro para sensibilidad | V0 |
| `--values` | Valores del parámetro (separados por comas) | - |

## 📊 Resultados y Exportación

### Archivos Generados

- **`results/cota_YYYY.csv`**: Cotas mensuales por año
- **`results/flows_YYYY.csv`**: Flujos detallados por central
- **`results/cota_YYYY.png`**: Gráficos de cotas mensuales
- **`infeasible_YYYY.ilp`**: Diagnóstico de infactibilidad (si aplica)

### KPIs Calculados

- **Tasa de factibilidad**: % años con solución óptima
- **Generación total**: Suma energía generada (MWh)
- **Generación promedio**: Media anual (MWh)
- **Mejor/peor caso**: Años extremos y rangos
- **Estadísticas Monte Carlo**: Media, mediana, percentiles, desviación estándar

## 🧮 Formulación Matemática

### Correcciones Implementadas

1. **Déficit Regantes**: Linearización correcta de max{0, demanda - asignación}
2. **Excedente**: Cálculo de sobrante como max{0, asignación - demanda}
3. **Big-M**: Uso de variables binarias para restricciones condicionales
4. **Inequalities**: Compatibilidad con Gurobi (≥ en lugar de >)

### Variables Principales

- **V[t]**: Volumen mensual embalse (Hm³)
- **f[i,j,t]**: Flujo entre nodos (m³/s)
- **deficit_primeros[t]**: Déficit primeros regantes (Hm³)
- **deficit_segundos[t]**: Déficit segundos regantes (Hm³)
- **excedente_primeros[t]**: Excedente primeros regantes (Hm³)
- **excedente_segundos[t]**: Excedente segundos regantes (Hm³)

## 🐛 Troubleshooting

### Errores Comunes

1. **ImportError**: Verificar que Gurobi esté instalado y licenciado
2. **Infeasible**: Revisar archivos `.ilp` generados para diagnóstico
3. **Memory**: Reducir número de años u usar `--time-limit`

### Logs y Debugging

```bash
# Aumentar verbosidad con años limitados para pruebas
python -m src.main --years 2020 --v0 1200 --time-limit 60
```

## 📈 Extensibilidad

### Agregar Nuevos Parámetros

1. Modificar `sensitivity_analysis.py`
2. Actualizar `config.py` con rangos
3. Extender argumentos CLI en `main.py`

### Nuevos Tipos de Simulación

1. Crear función en `montecarlo_simulation.py`
2. Registrar en CLI principal
3. Documentar en README

## 🔄 Changelog

- **v2.0**: Modularización completa en 6 módulos especializados
- **v1.1**: Corrección fórmulas déficit y excedente
- **v1.0**: Implementación inicial monolítica

---

**Autores**: Equipo Capstone G20 - Modelo Embalse del Laja  
**Universidad**: UC - 10° Semestre  
**Tecnologías**: Python, Gurobi, MILP, Monte Carlo