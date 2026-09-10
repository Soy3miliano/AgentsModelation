"""Corredor de replicas de la simulacion (MODELO D).

Una simulacion estocastica corrida UNA sola vez no dice nada: cada corrida es
una realizacion de una variable aleatoria. Este script ejecuta la casilla
muchas veces, con una semilla distinta cada vez, acumula las variables de
salida y reporta SIEMPRE media, desviacion estandar e intervalo de confianza
al 95 % -- nunca un numero suelto.
"""

import argparse
import numpy as np
from agentes import ModeloCasilla
import estadistica as est


def correr_replica(semilla, params):
    """Ejecuta una corrida completa de la casilla con una semilla fija."""
    rng = np.random.default_rng(semilla)
    params_corrida = dict(params)
    params_corrida["rng"] = rng
    params_corrida["verbose"] = False

    modelo = ModeloCasilla(**params_corrida)

    while modelo.running and modelo.tick < modelo.hora_cierre * 2:
        modelo.step()

    return modelo.estadisticas_corrida()


def correr_experimento(num_replicas=est.REPLICAS_RECOMENDADAS, params=None):
    """Ejecuta N replicas independientes y agrega los resultados."""
    params = params or {}
    print(f"\nIniciando experimento con {num_replicas} replicas...")

    tiempos_espera_promedio = []
    tiempos_sistema_promedio = []
    longitudes_maximas = []
    participaciones = []
    votos_totales = {c: [] for c in (params.get("candidatos") or est.CATEGORIAS_VOTO)}

    for r in range(num_replicas):
        stats = correr_replica(semilla=1000 + r, params=params)

        if stats["tiempo_espera"]["media"] is not None:
            tiempos_espera_promedio.append(stats["tiempo_espera"]["media"])
        if stats["tiempo_en_sistema"]["media"] is not None:
            tiempos_sistema_promedio.append(stats["tiempo_en_sistema"]["media"])

        longitudes_maximas.append(stats["longitud_max_fila"])
        participaciones.append(stats["participacion_observada"])

        for c, prop in stats["proporcion_voto"].items():
            if c in votos_totales:
                votos_totales[c].append(prop)

        if (r + 1) % max(1, num_replicas // 10) == 0:
            print(f"Progreso: {r + 1}/{num_replicas} replicas completadas")

    print("\n" + "=" * 60)
    print(f"RESULTADOS AGREGADOS ({num_replicas} REPLICAS - IC 95%)")
    print("=" * 60)

    print("Tiempo de espera en fila (min):", est.formatear_ic(est.media_desv_ic95(tiempos_espera_promedio), unidad="min"))
    print("Tiempo total en casilla (min): ", est.formatear_ic(est.media_desv_ic95(tiempos_sistema_promedio), unidad="min"))
    print("Longitud maxima de fila:       ", est.formatear_ic(est.media_desv_ic95(longitudes_maximas), unidad="personas"))
    print("Participacion observada:       ", est.formatear_ic(est.media_desv_ic95(participaciones)))

    print("\nDistribucion de votos estimada:")
    for c, arr in votos_totales.items():
        if arr:
            res_ic = est.media_desv_ic95(arr)
            print(f"  {c:25s}: {est.formatear_ic(res_ic)}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Corredor de replicas Monte Carlo de la casilla.")
    parser.add_argument("--replicas", "-r", type=int, default=30, help="Numero de replicas a ejecutar")
    parser.add_argument("--electores", "-n", type=int, default=100, help="Electores por casilla")
    parser.add_argument("--escenario", "-e", type=str, default="A", help="Escenario de votacion (A/B/C/D)")

    args = parser.parse_args()

    parametros = {
        "n": args.electores,
        "escenario": args.escenario,
        "modo_voto": "categorico_dirichlet",
    }

    correr_experimento(num_replicas=args.replicas, params=parametros)