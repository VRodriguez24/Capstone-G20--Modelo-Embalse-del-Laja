from typing import Tuple, Optional, List
import gurobipy as gp
from gurobipy import GRB

# --- Conjuntos/red ---
from embalse import T, NODES, ARCS, A_inyeccion, A_generacion, IN, OUT
# --- Datos (CSV) ---
from data_loader import load_caudalmax, load_injections_for_year

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

# Volúmenes embalse (Hm3)
V_0 = 0.0
V_min = 1200.0
V_max = 3628.0

# --- Colchones (selección por V0 con Big-M y presupuestos anuales) ---
# Fuente de verdad única por colchón (rangos + shares=(riego,generación,lago))
COLCHONES = {
    "Inferior":   {"lo": 0.0,    "hi": 1200.0, "shares": (0.50, 0.05, 0.00)},
    "Transicion": {"lo": 1200.0, "hi": 1370.0, "shares": (0.40, 0.05, 0.55)},
    "Intermedio": {"lo": 1370.0, "hi": 1900.0, "shares": (0.40, 0.40, 0.20)},
    "Superior":   {"lo": 1900.0, "hi": V_max,  "shares": (0.25, 0.65, 0.10)},
}
C_LABELS = list(COLCHONES.keys())

# PWL de filtraciones: Filtr = a_k + b_k * Vprev, V ∈ [V_Lk, V_Uk]
FILTR_ARC: Tuple[str, str] = ("Embalse", "control_FiltracionesLaja")
a_k = {1: -477.789, 2: -483.720, 3: -707.724, 4: -1159.45}
b_k = {1: 0.378375, 2: 0.382877, 3: 0.550670, 4: 0.884665}
V_Lk = {1: 1300.0, 2: 1317.5, 3: 1335.0, 4: 1352.5}
V_Uk = {1: 1317.5, 2: 1335.0, 3: 1352.5, 4: 1370.0}


# Construimos nuestra función lineal por tramos
def _pwl_points_from_segments(V_Lk, V_Uk, a_k, b_k):
    ks = sorted(V_Lk.keys())     # [1, 2, 3, 4]
    xpts, ypts = [], []
    for k in ks:
        L, U = V_Lk[k], V_Uk[k]  # límites inferior/superior del tramo k
        tramo = [L, U] if k == ks[0] else [U]  # agrega L solo del primer tramo
        for V in tramo:
            y = a_k[k] + b_k[k]*V
            if xpts and abs(V - xpts[-1]) < 1e-9:
                ypts[-1] = y
            else:
                xpts.append(V)
                ypts.append(y)
    return xpts, ypts


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
    for n in NODES:
        if n in {"Embalse", "NodoMar", "SaltosLaja"}:
            continue
        for t in T:
            m.addConstr(
                sum_in(n, t) == sum_out(n, t),
                name=f"R2_bal_nodo_{n}_{t}"
            )

    # (R3) Capacidad máxima para arcos de generación
    for (i, j) in A_generacion:
        for t in T:
            m.addConstr(y[i, j, t] == 0.0, name=f"R3_y0_gen_{i}_{j}_{t}")
            cap = cap_max.get((i, j))
            if cap is not None:
                m.addConstr(x[i, j, t] <= cap, name=f"R3_cap_{i}_{j}_{t}")

    # (R4) Energía mensual: G_t = Σ eta_e * x_e,t
    for t in T:
        m.addConstr(G[t] == gp.quicksum(eta.get((i, j), 0.0) * x[i, j, t]
                                        for (i, j) in A_generacion),
                    name=f"R4_energy_{t}")

    # (R5) Filtraciones: igualar arco y PWL(Vprev)
    f_i, f_j = FILTR_ARC
    for t in T:
        m.addConstr(y[f_i, f_j, t] == Filtr[t], name=f"R5_filtr_arc_{t}")

    xpts, ypts = _pwl_points_from_segments(V_Lk, V_Uk, a_k, b_k)

    # Asegúrate de que las Vars están integradas antes de gen-constr:
    # m.update()

    for t in T:
        xv = V[t-1] if t != T[0] else Vinit   # <-- Var en ambos casos
        m.addGenConstrPWL(xv, Filtr[t], xpts, ypts, name=f"R5b_filtr_pwl_{t}")


    # (R6) Mínimos de entrada en Abanico (47) y Tucapel (90)
    for t in T:
        m.addConstr(
            (
                gp.quicksum(y[i, "Abanico", t] for i in IN["Abanico"])
                >= ABANICO_MIN
            ),
            name=f"R6a_abanico_min_{t}"
        )
        m.addConstr(
            (
                gp.quicksum(y[i, "Tucapel", t] for i in IN["Tucapel"])
                >= TUCAPEL_MIN
            ),
            name=f"R6b_tucapel_min_{t}"
        )

    # (R7) Déficits (MILP) y cobertura por El Toro
    for t in T:
        # Abanico: DefAb_t = max{0, 47 - Filtr_t - A_ab_t}
        expr_ab = ABANICO_MIN - Filtr[t] - A_ab_t(t)
        m.addConstr(DefAb[t] >= expr_ab, name=f"DAb_lb_{t}")
        m.addConstr(
            DefAb[t] <= expr_ab + M * (1 - dAb[t]),
            name=f"DAb_ub1_{t}"
        )
        m.addConstr(DefAb[t] <= M * dAb[t], name=f"DAb_ub2_{t}")

        # Tucapel: DefTu_t = max{0, 90 - Filtr_t - A_nat_tu_t}
        expr_tu = TUCAPEL_MIN - Filtr[t] - A_nat_tu_t(t)
        m.addConstr(DefTu[t] >= expr_tu, name=f"DTu_lb_{t}")
        m.addConstr(
            DefTu[t] <= expr_tu + M * (1 - dTu[t]),
            name=f"DTu_ub1_{t}"
        )
        m.addConstr(DefTu[t] <= M * dTu[t], name=f"DTu_ub2_{t}")

        # “El Toro” debe cubrir al menos el déficit de Tucapel
        m.addConstr(
            x["Embalse", "ElToro", t] >= DefTu[t],
            name=f"DTu_cover_by_ElToro_{t}"
        )

    # (R8) Presupuestos anuales por colchón (Hm3) desde Embalse
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
    share_r = gp.quicksum(COLCHONES[c]["shares"][0] * z[c] for c in C_LABELS)
    share_g = gp.quicksum(COLCHONES[c]["shares"][1] * z[c] for c in C_LABELS)

    m.addConstr(sum_riego_Hm3 <= share_r * Vinit, name="R8_riego_budget")
    m.addConstr(sum_gen_Hm3 <= share_g * Vinit, name="R8_gen_budget")

    # (R9) Mínimo ecológico en Saltos del Laja
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
# Runner por rango [min,max]
# =============================
def run_years(years_horizon: List[int], V0: Optional[float] = None):
    y_min, y_max = min(years_horizon), max(years_horizon)
    results = {}
    for y in range(y_min, y_max + 1):
        m = build_model_for_one_year(y, V0=V0)
        m.optimize()
        obj_mwh = m.ObjVal if m.Status == GRB.OPTIMAL else None
        results[y] = {"status": m.Status, "obj_MWh": obj_mwh}
        print(f"[{y}] status={m.Status}  obj_MWh={results[y]['obj_MWh']}")
    return results


# =============================
# Main
# =============================
if __name__ == "__main__":
    _ = run_years(YEARS_HORIZON, V0=None)
