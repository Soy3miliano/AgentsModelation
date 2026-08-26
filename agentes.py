import mesa 
import numpy as np

class ModeloCasilla(mesa.Model):    
    def __init__(self, n, rng=None):
        super().__init__(rng=rng)
        self.num_agentes = n

        AgenteVotante.create_agents(model=self, n=n)

        self.entrance_queue = []

        self.id_queue = []
        self.id_queue_capacity = 5

        self.booth_queue = []
        self.booth_queue_capacity = 5

        self.ballot_queue = []
        self.ballot_queue_capacity = 5

        self.exit_queue = []
        self.exit_queue_capacity = 5

        self.voting_booth = []

    def step(self):
        print("Time: ", self.time)

        self.agents.shuffle_do("step")

        print("Fila de Entrada:", [a.unique_id for a in self.entrance_queue])
        print("Fila de ID:", [a.unique_id for a in self.id_queue])
        print("Fila de Booth:", [a.unique_id for a in self.booth_queue])
        print("Agente Votando:", self.voting_booth[0].unique_id if self.voting_booth else 0)
        print("Fila de Ballot:", [a.unique_id for a in self.ballot_queue])
        print("Fila de Salida:", [a.unique_id for a in self.exit_queue])

        print("Terminaron:", len(self.agents.select(lambda a: a.status == "DONE")), "/", self.num_agentes)

        print("-" * 50)


class AgenteVotante(mesa.Agent):
    def __init__(self, model):
        #Inicializacion de Agentes
        super().__init__(model)
        self.status = "INACTIVE"

    def should_activate(self):
        prob = 1 - np.exp(-0.001 * self.model.time)
        return np.random.rand() < prob

    def can_change_queue(self, old_queue, new_queue, capacity):
        return (not old_queue) or (old_queue[0] is self and len(new_queue) < capacity)

    def change_queue(self, new_status, old_queue=None, new_queue=None):
        if old_queue:
            old_queue.pop(0)

        if new_queue is not None:
            new_queue.append(self)

        self.status = new_status

    def handle_voting(self):
        self.status = "VOTED"
    
    def calculate_voting_time(self):
        #Falta calcular bien el tiempo a esperar votantes
        return 5

    def step(self):
        if self.status == "VOTING" or self.status == "DONE": return

        #Colas
        entrance_queue, id_queue, booth_queue, ballot_queue, exit_queue = (
            self.model.entrance_queue, self.model.id_queue, self.model.booth_queue, 
            self.model.ballot_queue, self.model.exit_queue
        )

        #Capacidades
        id_capacity, booth_capacity, ballot_capacity, exit_capacity = (
            self.model.id_queue_capacity, self.model.booth_queue_capacity, 
            self.model.ballot_queue_capacity, self.model.exit_queue_capacity, 
        )

        #Cuarto Votacion
        voting_booth = self.model.voting_booth

        if self.status == "INACTIVE":
            if self.should_activate():
                print(f"Soy el agente {self.unique_id}, me active en el tiempo {self.model.time}")

                self.change_queue(new_status="PENDING_ENTRANCE", new_queue=entrance_queue)

        elif self.status == "PENDING_ENTRANCE":
            if self.can_change_queue(entrance_queue, id_queue, id_capacity):
                self.change_queue(
                    new_status="PENDING_VERIFICATION", 
                    old_queue=entrance_queue,
                    new_queue=id_queue
                )
        
        elif self.status == "PENDING_VERIFICATION":
            if self.can_change_queue(id_queue, booth_queue, booth_capacity):
                self.change_queue(
                    new_status="PENDING_VOTE",
                    old_queue=id_queue,
                    new_queue=booth_queue
                )

        elif self.status == "PENDING_VOTE":
            if self.can_change_queue(booth_queue, voting_booth, 1):
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
                self.change_queue(
                    new_status="DONE",
                    old_queue=exit_queue
                )

                print(f"Agente: {self.unique_id}, sali de la casilla en el tiempo: {self.model.time}")

        else:
            print(f"Estatus Indefinido: {self.status}")