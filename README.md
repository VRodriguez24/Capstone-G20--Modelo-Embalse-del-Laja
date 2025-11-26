# 🏗️ Modelo de Optimización Híbrida del Embalse del Laja

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Gurobi](https://img.shields.io/badge/Gurobi-10.0.3-red.svg)](https://gurobi.com)
[![License](https://img.shields.io/badge/License-Academic-green.svg)](LICENSE)
[![Status](https://img.shields.io/badge/Status-Production-success.svg)](STATUS)

**Proyecto Capstone G20 - Pontificia Universidad Católica de Chile**  
*Facultad de Ingeniería - Departamento de Ingeniería Industrial y de Sistemas*  
*Optimización Estocástica para la Gestión Integral de Recursos Hídricos: El Laja*

---

## Descripción General

Este repositorio implementa un sistema de modelación y optimización para la operación del Embalse del Laja, integrando técnicas deterministas (MILP) y simulación estocástica (Monte Carlo). El objetivo es desarrollar un modelo de optimización integral para la operación del Sistema Embalse del Laja que maximice la eficiencia energética e hídrica bajo condiciones de incertidumbre, garantizando el cumplimiento de compromisos productivos y ambientales.

---

## Estructura del Proyecto

```
Capstone-G20--Modelo-Embalse-del-Laja/
├── src/                    # Código fuente principal
│   ├── model.py                # Modelo MILP general (Gurobi)
│   ├── caso_base.py            # Versión simplificada (déficit riego)
│   ├── montecarlo.py           # Simulación Monte Carlo híbrida
│   ├── analisis_sensibilidad_v0.py # Sensibilidad al volumen inicial
│   ├── kpi.py                  # Cálculo y reporte de KPIs
│   ├── filt_cota.py            # Modelado filtraciones (PWL)
│   ├── data_loader.py          # Carga y normalización de datos
│   ├── embalse.py              # Topología de la red hidráulica
│   └── interfaces UI           # Menús y helpers de usuario
├── data/                   # Datos históricos procesados
│   ├── Caudales_historicos_filtrado.csv
│   └── CaudalMax_filtrado.csv
├── pre-procesamiento/      # Scripts de limpieza y transformación de datos
│   ├── caudales_historicos.py
│   ├── caudales_max.py
│   └── data/ElToro.txt
├── resultados/             # Salidas, gráficos y reportes automáticos
└── README.md
```

---

## Flujo Lógico y Secuencia de Uso

1. **Pre-procesamiento de datos**
    - Limpieza y transformación de caudales históricos y parámetros técnicos de centrales.
    - Scripts: `caudales_historicos.py`, `caudales_max.py`
    - Salida: Archivos CSV en `data/`

2. **Definición del sistema**
    - Estructura de la red hidráulica y mapeo de datos.
    - Archivos: `embalse.py`, `data_loader.py`

3. **Modelos de optimización y simulación**
    - Modelo determinista general: `model.py`
    - Caso base (déficit riego): `caso_base.py`
    - Simulación estocástica: `montecarlo.py`
    - Análisis de sensibilidad: `analisis_sensibilidad_v0.py`

4. **Componentes técnicos**
    - Modelado de filtraciones no lineales: `filt_cota.py`
    - Cálculo de indicadores clave de desempeño: `kpi.py`

5. **Ejecución y análisis**
    - Interfaces interactivas para ejecutar modelos y visualizar resultados.
    - Resultados y visualizaciones en `resultados/`

---

## Ejecución Básica

1. Ejecutar los scripts de pre-procesamiento para generar los archivos de datos limpios.
2. Ejecutar el modelo deseado desde la carpeta `src/`:
    - Análisis histórico: `python caso_base.py`
    - Simulación Monte Carlo: `python montecarlo.py`
    - Sensibilidad V0: `python analisis_sensibilidad_v0.py`
3. Seguir las instrucciones de la interfaz para seleccionar parámetros y visualizar resultados.

---

## Requisitos

- Python 3.10+
- Gurobi 10.x (licencia académica)
- Paquetes: pandas, numpy, matplotlib, psutil, gurobipy

---

## Créditos y Licencia

Desarrollado para fines académicos en la Pontificia Universidad Católica de Chile.  
Uso restringido a investigación y docencia.

---

