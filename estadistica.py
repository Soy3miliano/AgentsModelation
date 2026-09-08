"""Modelos estadisticos de la simulacion de casilla electoral.

Este modulo concentra los CUATRO modelos estadisticos formales del proyecto,
implementados como funciones puras (no dependen de Mesa ni del tablero) para
que se puedan probar, reusar y explicar por separado:

    A) Distribucion categorica (multinomial de un solo ensayo) -> voto individual.
    B) Dirichlet como prior conjugado sobre p              -> incertidumbre entre replicas.
    C) Proceso de Poisson no homogeneo (NHPP) piecewise    -> llegadas durante la jornada.
    D) Analisis de replicas: media, desviacion e IC 95%    -> validez de los resultados.

Todos los valores numericos provienen del documento de fundamentacion del
equipo ("Simulacion de una casilla electoral - AMG 2030"), secciones 6, 10 y 11.
No hay ningun parametro inventado aqui.

Ver CONCEPTOS_ESTADISTICOS_IMPLEMENTADOS.md para la explicacion conceptual.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Constantes de referencia (documento de fundamentacion, seccion 12)
# ---------------------------------------------------------------------------

Z_95 = 1.96          # valor critico normal para 95 % de confianza (seccion 6.2)
N_LISTA_NOMINAL = 625     # electores por casilla (seccion 5.3)
DURACION_JORNADA = 600    # minutos, de 08:00 a 18:00 (seccion 3.3)
PARTICIPACION_BASE = 0.61  # tasa de participacion esperada (seccion 7.2)
REPLICAS_RECOMENDADAS = 150  # valor de arranque antes del piloto (seccion 6.3)


# ---------------------------------------------------------------------------
# MODELO A + B: categorias de voto y vectores de intencion
# ---------------------------------------------------------------------------

# Orden canonico de las categorias. Es el mismo orden en todas las tablas de
# abajo: no reordenar sin reordenar tambien los vectores y los alphas.
CATEGORIAS_VOTO = [
    "Morena-PT-PVEM",
    "PAN-PRI",
    "Movimiento Ciudadano",
    "Otros/partidos nuevos",
    "Voto nulo",
    "Candidatura no registrada",
]

# Escenario base (seccion 10.2, tabla 17) con sus alphas de Dirichlet
# (seccion 10.4, tabla 19). Concentracion total = 200.
ALPHAS_ESCENARIO_BASE = [86.0, 67.0, 36.9, 5.0, 4.8, 0.3]

# Los cuatro escenarios de la seccion 10.3 (tabla 18). En los escenarios B, C y D
# el documento reporta "Nulos" agregando candidaturas no registradas; aqui se
# separa la fraccion no registrada (0.15 %, seccion 7.3) para conservar las 6
# categorias del orden canonico.
ESCENARIOS = {
    "A": {
        "nombre": "Base",
        "descripcion": "Proyeccion directa: encuesta nacional 2026 x ratio Jalisco 2024.",
        "p": [0.4300, 0.3351, 0.1844, 0.0250, 0.0240, 0.0015],
    },
    "B": {
        "nombre": "Continuidad oficialista",
        "descripcion": "Morena recupera niveles de 2024 y arrastra voto en Jalisco.",
        "p": [0.5200, 0.2700, 0.1550, 0.0250, 0.0285, 0.0015],
    },
    "C": {
        "nombre": "Repunte naranja",
        "descripcion": "MC capitaliza dos sexenios de gobierno estatal en Jalisco.",
        "p": [0.3800, 0.3000, 0.2700, 0.0250, 0.0235, 0.0015],
    },
    "D": {
        "nombre": "Alternancia opositora",
        "descripcion": "Recomposicion opositora y desgaste del oficialismo.",
        "p": [0.3500, 0.4000, 0.2000, 0.0250, 0.0235, 0.0015],
    },
}

# Concentracion total de la Dirichlet del escenario base (seccion 10.4).
# Se reusa para derivar los alphas de los escenarios alternativos:
# alpha_j = p_j * concentracion.
CONCENTRACION_DIRICHLET = 200.0


def vector_escenario(escenario="A"):
    """Devuelve el vector de probabilidades p del escenario pedido (A/B/C/D).

    El vector siempre tiene la longitud de CATEGORIAS_VOTO y suma 1.
    """
    if escenario not in ESCENARIOS:
        raise ValueError(
            f"Escenario '{escenario}' desconocido. Opciones: {sorted(ESCENARIOS)}"
        )
    p = np.array(ESCENARIOS[escenario]["p"], dtype=float)
    return p / p.sum()


def alphas_escenario(escenario="A", concentracion=CONCENTRACION_DIRICHLET):
    """Parametros alpha de la Dirichlet para el escenario pedido.

    Para el escenario base se devuelven los alphas tal cual los reporta el
    documento (tabla 19). Para los demas se derivan como alpha_j = p_j * c,
    que es justo la relacion que cumple la tabla 19 con c = 200.
    """
    if escenario == "A" and concentracion == CONCENTRACION_DIRICHLET:
        return np.array(ALPHAS_ESCENARIO_BASE, dtype=float)
    return vector_escenario(escenario) * float(concentracion)


# ---------------------------------------------------------------------------
# MODELO A: distribucion categorica (multinomial de un solo ensayo)
# ---------------------------------------------------------------------------

def muestrear_voto_categorico(probabilidades, rng, etiquetas=None):
    """MODELO A - Distribucion categorica Categorical(p).

    Extrae UNA realizacion de una variable aleatoria categorica sobre k
    opciones. Es el caso particular de la multinomial con un solo ensayo
    (n = 1): el agente emite exactamente un voto.

        P(X = j) = p_j,   con  sum_j p_j = 1

    Funciona para k arbitrario: la longitud la determina el vector que se
    pasa, no hay ningun numero de categorias fijado en el codigo.

    Parametros
    ----------
    probabilidades : secuencia de k floats no negativos (se renormaliza).
    rng            : np.random.Generator (el mismo del modelo, para que la
                     corrida sea reproducible con una semilla).
    etiquetas      : lista opcional de k nombres. Si se da, devuelve el nombre
                     de la categoria; si no, devuelve el indice entero.
    """
    p = np.asarray(probabilidades, dtype=float)

    if p.ndim != 1 or p.size == 0:
        raise ValueError("`probabilidades` debe ser un vector de longitud k >= 1.")
    if np.any(p < 0):
        raise ValueError("`probabilidades` no puede tener valores negativos.")

    total = p.sum()
    if total <= 0:
        raise ValueError("`probabilidades` debe sumar mas que cero.")
    p = p / total  # renormaliza por seguridad ante error de redondeo

    indice = int(rng.choice(len(p), p=p))

    if etiquetas is None:
        return indice
    if len(etiquetas) != len(p):
        raise ValueError(
            f"`etiquetas` tiene {len(etiquetas)} elementos y `probabilidades` {len(p)}."
        )
    return etiquetas[indice]


# ---------------------------------------------------------------------------
# MODELO B: Dirichlet como prior conjugado sobre p
# ---------------------------------------------------------------------------

def muestrear_dirichlet(alphas, rng):
    """MODELO B - Extrae un vector de probabilidades p ~ Dirichlet(alpha).

        f(p | alpha) = [1/B(alpha)] * prod_j p_j^(alpha_j - 1)

    Se llama UNA VEZ POR REPLICA, antes de generar los votos individuales de
    esa replica. Asi la incertidumbre no esta solo en el voto de cada persona
    (eso ya lo da el modelo A) sino tambien en cual es el verdadero reparto
    de preferencias de la casilla, que es lo que en realidad no conocemos.

    La media de la Dirichlet es E[p_j] = alpha_j / sum(alpha), y la suma de
    los alphas (concentracion) controla que tan parecidas son las replicas
    entre si: mas concentracion -> menos variabilidad.
    """
    a = np.asarray(alphas, dtype=float)

    if a.ndim != 1 or a.size == 0:
        raise ValueError("`alphas` debe ser un vector de longitud k >= 1.")
    if np.any(a <= 0):
        raise ValueError("Todos los `alphas` deben ser estrictamente positivos.")

    return rng.dirichlet(a)


# ---------------------------------------------------------------------------
# MODELO C: proceso de Poisson no homogeneo (NHPP) piecewise-constant
# ---------------------------------------------------------------------------

# Perfil horario de llegadas (seccion 11.3, tabla 21). La jornada de 600
# minutos se parte en 5 tramos de 120 minutos, y DENTRO de cada tramo la tasa
# es constante: eso es un NHPP con tasa constante por tramos.
# Cada entrada: (minuto_inicio, minuto_fin, tasa_por_hora, etiqueta)
PERFIL_HORARIO_NHPP = [
    (0,   120, 34.4, "08:00-10:00  apertura"),
    (120, 240, 49.6, "10:00-12:00  primer pico"),
    (240, 360, 42.0, "12:00-14:00  meseta alta"),
    (360, 480, 30.5, "14:00-16:00  valle de comida"),
    (480, 600, 34.4, "16:00-18:00  segundo pico"),
]


def pesos_tramos_nhpp(perfil=None):
    """Peso (probabilidad) de cada tramo bajo el NHPP piecewise-constant.

    El numero esperado de llegadas del tramo i es la integral de la tasa en
    ese tramo:  Lambda_i = lambda_i * duracion_i. La probabilidad de que una
    llegada cualquiera caiga en el tramo i es Lambda_i / sum_l Lambda_l.

    Reproduce los porcentajes de la tabla 21 (18 / 26 / 22 / 16 / 18 %).
    """
    perfil = perfil or PERFIL_HORARIO_NHPP
    # tasa esta en personas/hora y la duracion en minutos -> /60 para integrar
    intensidades = np.array(
        [tasa * (fin - inicio) / 60.0 for inicio, fin, tasa, _ in perfil],
        dtype=float,
    )
    return intensidades / intensidades.sum()


def muestrear_tiempo_llegada_nhpp(rng, perfil=None, duracion_jornada=DURACION_JORNADA):
    """MODELO C - Sortea el minuto de llegada de UN votante bajo el NHPP.

    Con una poblacion fija de N electores, condicionar un proceso de Poisson
    no homogeneo a que ocurran N eventos hace que los tiempos de llegada sean
    independientes y con densidad proporcional a la tasa:

        f(t) = lambda(t) / Lambda,   con  Lambda = integral de lambda(t) dt

    Como lambda(t) es constante por tramos, muestrear de f(t) se reduce a dos
    pasos exactos: (1) elegir tramo con probabilidad Lambda_i / Lambda, y
    (2) elegir un instante uniforme dentro de ese tramo. No es una
    aproximacion: es la forma cerrada de esa densidad.

    `duracion_jornada` reescala el perfil si la simulacion usa una jornada
    distinta a los 600 minutos del documento.
    """
    perfil = perfil or PERFIL_HORARIO_NHPP
    pesos = pesos_tramos_nhpp(perfil)

    i = int(rng.choice(len(perfil), p=pesos))
    inicio, fin, _, _ = perfil[i]

    minuto = rng.uniform(inicio, fin)

    # Reescala si la jornada simulada no dura los 600 minutos de referencia.
    escala = float(duracion_jornada) / float(perfil[-1][1])
    return minuto * escala


def muestrear_tiempo_llegada_homogeneo(rng, tasa_llegada):
    """Modo simple (fallback): proceso homogeneo, tasa constante toda la jornada.

    Se conserva para poder comparar contra el NHPP y mostrar que la diferencia
    entre ambos es justo lo que genera -o no- colas visibles. NO es el modo
    por defecto.
    """
    return rng.exponential(scale=1.0 / tasa_llegada)


# ---------------------------------------------------------------------------
# MODELO D: analisis de replicas, intervalos de confianza y tamano de muestra
# ---------------------------------------------------------------------------

def media_desv_ic95(muestras, z=Z_95):
    """MODELO D - Media, desviacion estandar muestral e intervalo de confianza 95 %.

        media    = (1/n) * sum(x_i)
        s        = sqrt( sum((x_i - media)^2) / (n - 1) )      [n-1: insesgada]
        error    = z * s / sqrt(n)                              [error estandar]
        IC 95 %  = media +/- error

    Devuelve un diccionario listo para serializar a JSON (la API de Unity lo
    consume tal cual). Con una sola muestra no existe dispersion: se devuelve
    desviacion 0 y el intervalo colapsa al punto, y `n` deja claro por que.
    """
    x = np.asarray(list(muestras), dtype=float)
    n = x.size

    if n == 0:
        return {
            "n": 0, "media": None, "desviacion": None,
            "error_estandar": None, "ic95_inferior": None, "ic95_superior": None,
        }

    media = float(x.mean())

    if n == 1:
        return {
            "n": 1, "media": media, "desviacion": 0.0,
            "error_estandar": 0.0, "ic95_inferior": media, "ic95_superior": media,
        }

    desviacion = float(x.std(ddof=1))   # ddof=1 -> divide entre n-1
    error = float(z * desviacion / np.sqrt(n))

    return {
        "n": int(n),
        "media": media,
        "desviacion": desviacion,
        "error_estandar": error,
        "ic95_inferior": media - error,
        "ic95_superior": media + error,
    }


def replicas_necesarias(desviacion_piloto, semiamplitud, z=Z_95):
    """MODELO D - Numero de replicas para alcanzar una precision dada.

        n = ( z * s / E )^2

    donde `s` es la desviacion estandar medida en una corrida piloto (el
    documento sugiere 30 replicas) y `E` es la semiamplitud aceptable del
    intervalo de confianza. Se redondea hacia arriba porque no existen
    fracciones de replica.

    Ejemplo del documento (seccion 6.3): s = 6.0 min y E = 1.0 min -> 139.
    """
    if semiamplitud <= 0:
        raise ValueError("`semiamplitud` (E) debe ser mayor que cero.")
    if desviacion_piloto < 0:
        raise ValueError("`desviacion_piloto` (s) no puede ser negativa.")

    return int(np.ceil((z * float(desviacion_piloto) / float(semiamplitud)) ** 2))


def formatear_ic(resumen_ic, decimales=2, unidad=""):
    """Formatea un resultado de `media_desv_ic95` como 'media +/- error' legible.

    Pensado para el HUD de Unity y para la salida de consola: nunca imprime un
    numero solo, siempre acompanado de su intervalo.
    """
    if not resumen_ic or resumen_ic.get("media") is None:
        return "sin datos"

    sufijo = f" {unidad}".rstrip()
    media = resumen_ic["media"]

    if resumen_ic["n"] == 1:
        return f"{media:.{decimales}f}{sufijo} (1 corrida, sin IC)"

    error = resumen_ic["error_estandar"]
    return f"{media:.{decimales}f} +/- {error:.{decimales}f}{sufijo} (IC 95 %, n={resumen_ic['n']})"
