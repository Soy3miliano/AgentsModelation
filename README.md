# AgentsModelation — Simulación de casilla electoral

Modelo basado en agentes (Python + Mesa) de una casilla de votación, con una
visualización 3D en Unity que consume el estado por HTTP.

```
backend (Python/Flask)  ──►  /api/tablero, /api/elementos, ...  ──►  Unity (cliente)
```

## Requisitos

| Parte | Necesitas |
|---|---|
| Backend | Python 3.10+ y las libs de `requirements.txt` (`mesa`, `numpy`, `flask`) |
| Visualización | **Unity 6000.5.9f1** (exacta), vía Unity Hub |

> La versión de Unity tiene que ser la misma. Está fijada en
> `ProjectSettings/ProjectVersion.txt`. Si Unity Hub no la lista, usa
> "Install Editor → Archive" y busca `6000.5.9f1`.

## Puesta en marcha

### 1. Clonar

```bash
git clone https://github.com/Soy3miliano/AgentsModelation.git
cd AgentsModelation
git checkout ajustes-layout-y-unity   # o main, una vez mergeado el PR
```

### 2. Backend

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
python server.py
```

Queda escuchando en `http://localhost:5000`. Endpoints principales:

| Endpoint | Uso |
|---|---|
| `GET /api/tablero` | Estado + posición de cada agente (lo que consume Unity cada tick) |
| `GET /api/elementos` | Posición de muebles fijos (puertas, mesa ID, urna, mamparas, fila prioritaria) |
| `POST /api/simulacion/iniciar` \| `/pausar` | Arranca / pausa el reloj |
| `POST /api/simulacion/reset` | Reinicia. Body JSON opcional: `{"n":30,"hora_cierre":60,"voting_booth_capacity":2}` |
| `GET /api/resumen` | Métricas de la corrida |

### 3. Unity

1. Abre **Unity Hub → Add → project from disk** y selecciona la carpeta del repo.
2. Ábrelo con la versión `6000.5.9f1`. **El primer arranque tarda varios
   minutos**: reconstruye `Library/`, importa todos los assets y restaura los
   paquetes de `Packages/manifest.json`. Es normal.
3. Abre la escena `Assets/Scenes/SampleScene.unity`.
4. Con `server.py` corriendo, dale **Play**.

## Controles en Play (escena SampleScene)

| Tecla | Acción |
|---|---|
| `Space` | Inicia la jornada (arranca el reloj del backend) |
| `R` | Reset con la configuración por defecto |
| `1` / `2` / `3` | Reset con perfiles de densidad (editable en el `SimulationManager`) |

## Estructura

```
agentes.py        Modelo Mesa: ModeloCasilla + AgenteVotante/Funcionario/Presidente
estadistica.py    Modelos estadísticos (llegadas NHPP, voto, Dirichlet, métricas)
server.py         API Flask que expone el modelo (Unity consume esto)
replicas.py       Corredor de réplicas Monte Carlo (offline, no lo usa el server)
Assets/           Proyecto Unity: escena, scripts, prefabs de personajes y mobiliario
  Scripts/SimulationManager.cs   Cliente HTTP: spawnea/mueve agentes, perfiles, marcadores de prioridad
  Scripts/EscenarioManager.cs    Coloca el mobiliario desde /api/elementos, con ajuste fino en vivo
```

## Notas

- `git` no versiona `Library/`, `Temp/`, `Logs/`, los `.csproj/.sln` ni
  `UserSettings/` (ver `.gitignore`): se regeneran al abrir el proyecto.
- Los `.meta` **sí** van al repo; son los que mantienen las referencias de
  prefabs y escena entre computadoras. No los borres.
- Hay un `Assets/Scripts/server.py` (copia vieja) colado en el proyecto Unity;
  Unity lo ignora, se puede borrar en una limpieza aparte.
