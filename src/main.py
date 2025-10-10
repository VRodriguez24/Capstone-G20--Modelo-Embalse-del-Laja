#!/usr/bin/env python3
"""
Entry point CLI for the Embalse del Laja model.

Usage examples:
  python -m src.main --v0 3000
  python -m src.main --montecarlo --n-sims 100 --year 2000 --seed 1 --v0 2500
"""
import argparse
import sys

# ensure src is on path when running from repository root
sys.path.insert(0, '.')

from model import run_years, run_montecarlo, YEARS_HORIZON


def parse_args():
    p = argparse.ArgumentParser(description="CLI para ejecutar el modelo Embalse del Laja")
    p.add_argument('--v0', type=float, default=None, help='Volumen inicial V0 (Hm3)')
    p.add_argument('--montecarlo', action='store_true', help='Ejecutar Monte Carlo (bootstrap mensual)')
    p.add_argument('--n-sims', type=int, default=110000, help='Número de simulaciones Monte Carlo')
    p.add_argument('--year', type=int, default=None, help='Año objetivo para Monte Carlo (default: primer año de YEARS_HORIZON)')
    p.add_argument('--seed', type=int, default=0, help='Seed para Monte Carlo')
    return p.parse_args()


def main():
    args = parse_args()
    if args.montecarlo:
        print(f"🏁 Ejecutando Monte Carlo: n_sims={args.n_sims}, year={args.year}, seed={args.seed}, V0={args.v0}")
        res = run_montecarlo(n_sims=args.n_sims, target_year=args.year, seed=args.seed, V0=args.v0)
        # resumen
        statuses = [r[1] for r in res]
        objs = [r[2] for r in res if r[2] is not None]
        print(f"Simulaciones: {len(res)} | Óptimos: {sum(1 for s in statuses if s==2)}")
        if objs:
            import statistics
            print(f"Media objetivo (MWh): {statistics.mean(objs):.4f}")
    else:
        print(f"🏁 Ejecutando run_years para el horizonte {YEARS_HORIZON} con V0={args.v0}")
        run_years(YEARS_HORIZON, V0=args.v0)


if __name__ == '__main__':
    main()
