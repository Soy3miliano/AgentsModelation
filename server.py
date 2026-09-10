import threading
import time

from flask import Flask, jsonify, request

import estadistica as est
from agentes import ModeloCasilla, AgenteVotante

app = Flask(__name__)
 

config_default = {
    "n": 10,
    "board_size": 10,
    "hora_cierre": 300,
    "voting_booth_capacity": 2,
    "review_time_medio": 3,      
    "voting_shape": 4.0,           
    "voting_scale": 1.25,  
    "num_funcionarios": 1,
    "candidatos": ["Movimiento Ciudadano", "MORENA", "PAN-PRI"],

    # Modelos estadisticos (ver estadistica.py). modo_voto se deja en
    # "utilidad" para no alterar lo que Unity ya pinta (3 bloques). Para el
    # modelo Categorico + Dirichlet de 6 categorias basta un POST a
    # /api/simulacion/reset con {"modo_voto": "categorico_dirichlet"}.
    # Un solo modelo, con sus dos ingredientes conmutables. El jerarquico
    # contiene a los otros dos: con usar_atributos=False es exactamente el
    # categorico-Dirichlet, y con sortear_p=False es el clima politico fijo.
    "modo_voto": "logit_jerarquico",
    "escenario": "A",
    "usar_atributos": True,
    "sortear_p": True,

    # Heterogeneidad demografica (documento, seccion 11). Se exponen para poder
    # apagarlas desde Unity y ensenar el contraste en vivo: con ellas apagadas
    # el modelo vuelve a la Normal(45,15) inventada y a la Bernoulli plana.
    "distribucion_edad": "lista_nominal",   # o "normal"
    "participacion_heterogenea": True,
    "tiempos_por_edad": True,
    "perfil_llegadas": "nhpp",
    "participacion": est.PARTICIPACION_BASE,

    # Evento extraordinario (sismo) y perfil de accesibilidad. Se exponen para
    # poder forzarlos desde Unity: con el valor por defecto de 0.0005/tick el
    # sismo aparece en ~14 % de las corridas de 300 ticks, asi que para
    # DEMOSTRAR la evacuacion conviene un POST a /api/simulacion/reset con
    # {"prob_terremoto": 0.05} (o 1.0 para dispararlo en el primer tick).
    "prob_terremoto": 0.0005,
    "prob_discapacidad": 0.06,
}

casilla = ModeloCasilla(**config_default)
lock = threading.Lock() 

simulacion_activa = False
velocidad_tick = 1.0  


def loop_simulacion():
    global simulacion_activa

    while True:
        if simulacion_activa:
            with lock:
                if casilla.running:
                    casilla.step()
                else:
                    simulacion_activa = False
        time.sleep(velocidad_tick)


hilo_simulacion = threading.Thread(target=loop_simulacion, daemon=True)
hilo_simulacion.start()


def _todos_los_agentes():
    """Solo los agentes que estan fisicamente en el tablero.

    Los votantes INACTIVE (aun no llegan), NO_VOTO (se abstuvieron) y DONE (ya
    salieron) tienen pos=None y no deben viajar a Unity: si se mandan, llegan
    como x=null/y=null, JsonUtility los interpreta como (0,0) y terminan
    instanciados y congelados dentro de la escena."""
    return [a.to_dict() for a in casilla.agents if a.pos is not None]


@app.route('/api/spawn', methods=['GET'])
def agente_spawn():
    with lock:
        return jsonify({"votantes_generados": casilla.num_agentes}), 200


@app.route('/api/tablero', methods=['GET'])
def tablero():
    """Endpoint principal para Unity: estado completo del tablero con la
    posicion de cada agente (votantes, funcionarios y presidente)."""
    with lock:
        return jsonify({
            "tamano": {"filas": casilla.board_size, "columnas": casilla.board_size},
            "time": casilla.tick,
            "num_agentes": casilla.num_agentes,
            "simulacion_activa": simulacion_activa,
            "casilla_abierta": casilla.casilla_abierta,
            "finalizada": casilla.finalizada,
            # Sin esto Unity solo podia inferir el sismo de casilla_abierta,
            # que tambien es False al cerrar por hora: no se distinguian.
            "evento_extraordinario": casilla.evento_extraordinario,
            "tick_evento": casilla.tick_evento_extraordinario,
            "agentes": _todos_los_agentes(),
        }), 200


@app.route('/api/elementos', methods=['GET'])
def elementos_fijos():
    with lock:
        return jsonify(casilla.elementos_fijos()), 200


@app.route('/api/agente/<int:agente_id>', methods=['GET'])
def agente_detalle(agente_id):
    with lock:
        agente = next((a for a in casilla.agents if a.unique_id == agente_id), None)

        if agente is None:
            return jsonify({"error": "Agente no encontrado"}), 404

        return jsonify(agente.to_dict()), 200


@app.route('/api/resultados', methods=['GET'])
def resultados():
    """El conteo de votos se mantiene oculto mientras la jornada sigue activa
    (asi como en una casilla real), y se revela hasta que 'finalizada' es True."""
    with lock:
        if not casilla.finalizada:
            return jsonify({
                "disponible": False,
                "mensaje": "La votacion sigue en curso, los resultados se conocen hasta el cierre.",
                "votos_emitidos": casilla.votos_emitidos,
            }), 200

        return jsonify({
            "disponible": True,
            "resultados": casilla.resultados,
            "votos_emitidos": casilla.votos_emitidos,
        }), 200


@app.route('/api/resumen', methods=['GET'])
def resumen():
    with lock:
        return jsonify(casilla.resumen()), 200



@app.route('/api/simulacion/iniciar', methods=['POST'])
def iniciar_simulacion():
    global simulacion_activa
    simulacion_activa = True
    return jsonify({"simulacion_activa": simulacion_activa}), 200


@app.route('/api/simulacion/pausar', methods=['POST'])
def pausar_simulacion():
    global simulacion_activa
    simulacion_activa = False
    return jsonify({"simulacion_activa": simulacion_activa}), 200


@app.route('/api/simulacion/velocidad', methods=['POST'])
def cambiar_velocidad():
    """Body JSON: {"segundos_por_paso": 0.5}"""
    global velocidad_tick
    data = request.get_json(silent=True) or {}
    nueva_velocidad = data.get("segundos_por_paso")

    if not isinstance(nueva_velocidad, (int, float)) or nueva_velocidad <= 0:
        return jsonify({"error": "segundos_por_paso debe ser un numero mayor a 0"}), 400

    velocidad_tick = nueva_velocidad
    return jsonify({"segundos_por_paso": velocidad_tick}), 200


@app.route('/api/simulacion/sismo', methods=['POST'])
def provocar_sismo():
    """Fuerza el evento extraordinario en el tick actual.

    El modelo lo sortea con prob_terremoto (0.0005 por tick), que en una jornada
    de 600 minutos sale ~14 % de las veces: sin este endpoint la evacuacion es
    casi imposible de ensenar en vivo.
    """
    with lock:
        ocurrio = casilla.forzar_evento_extraordinario()
        return jsonify({
            "sismo": casilla.evento_extraordinario,
            "tick": casilla.tick_evento_extraordinario,
            "disparado_ahora": ocurrio,
            "motivo": None if ocurrio else (
                "la jornada ya termino" if casilla.finalizada else "el sismo ya habia ocurrido"),
        }), 200


@app.route('/api/simulacion/reset', methods=['POST'])
def reset_simulacion():
    """Reinicia la simulacion desde cero. Body JSON opcional para configurarla, ej:
    {"n": 20, "hora_cierre": 500, "voting_booth_capacity": 3, "board_size": 10}"""
    global casilla, simulacion_activa
    data = request.get_json(silent=True) or {}

    nueva_config = dict(config_default)
    nueva_config.update({k: v for k, v in data.items() if k in config_default})

    with lock:
        simulacion_activa = False
        casilla = ModeloCasilla(**nueva_config)

    return jsonify({"mensaje": "Simulacion reiniciada", "config": nueva_config}), 200


@app.route('/api/step', methods=['POST'])
def avanzar_paso():
    """Avanza un paso manual, util para debug o un modo 'paso a paso' controlado desde Unity."""
    with lock:
        if casilla.running:
            casilla.step()
        return jsonify(casilla.resumen()), 200


@app.route('/api/estadisticas', methods=['GET'])
def estadisticas():
    """Estadisticas para el HUD de Unity.

    - `en_vivo`: lo que se muestra durante la jornada.
    - `final`: solo al cerrar. Media, desviacion e IC 95 % de cada variable.

    IMPORTANTE: es UNA corrida, no un promedio de replicas. El campo
    `advertencia` trae el texto que debe mostrarse junto a los numeros para no
    dar una falsa idea de precision. Para IC entre replicas correr replicas.py.
    """
    with lock:
        payload = {
            "en_vivo": {
                "minuto_jornada": casilla.tick,
                "duracion_jornada": casilla.hora_cierre,
                # Config REALMENTE en uso, para que Unity confirme en pantalla
                # con que parametros corre la casilla y no con los que quedaron
                # en los sliders sin aplicar.
                "lista_nominal": casilla.num_agentes,
                "mamparas": casilla.voting_booth_capacity,
                "segundos_por_paso": velocidad_tick,
                "votantes_atendidos": casilla.votos_emitidos,
                "personas_formadas": casilla.personas_formadas(),
                "longitud_max_fila": casilla.longitud_max_fila,
                "casilla_abierta": casilla.casilla_abierta,
                "simulacion_activa": simulacion_activa,
                "evento_extraordinario": casilla.evento_extraordinario,
                "tick_evento": casilla.tick_evento_extraordinario,
            },
            "finalizada": casilla.finalizada,
            "modelo": {
                # Unity pinta una barra por candidato desde que arranca la
                # jornada, asi que necesita los nombres antes de que el conteo
                # se revele en /api/resultados (que los oculta hasta el cierre).
                "candidatos": list(casilla.candidatos),
                "modo_voto": casilla.modo_voto,
                "escenario": casilla.escenario,
                "perfil_llegadas": casilla.perfil_llegadas,
            },
            "advertencia": "Resultado de 1 corrida, no es promedio de replicas.",
        }
        payload["final"] = casilla.estadisticas_corrida() if casilla.finalizada else None
        return jsonify(payload), 200


@app.route('/api/escenarios', methods=['GET'])
def escenarios():
    """Catalogo de escenarios y modelos disponibles, para poblar un menu en Unity."""
    return jsonify({
        "escenarios": {
            clave: {
                "nombre": datos["nombre"],
                "descripcion": datos["descripcion"],
                "p": datos["p"],
                "alphas": list(est.alphas_escenario(clave)),
            }
            for clave, datos in est.ESCENARIOS.items()
        },
        "categorias_voto": est.CATEGORIAS_VOTO,
        "modos_voto": ["utilidad", "categorico_dirichlet", "logit_jerarquico"],
        "perfiles_llegada": ["nhpp", "homogeneo"],
    }), 200


@app.route('/api/series', methods=['GET'])
def series():
    """Datos para las graficas de Unity. Una grafica por modelo estadistico,
    siguiendo la estructura de CONCEPTOS_ESTADISTICOS_IMPLEMENTADOS.md:

      - llegadas -> MODELO C (NHPP): observado contra el perfil teorico.
      - espera   -> MODELO D (IC 95 %): histograma con su media e intervalo.
      - edad     -> seccion 11: quien acude, contra quien esta en la lista.
      - fila     -> el nucleo operativo: la cola a lo largo de la jornada.
      - embudo   -> saturacion: de la lista nominal a los votos efectivos.

    Todo se calcula al vuelo del estado actual; no hay serie nueva que guardar.
    """
    with lock:
        votantes = [a for a in casilla.agents if isinstance(a, AgenteVotante)]
        duracion = max(1, casilla.hora_cierre)

        # --- MODELO C: llegadas por tramo contra el NHPP teorico ------------
        tramos = est.PERFIL_HORARIO_NHPP
        escala = duracion / float(tramos[-1][1])
        bordes = [t[0] * escala for t in tramos] + [tramos[-1][1] * escala]
        observado = [0] * len(tramos)
        for v in votantes:
            if not v.acude_a_votar:
                continue
            for i in range(len(tramos)):
                if bordes[i] <= v.tiempo_llegada < bordes[i + 1] or (i == len(tramos) - 1 and v.tiempo_llegada >= bordes[i]):
                    observado[i] += 1
                    break
        total_obs = sum(observado) or 1
        teorico = [float(w) for w in est.pesos_tramos_nhpp()]

        # --- MODELO D: histograma de esperas --------------------------------
        esperas = list(casilla.tiempos_espera)
        ic = est.media_desv_ic95(esperas)
        n_cajas = 12
        tope = max(esperas) if esperas else 1
        ancho = max(1.0, tope / n_cajas)
        histo = [0] * n_cajas
        for e in esperas:
            histo[min(n_cajas - 1, int(e / ancho))] += 1

        # --- Seccion 11: piramide de edad, lista contra quienes acuden ------
        grupos = est.ESTRUCTURA_EDAD_LN
        etiquetas = [f"{g[0]}-{g[1]}" if g[1] < 90 else f"{g[0]}+" for g in grupos]
        en_lista = [0] * len(grupos)
        acuden = [0] * len(grupos)
        for v in votantes:
            for i, (minimo, maximo, _, _) in enumerate(grupos):
                if minimo <= v.edad <= maximo:
                    en_lista[i] += 1
                    if v.acude_a_votar:
                        acuden[i] += 1
                    break

        # --- Cola a lo largo de la jornada (submuestreada para dibujar) -----
        serie = list(casilla.serie_longitud_fila)
        objetivo = 60
        if len(serie) > objetivo:
            paso = len(serie) / objetivo
            serie = [max(serie[int(i * paso):max(int(i * paso) + 1, int((i + 1) * paso))])
                     for i in range(objetivo)]

        # --- Embudo de saturacion -------------------------------------------
        n_acuden = len([v for v in votantes if v.acude_a_votar])

        return jsonify({
            "llegadas": {
                "etiquetas": [t[3] for t in tramos],
                "observado": [o / total_obs for o in observado],
                "teorico": teorico,
                "total": total_obs,
            },
            "espera": {
                "conteo": histo,
                "ancho_caja": ancho,
                "media": ic["media"],
                "ic95_inferior": ic["ic95_inferior"],
                "ic95_superior": ic["ic95_superior"],
                "n": ic["n"],
            },
            "edad": {
                "etiquetas": etiquetas,
                "en_lista": en_lista,
                "acuden": acuden,
            },
            "fila": {
                "serie": serie,
                "maximo": casilla.longitud_max_fila,
                "duracion": duracion,
            },
            "embudo": {
                "lista_nominal": casilla.num_agentes,
                "acudieron": n_acuden,
                "votaron": casilla.votos_emitidos,
                "sin_votar": max(0, n_acuden - casilla.votos_emitidos),
            },
        }), 200


if __name__ == "__main__":
    app.run(debug=True, threaded=True)