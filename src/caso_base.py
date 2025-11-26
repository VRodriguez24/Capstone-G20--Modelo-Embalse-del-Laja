"""
==================================================================
CASO BASE: Minimización de Déficit de Primeros Regantes
==================================================================

Modelo simplificado basado en model.py enfocado exclusivamente en:
- Estructura operativa del embalse (balance hídrico, filtraciones)
- Gestión de primeros regantes (90 m³/s Tucapel, 47 m³/s Abanico)
- Sin generación energética ni segundos regantes

Función Objetivo: Minimizar el déficit máximo de primeros regantes

Variables principales:
- y: Flujos de conectividad/inyección (m³/s)
- x: Extracción por El Toro (m³/s)
- V: Volumen del embalse (Hm³)
- Filtr: Filtraciones naturales (m³/s)
- Def1: Déficit consolidado primeros regantes (Hm³/mes)

Basado en el modelo principal pero eliminando complejidades innecesarias.
"""

from typing import Tuple, Optional
import os
import gurobipy as gp
from gurobipy import GRB

# Módulos de configuración del embalse
from embalse import (
    NODES, ARCS, A_inyeccion, A_generacion, A_conectividad,
    A_vertimiento, IN, OUT
)
from data_loader import load_caudalmax, load_injections_for_year
from filt_cota import (
    build_pwl_final_segments,
    add_pwl_filtration_constraints
)


# ============================================================================
# CONFIGURACIÓN DEL MODELO
# ============================================================================
# Detectar rutas relativas
if os.path.exists("data/CaudalMax_filtrado.csv"):
    CAUDALMAX_CSV = "data/CaudalMax_filtrado.csv"
    INJ_CSV = "data/Caudales_historicos_filtrado.csv"
else:
    CAUDALMAX_CSV = "../data/CaudalMax_filtrado.csv"
    INJ_CSV = "../data/Caudales_historicos_filtrado.csv"

# Rango de años a correr (el script usará min/max e iterará entre ambos)
YEARS_HORIZON = [1960, 2023]

# Período hidrológico: Diciembre a Noviembre (30 nov = fin de temporada)
T = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

# Reglas de riego / ecológico (constantes, mismos valores para todo t)
TUCAPEL_MIN = 90.0     # m3/s
ABANICO_MIN = 47.0     # m3/s

# Curvas estacionales para 1° regantes (por mes 1..12)
# Tomadas de la Tabla N°2 (imagen). Valores entre 0 y 1
# NOTA: Los factores siguen siendo por mes calendario (1=Ene, 12=Dic)
FIRST_REGANTES_FACTOR = {
    1: 1.00, 2: 1.00, 3: 1.00, 4: 1.00,
    5: 0.00, 6: 0.00, 7: 0.00, 8: 0.00,
    9: 1.00, 10: 1.00, 11: 1.00, 12: 1.00
}

# Big-M y conversión
M = 6000                        # Big-M
EPS = 1e-3                      # epsilon para desambiguar límites
Conv = (86400 * 30) / 1e6       # m^3/s x mes -> Hm3

# Volúmenes embalse (Hm3) - Basado en ANEXO N°1
V_0 = 1400.0  # Volumen inicial por defecto
V_min = 0.0     # Volumen mínimo
V_max = 5582.0  # Volumen máximo

EMERGENCY_THRESHOLD = 0.90  # Umbral de emergencia (90% V_max)

# Configuración de filtraciones del embalse El Toro
FILTR_ARC: Tuple[str, str] = ("Embalse", "control_FiltracionesLaja")


# ============================================================================
# MODELO PRINCIPAL
# ============================================================================
def build_casobase_model_for_one_year(
    target_year: int,
    V0: Optional[float] = None,
    I_arc_override: Optional[dict] = None
) -> gp.Model:
    """
    Modelo simplificado para análisis de primeros regantes del Embalse Laja.

    Basado en model.py pero eliminando:
    - Generación energética (variables G, beta, arcos de generación)
    - Segundos regantes (Def2, d2)
    - Presupuestos y colchones (z, vinit_share)
    - Complejidad innecesaria

    Mantiene:
    - Estructura del embalse (balance hídrico, filtraciones PWL)
    - Primeros regantes (Tucapel 90 m³/s, Abanico 47 m³/s)
    - Control de vertimientos básico
    - Extracción por El Toro para cubrir déficits

    Args:
        target_year: Año objetivo
        V0: Volumen inicial (Hm³), por defecto V_0
        I_arc_override: Sobreescribir inyecciones (para Monte Carlo)

    Returns:
        Modelo de Gurobi configurado para minimizar déficit de 1R
    """
    # 1) Datos iniciales
    _, cap_max, _ = load_caudalmax(CAUDALMAX_CSV)
    # permitir sobreescribir inyecciones (útil para Monte Carlo)
    if I_arc_override is None:
        I_arc = load_injections_for_year(INJ_CSV, target_year)
    else:
        I_arc = I_arc_override
    V0_eff = V_0 if V0 is None else V0

    # Funciones auxiliares para balance hídrico
    def sum_in(n: str, t: int):
        """Flujo total entrante al nodo n en período t"""
        return (gp.quicksum(y[i, n, t] for i in IN[n]))

    def sum_out(n: str, t: int):
        """Flujo total saliente del nodo n en período t"""
        return (gp.quicksum(y[n, j, t] for j in OUT[n]))

    # Inyecciones externas (afluentes) por nodo y período
    A_ext = {(n, t): 0.0 for n in NODES for t in T}
    for (i, j) in A_inyeccion:
        for t in T:
            A_ext[(i, t)] += I_arc[(i, j, t)]  # Afluente natural

    # Etiquetas de inyección para cálculo de déficits
    inj_label = {(i, j): i.replace("afluente_", "").lower()
                 for (i, j) in A_inyeccion}
    excluir_lbls_tucapel = {"laja_i", "abanico", "eltoro"}

    def A_ab_t(t: int) -> float:
        """Aporte natural hacia Abanico en período t (Hm³/mes)"""
        for (i, j) in A_inyeccion:
            if inj_label[(i, j)] == "abanico":
                return I_arc[(i, j, t)] * Conv
        return 0.0

    def A_nat_tu_t(t: int) -> float:
        """Aportes naturales hacia Tucapel en período t (Hm³/mes)
        Excluye: laja_i, abanico, eltoro.
        """
        return sum(I_arc[(i, j, t)] * Conv for (i, j) in A_inyeccion
                   if inj_label[(i, j)] not in excluir_lbls_tucapel)

    # 2) Modelo
    m = gp.Model(f"caso_base{target_year}")

    # ========================================================================
    # VARIABLES
    # ========================================================================
    # Flujos hídricos básicos
    y = m.addVars(ARCS, T, lb=0.0, name="y")  # Conectividad/inyección
    # Flujos a través de arcos generadores (incluye El Toro y otros
    # arcos de "generación" aunque en este caso no se modela la
    # generación energética). Necesitamos crear `x` para TODOS los
    # arcos en A_generacion para poder referenciarlos en restricciones
    # (p. ej. activación `beta` y límites de capacidad).
    x = m.addVars(A_generacion, T, lb=0.0, name="x")  # Flujos en arcos generacion
    V = m.addVars(T, lb=V_min, ub=V_max, name="V")  # Volumen embalse
    Filtr = m.addVars(T, lb=0.0, name="Filtr")  # Filtraciones

    # Variables binarias de control
    beta = m.addVars(A_generacion, T, vtype=GRB.BINARY, name="beta")
    gamma = m.addVars(A_conectividad, T, vtype=GRB.BINARY, name="gamma")
    emergency = m.addVars(T, vtype=GRB.BINARY, name="emergency")

    # Primeros regantes - Abanico (47 m³/s base)
    DefTu = m.addVars(T, lb=0.0, name="DeficitTucapel")    # Q_T^D(t)
    ExcTu = m.addVars(T, lb=0.0, name="ExcedenteTucapel")  # Q_T^E(t)
    dAb = m.addVars(T, vtype=GRB.BINARY, name="deltaAb")

    # Primeros regantes - Tucapel (90 m³/s base)
    DefAb = m.addVars(T, lb=0.0, name="DeficitAbanico")    # Q_A^D(t)
    ExcAb = m.addVars(T, lb=0.0, name="ExcedenteAbanico")  # Q_A^E(t)
    dTu = m.addVars(T, vtype=GRB.BINARY, name="deltaTu")

    # Déficit consolidado primeros: min{DefTu, DefAb}
    # Déficit que El Toro debe compensar
    Def1 = m.addVars(T, lb=0.0, name="Deficit1erosRegantes")
    dMin = m.addVars(T, vtype=GRB.BINARY, name="deltaMin")

    # Variables auxiliares
    Vinit = m.addVar(lb=0.0, name="Vinit")
    MaxDef = m.addVar(lb=0.0, name="MaxDeficit")

    # ========================================================================
    # RESTRICCIONES
    # ========================================================================

    # Volumen inicial
    m.addConstr(Vinit == V0_eff, name="link_Vinit")

    # (R0) Inyección fija en A_inyeccion: y = I_arc
    for (i, j) in A_inyeccion:
        for t in T:
            m.addConstr(
                y[i, j, t] == I_arc[(i, j, t)],
                name=f"R0_inj_{i}_{j}_{t}"
            )

    # (R1) Balance hídrico del embalse
    for i, t in enumerate(T):
        if i == 0:  # Primer mes del período hidrológico (Diciembre)
            m.addConstr(
                V[t] == Vinit
                + (sum_in("Embalse", t) - sum_out("Embalse", t)) * Conv,
                name=f"R1_bal_emb_{t}"
            )
        else:
            prev_t = T[i-1]  # Mes anterior en secuencia hidrológica
            m.addConstr(
                V[t] == V[prev_t]
                + (sum_in("Embalse", t) - sum_out("Embalse", t)) * Conv,
                name=f"R1_bal_emb_{t}"
            )

    # (R2) Conservación de flujo en nodos (excepto sumideros/almacenamiento)
    SKIP_BALANCE = {"Embalse", "NodoMar", "SaltosLaja"}
    for n in NODES:
        if n in SKIP_BALANCE:
            continue
        for t in T:
            m.addConstr(
                sum_in(n, t) + A_ext[(n, t)] == sum_out(n, t),
                name=f"R2_bal_nodo_{n}_{t}"
            )

    # (R3) Capacidades máximas y control de vertimientos
    # Prioridad: usar El Toro primero, vertir solo si necesario
    #   - Vertir si arcos útiles saturados O embalse >= 90% V_max

    # R3a: Arcos de generación usan solo x (no y: y=0)
    for (i, j) in A_generacion:
        for t in T:
            m.addConstr(y[i, j, t] == 0.0, name=f"R3a_gen_y0_{i}{j}{t}")

    # R3b: Capacidad máxima en arcos de generación
    # beta[i,j,t] = 1 si arco alcanza capacidad (permite vertimiento)
    for (i, j) in A_generacion:
        if (i, j) in A_inyeccion:
            continue
        cap = cap_max.get((i, j))
        if cap is not None:
            for t in T:
                # Capacidad máxima
                m.addConstr(x[i, j, t] <= cap,
                            name=f"R3b_cap_gen_{i}{j}{t}")
                # Activar beta solo si flujo ≥ capacidad (indicador)
                m.addConstr(x[i, j, t] >= cap * beta[i, j, t])

    # R3c: Capacidad máxima en arcos de conectividad
    # gamma[i,j,t] = 1 si arco alcanza capacidad (permite vertimiento)
    for (i, j) in A_conectividad:
        cap = cap_max.get((i, j))
        if cap is not None:
            for t in T:
                # Capacidad máxima
                m.addConstr(y[i, j, t] <= cap,
                            name=f"R3c_cap_con_{i}{j}{t}")

                # Activar gamma solo si flujo ≥ capacidad (indicador)
                m.addConstr(y[i, j, t] >= cap * gamma[i, j, t])

    # R3d: Emergencia cuando V >= 90% V_max
    threshold = EMERGENCY_THRESHOLD * V_max
    for t in T:
        m.addConstr(V[t] >= threshold - M * (1 - emergency[t]),
                    name=f"R3d_emerg_lb_{t}")
        m.addConstr(V[t] <= threshold + M * emergency[t],
                    name=f"R3d_emerg_ub_{t}")

    # R3e: Control de vertimientos (activación condicionada)
    for (i, j) in A_vertimiento:
        for t in T:
            # Caso especial: Filtraciones del embalse
            if (i, j) == FILTR_ARC:
                # Siempre filtrar al menos Filtr[t]
                m.addConstr(y[i, j, t] >= Filtr[t],
                            name=f"R3e_filtr_min_{t}")
                # Solo exceder en emergencia
                m.addConstr(y[i, j, t] - Filtr[t] <= M * emergency[t],
                            name=f"R3e_filtr_max_{t}")
                continue

            # Caso general: vertir solo si arcos útiles saturados
            sat_indicators = []
            for (ii, jj) in ARCS:
                cap = cap_max.get((ii, jj))
                if cap is not None:
                    if (ii, jj) in A_generacion:
                        sat_indicators.append(beta[ii, jj, t])
                    elif (ii, jj) in A_conectividad:
                        sat_indicators.append(gamma[ii, jj, t])

            # Vertimiento permitido solo si:
            #   - algún arco útil saturado (sum sat_indicators >= 1)
            #   - o estamos en emergencia (emergency[t] = 1)
            if sat_indicators:
                m.addConstr(
                    y[i, j, t]
                    <= M * (
                        gp.quicksum(sat_indicators)
                        + emergency[t]
                    ),
                    name=f"R3e_vert_{i}_{j}_{t}"
                )
            else:
                # Si no hay arcos útiles, permitir vertimiento
                # solo en emergencia
                m.addConstr(
                    y[i, j, t] <= M * emergency[t],
                    name=f"R3e_vert_{i}_{j}_{t}"
                )

    # (R5) Filtraciones del embalse (PWL con 14 segmentos)
    m._y = y  # Requerido por add_pwl_filtration_constraints
    segments = build_pwl_final_segments(V_max=V_max)

    # Preparar variables de volumen previo por período
    Vprev_vars = {}
    for idx, t in enumerate(T):
        if idx == 0:  # Primer período (Diciembre)
            Vprev_vars[t] = Vinit
        else:
            prev_t = T[idx-1]  # Período anterior en secuencia hidrológica
            Vprev_vars[t] = V[prev_t]

    add_pwl_filtration_constraints(
        model=m,
        Filtr_vars=Filtr,
        Vprev_vars=Vprev_vars,
        time_periods=T,
        filtr_arc=FILTR_ARC,
        segments=segments,
        bigM=M,
        v_max=V_max
    )

    # ------------------------------------------------------------------
    # (R6) Déficits (MILP) linealizadas y cobertura por El Toro
    # ------------------------------------------------------------------
    # Se calculan dos tipos de déficits independientes:
    # 1) Déficit de primeros regantes (90 m³/s en Tucapel, 47 m³/s en Abanico)
    for t in T:
        # Factores estacionales
        first_factor = FIRST_REGANTES_FACTOR.get(t, 1.0)

        # Demandas estacionales (Hm3/mes)
        demanda_abanico = ABANICO_MIN * first_factor * Conv
        demanda_tucapel = TUCAPEL_MIN * first_factor * Conv

        # ------------------------------------------------------------------
        # (R6.1) PRIMEROS REGANTES: balances y modo déficit/excedente
        # ------------------------------------------------------------------
        # Balance Abanico (R6.1a): Filtr + A_ab + DefAb - ExcAb = D_Abanico
        m.addConstr(
            (Filtr[t] * Conv) + A_ab_t(t) + DefAb[t] - ExcAb[t] ==
            demanda_abanico, name=f"R6_1a_balance_Ab_{t}"
        )

        # Balance Tucapel (R6.1b): Filtr + A_nat + DefTu - ExcTu = D_Tucapel
        m.addConstr(
            (Filtr[t] * Conv) + A_nat_tu_t(t) + DefTu[t] - ExcTu[t] ==
            demanda_tucapel, name=f"R6_1b_balance_Tu_{t}"
        )

        # Modo déficit/excedente en Abanico (R6.1c)
        m.addConstr(DefAb[t] <= dAb[t] * M, name=f"R6_1c_DefAb_ub_{t}")
        m.addConstr(ExcAb[t] <= (1 - dAb[t]) * M, name=f"R6_1c_ExcAb_ub_{t}")

        # Modo déficit/excedente en Tucapel (R6.1d)
        # dTu=1 -> DefTu puede ser >0, ExcTu = 0
        # dTu=0 -> DefTu = 0, ExcTu puede ser >0
        m.addConstr(DefTu[t] <= dTu[t] * M, name=f"R6_1d_DefTu_ub_{t}")
        m.addConstr(ExcTu[t] <= (1 - dTu[t]) * M, name=f"R6_1d_ExcTu_ub_{t}")

        # ------------------------------------------------------------------
        # Déficit consolidado de primeros regantes (Def1 = min{DefAb, DefTu})
        # ------------------------------------------------------------------
        # Def1 debe ser menor o igual a ambos ( <= al min de los dos)
        m.addConstr(Def1[t] <= DefAb[t], name=f"R6_1e_Def1_le_Ab_{t}")
        m.addConstr(Def1[t] <= DefTu[t], name=f"R6_1f_Def1_le_Tu_{t}")

        # Linearización con dMin: forzar igualdad al mínimo
        m.addConstr(Def1[t] >= DefTu[t] - M * (1 - dMin[t]),
                    name=f"D1_eq_Tu_{t}")
        m.addConstr(Def1[t] >= DefAb[t] - M * dMin[t],
                    name=f"D1_eq_Ab_{t}")
        m.addConstr(DefTu[t] <= DefAb[t] + M * (1 - dMin[t]),
                    name=f"D1_sel_Tu_{t}")
        m.addConstr(DefAb[t] <= DefTu[t] + M * dMin[t],
                    name=f"D1_sel_Ab_{t}")

        # ------------------------------------------------------------------
        # (R6.4) COBERTURA DESDE EL TORO
        # ------------------------------------------------------------------
        # El Toro debe extraer agua para compensar déficits de riego.
        # El agua que pasa por El Toro SIEMPRE genera energía, pero se
        # contabiliza según su propósito:
        #   - Si cubre déficits → "agua para riego"
        #   - Si excede déficits → "agua para generación"
        m.addConstr(
            x["Embalse", "ElToro", t] * Conv >= Def1[t],
            name=f"R6_4a_cobertura_ElToro_{t}"
        )

    # (R7) Déficit máximo
    for t in T:
        m.addConstr(MaxDef >= Def1[t], name=f"R7_maxdef_{t}")

    # ========================================================================
    # FUNCIÓN OBJETIVO
    # ========================================================================
    # Minimizar déficit máximo (prioridad) + extracción total (desempate)
    extraccion_total = gp.quicksum(x["Embalse", "ElToro", t] * Conv for t in T)
    m.setObjective(1000 * MaxDef + extraccion_total, GRB.MINIMIZE)

    # ========================================================================
    # METADATA
    # ========================================================================
    m._y = y
    m._x = x
    m._V = V
    m._Filtr = Filtr
    m._Def1 = Def1
    m._MaxDef = MaxDef
    m._meta = {
        "Conv": Conv,
        "target_year": target_year,
        "V0": V0_eff,
        "demandas_mensuales": {
            "tucapel": {
                t: TUCAPEL_MIN * FIRST_REGANTES_FACTOR.get(t, 1.0) * Conv
                for t in T
            },
            "abanico": {
                t: ABANICO_MIN * FIRST_REGANTES_FACTOR.get(t, 1.0) * Conv
                for t in T
            }
        }
    }

    return m


# ============================================================================
# INTERFAZ PRINCIPAL
# ============================================================================
if __name__ == "__main__":
    """
    Interfaz para ejecutar el modelo caso base.

    Uso: python src/caso_base.py
    """
    from ui_caso_base import run

    run(
        build_model_func=build_casobase_model_for_one_year,
        years_horizon=YEARS_HORIZON,
        time_periods=T,
        conv_factor=Conv,
        model_name="Caso Base - Minimización Déficit Regantes",
        default_v0=V_0
    )
