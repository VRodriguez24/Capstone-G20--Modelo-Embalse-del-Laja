"""
Script para el analisis de los deficit del modelo
"""
from model import build_model_for_one_year


def test_deficit_logic(start_year=1960, end_year=2023, V0_inicial=1400.0):
    """
    Prueba la lógica de déficits del modelo para verificar que:
    1. DefTu y DefAb se calculan correctamente
    2. Def1 = min{DefTu, DefAb}
    3. La cobertura por El Toro es x_ElToro >= Def1 + Def2

    Args:
        start_year: Año inicial del análisis (default: 1960)
        end_year: Año final del análisis (default: 2023)
        V0_inicial: Volumen inicial para el primer año (default: 1400.0 Hm³)
    """

    print("=" * 70)
    print("🧪 VALIDACIÓN DE LÓGICA DE DÉFICITS (MULTI-AÑO)")
    print("=" * 70)

    years = list(range(start_year, end_year + 1))
    total_years = len(years)

    print("\n📅 Período de análisis: {}-{} ({} años)".format(
        start_year, end_year, total_years))
    print(f"💧 Volumen inicial: {V0_inicial} Hm³")

    # Periodo hidrológico
    T = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    Conv = (86400 * 30) / 1e6  # m³/s × mes -> Hm³

    # Almacenar resultados agregados
    resultados_totales = []
    current_V0 = V0_inicial

    print("\n🔄 Procesando años...")
    print("=" * 70)

    for year_idx, test_year in enumerate(years):
        year_num = year_idx + 1
        print(f"\n[{year_num}/{total_years}] 📅 Año {test_year} "
              f"(V0={current_V0:.1f} Hm³)")

        try:
            model = build_model_for_one_year(
                target_year=test_year,
                V0=current_V0
            )

            # Configurar solver para que no imprima mensajes
            model.Params.OutputFlag = 0

            model.optimize()

            if model.status == 2:  # Óptimo
                # Extraer variables de déficit
                deftu_vars = {}
                defab_vars = {}
                def1_vars = {}
                def2_vars = {}
                eltoro_vars = {}

                for v in model.getVars():
                    if v.VarName.startswith("DeficitTucapel"):
                        period = int(v.VarName.split('[')[-1].split(']')[0])
                        deftu_vars[period] = v.X
                    elif v.VarName.startswith("DeficitAbanico"):
                        period = int(v.VarName.split('[')[-1].split(']')[0])
                        defab_vars[period] = v.X
                    elif v.VarName.startswith("Deficit1erosRegantes"):
                        period = int(v.VarName.split('[')[-1].split(']')[0])
                        def1_vars[period] = v.X
                    elif v.VarName.startswith("Deficit2dosRegantes"):
                        period = int(v.VarName.split('[')[-1].split(']')[0])
                        def2_vars[period] = v.X

                # Extraer flujo por El Toro
                x_vars = model._x
                for t in T:
                    eltoro_vars[t] = x_vars["Embalse", "ElToro", t].X

                # Verificar lógica de mínimo
                violations = 0
                tolerance = 1e-4

                for t in T:
                    deftu = deftu_vars.get(t, 0.0)
                    defab = defab_vars.get(t, 0.0)
                    def1 = def1_vars.get(t, 0.0)
                    expected_def1 = min(deftu, defab)

                    if abs(def1 - expected_def1) >= tolerance:
                        violations += 1

                # Totales anuales
                total_def1 = sum(def1_vars.values())
                total_def2 = sum(def2_vars.values())
                total_eltoro = sum(eltoro_vars.values())
                energia = model.objVal

                # Actualizar V0 para siguiente año
                V_vars = model._V
                final_month = max(T)
                v_final = V_vars[final_month].X

                status = "✅" if violations == 0 else "⚠️"
                print(f"  {status} Def1={total_def1:.1f} | "
                      f"Def2={total_def2:.1f} | "
                      f"Toro={total_eltoro*Conv:.1f} Hm³ | "
                      f"E={energia:.0f} MWh | "
                      f"Vf={v_final:.0f}")

                resultados_totales.append({
                    'year': test_year,
                    'def1': total_def1,
                    'def2': total_def2,
                    'eltoro': total_eltoro * Conv,
                    'energia': energia,
                    'v_final': v_final,
                    'violations': violations
                })

                current_V0 = v_final  # Actualizar para siguiente año

            else:
                print(f"  ❌ No factible (status={model.status})")
                current_V0 = 1400.0  # Reset a valor seguro

            model.dispose()

        except Exception as e:
            print(f"  ❌ Error: {e}")
            current_V0 = 1400.0

    # Resumen agregado
    print("\n" + "=" * 70)
    print("📋 RESUMEN AGREGADO")
    print("=" * 70)

    if resultados_totales:
        total_violations = sum(r['violations'] for r in resultados_totales)
        años_exitosos = len([r for r in resultados_totales
                            if r['violations'] == 0])

        print(f"\n✅ Años procesados: {len(resultados_totales)}/{total_years}")
        print(f"✅ Años sin violaciones: {años_exitosos}"
              f"/{len(resultados_totales)}")
        print(f"⚠️  Total violaciones: {total_violations}")

        # Totales acumulados
        suma_def1 = sum(r['def1'] for r in resultados_totales)
        suma_def2 = sum(r['def2'] for r in resultados_totales)
        suma_eltoro = sum(r['eltoro'] for r in resultados_totales)
        suma_energia = sum(r['energia'] for r in resultados_totales)

        print(f"\n📊 TOTALES HISTÓRICOS ({start_year}-{end_year}):")
        print(f" • Déficit 1os regantes: {suma_def1:,.1f} Hm³")
        print(f" • Déficit 2dos regantes: {suma_def2:,.1f} Hm³")
        print(f" • Extracción El Toro: {suma_eltoro:,.1f} Hm³")
        print(f" • Energía total: {suma_energia:,.0f} MWh")

        print("\n📊 PROMEDIOS ANUALES:")
        n = len(resultados_totales)
        print(f" • Déficit 1os: {suma_def1/n:,.1f} Hm³/año")
        print(f" • Déficit 2dos: {suma_def2/n:,.1f} Hm³/año")
        print(f" • El Toro: {suma_eltoro/n:,.1f} Hm³/año")
        print(f" • Energía: {suma_energia/n:,.0f} MWh/año")

    print("=" * 70)


if __name__ == "__main__":
    test_deficit_logic()
