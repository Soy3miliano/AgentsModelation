import mesa
import numpy as np

ESTATUS_EN_PROCESO = (
    "PENDING_ENTRANCE", "PENDING_VERIFICATION", "PENDING_VOTE",
    "VOTING", "VOTED", "PENDING_BALLOT", "PENDING_EXIT", "EXITING",
)


class ModeloCasilla(mesa.Model):
    def __init__(
        self,
        n,
        board_size=10,
        hora_cierre=300,
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

        prob_educacion=None,
        ingreso_media=8000.0,
        ingreso_sigma=3000.0,
        ideologia_sigma=1.0,
        beta=None,
    ):
        super().__init__(rng=rng)
        self.num_agentes = n
        self.num_funcionarios = num_funcionarios
        self.tick = 0
        self.board_size = board_size

        self.hora_cierre = hora_cierre     
        self.casilla_abierta = True
        self.finalizada = False

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

        self.candidatos = candidatos or ["Candidato A", "Candidato B", "Candidato C"]
        self.beta = np.array(beta) if beta is not None else self._beta_por_defecto()
        self.resultados = {c: 0 for c in self.candidatos}
        self.votos_emitidos = 0

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
        Es una 'plataforma' ilustrativa (no calibrada con datos reales) pensada
        para los 3 candidatos default. Ver knowledge-base/ para la
        justificacion completa de estos valores."""
        num_features = 5
        if len(self.candidatos) == 3:
            return np.array([
                [0.0,  0.4, -0.1,  0.5,  1.0],   # perfil "derecha": mayores, ingreso alto, ideologia derecha
                [0.0, -0.3,  0.3, -0.4, -1.0],   # perfil "izquierda": jovenes, mas educacion, ideologia izquierda
                [0.0,  0.0,  0.0,  0.0,  0.0],   # perfil "centro": no reacciona a ninguna caracteristica
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

    def get_agent_position(self, agente):
        if isinstance(agente, AgenteFuncionario) or isinstance(agente, AgentePresidente):
            return agente.pos
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
                print(f"Agente: {v.unique_id}, sali de la casilla en el tiempo: {self.tick}")

    def step(self):
        self.process_events()
        print("Time: ", self.tick)

        self.agents.shuffle_do("step")
        self._mover_votantes_un_paso()

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
        }


class AgenteVotante(mesa.Agent):
    def __init__(self, model):
        super().__init__(model)
        self.status = "INACTIVE"
        rng = self.model.rng
        self.tiempo_llegada = rng.exponential(scale=1 / self.model.tasa_llegada)

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

        self.en_revision = False
        self.revisado = False
        self.voto = None

    def can_change_queue(self, old_queue, new_queue, capacity):
        # Desbloqueado: No importa si es el primero de la cola, solo si hay espacio en la siguiente
        return len(new_queue) < capacity

    def change_queue(self, new_status, old_queue=None, new_queue=None):
        # Desbloqueado: Se remueve a sí mismo independientemente de su posición en la lista
        if old_queue and self in old_queue:
            old_queue.remove(self)

        if new_queue is not None:
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

    def handle_voting(self):
        # Utilidad determinista por candidato: U_j = beta_j^T z_i
        utilidades = self.model.beta @ self.vector_caracteristicas()

        # Softmax (resultado de asumir ruido Gumbel en U_ij = beta_j^T z_i + eps_ij):
        # P(X_i = j) = exp(U_j) / sum_l exp(U_l). Restar el maximo antes de exp()
        # evita overflow numerico sin cambiar el resultado.
        utilidades = utilidades - utilidades.max()
        exp_u = np.exp(utilidades)
        probs = exp_u / exp_u.sum()

        self.voto = str(self.model.rng.choice(self.model.candidatos, p=probs))
        self.model.resultados[self.voto] += 1
        self.model.votos_emitidos += 1
        self.status = "VOTED"

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
        }
    
    def step(self):
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
            if not self.model.casilla_abierta:
                self.status = "NO_VOTO"
                return

            if self.model.tick >= self.tiempo_llegada and self.can_change_queue(entrance_queue, entrance_queue, self.model.entrance_queue_capacity):
                if self.pos is None and self.model.grid.is_cell_empty(self.model.puerta_entrada):
                    self.model.grid.place_agent(self, self.model.puerta_entrada)
                    self.change_queue(new_status="PENDING_ENTRANCE", old_queue=None, new_queue=entrance_queue)

        elif self.status == "PENDING_ENTRANCE":
            if self.can_change_queue(entrance_queue, id_queue, id_capacity):
                self.change_queue(new_status="PENDING_VERIFICATION", old_queue=entrance_queue, new_queue=id_queue)

        elif self.status == "PENDING_VERIFICATION":
            if self.revisado and self.can_change_queue(id_queue, booth_queue, booth_capacity):
                self.revisado = False
                self.change_queue(new_status="PENDING_VOTE", old_queue=id_queue, new_queue=booth_queue)

        elif self.status == "PENDING_VOTE":
            if self.can_change_queue(booth_queue, voting_booth, voting_capacity):
                self.change_queue(new_status="VOTING", old_queue=booth_queue, new_queue=voting_booth)
                # Disparamos el tiempo inmediatamente al entrar a la mampara
                wait = self.calculate_voting_time()
                self.model.schedule_event(self.handle_voting, after=wait)

        elif self.status == "VOTING":
            # Espera a que el evento cambie su estatus a VOTED
            pass

        elif self.status == "VOTED":
            if self.can_change_queue(voting_booth, ballot_queue, ballot_capacity):
                self.change_queue(new_status="PENDING_BALLOT", old_queue=voting_booth, new_queue=ballot_queue)

        elif self.status == "PENDING_BALLOT":
            # Pasa directamente a salida, evitando candados de urna
            if self.can_change_queue(ballot_queue, exit_queue, exit_capacity):
                self.change_queue(new_status="PENDING_EXIT", old_queue=ballot_queue, new_queue=exit_queue)

        elif self.status == "PENDING_EXIT":
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

    def step(self):
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
