using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

/// <summary>
/// Panel de resultados de la elección dibujado encima de la escena.
///
/// Se construye solo al entrar en Play (ver <see cref="Arrancar"/>), así que no
/// hay nada que arrastrar en el Inspector ni ningún Canvas que agregar a mano.
///
/// Consume dos endpoints del backend:
///   /api/estadisticas -> estado en vivo, y al cerrar la media e IC 95 % de las
///                        esperas. Trae también los nombres de los candidatos.
///   /api/resultados   -> el conteo por partido. OJO: el backend lo oculta a
///                        propósito hasta que la jornada termina, igual que una
///                        casilla real, así que durante la simulación las
///                        barras se quedan vacías. No es un bug.
/// </summary>
public class ResultadosUI : MonoBehaviour
{
    [Header("Backend")]
    // 127.0.0.1 y no "localhost": ese nombre resuelve a ::1 primero y el backend
    // solo escucha en IPv4, lo que costaba ~2 s por conexión.
    public string apiBase = "http://127.0.0.1:5000/api";
    public float intervalo = 1f;

    [Header("Interacción")]
    public KeyCode teclaToggle = KeyCode.Tab;

    private const int AnchoPanel = 580;
    private const int Padding = 22;
    private const int AltoFila = 56;

    private RectTransform panel;
    private Text titulo;
    private Text estado;
    private Text pie1;
    private Text pie2;
    private Font fuente;

    private readonly List<Fila> filas = new List<Fila>();
    private string ultimaListaCandidatos = "";

    // Pantalla completa que aparece al cerrar la casilla.
    private RectTransform pantallaFinal;
    private RectTransform cuerpoFinal;
    private Text tituloFinal;
    private Text totalFinal;
    private Text detalleFinal;
    private readonly List<Fila> filasFinal = new List<Fila>();
    private bool finalMostrada;
    private bool panelVisible = true;   // lo alterna TAB; Refrescar lo respeta

    private class Fila
    {
        public Text etiqueta;
        public Text valor;
        public RectTransform relleno;
        public float objetivo;   // fracción 0..1 a la que debe llegar la barra
        public float actual;     // fracción dibujada ahora (se interpola)
    }

    /// <summary>
    /// Se instancia solo al entrar en Play. Evita tener que tocar la escena:
    /// SampleScene no tiene Canvas y no hace falta que lo tenga.
    /// </summary>
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Arrancar()
    {
        if (FindAnyObjectByType<ResultadosUI>() != null) return;
        new GameObject("ResultadosUI").AddComponent<ResultadosUI>();
    }

    private void Start()
    {
        fuente = FuenteBase();
        ConstruirPanel();
        StartCoroutine(Sondear());
    }

    private void Update()
    {
        if (Input.GetKeyDown(teclaToggle)) panelVisible = !panelVisible;

        // Las barras crecen en vez de aparecer de golpe al revelarse el conteo.
        Animar(filas);
        Animar(filasFinal);
    }

    private static void Animar(List<Fila> conjunto)
    {
        foreach (Fila fila in conjunto)
        {
            if (Mathf.Approximately(fila.actual, fila.objetivo)) continue;
            fila.actual = Mathf.MoveTowards(fila.actual, fila.objetivo, Time.deltaTime * 0.9f);
            fila.relleno.anchorMax = new Vector2(Mathf.Clamp01(fila.actual), 1f);
        }
    }

    // ----------------------------------------------------------------- red ---

    private IEnumerator Sondear()
    {
        while (true)
        {
            string estadisticas = null;
            string resultados = null;

            yield return Pedir(apiBase + "/estadisticas", r => estadisticas = r);
            yield return Pedir(apiBase + "/resultados", r => resultados = r);

            if (estadisticas == null)
            {
                estado.text = "Sin conexión con el backend (¿está corriendo server.py?)";
                estado.color = new Color(1f, 0.55f, 0.45f);
            }
            else
            {
                Refrescar(estadisticas, resultados);
            }

            yield return new WaitForSeconds(intervalo);
        }
    }

    private IEnumerator Pedir(string url, System.Action<string> alTerminar)
    {
        using (UnityWebRequest peticion = UnityWebRequest.Get(url))
        {
            peticion.timeout = 5;
            yield return peticion.SendWebRequest();
            alTerminar(peticion.result == UnityWebRequest.Result.Success
                ? peticion.downloadHandler.text
                : null);
        }
    }

    // ------------------------------------------------------------- pintado ---

    private void Refrescar(string estadisticas, string resultados)
    {
        string enVivo = Objeto(estadisticas, "en_vivo");
        string modelo = Objeto(estadisticas, "modelo");
        string final = Objeto(estadisticas, "final");
        bool finalizada = Booleano(estadisticas, "finalizada");

        SincronizarFilas(Cadenas(modelo, "candidatos"));

        int minuto = (int)Numero(enVivo, "minuto_jornada", 0);
        int duracion = (int)Numero(enVivo, "duracion_jornada", 0);
        int formados = (int)Numero(enVivo, "personas_formadas", 0);
        int colaMax = (int)Numero(enVivo, "longitud_max_fila", 0);
        int emitidos = (int)Numero(enVivo, "votantes_atendidos", 0);
        bool abierta = Booleano(enVivo, "casilla_abierta");

        if (finalizada)
        {
            estado.text = string.Format(CultureInfo.InvariantCulture,
                "JORNADA CERRADA  ·  {0} votos emitidos  ·  cola máxima {1}",
                emitidos, colaMax);
            estado.color = new Color(0.55f, 0.85f, 0.60f);
        }
        else
        {
            estado.text = string.Format(CultureInfo.InvariantCulture,
                "Minuto {0} / {1}  ·  {2}  ·  {3} en fila  ·  cola máxima {4}",
                minuto, duracion, abierta ? "casilla abierta" : "puerta cerrada",
                formados, colaMax);
            estado.color = new Color(0.78f, 0.80f, 0.86f);
        }

        // El conteo por partido solo existe una vez que la jornada terminó.
        bool disponible = resultados != null && Booleano(resultados, "disponible");
        Dictionary<string, int> conteo = disponible
            ? ParesEnteros(Objeto(resultados, "resultados"))
            : new Dictionary<string, int>();

        int total = 0;
        foreach (int v in conteo.Values) total += v;

        AplicarConteo(filas, conteo, total, disponible);
        AplicarConteo(filasFinal, conteo, total, disponible);

        // La pantalla completa se muestra sola al cerrar la casilla, una vez por
        // corrida: si el usuario la cierra, no vuelve a saltar hasta el próximo
        // reinicio. El panel lateral se oculta mientras tanto para no duplicar.
        if (finalizada && !finalMostrada)
        {
            finalMostrada = true;
            pantallaFinal.gameObject.SetActive(true);
            totalFinal.text = string.Format(CultureInfo.InvariantCulture,
                "{0} votos emitidos   ·   jornada de {1} minutos", total, duracion);
        }
        else if (!finalizada && finalMostrada)
        {
            finalMostrada = false;
            pantallaFinal.gameObject.SetActive(false);
        }
        panel.gameObject.SetActive(panelVisible && !pantallaFinal.gameObject.activeSelf);

        if (finalizada && final != null)
        {
            string espera = Objeto(final, "tiempo_espera");
            float media = (float)Numero(espera, "media", 0);
            float bajo = (float)Numero(espera, "ic95_inferior", 0);
            float alto = (float)Numero(espera, "ic95_superior", 0);
            float participacion = (float)Numero(final, "participacion_observada", 0);

            pie1.text = string.Format(CultureInfo.InvariantCulture,
                "Participación {0:F1} %   ·   espera media {1:F1} min  (IC 95 % {2:F1}–{3:F1})",
                participacion * 100f, media, bajo, alto);

            detalleFinal.text = string.Format(CultureInfo.InvariantCulture,
                "Participación observada {0:F1} %   ·   cola máxima {1} personas\n"
                + "Espera media en fila {2:F1} min   (IC 95 % {3:F1} – {4:F1})\n"
                + "Una sola corrida: el intervalo describe la dispersión entre votantes, no entre réplicas.",
                participacion * 100f, colaMax, media, bajo, alto);
        }
        else
        {
            pie1.text = "El conteo se revela al cerrar la casilla, como en una casilla real.";
        }

        // El escenario A/B/C/D solo alimenta la Dirichlet del modo
        // "categorico_dirichlet". En modo "utilidad" cada votante deriva su
        // propio p de sus atributos y el escenario NO se lee: anunciarlo aquí
        // haría creer que la corrida depende de algo que no la toca.
        string modoVoto = Cadena(modelo, "modo_voto");
        string origenDelVoto = modoVoto == "categorico_dirichlet"
            ? "escenario " + Cadena(modelo, "escenario") + " (Dirichlet)"
            : "utilidad por atributos (el escenario no aplica)";

        pie2.text = string.Format(CultureInfo.InvariantCulture,
            "{0}  ·  llegadas {1}   —   1 corrida, no es promedio de réplicas",
            origenDelVoto, Cadena(modelo, "perfil_llegadas"));
    }

    /// <summary>Vuelca el conteo sobre un juego de barras (el panel lateral y el
    /// de pantalla completa comparten datos, solo cambian de tamaño).</summary>
    private static void AplicarConteo(List<Fila> destino, Dictionary<string, int> conteo,
                                      int total, bool disponible)
    {
        foreach (Fila fila in destino)
        {
            int votos;
            if (disponible && conteo.TryGetValue(fila.etiqueta.text, out votos))
            {
                float p = total > 0 ? (float)votos / total : 0f;
                fila.objetivo = p;
                fila.valor.text = string.Format(CultureInfo.InvariantCulture,
                    "{0}   ({1:F1} %)", votos, p * 100f);
            }
            else
            {
                fila.objetivo = 0f;
                fila.valor.text = "—";
            }
        }
    }

    /// <summary>Reconstruye las barras si cambió la lista de candidatos (pasa al
    /// alternar entre el modelo de utilidad y el categórico de 6 categorías).</summary>
    private void SincronizarFilas(List<string> candidatos)
    {
        if (candidatos.Count == 0) return;
        string clave = string.Join("|", candidatos.ToArray());
        if (clave == ultimaListaCandidatos) return;
        ultimaListaCandidatos = clave;

        foreach (Fila fila in filas) Destroy(fila.etiqueta.transform.parent.gameObject);
        filas.Clear();
        foreach (Fila fila in filasFinal) Destroy(fila.etiqueta.transform.parent.gameObject);
        filasFinal.Clear();

        for (int i = 0; i < candidatos.Count; i++)
        {
            Color color = ColorPartido(candidatos[i], i);
            filas.Add(CrearFila(panel, candidatos[i], color, 18, 16f));
            filasFinal.Add(CrearFila(cuerpoFinal, candidatos[i], color, 34, 34f));
        }

        Reacomodar();
        ReacomodarFinal();
    }

    // -------------------------------------------------------- construcción ---

    private void ConstruirPanel()
    {
        GameObject lienzoGO = new GameObject("CanvasResultados",
            typeof(Canvas), typeof(CanvasScaler));
        lienzoGO.transform.SetParent(transform, false);

        Canvas lienzo = lienzoGO.GetComponent<Canvas>();
        lienzo.renderMode = RenderMode.ScreenSpaceOverlay;
        lienzo.sortingOrder = 100;

        CanvasScaler escalador = lienzoGO.GetComponent<CanvasScaler>();
        escalador.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        escalador.referenceResolution = new Vector2(1920, 1080);
        escalador.matchWidthOrHeight = 0.5f;

        panel = NuevoRect("Panel", lienzoGO.transform);
        panel.anchorMin = new Vector2(1f, 1f);
        panel.anchorMax = new Vector2(1f, 1f);
        panel.pivot = new Vector2(1f, 1f);
        panel.anchoredPosition = new Vector2(-24f, -24f);
        Fondo(panel, new Color(0.06f, 0.07f, 0.10f, 0.92f));

        titulo = CrearTexto(panel, "RESULTADOS DE LA CASILLA", 26, FontStyle.Bold,
            TextAnchor.MiddleLeft, new Color(0.96f, 0.96f, 0.98f));
        estado = CrearTexto(panel, "Conectando con el backend...", 17, FontStyle.Normal,
            TextAnchor.MiddleLeft, new Color(0.78f, 0.80f, 0.86f));
        pie1 = CrearTexto(panel, "", 16, FontStyle.Normal,
            TextAnchor.MiddleLeft, new Color(0.72f, 0.75f, 0.82f));
        pie2 = CrearTexto(panel, "", 14, FontStyle.Italic,
            TextAnchor.MiddleLeft, new Color(0.50f, 0.53f, 0.60f));

        Reacomodar();
        ConstruirPantallaCompleta();
    }

    /// <summary>La resolución de la casilla, a pantalla completa. Se arma al
    /// inicio y se deja apagada; aparece sola cuando el backend reporta
    /// finalizada. Vive en su propio Canvas por encima de todo lo demás.</summary>
    private void ConstruirPantallaCompleta()
    {
        GameObject lienzoGO = new GameObject("CanvasResultadoFinal",
            typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
        lienzoGO.transform.SetParent(transform, false);

        Canvas lienzo = lienzoGO.GetComponent<Canvas>();
        lienzo.renderMode = RenderMode.ScreenSpaceOverlay;
        lienzo.sortingOrder = 200;

        CanvasScaler escalador = lienzoGO.GetComponent<CanvasScaler>();
        escalador.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        escalador.referenceResolution = new Vector2(1920, 1080);
        escalador.matchWidthOrHeight = 0.5f;

        pantallaFinal = NuevoRect("PantallaFinal", lienzoGO.transform);
        pantallaFinal.anchorMin = Vector2.zero;
        pantallaFinal.anchorMax = Vector2.one;
        pantallaFinal.offsetMin = Vector2.zero;
        pantallaFinal.offsetMax = Vector2.zero;
        Fondo(pantallaFinal, new Color(0.03f, 0.04f, 0.07f, 0.97f));

        tituloFinal = CrearTexto(pantallaFinal, "RESULTADOS DE LA CASILLA", 62,
            FontStyle.Bold, TextAnchor.MiddleCenter, new Color(0.97f, 0.97f, 0.99f));
        Franja(tituloFinal.rectTransform, -70f, 76f);

        totalFinal = CrearTexto(pantallaFinal, "", 30, FontStyle.Normal,
            TextAnchor.MiddleCenter, new Color(0.60f, 0.86f, 0.66f));
        Franja(totalFinal.rectTransform, -150f, 40f);

        cuerpoFinal = NuevoRect("Cuerpo", pantallaFinal);
        cuerpoFinal.anchorMin = new Vector2(0.5f, 1f);
        cuerpoFinal.anchorMax = new Vector2(0.5f, 1f);
        cuerpoFinal.pivot = new Vector2(0.5f, 1f);
        cuerpoFinal.anchoredPosition = new Vector2(0f, -230f);
        cuerpoFinal.sizeDelta = new Vector2(1180f, 100f);

        detalleFinal = CrearTexto(pantallaFinal, "", 22, FontStyle.Normal,
            TextAnchor.MiddleCenter, new Color(0.70f, 0.74f, 0.82f));
        detalleFinal.rectTransform.anchorMin = new Vector2(0f, 0f);
        detalleFinal.rectTransform.anchorMax = new Vector2(1f, 0f);
        detalleFinal.rectTransform.pivot = new Vector2(0.5f, 0f);
        detalleFinal.rectTransform.anchoredPosition = new Vector2(0f, 110f);
        detalleFinal.rectTransform.sizeDelta = new Vector2(-200f, 70f);

        BotonCerrar();
        pantallaFinal.gameObject.SetActive(false);
    }

    private void BotonCerrar()
    {
        RectTransform rt = NuevoRect("Cerrar", pantallaFinal);
        rt.anchorMin = new Vector2(0.5f, 0f);
        rt.anchorMax = new Vector2(0.5f, 0f);
        rt.pivot = new Vector2(0.5f, 0f);
        rt.anchoredPosition = new Vector2(0f, 44f);
        rt.sizeDelta = new Vector2(280f, 48f);

        Image imagen = rt.gameObject.AddComponent<Image>();
        imagen.color = new Color(0.22f, 0.26f, 0.34f);

        Button boton = rt.gameObject.AddComponent<Button>();
        boton.targetGraphic = imagen;
        boton.onClick.AddListener(delegate { pantallaFinal.gameObject.SetActive(false); });

        Text etiqueta = CrearTexto(rt, "VOLVER A LA ESCENA", 18, FontStyle.Bold,
            TextAnchor.MiddleCenter, new Color(0.95f, 0.96f, 0.98f));
        etiqueta.rectTransform.anchorMin = Vector2.zero;
        etiqueta.rectTransform.anchorMax = Vector2.one;
        etiqueta.rectTransform.offsetMin = Vector2.zero;
        etiqueta.rectTransform.offsetMax = Vector2.zero;
    }

    private static void Franja(RectTransform rt, float y, float alto)
    {
        rt.anchorMin = new Vector2(0f, 1f);
        rt.anchorMax = new Vector2(1f, 1f);
        rt.pivot = new Vector2(0.5f, 1f);
        rt.anchoredPosition = new Vector2(0f, y);
        rt.sizeDelta = new Vector2(-200f, alto);
    }

    /// <summary>Apila las barras grandes dentro de la columna central.</summary>
    private void ReacomodarFinal()
    {
        float y = 0f;
        foreach (Fila fila in filasFinal)
        {
            RectTransform contenedor = (RectTransform)fila.etiqueta.transform.parent;
            contenedor.anchorMin = new Vector2(0f, 1f);
            contenedor.anchorMax = new Vector2(1f, 1f);
            contenedor.pivot = new Vector2(0.5f, 1f);
            contenedor.anchoredPosition = new Vector2(0f, y);
            contenedor.sizeDelta = new Vector2(0f, 86f);
            y -= 86f + 22f;
        }
        cuerpoFinal.sizeDelta = new Vector2(1180f, -y);
    }

    private Fila CrearFila(Transform padre, string nombre, Color color,
                           int tamanoTexto, float altoBarra)
    {
        RectTransform contenedor = NuevoRect("Fila_" + nombre, padre);

        Fila fila = new Fila();
        fila.etiqueta = CrearTexto(contenedor, nombre, tamanoTexto, FontStyle.Bold,
            TextAnchor.UpperLeft, new Color(0.93f, 0.94f, 0.97f));
        fila.valor = CrearTexto(contenedor, "—", tamanoTexto, FontStyle.Bold,
            TextAnchor.UpperRight, color);

        RectTransform canal = NuevoRect("Barra", contenedor);
        Fondo(canal, new Color(1f, 1f, 1f, 0.09f));
        canal.anchorMin = new Vector2(0f, 0f);
        canal.anchorMax = new Vector2(1f, 0f);
        canal.pivot = new Vector2(0.5f, 0f);
        canal.offsetMin = Vector2.zero;
        canal.offsetMax = new Vector2(0f, altoBarra);

        fila.relleno = NuevoRect("Relleno", canal);
        Fondo(fila.relleno, color);
        fila.relleno.anchorMin = Vector2.zero;
        fila.relleno.anchorMax = new Vector2(0f, 1f);
        fila.relleno.offsetMin = Vector2.zero;
        fila.relleno.offsetMax = Vector2.zero;

        Anclar(fila.etiqueta.rectTransform, 0f, 0.62f, tamanoTexto + 8f);
        Anclar(fila.valor.rectTransform, 0.55f, 1f, tamanoTexto + 8f);

        return fila;
    }

    /// <summary>Coloca título, estado, barras y pie uno debajo del otro y ajusta
    /// el alto del panel a lo que haya (3 partidos o 6 categorías).</summary>
    private void Reacomodar()
    {
        float y = -Padding;

        y = Apilar(titulo.rectTransform, y, 32f) - 6f;
        y = Apilar(estado.rectTransform, y, 24f) - 14f;

        foreach (Fila fila in filas)
        {
            RectTransform contenedor = (RectTransform)fila.etiqueta.transform.parent;
            y = Apilar(contenedor, y, AltoFila - 12f) - 12f;
        }

        y -= 6f;
        y = Apilar(pie1.rectTransform, y, 22f) - 2f;
        y = Apilar(pie2.rectTransform, y, 20f);

        panel.sizeDelta = new Vector2(AnchoPanel, -y + Padding);
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

    private static void Anclar(RectTransform rt, float min, float max, float alto)
    {
        rt.anchorMin = new Vector2(min, 1f);
        rt.anchorMax = new Vector2(max, 1f);
        rt.pivot = new Vector2(0.5f, 1f);
        rt.anchoredPosition = Vector2.zero;
        rt.sizeDelta = new Vector2(0f, alto);
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
        imagen.raycastTarget = false;
    }

    private Text CrearTexto(Transform padre, string contenido, int tamano,
                            FontStyle estilo, TextAnchor alineacion, Color color)
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

    /// <summary>TextMeshPro no está importado en el proyecto, así que se usa la
    /// fuente legacy que Unity trae compilada y no depende de ningún asset.</summary>
    private static Font FuenteBase()
    {
        Font f = null;
        try { f = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf"); } catch { }
        if (f == null) { try { f = Resources.GetBuiltinResource<Font>("Arial.ttf"); } catch { } }
        if (f == null) f = Font.CreateDynamicFontFromOSFont("Arial", 16);
        return f;
    }

    private static Color ColorPartido(string nombre, int indice)
    {
        string n = nombre.ToLowerInvariant();
        if (n.Contains("morena")) return new Color32(0x9E, 0x1B, 0x32, 0xFF);
        if (n.Contains("movimiento ciudadano")) return new Color32(0xF2, 0x7A, 0x1A, 0xFF);
        if (n.Contains("pan")) return new Color32(0x1E, 0x6F, 0xD9, 0xFF);
        if (n.Contains("nulo")) return new Color32(0x8A, 0x8F, 0x98, 0xFF);
        if (n.Contains("no registrada")) return new Color32(0x5F, 0x64, 0x6E, 0xFF);
        if (n.Contains("otros")) return new Color32(0x2E, 0xB8, 0x8A, 0xFF);
        return Color.HSVToRGB((indice * 0.618f) % 1f, 0.62f, 0.88f);
    }

    // -------------------------------------------------- lectura de JSON ---
    // JsonUtility no sabe leer diccionarios con claves arbitrarias ("MORENA",
    // "PAN-PRI"...), que es justo la forma de /api/resultados. Estas funciones
    // sacan a mano lo poco que se necesita.

    /// <summary>Posición del valor de una clave, o -1. Se salta los espacios tras
    /// los dos puntos SIN aceptar cualquier cosa: si la clave vale null (el caso
    /// de "final" mientras la jornada no termina) hay que devolver -1, no el
    /// siguiente objeto del JSON. Flask ordena las claves alfabéticamente, así
    /// que ese siguiente objeto sería "modelo" y los datos saldrían cruzados.</summary>
    private static int InicioValor(string json, string clave)
    {
        int i = json.IndexOf("\"" + clave + "\"");
        if (i < 0) return -1;
        int dosPuntos = json.IndexOf(':', i + clave.Length + 2);
        if (dosPuntos < 0) return -1;

        int j = dosPuntos + 1;
        while (j < json.Length && char.IsWhiteSpace(json[j])) j++;
        return j < json.Length ? j : -1;
    }

    /// <summary>Devuelve el sub-objeto de una clave, respetando llaves anidadas.</summary>
    private static string Objeto(string json, string clave)
    {
        if (string.IsNullOrEmpty(json)) return null;
        int abre = InicioValor(json, clave);
        if (abre < 0 || json[abre] != '{') return null;

        int profundidad = 0;
        for (int j = abre; j < json.Length; j++)
        {
            if (json[j] == '{') profundidad++;
            else if (json[j] == '}')
            {
                profundidad--;
                if (profundidad == 0) return json.Substring(abre, j - abre + 1);
            }
        }
        return null;
    }

    private static double Numero(string json, string clave, double porDefecto)
    {
        if (string.IsNullOrEmpty(json)) return porDefecto;
        Match m = Regex.Match(json, "\"" + Regex.Escape(clave)
            + "\"\\s*:\\s*(-?[0-9]+(?:\\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)");
        if (!m.Success) return porDefecto;
        double v;
        return double.TryParse(m.Groups[1].Value, NumberStyles.Float,
            CultureInfo.InvariantCulture, out v) ? v : porDefecto;
    }

    private static bool Booleano(string json, string clave)
    {
        if (string.IsNullOrEmpty(json)) return false;
        Match m = Regex.Match(json, "\"" + Regex.Escape(clave) + "\"\\s*:\\s*(true|false)");
        return m.Success && m.Groups[1].Value == "true";
    }

    private static string Cadena(string json, string clave)
    {
        if (string.IsNullOrEmpty(json)) return "";
        Match m = Regex.Match(json, "\"" + Regex.Escape(clave) + "\"\\s*:\\s*\"([^\"]*)\"");
        return m.Success ? m.Groups[1].Value : "";
    }

    private static List<string> Cadenas(string json, string clave)
    {
        List<string> salida = new List<string>();
        if (string.IsNullOrEmpty(json)) return salida;
        int abre = InicioValor(json, clave);
        if (abre < 0 || json[abre] != '[') return salida;
        int cierra = json.IndexOf(']', abre + 1);
        if (cierra < 0) return salida;

        foreach (Match m in Regex.Matches(json.Substring(abre, cierra - abre), "\"([^\"]*)\""))
            salida.Add(m.Groups[1].Value);
        return salida;
    }

    private static Dictionary<string, int> ParesEnteros(string objetoJson)
    {
        Dictionary<string, int> salida = new Dictionary<string, int>();
        if (string.IsNullOrEmpty(objetoJson)) return salida;
        foreach (Match m in Regex.Matches(objetoJson, "\"([^\"]+)\"\\s*:\\s*(-?[0-9]+)"))
            salida[m.Groups[1].Value] = int.Parse(m.Groups[2].Value, CultureInfo.InvariantCulture);
        return salida;
    }
}
