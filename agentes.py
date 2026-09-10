import mesa
import numpy as np
import estadistica as est

ESTATUS_EN_PROCESO = (
    "PENDING_ENTRANCE", "PENDING_VERIFICATION", "PENDING_VOTE",
    "VOTING", "VOTED", "PENDING_BALLOT", "PENDING_EXIT", "EXITING",
    "EN_EVACUACION",
)

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
        tasa_llegada=0.05,
        edad_media=45,
        edad_sigma=15,
        prob_genero_m=0.5,
        review_time_medio=3,
        voting_shape=4.0,
        voting_scale=1.25,
        prob_candidatos=None,
        modo_voto="utilidad",
        escenario="A",
        concentracion_dirichlet=None,
        p_replica=None,
        perfil_llegadas="nhpp",
        participacion=est.PARTICIPACION_BASE,
        verbose=True,
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

        # Emergencia / Sismo
        self.prob_terremoto = prob_terremoto
        self.evento_extraordinario = False
        self.tick_evento_extraordinario = None
        self.zona_segura = (board_size // 2, board_size // 2)
        self.tick_llegada_zona_segura = None

        # Atributos sociodemográficos y colas
        self.prob_discapacidad = prob_discapacidad
        self.tasa_llegada = tasa_llegada
        self.edad_media = edad_media
        self.edad_sigma = edad_sigma
        self.prob_genero_m = prob_genero_m
        self.review_time_medio = review_time_medio
        self.voting_shape = voting_shape
        self.voting_scale = voting_scale
        # Cuantas mamparas simultaneas se piden; _definir_zonas genera una celda por cada una.
        self.mamparas_solicitadas = max(1, int(voting_booth_capacity))

        self.prob_educacion = prob_educacion or [0.25, 0.35, 0.30, 0.10]
        niveles_educacion = [0, 1, 2, 3]
        self.educacion_media = sum(n * p for n, p in zip(niveles_educacion, self.prob_educacion))
        self.educacion_sigma = (
            sum(p * (n - self.educacion_media) ** 2 for n, p in zip(niveles_educacion, self.prob_educacion)) ** 0.5
        )
        self.ingreso_media = ingreso_media
        self.ingreso_sigma = ingreso_sigma
        self.ideologia_sigma = ideologia_sigma

        # Modelos estadísticos de votación
        self.modo_voto = modo_voto
        self.escenario = escenario
        self.perfil_llegadas = perfil_llegadas
        self.participacion = participacion

        if modo_voto == "categorico_dirichlet":
            self.candidatos = list(est.CATEGORIAS_VOTO)
            self.alphas_dirichlet = est.alphas_escenario(
                escenario, concentracion_dirichlet or est.CONCENTRACION_DIRICHLET
            )
            self.p_replica = np.asarray(p_replica, dtype=float) if p_replica is not None else est.muestrear_dirichlet(self.alphas_dirichlet, self.rng)
        else:
            self.candidatos = candidatos or ["Movimiento Ciudadano", "MORENA", "PAN-PRI"]
            self.alphas_dirichlet = None
            self.p_replica = None

        if beta is not None:
            self.beta = np.array(beta)
        elif self.modo_voto == "utilidad":
            self.beta = self._beta_por_defecto()
        else:
            self.beta = None

        self.prob_candidatos = prob_candidatos or [1 / len(self.candidatos)] * len(self.candidatos)
        self.resultados = {c: 0 for c in self.candidatos}
        self.votos_emitidos = 0

        # Métricas de salida (Modelo D)
        self.tiempos_espera = []
        self.tiempos_en_sistema = []
        self.longitud_max_fila = 0
        self.serie_longitud_fila = []

        self.entrance_queue = []
        self.id_queue = []
        self.priority_queue = []   # fila exclusiva para adultos mayores / discapacidad
        self.booth_queue = []
        self.voting_booth = []
        self.ballot_queue = []
        self.exit_queue = []
        self.event_queue = []

        self.grid = mesa.space.SingleGrid(board_size, board_size, torus=False)
        self._definir_zonas()

        AgenteVotante.create_agents(model=self, n=n)
        self.funcionarios = AgenteFuncionario.create_agents(model=self, n=num_funcionarios)
        self.presidente = AgentePresidente.create_agents(model=self, n=1)[0]
        self._colocar_agentes_fijos()

    def _beta_por_defecto(self):
        num_features = 5
        if len(self.candidatos) == 3:
            return np.array([
                [ 0.3, -0.1,  0.3,  0.4,  0.1],
                [ 0.5,  0.1, -0.2, -0.5, -0.9],
                [-0.4,  0.5, -0.1,  0.4,  1.0],
            ])
        return np.zeros((len(self.candidatos), num_features))

    def _definir_zonas(self):
        w = self.board_size
        self.puerta_entrada = (0, 9)
        self.puerta_salida = (9, 9)

        # Una celda de mampara por cada voto simultaneo pedido. Van en la fila 8
        # (no en la 9, pegada al muro superior) para que el rectangulo 3D de la
        # mampara no se incruste en la pared. La cola arranca justo debajo, en 7.
        num_mamparas = max(1, min(self.mamparas_solicitadas, w - 1 - 5))
        mamparas = [(5 + i, 8) for i in range(num_mamparas)]

        # El modulo de identificacion (mesa) ocupa la celda (0,1): el funcionario
        # esta detras en (0,0) y la fila empieza DELANTE de la mesa, en (0,2).
        # Ningun votante pisa (0,1), asi la mesa se comporta como bloque solido.
        self.modulo_id_pos = (0, 1)

        self.zone_coords = {
            "entrance_queue": [(0, y) for y in range(5, 9)],
            "id_queue": [(0, y) for y in range(2, 5)],
            # Fila prioritaria: columna x=1, paralela a la fila normal. El
            # funcionario atiende SIEMPRE primero a quien esté en su frente (1,2).
            "priority_queue": [(1, y) for y in range(2, 5)],
            "booth_queue": [(5, y) for y in range(7, 2, -1)],
            "voting_booth": mamparas,
            # Urna en la esquina inferior derecha (w-1, 0). La cola crece hacia la
            # izquierda por el borde inferior para no chocar con exit_queue, que
            # ocupa la pared derecha (columna w-1, filas 4-8).
            "ballot_queue": [(x, 0) for x in range(w - 1, w - 6, -1)],
            "exit_queue": [(9, y) for y in range(8, 3, -1)],
        }

        self.entrance_queue_capacity = len(self.zone_coords["entrance_queue"])
        self.id_queue_capacity = len(self.zone_coords["id_queue"])
        self.priority_queue_capacity = len(self.zone_coords["priority_queue"])
        self.booth_queue_capacity = len(self.zone_coords["booth_queue"])
        self.voting_booth_capacity = len(self.zone_coords["voting_booth"])
        self.ballot_queue_capacity = len(self.zone_coords["ballot_queue"])
        self.exit_queue_capacity = len(self.zone_coords["exit_queue"])

    def _colocar_agentes_fijos(self):
        for i, funcionario in enumerate(self.funcionarios):
            self.grid.place_agent(funcionario, (i, 0))
        pos_presi = (len(self.funcionarios), 0)
        self.grid.place_agent(self.presidente, pos_presi)

    def elementos_fijos(self):
        return {
            "puerta_entrada": self.puerta_entrada,
            "puerta_salida": self.puerta_salida,
            "modulo_id": self.modulo_id_pos,
            "fila_prioritaria": self.zone_coords["priority_queue"],
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
        if self.evento_extraordinario or self.finalizada:
            return
        if self.rng.random() < self.prob_terremoto:
            self.evento_extraordinario = True
            self.tick_evento_extraordinario = self.tick
            self.casilla_abierta = False
            self.entrance_queue.clear()
            self.id_queue.clear()
            self.priority_queue.clear()
            self.booth_queue.clear()
            self.voting_booth.clear()
            self.ballot_queue.clear()
            self.exit_queue.clear()
            if self.verbose:
                print(f"¡SISMO EN EL TICK {self.tick}! Evacuando con el presidente.")

    def get_agent_position(self, agente):
        if isinstance(agente, (AgenteFuncionario, AgentePresidente)):
            return agente.pos
        if agente.status == "EN_EVACUACION":
            return self.presidente.pos
        if agente.status == "EXITING":
            return self.puerta_salida

        if agente.status == "PENDING_VERIFICATION":
            zona = "priority_queue" if agente.prioridad else "id_queue"
            return self.zone_coords[zona][0]

        status_a_cola = {
            "PENDING_ENTRANCE": ("entrance_queue", self.entrance_queue),
            "PENDING_VOTE": ("booth_queue", self.booth_queue),
            "VOTING": ("voting_booth", self.voting_booth),
            "VOTED": ("voting_booth", self.voting_booth),
            "PENDING_BALLOT": ("ballot_queue", self.ballot_queue),
            "PENDING_EXIT": ("exit_queue", self.exit_queue),
        }

        if agente.status in status_a_cola:
            zona, _cola = status_a_cola[agente.status]
            coords = self.zone_coords[zona]
            if zona == "voting_booth":
                # La mampara se reserva al entrar y no se reasigna, para que el
                # agente no se mueva de casilla cuando otro termina de votar.
                return agente.mampara or coords[0]
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
                if v in resuelto: continue
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

        # Rompedor de deadlocks
        pendientes = [v for v in orden if not resuelto[v]]
        visitados_globales = set()
        for v in pendientes:
            if v in visitados_globales: continue
            cadena, actual = [], v
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
                es_valido = all(deseos[nodo] == ciclo[(i + 1) % len(ciclo)].pos for i, nodo in enumerate(ciclo))
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
                v.tick_salida = self.tick
                if v.tick_entrada is not None:
                    self.tiempos_en_sistema.append(self.tick - v.tick_entrada)
                if self.verbose:
                    print(f"Agente {v.unique_id} salió en el tick {self.tick}")

    def personas_formadas(self):
        return sum(len(q) for q in [self.entrance_queue, self.id_queue, self.priority_queue, self.booth_queue, self.ballot_queue, self.exit_queue])

    def step(self):
        self.process_events()
        self._chequear_evento_extraordinario()
        self.agents.shuffle_do("step")
        self._mover_votantes_un_paso()

        formados = self.personas_formadas()
        self.serie_longitud_fila.append(formados)
        self.longitud_max_fila = max(self.longitud_max_fila, formados)

        if self.verbose:
            print("Time:", self.tick, "| Formados:", formados, "| Votos:", self.votos_emitidos)
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
            "personas_formadas": self.personas_formadas(),
            "longitud_max_fila": self.longitud_max_fila,
            "modo_voto": self.modo_voto,
            "escenario": self.escenario,
            "perfil_llegadas": self.perfil_llegadas,
            "evento_extraordinario": self.evento_extraordinario,
        }

    def estadisticas_corrida(self):
        proporciones = {c: self.resultados[c] / self.votos_emitidos for c in self.candidatos} if self.votos_emitidos > 0 else {}
        return {
            "corrida_unica": True,
            "tiempo_espera": est.media_desv_ic95(self.tiempos_espera),
            "tiempo_en_sistema": est.media_desv_ic95(self.tiempos_en_sistema),
            "longitud_fila": est.media_desv_ic95(self.serie_longitud_fila),
            "longitud_max_fila": self.longitud_max_fila,
            "proporcion_voto": proporciones,
            "votos_emitidos": self.votos_emitidos,
            "participacion_observada": (self.votos_emitidos / self.num_agentes if self.num_agentes else 0.0),
            "p_replica": list(self.p_replica) if self.p_replica is not None else None,
        }


class AgenteVotante(mesa.Agent):
    def __init__(self, model):
        super().__init__(model)
        self.status = "INACTIVE"
        rng = self.model.rng

        if self.model.perfil_llegadas == "nhpp":
            self.tiempo_llegada = est.muestrear_tiempo_llegada_nhpp(rng, duracion_jornada=self.model.hora_cierre)
        else:
            self.tiempo_llegada = est.muestrear_tiempo_llegada_homogeneo(rng, self.model.tasa_llegada)

        self.acude_a_votar = rng.random() < self.model.participacion
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

        self.es_adulto_mayor = self.edad >= UMBRAL_ADULTO_MAYOR
        self.tiene_discapacidad = rng.random() < self.model.prob_discapacidad
        self.prioridad = self.es_adulto_mayor or self.tiene_discapacidad

        self.en_revision = False
        self.revisado = False
        self.voto = None
        self.mampara = None  # celda de mampara reservada mientras vota

    def can_change_queue(self, old_queue, new_queue, capacity):
        if self.prioridad:
            return True
        return len(new_queue) < capacity

    def change_queue(self, new_status, old_queue=None, new_queue=None):
        if old_queue and self in old_queue:
            old_queue.remove(self)
        if new_queue is not None:
            new_queue.append(self)
        self.status = new_status

    def ha_llegado(self):
        """Fuerza al agente a caminar físicamente hasta su waypoint antes de cambiar de estado."""
        if self.pos is None:
            return False
        return self.pos == self.model.get_agent_position(self)

    def vector_caracteristicas(self):
        m = self.model
        edad_norm = (self.edad - m.edad_media) / m.edad_sigma
        educacion_norm = (self.educacion - m.educacion_media) / m.educacion_sigma
        ingreso_norm = (self.ingreso - m.ingreso_media) / m.ingreso_sigma
        return np.array([1.0, edad_norm, educacion_norm, ingreso_norm, self.ideologia])

    def probabilidades_voto(self):
        if self.model.modo_voto == "categorico_dirichlet":
            return self.model.p_replica
        utilidades = self.model.beta @ self.vector_caracteristicas()
        utilidades = utilidades - utilidades.max()
        exp_u = np.exp(utilidades)
        return exp_u / exp_u.sum()

    def handle_voting(self):
        if self.model.evento_extraordinario:
            return
        self.voto = est.muestrear_voto_categorico(
            self.probabilidades_voto(), self.model.rng, etiquetas=self.model.candidatos
        )
        self.model.resultados[self.voto] += 1
        self.model.votos_emitidos += 1
        self.status = "VOTED"
        if self.tick_entrada is not None:
            self.model.tiempos_espera.append(self.model.tick - self.tick_entrada)

    def _reaccionar_a_evento_extraordinario(self):
        if self.status in ("INACTIVE", "DONE", "NO_VOTO"):
            return
        self.en_revision = False
        self.mampara = None
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
            if not self.acude_a_votar or not self.model.casilla_abierta:
                self.status = "NO_VOTO"
                return
            if self.model.tick >= self.tiempo_llegada and self.can_change_queue(entrance_queue, entrance_queue, self.model.entrance_queue_capacity):
                if self.pos is None and self.model.grid.is_cell_empty(self.model.puerta_entrada):
                    self.model.grid.place_agent(self, self.model.puerta_entrada)
                    self.tick_entrada = self.model.tick
                    self.change_queue(new_status="PENDING_ENTRANCE", old_queue=None, new_queue=entrance_queue)

        elif self.status == "PENDING_ENTRANCE":
            # Adultos mayores / discapacidad van a su fila prioritaria; el resto a la normal.
            if self.prioridad:
                mi_cola, mi_capacidad = self.model.priority_queue, self.model.priority_queue_capacity
            else:
                mi_cola, mi_capacidad = id_queue, id_capacity
            if self.ha_llegado() and self.can_change_queue(entrance_queue, mi_cola, mi_capacidad):
                self.change_queue(new_status="PENDING_VERIFICATION", old_queue=entrance_queue, new_queue=mi_cola)

        elif self.status == "PENDING_VERIFICATION":
            # Debe caminar hasta el frente de SU fila y ser revisado por el funcionario.
            mi_cola = self.model.priority_queue if self.prioridad else id_queue
            if self.ha_llegado() and self.revisado and self.can_change_queue(mi_cola, booth_queue, booth_capacity):
                self.revisado = False
                self.change_queue(new_status="PENDING_VOTE", old_queue=mi_cola, new_queue=booth_queue)

        elif self.status == "PENDING_VOTE":
            if self.ha_llegado() and self.can_change_queue(booth_queue, voting_booth, voting_capacity):
                ocupadas = {v.mampara for v in voting_booth if v.mampara is not None}
                libres = [c for c in self.model.zone_coords["voting_booth"] if c not in ocupadas]
                if not libres:
                    return
                self.mampara = libres[0]
                self.change_queue(new_status="VOTING", old_queue=booth_queue, new_queue=voting_booth)
                wait = self.calculate_voting_time()
                self.model.schedule_event(self.handle_voting, after=wait)

        elif self.status == "VOTING":
            pass

        elif self.status == "VOTED":
            if self.ha_llegado() and self.can_change_queue(voting_booth, ballot_queue, ballot_capacity):
                self.change_queue(new_status="PENDING_BALLOT", old_queue=voting_booth, new_queue=ballot_queue)
                self.mampara = None  # libera la mampara para el siguiente votante

        elif self.status == "PENDING_BALLOT":
            # Pasa de inmediato a la fila de salida una vez pise la urna
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
        # Se atiende SIEMPRE primero la fila prioritaria; si su frente está vacío,
        # se pasa a la fila normal.
        for zona, cola in (("priority_queue", self.model.priority_queue),
                           ("id_queue", self.model.id_queue)):
            if not cola:
                continue
            posicion_frente = self.model.zone_coords[zona][0]
            votante_frente = next((v for v in cola if v.pos == posicion_frente), None)
            if votante_frente and not votante_frente.en_revision and not votante_frente.revisado:
                self.review_id(votante_frente)
                return


class AgentePresidente(mesa.Agent):
    def __init__(self, model):
        super().__init__(model)

    def to_dict(self):
        x, y = self.pos if self.pos is not None else (None, None)
        return {"id": self.unique_id, "tipo": "presidente", "x": x, "y": y}

    def liderar_evacuacion(self):
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

        (ocupante,) = self.model.grid.get_cell_list_contents([destino]) or (None,)
        if isinstance(ocupante, AgenteVotante) and ocupante.status == "EN_EVACUACION":
            origen = self.pos
            self.model.grid.remove_agent(self)
            self.model.grid.remove_agent(ocupante)
            self.model.grid.place_agent(self, destino)
            self.model.grid.place_agent(ocupante, origen)

    def _verificar_evacuacion_completa(self):
        margen_maximo = 5 * self.model.board_size
        if (self.model.tick_evento_extraordinario is not None
                and self.model.tick >= self.model.tick_evento_extraordinario + margen_maximo):
            self.model.finalizada = True
            self.model.running = False
            return

        if self.pos != self.model.zona_segura:
            return
        if self.model.tick_llegada_zona_segura is None:
            self.model.tick_llegada_zona_segura = self.model.tick
            return

        if self.model.tick >= self.model.tick_llegada_zona_segura + self.model.board_size:
            self.model.finalizada = True
            self.model.running = False

    def step(self):
        if self.model.evento_extraordinario:
            self.liderar_evacuacion()
            self._verificar_evacuacion_completa()
            return

        if self.model.casilla_abierta and self.model.tick >= self.model.hora_cierre:
            self.model.casilla_abierta = False

        if not self.model.casilla_abierta and not self.model.finalizada:
            votantes = [a for a in self.model.agents if isinstance(a, AgenteVotante)]
            quedan_pendientes = any(v.status in ESTATUS_EN_PROCESO or v.status == "INACTIVE" for v in votantes)
            if not quedan_pendientes:
                self.model.finalizada = True
                self.model.running = False