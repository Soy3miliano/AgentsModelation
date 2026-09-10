"""Corrida unica de la casilla electoral (modo consola).

Para el analisis estadistico serio use `replicas.py`: una sola corrida es una
realizacion de una variable aleatoria y no permite construir intervalos de
confianza entre replicas.
"""

import estadistica as est
from agentes import ModeloCasilla

# N = 625 electores y jornada de 600 minutos (documento de fundamentacion,
# secciones 5.3 y 3.3).
modelo = ModeloCasilla(n=est.N_LISTA_NOMINAL, verbose=False)

while modelo.running:
    modelo.step()

stats = modelo.estadisticas_corrida()

print("-" * 60)
print("Simulacion terminada")
print(f"Modelo de voto    : {modelo.modo_voto}")
print(f"Modelo de llegadas: {modelo.perfil_llegadas}")
print("-" * 60)
print("Resumen:", modelo.resumen())
print("Resultados:", modelo.resultados)
print("-" * 60)
print("ESTADISTICAS DE LA CORRIDA (una sola corrida, no promedio de replicas)")
print(f"  Tiempo de espera en fila : {est.formatear_ic(stats['tiempo_espera'], unidad='min')}")
print(f"  Tiempo total en casilla  : {est.formatear_ic(stats['tiempo_en_sistema'], unidad='min')}")
print(f"  Longitud de fila         : {est.formatear_ic(stats['longitud_fila'], unidad='personas')}")
print(f"  Longitud maxima de fila  : {stats['longitud_max_fila']} personas")
print(f"  Lista nominal            : {stats['lista_nominal']} electores")
print(f"  Acudieron a la casilla   : {stats['acudieron']} ({stats['participacion_potencial'] * 100:.1f} % de la lista)")
print(f"  Alcanzaron a votar       : {stats['votos_emitidos']} ({stats['tasa_atencion'] * 100:.1f} % de quienes acudieron)")
print(f"  Se quedaron sin votar    : {stats['no_alcanzaron']} por saturacion de la casilla")
print("-" * 60)
print("Para intervalos de confianza entre replicas:  python replicas.py --replicas 150")
