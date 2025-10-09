from typing import Tuple, Optional, List
import gurobipy as gp
from gurobipy import GRB

# --- Conjuntos/red ---
from embalse import T, NODES, ARCS, A_inyeccion, A_generacion, IN, OUT
# --- Datos (CSV) ---
from data_loader import load_caudalmax, load_injections_for_year
# --- Filtraciones y cotas ---
from filt_cota import filtraciones_from_volumen, get_pwl_segments

# =============================
# CONFIGURACIÓN (parámetros)
# =============================
CAUDALMAX_CSV = "data/CaudalMax_filtrado.csv"
INJ_CSV = "data/Caudales_historicos_filtrado.csv"

# Rango de años a correr (el script usará min/max e iterará entre ambos)
YEARS_HORIZON = [1960, 1961]

# Reglas de riego / ecológico (constantes, mismos valores para todo t)
TUCAPEL_MIN = 90.0     # m3/s
ABANICO_MIN = 47.0     # m3/s
SALTOS_MIN = 7.0       # m3/s
SALTOS_MIN_T = {t: SALTOS_MIN for t in T}  # comodidad para indexar por t

# Big-M y conversión
M = 4000                        # Big-M (ajusta si hace falta)
EPS = 1e-3                      # epsilon para desambiguar límites
Conv = (86400 * 30) / 1e6       # m^3/s x mes -> Hm3

# Volúmenes embalse (Hm3) - Basado en ANEXO N°1
V_0 = 2500.0  # Volumen inicial por defecto (colchón "Superior")
V_min = 1200.0  # Volumen mínimo operativo (cota 1.300 msnm)
V_max = 3628.0  # Volumen máximo (cota de vertimiento 1.368 msnm)

# --- Colchones según ANEXO N°1 (rangos + shares=(riego,generación,lago)) ---
# Nota: Inferior representa volumen mínimo operativo, no volumen muerto
COLCHONES = {
    "Inferior":   {"lo": 1200.0, "hi": 1370.0, "shares": (0.50, 0.05, 0.00)},
    "Transicion": {"lo": 1370.0, "hi": 1730.0, "shares": (0.40, 0.05, 0.55)},
    "Intermedio": {"lo": 1730.0, "hi": 1900.0, "shares": (0.40, 0.40, 0.20)},
    "Superior":   {"lo": 1900.0, "hi": V_max,  "shares": (0.25, 0.65, 0.10)},
}
C_LABELS = list(COLCHONES.keys())

# Configuración de filtraciones del embalse El Toro
FILTR_ARC: Tuple[str, str] = ("Embalse", "control_FiltracionesLaja")

# Importar segmentos PWL desde módulo especializado
PWL_SEGMENTS = get_pwl_segments()


# =============================
# MODELO
# =============================
def build_model_for_one_year(
    target_year: int,
    V0: Optional[float] = None
) -> gp.Model:

    # 1) Datos iniciales
    eta, cap_max, _ = load_caudalmax(CAUDALMAX_CSV)
    I_arc = load_injections_for_year(INJ_CSV, target_year)
    V0_eff = V_0 if V0 is None else V0

    # Helpers de balance
    def sum_in(n: str, t: int):
        return gp.quicksum(y[i, n, t] for i in IN[n]) \
             + gp.quicksum(x[i, n, t] for i in IN[n] if (i, n) in A_generacion)

    def sum_out(n: str, t: int):
        return gp.quicksum(y[n, j, t] for j in OUT[n]) \
             + gp.quicksum(
                 x[n, j, t] for j in OUT[n] if (n, j) in A_generacion
             )
    A_ext = {(n, t): 0.0 for n in NODES for t in T}
    for (i, j) in A_inyeccion:
        for t in T:
            A_ext[(i, t)] = (
                I_arc[(i, j, t)]
            )  # fuente externa en el nodo i = afluente_*

    # Aportes naturales para déficit (labels de inyección)
    inj_label = {
        (i, j): i.replace("afluente_", "").lower()
        for (i, j) in A_inyeccion
    }
    excluir_lbls_tucapel = {"laja_i", "abanico", "eltoro"}

    def A_ab_t(t: int) -> float:
        # afluente hacia Abanico (arco afluente_Abanico -> control_Abanico)
        for (i, j) in A_inyeccion:
            if inj_label[(i, j)] == "abanico":
                return I_arc[(i, j, t)]
        return 0.0

    def A_nat_tu_t(t: int) -> float:
        # suma de afluentes “naturales” salvo {laja_i, abanico, eltoro}
        return sum(I_arc[(i, j, t)] for (i, j) in A_inyeccion
                   if inj_label[(i, j)] not in excluir_lbls_tucapel)

    # 2) Modelo
    m = gp.Model(f"embalse_laja_{target_year}")

    # 3) Variables
    y = m.addVars(ARCS, T, lb=0.0, name="y")
    x = m.addVars(A_generacion, T, lb=0.0, name="x")
    V = m.addVars(T, lb=V_min, ub=V_max, name="V")
    Filtr = m.addVars(T, lb=0.0, name="Filtr")
    G = m.addVars(T, lb=0.0, name="G")

    # Déficits y binarias
    DefAb = m.addVars(T, lb=0.0, name="DeficitAbanico")
    DefTu = m.addVars(T, lb=0.0, name="DeficitTucapel")
    dAb = m.addVars(T, vtype=GRB.BINARY, name="deltaAb")
    dTu = m.addVars(T, vtype=GRB.BINARY, name="deltaTu")

    # “Pseudo-variable” para V0 y selección de colchón z[c]
    Vinit = m.addVar(lb=0.0, name="Vinit")
    m.addConstr(Vinit == V0_eff, name="link_Vinit")

    z = m.addVars(C_LABELS, vtype=GRB.BINARY, name="z")
    m.addConstr(gp.quicksum(z[c] for c in C_LABELS) == 1, name="C_sum_z")

    # Selección por rangos con Big-M: lo_c + EPS <= Vinit <= hi_c si z[c]=1
    for c in C_LABELS:
        lo = COLCHONES[c]["lo"]
        hi = COLCHONES[c]["hi"]
        eps_lo = EPS if c != "Inferior" else 0.0   # no excluye 0 del inferior
        m.addConstr(Vinit >= (lo + eps_lo) - M * (1 - z[c]), name=f"C_{c}_lo")
        m.addConstr(Vinit <= hi + M * (1 - z[c]), name=f"C_{c}_hi")

    # 4) Restricciones

    # (R0) Inyección fija en A_inyeccion: y = I_arc
    for (i, j) in A_inyeccion:
        for t in T:
            m.addConstr(
                y[i, j, t] == I_arc[(i, j, t)],
                name=f"R0_inj_{i}_{j}_{t}"
            )

    # (R1) Balance hídrico del embalse
    for t in T:
        if t == T[0]:
            m.addConstr(
                V[t] == Vinit
                + (sum_in("Embalse", t) - sum_out("Embalse", t)) * Conv,
                name=f"R1_bal_emb_{t}"
            )
        else:
            m.addConstr(
                V[t] == V[t-1]
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

    # (R3) Capacidad máxima para arcos de generación
    for (i, j) in A_generacion:
        for t in T:
            m.addConstr(y[i, j, t] == 0.0, name=f"R3_y0_gen_{i}_{j}_{t}")
            cap = cap_max.get((i, j))
            if cap is not None:
                m.addConstr(x[i, j, t] <= cap, name=f"R3_cap_{i}_{j}_{t}")

    # (R4) Energía mensual: G_t = sum{ eta_e * x_e,t }
    for t in T:
        m.addConstr(G[t] == gp.quicksum(eta.get((i, j), 0.0) * x[i, j, t]
                                        for (i, j) in A_generacion),
                    name=f"R4_energy_{t}")

    # (R5) Filtraciones: PWL manual con variables binarias (MILP puro)
    f_i, f_j = FILTR_ARC

    # PWL simplificado: usar aproximación lineal directa por segmentos
    seg_labels = list(PWL_SEGMENTS.keys())
    delta = m.addVars(seg_labels, T, vtype=GRB.BINARY, name="delta_pwl")

    for t in T:
        # Igualar arco de filtración con variable
        m.addConstr(y[f_i, f_j, t] == Filtr[t], name=f"R5a_filtr_arc_{t}")

        # Exactamente un segmento debe estar activo
        m.addConstr(gp.quicksum(delta[k, t] for k in seg_labels) == 1,
                    name=f"R5b_one_segment_{t}")

        # Volumen anterior (para t=1 es Vinit, para t>1 es V[t-1])
        V_prev = Vinit if t == T[0] else V[t-1]

        # Restricciones de volumen por segmento activo
        for k in seg_labels:
            seg = PWL_SEGMENTS[k]
            # Si segmento k activo, volumen debe estar en su rango
            m.addConstr(V_prev >= seg["v_min"] * delta[k, t],
                        name=f"R5c_vol_min_{k}_{t}")
            m.addConstr(V_prev <= seg["v_max"] * delta[k, t] +
                        3628 * (1 - delta[k, t]),
                        name=f"R5d_vol_max_{k}_{t}")

        # PWL función: usar funciones originales evaluadas en puntos medios
        filtr_values = {}
        for k in seg_labels:
            seg = PWL_SEGMENTS[k]
            v_mid = (seg["v_min"] + seg["v_max"]) / 2
            filtr_values[k] = filtraciones_from_volumen(v_mid)

        # Función PWL: Filtr = suma de valores por segmento activo
        filtr_expr = gp.quicksum(
            filtr_values[k] * delta[k, t]
            for k in seg_labels
        )
        m.addConstr(Filtr[t] == filtr_expr, name=f"R5e_pwl_function_{t}")

    # (R6) Déficits (MILP) linealizadas y cobertura por El Toro
    for t in T:
        # Abanico: DefAb_t = max{0, 47 - Filtr_t - A_ab_t}
        expr_ab = ABANICO_MIN - Filtr[t] - A_ab_t(t)
        m.addConstr(DefAb[t] >= expr_ab, name=f"DAb_lb_{t}")
        m.addConstr(
            DefAb[t] <= expr_ab + M * (1 - dAb[t]), name=f"DAb_ub1_{t}"
            )
        m.addConstr(DefAb[t] <= M * dAb[t], name=f"DAb_ub2_{t}")

        # Tucapel: DefTu_t = max{0, 90 - Filtr_t - A_nat_tu_t}
        expr_tu = TUCAPEL_MIN - Filtr[t] - A_nat_tu_t(t)
        m.addConstr(DefTu[t] >= expr_tu, name=f"DTu_lb_{t}")
        m.addConstr(
            DefTu[t] <= expr_tu + M * (1 - dTu[t]), name=f"DTu_ub1_{t}"
            )
        m.addConstr(DefTu[t] <= M * dTu[t], name=f"DTu_ub2_{t}")

        # Cobertura desde Embalse via El Toro (suma de déficits)
        m.addConstr(x["Embalse", "ElToro", t] >= DefAb[t] + DefTu[t],
                    name=f"D_cover_by_ElToro_{t}")

    # (R7) Presupuestos anuales por colchón (Hm3) desde Embalse
    # (excluye filtración del riego)
    sum_riego_Hm3 = gp.quicksum(
        gp.quicksum(
            y["Embalse", j, t]
            for j in OUT["Embalse"]
            if ("Embalse", j) != FILTR_ARC
        ) * Conv
        for t in T
    )
    sum_gen_Hm3 = gp.quicksum(
        gp.quicksum(
            x["Embalse", j, t]
            for j in OUT["Embalse"]
            if ("Embalse", j) in A_generacion
        ) * Conv
        for t in T
    )
    # Variables auxiliares: vinit_share[c] = z[c] * Vinit
    vinit_share = m.addVars(C_LABELS, lb=0.0, ub=V_max, name="vinit_share")

    # Linearización McCormick: vinit_share[c] = z[c] * Vinit
    for c in C_LABELS:
        # Cuando z[c] = 0: vinit_share[c] = 0
        # Cuando z[c] = 1: vinit_share[c] = Vinit
        m.addConstr(vinit_share[c] <= V_max * z[c],
                    name=f"McCormick_vinit1_{c}")
        m.addConstr(vinit_share[c] >= 0 * z[c],
                    name=f"McCormick_vinit2_{c}")
        m.addConstr(vinit_share[c] <= Vinit - 0 * (1 - z[c]),
                    name=f"McCormick_vinit3_{c}")
        m.addConstr(vinit_share[c] >= Vinit - V_max * (1 - z[c]),
                    name=f"McCormick_vinit4_{c}")

    # Presupuestos lineales: multiplicar por constantes después
    budget_r = gp.quicksum(COLCHONES[c]["shares"][0] * vinit_share[c]
                           for c in C_LABELS)
    budget_g = gp.quicksum(COLCHONES[c]["shares"][1] * vinit_share[c]
                           for c in C_LABELS)

    m.addConstr(sum_riego_Hm3 <= budget_r, name="R8_riego_budget")
    m.addConstr(sum_gen_Hm3 <= budget_g, name="R8_gen_budget")

    # (R8) Mínimo ecológico en Saltos del Laja
    for t in T:
        m.addConstr(
            gp.quicksum(y[i, "SaltosLaja", t] for i in IN["SaltosLaja"])
            >= SALTOS_MIN_T[t],
            name=f"R9_saltos_min_{t}"
        )

    # 5) FO: Max energía total
    m.setObjective(gp.quicksum(G[t] for t in T), GRB.MAXIMIZE)
    return m


# =============================
# 🚀 Runner por rango [min,max]
# =============================
def run_years(years_horizon: List[int], V0: Optional[float] = None):
    y_min, y_max = min(years_horizon), max(years_horizon)
    total_years = y_max - y_min + 1

    print("\n🌊 === MODELO EMBALSE DEL LAJA ===")
    print(f"📅 Optimizando años: {y_min}-{y_max} ({total_years} años)")
    print(f"💧 Volumen inicial: {V0 if V0 else 'Automático'}\n")

    results = {}
    optimal_count = 0

    for i, y in enumerate(range(y_min, y_max + 1), 1):
        print(f"⚙️  Construyendo modelo año {y} ({i}/{total_years})...")
        m = build_model_for_one_year(y, V0=V0)

        print(f"🔍 Optimizando año {y}...")
        m.optimize()

        if m.Status == GRB.INFEASIBLE:
            print(f"❌ Año {y}: INFACTIBLE - generando diagnóstico")
            m.computeIIS()
            m.write(f"infeasible_{y}.ilp")
        elif m.Status == GRB.OPTIMAL:
            optimal_count += 1
            print(f"✅ Año {y}: ÓPTIMO - {m.ObjVal:.1f} MWh")
        else:
            print(f"⚠️  Año {y}: Status {m.Status}")

        obj_mwh = m.ObjVal if m.Status == GRB.OPTIMAL else None
        results[y] = {"status": m.Status, "obj_MWh": obj_mwh}

    # Resumen final
    print()
    print("🎯 === RESUMEN OPTIMIZACIÓN ===")
    print(f"✅ Soluciones óptimas: {optimal_count}/{total_years}")
    if optimal_count > 0:
        total_energy = sum(r["obj_MWh"] for r in results.values()
                           if r["obj_MWh"] is not None)
        avg_energy = total_energy / optimal_count
        print(f"⚡ Energía total: {total_energy:,.0f} MWh")
        print(f"📊 Promedio anual: {avg_energy:,.0f} MWh")
    print()

    return results


# =============================
# 🎬 Main
# =============================
if __name__ == "__main__":
    print("🔥 Iniciando optimización del Embalse del Laja...")
    results = run_years(YEARS_HORIZON, V0=3000.0)
    print("🏁 Optimización completada.")
