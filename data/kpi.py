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

KPIs estratégicos implementados:
1. 🏗️ Tiempo en colchones operativos (%) - Tensión operativa
2. 💰 Uso de presupuestos riego/generación (%) - Eficiencia presupuestaria
3. 🏭 Participación El Toro en generación (%) - Dominancia energética
4. 🏗️ Factor de utilización (%) - Eficiencia hidráulica

Funciones principales:
- extract_kpis(model): Extrae KPIs de un modelo individual
- aggregate_kpis(kpis_list): Agrega múltiples KPIs (Monte Carlo/histórico)
- print_kpis(kpis, context): Imprime KPIs formateados
- export_kpis_csv(kpis, output_dir): Exporta a CSV
"""


def extract_kpis(model, include_detailed: bool = True) -> Dict[str, Any]:
    """
    Extrae KPIs estratégicos de un modelo optimizado.
    Función universal para análisis determinístico y Monte Carlo.

    Args:
        model: Modelo optimizado de Gurobi
        include_detailed: Si incluir KPIs detallados (compatibilidad)

    Returns:
        Diccionario con KPIs estratégicos y resultados del modelo
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
    Calcula los 4 KPIs estratégicos del modelo.
    Función interna para evitar duplicación de código.
    """
    from model import T, Conv, COLCHONES, C_LABELS

    # Extraer volumenes y cotas mensuales
    volumenes_mensuales = {}
    cota_mensual = {}
    for t in T:
        volumen_hm3 = model._V[t].x
        volumenes_mensuales[t] = volumen_hm3
        cota_mensual[t] = cota_from_volumen(volumen_hm3)

    # Calcular dependencia del lago (déficits)
    dependencia_lago_m3s = {}
    for t in T:
        deficit_total = 0.0
        # Sumar todos los déficits convertidos a m³/s
        for deficit_name in ["DeficitAbanico", "DeficitTucapel",
                            "Deficit2dosRegantes"]:
            try:
                deficit_var = model.getVarByName(f"{deficit_name}[{t}]")
                if deficit_var:
                    deficit_total += deficit_var.x / Conv
            except Exception:
                pass
        dependencia_lago_m3s[t] = deficit_total

    # KPI 1: Tiempo en colchones operativos
    tiempo_colchones = {c: 0 for c in C_LABELS}
    for t in T:
        volumen = volumenes_mensuales[t]
        for c in C_LABELS:
            lo = COLCHONES[c]["lo"]
            hi = COLCHONES[c]["hi"]
            eps = 1e-3 if c != "Inferior" else 0.0
            if lo + eps <= volumen <= hi:
                tiempo_colchones[c] += 1
                break

    tiempo_colchones_pct = {c: (count / len(T)) * 100.0
                           for c, count in tiempo_colchones.items()}

    # KPI 2: Uso de presupuestos
    uso_riego_hm3, uso_gen_hm3 = 0.0, 0.0
    presupuesto_riego, presupuesto_gen = 0.0, 0.0

    # Calcular uso real
    for t in T:
        # Riego: flujos desde embalse
        for j in ["control_Antuco", "control_Abanico", "control_Tucapel"]:
            try:
                var = model.getVarByName(f"y[Embalse,{j},{t}]")
                if var:
                    uso_riego_hm3 += var.x * Conv
            except Exception:
                pass

        # Generación: flujos hacia centrales
        for central in ["Antuco", "ElToro", "Abanico"]:
            try:
                var = model.getVarByName(f"x[Embalse,{central},{t}]")
                if var:
                    uso_gen_hm3 += var.x * Conv
            except Exception:
                pass

    # Calcular presupuestos según colchón activo
    v_inicial = model.getVarByName("Vinit")
    v_init_val = v_inicial.x if v_inicial else 1400.0

    for c in C_LABELS:
        z_var = model.getVarByName(f"z[{c}]")
        if z_var and z_var.x > 0.5:
            r_share, g_share, l_share = COLCHONES[c]["shares"]
            presupuesto_riego = (r_share if r_share > 1.0
                               else r_share * v_init_val)
            presupuesto_gen = (g_share if g_share > 1.0
                             else g_share * v_init_val)
            break

    uso_presupuestos_pct = {
        "riego": (uso_riego_hm3 / presupuesto_riego * 100.0
                 if presupuesto_riego > 0 else 0.0),
        "generacion": (uso_gen_hm3 / presupuesto_gen * 100.0
                      if presupuesto_gen > 0 else 0.0)
    }

    # KPI 3: Participación de El Toro
    energia_toro, energia_total = 0.0, 0.0
    try:
        from model import A_generacion
        eta = model._meta.get("eta", {}) if hasattr(model, '_meta') else {}

        for t in T:
            # Energía de El Toro
            x_toro_var = model.getVarByName(f"x[Embalse,ElToro,{t}]")
            if x_toro_var and ("Embalse", "ElToro") in eta:
                energia_toro += eta[("Embalse", "ElToro")] * x_toro_var.x

            # Energía total
            for (i, j) in A_generacion:
                x_var = model.getVarByName(f"x[{i},{j},{t}]")
                if x_var and (i, j) in eta:
                    energia_total += eta[(i, j)] * x_var.x
    except Exception:
        pass

    participacion_toro_pct = (energia_toro / energia_total * 100.0
                             if energia_total > 0 else 0.0)

    # KPI 4: Factor de utilización
    factor_utilizacion = {"sistema": 0.0}
    try:
        from model import A_generacion
        cap_max = (model._meta.get("cap_max", {})
                  if hasattr(model, '_meta') else {})

        uso_total, capacidad_total = 0.0, 0.0
        for (i, j) in A_generacion:
            if (i, j) in cap_max:
                uso_central = sum(
                    model.getVarByName(f"x[{i},{j},{t}]").x
                    for t in T
                    if model.getVarByName(f"x[{i},{j},{t}]")
                )
                capacidad_central = cap_max[(i, j)] * len(T)
                uso_total += uso_central
                capacidad_total += capacidad_central

        if capacidad_total > 0:
            factor_utilizacion["sistema"] = (uso_total / capacidad_total
                                           * 100.0)
    except Exception:
        pass

    return {
        # KPIs estratégicos
        'tiempo_colchones_%': tiempo_colchones_pct,
        'uso_presupuestos_%': uso_presupuestos_pct,
        'participacion_toro_%': participacion_toro_pct,
        'factor_utilizacion_%': factor_utilizacion,

        # Resultados del modelo
        'cota_mensual': cota_mensual,
        'dependencia_lago_m3s': dependencia_lago_m3s,
        'volumenes_mensuales': volumenes_mensuales
    }


def aggregate_kpis(kpis_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Agrega múltiples KPIs para análisis Monte Carlo o histórico.
    Función universal que calcula promedios y estadísticas.

    Args:
        kpis_list: Lista de diccionarios de KPIs

    Returns:
        Diccionario con KPIs agregados y estadísticas
    """
    if not kpis_list:
        return {}

    # Filtrar solo KPIs válidos
    valid_kpis = [kpi for kpi in kpis_list
                  if kpi.get('status') == 2 and kpi.get('tiempo_colchones_%')]

    if not valid_kpis:
        return {"error": "No hay KPIs válidos para agregar"}

    # Agregar KPI 1: Tiempo en colchones
    colchones_agregados = {}
    for colchon in ["Inferior", "Transicion", "Intermedio", "Superior"]:
        valores = [kpi['tiempo_colchones_%'].get(colchon, 0.0)
                  for kpi in valid_kpis]
        colchones_agregados[colchon] = np.mean(valores) if valores else 0.0

    # Agregar KPI 2: Uso de presupuestos
    riego_valores = [kpi['uso_presupuestos_%'].get('riego', 0.0)
                    for kpi in valid_kpis]
    gen_valores = [kpi['uso_presupuestos_%'].get('generacion', 0.0)
                  for kpi in valid_kpis]

    uso_presupuestos_agregado = {
        "riego": np.mean(riego_valores) if riego_valores else 0.0,
        "generacion": np.mean(gen_valores) if gen_valores else 0.0
    }

    # Agregar KPI 3: Participación El Toro
    toro_valores = [kpi.get('participacion_toro_%', 0.0)
                   for kpi in valid_kpis]
    participacion_toro_agregada = (np.mean(toro_valores)
                                  if toro_valores else 0.0)

    # Agregar KPI 4: Factor de utilización
    fu_valores = [kpi['factor_utilizacion_%'].get('sistema', 0.0)
                 for kpi in valid_kpis]
    factor_utilizacion_agregado = {
        "sistema": np.mean(fu_valores) if fu_valores else 0.0
    }

    # Agregar resultados del modelo
    cota_mensual_agregada = {}
    dependencia_agregada = {}

    # Promediar por mes
    from model import T
    for t in T:
        cotas_mes = [kpi['cota_mensual'].get(t, 0.0) for kpi in valid_kpis
                    if kpi.get('cota_mensual')]
        deps_mes = [kpi['dependencia_lago_m3s'].get(t, 0.0)
                   for kpi in valid_kpis
                   if kpi.get('dependencia_lago_m3s')]

        cota_mensual_agregada[t] = np.mean(cotas_mes) if cotas_mes else 0.0
        dependencia_agregada[t] = np.mean(deps_mes) if deps_mes else 0.0

    return {
        # KPIs estratégicos agregados
        'tiempo_colchones_%': colchones_agregados,
        'uso_presupuestos_%': uso_presupuestos_agregado,
        'participacion_toro_%': participacion_toro_agregada,
        'factor_utilizacion_%': factor_utilizacion_agregado,

        # Resultados agregados
        'cota_mensual': cota_mensual_agregada,
        'dependencia_lago_m3s': dependencia_agregada,

        # Metadata
        'num_kpis': len(valid_kpis),
        'num_total': len(kpis_list)
    }


def print_kpis(kpis: Dict[str, Any], context: str = "") -> None:
    """
    Imprime KPIs en formato legible.
    Función universal para cualquier tipo de análisis.

    Args:
        kpis: Diccionario con KPIs calculados
        context: Contexto del análisis (año, "histórico", "Monte Carlo", etc.)
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

    # KPI 2: Uso de presupuestos
    print("\n💰 KPI 2 - USO DE PRESUPUESTOS:")
    presupuestos = kpis.get('uso_presupuestos_%', {})
    sufijo = " (promedio histórico)" if "histórico" in context else ""
    print(f"   🌾 Riego:      {presupuestos.get('riego', 0):6.1f}%{sufijo}")
    print(f"   ⚡ Generación: "
          f"{presupuestos.get('generacion', 0):6.1f}%{sufijo}")

    # KPI 3: Participación El Toro
    print("\n🏭 KPI 3 - PARTICIPACIÓN EL TORO:")
    participacion = kpis.get('participacion_toro_%', 0.0)
    sufijo = " (promedio histórico)" if "histórico" in context else ""
    print(f"   ⚡ El Toro: {participacion:6.1f}% de energía total{sufijo}")

    # KPI 4: Factor de utilización
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
                      prefix: str = "kpis") -> List[str]:
    """
    Exporta KPIs a archivos CSV.
    Función universal para cualquier tipo de análisis.

    Args:
        kpis: Diccionario con KPIs calculados
        output_dir: Directorio de salida
        prefix: Prefijo para nombres de archivo

    Returns:
        Lista de archivos CSV generados
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    files_created = []

    if not kpis or 'tiempo_colchones_%' not in kpis:
        return files_created

    # Crear DataFrame con todos los KPIs
    data = []

    # KPI 1: Colchones
    for colchon, valor in kpis.get('tiempo_colchones_%', {}).items():
        data.append({
            'kpi_categoria': 'Tiempo_Colchones',
            'kpi_detalle': colchon,
            'valor': valor,
            'unidad': '%'
        })

    # KPI 2: Presupuestos
    for tipo, valor in kpis.get('uso_presupuestos_%', {}).items():
        data.append({
            'kpi_categoria': 'Uso_Presupuestos',
            'kpi_detalle': tipo,
            'valor': valor,
            'unidad': '%'
        })

    # KPI 3: Participación El Toro
    data.append({
        'kpi_categoria': 'Participacion_ElToro',
        'kpi_detalle': 'energia_total',
        'valor': kpis.get('participacion_toro_%', 0.0),
        'unidad': '%'
    })

    # KPI 4: Factor utilización
    for tipo, valor in kpis.get('factor_utilizacion_%', {}).items():
        data.append({
            'kpi_categoria': 'Factor_Utilizacion',
            'kpi_detalle': tipo,
            'valor': valor,
            'unidad': '%'
        })

    # Exportar KPIs principales
    if data:
        kpis_df = pd.DataFrame(data)
        kpis_file = output_path / f"{prefix}_kpis_estrategicos.csv"
        kpis_df.to_csv(kpis_file, index=False)
        files_created.append(str(kpis_file))

    # Exportar trayectoria de cota
    cota_data = kpis.get('cota_mensual', {})
    if cota_data:
        from model import T
        cota_df = pd.DataFrame({
            "mes": T,
            "cota_msnm": [cota_data.get(t, 0) for t in T]
        })
        cota_file = output_path / f"{prefix}_trayectoria_cota.csv"
        cota_df.to_csv(cota_file, index=False)
        files_created.append(str(cota_file))

    return files_created


def generate_historical_plots(kpis_historicos: List[Dict[str, Any]],
                             years: List[int],
                             output_dir: str = "resultados") -> List[str]:
    """
    Genera gráficos históricos de evolución.

    Args:
        kpis_historicos: Lista de KPIs por año
        years: Lista de años correspondientes
        output_dir: Directorio de salida

    Returns:
        Lista de archivos de gráfico generados
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

    # Guardar gráfico
    plot_file = output_path / "evolucion_historica_lago.png"
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
    
    # 2) KPI 2: Uso promedio de presupuestos
    uso_riego_historico = []
    uso_gen_historico = []
    
    for kpis in kpis_historicos:
        uso_presup = kpis.get("uso_presupuestos_%", {})
        uso_riego_historico.append(uso_presup.get("riego", 0.0))
        uso_gen_historico.append(uso_presup.get("generacion", 0.0))
    
    uso_presupuestos_promedio = {
        "riego": sum(uso_riego_historico) / len(uso_riego_historico) if uso_riego_historico else 0.0,
        "generacion": sum(uso_gen_historico) / len(uso_gen_historico) if uso_gen_historico else 0.0
    }
    
    # 3) KPI 3: Participación promedio de El Toro
    participacion_toro_historico = []
    
    for kpis in kpis_historicos:
        participacion_toro_historico.append(kpis.get("participacion_toro_%", 0.0))
    
    participacion_toro_promedio = (sum(participacion_toro_historico) / len(participacion_toro_historico)
                                  if participacion_toro_historico else 0.0)
    
    # 4) KPI 4: Factor de utilización promedio
    fu_sistema_historico = []
    fu_centrales_historico = {}
    
    for kpis in kpis_historicos:
        fu_data = kpis.get("factor_utilizacion_%", {})
        fu_sistema_historico.append(fu_data.get("sistema", 0.0))
        
        # Agregar datos por central
        for central, fu_val in fu_data.items():
            if central != "sistema":
                if central not in fu_centrales_historico:
                    fu_centrales_historico[central] = []
                fu_centrales_historico[central].append(fu_val)
    
    fu_sistema_promedio = (sum(fu_sistema_historico) / len(fu_sistema_historico)
                          if fu_sistema_historico else 0.0)
    
    fu_centrales_promedio = {}
    for central, valores in fu_centrales_historico.items():
        if valores:
            fu_centrales_promedio[central] = sum(valores) / len(valores)
    
    factor_utilizacion_promedio = {"sistema": fu_sistema_promedio, **fu_centrales_promedio}
    
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
        # KPIs estratégicos históricos
        "tiempo_colchones_%": tiempo_colchones_promedio,
        "uso_presupuestos_%": uso_presupuestos_promedio,
        "participacion_toro_%": participacion_toro_promedio,
        "factor_utilizacion_%": factor_utilizacion_promedio,
        
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
    
    # KPI 2: Uso de presupuestos
    print(f"\n💰 KPI 2 - USO PROMEDIO DE PRESUPUESTOS:")
    presupuestos = kpis_agregados.get("uso_presupuestos_%", {})
    uso_riego = presupuestos.get("riego", 0.0)
    uso_gen = presupuestos.get("generacion", 0.0)
    
    print(f"   🌾 Riego:      {uso_riego:6.1f}% (promedio histórico)")
    print(f"   ⚡ Generación: {uso_gen:6.1f}% (promedio histórico)")
    
    # KPI 3: Participación de El Toro
    print(f"\n🏭 KPI 3 - PARTICIPACIÓN PROMEDIO EL TORO:")
    participacion_toro = kpis_agregados.get("participacion_toro_%", 0.0)
    print(f"   ⚡ El Toro: {participacion_toro:6.1f}% de energía total (promedio histórico)")
    
    # KPI 4: Factor de utilización
    print(f"\n🏗️ KPI 4 - FACTOR DE UTILIZACIÓN PROMEDIO:")
    fu_data = kpis_agregados.get("factor_utilizacion_%", {})
    fu_sistema = fu_data.get("sistema", 0.0)
    print(f"   🏭 Sistema: {fu_sistema:6.1f}% (promedio histórico)")
    
    # Detalle por central si está disponible
    for central, fu in fu_data.items():
        if central != "sistema":
            print(f"   📍 {central}: {fu:6.1f}%")
    
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
