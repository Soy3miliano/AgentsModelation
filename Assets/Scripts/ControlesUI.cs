using System.Collections;
using System.Globalization;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.Networking;
using UnityEngine.UI;

/// <summary>
/// Panel de control de la simulación, dibujado dentro de la escena.
///
/// Sustituye a las teclas 1/2/3 + SPACE por controles de verdad: dos sliders
/// para el tamaño de la lista nominal y la duración de la jornada, botones para
/// abrir / pausar / reiniciar la casilla y una barra de velocidad x1..x10.
///
/// Se construye solo al entrar en Play, igual que <see cref="ResultadosUI"/>,
/// así que no hay nada que armar a mano en SampleScene.
///
/// Los límites no son arbitrarios:
///   - Votantes: hasta 625, que es la lista nominal por casilla que fija el
///     documento del equipo (estadistica.N_LISTA_NOMINAL, sección 5.3).
///   - Jornada: hasta 600 minutos, las 08:00-18:00 reales de la jornada
///     electoral mexicana (estadistica.DURACION_JORNADA, sección 3.3).
/// </summary>
public class ControlesUI : MonoBehaviour
{
    [Header("Backend")]
    // 127.0.0.1 y no "localhost": ese nombre resuelve a ::1 primero y el backend
    // solo escucha en IPv4, lo que costaba ~2 s por conexión.
    public string apiBase = "http://127.0.0.1:5000/api";

    [Header("Límites (ver documento de fundamentación)")]
    public int votantesMin = 10;
    public int votantesMax = 625;      // lista nominal por casilla
    public int jornadaMin = 60;
    public int jornadaMax = 600;       // 08:00-18:00

    /// <summary>Votantes por minuto que la casilla alcanza a atender con 1
    /// funcionario y 2 mamparas. Medido sobre corridas del propio modelo: con
    /// 600 minutos se atienden ~185 personas por más votantes que se metan.</summary>
    private const float RendimientoPorMinuto = 0.30f;

    private const int AnchoPanel = 520;
    private const int Padding = 20;

    private int votantes = 60;
    private int jornada = 300;
    private int multiplicador = 1;

    // UN modelo, no tres. El logit multinomial jerarquico contiene a los otros
    // dos como casos particulares (verificado: diferencia 0.0e+00), asi que en
    // vez de tres botones excluyentes se exponen sus dos ingredientes.
    private bool usarAtributos = true;   // componente individual: beta^T z_i
    private bool sortearP = true;        // componente agregado: p ~ Dirichlet
    private string escenario = "A";
    private Text equivalencia;
    private Button botonAtributos, botonDirichlet;
    private readonly Button[] botonesEscenario = new Button[4];
    private RectTransform filaEscenario;

    private RectTransform panel;
    private Text lecturaVotantes;
    private Text lecturaJornada;
    private Text aforo;
    private Text avisoVelocidad;
    private Text enUso;
    private Text avisoSismo;
    private Button botonSismo;
    private Text textoAbrir;
    private int nAplicado = -1;        // -1 = aun sin respuesta del backend
    private int jornadaAplicada = -1;
    private Font fuente;
    private SimulationManager simulacion;
    private readonly Button[] botonesVelocidad = new Button[4];
    private static readonly int[] Multiplicadores = { 1, 2, 5, 10 };

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Arrancar()
    {
        if (FindAnyObjectByType<ControlesUI>() != null) return;
        new GameObject("ControlesUI").AddComponent<ControlesUI>();
    }

    private void Start()
    {
        fuente = FuenteBase();
        simulacion = FindAnyObjectByType<SimulationManager>();
        GarantizarEventSystem();
        Construir();
        Refrescar();
        StartCoroutine(SondearConfigAplicada());
    }

    /// <summary>Sin EventSystem los botones se dibujan pero no reciben clicks.
    /// SampleScene no tiene uno porque hasta ahora no había UI.</summary>
    private static void GarantizarEventSystem()
    {
        if (FindAnyObjectByType<EventSystem>() != null) return;

        // El proyecto tiene Active Input Handling en "Both", así que el módulo
        // legacy funciona igual que Input.GetKeyDown en SimulationManager.
        new GameObject("EventSystem", typeof(EventSystem), typeof(StandaloneInputModule));
    }

    // ------------------------------------------------------------ acciones ---

    private void AlCambiarVotantes(float v)
    {
        votantes = Mathf.RoundToInt(v);
        Refrescar();
    }

    private void AlCambiarJornada(float v)
    {
        // De 15 en 15 minutos: valores redondos y un slider que no se siente resbaloso.
        jornada = Mathf.RoundToInt(v / 15f) * 15;
        jornada = Mathf.Clamp(jornada, jornadaMin, jornadaMax);
        Refrescar();
    }

    private void Refrescar()
    {
        lecturaVotantes.text = votantes.ToString(CultureInfo.InvariantCulture) + " votantes";
        // La jornada siempre CIERRA a las 18:00, así que una jornada corta es
        // una que abre más tarde. 600 min = 08:00, el caso real completo.
        int minutoApertura = 18 * 60 - jornada;
        lecturaJornada.text = string.Format(CultureInfo.InvariantCulture,
            "{0} min   ({1:00}:{2:00} → 18:00)", jornada, minutoApertura / 60, minutoApertura % 60);

        // Cuántos alcanzan a votar de verdad antes de que cierre la casilla.
        // OJO: esto describe los valores de los SLIDERS, que no son los que
        // corren hasta pulsar aplicar. El texto lo dice explícitamente, porque
        // leer "acuden ~127" durante una corrida de 89 votantes es confuso.
        int capacidad = Mathf.RoundToInt(RendimientoPorMinuto * jornada);
        int acuden = Mathf.RoundToInt(votantes * 0.61f);   // PARTICIPACION_BASE
        bool pendiente = HayCambiosPendientes();

        string sujeto = pendiente
            ? string.Format(CultureInfo.InvariantCulture, "Si aplicas {0}:", votantes)
            : string.Format(CultureInfo.InvariantCulture, "De {0} en la lista", votantes);

        if (acuden > capacidad)
        {
            aforo.text = string.Format(CultureInfo.InvariantCulture,
                "{0} acuden ~{1} pero la casilla solo atiende ~{2} en {3} min: ~{4} sin votar.",
                sujeto, acuden, capacidad, jornada, acuden - capacidad);
            aforo.color = new Color(1f, 0.72f, 0.35f);
        }
        else
        {
            aforo.text = string.Format(CultureInfo.InvariantCulture,
                "{0} acuden ~{1} y la casilla atiende ~{2} en {3} min: alcanza.",
                sujeto, acuden, capacidad, jornada);
            aforo.color = new Color(0.62f, 0.66f, 0.74f);
        }

        if (textoAbrir != null)
            textoAbrir.text = pendiente ? "APLICAR Y ABRIR" : "ABRIR CASILLA";
    }

    /// <summary>Los sliders piden algo distinto de lo que el backend tiene cargado.</summary>
    private bool HayCambiosPendientes()
    {
        // Antes de la primera respuesta del backend no hay con qué comparar.
        if (nAplicado < 0) return false;
        return nAplicado != votantes || jornadaAplicada != jornada;
    }

    /// <summary>
    /// Refleja en pantalla que apagar un ingrediente no cambia de modelo: lo
    /// degrada a un caso particular conocido. Es la version visual del ablation
    /// study, y es lo que permite defender que aqui hay UN modelo y no tres.
    /// </summary>
    private void ActualizarModelo()
    {
        Color encendido = new Color(0.20f, 0.55f, 0.95f);
        Color apagado = new Color(1f, 1f, 1f, 0.10f);
        botonAtributos.GetComponent<Image>().color = usarAtributos ? encendido : apagado;
        botonDirichlet.GetComponent<Image>().color = sortearP ? encendido : apagado;

        if (usarAtributos && sortearP)
            equivalencia.text = "Modelo completo: U = log(p_escenario) + β·z del votante.";
        else if (!usarAtributos && sortearP)
            equivalencia.text = "Sin atributos ≡ categórico-Dirichlet puro: los agentes no influyen.";
        else if (usarAtributos && !sortearP)
            equivalencia.text = "Sin sorteo ≡ clima político fijo: toda la dispersión viene de quién vota.";
        else
            equivalencia.text = "Sin ninguno: todos votan el vector del escenario. Es el piso de comparación.";

        Refrescar();
    }

    private void FijarEscenario(string clave)
    {
        escenario = clave;
        string[] claves = { "A", "B", "C", "D" };
        for (int i = 0; i < botonesEscenario.Length; i++)
            botonesEscenario[i].GetComponent<Image>().color = claves[i] == clave
                ? new Color(0.55f, 0.35f, 0.85f)
                : new Color(1f, 1f, 1f, 0.10f);
        Refrescar();
    }

    private void Reiniciar()
    {
        if (simulacion != null)
            simulacion.ReiniciarCon(votantes, jornada, 2, escenario, usarAtributos, sortearP);
    }

    /// <summary>
    /// Abre la casilla. Si los sliders piden algo distinto de lo cargado en el
    /// backend, primero lo aplica: pulsar "abrir" con 207 en pantalla y que la
    /// jornada corra con los 89 anteriores es justo la confusión que hay que
    /// evitar. El reinicio se espera antes de arrancar, o el iniciar le ganaría
    /// la carrera al reset y volvería a correr la config vieja.
    /// </summary>
    private void Abrir()
    {
        StartCoroutine(AplicarYAbrir());
    }

    private IEnumerator AplicarYAbrir()
    {
        if (simulacion == null) yield break;

        if (HayCambiosPendientes())
        {
            yield return simulacion.ReiniciarCon(votantes, jornada, 2, escenario,
                                                 usarAtributos, sortearP);
            nAplicado = votantes;
            jornadaAplicada = jornada;
            Refrescar();
        }

        simulacion.Iniciar();
    }

    /// <summary>
    /// Fuerza el evento extraordinario. El modelo lo sortea con prob_terremoto
    /// = 0.0005 por tick, que en una jornada completa sale ~14 % de las veces:
    /// sin este boton la evacuacion es practicamente imposible de ensenar en
    /// vivo. El sorteo aleatorio del modelo sigue intacto.
    /// </summary>
    private void ProvocarSismo()
    {
        StartCoroutine(Postear("/simulacion/sismo", "{}"));
    }

    private void Pausar()
    {
        StartCoroutine(Postear("/simulacion/pausar", "{}"));
    }

    private void FijarVelocidad(int mult)
    {
        multiplicador = mult;

        // El backend duerme `segundos_por_paso` entre ticks: x10 = 0.1 s.
        float segundosPorPaso = 1f / mult;
        StartCoroutine(Postear("/simulacion/velocidad", string.Format(
            CultureInfo.InvariantCulture, "{{\"segundos_por_paso\": {0}}}", segundosPorPaso)));

        // Y la visualización completa se ajusta al mismo ritmo: sondeo, traslado
        // de los agentes y velocidad del Animator. Es lo que hace que x10 se vea
        // como adelantar un video y no como agentes teletransportándose.
        if (simulacion != null) simulacion.FijarVelocidad(segundosPorPaso);

        for (int i = 0; i < botonesVelocidad.Length; i++)
        {
            bool activo = Multiplicadores[i] == mult;
            botonesVelocidad[i].GetComponent<Image>().color = activo
                ? new Color(0.20f, 0.55f, 0.95f)
                : new Color(1f, 1f, 1f, 0.10f);
        }

        avisoVelocidad.text = mult == 1
            ? ""
            : string.Format(CultureInfo.InvariantCulture,
                "Backend a {0} ticks/s y agentes caminando x{1}: van sincronizados.", mult, mult);
    }

    /// <summary>Pregunta cada segundo con qué parámetros corre REALMENTE la
    /// casilla. Los sliders son una intención; esto es el hecho.</summary>
    private IEnumerator SondearConfigAplicada()
    {
        while (true)
        {
            using (UnityWebRequest peticion = UnityWebRequest.Get(apiBase + "/estadisticas"))
            {
                peticion.timeout = 5;
                yield return peticion.SendWebRequest();

                if (peticion.result == UnityWebRequest.Result.Success)
                    MostrarConfigAplicada(peticion.downloadHandler.text);
                else
                    enUso.text = "SIN CONEXIÓN AL BACKEND\n¿Está corriendo server.py?";
            }
            yield return new WaitForSeconds(1f);
        }
    }

    private void MostrarConfigAplicada(string json)
    {
        int nReal = (int)Numero(json, "lista_nominal", 0);
        int jornadaReal = (int)Numero(json, "duracion_jornada", 0);
        int mamparasReal = (int)Numero(json, "mamparas", 0);
        float pasoReal = (float)Numero(json, "segundos_por_paso", 1);
        int minuto = (int)Numero(json, "minuto_jornada", 0);
        bool corriendo = Booleano(json, "simulacion_activa");

        // Sismo en curso: se anuncia arriba y el boton se apaga (ya no aplica).
        bool sismo = Booleano(json, "evento_extraordinario");
        RectTransform banda = (RectTransform)avisoSismo.transform.parent;
        banda.gameObject.SetActive(sismo);
        if (sismo)
        {
            int tickEvento = (int)Numero(json, "tick_evento", 0);
            avisoSismo.text = "SISMO EN EL MINUTO " + tickEvento + "  ·  EVACUANDO";
        }
        botonSismo.interactable = !sismo;
        botonSismo.GetComponent<Image>().color = sismo
            ? new Color(0.28f, 0.14f, 0.13f)
            : new Color(0.52f, 0.20f, 0.16f);

        int multReal = Mathf.RoundToInt(1f / Mathf.Max(0.01f, pasoReal));

        // Si el backend cambio de config (un reset, otra pestana, lo que sea),
        // hay que rehacer el aviso de aforo y la etiqueta del boton abrir.
        bool cambio = nAplicado != nReal || jornadaAplicada != jornadaReal;
        nAplicado = nReal;
        jornadaAplicada = jornadaReal;
        if (cambio) Refrescar();

        bool pendiente = HayCambiosPendientes();

        string linea = string.Format(CultureInfo.InvariantCulture,
            "EN USO: {0} votantes · {1} min · {2} mamparas · x{3}\nminuto {4} · {5}",
            nReal, jornadaReal, mamparasReal, multReal, minuto,
            corriendo ? "corriendo" : "detenida");

        if (pendiente)
        {
            enUso.text = linea + string.Format(CultureInfo.InvariantCulture,
                "   →  sin aplicar: {0} / {1}", votantes, jornada);
            enUso.color = new Color(1f, 0.78f, 0.35f);
        }
        else
        {
            enUso.text = linea;
            enUso.color = new Color(0.60f, 0.88f, 0.70f);
        }
    }

    /// <summary>Lee un booleano sin depender del formateo del servidor: un
    /// Contains sobre el literal se rompe si Flask cambia a JSON compacto.</summary>
    private static bool Booleano(string json, string clave)
    {
        if (string.IsNullOrEmpty(json)) return false;
        Match m = Regex.Match(json, "\"" + Regex.Escape(clave) + "\"\\s*:\\s*(true|false)");
        return m.Success && m.Groups[1].Value == "true";
    }

    private static double Numero(string json, string clave, double porDefecto)
    {
        Match m = Regex.Match(json, "\"" + Regex.Escape(clave)
            + "\"\\s*:\\s*(-?[0-9]+(?:\\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)");
        double v;
        if (!m.Success) return porDefecto;
        return double.TryParse(m.Groups[1].Value, NumberStyles.Float,
            CultureInfo.InvariantCulture, out v) ? v : porDefecto;
    }

    private IEnumerator Postear(string ruta, string cuerpo)
    {
        byte[] carga = System.Text.Encoding.UTF8.GetBytes(cuerpo);
        using (UnityWebRequest peticion = new UnityWebRequest(apiBase + ruta, "POST"))
        {
            peticion.uploadHandler = new UploadHandlerRaw(carga);
            peticion.downloadHandler = new DownloadHandlerBuffer();
            peticion.SetRequestHeader("Content-Type", "application/json");
            peticion.timeout = 5;
            yield return peticion.SendWebRequest();

            if (peticion.result != UnityWebRequest.Result.Success)
                Debug.LogError("Falló " + ruta + ": " + peticion.error);
        }
    }

    // -------------------------------------------------------- construcción ---

    private void Construir()
    {
        GameObject lienzoGO = new GameObject("CanvasControles",
            typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
        lienzoGO.transform.SetParent(transform, false);

        Canvas lienzo = lienzoGO.GetComponent<Canvas>();
        lienzo.renderMode = RenderMode.ScreenSpaceOverlay;
        lienzo.sortingOrder = 90;

        CanvasScaler escalador = lienzoGO.GetComponent<CanvasScaler>();
        escalador.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        escalador.referenceResolution = new Vector2(1920, 1080);
        escalador.matchWidthOrHeight = 0.5f;

        panel = NuevoRect("Panel", lienzoGO.transform);
        panel.anchorMin = Vector2.zero;
        panel.anchorMax = Vector2.zero;
        panel.pivot = Vector2.zero;
        panel.anchoredPosition = new Vector2(24f, 24f);
        Fondo(panel, new Color(0.06f, 0.07f, 0.10f, 0.93f));

        // Aviso de sismo: va sobre el lienzo, no dentro del panel, para que se
        // vea aunque el panel de configuracion este tapado por otra cosa.
        RectTransform banda = NuevoRect("AvisoSismo", lienzoGO.transform);
        banda.anchorMin = new Vector2(0.5f, 1f);
        banda.anchorMax = new Vector2(0.5f, 1f);
        banda.pivot = new Vector2(0.5f, 1f);
        banda.anchoredPosition = new Vector2(0f, -20f);
        banda.sizeDelta = new Vector2(760f, 58f);
        Fondo(banda, new Color(0.62f, 0.16f, 0.13f, 0.95f));
        avisoSismo = Texto(banda, "", 26, FontStyle.Bold, TextAnchor.MiddleCenter,
            new Color(1f, 0.94f, 0.90f));
        avisoSismo.rectTransform.anchorMin = Vector2.zero;
        avisoSismo.rectTransform.anchorMax = Vector2.one;
        avisoSismo.rectTransform.offsetMin = Vector2.zero;
        avisoSismo.rectTransform.offsetMax = Vector2.zero;
        banda.gameObject.SetActive(false);

        float y = -Padding;

        Text titulo = Texto(panel, "CONFIGURACIÓN DE LA CASILLA", 22, FontStyle.Bold,
            TextAnchor.MiddleLeft, new Color(0.96f, 0.96f, 0.98f));
        y = Apilar(titulo.rectTransform, y, 28f) - 10f;

        // Tira de confirmación: qué está corriendo AHORA en el backend, que no
        // es lo mismo que lo que marcan los sliders hasta pulsar APLICAR.
        RectTransform tira = NuevoRect("EnUso", panel);
        Fondo(tira, new Color(0.09f, 0.15f, 0.13f, 1f));
        y = Apilar(tira, y, 52f) - 14f;
        enUso = Texto(tira, "Consultando al backend...", 15, FontStyle.Bold,
            TextAnchor.MiddleLeft, new Color(0.60f, 0.88f, 0.70f));
        enUso.rectTransform.anchorMin = Vector2.zero;
        enUso.rectTransform.anchorMax = Vector2.one;
        enUso.rectTransform.offsetMin = new Vector2(12f, 0f);
        enUso.rectTransform.offsetMax = new Vector2(-12f, 0f);

        Text etiquetaV = Texto(panel, "Lista nominal", 15, FontStyle.Normal,
            TextAnchor.MiddleLeft, new Color(0.62f, 0.66f, 0.74f));
        lecturaVotantes = Texto(panel, "", 17, FontStyle.Bold,
            TextAnchor.MiddleRight, new Color(0.93f, 0.94f, 0.97f));
        y = Apilar(etiquetaV.rectTransform, y, 22f);
        Apilar(lecturaVotantes.rectTransform, y + 22f, 22f);
        Slider sv = Deslizador(panel, votantesMin, votantesMax, votantes, AlCambiarVotantes);
        y = Apilar(sv.GetComponent<RectTransform>(), y - 4f, 20f) - 14f;

        Text etiquetaJ = Texto(panel, "Duración de la jornada (máx. 600 = 08:00-18:00)", 15,
            FontStyle.Normal, TextAnchor.MiddleLeft, new Color(0.62f, 0.66f, 0.74f));
        lecturaJornada = Texto(panel, "", 17, FontStyle.Bold,
            TextAnchor.MiddleRight, new Color(0.93f, 0.94f, 0.97f));
        y = Apilar(etiquetaJ.rectTransform, y, 22f);
        Apilar(lecturaJornada.rectTransform, y + 22f, 22f);
        Slider sj = Deslizador(panel, jornadaMin, jornadaMax, jornada, AlCambiarJornada);
        y = Apilar(sj.GetComponent<RectTransform>(), y - 4f, 20f) - 10f;

        aforo = Texto(panel, "", 14, FontStyle.Italic,
            TextAnchor.MiddleLeft, new Color(0.62f, 0.66f, 0.74f));
        y = Apilar(aforo.rectTransform, y, 20f) - 16f;

        // ---- el modelo, y sus dos ingredientes ----------------------------
        Text etiquetaModo = Texto(panel, "Logit multinomial jerárquico", 16, FontStyle.Bold,
            TextAnchor.MiddleLeft, new Color(0.93f, 0.94f, 0.97f));
        y = Apilar(etiquetaModo.rectTransform, y, 22f) - 2f;

        Text sub = Texto(panel, "un solo modelo · apaga un ingrediente para compararlo",
            13, FontStyle.Italic, TextAnchor.MiddleLeft, new Color(0.62f, 0.66f, 0.74f));
        y = Apilar(sub.rectTransform, y, 18f) - 6f;

        RectTransform filaModo = NuevoRect("Ingredientes", panel);
        y = Apilar(filaModo, y, 32f) - 6f;
        botonAtributos = Boton(filaModo, "Atributos del votante", 0f, 0.49f,
            new Color(1f, 1f, 1f, 0.10f),
            delegate { usarAtributos = !usarAtributos; ActualizarModelo(); });
        botonDirichlet = Boton(filaModo, "Incertidumbre Dirichlet", 0.51f, 1f,
            new Color(1f, 1f, 1f, 0.10f),
            delegate { sortearP = !sortearP; ActualizarModelo(); });

        equivalencia = Texto(panel, "", 13, FontStyle.Italic,
            TextAnchor.UpperLeft, new Color(0.62f, 0.66f, 0.74f));
        equivalencia.horizontalOverflow = HorizontalWrapMode.Wrap;
        y = Apilar(equivalencia.rectTransform, y, 34f) - 8f;

        // ---- escenario politico (solo si el modo lo usa) -------------------
        // El escenario siempre aplica: el modelo unico siempre parte de el.
        filaEscenario = NuevoRect("Escenarios", panel);
        y = Apilar(filaEscenario, y, 30f) - 14f;
        string[] claves = { "A", "B", "C", "D" };
        string[] nombres = { "A base", "B oficial.", "C naranja", "D altern." };
        for (int i = 0; i < claves.Length; i++)
        {
            string clave = claves[i];
            float ancho = 1f / claves.Length;
            botonesEscenario[i] = Boton(filaEscenario, nombres[i],
                i * ancho + 0.008f, (i + 1) * ancho - 0.008f,
                new Color(1f, 1f, 1f, 0.10f), delegate { FijarEscenario(clave); });
        }

        RectTransform fila = NuevoRect("Acciones", panel);
        y = Apilar(fila, y, 40f) - 16f;
        Boton(fila, "APLICAR Y REINICIAR", 0f, 0.52f, new Color(0.24f, 0.28f, 0.36f), Reiniciar);
        Button abrir = Boton(fila, "ABRIR CASILLA", 0.545f, 0.80f,
            new Color(0.14f, 0.50f, 0.30f), Abrir);
        textoAbrir = abrir.GetComponentInChildren<Text>();
        Boton(fila, "PAUSA", 0.825f, 1f, new Color(0.40f, 0.26f, 0.16f), Pausar);

        RectTransform filaSismo = NuevoRect("Sismo", panel);
        y = Apilar(filaSismo, y, 34f) - 14f;
        botonSismo = Boton(filaSismo, "PROVOCAR SISMO  ·  evacuación", 0f, 1f,
            new Color(0.52f, 0.20f, 0.16f), ProvocarSismo);

        Text etiquetaVel = Texto(panel, "Velocidad de la simulación", 15, FontStyle.Normal,
            TextAnchor.MiddleLeft, new Color(0.62f, 0.66f, 0.74f));
        y = Apilar(etiquetaVel.rectTransform, y, 20f) - 4f;

        RectTransform filaVel = NuevoRect("Velocidad", panel);
        y = Apilar(filaVel, y, 34f) - 8f;
        for (int i = 0; i < Multiplicadores.Length; i++)
        {
            int mult = Multiplicadores[i];
            float ancho = 1f / Multiplicadores.Length;
            botonesVelocidad[i] = Boton(filaVel, "x" + mult,
                i * ancho + 0.012f, (i + 1) * ancho - 0.012f,
                new Color(1f, 1f, 1f, 0.10f), delegate { FijarVelocidad(mult); });
        }

        avisoVelocidad = Texto(panel, "", 13, FontStyle.Italic,
            TextAnchor.MiddleLeft, new Color(0.80f, 0.62f, 0.35f));
        y = Apilar(avisoVelocidad.rectTransform, y, 18f);

        panel.sizeDelta = new Vector2(AnchoPanel, -y + Padding);
        FijarVelocidad(1);
        FijarEscenario("A");
        ActualizarModelo();
    }

    private Slider Deslizador(Transform padre, int min, int max, int valor,
                              UnityEngine.Events.UnityAction<float> alCambiar)
    {
        RectTransform rt = NuevoRect("Slider", padre);
        Slider sl = rt.gameObject.AddComponent<Slider>();

        RectTransform canal = NuevoRect("Canal", rt);
        Estirar(canal, 0f, 6f);
        Fondo(canal, new Color(1f, 1f, 1f, 0.12f));

        RectTransform areaRelleno = NuevoRect("AreaRelleno", rt);
        Estirar(areaRelleno, 0f, 6f);
        // Slider reescribe los anchors de fillRect y handleRect en cada
        // UpdateVisuals, pero NO los offsets: si se quedan en el sizeDelta por
        // defecto del RectTransform, el relleno se dibuja 100 px más grande que
        // su área. Hay que dejarlos en cero a mano.
        RectTransform relleno = NuevoRect("Relleno", areaRelleno);
        Fondo(relleno, new Color(0.20f, 0.55f, 0.95f));
        relleno.anchorMin = Vector2.zero;
        relleno.anchorMax = Vector2.one;
        relleno.offsetMin = Vector2.zero;
        relleno.offsetMax = Vector2.zero;

        RectTransform areaTirador = NuevoRect("AreaTirador", rt);
        Estirar(areaTirador, 9f, 0f);
        RectTransform tirador = NuevoRect("Tirador", areaTirador);
        Fondo(tirador, new Color(0.92f, 0.94f, 0.98f));
        tirador.anchorMin = Vector2.zero;
        tirador.anchorMax = new Vector2(0f, 1f);
        tirador.offsetMin = Vector2.zero;
        tirador.offsetMax = Vector2.zero;
        tirador.sizeDelta = new Vector2(18f, 0f);   // alto lo pone el anchor

        sl.fillRect = relleno;
        sl.handleRect = tirador;
        sl.targetGraphic = tirador.GetComponent<Image>();
        sl.direction = Slider.Direction.LeftToRight;
        sl.wholeNumbers = true;
        sl.minValue = min;
        sl.maxValue = max;
        sl.value = valor;
        sl.onValueChanged.AddListener(alCambiar);
        return sl;
    }

    private Button Boton(Transform padre, string texto, float min, float max,
                         Color color, UnityEngine.Events.UnityAction alPulsar)
    {
        RectTransform rt = NuevoRect("Boton_" + texto, padre);
        rt.anchorMin = new Vector2(min, 0f);
        rt.anchorMax = new Vector2(max, 1f);
        rt.offsetMin = Vector2.zero;
        rt.offsetMax = Vector2.zero;

        Image imagen = rt.gameObject.AddComponent<Image>();
        imagen.color = color;

        Button boton = rt.gameObject.AddComponent<Button>();
        boton.targetGraphic = imagen;
        boton.onClick.AddListener(alPulsar);

        Text etiqueta = Texto(rt, texto, 15, FontStyle.Bold,
            TextAnchor.MiddleCenter, new Color(0.97f, 0.97f, 0.99f));
        Estirar(etiqueta.rectTransform, 0f, 0f);
        return boton;
    }

    // ------------------------------------------------------------ utilería ---

    private static void Estirar(RectTransform rt, float margenX, float alto)
    {
        rt.anchorMin = new Vector2(0f, alto > 0f ? 0.5f : 0f);
        rt.anchorMax = new Vector2(1f, alto > 0f ? 0.5f : 1f);
        rt.pivot = new Vector2(0.5f, 0.5f);
        rt.anchoredPosition = Vector2.zero;
        rt.sizeDelta = new Vector2(-margenX * 2f, alto);
    }

    private float Apilar(RectTransform rt, float y, float alto)
    {
        rt.anchorMin = new Vector2(0f, 1f);
        rt.anchorMax = new Vector2(1f, 1f);
        rt.pivot = new Vector2(0.5f, 1f);
        rt.anchoredPosition = new Vector2(0f, y);
        rt.sizeDelta = new Vector2(-Padding * 2f, alto);
        return y - alto;
    }

    private static RectTransform NuevoRect(string nombre, Transform padre)
    {
        GameObject go = new GameObject(nombre, typeof(RectTransform));
        go.transform.SetParent(padre, false);
        return (RectTransform)go.transform;
    }

    private static void Fondo(RectTransform rt, Color color)
    {
        Image imagen = rt.gameObject.AddComponent<Image>();
        imagen.color = color;
    }

    private Text Texto(Transform padre, string contenido, int tamano, FontStyle estilo,
                       TextAnchor alineacion, Color color)
    {
        RectTransform rt = NuevoRect("Texto", padre);
        Text texto = rt.gameObject.AddComponent<Text>();
        texto.font = fuente;
        texto.text = contenido;
        texto.fontSize = tamano;
        texto.fontStyle = estilo;
        texto.alignment = alineacion;
        texto.color = color;
        texto.horizontalOverflow = HorizontalWrapMode.Overflow;
        texto.verticalOverflow = VerticalWrapMode.Overflow;
        texto.raycastTarget = false;
        return texto;
    }

    private static Font FuenteBase()
    {
        Font f = null;
        try { f = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf"); } catch { }
        if (f == null) { try { f = Resources.GetBuiltinResource<Font>("Arial.ttf"); } catch { } }
        if (f == null) f = Font.CreateDynamicFontFromOSFont("Arial", 16);
        return f;
    }
}
