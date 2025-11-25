"""
=========================================================
Modelo de Optimización del Embalse del Laja
=========================================================

Modelo MILP para la gestión óptima del Embalse Laja según Convenio 2017.

Características principales:
- Horizonte: Período hidrológico anual (Diciembre-Noviembre)
- Objetivo: Maximizar generación energética
- Restricciones: Balance hídrico, déficits de riego, presupuestos, caudales
  ecológicos
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
SALTOS_MIN = 7.0       # m3/s
SEGUNDOS_MIN = 53.0    # m3/s

# Curvas estacionales para 1°, 2° regantes y caudal ecologico (por mes 1..12)
# Tomadas de la Tabla N°2 (imagen). Valores entre 0 y 1
# NOTA: Los factores siguen siendo por mes calendario (1=Ene, 12=Dic)
FIRST_REGANTES_FACTOR = {
    1: 1.00, 2: 1.00, 3: 1.00, 4: 1.00,
    5: 0.00, 6: 0.00, 7: 0.00, 8: 0.00,
    9: 1.00, 10: 1.00, 11: 1.00, 12: 1.00
}
SECOND_REGANTES_FACTOR = {
    1: 1.00, 2: 1.00, 3: 0.80, 4: 0.50,
    5: 0.00, 6: 0.00, 7: 0.00, 8: 0.00,
    9: 0.30, 10: 0.65, 11: 0.85, 12: 1.00
}
SALTOS_REGANTES_FACTOR = {
    1: 1.00, 2: 1.00, 3: 0.00, 4: 0.00,
    5: 0.00, 6: 0.00, 7: 0.00, 8: 0.00,
    9: 0.00, 10: 0.00, 11: 0.00, 12: 0.50
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

# --- Colchones según configuración definitiva operacional ---
# (ANEXO 1 Convenio) Riego puede ser valor fijo en Hm3 o porcentaje
# Generación y Lago en %
COLCHONES = {
    # R=600 Hm³, G=5%, L=0%
    "Inferior": {"lo": 0.0, "hi": 1200.0, "shares": (600.0, 0.05, 0.0)},
    # R=40%, G=5%, L=55%
    "Transicion": {"lo": 1200.0, "hi": 1370.0, "shares": (0.40, 0.05, 0.55)},
    # R=40%, G=40%, L=20%
    "Intermedio": {"lo": 1370.0, "hi": 1900.0, "shares": (0.40, 0.40, 0.20)},
    # R=25%, G=65%, L=10%
    "Superior":   {"lo": 1900.0, "hi": 5582.0, "shares": (0.25, 0.65, 0.10)},
}
C_LABELS = list(COLCHONES.keys())

# Configuración de filtraciones del embalse El Toro
FILTR_ARC: Tuple[str, str] = ("Embalse", "control_FiltracionesLaja")


# =============================
# MODELO
# =============================
def build_model_for_one_year(
    target_year: int,
    V0: Optional[float] = None,
    I_arc_override: Optional[dict] = None,
) -> gp.Model:
    """
    Construye el modelo de optimización del Embalse para un año específico.

    Args:
        target_year: Año objetivo para la optimización
        V0: Volumen inicial opcional (Hm3). Si None, usa V_0 por defecto
        I_arc_override: Diccionario opcional para sobreescribir inyecciones

    Returns:
        gp.Model: Modelo de Gurobi configurado y listo para optimizar

    Función Objetivo:
        Maximiza generación energética total (suma de G[t] en MW).

    Presupuestos (R7) - Convenio 2017:
        - Riego: Agua del lago para cubrir déficits
          <= presupuesto_riego (600 Hm³ fijo en Inferior, % V0 otros)
        - Generación: Agua EXCEDENTE del lago (post-riego)
          <= presupuesto_gen (% V0 + tope 1200 Hm³ en Superior)
        - Lago: V_final >= % de V0 según colchón (recuperación)

    Nota: El flujo total por El Toro NO está limitado, solo sus componentes:
          Flujo_total = Riego + Generación (ambos con presupuestos)
    """

    # 1) Datos iniciales
    eta, cap_max, _ = load_caudalmax(CAUDALMAX_CSV)
    # permitir sobreescribir inyecciones (útil para Monte Carlo)
    if I_arc_override is None:
        I_arc = load_injections_for_year(INJ_CSV, target_year)
    else:
        I_arc = I_arc_override
    V0_eff = V_0 if V0 is None else V0

    # Funciones auxiliares para balance hídrico
    def sum_in(n: str, t: int):
        """Flujo total entrante al nodo n en período t"""
        return (gp.quicksum(y[i, n, t] for i in IN[n]) +
                gp.quicksum(x[i, n, t] for i in IN[n]
                            if (i, n) in A_generacion))

    def sum_out(n: str, t: int):
        """Flujo total saliente del nodo n en período t"""
        return (gp.quicksum(y[n, j, t] for j in OUT[n]) +
                gp.quicksum(x[n, j, t] for j in OUT[n]
                            if (n, j) in A_generacion))
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
    m = gp.Model(f"embalse_laja_{target_year}")

    # 3) Variables de decisión
    # Flujos hídricos
    y = m.addVars(ARCS, T, lb=0.0, name="y")  # Flujo conectividad (m³/s)
    x = m.addVars(A_generacion, T, lb=0.0, name="x")  # Flujo generación
    V = m.addVars(T, lb=V_min, ub=V_max, name="V")  # Volumen embalse (Hm³)
    Filtr = m.addVars(T, lb=0.0, name="Filtr")  # Filtraciones (m³/s)

    # Energía
    G = m.addVars(T, lb=0.0, name="G")  # Generación mensual (MW)

    # Variables binarias de control
    beta = m.addVars(A_generacion, T, vtype=GRB.BINARY, name="beta")
    gamma = m.addVars(A_conectividad, T, vtype=GRB.BINARY, name="gamma")
    emergency = m.addVars(T, vtype=GRB.BINARY, name="emergency")

    # Variables de déficit y excedentes de riego

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

    # Excedente primeros regantes (medido en Tucapel)
    Exc1 = m.addVars(T, lb=0.0, name="ExcedentePrimeros")

    # Segundos regantes (53 m³/s base)
    Def2 = m.addVars(T, lb=0.0, name="Deficit2dosRegantes")
    d2 = m.addVars(T, vtype=GRB.BINARY, name="delta2")

    # Volumen inicial y selección de colchón operativo
    Vinit = m.addVar(lb=0.0, name="Vinit")
    m.addConstr(Vinit == V0_eff, name="link_Vinit")

    z = m.addVars(C_LABELS, vtype=GRB.BINARY, name="z")
    m.addConstr(gp.quicksum(z[c] for c in C_LABELS) == 1,
                name="C_sum_z")

    # Linearización McCormick: vinit_share[c] = z[c] * Vinit
    vinit_share = m.addVars(C_LABELS, lb=0.0, ub=V_max, name="vinit_share")

    budget_gen_tope = m.addVar(lb=0.0, name="budget_gen_tope")

    # Activación de colchón según rango de Vinit
    for c in C_LABELS:
        lo = COLCHONES[c]["lo"]
        hi = COLCHONES[c]["hi"]
        eps_lo = EPS if c != "Inferior" else 0.0
        m.addConstr(Vinit >= (lo + eps_lo) - M * (1 - z[c]),
                    name=f"C_{c}_lo")
        m.addConstr(Vinit <= hi + M * (1 - z[c]),
                    name=f"C_{c}_hi")

    # 4) Restricciones

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

    # (R4) Generación energética mensual
    # G[t] = Σ{eta_e × x_e,t} donde eta en MW/(m³/s)
    for t in T:
        m.addConstr(G[t] == gp.quicksum(eta.get((i, j), 0.0) * x[i, j, t]
                                        for (i, j) in A_generacion),
                    name=f"R4_energy_{t}")

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
    # 2) Déficit de segundos regantes (53 m³/s, basado en excedente de Tucapel)
    for t in T:
        # Factores estacionales
        first_factor = FIRST_REGANTES_FACTOR.get(t, 1.0)
        second_factor = SECOND_REGANTES_FACTOR.get(t, 1.0)

        # Demandas estacionales (Hm3/mes)
        demanda_abanico = ABANICO_MIN * first_factor * Conv
        demanda_tucapel = TUCAPEL_MIN * first_factor * Conv
        demanda_2dos = SEGUNDOS_MIN * second_factor * Conv

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
        # (R6.2) EXCEDENTE DE PRIMEROS REGANTES
        # ------------------------------------------------------------------
        # Por definición del convenio, el excedente relevante para segundos
        # se mide en Tucapel: Exc1_t = ExcTu_t
        m.addConstr(Exc1[t] == ExcTu[t], name=f"R6_2_Exc1_eq_ExcTu_{t}")

        # ------------------------------------------------------------------
        # (R6.3) SEGUNDOS REGANTES: Def2 = max{0, D_2dos - Exc1}
        # ------------------------------------------------------------------
        # Linearización Big-M con variable binaria d2[t]
        m.addConstr(Def2[t] >= demanda_2dos - Exc1[t] - M * (1 - d2[t]),
                    name=f"R6_3a_D2_lb_{t}")
        m.addConstr(Def2[t] <= demanda_2dos - Exc1[t] + M * (1 - d2[t]),
                    name=f"R6_3b_D2_ub1_{t}")
        m.addConstr(Def2[t] <= M * d2[t],
                    name=f"R6_3c_D2_ub2_{t}")
        # Forzar d2=0 cuando no hay déficit (D_2dos <= Exc1)
        # Si d2=1, entonces Def2 debe ser >= D_2dos - Exc1 (positivo)
        m.addConstr(Def2[t] >= (demanda_2dos - Exc1[t]) * d2[t],
                    name=f"R6_3d_D2_force_d2_{t}")

        # ------------------------------------------------------------------
        # (R6.4) COBERTURA DESDE EL TORO
        # ------------------------------------------------------------------
        # El Toro debe extraer agua para compensar déficits de riego.
        # El agua que pasa por El Toro SIEMPRE genera energía, pero se
        # contabiliza según su propósito:
        #   - Si cubre déficits → "agua para riego"
        #   - Si excede déficits → "agua para generación"
        m.addConstr(
            x["Embalse", "ElToro", t] * Conv >= Def1[t] + Def2[t],
            name=f"R6_4a_cobertura_ElToro_{t}"
        )

    # =========================================================================
    # (R7) PRESUPUESTOS ANUALES SEGÚN CONVENIO 2017
    # =========================================================================
    # - Riego:    agua desde El Toro usada para cubrir déficits de regantes
    # - Generación: agua desde El Toro usada para generación (excedente)
    # - Lago:     volumen mínimo que debe quedar al final de la temporada
    #
    # Todos los presupuestos se fijan al inicio de la temporada
    # (Vinit = V_30nov) y se aplican sobre el ACUMULADO ANUAL (dic–nov)
    # =========================================================================

    # Linearización McCormick para vinit_share[c] = z[c] * Vinit
    for c in C_LABELS:
        # vinit_share[c] <= V_max * z[c]
        m.addConstr(vinit_share[c] <= V_max * z[c],
                    name=f"R7_McCormick_ub_{c}")
        # vinit_share[c] <= Vinit
        m.addConstr(vinit_share[c] <= Vinit,
                    name=f"R7_McCormick_link_{c}")
        # vinit_share[c] >= Vinit - V_max * (1 - z[c])
        m.addConstr(vinit_share[c] >= Vinit - V_max * (1 - z[c]),
                    name=f"R7_McCormick_lb_{c}")

    # -------------------------------------------------------------------------
    # Volúmenes anuales desde El Toro y destinados a riego / generación
    # -------------------------------------------------------------------------

    # Extracción anual desde El Toro (Hm³/año)
    extraccion_eltoro_anual = gp.quicksum(
        x["Embalse", "ElToro", t] for t in T
    ) * Conv

    # Agua destinada a riego = cobertura de déficits (Hm³/año)
    riego_anual = gp.quicksum(
        Def1[t] + Def2[t] for t in T
    )  # Ya está en Hm³/mes, suma anual

    # Agua destinada a generación = excedente desde El Toro (Hm³/año)
    generacion_anual = extraccion_eltoro_anual - riego_anual

    # -------------------------------------------------------------------------
    # Cálculo de presupuestos por colchón
    #   - Riego (R): Hm³ que PUEDEN DESTINARSE a riego
    #   - Generación (G): Hm³ que PUEDEN DESTINARSE a generación
    #   - Lago (L): Hm³ que DEBEN QUEDAR al final en el embalse
    # -------------------------------------------------------------------------

    budget_riego_terms = []
    budget_gen_terms = []
    budget_lago_terms = []

    for c in C_LABELS:
        r_share, g_share, l_share = COLCHONES[c]["shares"]

        # RIEGO y GENERACIÓN:
        #   - share > 1.0   => valor fijo en Hm³ (p.ej. 600 Hm³ en Inferior)
        #   - share <= 1.0  => porcentaje de Vinit (via vinit_share[c])
        for terms, share in [
            (budget_riego_terms, r_share),
            (budget_gen_terms, g_share),
        ]:
            if share > 1.0:
                # Volumen fijo (Hm³) si el colchón c está activo
                terms.append(share * z[c])
            else:
                # Porcentaje de Vinit (linealizado)
                terms.append(share * vinit_share[c])

        # LAGO: siempre porcentaje de Vinit (usando vinit_share[c])
        budget_lago_terms.append(l_share * vinit_share[c])

    # Expresiones finales de presupuesto
    budget_riego = gp.quicksum(budget_riego_terms)  # Hm³/año
    budget_gen = gp.quicksum(budget_gen_terms)      # Hm³/año
    budget_lago = gp.quicksum(budget_lago_terms)    # Hm³

    # -------------------------------------------------------------------------
    # Restricciones de presupuesto
    # -------------------------------------------------------------------------

    # (R7a) Presupuesto anual de riego
    # Agua usada para cubrir déficits no puede exceder el cupo del colchón
    m.addConstr(
        riego_anual <= budget_riego,
        name="R7a_presupuesto_riego"
    )

    # (R7b) Presupuesto anual de generación
    # Agua destinada a generación (excedente por El Toro) no puede
    # superar el presupuesto del colchón, con tope 1.200 Hm³ en Superior

    # Siempre: budget_gen_tope <= presupuesto calculado por colchón
    m.addConstr(
        budget_gen_tope <= budget_gen,
        name="R7b_gen_base"
    )

    # Si colchón Superior está activo => tope 1.200 Hm³
    m.addConstr(
        budget_gen_tope
        <= 1200.0 * z["Superior"] + M * (1 - z["Superior"]),
        name="R7b_gen_cap_superior"
    )

    # Para colchones distintos a Superior, no hay tope adicional:
    # fuerza que cuando z["Superior"] = 0, budget_gen_tope = budget_gen
    m.addConstr(
        budget_gen_tope >= budget_gen - M * z["Superior"],
        name="R7b_gen_otros"
    )

    # Restricción efectiva de presupuesto de generación
    m.addConstr(
        generacion_anual <= budget_gen_tope,
        name="R7b_presupuesto_generacion"
    )

    # (R7c) Reserva mínima de lago al final de la temporada (30 de noviembre)
    #       Solo se exige en el último período hidrológico (t = 11)
    m.addConstr(
        V[11] >= budget_lago,
        name="R7c_reserva_lago_final"
    )

    # (R8) Caudal ecológico mínimo en Saltos del Laja
    for t in T:
        # Aplicar factor estacional al caudal mínimo base
        saltos_factor = SALTOS_REGANTES_FACTOR.get(t, 1.0)
        saltos_min_t = SALTOS_MIN * saltos_factor
        m.addConstr(
            gp.quicksum(y[i, "SaltosLaja", t] for i in IN["SaltosLaja"])
            >= saltos_min_t,
            name=f"R8_saltos_min_{t}"
        )

    # Función objetivo: maximizar generación energética total
    # El límite R7a ya controla el uso de agua para riego
    m.setObjective(gp.quicksum(G[t] for t in T), GRB.MAXIMIZE)

    # Adjuntar variables y metadatos para postprocesamiento
    m._y = y
    m._x = x
    m._V = V
    m._Filtr = Filtr
    m._G = G
    m._emergency = emergency
    m._Def1 = Def1
    m._Def2 = Def2

    # Metadata del modelo
    m._meta = {
        "eta": eta,
        "cap_max": cap_max,
        "Conv": Conv,
        "A_generacion": A_generacion,
        "ARCS": ARCS,
        # Definiciones de colchones para referencia
        "colchones_def": COLCHONES,
        "colchon_labels": C_LABELS,
        "demandas_mensuales": {
            "tucapel": {
                t: TUCAPEL_MIN * FIRST_REGANTES_FACTOR.get(t, 1.0) * Conv
                for t in T
            },
            "abanico": {
                t: ABANICO_MIN * FIRST_REGANTES_FACTOR.get(t, 1.0) * Conv
                for t in T
            },
            "segundos": {
                t: SEGUNDOS_MIN * SECOND_REGANTES_FACTOR.get(t, 1.0) * Conv
                for t in T
            }
        }
    }

    return m


# =============================
# INTERFAZ PRINCIPAL
# =============================
if __name__ == "__main__":
    """
    Interfaz para ejecutar el modelo determinístico.
    Uso: python src/model.py
    """
    from ui_model import run

    run(
        build_model_func=build_model_for_one_year,
        years_horizon=YEARS_HORIZON,
        time_periods=T,
        conv_factor=Conv,
        model_name="Modelo Determinístico - Embalse del Laja",
        default_v0=V_0
    )
