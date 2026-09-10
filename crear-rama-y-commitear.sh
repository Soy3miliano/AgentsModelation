#!/usr/bin/env bash
#
# Crea una rama nueva a partir de integracion-unity-voto y commitea todo el
# trabajo en cuatro commits tematicos, para que el diff se pueda revisar por
# partes en vez de como un solo bloque de 3000 lineas.
#
#   Uso:   bash crear-rama-y-commitear.sh
#
# NO hace push. Al final te dice como hacerlo.

set -euo pipefail
cd "$(dirname "$0")"

RAMA="feature/ui-interactiva-y-modelo-jerarquico"
BASE="integracion-unity-voto"

# ---------------------------------------------------------------- guardas ---
actual="$(git branch --show-current)"
if [ "$actual" != "$BASE" ]; then
    echo "Estas en '$actual' y este script espera '$BASE'."
    echo "Cambiate con:  git checkout $BASE"
    exit 1
fi

if git show-ref --verify --quiet "refs/heads/$RAMA"; then
    echo "La rama '$RAMA' ya existe. Borrala o cambia RAMA en este script."
    exit 1
fi

echo "Creando '$RAMA' a partir de '$BASE'..."
git checkout -b "$RAMA"

# ------------------------------------------- 0. limpieza del stub muerto ---
# Assets/Scripts/server.py era un prototipo de 39 lineas que servia dos agentes
# falsos en /step y escuchaba en el MISMO puerto 5000 que el backend real. Quien
# lo corriera por error veia datos inventados sin ninguna senal de que algo iba
# mal. El README ya lo tenia anotado como pendiente de limpieza.
# `rm -f` + `git add -A` en vez de `git rm`: asi funciona igual si el archivo
# sigue en disco que si ya se borro en un intento anterior.
rm -f Assets/Scripts/server.py Assets/Scripts/server.py.meta
git add -A -- Assets/Scripts/server.py Assets/Scripts/server.py.meta
git add README.md
git commit -m "$(cat <<'EOF'
limpieza: elimina el stub de servidor colado en el proyecto Unity

Assets/Scripts/server.py era una copia vieja de un prototipo: 39 lineas que
devolvian dos agentes falsos en /step y escuchaban en el mismo puerto 5000 que
el backend real de la raiz (394 lineas). Correrlo por equivocacion daba datos
inventados sin ninguna senal de error, y ademas importaba flask_cors, que ni
siquiera esta en requirements.txt.

Se borra junto con su .meta y se quita la nota del README que lo listaba como
pendiente.

EOF
)"

# ------------------------------------------------- 1. modelos estadisticos ---
git add estadistica.py
git commit -m "$(cat <<'EOF'
estadistica: corrige el error estandar y aterriza la demografia al documento

El campo `error_estandar` contenia z*s/sqrt(n), que es el MARGEN DE ERROR, no
el error estandar. Los intervalos siempre estuvieron bien calculados, pero
reportar ese numero como error estandar lo infla por un factor de 1.96. Ahora
se devuelven los dos por separado y `formatear_ic` usa el margen.

Se anade el bloque de heterogeneidad de la seccion 11 del documento, que hasta
ahora estaba documentado pero no implementado:

  - ESTRUCTURA_EDAD_LN: la estructura real de la lista nominal de Guadalajara
    (tabla 20). El modelo sorteaba la edad de una Normal(45,15) inventada que
    acierta la media (46 anos) pero genera 9.3 % de personas de 65 o mas contra
    17.7 % reales. Como el paso preferente arranca a los 60, la fila prioritaria
    se ejercitaba la mitad de lo que deberia.
  - probabilidad_participacion(): 61 % por edad y sexo en vez de una Bernoulli
    plana. La brecha de 9.5 puntos entre mujeres y hombres es dato del INE
    (seccion 11.1) y estaba sin usar; `genero` se sorteaba y nunca se leia.
  - factor_tiempo_por_edad(): unico supuesto nuevo de este bloque, aislado y
    configurable, porque el documento afirma que los mayores tardan mas pero no
    publica un factor.

Verificado: la edad reproduce 17.6 % de 65+ y la participacion agregada queda
en 0.607 contra el 0.61 del documento.

EOF
)"

# --------------------------------------------------- 2. modelo de agentes ---
git add agentes.py main.py replicas.py
git commit -m "$(cat <<'EOF'
agentes: un solo modelo de voto jerarquico, demografia real y sismo forzable

MODELO DE VOTO. Se anade `logit_jerarquico`, que junta los dos modelos que
hasta ahora se excluian en vez de obligar a elegir:

    U_ij = log(p_j^replica) + beta_j^T z_i     con  p^replica ~ Dirichlet(alpha)

El intercepto sale de la Dirichlet del escenario y los atributos del votante lo
desvian. Un votante promedio (z=0) reproduce el escenario exacto porque
softmax(log p) = p. Contiene a los otros dos como casos particulares, y no de
forma aproximada: con `usar_atributos=False` la diferencia contra el categorico
puro es 0.0e+00. Ablacion sobre 20 replicas:

    atributos  Dirichlet   disp.replicas   sep.izq-der
       si         si          2.82 %          72.3 %
       no         si          4.00 %           4.0 %
       si         no          0.99 %          71.8 %

Cada ingrediente controla exactamente una dimension, que es lo que justifica la
complejidad del modelo en vez de tener tres opciones sueltas.

DEMOGRAFIA. La edad, la participacion y los tiempos de servicio pasan a usar el
bloque nuevo de estadistica.py. Efecto sobre 25 replicas de la casilla completa:
prioritarios 22.6 % -> 28.7 %, votos 180 -> 155, espera 41.2 -> 45.8 min.

SATURACION. `estadisticas_corrida` separa el embudo. Antes reportaba un solo
numero llamado "participacion observada" que con la casilla saturada daba 24 %
contra el 61 % del documento, y se leia como si el modelo estuviera mal
calibrado cuando media otra cosa. Ahora: 625 en lista -> 379 acuden (60.6 %) ->
164 votan -> 215 se quedan fuera.

`prob_candidatos` se elimina. Era el vector del voto uniforme anterior al modelo
de utilidad; desde entonces se aceptaba y se ignoraba en silencio, asi que
pasarlo no hacia nada y no avisaba.

`forzar_evento_extraordinario()` dispara el sismo a voluntad sin tocar el sorteo
de prob_terremoto, que con 0.0005 por tick solo aparece en ~14 % de las jornadas.

EOF
)"

# ----------------------------------------------------------- 3. backend ---
git add server.py
git commit -m "$(cat <<'EOF'
server: endpoints de series y sismo, y config aplicada para el HUD

/api/series      cinco series para las graficas de Unity, calculadas al vuelo:
                 llegadas contra el perfil NHPP teorico, histograma de esperas
                 con su IC, piramide de edad, longitud de fila y embudo de
                 saturacion. Una por modelo del documento.
/api/simulacion/sismo   fuerza el evento extraordinario en el tick actual.

/api/tablero y /api/estadisticas ahora reportan `evento_extraordinario`. Sin eso
Unity solo podia inferir el sismo de casilla_abierta=false, que tambien es false
al cerrar por hora: los dos casos eran indistinguibles desde la escena.

`en_vivo` expone la config REALMENTE cargada (lista_nominal, mamparas,
segundos_por_paso) para que el panel confirme con que parametros corre la
casilla y no con los que quedaron en los sliders sin aplicar.

config_default pasa a `logit_jerarquico` y expone los interruptores de ablacion,
la distribucion de edad y la heterogeneidad de participacion.

EOF
)"

# ------------------------------------------------------------- 4. unity ---
# Los .meta van SIEMPRE con su script: sin ellos Unity regenera el GUID en cada
# maquina y las referencias de la escena se rompen para el resto del equipo.
git add Assets/Scripts/ControlesUI.cs Assets/Scripts/ControlesUI.cs.meta \
        Assets/Scripts/GraficasUI.cs Assets/Scripts/GraficasUI.cs.meta \
        Assets/Scripts/ResultadosUI.cs Assets/Scripts/ResultadosUI.cs.meta \
        Assets/Scripts/SimulationManager.cs Assets/Scripts/VotanteAgente.cs
git commit -m "$(cat <<'EOF'
unity: panel de control, resultados a pantalla completa y graficas

Tres paneles que se autoconstruyen al entrar en Play; no hay nada que armar a
mano en SampleScene ni que arrastrar en el Inspector.

ControlesUI   sliders de lista nominal (hasta 625, el N del documento) y de
              jornada (hasta 600 min, las 08:00-18:00 reales), selector del
              modelo con sus dos interruptores de ablacion, escenarios A/B/C/D,
              barra de velocidad x1..x10 y boton de sismo. Confirma en pantalla
              la config que el backend tiene cargada, distinta de la de los
              sliders hasta pulsar aplicar.
ResultadosUI  panel lateral en vivo y resolucion a pantalla completa al cerrar.
GraficasUI    tecla G: una grafica por modelo estadistico del documento.

Se usa UI legacy y no TextMeshPro porque TMP Essentials no esta importado en el
proyecto y habria renderizado texto invisible. El JSON se lee a mano porque
JsonUtility no sabe leer diccionarios con claves arbitrarias como "PAN-PRI",
que es justo la forma de /api/resultados.

CORRECCION IMPORTANTE en SimulationManager: las URLs se normalizan a 127.0.0.1
en Awake. "localhost" resuelve a ::1 antes que a IPv4 y el backend solo escucha
en IPv4, asi que cada conexion desperdiciaba ~2 s esperando el fallback (medido:
2051 ms contra 0.2 ms). Con el sondeo acelerado eso encolaba decenas de
peticiones y el server dev las cortaba con "Curl error 56: Connection was
reset". Se normaliza en codigo y no solo en el default porque la URL vieja esta
serializada dentro de SampleScene. Se anade ademas una guarda para que un sondeo
no se lance si el anterior sigue en vuelo.

VotanteAgente.AjustarRitmo() hace que el agente cruce exactamente una celda por
tick a cualquier velocidad. Con el moveSpeed fijo de 3 u/s y celdas de 4 u,
tardaba 1.33 s en cruzar una celda que el modelo cruza en 1 s: ya iba atrasado
en x1 y en x10 nunca alcanzaba su destino, que es lo que se veia como
movimiento erratico.

EOF
)"

# ------------------------------------- 5. settings que Unity toco solo ---
# Estos cuatro los reescribio el editor al abrir el proyecto, no son trabajo
# nuestro. Van aparte para que sea trivial descartarlos si el equipo prefiere.
if ! git diff --quiet -- Assets/Settings ProjectSettings; then
    git add Assets/Settings ProjectSettings
    git commit -m "$(cat <<'EOF'
chore: settings regenerados por el editor de Unity

Cambios que Unity 6000.5.9f1 escribio solo al abrir el proyecto. No son trabajo
del equipo; van en su propio commit para poder descartarlos con un revert si
generan ruido en los merges.

EOF
)"
fi

# ----------------------------------------------------------------- cierre ---
echo
echo "Listo. Commits nuevos sobre $BASE:"
git --no-pager log --oneline "$BASE..HEAD"
echo
echo "Sin subir todavia. Cuando quieras:"
echo "    git push -u origin $RAMA"
echo
echo "Ojo: '$BASE' tampoco esta en el remoto, asi que este push publicara"
echo "los 12 commits que ya tenia mas estos. Es la primera vez que este"
echo "trabajo sale de tu maquina."
