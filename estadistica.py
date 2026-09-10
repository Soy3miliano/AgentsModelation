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
# HETEROGENEIDAD DEMOGRAFICA (documento, seccion 11)
#
# Hasta antes de esto el modelo sorteaba la edad de una Normal(45, 15) inventada
# y hacia que todos acudieran a votar con la misma Bernoulli(0.61). El documento
# tiene datos mejores y ya publicados, y no usarlos era el hueco mas grande
# entre lo que dice el reporte y lo que hace el codigo.
# ---------------------------------------------------------------------------

# Tabla 20: estructura de edad REAL de la Lista Nominal de Guadalajara
# (DERFE-INE, enero de 2026). Cada entrada: (edad_min, edad_max, electores,
# multiplicador_participacion).
#
# Los conteos de electores son DATO oficial. El multiplicador es SUPUESTO de
# modelacion del documento, calibrado para reproducir el patron que si publica
# el INE: participacion creciente con la edad hasta los 79, maxima en 65-74.
ESTRUCTURA_EDAD_LN = [
    (18, 24, 157757, 0.88),
    (25, 29, 124229, 0.82),
    (30, 34, 125623, 0.85),
    (35, 39, 118888, 0.90),
    (40, 44, 109383, 0.97),
    (45, 49,  99838, 1.03),
    (50, 54, 101067, 1.08),
    (55, 59,  91994, 1.13),
    (60, 64,  82690, 1.18),
    (65, 90, 217191, 1.15),
]

# Seccion 11.1: brecha de participacion por sexo (INE, Estudio Muestral de
# Participacion Ciudadana 2024). Es DATO, no supuesto.
PARTICIPACION_MUJERES = 0.643
PARTICIPACION_HOMBRES = 0.548

# Composicion de la Lista Nominal de Guadalajara (DERFE-INE, enero de 2026).
PROPORCION_MUJERES_LN = 0.520

# Supuesto explicito: el tiempo de atencion crece con la edad. El documento lo
# afirma cualitativamente (seccion 11.2: el grupo de 65+ "requiere mas tiempo de
# atencion en la mesa directiva") pero no publica un factor numerico, asi que
# este es el unico parametro de este bloque que NO viene del documento. Se deja
# aislado y configurable para poder apagarlo o recalibrarlo.
PENDIENTE_TIEMPO_POR_EDAD = 0.010   # +1 % de tiempo por cada ano sobre la media
EDAD_REFERENCIA_TIEMPO = 45         # edad a la que el factor vale 1.0
FACTOR_TIEMPO_MIN, FACTOR_TIEMPO_MAX = 0.85, 1.50


def _pesos_edad():
    total = sum(t[2] for t in ESTRUCTURA_EDAD_LN)
    return np.array([t[2] / total for t in ESTRUCTURA_EDAD_LN], dtype=float)


def muestrear_edad(rng):
    """Sortea la edad de un elector segun la estructura real de la Lista Nominal.

    Dos pasos: se elige el grupo quinquenal con probabilidad proporcional a sus
    electores, y dentro del grupo se toma un ano uniforme. Es el mismo esquema
    exacto del NHPP (elegir tramo, luego uniforme dentro del tramo).

    Importa mas de lo que parece: la Normal(45, 15) que se usaba antes acierta
    la media (46 anos) pero se queda corta en la cola larga. Genera 9.3 % de
    personas de 65 o mas cuando la lista nominal real tiene 17.7 %, y 16 % de
    60 o mas contra 24 % reales. Como el paso preferente se activa a los 60,
    la fila prioritaria se ejercitaba la mitad de lo que deberia.
    """
    i = int(rng.choice(len(ESTRUCTURA_EDAD_LN), p=_pesos_edad()))
    minimo, maximo, _, _ = ESTRUCTURA_EDAD_LN[i]
    return int(rng.integers(minimo, maximo + 1))


def media_sigma_edad():
    """Media y desviacion teoricas de la estructura de edad de la lista nominal.

    El modelo de utilidad estandariza la edad con (edad - media) / sigma. Si se
    dejaran los 45 / 15 de la Normal vieja, el z-score quedaria descentrado
    respecto a la distribucion que de verdad se esta muestreando.
    """
    pesos = _pesos_edad()
    centros = np.array([(t[0] + t[1]) / 2.0 for t in ESTRUCTURA_EDAD_LN])
    anchos = np.array([t[1] - t[0] + 1 for t in ESTRUCTURA_EDAD_LN], dtype=float)

    media = float((pesos * centros).sum())
    # Varianza total = entre grupos + dentro de cada grupo (uniforme discreta).
    var_entre = float((pesos * (centros - media) ** 2).sum())
    var_dentro = float((pesos * (anchos ** 2 - 1) / 12.0).sum())
    return media, float(np.sqrt(var_entre + var_dentro))


def multiplicador_edad(edad):
    """Multiplicador de participacion del grupo de edad al que pertenece `edad`."""
    for minimo, maximo, _, mult in ESTRUCTURA_EDAD_LN:
        if minimo <= edad <= maximo:
            return mult
    return ESTRUCTURA_EDAD_LN[-1][3] if edad > 90 else ESTRUCTURA_EDAD_LN[0][3]


def _multiplicadores_sexo():
    """Multiplicadores de sexo normalizados a la composicion de la lista nominal.

    Se normalizan para que el promedio ponderado valga exactamente 1: asi la
    brecha documentada de 9.5 puntos se conserva sin desplazar la participacion
    global, que sigue anclada en PARTICIPACION_BASE.
    """
    pm = PROPORCION_MUJERES_LN
    promedio = pm * PARTICIPACION_MUJERES + (1 - pm) * PARTICIPACION_HOMBRES
    return PARTICIPACION_MUJERES / promedio, PARTICIPACION_HOMBRES / promedio


def probabilidad_participacion(edad, genero, base=PARTICIPACION_BASE):
    """Probabilidad de que ESTE elector acuda a votar.

        p_i = base * multiplicador_edad(edad_i) * multiplicador_sexo(genero_i)

    Ambos multiplicadores estan normalizados para que, agregados sobre la
    estructura real de la lista nominal, devuelvan `base`. O sea: la
    participacion global sigue siendo la del documento (61 %); lo que cambia es
    COMO se reparte entre personas, que es justo lo que hace falta para que la
    casilla se llene de adultos mayores a las horas correctas.
    """
    mult_mujer, mult_hombre = _multiplicadores_sexo()
    mult_sexo = mult_mujer if genero == "mujer" else mult_hombre
    return float(np.clip(base * multiplicador_edad(edad) * mult_sexo, 0.0, 1.0))


def factor_tiempo_por_edad(edad):
    """Cuanto mas (o menos) tarda una persona de `edad` en ser atendida.

    SUPUESTO explicito, ver PENDIENTE_TIEMPO_POR_EDAD. Vale 1.0 a los 45 anos.
    """
    factor = 1.0 + PENDIENTE_TIEMPO_POR_EDAD * (edad - EDAD_REFERENCIA_TIEMPO)
    return float(np.clip(factor, FACTOR_TIEMPO_MIN, FACTOR_TIEMPO_MAX))


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
        SE       = s / sqrt(n)                                  [error estandar]
        margen   = z * SE                                       [semiamplitud del IC]
        IC 95 %  = media +/- margen

    OJO con los dos nombres: el ERROR ESTANDAR es s/sqrt(n) y el MARGEN DE
    ERROR es z veces eso (1.96 veces, al 95 %). Hasta antes de esta correccion
    el campo "error_estandar" contenia en realidad el margen -los intervalos
    siempre estuvieron bien calculados, pero reportar ese numero como error
    estandar lo infla por un factor de 1.96-. Se devuelven los dos por separado.

    Devuelve un diccionario listo para serializar a JSON (la API de Unity lo
    consume tal cual). Con una sola muestra no existe dispersion: se devuelve
    desviacion 0 y el intervalo colapsa al punto, y `n` deja claro por que.
    """
    x = np.asarray(list(muestras), dtype=float)
    n = x.size

    if n == 0:
        return {
            "n": 0, "media": None, "desviacion": None, "error_estandar": None,
            "margen_error": None, "ic95_inferior": None, "ic95_superior": None,
        }

    media = float(x.mean())

    if n == 1:
        return {
            "n": 1, "media": media, "desviacion": 0.0, "error_estandar": 0.0,
            "margen_error": 0.0, "ic95_inferior": media, "ic95_superior": media,
        }

    desviacion = float(x.std(ddof=1))               # ddof=1 -> divide entre n-1
    error_estandar = float(desviacion / np.sqrt(n))  # SE, la dispersion de la media
    margen = float(z * error_estandar)               # semiamplitud del IC al 95 %

    return {
        "n": int(n),
        "media": media,
        "desviacion": desviacion,
        "error_estandar": error_estandar,
        "margen_error": margen,
        "ic95_inferior": media - margen,
        "ic95_superior": media + margen,
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

    margen = resumen_ic["margen_error"]
    return f"{media:.{decimales}f} +/- {margen:.{decimales}f}{sufijo} (IC 95 %, n={resumen_ic['n']})"
