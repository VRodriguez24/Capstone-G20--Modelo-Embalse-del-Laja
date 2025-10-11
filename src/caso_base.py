"""Caso base (diagnóstico de déficits) - LP simplificado

Este script construye y resuelve un LP anual (12 meses) para diagnosticar
déficits mínimos en Abanico (47 m3/s) y Tucapel (90 m3/s) respetando la
capacidad física del canal de Tucapel. Usa las inyecciones mensuales y
la función de filtraciones desde `filt_cota.py` tal como se describe en
el modelo general, pero sin balance completo ni variables binarias.

Salida: imprime un resumen en consola y guarda un CSV en `results/caso_base_{year}.csv`
que contiene r_TU_t, d_AB_t, d_TU_t y Filtr_t/Aportes locales.
"""
from typing import Dict, Tuple
import os
import csv

import gurobipy as gp
from gurobipy import GRB

# Conjuntos y utilidades del workspace
from embalse import T, A_inyeccion
from data_loader import load_injections_for_year
from filt_cota import filtraciones_from_volumen, cota_from_volumen
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from data_loader import load_caudalmax

# Constantes del caso base
ABANICO_MIN = 47.0
TUCAPEL_MIN = 90.0
# Capacidad física del canal Tucapel (m3/s)
CAP_TUCAPEL = 56.5

# Conversión volumen(m3/s * mes) -> Hm3 usada en el modelo general
Conv = (86400 * 30) / 1e6


def build_caso_base_model(year: int, V_prev_by_t: Dict[int, float], A_local: Dict[Tuple[str, int], float]):
    """Construye un modelo LP para el año indicado.

    Args:
        year: año (para referencia)
        V_prev_by_t: dict t->V_{t-1} en Hm3. Para t=1 se espera V_prev_by_t[1]=V0.
        A_local: dict (label, t) -> aporte m3/s. Debe contener al menos 'Abanico' y
                 los aportes intermedios para Tucapel (Antuco, Abanico, Rucue, Quilleco).
    Returns:
        Modelo Gurobi (no optimizado todavía)
    """
    m = gp.Model(f"caso_base_{year}")
    m.setParam('OutputFlag', 0)

    # Variables: r_TU_t, d_AB_t, d_TU_t
    r_TU = m.addVars(T, lb=0.0, name="r_TU")
    d_AB = m.addVars(T, lb=0.0, name="d_AB")
    d_TU = m.addVars(T, lb=0.0, name="d_TU")

    # Filtraciones dadas por V_prev_by_t: Filtr_t = f(V_{t-1})
    Filtr = {t: filtraciones_from_volumen(V_prev_by_t.get(t, V_prev_by_t.get(1, 1200.0))) for t in T}

    # Objetivo: minimizar suma de déficits
    m.setObjective(gp.quicksum(d_AB[t] + d_TU[t] for t in T), GRB.MINIMIZE)

    # Restricciones CB1: Filtr_t + A_Abanico_t + d_AB_t >= 47
    for t in T:
        a_ab = A_local.get(("Abanico", t), 0.0)
        m.addConstr(Filtr[t] + a_ab + d_AB[t] >= ABANICO_MIN, name=f"CB1_abanico_{t}")

    # Restricciones CB2: Phi_t + r_TU_t + d_TU_t >= 90
    # Phi_t = Filtr_t + A_Antuco + A_Abanico + A_Rucue + A_Quilleco
    for t in T:
        phi = Filtr[t]
        for lab in ("Antuco", "Abanico", "Rucue", "Quilleco"):
            phi += A_local.get((lab, t), 0.0)

        # Además imponemos la capacidad física del canal como un upper bound en r_TU
        m.addConstr(r_TU[t] <= CAP_TUCAPEL, name=f"cap_rTU_{t}")
        m.addConstr(phi + r_TU[t] + d_TU[t] >= TUCAPEL_MIN, name=f"CB2_tucapel_{t}")

    # Adjuntar metadatos para postprocesamiento
    m._Filtr = Filtr
    m._A_local = A_local
    m._r_TU = r_TU
    m._d_AB = d_AB
    m._d_TU = d_TU

    return m


def run_caso_base_for_year(year: int, V0: float = 1400.0):
    """Carga datos del CSV y corre el caso base para `year`.

    Estrategia: usar `load_injections_for_year` para obtener I_arc y mapear a
    aportes locales por etiqueta (Antuco, Abanico, Rucue, Quilleco,...).
    Para V_{t-1} se usa una aproximación simple: todo V_prev = V0 (constante)
    o se puede pasar un dict con variación mensual.
    """
    # Cargar inyecciones mensuales (I_arc[(i,j,t)])
    I_arc = load_injections_for_year("data/Caudales_historicos_filtrado.csv", year)

    # Mapear aportes locales por etiqueta (usando las claves de embalse CENTRAL_TO_INJ_ARC
    # definidas en data_loader). Aquí esperamos los nombres sin prefijo 'afluente_'
    # Ej: A_local[("Abanico", t)] = caudal m3/s que llega a control_Abanico desde afluente_Abanico
    A_local = {}
    for (i, j) in A_inyeccion:
        # etiqueta del nodo receptor: por ejemplo control_Abanico -> Abanico
        # si j empieza con 'control_' removemos prefijo
        label = j.replace("control_", "")
        for t in T:
            A_local.setdefault((label, t), 0.0)
            A_local[(label, t)] += I_arc.get((i, j, t), 0.0)

    # Construir V_prev_by_t como constante V0 para todos t (simple)
    V_prev_by_t = {t: V0 for t in T}

    m = build_caso_base_model(year, V_prev_by_t, A_local)
    m.optimize()

    status = m.Status
    obj = m.ObjVal if status == GRB.OPTIMAL else None

    print(f"Año {year}: Status={status}, Obj(sum deficits)={obj}")

    # Propagación simple de volumen mes a mes (balance hidrológico simplificado)
    # V_prev = V0 (Hm3). Inflow hacia Embalse proviene de 'AltoPolc' en A_local.
    V_prev = V0
    V_posts = []
    cotas = []
    Filtr_prop = {}
    for t in T:
        filtr_t = filtraciones_from_volumen(V_prev)
        Filtr_prop[t] = filtr_t
        inflow_emb = A_local.get(("AltoPolc", t), 0.0)
        V_new = V_prev + (inflow_emb - filtr_t) * Conv
        V_posts.append(V_new)
        cotas.append(cota_from_volumen(V_new))
        V_prev = V_new

    # Guardar resultados en CSV
    os.makedirs("results", exist_ok=True)
    csv_path = os.path.join("results", f"caso_base_{year}.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        header = ["mes", "Filtr_m3s", "A_Abanico_m3s", "A_Antuco_m3s", "A_Rucue_m3s", "A_Quilleco_m3s", "r_TU_m3s", "d_AB_m3s", "d_TU_m3s", "V_Hm3", "cota_m"]
        writer.writerow(header)
        for t in T:
            row = [t]
            # usar filtraciones propagadas (dependen de V_{t-1})
            filtr = Filtr_prop.get(t, m._Filtr.get(t, 0.0))
            row.append(f"{filtr:.6f}")
            for lab in ("Abanico", "Antuco", "Rucue", "Quilleco"):
                row.append(f"{m._A_local.get((lab, t), 0.0):.6f}")
            # variables
            r_val = m._r_TU[t].x if m._r_TU[t] is not None else 0.0
            d_ab_val = m._d_AB[t].x if m._d_AB[t] is not None else 0.0
            d_tu_val = m._d_TU[t].x if m._d_TU[t] is not None else 0.0
            row += [f"{r_val:.6f}", f"{d_ab_val:.6f}", f"{d_tu_val:.6f}"]
            # volumen y cota post-mes
            v_post = V_posts[t-1]
            cota = cotas[t-1]
            row += [f"{v_post:.6f}", f"{cota:.6f}"]
            writer.writerow(row)

    print(f"Guardado: {csv_path}")
    # Graficar cota vs mes usando la serie propagada (post-mes)
    try:
        png_path = os.path.join("results", f"cota_caso_base_{year}.png")
        plt.figure(figsize=(8, 3))
        plt.plot(T, cotas, marker='o')
        plt.xticks(T)
        plt.xlabel("Mes")
        plt.ylabel("Cota (m)")
        plt.title(f"Cota mensual (caso base, propagada) - año {year}")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(png_path, dpi=150)
        plt.close()
        print(f"Guardado gráfico cota: {png_path}")
    except Exception as e:
        print(f"⚠️ Error generando gráfico de cota: {e}")

    # RESUMEN DETERMINÍSTICO (si la solución es factible u óptima)
    # Objetivo del caso base es minimizar suma de déficits (unidad: m3/s)
    deficits_monthly = [ (m._d_AB[t].x if m._d_AB[t] is not None else 0.0) +
                         (m._d_TU[t].x if m._d_TU[t] is not None else 0.0)
                         for t in T ]
    total_deficit = sum(deficits_monthly)
    avg_deficit_monthly = total_deficit / len(T) if len(T) > 0 else 0.0

    # Imprimir bloque formateado similar al ejemplo solicitado
    print("\n📋 RESUMEN DETERMINÍSTICO")
    print("=" * 80)
    print(f"🎯 Años procesados: 1")
    # Gurobi no define GRB.FEASIBLE; considerar solución factible si hay incumbente o status óptimo/subóptimo
    feas_flag = 1 if (status in (GRB.OPTIMAL, getattr(GRB, 'SUBOPTIMAL', -1)) or getattr(m, 'SolCount', 0) > 0) else 0
    print(f"✅ Soluciones factibles: {feas_flag}")
    print(f"📉 Déficit total (suma mensual d_AB+d_TU): {total_deficit:.3f} m3/s")
    print(f"📊 Déficit promedio mensual: {avg_deficit_monthly:.3f} m3/s\n")

    # Estimación aproximada de generación (proxy)
    try:
        eta, cap_max, _ = load_caudalmax("data/CaudalMax_filtrado.csv")
        if not eta:
            print("⚠️ Aviso: mapa de rendimientos 'eta' vacío. Verifica 'data/CaudalMax_filtrado.csv'.")
        total_energy = 0.0
        # Usar solo arcos de generación para proxy y respetar cap_max si está disponible
        from embalse import A_generacion
        for t in T:
            energy_t = 0.0
            for (i, j) in A_generacion:
                eta_val = eta.get((i, j), 0.0)
                # flujo proxy: usar aporte local al nodo j si existe
                flow_proxy = A_local.get((j, t), 0.0)
                # aplicar cap_max si está definido
                cap = None
                try:
                    cap = cap_max.get((i, j))
                except Exception:
                    cap = None
                if cap is not None and cap > 0:
                    flow_used = min(flow_proxy, cap)
                else:
                    flow_used = flow_proxy
                energy_t += eta_val * flow_used
            total_energy += energy_t

        avg_energy_annual = total_energy
        avg_energy_monthly = total_energy / len(T) if len(T) > 0 else 0.0

        print("⚡ Estimación proxy de generación (arcos de generación, con cap_max)")
        print(f"   - Energía total (proxy): {avg_energy_annual:,.1f} MWh")
        print(f"   - Energía promedio mensual (proxy): {avg_energy_monthly:,.1f} MWh\n")
        print("(Nota: proxy usando A_generacion y cap_max; no sustituye al cálculo del MILP)")
    except Exception as e:
        print(f"⚠️ No fue posible calcular estimación de generación: {e}")

    return status, obj
def run_montecarlo_caso_base(n_sims: int = 100, target_year: int = None,
                             V0_mean: float = 1400.0, V0_std: float = 0.0,
                             V0_min: float = 0.0, V0_max: float = 0.0,
                             seed: int = 0):
    """Ejecuta Monte Carlo por bootstrap mensual para el caso base.

    - Muestrea las inyecciones mensuales por arco mediante bootstrap (elección aleatoria
      dentro de la muestra histórica mensual por (i,j,t)).
    - Muestrea V0: si V0_std>0 usa normal truncada (>=0), si V0_min/V0_max definidos usa uniforme.

    Retorna lista de tuplas (sim_id, status, obj_val, V0_sample)
    """
    rng = np.random.default_rng(seed)

    # Leer todo el CSV histórico y construir pools mensuales por (i,j,t)
    df = pd.read_csv("data/Caudales_historicos_filtrado.csv")
    # normalizar nombres y columnas (compatibilidad con data_loader)
    df = df.rename(columns={"central": "central", "fecha (mm-aaaa)": "fecha", "caudal (m^3/s)": "caudal_m3s"})

    # importar utilidades
    from data_loader import _norm_central_for_inj, _parse_mm_yyyy, CENTRAL_TO_INJ_ARC

    months_pool = {}
    for row in df.itertuples(index=False):
        try:
            month, year = _parse_mm_yyyy(row.fecha)
        except Exception:
            continue
        cent_key = _norm_central_for_inj(row.central)
        if cent_key not in CENTRAL_TO_INJ_ARC:
            continue
        i, j = CENTRAL_TO_INJ_ARC[cent_key]
        # pool keyed by (i,j,month)
        months_pool.setdefault((i, j, month), []).append(float(row.caudal_m3s))

    # asegurar pools mínimos
    for (i, j) in A_inyeccion:
        for t in T:
            months_pool.setdefault((i, j, t), [0.0])

    # precargar eta para proxy de generación
    try:
        eta_map, _, _ = load_caudalmax("data/CaudalMax_filtrado.csv")
    except Exception:
        eta_map = {}

    results = []
    for s in range(n_sims):
        # muestrear V0
        if V0_min > 0.0 and V0_max > 0.0 and V0_max > V0_min:
            v0_sample = float(rng.uniform(V0_min, V0_max))
        elif V0_std > 0.0:
            v0_sample = float(max(0.0, rng.normal(V0_mean, V0_std)))
        else:
            v0_sample = float(V0_mean)

        # muestrear inyecciones mensuales
        I_arc_sim = {}
        for (i, j) in A_inyeccion:
            for t in T:
                pool = months_pool.get((i, j, t), [0.0])
                I_arc_sim[(i, j, t)] = float(rng.choice(pool))

        # mapear a A_local
        A_local = {}
        for (i, j) in A_inyeccion:
            label = j.replace("control_", "")
            for t in T:
                A_local.setdefault((label, t), 0.0)
                A_local[(label, t)] += I_arc_sim.get((i, j, t), 0.0)

        V_prev_by_t = {t: v0_sample for t in T}
        m = build_caso_base_model(target_year if target_year is not None else 2000, V_prev_by_t, A_local)
        m.optimize()
        status = m.Status
        obj = m.ObjVal if status == GRB.OPTIMAL else None
        # Estimación proxy de generación para esta simulación
        total_energy_sim = 0.0
        for t in T:
            energy_t = 0.0
            for (i_j), eta_val in eta_map.items():
                if isinstance(i_j, tuple) and len(i_j) == 2:
                    i_arc, j_arc = i_j
                else:
                    continue
                flow_proxy = A_local.get((j_arc, t), 0.0)
                energy_t += eta_val * flow_proxy
            total_energy_sim += energy_t

        results.append((s, int(status), obj, v0_sample, total_energy_sim))

    return results


def check_years_coverage(path_csv: str = "data/Caudales_historicos_filtrado.csv", top_n: int = 10):
    """Analiza la cobertura de datos por año en el CSV de inyecciones.
    Imprime por año el total de filas y cuántas de ellas tienen caudal != 0.
    """
    df = pd.read_csv(path_csv)
    colmap = {"fecha (mm-aaaa)": "fecha", "caudal (m^3/s)": "caudal"}
    df = df.rename(columns=colmap)

    def _parse(s):
        try:
            mm, yy = s.split("-")
            return int(yy)
        except Exception:
            return None

    df['year'] = df['fecha'].map(_parse)
    years = sorted(df['year'].dropna().unique())
    summary = []
    for y in years:
        d = df[df['year'] == y]
        total = len(d)
        nonzero = int((d['caudal'].fillna(0) != 0).sum())
        summary.append((y, total, nonzero))

    summary_sorted = sorted(summary, key=lambda x: (-x[2], -x[1], x[0]))
    print("\n📊 Cobertura de datos por año (top por meses no nulos):")
    print("year | total_rows | nonzero_rows")
    for row in summary_sorted[:top_n]:
        print(f"{row[0]:4d} | {row[1]:10d} | {row[2]:12d}")
    return summary_sorted


def run_caso_base_silent(year: int, V0: float = 1400.0):
    """Versión silenciosa de run_caso_base_for_year que no escribe archivos.
    Retorna (status, obj, deficits_total)
    """
    # Cargar inyecciones
    I_arc = load_injections_for_year("data/Caudales_historicos_filtrado.csv", year)
    A_local = {}
    for (i, j) in A_inyeccion:
        label = j.replace("control_", "")
        for t in T:
            A_local.setdefault((label, t), 0.0)
            A_local[(label, t)] += I_arc.get((i, j, t), 0.0)

    V_prev_by_t = {t: V0 for t in T}
    m = build_caso_base_model(year, V_prev_by_t, A_local)
    m.optimize()
    status = m.Status
    obj = m.ObjVal if status == GRB.OPTIMAL else None
    deficits_monthly = [ (m._d_AB[t].x if m._d_AB[t] is not None else 0.0) + (m._d_TU[t].x if m._d_TU[t] is not None else 0.0) for t in T ]
    total_deficit = sum(deficits_monthly)
    return status, obj, total_deficit


def scan_full_coverage_years(min_nonzero: int = 84, V0: float = 1400.0, top_k: int = 5):
    """Escanea años con cobertura completa (nonzero_rows >= min_nonzero) y retorna top_k por menor déficit.
    Retorna lista de tuples (year, status, obj, total_deficit)
    """
    summary = check_years_coverage()
    full_years = [y for (y, total, nonzero) in summary if nonzero >= min_nonzero]
    results = []
    for y in full_years:
        status, obj, total_def = run_caso_base_silent(y, V0=V0)
        results.append((y, status, obj, total_def))

    results_sorted = sorted(results, key=lambda x: (x[3], x[2] if x[2] is not None else float('inf')))
    return results_sorted[:top_k]


if __name__ == "__main__":
    # Ejecuta caso base desde CLI, permitiendo variar año y V0 manualmente
    import argparse

    parser = argparse.ArgumentParser(description="Caso base: diagnosticar déficits en Abanico/Tucapel")
    parser.add_argument("--year", type=int, help="Año a evaluar (por ejemplo 2000). Requerido si no usa --scan-full-years ni --export-best-year ni --mc")
    parser.add_argument("--V0", type=float, default=1400.0, help="Volumen inicial V0 en Hm3 (por defecto 1400.0)")
    parser.add_argument("--check-years", action='store_true', help="Analiza la cobertura de datos por año y muestra los top años")
    parser.add_argument("--scan-full-years", action='store_true', help="Escanea años con cobertura completa y devuelve top-5 por menor déficit")
    parser.add_argument("--export-best-year", action='store_true', help="Escanea años con cobertura completa y ejecuta caso base (CSV+PNG) para el mejor año")
    parser.add_argument("--mc", type=int, default=0, help="Número de simulaciones Monte Carlo (bootstrap mensual). Si 0, corre una sola vez.")
    parser.add_argument("--mc-v0-std", type=float, default=0.0, help="Desvío estándar para muestrear V0 (si >0 usa normal truncada alrededor de --V0)")
    parser.add_argument("--mc-v0-min", type=float, default=0.0, help="Valor mínimo para muestreo uniforme de V0 (si >0 activa muestreo uniforme entre min/max)")
    parser.add_argument("--mc-v0-max", type=float, default=0.0, help="Valor máximo para muestreo uniforme de V0 (si >0 activa muestreo uniforme entre min/max)")
    parser.add_argument("--seed", type=int, default=0, help="Seed aleatoria para reproducibilidad")
    args = parser.parse_args()

    if getattr(args, 'check_years', False):
        check_years_coverage()
        exit(0)

    if getattr(args, 'scan_full_years', False):
        print("\n🔎 Escaneando años con cobertura completa (nonzero_rows >= 84)...")
        best = scan_full_coverage_years(min_nonzero=84, V0=args.V0, top_k=1)
        if not best:
            print("No se encontraron años con cobertura completa.")
            exit(1)

        # Tomar sólo el mejor año (top-1)
        y, status, obj, total_def = best[0]
        print(f"\nMejor año por menor déficit total: {y} | status: {status} | obj: {'' if obj is None else f'{obj:.6f}'} | total_deficit_m3s: {total_def:.6f}")

        # Ejecutar caso_base completo para el mejor año y guardar solo sus archivos (CSV + PNG)
        print(f"\nEjecutando caso_base completo para el mejor año: {y} (guardando un único CSV y PNG)")
        run_caso_base_for_year(y, V0=args.V0)
        # Renombrar los archivos generados para dejar claro que son del mejor año
        os.makedirs("results", exist_ok=True)
        src_csv = os.path.join("results", f"caso_base_{y}.csv")
        src_png = os.path.join("results", f"cota_caso_base_{y}.png")
        dst_csv = os.path.join("results", f"best_caso_base_{y}.csv")
        dst_png = os.path.join("results", f"best_cota_caso_base_{y}.png")
        try:
            if os.path.exists(src_csv):
                os.replace(src_csv, dst_csv)
            if os.path.exists(src_png):
                os.replace(src_png, dst_png)
            print(f"Guardado único CSV: {dst_csv}")
            print(f"Guardado único PNG: {dst_png}")
        except Exception as e:
            print(f"⚠️ Error al renombrar/guardar archivos del mejor año: {e}")

        exit(0)

    if getattr(args, 'export_best_year', False):
        best = scan_full_coverage_years(min_nonzero=84, V0=args.V0, top_k=1)
        if not best:
            print("No se encontró año con cobertura completa.")
            exit(1)
        y, status, obj, total_def = best[0]
        print(f"Ejecutando caso base completo para el mejor año: {y}")
        run_caso_base_for_year(y, V0=args.V0)
        exit(0)

    if args.mc and args.mc > 0:
        # correr Monte Carlo
        target_year = args.year
        if target_year is None:
            print("--mc solicitado sin --year: buscando el mejor año con cobertura completa...")
            best = scan_full_coverage_years(min_nonzero=84, V0=args.V0, top_k=1)
            if not best:
                print("No se encontró año con cobertura completa para usar en MC.")
                exit(1)
            target_year = best[0][0]
            print(f"Usando año {target_year} para Monte Carlo (top-1)")

        results_mc = run_montecarlo_caso_base(n_sims=args.mc, target_year=target_year,
                                             V0_mean=args.V0, V0_std=args.mc_v0_std,
                                             V0_min=args.mc_v0_min, V0_max=args.mc_v0_max,
                                             seed=args.seed)
        # Guardar resumen
        os.makedirs("results", exist_ok=True)
        out_csv = os.path.join("results", f"mc_caso_base_{target_year}.csv")
        with open(out_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["sim", "status", "obj_sum_deficits", "V0_sample", "energy_proxy_MWh"])
            for sim, status, obj, v0s, energy in results_mc:
                writer.writerow([sim, status, "" if obj is None else f"{obj:.6f}", f"{v0s:.6f}", f"{energy:.6f}"])
        print(f"Guardado resumen Monte Carlo: {out_csv}")

        # Resumen agregado
        opt_count = sum(1 for (_, st, _, _, _) in results_mc if st == GRB.OPTIMAL)
        feasible_count = sum(1 for (_, st, _, _, _) in results_mc if st in (GRB.OPTIMAL, getattr(GRB, 'SUBOPTIMAL', -1)))
        energies = [r[4] for r in results_mc]
        objs = [r[2] for r in results_mc if r[2] is not None]
        total_energy = sum(energies)
        avg_energy = (total_energy / len(energies)) if energies else None
        avg_obj = (sum(objs) / len(objs)) if objs else None

        print("\n📋 RESUMEN MONTE CARLO")
        print("=" * 80)
        print(f"🎯 Año usado en MC: {target_year}")
        print(f"🔁 Simulaciones: {len(results_mc)}")
        print(f"✅ Óptimos: {opt_count}, Factibles (óptimo/subóptimo): {feasible_count}")
        if avg_energy is not None:
            print(f"⚡ Energía total (proxy, suma sims): {total_energy:,.1f} MWh")
            print(f"📊 Energía promedio por simulación (proxy): {avg_energy:,.1f} MWh")
        if avg_obj is not None:
            print(f"📉 Objetivo promedio (déficit) entre sims: {avg_obj:.3f} m3/s")
    else:
        # Si no se pidió scan/export/mc, exigir que el usuario haya pasado --year
        if args.year is None:
            parser.error("--year es requerido cuando no se usan --scan-full-years, --export-best-year o --mc")
        run_caso_base_for_year(args.year, V0=args.V0)


# end of file
