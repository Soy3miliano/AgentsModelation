import mesa

ESTATUS_EN_PROCESO = (
    "PENDING_ENTRANCE", "PENDING_VERIFICATION", "PENDING_VOTE",
    "VOTING", "VOTED", "PENDING_BALLOT", "PENDING_EXIT",
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
        prob_candidatos=None,     
    ):
        super().__init__(rng=rng)
        self.num_agentes = n
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

        self.candidatos = candidatos or ["Candidato A", "Candidato B", "Candidato C"]
        self.prob_candidatos = prob_candidatos or [1 / len(self.candidatos)] * len(self.candidatos)
        self.resultados = {c: 0 for c in self.candidatos}
        self.votos_emitidos = 0

        #Posicion 0 es al inicio
        self.entrance_queue = []
        self.entrance_queue_capacity = board_size

        self.id_queue = []
        self.id_queue_capacity = 5

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

        for i, funcionario in enumerate(self.funcionarios):
            pos = (min(self.board_size - 1, self.board_size - 1), 2 + i)
            self.grid.place_agent(funcionario, pos)

        self.grid.place_agent(self.presidente, (self.board_size - 1, self.board_size - 1))


    def _definir_zonas(self):
        """Define en que fila del tablero vive cada etapa del proceso, y
        calcula las coordenadas disponibles para cada agente segun su
        posicion dentro de la cola correspondiente."""
        w = self.board_size

        def fila(y, capacidad, x_inicio=0):
            return [(x_inicio + i, y) for i in range(capacidad)]

        self.zone_coords = {
            "entrance_queue": fila(0, self.entrance_queue_capacity),
            "id_queue": fila(2, self.id_queue_capacity),
            "booth_queue": fila(4, self.booth_queue_capacity),
            "voting_booth": self._posiciones_centradas(6, self.voting_booth_capacity, w),
            "ballot_queue": fila(8, self.ballot_queue_capacity),
            "exit_queue": fila(9, self.exit_queue_capacity, x_inicio=max(0, w - self.exit_queue_capacity)),
        }

    @staticmethod
    def _posiciones_centradas(y, cantidad, ancho_tablero):
        """Reparte 'cantidad' posiciones (ej. mamparas de votacion) centradas en el ancho del tablero."""
        espacio = ancho_tablero / (cantidad + 1)
        return [(round(espacio * (i + 1)), y) for i in range(cantidad)]

    def elementos_fijos(self):
        """Puntos fijos del escenario (no cambian) para que Unity pueda colocar
        props una sola vez: puerta de entrada, modulo de credenciales, mamparas,
        urna y puerta de salida."""
        return {
            "puerta_entrada": (self.board_size // 2, 0),
            "modulo_id": self.zone_coords["id_queue"][0],
            "mamparas": self.zone_coords["voting_booth"],
            "urna": (self.board_size // 2, 8),
            "puerta_salida": (self.board_size // 2, self.board_size - 1),
        }

    def schedule_event(self, callback, after=0):
        self.event_queue.append((self.tick + after, callback))

    def process_events(self):
        pendientes = [e for e in self.event_queue if e[0] <= self.tick]
        self.event_queue = [e for e in self.event_queue if e[0] > self.tick]
        for _, callback in pendientes:
            callback()

    def get_agent_position(self, agente):
        """Calcula la posicion (x, y) que le corresponde a un agente segun su
        estatus actual y su lugar dentro de la cola correspondiente.
        Regresa None si el agente no debe estar presente en el tablero."""

        if isinstance(agente, AgenteFuncionario):
            return agente.pos  # posicion fija, ya se coloco en __init__
        if isinstance(agente, AgentePresidente):
            return agente.pos  # posicion fija

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
            if agente in cola:
                idx = cola.index(agente)
                return coords[idx % len(coords)]
            return coords[0]

        return None

    def _actualizar_posiciones(self):
        """Sincroniza la posicion de cada votante en el grid de Mesa con su
        estatus logico actual. Se hace en dos pasadas para nunca dejar a dos
        agentes compitiendo por la misma celda en SingleGrid."""

        votantes = [a for a in self.agents if isinstance(a, AgenteVotante)]

        for votante in votantes:
            if votante.pos is not None:
                self.grid.remove_agent(votante)

        for votante in votantes:
            nueva_pos = self.get_agent_position(votante)
            if nueva_pos is not None:
                self.grid.place_agent(votante, nueva_pos)

    def step(self):
        self.process_events()

        print("Time: ", self.tick)

        self.agents.shuffle_do("step")
        self._actualizar_posiciones()

        print("Fila de Entrada:", [a.unique_id for a in self.entrance_queue])
        print("Fila de ID:", [a.unique_id for a in self.id_queue])
        print("Fila de Booth:", [a.unique_id for a in self.booth_queue])
        print("Agentes Votando:", [a.unique_id for a in self.voting_booth])
        print("Fila de Ballot:", [a.unique_id for a in self.ballot_queue])
        print("Fila de Salida:", [a.unique_id for a in self.exit_queue])
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

        self.en_revision = False
        self.revisado = False

        self.voto = None

    def can_change_queue(self, old_queue, new_queue, capacity):
        return (not old_queue) or (old_queue[0] is self and len(new_queue) < capacity)

    def change_queue(self, new_status, old_queue=None, new_queue=None):
        if old_queue:
            old_queue.pop(0)

        if new_queue is not None:
            new_queue.append(self)

        self.status = new_status

    def handle_voting(self):
        """Se dispara cuando termina el tiempo dentro de la mampara: el
        votante elige candidato (distribucion categorica/multinomial segun
        las preferencias configuradas), se registra el voto (de forma
        agregada, para simular el secreto del voto) y libera la mampara."""
        self.voto = str(self.model.rng.choice(self.model.candidatos, p=self.model.prob_candidatos))
        self.model.resultados[self.voto] += 1
        self.model.votos_emitidos += 1
        self.status = "VOTED"

    def calculate_voting_time(self):
        """Tiempo dentro de la mampara: distribucion Gamma (siempre positiva,
        asimetrica a la derecha), tipica para modelar duraciones de servicio."""
        return max(1, int(round(self.model.rng.gamma(self.model.voting_shape, self.model.voting_scale))))

    def to_dict(self):
        x, y = self.pos if self.pos is not None else (None, None)
        return {
            "id": self.unique_id,
            "tipo": "votante",
            "status": self.status,
            "edad": self.edad,
            "genero": self.genero,
            "x": x,
            "y": y,
        }

    def step(self):
        if self.status in ("VOTING", "DONE", "NO_VOTO"):
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

            llego_su_hora = self.model.tick >= self.tiempo_llegada
            if llego_su_hora and len(entrance_queue) < self.model.entrance_queue_capacity:
                print(f"Soy el agente {self.unique_id}, me active en el tiempo {self.model.tick}")
                self.change_queue(new_status="PENDING_ENTRANCE", new_queue=entrance_queue)

        elif self.status == "PENDING_ENTRANCE":
            if self.can_change_queue(entrance_queue, id_queue, id_capacity):
                self.change_queue(
                    new_status="PENDING_VERIFICATION",
                    old_queue=entrance_queue,
                    new_queue=id_queue
                )

        elif self.status == "PENDING_VERIFICATION":
            if self.revisado and self.can_change_queue(id_queue, booth_queue, booth_capacity):
                self.revisado = False
                self.change_queue(
                    new_status="PENDING_VOTE",
                    old_queue=id_queue,
                    new_queue=booth_queue
                )

        elif self.status == "PENDING_VOTE":
            if self.can_change_queue(booth_queue, voting_booth, voting_capacity):
                self.change_queue(
                    new_status="VOTING",
                    old_queue=booth_queue,
                    new_queue=voting_booth
                )

                wait = self.calculate_voting_time()
                self.model.schedule_event(self.handle_voting, after=wait)

        elif self.status == "VOTED":
            if len(ballot_queue) < ballot_capacity:
                self.change_queue(
                    new_status="PENDING_BALLOT",
                    old_queue=voting_booth,
                    new_queue=ballot_queue
                )

        elif self.status == "PENDING_BALLOT":
            if self.can_change_queue(ballot_queue, exit_queue, exit_capacity):
                self.change_queue(
                    new_status="PENDING_EXIT",
                    old_queue=ballot_queue,
                    new_queue=exit_queue
                )

        elif self.status == "PENDING_EXIT":
            if not exit_queue or exit_queue[0] is self:
                self.change_queue(new_status="DONE", old_queue=exit_queue)
                print(f"Agente: {self.unique_id}, sali de la casilla en el tiempo: {self.model.tick}")

        else:
            print(f"Estatus Indefinido: {self.status}")


class AgenteFuncionario(mesa.Agent):
    """Revisa la credencial de elector de quien esta al frente de la fila de
    identificacion. Mientras un votante esta 'en_revision', no puede avanzar
    a la fila de mamparas hasta que termine su revision."""

    def __init__(self, model):
        super().__init__(model)

    def review_id(self, votante):
        """El tiempo de revision sigue una distribucion Exponencial (comun
        para modelar tiempos de servicio en teoria de colas)."""
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
        id_queue = self.model.id_queue
        if not id_queue:
            return

        votante = id_queue[0]
        if not votante.en_revision and not votante.revisado:
            self.review_id(votante)


class AgentePresidente(mesa.Agent):
    """Administra la jornada: cierra la entrada al llegar la hora de cierre
    y determina cuando la simulacion ha terminado por completo."""

    def __init__(self, model):
        super().__init__(model)

    def to_dict(self):
        x, y = self.pos if self.pos is not None else (None, None)
        return {"id": self.unique_id, "tipo": "presidente", "x": x, "y": y}

    def step(self):
        if self.model.casilla_abierta and self.model.tick >= self.model.hora_cierre:
            self.model.casilla_abierta = False
            print(f"El presidente de casilla cierra la entrada en el tiempo {self.model.tick}")

        if not self.model.casilla_abierta and not self.model.finalizada:
            votantes = [a for a in self.model.agents if isinstance(a, AgenteVotante)]
            quedan_pendientes = any(v.status in ESTATUS_EN_PROCESO or v.status == "INACTIVE" for v in votantes)

            if not quedan_pendientes:
                self.model.finalizada = True
                self.model.running = False
                print(f"Jornada electoral terminada en el tiempo {self.model.tick}. Resultados: {self.model.resultados}")