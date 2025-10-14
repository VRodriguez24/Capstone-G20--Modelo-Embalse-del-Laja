from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

# Importar función de conversión de volumen a cota
from filt_cota import cota_from_volumen

"""
Módulo de KPIs para el Embalse del Laja
======================================

Este módulo implementa 4 KPIs estratégicos para evaluar la operación del Embalse del Laja:

📊 KPIs ESTRATÉGICOS:

1. 🏗️ TIEMPO EN COLCHONES OPERATIVOS (%)
   - Definición: Porcentaje del tiempo que el embalse opera en cada rango de volumen
   - Propósito: Medir tensión operativa y distribución de estados
   - Rangos: Inferior (0-1200), Transición (1200-1370), Intermedio (1370-1900), Superior (1900-5582 Hm³)
   - Interpretación: Mayor tiempo en colchones superiores = mayor disponibilidad de agua

2. 💰 USO DE PRESUPUESTOS RIEGO/GENERACIÓN (%)
   - Definición: Porcentaje de uso real vs presupuesto asignado según colchón activo
   - Propósito: Medir eficiencia en asignación de recursos hídricos
   - Cálculo: (Uso_real_anual / Presupuesto_asignado) × 100
   - Interpretación: >100% indica sobre-uso, <100% indica subutilización

3. 🏭 PARTICIPACIÓN EL TORO EN GENERACIÓN (%)
   - Definición: Porcentaje de energía generada por Central El Toro vs total del sistema
   - Propósito: Medir dominancia energética de la central principal
   - Cálculo: (Energía_ElToro / Energía_Total_Sistema) × 100
   - Interpretación: Mayor % indica mayor dependencia de El Toro para generación

4. 🏗️ FACTOR DE UTILIZACIÓN (%)
   - Definición: Porcentaje de uso real vs capacidad disponible ponderado por tamaño
   - Propósito: Medir eficiencia hidráulica del sistema de centrales
   - Cálculo: Promedio ponderado por capacidad instalada de cada central
   - Interpretación: Mayor % indica mejor aprovechamiento de infraestructura

📈 FUNCIONES PRINCIPALES:
- extract_kpis(model): Extrae KPIs de un modelo individual
- aggregate_kpis(kpis_list): Agrega múltiples KPIs (Monte Carlo/histórico)
- print_kpis(kpis, context): Imprime KPIs formateados
- export_kpis_csv(kpis, output_dir): Exporta a CSV

💡 METODOLOGÍA:
- Período hidrológico: Diciembre→Noviembre (12 meses)
- Colchones: Basados en volumen inicial y normativa DGA
- Presupuestos: Dinámicos según colchón activo al inicio del período
- Agregación: Promedios ponderados para análisis multi-año

✅ MEJORAS IMPLEMENTADAS v2.0:
- KPI 2: Cálculo mejorado incluyendo flujos downstream y déficits cubiertos
- KPI 4: Ponderación por capacidad instalada evitando sesgo de centrales pequeñas
- Comentarios: Documentación completa con definiciones, metodología y propósito
- Exportación: Formato CSV estructurado para análisis posterior
- Visualización: Gráficos históricos profesionales para reportes ejecutivos
"""


def extract_kpis(model, include_detailed: bool = True) -> Dict[str, Any]:
    """
    Extrae KPIs estratégicos de un modelo optimizado del Embalse del Laja.
    
    Esta función es universal y compatible con análisis determinísticos, Monte Carlo e históricos.
    Calcula los 4 KPIs estratégicos principales más métricas complementarias.

    Args:
        model: Modelo optimizado de Gurobi con variables del embalse
        include_detailed: Si incluir KPIs detallados (parámetro de compatibilidad)

    Returns:
        Dict[str, Any]: Diccionario con estructura:
            - 'status': Estado de optimización del modelo (2=óptimo)
            - 'obj_MWh': Valor objetivo (energía total generada)
            - 'V_end': Volumen final del embalse (Hm³)
            - 'tiempo_colchones_%': Dict con % tiempo en cada colchón
            - 'uso_presupuestos_%': Dict con % uso de presupuestos riego/generación
            - 'participacion_toro_%': % participación energética de El Toro
            - 'factor_utilizacion_%': Dict con factor utilización sistema/centrales
            - 'cota_mensual': Dict con cotas mensuales (msnm)
            - 'dependencia_lago_m3s': Dict con déficits mensuales (m³/s)
            - 'volumenes_mensuales': Dict con volúmenes mensuales (Hm³)
    """
    # Validación básica
    if not hasattr(model, 'status'):
        return {
            'status': -1,
            'obj_MWh': None,
            'V_end': None,
            'tiempo_colchones_%': {},
            'uso_presupuestos_%': {'riego': 0.0, 'generacion': 0.0},
            'participacion_toro_%': 0.0,
            'factor_utilizacion_%': {'sistema': 0.0},
            'cota_mensual': {},
            'dependencia_lago_m3s': {}
        }

    # KPIs básicos para compatibilidad
    basic_kpis = {
        'status': model.status,
        'obj_MWh': model.objVal if hasattr(model, 'objVal') else None,
        'V_end': None
    }

    # Extraer volumen final
    if hasattr(model, '_V'):
        from model import T
        final_month = max(T)
        basic_kpis['V_end'] = model._V[final_month].x

    # Si el modelo no es óptimo, retornar solo básicos
    if model.status != 2:
        basic_kpis.update({
            'tiempo_colchones_%': {},
            'uso_presupuestos_%': {'riego': 0.0, 'generacion': 0.0},
            'participacion_toro_%': 0.0,
            'factor_utilizacion_%': {'sistema': 0.0},
            'cota_mensual': {},
            'dependencia_lago_m3s': {}
        })
        return basic_kpis

    # Extraer KPIs estratégicos completos si es óptimo
    strategic_kpis = _calculate_strategic_kpis(model)
    basic_kpis.update(strategic_kpis)

    return basic_kpis


def _calculate_strategic_kpis(model) -> Dict[str, Any]:
    """
    Calcula los 4 KPIs estratégicos del modelo optimizado.
    
    Esta función interna implementa la lógica de cálculo de cada KPI según
    las mejores prácticas definidas para el Embalse del Laja.
    
    Args:
        model: Modelo optimizado de Gurobi con estado óptimo (status=2)
        
    Returns:
        Dict[str, Any]: KPIs estratégicos calculados
        
    KPIs calculados:
        1. Tiempo en colchones: Distribución temporal por rangos de volumen
        2. Uso de presupuestos: Eficiencia en asignación riego/generación  
        3. Participación El Toro: Dominancia energética de central principal
        4. Factor utilización: Eficiencia hidráulica del sistema
    """
    from model import T, Conv, COLCHONES, C_LABELS

    # PASO 1: Extraer datos base del modelo optimizado
    # ================================================
    
    # Extraer volúmenes mensuales y convertir a cotas
    volumenes_mensuales = {}
    cota_mensual = {}
    for t in T:
        volumen_hm3 = model._V[t].x  # Volumen del embalse en mes t (Hm³)
        volumenes_mensuales[t] = volumen_hm3
        # Convertir volumen a cota usando curva embalse El Toro
        cota_mensual[t] = cota_from_volumen(volumen_hm3)

    # Calcular dependencia del lago: suma de déficits que requieren apoyo del embalse
    # Déficits en Hm³/mes se convierten a m³/s para interpretación operacional
    dependencia_lago_m3s = {}
    for t in T:
        deficit_total = 0.0
        # Sumar déficits de todos los usuarios (regantes primarios y secundarios)
        for deficit_name in ["DeficitAbanico", "DeficitTucapel", "Deficit2dosRegantes"]:
            try:
                deficit_var = model.getVarByName(f"{deficit_name}[{t}]")
                if deficit_var:
                    # Convertir de Hm³/mes a m³/s: deficit_Hm³ / Conv = m³/s
                    deficit_total += deficit_var.x / Conv
            except Exception:
                pass
        dependencia_lago_m3s[t] = deficit_total

    # ================================================
    # KPI 1: TIEMPO EN COLCHONES OPERATIVOS ✓ CORRECTO
    # ================================================
    # Definición: % del tiempo que el embalse opera en cada rango de volumen
    # Metodología: Clasifica cada mes según volumen vs rangos definidos
    # Validación: Evita solapamientos con epsilon, suma total = 100%
    # Rangos (Hm³): Inferior(0-1200), Transición(1200-1370), Intermedio(1370-1900), Superior(1900-5582)
    
    tiempo_colchones = {c: 0 for c in C_LABELS}
    for t in T:
        volumen = volumenes_mensuales[t]
        # Clasificar mes según rango de volumen (solo uno por mes)
        for c in C_LABELS:
            lo = COLCHONES[c]["lo"]  # Límite inferior del colchón
            hi = COLCHONES[c]["hi"]  # Límite superior del colchón
            eps = 1e-3 if c != "Inferior" else 0.0  # Evita solapamiento en límites
            if lo + eps <= volumen <= hi:
                tiempo_colchones[c] += 1
                break  # Solo un colchón por mes

    # Convertir conteos a porcentajes
    tiempo_colchones_pct = {c: (count / len(T)) * 100.0
                            for c, count in tiempo_colchones.items()}

    # ================================================
    # KPI 2: USO DE PRESUPUESTOS ✅ MEJORADO
    # ================================================
    # Definición: % de uso real vs presupuesto asignado según colchón activo
    # Metodología: Suma TODOS los flujos de riego/generación vs límites por colchón
    # Mejora: Incluye flujos downstream y déficits cubiertos por el sistema
    # Fórmula: (Uso_real_anual_Hm³ / Presupuesto_asignado_Hm³) × 100
    
    uso_riego_hm3, uso_gen_hm3 = 0.0, 0.0  # Uso real acumulado anual
    presupuesto_riego, presupuesto_gen = 0.0, 0.0  # Presupuestos según colchón activo

    # Obtener arcos de generación del modelo
    A_gen = model._meta.get("A_generacion", []) if hasattr(model, '_meta') else []
    if not A_gen:
        try:
            from model import A_generacion
            A_gen = A_generacion
        except ImportError:
            A_gen = []

    # CALCULAR USO REAL ANUAL (suma de todos los meses)
    for t in T:
        # RIEGO: Flujos de agua destinados a riego (no generación)
        # Incluye: flujos directos desde embalse + agua para cubrir déficits downstream
        if hasattr(model, '_y'):
            arcos_y = set((i, j) for (i, j, _) in model._y.keys())
            for (i, j) in arcos_y:
                # 1) Flujos directos desde embalse (excepto generación)
                if i == "Embalse" and (i, j) not in A_gen:
                    try:
                        var = model._y[i, j, t]
                        if var:
                            uso_riego_hm3 += var.x * Conv  # m³/s → Hm³
                    except Exception:
                        pass
                        
                # 2) Flujos downstream para cubrir déficits de riego
                # Solo cuenta si efectivamente hay déficit siendo cubierto
                if j in ["control_Abanico", "control_Tucapel"] and i != "Embalse":
                    try:
                        var = model._y[i, j, t]
                        if var:
                            # Verificar si hay déficit activo en este punto
                            deficit_var = None
                            if j == "control_Abanico":
                                deficit_var = model.getVarByName(f"DeficitAbanico[{t}]")
                            elif j == "control_Tucapel": 
                                deficit_var = model.getVarByName(f"DeficitTucapel[{t}]")
                            
                            # Solo contar si deficit > 0 (hay necesidad real)
                            if deficit_var and deficit_var.x > 1e-6:
                                uso_riego_hm3 += var.x * Conv
                    except Exception:
                        pass

        # GENERACIÓN: Agua usada en todas las centrales hidroeléctricas
        if hasattr(model, '_x'):
            for (i, j) in A_gen:
                try:
                    var = model._x[i, j, t]
                    if var:
                        uso_gen_hm3 += var.x * Conv  # m³/s → Hm³
                except Exception:
                    pass
                except Exception:
                    pass

    # CALCULAR PRESUPUESTOS según colchón activo al inicio del período
    # Los presupuestos se determinan por el volumen inicial y colchón seleccionado
    v_inicial = model.getVarByName("Vinit")
    v_init_val = v_inicial.x if v_inicial else 1400.0  # Valor por defecto

    # Identificar colchón activo (z[c] = 1)
    for c in C_LABELS:
        z_var = model.getVarByName(f"z[{c}]")
        if z_var and z_var.x > 0.5:  # Colchón activo
            r_share, g_share, l_share = COLCHONES[c]["shares"]
            # Calcular presupuestos: valor fijo (>1.0) o porcentaje (≤1.0) del volumen inicial
            presupuesto_riego = (r_share if r_share > 1.0 else r_share * v_init_val)
            presupuesto_gen = (g_share if g_share > 1.0 else g_share * v_init_val)
            break

    # Calcular porcentajes de uso vs presupuesto
    uso_presupuestos_pct = {
        "riego": (uso_riego_hm3 / presupuesto_riego * 100.0 if presupuesto_riego > 0 else 0.0),
        "generacion": (uso_gen_hm3 / presupuesto_gen * 100.0 if presupuesto_gen > 0 else 0.0)
    }

    # ================================================
    # KPI 3: PARTICIPACIÓN DE EL TORO ✓ CORRECTO
    # ================================================
    # Definición: % de energía generada por Central El Toro vs total del sistema
    # Metodología: Usa factores de conversión eta (m³/s → MWh) correctamente
    # Propósito: Medir dominancia energética de la central principal del embalse
    # Fórmula: (Energía_ElToro / Energía_Total_Sistema) × 100
    
    energia_toro, energia_total = 0.0, 0.0  # Energía acumulada anual (MWh)
    try:
        from model import A_generacion
        # Factores de conversión: eta[arco] = MWh por m³/s
        eta = model._meta.get("eta", {}) if hasattr(model, '_meta') else {}

        for t in T:
            # Energía generada por El Toro en mes t
            x_toro_var = model.getVarByName(f"x[Embalse,ElToro,{t}]")
            if x_toro_var and ("Embalse", "ElToro") in eta:
                # Energía = factor_conversión × caudal_turbinado
                energia_toro += eta[("Embalse", "ElToro")] * x_toro_var.x

            # Energía total del sistema en mes t (suma de todas las centrales)
            for (i, j) in A_generacion:
                x_var = model.getVarByName(f"x[{i},{j},{t}]")
                if x_var and (i, j) in eta:
                    energia_total += eta[(i, j)] * x_var.x
    except Exception:
        pass

    # Calcular participación porcentual
    participacion_toro_pct = (energia_toro / energia_total * 100.0 if energia_total > 0 else 0.0)

    # ================================================
    # KPI 4: FACTOR DE UTILIZACIÓN ✅ MEJORADO
    # ================================================
    # Definición: % de uso real vs capacidad disponible ponderado por tamaño de central
    # Metodología: Promedio ponderado por capacidad instalada + detalle individual
    # Propósito: Medir eficiencia hidráulica del sistema evitando sesgo de centrales pequeñas
    # Mejora: Centrales grandes tienen mayor peso en el promedio del sistema
    # Fórmula: Σ(FU_central × Capacidad_central) / Σ(Capacidad_central)
    
    factor_utilizacion = {"sistema": 0.0}  # Resultado principal + detalles por central
    try:
        # Capacidades máximas por central (m³/s)
        cap_max = (model._meta.get("cap_max", {}) if hasattr(model, '_meta') else {})

        if cap_max and hasattr(model, '_x'):
            uso_total_ponderado, capacidad_total_ponderada = 0.0, 0.0
            
            # Calcular factor de utilización por central y agregar con ponderación
            for (i, j) in A_gen:
                if (i, j) in cap_max and cap_max[(i, j)] is not None:
                    capacidad_max = cap_max[(i, j)]  # Capacidad máxima (m³/s)
                    
                    # Uso real anual de la central (suma de todos los meses)
                    uso_central = sum(
                        model._x[i, j, t].x for t in T if (i, j, t) in model._x
                    )
                    
                    # Capacidad disponible total anual (capacidad × número_meses)
                    capacidad_anual = capacidad_max * len(T)
                    
                    # Factor de utilización individual de la central (0-1)
                    fu_central = (uso_central / capacidad_anual) if capacidad_anual > 0 else 0.0
                    
                    # Ponderar por capacidad instalada para el promedio del sistema
                    peso = capacidad_max  # Centrales más grandes tienen mayor peso
                    uso_total_ponderado += fu_central * peso
                    capacidad_total_ponderada += peso

            # Factor de utilización del sistema (promedio ponderado)
            if capacidad_total_ponderada > 0:
                factor_utilizacion["sistema"] = (uso_total_ponderado / capacidad_total_ponderada * 100.0)
                
            # Detalle individual por central para análisis específico
            factor_utilizacion["por_central"] = {}
            for (i, j) in A_gen:
                if (i, j) in cap_max and cap_max[(i, j)] is not None:
                    capacidad_max = cap_max[(i, j)]
                    uso_central = sum(
                        model._x[i, j, t].x for t in T if (i, j, t) in model._x
                    )
                    capacidad_anual = capacidad_max * len(T)
                    fu_central = (uso_central / capacidad_anual * 100.0) if capacidad_anual > 0 else 0.0
                    factor_utilizacion["por_central"][f"{i}-{j}"] = fu_central
                    
    except Exception:
        pass

    # Calcular totales para nuevos KPIs
    uso_real_agua = {"riego": uso_riego_hm3, "generacion": uso_gen_hm3}
    
    # Energía total del sistema
    energia_total = 0.0
    if hasattr(model, '_G'):
        for t in T:
            try:
                energia_total += model._G[t].x
            except Exception:
                pass

    return {
        # KPIs estratégicos
        'tiempo_colchones_%': tiempo_colchones_pct,
        'uso_presupuestos_%': uso_presupuestos_pct,
        'participacion_toro_%': participacion_toro_pct,
        'factor_utilizacion_%': factor_utilizacion,

        # Nuevos campos para KPIs mejorados
        'uso_real_agua_hm3': uso_real_agua,
        'energia_total_mwh': energia_total,

        # Resultados del modelo
        'cota_mensual': cota_mensual,
        'dependencia_lago_m3s': dependencia_lago_m3s,
        'volumenes_mensuales': volumenes_mensuales
    }


def aggregate_kpis(kpis_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Agrega múltiples KPIs para análisis Monte Carlo o histórico.
    
    Esta función es fundamental para consolidar resultados de múltiples simulaciones
    o años históricos en métricas promedio representativas del comportamiento del sistema.
    
    Casos de uso:
    - Análisis Monte Carlo: Promedia KPIs de N simulaciones estocásticas
    - Análisis histórico: Promedia KPIs de múltiples años (1960-2023)
    - Evaluación de sensibilidad: Consolida resultados de diferentes escenarios

    Args:
        kpis_list: Lista de diccionarios de KPIs individuales (uno por simulación/año)
                  Cada elemento debe contener los 4 KPIs estratégicos

    Returns:
        Dict[str, Any]: KPIs agregados con estructura:
            - Promedios de los 4 KPIs estratégicos
            - Trayectorias promedio mensuales (cota, dependencia)
            - Metadata de agregación (num_kpis, num_total)
            
    Metodología de agregación:
        - KPIs estratégicos: Promedio aritmético simple
        - Trayectorias mensuales: Promedio por mes específico
        - Filtrado: Solo incluye casos con optimización exitosa (status=2)
    """
    if not kpis_list:
        return {}

    # Filtrar solo KPIs válidos
    valid_kpis = [kpi for kpi in kpis_list
                  if kpi.get('status') == 2 and kpi.get('tiempo_colchones_%')]

    if not valid_kpis:
        return {"error": "No hay KPIs válidos para agregar"}

    # AGREGACIÓN DE KPIs ESTRATÉGICOS
    # ===============================
    
    # KPI 1: Promedio de tiempo en colchones por tipo
    colchones_agregados = {}
    for colchon in ["Inferior", "Transicion", "Intermedio", "Superior"]:
        valores = [kpi['tiempo_colchones_%'].get(colchon, 0.0) for kpi in valid_kpis]
        colchones_agregados[colchon] = np.mean(valores) if valores else 0.0

    # KPI 2: Promedio de uso de presupuestos por categoría
    riego_valores = [kpi['uso_presupuestos_%'].get('riego', 0.0) for kpi in valid_kpis]
    gen_valores = [kpi['uso_presupuestos_%'].get('generacion', 0.0) for kpi in valid_kpis]
    uso_presupuestos_agregado = {
        "riego": np.mean(riego_valores) if riego_valores else 0.0,
        "generacion": np.mean(gen_valores) if gen_valores else 0.0
    }

    # KPI 3: Promedio de participación de El Toro
    toro_valores = [kpi.get('participacion_toro_%', 0.0) for kpi in valid_kpis]
    participacion_toro_agregada = np.mean(toro_valores) if toro_valores else 0.0

    # KPI 4: Promedio de factor de utilización del sistema
    fu_valores = [kpi['factor_utilizacion_%'].get('sistema', 0.0) for kpi in valid_kpis]
    factor_utilizacion_agregado = {
        "sistema": np.mean(fu_valores) if fu_valores else 0.0
    }

    # AGREGACIÓN DE NUEVAS MÉTRICAS ABSOLUTAS
    # =======================================
    # Promedio de uso real de agua y eficiencia energética
    
    # Uso real de agua promedio
    riego_agua_valores = [
        kpi.get('uso_real_agua_hm3', {}).get('riego', 0.0)
        for kpi in valid_kpis
    ]
    gen_agua_valores = [
        kpi.get('uso_real_agua_hm3', {}).get('generacion', 0.0)
        for kpi in valid_kpis
    ]
    
    uso_real_agua_agregado = {
        "riego": np.mean(riego_agua_valores) if riego_agua_valores else 0.0,
        "generacion": np.mean(gen_agua_valores) if gen_agua_valores else 0.0
    }
    # Calcular total
    total_riego = uso_real_agua_agregado["riego"]
    total_gen = uso_real_agua_agregado["generacion"]
    uso_real_agua_agregado["total"] = total_riego + total_gen
    
    # Energía total promedio
    energia_valores = [kpi.get('energia_total_mwh', 0.0) for kpi in valid_kpis]
    energia_total_agregada = (np.mean(energia_valores) 
                             if energia_valores else 0.0)
    
    # Eficiencia energética promedio (MWh/Hm³)
    total_agua = uso_real_agua_agregado["total"]
    eficiencia_energetica_agregada = (energia_total_agregada / total_agua
                                     if total_agua > 0 else 0.0)

    # AGREGACIÓN DE TRAYECTORIAS MENSUALES
    # ===================================
    # Promedia valores por mes específico (conserva estacionalidad)
    
    cota_mensual_agregada = {}
    dependencia_agregada = {}

    from model import T
    for t in T:  # Para cada mes del período hidrológico
        # Cotas promedio por mes
        cotas_mes = [kpi['cota_mensual'].get(t, 0.0) for kpi in valid_kpis 
                    if kpi.get('cota_mensual')]
        cota_mensual_agregada[t] = np.mean(cotas_mes) if cotas_mes else 0.0
        
        # Dependencia promedio por mes
        deps_mes = [kpi['dependencia_lago_m3s'].get(t, 0.0) for kpi in valid_kpis
                   if kpi.get('dependencia_lago_m3s')]
        dependencia_agregada[t] = np.mean(deps_mes) if deps_mes else 0.0

    return {
        # KPIs estratégicos agregados (sistema viejo para compatibilidad)
        'tiempo_colchones_%': colchones_agregados,
        'uso_presupuestos_%': uso_presupuestos_agregado,
        'participacion_toro_%': participacion_toro_agregada,
        'factor_utilizacion_%': factor_utilizacion_agregado,

        # KPIs estratégicos nuevos (sistema mejorado)
        'uso_real_agua_hm3': uso_real_agua_agregado,
        'energia_total_mwh': energia_total_agregada,
        'eficiencia_energetica_mwh_hm3': eficiencia_energetica_agregada,

        # Resultados agregados
        'cota_mensual': cota_mensual_agregada,
        'dependencia_lago_m3s': dependencia_agregada,

        # Metadata
        'num_kpis': len(valid_kpis),
        'num_total': len(kpis_list)
    }


def print_kpis(kpis: Dict[str, Any], context: str = "") -> None:
    """
    Imprime KPIs en formato legible y organizado para análisis operacional.
    
    Esta función presenta los resultados de manera estructurada con emojis y formato
    que facilita la interpretación rápida de los indicadores estratégicos.
    
    Formatos soportados:
    - Análisis individual: KPIs de un año específico o simulación única
    - Análisis agregado: Promedios históricos o Monte Carlo
    - Comparativo: Múltiples contextos con sufijos explicativos
    
    Args:
        kpis: Diccionario con KPIs calculados (individual o agregado)
        context: Contexto del análisis para personalizar mensaje:
                - "año XXXX": Análisis de año específico
                - "histórico": Promedio de análisis histórico completo
                - "Monte Carlo": Promedio de simulaciones estocásticas
                - "": Sin contexto específico (genérico)
                
    Salida formateada:
        📊 Título con contexto y número de casos (si aplica)
        🏗️ KPI 1: Distribución por colchones con códigos de color
        💰 KPI 2: Eficiencia de uso de presupuestos
        🏭 KPI 3: Dominancia energética de El Toro
        🏗️ KPI 4: Eficiencia hidráulica del sistema
        📋 Resumen operacional: cotas, déficits, autosuficiencia
    """
    if not kpis or 'tiempo_colchones_%' not in kpis:
        print("⚠️ No hay KPIs válidos para mostrar")
        return

    # Título
    titulo = "📊 KPIs ESTRATÉGICOS"
    if context:
        titulo += f" - {context.upper()}"

    num_kpis = kpis.get('num_kpis')
    if num_kpis:
        titulo += f" ({num_kpis} casos)"

    print(f"\n{titulo}")
    print("=" * len(titulo))

    # KPI 1: Tiempo en colchones
    print("🏗️ KPI 1 - TIEMPO EN COLCHONES OPERATIVOS:")
    colchones_data = kpis.get('tiempo_colchones_%', {})
    for colchon, porcentaje in colchones_data.items():
        emoji = {"Inferior": "🔴", "Transicion": "🟡",
                "Intermedio": "🟢", "Superior": "🔵"}.get(colchon, "⚪")
        sufijo = " (promedio histórico)" if "histórico" in context else ""
        print(f"   {emoji} {colchon:11s}: {porcentaje:5.1f}%{sufijo}")

    # KPI 2: Uso real de agua (sistema mejorado) o presupuestos (compatibilidad)
    if 'uso_real_agua_hm3' in kpis:
        print("\n💰 KPI 2 - USO REAL PROMEDIO DE AGUA:")
        agua_data = kpis.get('uso_real_agua_hm3', {})
        sufijo = " (promedio histórico)" if "histórico" in context else ""
        print(f"   🌾 Riego:      {agua_data.get('riego', 0):7.1f} Hm³/año{sufijo}")
        print(f"   ⚡ Generación: {agua_data.get('generacion', 0):7.1f} Hm³/año{sufijo}")
        print(f"   🏭 Total:      {agua_data.get('total', 0):7.1f} Hm³/año{sufijo}")
    else:
        print("\n💰 KPI 2 - USO DE PRESUPUESTOS:")
        presupuestos = kpis.get('uso_presupuestos_%', {})
        sufijo = " (promedio histórico)" if "histórico" in context else ""
        print(f"   🌾 Riego:      {presupuestos.get('riego', 0):6.1f}%{sufijo}")
        print(f"   ⚡ Generación: "
              f"{presupuestos.get('generacion', 0):6.1f}%{sufijo}")

    # KPI 3: Participación El Toro
    print("\n🏭 KPI 3 - PARTICIPACIÓN PROMEDIO EL TORO:")
    participacion = kpis.get('participacion_toro_%', 0.0)
    sufijo = " (promedio histórico)" if "histórico" in context else ""
    print(f"   ⚡ El Toro: {participacion:6.1f}% de energía total{sufijo}")

    # KPI 4: Eficiencia energética (sistema mejorado) o factor utilización (compatibilidad)
    if 'eficiencia_energetica_mwh_hm3' in kpis:
        print("\n⚡ KPI 4 - EFICIENCIA ENERGÉTICA PROMEDIO:")
        eficiencia = kpis.get('eficiencia_energetica_mwh_hm3', 0.0)
        sufijo = " (promedio histórico)" if "histórico" in context else ""
        print(f"   🔋 Sistema:   {eficiencia:.2f} MWh/Hm³{sufijo}")
        print(f"   💡 Interpretación: {eficiencia:.2f} MWh por cada Hm³ de agua utilizada")
    else:
        print("\n🏗️ KPI 4 - FACTOR DE UTILIZACIÓN:")
        fu_data = kpis.get('factor_utilizacion_%', {})
        sufijo = " (promedio histórico)" if "histórico" in context else ""
        print(f"   🏭 Sistema: {fu_data.get('sistema', 0):6.1f}%{sufijo}")

    # Resultados del modelo
    print("\n📋 RESULTADOS DEL MODELO:")
    cota_data = kpis.get('cota_mensual', {})
    if cota_data:
        cota_promedio = sum(cota_data.values()) / len(cota_data)
        cota_min = min(cota_data.values())
        cota_max = max(cota_data.values())
        titulo_cota = ("Cota promedio histórica" if "histórico" in context
                      else "Cota promedio")
        print(f"   📏 {titulo_cota}: {cota_promedio:6.1f} msnm")
        titulo_rango = "Rango histórico" if "histórico" in context else "Rango"
        print(f"   📏 {titulo_rango}: [{cota_min:6.1f}, {cota_max:6.1f}] msnm")

    # Dependencia del lago
    dependencia = kpis.get('dependencia_lago_m3s', {})
    if dependencia:
        deficit_total = sum(dependencia.values())
        deficit_max = (max(dependencia.values())
                      if dependencia.values() else 0.0)
        meses_deficit = sum(1 for d in dependencia.values() if d > 1e-6)

        titulo_deficit = ("anual promedio" if "histórico" in context
                         else "total anual")
        print(f"   🚱 Déficit {titulo_deficit}: {deficit_total:8.2f} m³/s")
        titulo_max = ("máximo mensual promedio" if "histórico" in context
                     else "máximo mensual")
        print(f"   🚱 Déficit {titulo_max}: {deficit_max:8.2f} m³/s")
        titulo_meses = ("típicos con déficit" if "histórico" in context
                       else "con déficit")
        print(f"   🚱 Meses {titulo_meses}: {meses_deficit}/12")

        if deficit_max > 0:
            msg = ("históricamente requiere" if "histórico" in context
                  else "requiere")
            print(f"   ⚠️  Sistema {msg} apoyo del embalse")
        else:
            msg = ("históricamente autosuficiente" if "histórico" in context
                  else "autosuficiente")
            print(f"   ✅ Sistema {msg}")


def export_kpis_to_csv(kpis: Dict[str, Any],
                      output_dir: str = "resultados",
                      prefix: str = "kpis",
                      suffix: str = "") -> List[str]:
    """
    Exporta KPIs a archivos CSV estructurados para análisis posterior.
    
    Esta función genera archivos CSV normalizados que permiten:
    - Análisis estadístico con herramientas externas (R, Python, Excel)
    - Integración con sistemas de reporting empresarial
    - Comparación temporal y entre escenarios
    - Visualización avanzada con herramientas BI
    
    Archivos generados:
    1. {prefix}_kpis_estrategicos.csv: Los 4 KPIs principales en formato largo
    2. {prefix}_trayectoria_cota.csv: Evolución mensual de cotas del embalse
    
    Estructura CSV (KPIs):
        - kpi_categoria: Tipo de KPI (Tiempo_Colchones, Uso_Presupuestos, etc.)
        - kpi_detalle: Subcategoría específica (Inferior, riego, sistema, etc.)
        - valor: Valor numérico del KPI
        - unidad: Unidad de medida (%, m³/s, msnm)

    Args:
        kpis: Diccionario con KPIs calculados (individual o agregado)
        output_dir: Directorio de salida (se crea si no existe)
        prefix: Prefijo para nombres de archivo (ej: "2023", "historico", "montecarlo")
        suffix: Sufijo adicional para evitar sobreescribir archivos (ej: timestamp, configuración)

    Returns:
        List[str]: Lista de rutas completas de archivos CSV generados
        
    Nota: Compatible con KPIs individuales y agregados automáticamente
    """
    # VALIDACIÓN Y PREPARACIÓN
    # ========================
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)  # Crear directorio si no existe
    files_created = []

    if not kpis or 'tiempo_colchones_%' not in kpis:
        return files_created  # Sin KPIs válidos, no generar archivos

    # ESTRUCTURACIÓN DE DATOS EN FORMATO LARGO (TIDY DATA)
    # ===================================================
    # Formato normalizado: cada fila = una observación de un KPI específico
    data = []

    # KPI 1: Tiempo en colchones - Distribución por rango operativo
    for colchon, valor in kpis.get('tiempo_colchones_%', {}).items():
        data.append({
            'kpi_categoria': 'Tiempo_Colchones',
            'kpi_detalle': colchon,  # Inferior, Transicion, Intermedio, Superior
            'valor': valor,
            'unidad': '%'
        })

    # KPI 2: Uso de presupuestos - Eficiencia por tipo de uso
    for tipo, valor in kpis.get('uso_presupuestos_%', {}).items():
        data.append({
            'kpi_categoria': 'Uso_Presupuestos',
            'kpi_detalle': tipo,  # riego, generacion
            'valor': valor,
            'unidad': '%'
        })

    # KPI 3: Participación energética de El Toro
    data.append({
        'kpi_categoria': 'Participacion_ElToro',
        'kpi_detalle': 'energia_total',
        'valor': kpis.get('participacion_toro_%', 0.0),
        'unidad': '%'
    })

    # KPI 4: Factor de utilización - Eficiencia hidráulica
    for tipo, valor in kpis.get('factor_utilizacion_%', {}).items():
        data.append({
            'kpi_categoria': 'Factor_Utilizacion',
            'kpi_detalle': tipo,  # sistema, por_central (si existe)
            'valor': valor,
            'unidad': '%'
        })

    # EXPORTACIÓN DE ARCHIVO PRINCIPAL
    # ===============================
    if data:
        kpis_df = pd.DataFrame(data)
        # Construir nombre con sufijo si se proporciona
        base_name = f"{prefix}_kpis_estrategicos"
        if suffix:
            kpis_file = output_path / f"{base_name}_{suffix}.csv"
        else:
            kpis_file = output_path / f"{base_name}.csv"
        kpis_df.to_csv(kpis_file, index=False, encoding='utf-8')
        files_created.append(str(kpis_file))

    # EXPORTACIÓN DE TRAYECTORIA MENSUAL
    # =================================
    # Serie temporal de cotas para análisis estacional
    cota_data = kpis.get('cota_mensual', {})
    if cota_data:
        from model import T
        cota_df = pd.DataFrame({
            "mes": T,  # Período hidrológico: [12,1,2,...,11]
            "cota_msnm": [cota_data.get(t, 0) for t in T]
        })
        # Construir nombre con sufijo si se proporciona
        base_name = f"{prefix}_trayectoria_cota"
        if suffix:
            cota_file = output_path / f"{base_name}_{suffix}.csv"
        else:
            cota_file = output_path / f"{base_name}.csv"
        cota_df.to_csv(cota_file, index=False, encoding='utf-8')
        files_created.append(str(cota_file))

    return files_created


def generate_historical_plots(kpis_historicos: List[Dict[str, Any]],
                             years: List[int],
                             output_dir: str = "resultados",
                             suffix: str = "") -> List[str]:
    """
    Genera gráficos de evolución histórica para análisis visual de tendencias.
    
    Esta función produce visualizaciones profesionales que permiten identificar:
    - Tendencias temporales en la operación del embalse
    - Años críticos con baja disponibilidad hídrica
    - Patrones de dependencia del sistema respecto al embalse
    - Correlaciones entre disponibilidad y demandas hídricas
    
    Gráficos generados:
    1. Evolución del nivel del lago (cota promedio anual)
    2. Dependencia anual del embalse (déficits totales)
    
    Aplicaciones:
    - Informes ejecutivos y presentaciones
    - Análisis de riesgo hídrico multi-año
    - Evaluación de políticas de gestión
    - Identificación de períodos críticos históricos

    Args:
        kpis_historicos: Lista de KPIs calculados por año histórico
        years: Lista de años correspondientes (misma longitud que kpis_historicos)
        output_dir: Directorio donde guardar los gráficos PNG
        suffix: Sufijo adicional para evitar sobreescribir archivos

    Returns:
        List[str]: Lista de rutas completas de archivos PNG generados
        
    Formato de salida:
        - Resolución: 300 DPI (calidad publicación)
        - Formato: PNG con compresión optimizada
        - Tamaño: 14x10 pulgadas (ideal para presentaciones)
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    files_created = []

    if not kpis_historicos or not years:
        return files_created

    # Configurar matplotlib
    plt.rcParams['font.size'] = 10
    plt.rcParams['figure.figsize'] = (12, 8)

    # Gráfico de evolución histórica
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    # Extraer cotas promedio anuales
    cotas_anuales = []
    dependencias_anuales = []

    for kpis in kpis_historicos:
        cota_data = kpis.get('cota_mensual', {})
        cota_promedio = (sum(cota_data.values()) / len(cota_data)
                        if cota_data else 0.0)
        cotas_anuales.append(cota_promedio)

        dependencia_data = kpis.get('dependencia_lago_m3s', {})
        dependencia_total = (sum(dependencia_data.values())
                           if dependencia_data else 0.0)
        dependencias_anuales.append(dependencia_total)

    # Subplot 1: Evolución de cota
    ax1.plot(years, cotas_anuales, 'b-o', linewidth=2, markersize=4)
    ax1.set_title('Evolución Histórica del Nivel del Lago',
                  fontweight='bold')
    ax1.set_xlabel('Año')
    ax1.set_ylabel('Cota promedio [msnm]')
    ax1.grid(True, alpha=0.3)

    # Subplot 2: Dependencia del lago
    ax2.bar(years, dependencias_anuales, alpha=0.7, color='coral')
    ax2.set_title('Dependencia Anual del Embalse para Cubrir Déficits',
                  fontweight='bold')
    ax2.set_xlabel('Año')
    ax2.set_ylabel('Déficit total anual [m³/s]')
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()

    # Guardar gráfico con sufijo si se proporciona
    base_name = "evolucion_historica_lago"
    if suffix:
        plot_file = output_path / f"{base_name}_{suffix}.png"
    else:
        plot_file = output_path / f"{base_name}.png"
    plt.savefig(plot_file, dpi=300, bbox_inches='tight')
    plt.close()
    files_created.append(str(plot_file))

    return files_created


# Funciones de compatibilidad hacia atrás
def extract_kpis_historicos_agregados(
        kpis_historicos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Función de compatibilidad para análisis histórico."""
    return aggregate_kpis(kpis_historicos)


def print_kpis_historicos_agregados(kpis_agregados: Dict[str, Any]) -> None:
    """Función de compatibilidad para impresión histórica."""
    print_kpis(kpis_agregados, "histórico")


# Alias para compatibilidad hacia atrás
def extract_kpis_deterministico(model) -> Dict[str, Any]:
    """Función de compatibilidad que usa la nueva función general."""
    return extract_kpis(model)


# Alias para compatibilidad hacia atrás
def extract_kpis_montecarlo(models: List,
                          detailed_output: bool = False) -> Dict[str, Any]:
    """Función de compatibilidad que extrae KPIs de múltiples modelos."""
    kpis_list = [extract_kpis(model) for model in models]
    return aggregate_kpis(kpis_list)


def print_kpis_deterministico(kpis: Dict[str, Any], year: int) -> None:
    """Función de compatibilidad para impresión con año."""
    print_kpis(kpis, f"año {year}")


def print_kpis_montecarlo(kpis: Dict[str, Any],
                         target_year: Optional[int] = None) -> None:
    """Función de compatibilidad para impresión Monte Carlo."""
    context = "Monte Carlo"
    if target_year:
        context += f" año {target_year}"
    print_kpis(kpis, context)


def extract_kpis_historicos_agregados(kpis_historicos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Calcula KPIs estratégicos agregados para análisis histórico completo.
    
    Args:
        kpis_historicos: Lista de KPIs por año
        
    Returns:
        Diccionario con KPIs históricos agregados
    """
    if not kpis_historicos:
        return {}
    
    # 1) KPI 1: Tiempo promedio en colchones (agregado histórico)
    colchones_historicos = {"Inferior": [], "Transicion": [], "Intermedio": [], "Superior": []}
    
    for kpis in kpis_historicos:
        tiempo_colchones = kpis.get("tiempo_colchones_%", {})
        for colchon in colchones_historicos.keys():
            colchones_historicos[colchon].append(tiempo_colchones.get(colchon, 0.0))
    
    tiempo_colchones_promedio = {}
    for colchon, valores in colchones_historicos.items():
        if valores:
            tiempo_colchones_promedio[colchon] = sum(valores) / len(valores)
        else:
            tiempo_colchones_promedio[colchon] = 0.0
    
    # 2) KPI 2: Uso real promedio de agua (Hm³/año)
    uso_riego_real_historico = []
    uso_gen_real_historico = []
    
    for kpis in kpis_historicos:
        # Obtener uso real en Hm³/año directamente, no porcentajes
        uso_real = kpis.get("uso_real_agua_hm3", {})
        uso_riego_real_historico.append(uso_real.get("riego", 0.0))
        uso_gen_real_historico.append(uso_real.get("generacion", 0.0))
    
    uso_real_agua_promedio = {
        "riego": sum(uso_riego_real_historico) / len(uso_riego_real_historico) if uso_riego_real_historico else 0.0,
        "generacion": sum(uso_gen_real_historico) / len(uso_gen_real_historico) if uso_gen_real_historico else 0.0
    }
    
    # 3) KPI 3: Participación promedio de El Toro
    participacion_toro_historico = []
    
    for kpis in kpis_historicos:
        participacion_toro_historico.append(kpis.get("participacion_toro_%", 0.0))
    
    participacion_toro_promedio = (sum(participacion_toro_historico) / len(participacion_toro_historico)
                                  if participacion_toro_historico else 0.0)
    
    # 4) KPI 4: Eficiencia energética promedio (MWh/Hm³)
    eficiencia_energetica_historico = []
    
    for kpis in kpis_historicos:
        # Calcular eficiencia: Energía total / Agua total usada
        energia_total = kpis.get("energia_total_mwh", 0.0)
        agua_total = kpis.get("uso_real_agua_hm3", {})
        uso_total_hm3 = agua_total.get("riego", 0.0) + agua_total.get("generacion", 0.0)
        
        if uso_total_hm3 > 0:
            eficiencia = energia_total / uso_total_hm3
            eficiencia_energetica_historico.append(eficiencia)
    
    eficiencia_energetica_promedio = (
        sum(eficiencia_energetica_historico) / len(eficiencia_energetica_historico)
        if eficiencia_energetica_historico else 0.0
    )
    
    # Resultados del modelo (no KPIs) - promedios históricos
    cota_mensual_historica = {}
    dependencia_mensual_historica = {}
    
    # Promediar cotas y dependencias por mes
    from collections import defaultdict
    cota_sums = defaultdict(float)
    cota_counts = defaultdict(int)
    dependencia_sums = defaultdict(float)
    dependencia_counts = defaultdict(int)
    
    for kpis in kpis_historicos:
        # Cotas mensuales
        for mes, cota in kpis.get("cota_mensual", {}).items():
            cota_sums[mes] += cota
            cota_counts[mes] += 1
            
        # Dependencia del lago
        for mes, dep in kpis.get("dependencia_lago_m3s", {}).items():
            dependencia_sums[mes] += dep
            dependencia_counts[mes] += 1
    
    # Promedios por mes
    for mes in cota_sums.keys():
        cota_mensual_historica[mes] = cota_sums[mes] / cota_counts[mes]
        
    for mes in dependencia_sums.keys():
        dependencia_mensual_historica[mes] = dependencia_sums[mes] / dependencia_counts[mes]
    
    return {
        # KPIs estratégicos históricos mejorados
        "tiempo_colchones_%": tiempo_colchones_promedio,
        "uso_real_agua_hm3": uso_real_agua_promedio,
        "participacion_toro_%": participacion_toro_promedio,
        "eficiencia_energetica_mwh_hm3": eficiencia_energetica_promedio,
        
        # Resultados del modelo (históricos)
        "cota_mensual": cota_mensual_historica,
        "dependencia_lago_m3s": dependencia_mensual_historica,
        
        # Metadata
        "num_años": len(kpis_historicos)
    }


def print_kpis_historicos_agregados(kpis_agregados: Dict[str, Any]) -> None:
    """
    Imprime KPIs históricos agregados en formato legible.
    
    Args:
        kpis_agregados: Diccionario con KPIs históricos agregados
    """
    num_años = kpis_agregados.get("num_años", 0)
    if num_años == 0:
        return
        
    print(f"\n📊 KPIs ESTRATÉGICOS HISTÓRICOS ({num_años} años):")
    print("=" * 70)
    
    # KPI 1: Tiempo en colchones
    print("🏗️ KPI 1 - TIEMPO PROMEDIO EN COLCHONES OPERATIVOS:")
    colchones_data = kpis_agregados.get("tiempo_colchones_%", {})
    if colchones_data:
        for colchon, porcentaje in colchones_data.items():
            emoji = {"Inferior": "🔴", "Transicion": "🟡", 
                    "Intermedio": "🟢", "Superior": "🔵"}.get(colchon, "⚪")
            print(f"   {emoji} {colchon:11s}: {porcentaje:5.1f}% (promedio histórico)")
    
    # KPI 2: Uso real de agua
    print(f"\n� KPI 2 - USO REAL PROMEDIO DE AGUA:")
    uso_agua = kpis_agregados.get("uso_real_agua_hm3", {})
    uso_riego = uso_agua.get("riego", 0.0)
    uso_gen = uso_agua.get("generacion", 0.0)
    uso_total = uso_riego + uso_gen
    
    print(f"   🌾 Riego:      {uso_riego:6.1f} Hm³/año (promedio histórico)")
    print(f"   ⚡ Generación: {uso_gen:6.1f} Hm³/año (promedio histórico)")
    print(f"   🏭 Total:      {uso_total:6.1f} Hm³/año (promedio histórico)")
    
    # KPI 3: Participación de El Toro
    print(f"\n🏭 KPI 3 - PARTICIPACIÓN PROMEDIO EL TORO:")
    participacion_toro = kpis_agregados.get("participacion_toro_%", 0.0)
    print(f"   ⚡ El Toro: {participacion_toro:6.1f}% de energía total (promedio histórico)")
    
    # KPI 4: Eficiencia energética
    print(f"\n⚡ KPI 4 - EFICIENCIA ENERGÉTICA PROMEDIO:")
    eficiencia = kpis_agregados.get("eficiencia_energetica_mwh_hm3", 0.0)
    print(f"   🔋 Sistema: {eficiencia:6.2f} MWh/Hm³ (promedio histórico)")
    if eficiencia > 0:
        print(f"   � Interpretación: {eficiencia:.2f} MWh por cada Hm³ de agua utilizada")
    
    # Resultados adicionales (no KPIs)
    print(f"\n📋 RESULTADOS HISTÓRICOS DEL MODELO:")
    
    # Cota promedio histórica
    cota_data = kpis_agregados.get("cota_mensual", {})
    if cota_data:
        cota_promedio = sum(cota_data.values()) / len(cota_data)
        cota_min = min(cota_data.values())
        cota_max = max(cota_data.values())
        print(f"   📏 Cota promedio histórica: {cota_promedio:6.1f} msnm")
        print(f"   📏 Rango histórico: [{cota_min:6.1f}, {cota_max:6.1f}] msnm")
    
    # Dependencia histórica del lago
    dependencia = kpis_agregados.get("dependencia_lago_m3s", {})
    if dependencia:
        deficit_total_promedio = sum(dependencia.values())
        deficit_max_promedio = max(dependencia.values()) if dependencia.values() else 0.0
        meses_con_deficit = sum(1 for d in dependencia.values() if d > 1e-6)
        
        print(f"   🚱 Déficit anual promedio: {deficit_total_promedio:8.2f} m³/s")
        print(f"   🚱 Déficit máximo mensual promedio: {deficit_max_promedio:8.2f} m³/s")
        print(f"   🚱 Meses típicos con déficit: {meses_con_deficit}/12")
        
        if deficit_max_promedio > 0:
            print("   ⚠️  Sistema históricamente requiere apoyo del embalse")
        else:
            print("   ✅ Sistema históricamente autosuficiente")


# Ya se implementó arriba en la función principal
