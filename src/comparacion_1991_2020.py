"""
Comparación del modelo con datos oficiales DGA
Periodo: 1991-2020 (promedio histórico)
"""
import sys
import os

# Configuración de paths
if os.path.exists("data/CaudalMax_filtrado.csv"):
    sys.path.insert(0, "src")
else:
    sys.path.insert(0, ".")

from data_loader import load_caudalmax, load_injections_for_year
from model import build_model_for_one_year
import gurobipy as gp

print("="*80)
print("COMPARACION CON DATOS OFICIALES DGA - PERIODO 1991-2020")
print("="*80)

print("\n[*] DATOS OFICIALES (Tabla 1 - DGA):")
print("-" * 80)
print("Categoria: Solo Generacion (Embalse del Laja)")
print("Volumen actual:     3,066 Hm³")
print("Capacidad utilizada: 87.7%")
print("Porcentaje vs promedio 1991-2020: +9.6%")
print("-" * 80)

# Ejecutar modelo para años 1991-2020 (muestra representativa)
# Para acelerar: usar años clave del periodo
years_muestra = [1991, 1995, 2000, 2005, 2010, 2015, 2020]
volumenes_finales = []
volumenes_promedios = []

print("\n[*] Ejecutando modelo para muestra de años 1991-2020...")
print(f"    Años seleccionados: {years_muestra}")
print("-" * 80)

v0_inicial = 1400.0  # Volumen inicial del periodo

for year in years_muestra:
    try:
        # Construir y resolver modelo
        m = build_model_for_one_year(year, V0=v0_inicial)
        m.setParam('OutputFlag', 0)  # Silenciar Gurobi
        m.optimize()
        
        if m.status == gp.GRB.OPTIMAL:
            # Extraer volumen final (30 nov)
            V_vars = m._V
            T = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
            v_final = V_vars[11].X  # Noviembre (último mes)
            
            # Calcular volumen promedio del año
            v_promedio = sum(V_vars[t].X for t in T) / 12
            
            volumenes_finales.append(v_final)
            volumenes_promedios.append(v_promedio)
            
            print(f"  {year}: V_final={v_final:6.1f} Hm³ "
                  f"({100*v_final/5582:.1f}%), "
                  f"V_prom={v_promedio:6.1f} Hm³")
            
            # Usar volumen final como inicial del siguiente año
            v0_inicial = v_final
        else:
            print(f"  {year}: ERROR - Modelo no óptimo (status={m.status})")
            volumenes_finales.append(None)
            volumenes_promedios.append(None)
    
    except Exception as e:
        print(f"  {year}: ERROR - {str(e)}")
        volumenes_finales.append(None)
        volumenes_promedios.append(None)

# Filtrar valores válidos
volumenes_finales_validos = [v for v in volumenes_finales if v is not None]
volumenes_promedios_validos = [v for v in volumenes_promedios if v is not None]

print("\n" + "="*80)
print("RESULTADOS COMPARATIVOS - PERIODO 1991-2020")
print("="*80)

if volumenes_finales_validos:
    # Calcular estadísticas del modelo
    v_final_promedio = sum(volumenes_finales_validos) / len(volumenes_finales_validos)
    v_anual_promedio = sum(volumenes_promedios_validos) / len(volumenes_promedios_validos)
    
    cap_final_prom = 100 * v_final_promedio / 5582
    cap_anual_prom = 100 * v_anual_promedio / 5582
    
    # Datos oficiales
    v_oficial = 3066.0
    cap_oficial = 87.7
    
    print(f"\n[1] VOLUMEN FINAL PROMEDIO (30 Nov):")
    print(f"    Modelo:  {v_final_promedio:7.1f} Hm³ ({cap_final_prom:5.1f}%)")
    print(f"    Oficial: {v_oficial:7.1f} Hm³ ({cap_oficial:5.1f}%)")
    print(f"    Diferencia: {v_final_promedio - v_oficial:+7.1f} Hm³ "
          f"({cap_final_prom - cap_oficial:+5.1f} pp)")
    
    print(f"\n[2] VOLUMEN PROMEDIO ANUAL:")
    print(f"    Modelo:  {v_anual_promedio:7.1f} Hm³ ({cap_anual_prom:5.1f}%)")
    print(f"    Oficial: {v_oficial:7.1f} Hm³ ({cap_oficial:5.1f}%)")
    print(f"    Diferencia: {v_anual_promedio - v_oficial:+7.1f} Hm³ "
          f"({cap_anual_prom - cap_oficial:+5.1f} pp)")
    
    print(f"\n[3] ESTADISTICAS DEL MODELO (1991-2020):")
    print(f"    Min V_final: {min(volumenes_finales_validos):7.1f} Hm³ "
          f"({100*min(volumenes_finales_validos)/5582:5.1f}%)")
    print(f"    Max V_final: {max(volumenes_finales_validos):7.1f} Hm³ "
          f"({100*max(volumenes_finales_validos)/5582:5.1f}%)")
    
    print(f"\n[4] EVALUACION:")
    diff_pct = abs(cap_final_prom - cap_oficial)
    
    if diff_pct < 10:
        evaluacion = "EXCELENTE"
        color = "✅"
    elif diff_pct < 20:
        evaluacion = "BUENO"
        color = "✓"
    elif diff_pct < 30:
        evaluacion = "ACEPTABLE"
        color = "⚠️"
    else:
        evaluacion = "REQUIERE REVISION"
        color = "❌"
    
    print(f"    {color} {evaluacion}")
    print(f"    Diferencia: {diff_pct:.1f} puntos porcentuales")
    
    # Análisis de tendencia
    print(f"\n[5] TENDENCIA EN EL PERIODO:")
    if len(volumenes_finales_validos) >= 2:
        v_inicio = volumenes_finales_validos[0]
        v_fin = volumenes_finales_validos[-1]
        tendencia = v_fin - v_inicio
        
        print(f"    Volumen inicial (1991): {v_inicio:7.1f} Hm³")
        print(f"    Volumen final (2020):   {v_fin:7.1f} Hm³")
        print(f"    Cambio neto: {tendencia:+7.1f} Hm³ ({100*tendencia/v_inicio:+.1f}%)")
else:
    print("\n[ERROR] No se pudieron calcular resultados válidos")

print("\n" + "="*80)
