# 🌊 Modelo de Optimización del Embalse del Laja

![Python](https://img.shields.io/badge/python-3.8+-blue.svg)
![Gurobi](https://img.shields.io/badge/Gurobi-Optimizer-orange.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

## 📋 Descripción

Este proyecto implementa un modelo de optimización matemática para la gestión operativa del **Embalse El Toro** en el río Laja, Chile. El modelo utiliza programación lineal mixta entera (MILP) para maximizar la generación de energía eléctrica mientras respeta las restricciones hídricas, ecológicas y operacionales del sistema.

### 🎯 Objetivos

- **Maximizar la generación energética** del sistema hidroeléctrico
- **Gestionar eficientemente** los recursos hídricos del embalse
- **Cumplir con restricciones** de riego, ecológicas y operacionales
- **Optimizar la operación** considerando filtraciones y colchones operativos

## 🏗️ Arquitectura del Proyecto

```
Capstone-G20--Modelo-Embalse-del-Laja/
├── 📁 data/                          # Datos procesados
│   ├── Caudales_historicos_filtrado.csv
│   └── CaudalMax_filtrado.csv
├── 📁 pre-procesamiento/             # Scripts de preparación de datos
│   ├── caudales_historicos.py        # Procesamiento semanal → mensual
│   ├── caudales_max.py               # Procesamiento capacidades máximas
│   └── 📁 data/                      # Datos originales (Excel)
├── 📁 src/                           # Código fuente principal
│   ├── embalse.py                    # Definición de la red hídrica
│   ├── data_loader.py                # Carga y mapeo de datos
│   ├── filt_cota.py                  # Cálculos de filtraciones
│   └── model.py                      # Modelo de optimización principal
└── README.md                         # Este archivo
```

## 🔧 Instalación y Configuración

### Prerrequisitos

```bash
# Python 3.8 o superior
python --version

# Gurobi Optimizer (licencia académica requerida)
# Instalar desde: https://www.gurobi.com/academia/
```

### Dependencias

```bash
pip install pandas numpy gurobipy pathlib
```

### Configuración de Gurobi

1. Descargar e instalar Gurobi desde el sitio oficial
2. Obtener licencia académica gratuita
3. Configurar variables de entorno según documentación oficial

## 🚀 Uso del Sistema

### 1. Pre-procesamiento de Datos

Antes de ejecutar el modelo, procesa los datos originales:

```bash
# Procesar caudales históricos (semanal → mensual)
cd pre-procesamiento
python caudales_historicos.py

# Procesar capacidades máximas de centrales
python caudales_max.py
```

### 2. Ejecución del Modelo

```bash
cd src
python model.py
```

### 3. Configuración de Parámetros

Modifica los parámetros en `src/model.py`:

```python
# Rango de años a optimizar
YEARS_HORIZON = [1960, 2023]

# Volumen inicial del embalse (Hm³)
V_0 = 2500.0

# Restricciones ecológicas
TUCAPEL_MIN = 90.0    # m³/s
ABANICO_MIN = 47.0    # m³/s
SALTOS_MIN = 7.0      # m³/s
```

## 📊 Componentes del Sistema

### 🏭 Red Hídrica (`embalse.py`)

Define la topología completa del sistema:

- **Nodos**: 37 puntos de control incluyendo centrales, controles y afluentes
- **Arcos**: 4 tipos de conexiones hídricas
  - `A_inyeccion`: Aportes naturales (6 afluentes)
  - `A_generacion`: Turbinado para generación (8 centrales)
  - `A_conectividad`: Flujos de transporte (22 arcos)
  - `A_vertimiento`: Descargas y derrames (10 arcos)

```python
# Ejemplo de centrales de generación
A_generacion = [
    ("Embalse", "ElToro"),           # Central El Toro
    ("control_Abanico", "Abanico"),  # Central Abanico
    ("control_Antuco", "Antuco"),    # Central Antuco
    # ... más centrales
]
```

### 📈 Carga de Datos (`data_loader.py`)

Maneja la integración de dos fuentes de datos:

#### Capacidades Máximas
- **Archivo**: `CaudalMax_filtrado.csv`
- **Datos**: Rendimiento (MWh/m³s), caudal máximo, potencia máxima
- **Mapeo**: Nombres de centrales → arcos de generación

#### Caudales Históricos
- **Archivo**: `Caudales_historicos_filtrado.csv`  
- **Datos**: Series temporales mensuales de aportes (1960-2023)
- **Mapeo**: Estaciones → arcos de inyección

```python
# Ejemplo de mapeo robusto
CENTRAL_TO_GEN_ARC = {
    "ELTORO":   ("Embalse", "ElToro"),
    "ABANICO":  ("control_Abanico", "Abanico"),
    "ANTUCO":   ("control_Antuco", "Antuco"),
    # ...
}
```

### 💧 Filtraciones y Cotas (`filt_cota.py`)

Implementa el modelo físico del embalse:

#### Conversión Volumen-Cota
- **Tabla**: 71 puntos de calibración (1300-1370 msnm)
- **Método**: Interpolación lineal entre puntos

#### Modelo de Filtraciones
- **Función**: Polinomio de 4º grado basado en cota
- **Aproximación**: PWL (Piecewise Linear) con 4 segmentos
- **Alineación**: Segmentos corresponden a colchones operativos

```python
def filtraciones_from_cota(cota: float) -> float:
    """Polinomio de 4º grado para filtraciones"""
    a0 = -133471.205667
    a1 = 251.668765787
    a2 = -0.112314280288
    a3 = -0.000031180464
    a4 = 0.000000022628942
    return a0 + (a1*cota) + (a2*cota**2) + (a3*cota**3) + (a4*cota**4)
```

### 🎯 Modelo de Optimización (`model.py`)

#### Variables de Decisión
- `y[i,j,t]`: Flujos hídricos (m³/s)
- `x[i,j,t]`: Flujos de generación (m³/s)
- `V[t]`: Volumen del embalse (Hm³)
- `G[t]`: Generación energética (MWh)
- `Filtr[t]`: Filtraciones (m³/s)

#### Restricciones Principales

##### R1: Balance Hídrico del Embalse
```
V[t] = V[t-1] + (Entradas - Salidas) * Conversión_temporal
```

##### R2: Conservación de Flujo
```
Σ Entradas[n,t] = Σ Salidas[n,t]  ∀ nodo n, tiempo t
```

##### R3: Capacidades Máximas
```
x[i,j,t] ≤ Cap_max[i,j]  ∀ arco de generación
```

##### R4: Generación Energética
```
G[t] = Σ η[i,j] * x[i,j,t]  ∀ t
```

##### R5: Filtraciones PWL (MILP)
Implementación con variables binarias para aproximación lineal por tramos.

##### R6: Déficits Hídricos
Linearización MILP de funciones max{0, demanda - disponibilidad}:

```python
# Déficit Abanico
DefAb[t] = max{0, 47 - Filtr[t] - A_abanico[t]}

# Déficit Tucapel  
DefTu[t] = max{0, 90 - Filtr[t] - A_naturales[t]}
```

##### R7: Presupuestos por Colchón
Sistema de colchones operativos según ANEXO N°1:

| Colchón     | Rango (Hm³)    | Reparto (Riego, Gen, Lago) |
|-------------|----------------|-----------------------------|
| Inferior    | 1200 - 1370    | (50%, 5%, 0%)              |
| Transición  | 1370 - 1730    | (40%, 5%, 55%)             |
| Intermedio  | 1730 - 1900    | (40%, 40%, 20%)            |
| Superior    | 1900 - 3628    | (25%, 65%, 10%)            |

#### Función Objetivo
```
Maximizar: Σ G[t]  ∀ t ∈ T
```

## 📊 Pre-procesamiento de Datos

### Caudales Históricos (`caudales_historicos.py`)

**Transformación**: Datos semanales → Series mensuales completas

#### Proceso:
1. **Lectura**: Excel con 50 columnas, elimina 3 filas de encabezado
2. **Normalización**: Encabezados sin acentos, formato estándar
3. **Agregación**: Wide→Long, identifica meses, promedia por mes
4. **Completitud**: Panel mensual completo por central (1960-2023)
5. **Filtrado**: Solo centrales de interés del sistema

```python
CENTRALES_KEEP = [
    "ALTOPOLC", "ELTORO", "ABANICO", "ANTUCO", 
    "CANECOL", "TUCAPEL", "LAJA_I"
]
```

### Capacidades Máximas (`caudales_max.py`)

**Procesamiento**: Parámetros técnicos de centrales

#### Proceso:
1. **Normalización**: Encabezados estándar
2. **Conversión**: Formato numérico (coma→punto)
3. **Filtrado**: Rendimiento ≠ 1 (elimina casos especiales)
4. **Exportación**: Formato CSV estándar

## 🔍 Características Técnicas

### Modelado Matemático
- **Tipo**: Programación Lineal Mixta Entera (MILP)
- **Solver**: Gurobi Optimizer
- **Variables**: ~3000 por año optimizado
- **Restricciones**: ~1500 por año optimizado

### Aproximaciones PWL
- **Filtraciones**: 4 segmentos lineales
- **Volúmenes**: Rango operativo 1200-3628 Hm³
- **Precisión**: Error < 1% vs función original

### Linearización MILP
- **Déficits**: Variables binarias + Big-M
- **Colchones**: McCormick para productos bilineales
- **PWL**: Variables binarias para selección de segmentos

## 📈 Resultados y Análisis

El modelo optimiza para cada año del horizonte temporal:

### Métricas de Salida
- **Energía total generada** (MWh/año)
- **Volúmenes mensuales** del embalse
- **Flujos de generación** por central
- **Déficits hídricos** cubiertos
- **Cumplimiento** de restricciones ecológicas

### Interpretación
- **Soluciones óptimas**: Porcentaje de años con solución factible
- **Rango energético**: Variabilidad según condiciones hidrológicas
- **Gestión adaptativa**: Respuesta a años secos/húmedos

## 🤝 Contribuciones

### Estructura de Código
- **Modular**: Separación clara de responsabilidades
- **Documentado**: Docstrings y comentarios explicativos  
- **Robusto**: Validaciones y manejo de errores
- **Escalable**: Fácil extensión a nuevas funcionalidades

### Buenas Prácticas
- **PEP 8**: Estilo de código Python estándar
- **Type Hints**: Tipado explícito para mejor legibilidad
- **Testing**: Funciones de prueba integradas
- **Logging**: Salidas informativas durante ejecución

## 📚 Referencias Técnicas

### Metodología
- **Optimización Hidrotérmica**: Gestión de recursos hídricos
- **Programación Lineal Mixta**: Técnicas de modelado MILP
- **Aproximación PWL**: Linearización de funciones no lineales

### Datos del Sistema
- **ANEXO N°1**: Colchones operativos del embalse
- **Estudios DGA**: Caudales ecológicos mínimos
- **Datos operacionales**: Centrales hidroeléctricas del Laja

## 📞 Contacto

**Grupo 20 - Capstone**  
Universidad Católica de Chile  
Ingeniería Industrial

---

*Modelo desarrollado para optimización operativa del Sistema Hidroeléctrico del Río Laja, considerando restricciones ambientales, operacionales y de riego.*