using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

[Serializable]
public class AgentData
{
    public int id;
    public string tipo;
    public string status;
    public float x;
    public float y;
    public int edad;         // solo votantes
    public bool prioridad;   // adulto mayor (>=60) o con discapacidad
}

[Serializable]
public class SimulationResponse
{
    public int time;
    public bool simulacion_activa;
    public List<AgentData> agentes;
}

/// <summary>
/// Un preset de configuración que se manda al backend en /api/simulacion/reset
/// al pulsar su tecla. Editable desde el Inspector, sin tocar código.
/// </summary>
[Serializable]
public class PerfilSimulacion
{
    public string nombre = "Perfil";
    public KeyCode tecla = KeyCode.Alpha1;
    [Min(1)] public int n = 10;
    [Min(1)] public int horaCierre = 300;
    [Min(1)] public int capacidadMamparas = 2;

    [Tooltip("A/B/C/D: el escenario politico del que parte el modelo.")]
    public string escenario = "A";
    [Tooltip("Componente individual del logit jerarquico (beta^T z del votante).")]
    public bool usarAtributos = true;
    [Tooltip("Componente agregado: sortear p de la Dirichlet en vez de usar la media.")]
    public bool sortearP = true;

    public string ToJsonBody()
    {
        var ci = CultureInfo.InvariantCulture;
        return "{"
            + "\"n\": " + n.ToString(ci) + ", "
            + "\"hora_cierre\": " + horaCierre.ToString(ci) + ", "
            + "\"voting_booth_capacity\": " + capacidadMamparas.ToString(ci) + ", "
            + "\"modo_voto\": \"logit_jerarquico\", "
            + "\"escenario\": \"" + escenario + "\", "
            + "\"usar_atributos\": " + (usarAtributos ? "true" : "false") + ", "
            + "\"sortear_p\": " + (sortearP ? "true" : "false")
            + "}";
    }
}

public class SimulationManager : MonoBehaviour
{
    [Header("Configuración de Servidor")]
    public string apiUrl = "http://localhost:5000/api/tablero";
    public string apiBase = "http://localhost:5000/api";
    public float updateInterval = 0.5f;

    [Header("Escala del Espacio")]
    public float gridScale = 4f;

    [Header("Prefabs de Agentes")]
    public GameObject voterPrefab;
    public GameObject presidentePrefab;
    public GameObject funcionarioPrefab;

    [Header("Escenario (opcional)")]
    [Tooltip("Si se asigna, se reconstruye el layout tras cada reset (por si cambian las mamparas).")]
    public EscenarioManager escenarioManager;

    [Header("Votantes con prioridad (adultos mayores / discapacidad)")]
    [Tooltip("Pinta el material del votante prioritario con 'Color Prioritario'. " +
             "Se aplica al aparecer el agente; si cambias esto en Play, aplica a los nuevos.")]
    public bool tintarPrioritarios = true;
    public Color colorPrioritario = new Color(1f, 0.82f, 0.15f);   // dorado
    [Tooltip("Añade una esfera flotante sobre la cabeza de los votantes prioritarios. " +
             "Este sí se puede prender/apagar en vivo.")]
    public bool marcadorFlotante = true;
    public Color colorMarcador = new Color(1f, 0.82f, 0.15f);
    public float alturaMarcador = 2.2f;
    public float tamanoMarcador = 0.35f;

    [Header("Perfiles de simulación (tecla -> reset con esa densidad)")]
    public PerfilSimulacion[] perfiles = new PerfilSimulacion[]
    {
        new PerfilSimulacion { nombre = "Rápido",  tecla = KeyCode.Alpha1, n = 30, horaCierre = 60,  capacidadMamparas = 2 },
        new PerfilSimulacion { nombre = "Medio",   tecla = KeyCode.Alpha2, n = 20, horaCierre = 150, capacidadMamparas = 2 },
        new PerfilSimulacion { nombre = "Jornada", tecla = KeyCode.Alpha3, n = 10, horaCierre = 300, capacidadMamparas = 2 },
    };

    private float timer = 0f;
    private bool peticionEnVuelo = false;      // impide que los sondeos se encimen
    private float segundosPorTick = 1f;        // cuánto dura un tick del backend
    private Dictionary<int, VotanteAgent> activeAgents = new Dictionary<int, VotanteAgent>();
    private HashSet<int> tintados = new HashSet<int>();               // ya se les pintó el material
    private Dictionary<int, GameObject> marcadores = new Dictionary<int, GameObject>();

    void Awake()
    {
        // "localhost" resuelve primero a ::1 y el backend solo escucha en IPv4,
        // así que cada conexión desperdiciaba ~2 s esperando el fallback a IPv4
        // (medido en esta máquina: 2051 ms contra 0.2 ms). Con el sondeo
        // acelerado eso encolaba decenas de peticiones y el server dev las
        // cortaba: "Curl error 56: Connection was reset".
        apiUrl = apiUrl.Replace("localhost", "127.0.0.1");
        apiBase = apiBase.Replace("localhost", "127.0.0.1");
    }

    void Update()
    {
        timer += Time.deltaTime;
        if (timer >= updateInterval)
        {
            // Si la anterior sigue en vuelo se salta este turno. Sin esta guarda,
            // a x10 se lanzaban 20 peticiones por segundo sin esperar respuesta.
            if (!peticionEnVuelo) StartCoroutine(GetSimulationState());
            timer = 0f;
        }

        if (Input.GetKeyDown(KeyCode.Space))
        {
            StartCoroutine(IniciarSimulacion());
        }

        if (Input.GetKeyDown(KeyCode.R))
        {
            // R = reset con la config default del server (sin body).
            StartCoroutine(ResetSimulacion(null));
        }

        // Cada perfil dispara un reset con su propia densidad.
        foreach (var perfil in perfiles)
        {
            if (perfil != null && Input.GetKeyDown(perfil.tecla))
            {
                StartCoroutine(ResetSimulacion(perfil));
                break;
            }
        }
    }

    private IEnumerator GetSimulationState()
    {
        peticionEnVuelo = true;
        using (UnityWebRequest request = UnityWebRequest.Get(apiUrl))
        {
            request.timeout = 5;
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                ProcessStepData(request.downloadHandler.text);
            }
        }
        peticionEnVuelo = false;
    }

   private void ProcessStepData(string json)
    {
        SimulationResponse data = JsonUtility.FromJson<SimulationResponse>(json);
        if (data == null || data.agentes == null) return;

        HashSet<int> currentStepIds = new HashSet<int>();

        foreach (var agent in data.agentes)
        {
            // Un agente sin tablero (INACTIVE / NO_VOTO / DONE) no debe existir en la
            // escena. El backend ya los filtra, pero lo repetimos aquí porque esos
            // estados llegan con x/y nulos y JsonUtility los aplana a (0,0).
            if (agent.status == "INACTIVE" || agent.status == "NO_VOTO" || agent.status == "DONE")
                continue;

            currentStepIds.Add(agent.id);

            Vector3 worldPos = new Vector3(agent.x * gridScale, 0, agent.y * gridScale);

            if (!activeAgents.ContainsKey(agent.id))
            {
                GameObject prefabElegido = voterPrefab;

                if (agent.tipo == "presidente")
                    prefabElegido = presidentePrefab;
                else if (agent.tipo == "funcionario")
                    prefabElegido = funcionarioPrefab;

                GameObject newAgent = Instantiate(prefabElegido, worldPos, Quaternion.identity);
                VotanteAgent script = newAgent.GetComponent<VotanteAgent>();

                // El presidente NO es fijo: durante un sismo camina a la zona segura
                // liderando la evacuación, y con esFijo=true se quedaría petrificado.
                if (agent.tipo == "funcionario")
                {
                    script.esFijo = true;
                }

                // Nace ya con el ritmo de la velocidad actual, si no, los agentes
                // que aparecen después de acelerar caminarían en cámara lenta.
                script.AjustarRitmo(gridScale, segundosPorTick);

                activeAgents.Add(agent.id, script);
            }

            activeAgents[agent.id].UpdateAgentData(worldPos, agent.status);

            if (agent.tipo == "votante" && agent.prioridad)
                ActualizarVisualPrioridad(agent.id, activeAgents[agent.id].gameObject);
        }

        List<int> toRemove = new List<int>();
        foreach (var kvp in activeAgents)
        {
            if (!currentStepIds.Contains(kvp.Key))
            {
                Destroy(kvp.Value.gameObject);   // destruye también su marcador (es hijo)
                toRemove.Add(kvp.Key);
            }
        }
        foreach (int id in toRemove)
        {
            activeAgents.Remove(id);
            tintados.Remove(id);
            marcadores.Remove(id);
        }
    }

    /// <summary>
    /// Marca visualmente a un votante prioritario: tinte del material (una vez) y
    /// esfera flotante sobre la cabeza (se prende/apaga en vivo con 'marcadorFlotante').
    /// </summary>
    private void ActualizarVisualPrioridad(int id, GameObject agente)
    {
        if (tintarPrioritarios && !tintados.Contains(id))
        {
            foreach (var r in agente.GetComponentsInChildren<Renderer>())
                r.material.color = colorPrioritario;
            tintados.Add(id);
        }

        bool tiene = marcadores.TryGetValue(id, out GameObject marcador) && marcador != null;

        if (marcadorFlotante && !tiene)
        {
            marcador = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            marcador.name = "MarcadorPrioridad";
            var col = marcador.GetComponent<Collider>();
            if (col != null) Destroy(col);
            marcador.transform.SetParent(agente.transform, false);
            marcador.transform.localPosition = new Vector3(0f, alturaMarcador, 0f);
            marcador.transform.localScale = Vector3.one * tamanoMarcador;
            marcadores[id] = marcador;
            tiene = true;
        }
        else if (!marcadorFlotante && tiene)
        {
            Destroy(marcador);
            marcadores.Remove(id);
            tiene = false;
        }

        if (tiene)
        {
            marcador.transform.localPosition = new Vector3(0f, alturaMarcador, 0f);
            marcador.transform.localScale = Vector3.one * tamanoMarcador;
            var r = marcador.GetComponent<Renderer>();
            if (r != null) r.material.color = colorMarcador;
        }
    }

    private void LimpiarAgentes()
    {
        foreach (var kvp in activeAgents)
        {
            if (kvp.Value != null) Destroy(kvp.Value.gameObject);
        }
        activeAgents.Clear();
        tintados.Clear();
        marcadores.Clear();
    }

    private IEnumerator IniciarSimulacion()
    {
        using (UnityWebRequest request = UnityWebRequest.PostWwwForm(apiBase + "/simulacion/iniciar", ""))
        {
            yield return request.SendWebRequest();
            if (request.result == UnityWebRequest.Result.Success)
            {
                Debug.Log("✅ ¡Casilla abierta! El reloj corre. Asómate a VS Code para comprobarlo.");
            }
        }
    }

    /// <summary>
    /// Reinicia el backend. Si <paramref name="perfil"/> es null usa la config
    /// default del server; si no, manda n / hora_cierre / mamparas de ese perfil.
    /// </summary>
    private IEnumerator ResetSimulacion(PerfilSimulacion perfil)
    {
        string body = perfil != null ? perfil.ToJsonBody() : "{}";
        byte[] payload = Encoding.UTF8.GetBytes(body);

        using (UnityWebRequest request = new UnityWebRequest(apiBase + "/simulacion/reset", "POST"))
        {
            request.uploadHandler = new UploadHandlerRaw(payload);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");

            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                LimpiarAgentes();
                if (escenarioManager != null) escenarioManager.Reconstruir();

                if (perfil != null)
                    Debug.Log($"🔄 Reset '{perfil.nombre}': n={perfil.n}, hora_cierre={perfil.horaCierre}, mamparas={perfil.capacidadMamparas}. Pulsa SPACE para empezar.");
                else
                    Debug.Log("🔄 Backend limpio y reseteado (config default). Pulsa SPACE para empezar.");
            }
            else
            {
                Debug.LogError($"Reset falló: {request.error} — {request.downloadHandler.text}");
            }
        }
    }

    // --------------------------------------------------------- API pública ---
    // La usa ControlesUI para que los botones de la escena hagan exactamente lo
    // mismo que las teclas, sin duplicar ni la lógica de red ni la
    // reconstrucción del layout tras un reset.

    /// <summary>Reinicia el backend con una configuración arbitraria.</summary>
    /// <summary>Devuelve la corrutina para poder esperar a que el reset termine
    /// antes de abrir la casilla.</summary>
    public Coroutine ReiniciarCon(int n, int horaCierre, int capacidadMamparas,
                                  string escenario = "A",
                                  bool usarAtributos = true, bool sortearP = true)
    {
        return StartCoroutine(ResetSimulacion(new PerfilSimulacion
        {
            nombre = "Personalizado",
            n = n,
            horaCierre = horaCierre,
            capacidadMamparas = capacidadMamparas,
            escenario = escenario,
            usarAtributos = usarAtributos,
            sortearP = sortearP
        }));
    }

    /// <summary>Abre la casilla (equivale a SPACE).</summary>
    public void Iniciar()
    {
        StartCoroutine(IniciarSimulacion());
    }

    /// <summary>
    /// Ajusta toda la visualización a la velocidad del backend, como el x2 de un
    /// reproductor de video: no se saltan fotogramas, todo va más rápido.
    ///
    /// Tres cosas tienen que moverse juntas o la escena se ve errática:
    ///   1. Cada cuánto se pregunta el tablero (un sondeo por tick, con tope de
    ///      10 Hz para no ahogar al server dev de Flask).
    ///   2. La velocidad de traslado del agente: tiene que cruzar EXACTAMENTE una
    ///      celda por tick. Con el moveSpeed fijo de 3 u/s y celdas de 4 u, un
    ///      agente tardaba 1.33 s en cruzar una celda que el modelo cruza en 1 s;
    ///      ya iba atrasado en x1 y en x10 nunca alcanzaba su destino.
    ///   3. La velocidad del Animator, para que el ciclo de caminado acompañe.
    /// </summary>
    public void FijarVelocidad(float segundosPorPaso)
    {
        segundosPorTick = Mathf.Max(0.01f, segundosPorPaso);
        updateInterval = Mathf.Clamp(segundosPorTick, 0.1f, 0.5f);

        foreach (VotanteAgent agente in activeAgents.Values)
            if (agente != null) agente.AjustarRitmo(gridScale, segundosPorTick);
    }
}
