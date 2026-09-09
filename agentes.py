import mesa
import numpy as np

import estadistica as est

ESTATUS_EN_PROCESO = (
    "PENDING_ENTRANCE", "PENDING_VERIFICATION", "PENDING_VOTE",
    "VOTING", "VOTED", "PENDING_BALLOT", "PENDING_EXIT", "EXITING",
)

# Umbral de edad (anios) a partir del cual un votante se considera "adulto
# mayor" para efectos de prioridad en fila (igual que en una casilla real:
# adultos mayores y personas con discapacidad votan sin hacer fila).
UMBRAL_ADULTO_MAYOR = 60


class ModeloCasilla(mesa.Model):
    def __init__(
        self,
        n,
        board_size=10,
        hora_cierre=est.DURACION_JORNADA,
        voting_booth_capacity=2,
        num_funcionarios=1,
        candidatos=None,
        rng=None,

        # --- Modelos estadisticos formales (ver estadistica.py) ---
        # modo_voto: "utilidad"            -> logit multinomial con la matriz beta (original)
        #            "categorico_dirichlet" -> MODELO A + B: p ~ Dirichlet por replica
        #                                      y voto ~ Categorical(p) por agente
        modo_voto="utilidad",
        escenario="A",
        concentracion_dirichlet=None,
        p_replica=None,
        # perfil_llegadas: "nhpp" (MODELO C, por defecto) u "homogeneo" (fallback simple)
        perfil_llegadas="nhpp",
        participacion=est.PARTICIPACION_BASE,
        verbose=True,

        tasa_llegada=0.05,
        edad_media=45,
        edad_sigma=15,
        prob_genero_m=0.5,
        review_time_medio=3,
        voting_shape=4.0,
        voting_scale=1.25,

        prob_educacion=None,
        ingreso_media=8000.0,
        ingreso_sigma=3000.0,
        ideologia_sigma=1.0,
        beta=None,
        prob_terremoto=0.0005,
        prob_discapacidad=0.06,
    ):
        super().__init__(rng=rng)
        self.num_agentes = n
        self.num_funcionarios = num_funcionarios
        self.tick = 0
        self.board_size = board_size
        self.verbose = verbose

        self.hora_cierre = hora_cierre     
        self.casilla_abierta = True
        self.finalizada = False

        # --- Evento extraordinario (sismo) ---
        # Probabilidad (baja) de que ocurra un sismo en cada tick. Cuando
        # ocurre, se suspenden las votaciones y el presidente se convierte
        # en un "faro" que lidera la evacuacion hacia la zona segura.
        self.prob_terremoto = prob_terremoto
        self.evento_extraordinario = False
        self.tick_evento_extraordinario = None
        self.zona_segura = (board_size // 2, board_size // 2)
        self.tick_llegada_zona_segura = None

        # --- Prioridad en fila (adultos mayores y personas con discapacidad) ---
        # Probabilidad de que un votante tenga alguna discapacidad (ensayo
        # Bernoulli independiente de la edad). Ser adulto mayor se deriva
        # directamente de la edad ya muestreada (ver UMBRAL_ADULTO_MAYOR),
        # asi que no necesita su propio parametro de probabilidad.
        self.prob_discapacidad = prob_discapacidad

        self.tasa_llegada = tasa_llegada
        self.edad_media = edad_media
        self.edad_sigma = edad_sigma
        self.prob_genero_m = prob_genero_m
        self.review_time_medio = review_time_medio
        self.voting_shape = voting_shape
        self.voting_scale = voting_scale

        # Distribucion de educacion (ordinal: 0=basica, 1=media, 2=universidad, 3=posgrado).
        # Se guarda la media/sigma teoricas de esta distribucion para poder normalizar
        # el atributo de cada agente igual que se hace con la edad.
        self.prob_educacion = prob_educacion or [0.25, 0.35, 0.30, 0.10]
        niveles_educacion = [0, 1, 2, 3]
        self.educacion_media = sum(n * p for n, p in zip(niveles_educacion, self.prob_educacion))
        self.educacion_sigma = (
            sum(p * (n - self.educacion_media) ** 2 for n, p in zip(niveles_educacion, self.prob_educacion)) ** 0.5
        )

        self.ingreso_media = ingreso_media
        self.ingreso_sigma = ingreso_sigma
        self.ideologia_sigma = ideologia_sigma

        # --- Configuracion del modelo de voto -------------------------------
        # Los dos modos conviven a proposito: "utilidad" es el logit multinomial
        # calibrado con la matriz beta y "categorico_dirichlet" es el modelo
        # jerarquico Dirichlet-Multinomial del documento de fundamentacion.
        self.modo_voto = modo_voto
        self.escenario = escenario
        self.perfil_llegadas = perfil_llegadas
        self.participacion = participacion

        if modo_voto == "categorico_dirichlet":
            # Las categorias las fija la tabla del escenario (6 opciones,
            # incluyendo nulo y candidatura no registrada), no el argumento
            # `candidatos`, para que el vector p y las etiquetas no se
            # desalineen nunca.
            if candidatos is not None and len(candidatos) != len(est.CATEGORIAS_VOTO):
                print(
                    f"Aviso: modo_voto='categorico_dirichlet' usa las "
                    f"{len(est.CATEGORIAS_VOTO)} categorias del escenario "
                    f"'{escenario}'; se ignoran los {len(candidatos)} candidatos recibidos."
                )
            self.candidatos = list(est.CATEGORIAS_VOTO)

            self.alphas_dirichlet = est.alphas_escenario(
                escenario,
                concentracion_dirichlet or est.CONCENTRACION_DIRICHLET,
            )
            # MODELO B: un solo sorteo de p POR REPLICA (aqui, por instancia del
            # modelo = una corrida). Todos los votos de esta corrida usan este
            # mismo p; la variacion entre corridas es lo que aporta la Dirichlet.
            if p_replica is not None:
                self.p_replica = np.asarray(p_replica, dtype=float)
            else:
                self.p_replica = est.muestrear_dirichlet(self.alphas_dirichlet, self.rng)
        else:
            self.candidatos = candidatos or ["Movimiento Ciudadano", "MORENA", "PAN-PRI"]
            self.alphas_dirichlet = None
            self.p_replica = None

        if beta is not None:
            self.beta = np.array(beta)
        elif self.modo_voto == "utilidad":
            self.beta = self._beta_por_defecto()
        else:
            # En modo categorico la matriz beta no se usa; no tiene sentido
            # advertir que no hay calibracion para 6 categorias.
            self.beta = None

        self.resultados = {c: 0 for c in self.candidatos}
        self.votos_emitidos = 0

        # --- Metricas de salida (MODELO D) ----------------------------------
        # Se acumulan durante la corrida para poder reportar media, desviacion
        # e IC 95 % al final, en vez de un solo numero suelto.
        self.tiempos_espera = []       # minutos de cola antes de entrar a la mampara
        self.tiempos_en_sistema = []   # minutos totales dentro de la casilla
        self.longitud_max_fila = 0
        self.serie_longitud_fila = []

        self.entrance_queue = []
        self.entrance_queue_capacity = max(1, board_size - 2)
        self.id_queue = []
        self.id_queue_capacity = 4
        self.booth_queue = []
        self.booth_queue_capacity = 5
        self.voting_booth = []
        self.voting_booth_capacity = voting_booth_capacity
        self.ballot_queue = []
        self.ballot_queue_capacity = 5
        self.exit_queue = []
        self.exit_queue_capacity = 5
        self.event_queue = []

        self.grid = mesa.space.SingleGrid(board_size, board_size, torus=False)
        self._definir_zonas()

        AgenteVotante.create_agents(model=self, n=n)
        self.funcionarios = AgenteFuncionario.create_agents(model=self, n=num_funcionarios)
        self.presidente = AgentePresidente.create_agents(model=self, n=1)[0]

        self._colocar_agentes_fijos()

    def _beta_por_defecto(self):
        """Matriz beta (K x 5) por defecto: una fila por candidato, columnas
        [intercepto, edad_norm, educacion_norm, ingreso_norm, ideologia].

        Calibrada al contexto real de la casilla simulada (Seccion 1250,
        Distrito Electoral Federal 09 de Jalisco, Col. Oblatos,
        Guadalajara) para los 3 bloques politicos que compiten ahi:
        Movimiento Ciudadano (fuerza dominante en la Zona Metropolitana
        de Guadalajara), MORENA (base amplia y de menor ingreso, con
        ventaja estructural adicional en una colonia popular como
        Oblatos) y PAN-PRI (debilitado en Jalisco frente a su fuerza
        nacional). Es una lectura razonada del contexto real, NO datos
        de encuesta oficiales de la seccion 1250 (no existen a ese
        nivel de granularidad). Ver
        ../REPORTE-CONTRADICCIONES-MODELO-SIMULACION.md y
        MODELO_DECISION_VOTO.md para la justificacion completa."""
        num_features = 5
        if len(self.candidatos) == 3:
            return np.array([
                [ 0.3, -0.1,  0.3,  0.4,  0.1],   # Movimiento Ciudadano: base urbana/clase media, no definido en el eje izq-der
                [ 0.5,  0.1, -0.2, -0.5, -0.9],   # MORENA: base amplia de menor ingreso, ventaja estructural en Oblatos
                [-0.4,  0.5, -0.1,  0.4,  1.0],   # PAN-PRI: mayor edad/ingreso, ideologia derecha, debilitado en Jalisco
            ])
        print(
            f"Aviso: no hay beta por defecto para {len(self.candidatos)} candidatos; "
            "usando perfiles neutros (voto uniforme por diseno). Pase `beta` explicitamente."
        )
        return np.zeros((len(self.candidatos), num_features))

    def _definir_zonas(self):
        w = self.board_size
        self.puerta_entrada = (0, 9)
        self.puerta_salida = (9, 9)

        # Mapeo físico estricto sin diagonales cruzadas
        self.zone_coords = {
            "entrance_queue": [(0, y) for y in range(5, 9)], 
            "id_queue": [(0, y) for y in range(1, 5)],       
            "booth_queue": [(5, y) for y in range(8, 3, -1)], 
            "voting_booth": [(5, 9)],                         
            "ballot_queue": [(2, y) for y in range(0, 5)],    
            "exit_queue": [(9, y) for y in range(8, 3, -1)],  
        }

        self.entrance_queue_capacity = len(self.zone_coords["entrance_queue"])
        self.id_queue_capacity = len(self.zone_coords["id_queue"])
        self.booth_queue_capacity = len(self.zone_coords["booth_queue"])
        self.voting_booth_capacity = len(self.zone_coords["voting_booth"])
        self.ballot_queue_capacity = len(self.zone_coords["ballot_queue"])
        self.exit_queue_capacity = len(self.zone_coords["exit_queue"])

    @staticmethod
    def _posiciones_centradas(y, cantidad, ancho_tablero):
        espacio = ancho_tablero / (cantidad + 1)
        return [(round(espacio * (i + 1)), y) for i in range(cantidad)]

    def _colocar_agentes_fijos(self):
        for i, funcionario in enumerate(self.funcionarios):
            self.grid.place_agent(funcionario, (i, 0))

        pos_presi = (len(self.funcionarios), 0)
        self.grid.place_agent(self.presidente, pos_presi)

    def elementos_fijos(self):
        return {
            "puerta_entrada": self.puerta_entrada,
            "puerta_salida": self.puerta_salida,
            "modulo_id": self.zone_coords["id_queue"][0],
            "mamparas": self.zone_coords["voting_booth"],
            "urna": self.zone_coords["ballot_queue"][0],
            "funcionarios": [f.pos for f in self.funcionarios],
            "presidente": self.presidente.pos,
        }

    def schedule_event(self, callback, after=0):
        self.event_queue.append((self.tick + after, callback))

    def process_events(self):
        pendientes = [e for e in self.event_queue if e[0] <= self.tick]
        self.event_queue = [e for e in self.event_queue if e[0] > self.tick]
        for _, callback in pendientes:
            callback()

    def _chequear_evento_extraordinario(self):
        """En cada tick, mientras no haya ocurrido ya un evento extraordinario
        y la jornada no haya finalizado, existe una probabilidad baja
        (self.prob_terremoto) de que ocurra un sismo. Al activarse, se
        suspenden las votaciones: todos los agentes votantes dejan de
        avanzar en sus tramites y el presidente lidera la evacuacion."""
        if self.evento_extraordinario or self.finalizada:
            return

        if self.rng.random() < self.prob_terremoto:
            self.evento_extraordinario = True
            self.tick_evento_extraordinario = self.tick

            # El sismo cierra la casilla de inmediato (ya no es una decision
            # normal de hora de cierre, sino una emergencia).
            self.casilla_abierta = False

            # Se vacian las filas: los agentes que estaban formados dejan de
            # estar "en cola" (cada uno pasa a EN_EVACUACION en su propio
            # step de este mismo tick, ver AgenteVotante) y siguen al
            # presidente en lugar de esperar su turno.
            self.entrance_queue.clear()
            self.id_queue.clear()
            self.booth_queue.clear()
            self.voting_booth.clear()
            self.ballot_queue.clear()
            self.exit_queue.clear()

            if self.verbose:
                print(f"¡EVENTO EXTRAORDINARIO! Sismo detectado en el tiempo {self.tick}. "
                      f"Se cierra la casilla, se suspenden las votaciones y el presidente "
                      f"lidera la evacuacion.")

    def get_agent_position(self, agente):
        if isinstance(agente, AgenteFuncionario) or isinstance(agente, AgentePresidente):
            return agente.pos

        if agente.status == "EN_EVACUACION":
            # Durante el evento extraordinario, el votante ya no se dirige a
            # su cola habitual: sigue al presidente (el "faro") hacia la
            # zona segura.
            return self.presidente.pos

        if agente.status == "EXITING":
            return self.puerta_salida

        status_a_cola = {
            "PENDING_ENTRANCE": ("entrance_queue", self.entrance_queue),
            "PENDING_VERIFICATION": ("id_queue", self.id_queue),
            "PENDING_VOTE": ("booth_queue", self.booth_queue),
            "VOTING": ("voting_booth", self.voting_booth),
            "VOTED": ("voting_booth", self.voting_booth),
            "PENDING_BALLOT": ("ballot_queue", self.ballot_queue),
            "PENDING_EXIT": ("exit_queue", self.exit_queue),
        }

        if agente.status in status_a_cola:
            zona, cola = status_a_cola[agente.status]
            coords = self.zone_coords[zona]
            
            if zona == "voting_booth":
                if agente in cola:
                    idx = cola.index(agente)
                    return coords[idx % len(coords)]
                return coords[0]
            else:
                return coords[0] 
                
        return None

    def _mover_votantes_un_paso(self):
        votantes = [a for a in self.agents if isinstance(a, AgenteVotante) and a.status not in ("INACTIVE", "NO_VOTO", "DONE")]
        ocupante_por_celda = {v.pos: v for v in votantes if v.pos is not None}

        deseos = {}
        for v in votantes:
            if v.pos is None:
                deseos[v] = self.puerta_entrada
                continue

            objetivo = self.get_agent_position(v)
            if objetivo is None or objetivo == v.pos:
                continue

            dx = (objetivo[0] > v.pos[0]) - (objetivo[0] < v.pos[0])
            dy = (objetivo[1] > v.pos[1]) - (objetivo[1] < v.pos[1])
            deseos[v] = (v.pos[0] + dx, v.pos[1] + dy)

        orden = sorted(deseos, key=lambda a: a.unique_id)
        reservadas = {self.presidente.pos} | {f.pos for f in self.funcionarios}
        resuelto = {}

        cambio = True
        while cambio:
            cambio = False
            for v in orden:
                if v in resuelto:
                    continue

                destino = deseos[v]

                if destino in reservadas:
                    resuelto[v] = False
                    cambio = True
                    continue

                ocupante = ocupante_por_celda.get(destino)

                if ocupante is None:
                    resuelto[v] = True
                    reservadas.add(destino)
                    cambio = True
                elif ocupante not in deseos:
                    resuelto[v] = False
                    cambio = True
                elif ocupante in resuelto:
                    if resuelto[ocupante] and deseos[ocupante] != v.pos:
                        resuelto[v] = True
                        reservadas.add(destino)
                    else:
                        resuelto[v] = False
                    cambio = True

        for v in orden:
            resuelto.setdefault(v, False) 

        # Detección de Deadlocks
        pendientes = [v for v in orden if not resuelto[v]]
        visitados_globales = set()
        for v in pendientes:
            if v in visitados_globales: continue
            cadena = []
            actual = v
            while actual not in cadena and actual in pendientes:
                cadena.append(actual)
                destino = deseos[actual]
                ocupante = ocupante_por_celda.get(destino)
                if ocupante and not resuelto.get(ocupante, False):
                    actual = ocupante
                else: break
            if actual in cadena:
                idx = cadena.index(actual)
                ciclo = cadena[idx:]
                es_valido = True
                for i, nodo in enumerate(ciclo):
                    siguiente = ciclo[(i + 1) % len(ciclo)]
                    if deseos[nodo] != siguiente.pos:
                        es_valido = False
                        break
                if es_valido:
                    for nodo in ciclo:
                        resuelto[nodo] = True
                        reservadas.add(deseos[nodo])
                        visitados_globales.add(nodo)
            for nodo in cadena:
                visitados_globales.add(nodo)


        moventes = [v for v in orden if resuelto[v]]
        for v in moventes:
            if v.pos is not None:
                self.grid.remove_agent(v)

        for v in moventes:
            destino = deseos[v]
            self.grid.place_agent(v, destino)
            if v.status == "EXITING" and destino == self.puerta_salida:
                v.status = "DONE"
                self.grid.remove_agent(v)
                # MODELO D: tiempo total dentro de la casilla.
                v.tick_salida = self.tick
                if v.tick_entrada is not None:
                    self.tiempos_en_sistema.append(self.tick - v.tick_entrada)
                if self.verbose:
                    print(f"Agente: {v.unique_id}, sali de la casilla en el tiempo: {self.tick}")

    def personas_formadas(self):
        """Total de votantes haciendo fila en este instante (todas las colas)."""
        return (
            len(self.entrance_queue) + len(self.id_queue) + len(self.booth_queue)
            + len(self.ballot_queue) + len(self.exit_queue)
        )

    def step(self):
        self.process_events()
        self._chequear_evento_extraordinario()
        if self.verbose:
            print("Time: ", self.tick)

        self.agents.shuffle_do("step")
        self._mover_votantes_un_paso()

        # MODELO D: la longitud de fila es una variable de salida, hay que
        # registrarla en cada paso y no solo imprimirla.
        formados = self.personas_formadas()
        self.serie_longitud_fila.append(formados)
        self.longitud_max_fila = max(self.longitud_max_fila, formados)

        if self.verbose:
            print("Fila Entrada:", len(self.entrance_queue), "| ID:", len(self.id_queue), "| Booth:", len(self.booth_queue), "| Ballot:", len(self.ballot_queue), "| Exit:", len(self.exit_queue))
            print("Terminaron:", len(self.agents.select(lambda a: getattr(a, "status", None) == "DONE")), "/", self.num_agentes)
            print("-" * 50)

        self.tick += 1

    def resumen(self):
        votantes = [a for a in self.agents if isinstance(a, AgenteVotante)]
        return {
            "time": self.tick,
            "casilla_abierta": self.casilla_abierta,
            "finalizada": self.finalizada,
            "total_agentes": self.num_agentes,
            "terminaron": len([a for a in votantes if a.status == "DONE"]),
            "no_votaron": len([a for a in votantes if a.status == "NO_VOTO"]),
            "en_proceso": len([a for a in votantes if a.status in ESTATUS_EN_PROCESO]),
            "votos_emitidos": self.votos_emitidos,
            # Claves nuevas (aditivas: no rompen a quien ya lee las anteriores)
            "personas_formadas": self.personas_formadas(),
            "longitud_max_fila": self.longitud_max_fila,
            "modo_voto": self.modo_voto,
            "escenario": self.escenario,
            "perfil_llegadas": self.perfil_llegadas,
            "evento_extraordinario": self.evento_extraordinario,
        }

    def estadisticas_corrida(self):
        """MODELO D aplicado a UNA corrida: media, desviacion e IC 95 % de las
        variables de salida, calculados sobre los votantes de esta corrida.

        Ojo con la interpretacion: aqui la unidad de observacion es el VOTANTE
        (cuanto espero cada persona), no la replica. Para el intervalo de
        confianza sobre el comportamiento del SISTEMA hay que promediar entre
        replicas: eso lo hace replicas.py.
        """
        proporciones = {}
        if self.votos_emitidos > 0:
            proporciones = {
                c: self.resultados[c] / self.votos_emitidos for c in self.candidatos
            }

        return {
            "corrida_unica": True,
            "nota": (
                "Resultado de 1 corrida. Los intervalos describen la dispersion "
                "ENTRE VOTANTES, no entre replicas. Use replicas.py para el IC "
                "del sistema."
            ),
            "tiempo_espera": est.media_desv_ic95(self.tiempos_espera),
            "tiempo_en_sistema": est.media_desv_ic95(self.tiempos_en_sistema),
            "longitud_fila": est.media_desv_ic95(self.serie_longitud_fila),
            "longitud_max_fila": self.longitud_max_fila,
            "proporcion_voto": proporciones,
            "votos_emitidos": self.votos_emitidos,
            "participacion_observada": (
                self.votos_emitidos / self.num_agentes if self.num_agentes else 0.0
            ),
            "p_replica": (
                list(self.p_replica) if self.p_replica is not None else None
            ),
        }


class AgenteVotante(mesa.Agent):
    def __init__(self, model):
        super().__init__(model)
        self.status = "INACTIVE"
        rng = self.model.rng

        # MODELO C: momento de llegada a la casilla.
        # Por defecto se usa el proceso de Poisson NO homogeneo (tasa constante
        # por tramos horarios); el proceso homogeneo queda como modo simple.
        if self.model.perfil_llegadas == "nhpp":
            self.tiempo_llegada = est.muestrear_tiempo_llegada_nhpp(
                rng, duracion_jornada=self.model.hora_cierre
            )
        else:
            self.tiempo_llegada = est.muestrear_tiempo_llegada_homogeneo(
                rng, self.model.tasa_llegada
            )

        # No todos los inscritos en la lista nominal acuden: la participacion
        # historica es del 61 % (documento de fundamentacion, seccion 7.2).
        # Es un ensayo Bernoulli por elector.
        self.acude_a_votar = rng.random() < self.model.participacion

        # Marcas de tiempo para las metricas del MODELO D.
        self.tick_entrada = None
        self.tick_salida = None

        while True:
            edad = int(round(rng.normal(self.model.edad_media, self.model.edad_sigma)))
            if 18 <= edad <= 90:
                self.edad = edad
                break

        self.genero = "M" if rng.random() < self.model.prob_genero_m else "F"

        self.educacion = int(rng.choice([0, 1, 2, 3], p=self.model.prob_educacion))

        while True:
            ingreso = rng.normal(self.model.ingreso_media, self.model.ingreso_sigma)
            if ingreso >= 0:
                self.ingreso = ingreso
                break

        self.ideologia = rng.normal(0, self.model.ideologia_sigma)

        # --- Prioridad en fila ---
        # Los adultos mayores (umbral por edad) y las personas con
        # discapacidad (ensayo Bernoulli) tienen prioridad: se les exime del
        # limite de cupo de cada fila y se colocan al frente de ellas (ver
        # can_change_queue / change_queue), por lo que en la practica se
        # "saltan la fila" para llegar directo con el funcionario y a votar.
        self.es_adulto_mayor = self.edad >= UMBRAL_ADULTO_MAYOR
        self.tiene_discapacidad = rng.random() < self.model.prob_discapacidad
        self.prioridad = self.es_adulto_mayor or self.tiene_discapacidad

        self.en_revision = False
        self.revisado = False
        self.voto = None

    def can_change_queue(self, old_queue, new_queue, capacity):
        if self.prioridad:
            # Adultos mayores y personas con discapacidad tienen prioridad:
            # no se les aplica el limite de cupo de la siguiente fila.
            return True
        # Desbloqueado: No importa si es el primero de la cola, solo si hay espacio en la siguiente
        return len(new_queue) < capacity

    def ha_llegado(self):
        """True si el agente ya alcanzo fisicamente la celda que le corresponde
        para su estatus actual. Se exige antes de avanzar de cola para que el
        estado logico no se adelante al fisico: si no, varios agentes pueden
        "ocupar" un cupo logico de la siguiente cola sin haber llegado nunca
        a la celda desde la que se sale, taponando el pasillo (deadlock)."""
        if self.pos is None:
            return False
        return self.pos == self.model.get_agent_position(self)

    def change_queue(self, new_status, old_queue=None, new_queue=None):
        # Desbloqueado: Se remueve a sí mismo independientemente de su posición en la lista
        if old_queue and self in old_queue:
            old_queue.remove(self)

        if new_queue is not None:
            if self.prioridad:
                # Prioridad: se coloca al frente de la fila (posicion 0) en
                # vez de al final. Como get_agent_position asigna la celda
                # segun el indice del agente dentro de la cola (coords[idx]),
                # esto lo manda directo a la celda mas cercana a la siguiente
                # etapa -la del funcionario o la de la mampara-, saltandose
                # fisicamente a quienes ya estaban formados.
                new_queue.insert(0, self)
            else:
                new_queue.append(self)

        self.status = new_status

    def vector_caracteristicas(self):
        """Vector z_i = [1, edad_norm, educacion_norm, ingreso_norm, ideologia]
        usado por el modelo de utilidad U_ij = beta_j^T z_i. Las variables
        continuas se normalizan (z-score) con la media/sigma de su
        distribucion en el modelo, igual que ya se hacia con la edad."""
        m = self.model
        edad_norm = (self.edad - m.edad_media) / m.edad_sigma
        educacion_norm = (self.educacion - m.educacion_media) / m.educacion_sigma
        ingreso_norm = (self.ingreso - m.ingreso_media) / m.ingreso_sigma
        return np.array([1.0, edad_norm, educacion_norm, ingreso_norm, self.ideologia])

    def probabilidades_voto(self):
        """Vector de probabilidades p sobre las k opciones de la boleta.

        De donde sale p depende del modo configurado en el modelo:

        - "utilidad": logit multinomial. Cada agente tiene SU PROPIO p,
          derivado de sus atributos via U_j = beta_j^T z_i + softmax.
        - "categorico_dirichlet": todos los agentes de la corrida comparten el
          mismo p, sorteado una sola vez de la Dirichlet (MODELO B).
        """
        if self.model.modo_voto == "categorico_dirichlet":
            return self.model.p_replica

        # Utilidad determinista por candidato: U_j = beta_j^T z_i
        utilidades = self.model.beta @ self.vector_caracteristicas()

        # Softmax (resultado de asumir ruido Gumbel en U_ij = beta_j^T z_i + eps_ij):
        # P(X_i = j) = exp(U_j) / sum_l exp(U_l). Restar el maximo antes de exp()
        # evita overflow numerico sin cambiar el resultado.
        utilidades = utilidades - utilidades.max()
        exp_u = np.exp(utilidades)
        return exp_u / exp_u.sum()

    def handle_voting(self):
        if self.model.evento_extraordinario:
            # Las votaciones estan suspendidas por el evento extraordinario:
            # este voto (programado antes del sismo) ya no se registra.
            return

        # MODELO A: el voto es una extraccion de una distribucion categorica
        # Categorical(p) de longitud k arbitraria (no hay k fijado en el codigo).
        self.voto = est.muestrear_voto_categorico(
            self.probabilidades_voto(),
            self.model.rng,
            etiquetas=self.model.candidatos,
        )
        self.model.resultados[self.voto] += 1
        self.model.votos_emitidos += 1
        self.status = "VOTED"

        # MODELO D: tiempo de espera en fila = desde que entro a la casilla
        # hasta que empezo a votar en la mampara.
        if self.tick_entrada is not None:
            self.model.tiempos_espera.append(self.model.tick - self.tick_entrada)

    def _reaccionar_a_evento_extraordinario(self):
        """Cuando ocurre el evento extraordinario (sismo), el votante
        suspende cualquier tramite de votacion en el que estuviera y pasa a
        seguir al presidente de casilla -convertido en un "faro"- rumbo a
        la zona segura. Los agentes que aun no habian entrado a la casilla,
        o que ya terminaron/no votaron, no se ven afectados."""
        if self.status in ("INACTIVE", "DONE", "NO_VOTO"):
            return

        self.en_revision = False
        self.status = "EN_EVACUACION"

    def calculate_voting_time(self):
        return max(1, int(round(self.model.rng.gamma(self.model.voting_shape, self.model.voting_scale))))

    def to_dict(self):
        x, y = self.pos if self.pos is not None else (None, None)
        return {
            "id": self.unique_id,
            "tipo": "votante",
            "status": self.status,
            "edad": self.edad,
            "genero": self.genero,
            "educacion": self.educacion,
            "ingreso": round(self.ingreso, 2),
            "ideologia": round(self.ideologia, 3),
            "x": x,
            "y": y,
            "prioridad": self.prioridad,
        }
    
    def step(self):
        if self.model.evento_extraordinario:
            self._reaccionar_a_evento_extraordinario()
            return

        if self.status in ("DONE", "NO_VOTO", "EXITING"):
            return

        entrance_queue, id_queue, booth_queue, ballot_queue, exit_queue = (
            self.model.entrance_queue, self.model.id_queue, self.model.booth_queue,
            self.model.ballot_queue, self.model.exit_queue
        )

        id_capacity, booth_capacity, ballot_capacity, exit_capacity, voting_capacity = (
            self.model.id_queue_capacity, self.model.booth_queue_capacity,
            self.model.ballot_queue_capacity, self.model.exit_queue_capacity,
            self.model.voting_booth_capacity,
        )

        voting_booth = self.model.voting_booth

        if self.status == "INACTIVE":
            # Abstencion: el elector estaba en la lista nominal pero no acude.
            if not self.acude_a_votar:
                self.status = "NO_VOTO"
                return

            if not self.model.casilla_abierta:
                self.status = "NO_VOTO"
                return

            if self.model.tick >= self.tiempo_llegada and self.can_change_queue(entrance_queue, entrance_queue, self.model.entrance_queue_capacity):
                if self.pos is None and self.model.grid.is_cell_empty(self.model.puerta_entrada):
                    self.model.grid.place_agent(self, self.model.puerta_entrada)
                    self.tick_entrada = self.model.tick
                    self.change_queue(new_status="PENDING_ENTRANCE", old_queue=None, new_queue=entrance_queue)

        elif self.status == "PENDING_ENTRANCE":
            if self.ha_llegado() and self.can_change_queue(entrance_queue, id_queue, id_capacity):
                self.change_queue(new_status="PENDING_VERIFICATION", old_queue=entrance_queue, new_queue=id_queue)

        elif self.status == "PENDING_VERIFICATION":
            if self.revisado and self.ha_llegado() and self.can_change_queue(id_queue, booth_queue, booth_capacity):
                self.revisado = False
                self.change_queue(new_status="PENDING_VOTE", old_queue=id_queue, new_queue=booth_queue)

        elif self.status == "PENDING_VOTE":
            if self.ha_llegado() and self.can_change_queue(booth_queue, voting_booth, voting_capacity):
                self.change_queue(new_status="VOTING", old_queue=booth_queue, new_queue=voting_booth)
                # Disparamos el tiempo inmediatamente al entrar a la mampara
                wait = self.calculate_voting_time()
                self.model.schedule_event(self.handle_voting, after=wait)

        elif self.status == "VOTING":
            # Espera a que el evento cambie su estatus a VOTED
            pass

        elif self.status == "VOTED":
            if self.ha_llegado() and self.can_change_queue(voting_booth, ballot_queue, ballot_capacity):
                self.change_queue(new_status="PENDING_BALLOT", old_queue=voting_booth, new_queue=ballot_queue)

        elif self.status == "PENDING_BALLOT":
            # Pasa directamente a salida, evitando candados de urna
            if self.ha_llegado() and self.can_change_queue(ballot_queue, exit_queue, exit_capacity):
                self.change_queue(new_status="PENDING_EXIT", old_queue=ballot_queue, new_queue=exit_queue)

        elif self.status == "PENDING_EXIT":
            if self.ha_llegado():
                self.change_queue(new_status="EXITING", old_queue=exit_queue)


class AgenteFuncionario(mesa.Agent):
    def __init__(self, model):
        super().__init__(model)

    def review_id(self, votante):
        votante.en_revision = True
        duracion = max(1, int(round(self.model.rng.exponential(self.model.review_time_medio))))
        self.model.schedule_event(lambda: self._completar_revision(votante), after=duracion)

    @staticmethod
    def _completar_revision(votante):
        votante.en_revision = False
        votante.revisado = True

    def to_dict(self):
        x, y = self.pos if self.pos is not None else (None, None)
        return {"id": self.unique_id, "tipo": "funcionario", "x": x, "y": y}

    def step(self):
        if not self.model.id_queue:
            return

        # Verifica quién está físicamente en la mesa, no solo lógicamente
        posicion_frente = self.model.zone_coords["id_queue"][0]
        votante_frente = next((v for v in self.model.id_queue if v.pos == posicion_frente), None)

        if not votante_frente:
            return  

        if not votante_frente.en_revision and not votante_frente.revisado:
            self.review_id(votante_frente)


class AgentePresidente(mesa.Agent):
    def __init__(self, model):
        super().__init__(model)

    def to_dict(self):
        x, y = self.pos if self.pos is not None else (None, None)
        return {"id": self.unique_id, "tipo": "presidente", "x": x, "y": y}

    def liderar_evacuacion(self):
        """Cuando ocurre el evento extraordinario, el presidente deja su
        posicion fija y se convierte en un "faro": avanza un paso por tick
        hacia la zona segura del tablero. El resto de los agentes presentes
        (los votantes, ver AgenteVotante._reaccionar_a_evento_extraordinario
        y ModeloCasilla.get_agent_position) toman su posicion como objetivo
        en cada tick, por lo que terminan siguiendolo hacia la seguridad."""
        if self.pos is None or self.pos == self.model.zona_segura:
            return

        x, y = self.pos
        tx, ty = self.model.zona_segura
        dx = (tx > x) - (tx < x)
        dy = (ty > y) - (ty < y)
        destino = (x + dx, y + dy)

        if self.model.grid.is_cell_empty(destino):
            self.model.grid.remove_agent(self)
            self.model.grid.place_agent(self, destino)
            return

        # El camino esta ocupado. Si quien lo bloquea es un votante que lo
        # esta siguiendo, no se espera: se intercambian de lugar (el
        # seguidor pasa a ocupar la celda que el presidente deja libre).
        # Sin esto, un seguidor justo delante del presidente y el propio
        # presidente quedarian esperandose mutuamente para siempre (cada
        # uno es, a su vez, el objetivo de movimiento del otro; la deteccion
        # generica de ciclos de ModeloCasilla._mover_votantes_un_paso no
        # incluye al presidente, ya que el se mueve por su cuenta aqui).
        (ocupante,) = self.model.grid.get_cell_list_contents([destino]) or (None,)
        if isinstance(ocupante, AgenteVotante) and ocupante.status == "EN_EVACUACION":
            origen = self.pos
            self.model.grid.remove_agent(self)
            self.model.grid.remove_agent(ocupante)
            self.model.grid.place_agent(self, destino)
            self.model.grid.place_agent(ocupante, origen)
        # si es un funcionario u otro elemento fijo, se espera sin romper la formacion

    def _verificar_evacuacion_completa(self):
        """Determina si la evacuacion ya termino, para poder cerrar la
        simulacion en lugar de quedarse en un bucle infinito una vez que el
        evento extraordinario esta activo (la logica normal de cierre y
        finalizacion queda en pausa mientras dura la emergencia, ver step).
        Se considera completa cuando el presidente (el "faro") llega a la
        zona segura y, ademas, transcurre un margen de ticks -del tamano del
        tablero- para dar tiempo a que los votantes que lo siguen alcancen a
        agruparse junto a el. Como red de seguridad adicional (por si algun
        bloqueo residual impidiera la llegada), tambien se fuerza el cierre
        pasado un tiempo maximo desde que ocurrio el sismo."""
        margen_maximo = 5 * self.model.board_size
        if (self.model.tick_evento_extraordinario is not None
                and self.model.tick >= self.model.tick_evento_extraordinario + margen_maximo):
            self.model.finalizada = True
            self.model.running = False
            if self.model.verbose:
                print(f"Evacuacion forzada a terminar en el tiempo {self.model.tick} "
                      f"(tiempo maximo de emergencia alcanzado).")
            return

        if self.pos != self.model.zona_segura:
            return

        if self.model.tick_llegada_zona_segura is None:
            self.model.tick_llegada_zona_segura = self.model.tick
            return

        margen = self.model.board_size
        if self.model.tick >= self.model.tick_llegada_zona_segura + margen:
            self.model.finalizada = True
            self.model.running = False
            if self.model.verbose:
                print(f"Evacuacion completada en el tiempo {self.model.tick}: "
                      f"el presidente llevo a todos los presentes a la zona segura.")

    def step(self):
        if self.model.evento_extraordinario:
            # Durante el evento extraordinario el presidente se dedica por
            # completo a liderar la evacuacion; la logica normal de cierre
            # de casilla y finalizacion (mas abajo) queda en pausa mientras
            # dure la emergencia.
            self.liderar_evacuacion()
            self._verificar_evacuacion_completa()
            return

        if self.model.casilla_abierta and self.model.tick >= self.model.hora_cierre:
            self.model.casilla_abierta = False
            print(f"El presidente cierra la entrada en el tiempo {self.model.tick}")

        if not self.model.casilla_abierta and not self.model.finalizada:
            votantes = [a for a in self.model.agents if isinstance(a, AgenteVotante)]
            quedan_pendientes = any(v.status in ESTATUS_EN_PROCESO or v.status == "INACTIVE" for v in votantes)

            if not quedan_pendientes:
                self.model.finalizada = True
                self.model.running = False
                print(f"Jornada terminada. Resultados: {self.model.resultados}")