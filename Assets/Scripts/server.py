from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# Coordenada X móvil para comprobar en vivo que camina
test_x = 0.0

@app.route("/step", methods=["GET"])
def step():
    global test_x
    test_x += 0.5
    if test_x > 8.0:
        test_x = 0.0

    # Enviamos dos agentes de prueba
    response = {
        "agents": [
            {
                "id": 1,
                "x": float(test_x),
                "y": 2.0,
                "type": "VOTER",
                "status": "WALKING"
            },
            {
                "id": 2,
                "x": 4.0,
                "y": 5.0,
                "type": "VOTER",
                "status": "VOTING"
            }
        ]
    }
    return jsonify(response)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
    