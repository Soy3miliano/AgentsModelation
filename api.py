import threading
import time

from flask import Flask, jsonify, request

from agentes import ModeloCasilla

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
    return [a.to_dict() for a in casilla.agents]


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


if __name__ == "__main__":
    app.run(debug=True, threaded=True)