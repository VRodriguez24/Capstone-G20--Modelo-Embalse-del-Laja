# 🌊 Modelo de Optimización - Embalse del Laja

## 📋 Descripción General

Sistema completo de optimización y análisis estocástico para la gestión del Embalse del Laja. Implementa programación lineal entera mixta (MILP) con Gurobi, simulaciones Monte Carlo con bootstrap estacional, y análisis de sensibilidad avanzado.

### � Características Principales

- **Modelo MILP determinístico** con período hidrológico oficial (Dic→Nov)
- **Simulación Monte Carlo** con bootstrap por bloques estacional
- **Interfaces interactivas** para ejecución directa
- **Análisis de sensibilidad** y evaluación de riesgo
- **Optimización multi-año** con volúmenes recursivos

## 🏗️ Arquitectura del Sistema

### 📁 Estructura de Archivos

```
📦 Capstone-G20--Modelo-Embalse-del-Laja/
├── 📂 src/                          # Código fuente
│   ├── model.py                     # 🎯 Modelo MILP + Interface interactiva
│   ├── montecarlo.py               # 🎲 Simulación Monte Carlo unificada
│   ├── data_loader.py              # 📊 Carga y procesamiento de datos
│   ├── sensitivity.py              # 📈 Análisis de sensibilidad
│   ├── embalse.py                  # 🏗️ Definición de red y conjuntos
│   ├── filt_cota.py               # 💧 Curvas de filtración PWL
│   └── main.py                     # 🚀 Controlador principal CLI
├── 📂 data/                         # Datos históricos
│   ├── Caudales_historicos_filtrado.csv
│   └── CaudalMax_filtrado.csv
├── 📂 results/                      # Resultados de simulaciones
├── 📂 pre-procesamiento/            # Scripts de preprocesamiento
└── 📄 README.md                     # Esta documentación
```

### 🔧 Módulos Especializados

#### 🎯 `model.py` - Modelo MILP + Interface Interactiva
- **Función principal**: `build_model_for_one_year()`
- **Características del modelo**:
  - Período hidrológico oficial: **Diciembre → Noviembre** (30-Nov fin temporada)
  - Linearización correcta de déficits: max{0, demanda - asignación}
  - Sistema de colchones volumétricos con presupuestos dinámicos
  - Variables binarias para Big-M y selección de colchones
  - Restricciones PWL para filtraciones del embalse
- **Interface interactiva**:
  - Menú principal con opciones 1️⃣ Año/Rango específico, 2️⃣ Todos los años
  - Parsing inteligente: '1985' o '1980-1990'
  - Volúmenes recursivos: V_final(30-Nov) → V_inicial(Dic siguiente)
  - Reportes detallados con métricas de El Toro

#### 🎲 `montecarlo.py` - Simulación Monte Carlo Unificada
- **Clases principales**:
  - `BlockBootstrapSampler`: Bootstrap por bloques estacional
  - `MonteCarloSimulator`: Simulador MC single-year y multi-year
  - `SimulationResult` & `SimulationSummary`: Clases de datos
- **Características**:
  - Bootstrap por bloques preservando correlaciones temporales
  - Ruido lognormal configurable (σ = 0.05-0.2)
  - Análisis de percentiles de riesgo (P5, P50, P95)
  - Interface interactiva con menú 3 opciones
  - Trayectorias multi-año con recursividad volumétrica

#### 📊 `data_loader.py` - Gestión de Datos
- **Funciones principales**: 
  - `load_injections_for_year()`: Carga caudales por año
  - `load_caudalmax()`: Capacidades y eficiencias de centrales
- **Características**: Manejo robusto de datos faltantes, normalización

#### 📈 `sensitivity.py` - Análisis de Sensibilidad
- **Función principal**: `extract_kpis()`: Extracción de KPIs del modelo
- **Métricas**: Status, energía, volúmenes, factibilidad
- **Análisis**: Compatibilidad con análisis paramétrico

#### 🏗️ `embalse.py` - Definición de Red
- **Conjuntos**: NODES, ARCS, A_inyeccion, A_generacion, IN, OUT
- **Topología**: Red hidráulica completa del sistema Laja

#### 💧 `filt_cota.py` - Curvas de Filtración
- **Función**: `get_pwl_segments()`: Segmentos PWL para filtraciones
- **Implementación**: Aproximación piecewise-linear de curvas no lineales

## 🚀 Guía de Uso Completa

### 📋 Prerequisitos

```bash
# Dependencias principales
pip install gurobipy pandas numpy matplotlib

# Licencia Gurobi requerida (académica disponible)
# Datos históricos en carpeta data/
```

### 🎯 Ejecución Interactiva (Recomendado)

#### 1. Modelo Determinístico
```bash
# Interface interactiva completa
python src/model.py
```

**Opciones del menú**:
- **1️⃣ Año/Rango específico**: Entrada flexible ('1985' o '1980-1990')
- **2️⃣ Todos los años**: Simulación completa 1960-2023
- **Configuración**: V0, parsing inteligente, reportes detallados

#### 2. Simulación Monte Carlo
```bash
# Interface Monte Carlo unificada
python src/montecarlo.py
```

**Opciones del menú**:
- **1️⃣ Simulación single-year**: MC para año específico con análisis estadístico
- **2️⃣ Simulación multi-año**: Trayectorias recursivas con estadísticas por año
- **3️⃣ Análisis de sensibilidad**: Evaluación paramétrica (en desarrollo)

### 🛠️ Uso Programático Avanzado

#### Modelo Determinístico
```python
from model import build_model_for_one_year

# Optimización para año específico
model = build_model_for_one_year(target_year=1985, V0=1400.0)
model.optimize()

# Análisis de resultados
if model.status == 2:  # Óptimo
    energy = model.objVal
    final_volume = model._V[11].x  # Noviembre (fin período)
```

#### Simulación Monte Carlo
```python
from montecarlo import MonteCarloSimulator

# Simulador con bootstrap estacional
simulator = MonteCarloSimulator()

# Monte Carlo single-year
results, summary = simulator.run_single_year(
    target_year=1985,
    V0=1400.0,
    n_iterations=100,
    block_len=3,
    noise_sigma=0.1
)

# Monte Carlo multi-año con recursividad
trajectories = simulator.run_multi_year(
    start_year=1980,
    n_years=10,
    V0=1400.0,
    n_iterations=50
)
```

#### Bootstrap de Escenarios
```python
from montecarlo import BlockBootstrapSampler

# Generar escenarios estocásticos
sampler = BlockBootstrapSampler("data/Caudales_historicos_filtrado.csv")

# Escenario base con bootstrap por bloques
scenario = sampler.sample_year(block_len=3)

# Escenario con ruido lognormal
noisy_scenario = sampler.sample_with_noise(block_len=3, sigma=0.1)
```

## � Período Hidrológico Oficial

### 🔄 Cambio Fundamental Implementado

El sistema opera con el **período hidrológico oficial chileno**:

- **Período**: **Diciembre → Noviembre** (fin temporada 30-Nov)
- **Conjunto temporal**: `T = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]`
- **Interpretación**: Año 1985 = Dic'84 → Nov'85

### 💡 Implicaciones

- **Volumen inicial**: Medido al 1° diciembre
- **Volumen final**: Medido al 30 noviembre
- **Recursividad**: V_final(30-Nov-año_n) → V_inicial(Dic-año_n+1)
- **Presupuestos**: Calculados según volumen al 30-Nov (normativa oficial)

### 🎯 Parámetros Configurables

| Parámetro | Descripción | Rango/Default |
|-----------|-------------|---------------|
| **Año objetivo** | Período hidrológico | 1960-2023 |
| **V0** | Volumen inicial (Hm³) | 0-5582 / 1400 |
| **Iteraciones MC** | Número de simulaciones | 10-1000 / 100 |
| **Longitud bloques** | Meses por bloque bootstrap | 2-6 / 3 |
| **Ruido σ** | Desviación lognormal | 0.05-0.3 / 0.1 |

## 📊 Resultados y Métricas

### 📈 KPIs del Modelo Determinístico

- **Energía total generada**: Suma anual por centrales (MWh)
- **Volumen embalse**: Evolución mensual y volumen final (Hm³)
- **Uso El Toro**: Agua extraída para cubrir déficits (Hm³)
- **Tasa de éxito**: % de años con solución óptima
- **Balance volumétrico**: V_inicial vs V_final con cambio neto

### 🎲 Análisis Monte Carlo

#### Métricas Single-Year
- **Distribución de energía**: Media, mediana, desviación estándar
- **Percentiles de riesgo**: P5, P50, P95 para análisis VaR
- **Tasa de factibilidad**: % escenarios con solución óptima
- **Robustez volumétrica**: Estadísticas de volumen final

#### Análisis Multi-Año
- **Trayectorias completas**: Energía acumulada por trayectoria
- **Estadísticas por año**: Éxito, energía promedio por período
- **Correlaciones temporales**: Persistencia de rendimiento
- **Evaluación de políticas**: Robustez a largo plazo

### 📁 Archivos de Salida

#### Modelo Determinístico
- **Consola interactiva**: Reportes detallados en tiempo real
- **Métricas de sesión**: Resúmenes por año y consolidados
- **Balance volumétrico**: Seguimiento recursivo entre años

#### Simulación Monte Carlo
- **Análisis estadístico**: Distribuciones completas por pantalla
- **Tablas de trayectorias**: Resultados multi-año organizados
- **Análisis de riesgo**: Percentiles y tasas de éxito

## 🧮 Formulación Matemática Avanzada

### 🎯 Modelo MILP Core

**Función Objetivo**: Maximizar energía total generada
```
MAX Σ(t∈T) G[t]
```

### 🔧 Variables Principales

#### Variables Continuas
- **V[t]**: Volumen embalse mensual (Hm³) ∈ [0, 5582]
- **y[i,j,t]**: Flujo arcos normales (m³/s) ≥ 0
- **x[i,j,t]**: Flujo arcos generación (m³/s) ≥ 0
- **G[t]**: Energía mensual generada (MWh) ≥ 0
- **Filtr[t]**: Filtraciones embalse (Hm³/mes) ≥ 0

#### Variables Binarias (MILP)
- **z[c]**: Selección colchón volumétrico ∈ {0,1}
- **δ[k,t]**: Selección segmento PWL filtraciones ∈ {0,1}
- **dAb[t], dTu[t], d2[t]**: Variables déficit ∈ {0,1}

### 🏗️ Restricciones Principales

#### R1: Balance Hídrico Embalse
```
V[t] = V[t-1] + (Entradas[t] - Salidas[t]) × Conv
```
Con manejo especial para t=12 (diciembre, inicio período)

#### R2: Conservación de Flujo
```
Σ(entradas) + Inyecciones_externas = Σ(salidas)
```
Para todos los nodos excepto almacenamientos

#### R3-R4: Capacidades y Energía
```
x[i,j,t] ≤ cap_max[i,j]
G[t] = Σ(η[i,j] × x[i,j,t])
```

#### R5: Filtraciones PWL
```
Filtr[t] = Σ(k) δ[k,t] × f_PWL(V[t-1])
Σ(k) δ[k,t] = 1
```

#### R6: Déficits Regantes (Linearización Big-M)
```
Déficit_Abanico[t] = max{0, Demanda[t] - (Filtr[t] + Afluente[t])}
Déficit_Tucapel[t] = max{0, Demanda[t] - (Filtr[t] + Naturales[t])}
```
Implementado con variables binarias y restricciones Big-M

#### R7: Presupuestos por Colchón (McCormick)
Sistema de presupuestos dinámicos basados en volumen inicial:
```
Uso_Riego ≤ Budget_Riego(V0, colchón_activo)
Uso_Generación ≤ Budget_Generación(V0, colchón_activo)
V[t] ≥ Budget_Lago(V0, colchón_activo) ∀t
```

### 🔬 Metodología Monte Carlo

#### Bootstrap por Bloques Estacional
1. **Descomposición**: Año hidrológico en bloques de k meses
2. **Muestreo**: Selección aleatoria de bloques históricos
3. **Preservación**: Correlaciones temporales de corto plazo
4. **Estacionalidad**: Respeto de patrones mensuales

#### Generación de Ruido
```
factor_ruido ~ LogNormal(μ=0, σ²)
caudal_final = caudal_bootstrap × factor_ruido
```

### 🎯 Sistema de Colchones

| Colchón | Rango (Hm³) | Riego | Generación | Lago |
|---------|-------------|--------|------------|------|
| Inferior | 0-1200 | 600 Hm³ | 5% V0 | 0% |
| Transición | 1200-1370 | 40% V0 | 5% V0 | 55% V0 |
| Intermedio | 1370-1900 | 40% V0 | 40% V0 | 20% V0 |
| Superior | 1900-5582 | 25% V0 | 1200 Hm³ | 10% V0 |

## � Casos de Uso y Ejemplos

### 📊 Análisis Determinístico Típico

```python
# Análisis histórico completo
python src/model.py
# Seleccionar opción 2: Todos los años (1960-2023)
# V0: 1400 Hm³

# Resultado esperado:
# - 64 períodos hidrológicos procesados
# - Tasa de éxito: ~95-98%
# - Energía total: ~450,000-500,000 MWh
# - Balance volumétrico histórico
```

### 🎲 Análisis de Riesgo Monte Carlo

```python
# Evaluación estocástica año crítico
python src/montecarlo.py
# Opción 1: Simulación año específico
# Año: 1998 (El Niño), V0: 1400, Iteraciones: 200

# Análisis esperado:
# - Percentil 5: ~4,500 MWh (escenario pesimista)
# - Media: ~6,800 MWh
# - Percentil 95: ~9,200 MWh (escenario optimista)
# - Tasa factibilidad: ~92%
```

### 📈 Evaluación Multi-Año

```python
# Robustez política de gestión
python src/montecarlo.py
# Opción 2: Simulación multi-año
# Período: 1990-2000, Trayectorias: 50

# Métricas de política:
# - Energía acumulada por trayectoria
# - Años con bajo rendimiento (<5000 MWh)
# - Correlación año-a-año de resultados
```

## 🛠️ Troubleshooting y Optimización

### ⚠️ Problemas Comunes

#### 1. Licencia Gurobi
```bash
# Error: "Model too large for size-limited license"
# Solución: Obtener licencia académica gratuita
# Registro en: https://www.gurobi.com/academia/academic-program-and-licenses/
```

#### 2. Memoria Insuficiente
```python
# Síntoma: Crash durante simulaciones multi-año
# Solución: Reducir número de iteraciones o años
n_iterations = 25  # En lugar de 100
n_years = 5        # En lugar de 10
```

#### 3. Datos Faltantes
```python
# El sistema maneja automáticamente datos faltantes
# Fallback a mediana histórica mensual
# Sin intervención requerida
```

### � Optimización de Rendimiento

#### Simulaciones Grandes
```python
# Para análisis extensivos, usar parámetros optimizados
simulator = MonteCarloSimulator()
results, summary = simulator.run_single_year(
    target_year=1985,
    V0=1400.0,
    n_iterations=500,    # Análisis robusto
    block_len=4,         # Bloques más largos = menos variabilidad
    noise_sigma=0.05,    # Menor ruido = mayor estabilidad
    verbose=False        # Desactivar salida detallada
)
```

#### Análisis Batch Programático
```python
# Análisis sistemático de múltiples años
years_critical = [1973, 1998, 2008, 2015]  # Años El Niño/La Niña
results_batch = {}

for year in years_critical:
    results, summary = simulator.run_single_year(
        target_year=year,
        V0=1400.0,
        n_iterations=100,
        verbose=False
    )
    results_batch[year] = summary.mean_energy
```

## 📚 Referencias Técnicas

### 📖 Documentación Adicional

- **Período hidrológico**: Ver `PERIODO_HIDROLOGICO_README.md`
- **Monte Carlo avanzado**: Ver `MONTECARLO_UNIFIED_README.md`
- **Pruebas rápidas**: `test_hydro_period.py`, `test_montecarlo_quick.py`

### 🔬 Metodologías Implementadas

1. **MILP con Gurobi**: Programación lineal entera mixta industrial
2. **Bootstrap por bloques**: Preservación de correlaciones estacionales
3. **Linearización Big-M**: Manejo de restricciones condicionales
4. **PWL (Piecewise Linear)**: Aproximación de curvas no lineales
5. **McCormick Relaxation**: Linearización de productos de variables

### 🎯 Validación y Testing

```bash
# Suite de pruebas rápidas
python test_hydro_period.py      # Validar período hidrológico
python test_montecarlo_quick.py  # Validar Monte Carlo (5 iteraciones)

# Ambos tests deben mostrar ✅ y completarse en <30 segundos
```

## 🎉 Logros del Proyecto

### ✅ Implementaciones Clave

- **Período hidrológico oficial**: Dic→Nov con recursividad volumétrica
- **Sistema unificado**: 2 interfaces interactivas principales
- **Bootstrap estacional**: Preserva correlaciones temporales naturales
- **Análisis de riesgo**: Percentiles, VaR, evaluación multi-año
- **MILP robusto**: Manejo de infactibilidades y big-M optimizado

### 🏆 Capacidades Avanzadas

- **Escalabilidad**: 1960-2023 (64 años) procesables
- **Flexibilidad**: Parámetros configurables por usuario
- **Robustez**: Manejo automático de datos faltantes
- **Usabilidad**: Interfaces intuitivas sin línea de comandos compleja
- **Extensibilidad**: Arquitectura modular para futuras mejoras

---

## 👥 Información del Proyecto

**Proyecto**: Capstone G20 - Modelo de Optimización Embalse del Laja  
**Universidad**: Pontificia Universidad Católica de Chile  
**Semestre**: 10° Semestre - 2025  
**Tecnologías**: Python, Gurobi, MILP, Monte Carlo, Bootstrap Estacional  

### 🛡️ Licencia y Uso

- **Uso académico**: Proyecto Capstone UC
- **Gurobi**: Licencia académica requerida
- **Datos**: Históricos sistema Laja (1960-2023)

**🌊 Sistema completo de optimización y análisis estocástico para la gestión avanzada del Embalse del Laja 🎯**