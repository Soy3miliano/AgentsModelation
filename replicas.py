"""Corredor de replicas de la simulacion (MODELO D).

Una simulacion estocastica corrida UNA sola vez no dice nada: cada corrida es
una realizacion de una variable aleatoria. Este script ejecuta la casilla
muchas veces, con una semilla distinta cada vez, acumula las variables de
salida y reporta SIEMPRE media, desviacion estandar e intervalo de confianza
al 95 % -- nunca un numero suelto.

Es tambien lo que le da sentido al MODELO B (Dirichlet): en cada replica se
sortea un vector p distinto ANTES de generar los votos de esa replica, asi que
la dispersion entre replicas incluye tanto el azar del voto individual como la
incertidumbre sobre el verdadero reparto de preferencias de la casilla.

Uso:
    python replicas.py                          # 30 replicas piloto, escenario A
    python replicas.py --replicas 150           # corrida definitiva
    python replicas.py --escenario C --n 625    # otro escenario
    python replicas.py --modo utilidad          # compara contra el modelo de utilidad

No modifica main.py ni api.py: importa ModeloCasilla y la corre en aislamiento.
"""

import argparse

import numpy as np

import estadistica as est
from agentes import ModeloCasilla


# Tope de seguridad: si una corrida no termina en este numero de pasos se
# aborta para que un eventual atasco no cuelgue todo el experimento.
MAX_TICKS = 5000


def correr_una_replica(semilla, n, escenario, modo_voto, perfil_llegadas, hora_cierre):
    """Ejecuta UNA corrida completa y devuelve sus metricas de salida.

    Cada replica usa su propia semilla, de modo que las corridas son
    independientes entre si pero el experimento completo es reproducible.
    """
    modelo = ModeloCasilla(
        n=n,
        hora_cierre=hora_cierre,
        modo_voto=modo_voto,
        escenario=escenario,
        perfil_llegadas=perfil_llegadas,
        verbose=False,
        rng=np.random.default_rng(semilla),
    )

    while modelo.running and modelo.tick < MAX_TICKS:
        modelo.step()

    proporciones = {}
    if modelo.votos_emitidos > 0:
        proporciones = {
            c: modelo.resultados[c] / modelo.votos_emitidos for c in modelo.candidatos
        }

    return {
        "semilla": semilla,
        "completada": modelo.finalizada,
        "duracion_ticks": modelo.tick,
        "votos_emitidos": modelo.votos_emitidos,
        "tiempo_espera_medio": float(np.mean(modelo.tiempos_espera)) if modelo.tiempos_espera else 0.0,
        "tiempo_en_sistema_medio": float(np.mean(modelo.tiempos_en_sistema)) if modelo.tiempos_en_sistema else 0.0,
        "longitud_max_fila": modelo.longitud_max_fila,
        "proporcion_voto": proporciones,
        "candidatos": modelo.candidatos,
        "p_replica": list(modelo.p_replica) if modelo.p_replica is not None else None,
    }


def correr_experimento(
    replicas=30,
    n=est.N_LISTA_NOMINAL,
    escenario="A",
    modo_voto="categorico_dirichlet",
    perfil_llegadas="nhpp",
    hora_cierre=est.DURACION_JORNADA,
    semilla_base=2030,
    progreso=True,
):
    """Corre `replicas` corridas independientes y agrega sus resultados."""
    corridas = []

    for i in range(replicas):
        corridas.append(
            correr_una_replica(
                semilla=semilla_base + i,
                n=n,
                escenario=escenario,
                modo_voto=modo_voto,
                perfil_llegadas=perfil_llegadas,
                hora_cierre=hora_cierre,
            )
        )
        if progreso:
            print(f"  replica {i + 1}/{replicas} lista", end="\r", flush=True)

    if progreso:
        print(" " * 40, end="\r")

    return agregar_resultados(corridas, escenario, modo_voto)


def agregar_resultados(corridas, escenario="A", modo_voto="categorico_dirichlet"):
    """Aplica media / desviacion / IC 95 % sobre el conjunto de replicas."""
    candidatos = corridas[0]["candidatos"] if corridas else []

    # IC 95 % de la proporcion de voto de cada bloque, entre replicas.
    proporcion_por_bloque = {}
    for c in candidatos:
        serie = [r["proporcion_voto"].get(c, 0.0) for r in corridas]
        proporcion_por_bloque[c] = est.media_desv_ic95(serie)

    return {
        "escenario": escenario,
        "nombre_escenario": est.ESCENARIOS.get(escenario, {}).get("nombre", "-"),
        "modo_voto": modo_voto,
        "replicas": len(corridas),
        "replicas_completadas": sum(1 for r in corridas if r["completada"]),
        "tiempo_espera": est.media_desv_ic95([r["tiempo_espera_medio"] for r in corridas]),
        "tiempo_en_sistema": est.media_desv_ic95([r["tiempo_en_sistema_medio"] for r in corridas]),
        "longitud_max_fila": est.media_desv_ic95([r["longitud_max_fila"] for r in corridas]),
        "votos_emitidos": est.media_desv_ic95([r["votos_emitidos"] for r in corridas]),
        "duracion_ticks": est.media_desv_ic95([r["duracion_ticks"] for r in corridas]),
        "proporcion_voto": proporcion_por_bloque,
        "corridas": corridas,
    }


def recomendar_replicas(resultado, precisiones=None):
    """Aplica n = (Z*s/E)^2 sobre el piloto ya corrido.

    Responde a: "con la dispersion que acabo de medir, cuantas replicas
    necesito para que el intervalo tenga la semiamplitud E que quiero".
    """
    precisiones = precisiones or {
        "tiempo_espera": [1.0, 0.5],
        "longitud_max_fila": [2.0, 1.0],
    }

    recomendaciones = []
    for variable, lista_E in precisiones.items():
        s = resultado[variable]["desviacion"]
        if s is None:
            continue
        for E in lista_E:
            recomendaciones.append({
                "variable": variable,
                "desviacion_piloto": s,
                "semiamplitud": E,
                "replicas_necesarias": est.replicas_necesarias(s, E),
            })
    return recomendaciones


def imprimir_reporte(resultado):
    """Reporte legible en consola, con IC 95 % en todas las variables."""
    print("=" * 68)
    print(f"  EXPERIMENTO: escenario {resultado['escenario']} "
          f"({resultado['nombre_escenario']}) | modo_voto = {resultado['modo_voto']}")
    print(f"  Replicas: {resultado['replicas']} "
          f"({resultado['replicas_completadas']} completadas)")
    print("=" * 68)

    print("\nVARIABLES DE SALIDA (media +/- semiamplitud del IC 95 %)")
    print("-" * 68)
    print(f"  Tiempo de espera en fila : {est.formatear_ic(resultado['tiempo_espera'], unidad='min')}")
    print(f"  Tiempo total en casilla  : {est.formatear_ic(resultado['tiempo_en_sistema'], unidad='min')}")
    print(f"  Longitud maxima de fila  : {est.formatear_ic(resultado['longitud_max_fila'], unidad='personas')}")
    print(f"  Votos emitidos           : {est.formatear_ic(resultado['votos_emitidos'], unidad='votos')}")
    print(f"  Duracion de la jornada   : {est.formatear_ic(resultado['duracion_ticks'], unidad='min')}")

    print("\nPROPORCION DE VOTO POR BLOQUE (IC 95 % entre replicas)")
    print("-" * 68)
    for bloque, ic in resultado["proporcion_voto"].items():
        if ic["media"] is None:
            continue
        if ic["n"] > 1:
            print(f"  {bloque:<28} {ic['media'] * 100:6.2f} % +/- {ic['margen_error'] * 100:.2f} pp")
        else:
            print(f"  {bloque:<28} {ic['media'] * 100:6.2f} %  (1 corrida, sin IC)")

    print("\nTAMANO DE MUESTRA RECOMENDADO   n = (Z*s/E)^2, Z = 1.96")
    print("-" * 68)
    for rec in recomendar_replicas(resultado):
        print(f"  {rec['variable']:<20} s = {rec['desviacion_piloto']:6.2f} | "
              f"E = +/-{rec['semiamplitud']:<4} -> {rec['replicas_necesarias']:>4} replicas")
    print()


def main():
    parser = argparse.ArgumentParser(description="Corredor de replicas de la casilla electoral.")
    parser.add_argument("--replicas", type=int, default=30,
                        help="Numero de replicas (30 = piloto, 150 = definitivo).")
    parser.add_argument("--n", type=int, default=est.N_LISTA_NOMINAL,
                        help="Electores en la lista nominal de la casilla.")
    parser.add_argument("--escenario", choices=sorted(est.ESCENARIOS), default="A",
                        help="Escenario de intencion de voto (A/B/C/D).")
    parser.add_argument("--modo", choices=["categorico_dirichlet", "utilidad"],
                        default="categorico_dirichlet", dest="modo_voto",
                        help="Modelo de decision de voto.")
    parser.add_argument("--llegadas", choices=["nhpp", "homogeneo"], default="nhpp",
                        dest="perfil_llegadas", help="Modelo de llegadas.")
    parser.add_argument("--hora-cierre", type=int, default=est.DURACION_JORNADA,
                        help="Minutos de jornada antes de cerrar la entrada.")
    args = parser.parse_args()

    print(f"\nCorriendo {args.replicas} replicas (N = {args.n})...")
    resultado = correr_experimento(
        replicas=args.replicas,
        n=args.n,
        escenario=args.escenario,
        modo_voto=args.modo_voto,
        perfil_llegadas=args.perfil_llegadas,
        hora_cierre=args.hora_cierre,
    )
    imprimir_reporte(resultado)


if __name__ == "__main__":
    main()
