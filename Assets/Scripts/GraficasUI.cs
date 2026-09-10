using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEngine.Networking;
using UnityEngine.UI;

/// <summary>
/// Panel de gráficas de la simulación. Se abre y cierra con la tecla G.
///
/// Está organizado a propósito igual que CONCEPTOS_ESTADISTICOS_IMPLEMENTADOS.md:
/// cada gráfica defiende visualmente uno de los modelos del documento, así que
/// el panel sirve de apoyo directo en la sustentación.
///
///   MODELO C  Llegadas por tramo contra el perfil NHPP teórico (tabla 21).
///   MODELO D  Histograma de esperas con su media e IC 95 %.
///   §11       Pirámide de edad: quién está en la lista contra quién acude.
///   Operación Longitud de la fila a lo largo de la jornada.
///   Embudo    De la lista nominal a los votos efectivos (la saturación).
///
/// Todo sale de /api/series, que el backend calcula al vuelo del estado actual.
/// Las barras son Images de uGUI: no hace falta ninguna librería de gráficas.
/// </summary>
public class GraficasUI : MonoBehaviour
{
    [Header("Backend")]
    public string apiBase = "http://127.0.0.1:5000/api";
    public float intervalo = 2f;

    [Header("Interacción")]
    public KeyCode teclaToggle = KeyCode.G;

    private RectTransform pantalla;
    private Font fuente;
    private bool visible;

    // Cada tarjeta guarda su zona de dibujo y los textos que la acompañan.
    private RectTransform zonaLlegadas, zonaEspera, zonaEdad, zonaFila, zonaEmbudo;
    private Text pieLlegadas, pieEspera, pieEdad, pieFila, pieEmbudo;

    private static readonly Color Fondo = new Color(0.06f, 0.07f, 0.10f, 0.97f);
    private static readonly Color Tarjeta = new Color(1f, 1f, 1f, 0.04f);
    private static readonly Color Tinta = new Color(0.93f, 0.94f, 0.97f);
    private static readonly Color Apagado = new Color(0.62f, 0.66f, 0.74f);
    private static readonly Color Azul = new Color(0.20f, 0.55f, 0.95f);
    private static readonly Color Naranja = new Color(0.95f, 0.55f, 0.15f);
    private static readonly Color Verde = new Color(0.30f, 0.78f, 0.50f);
    private static readonly Color Morado = new Color(0.62f, 0.42f, 0.92f);
    private static readonly Color Gris = new Color(1f, 1f, 1f, 0.16f);

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    private static void Arrancar()
    {
        if (FindAnyObjectByType<GraficasUI>() != null) return;
        new GameObject("GraficasUI").AddComponent<GraficasUI>();
    }

    private void Start()
    {
        fuente = FuenteBase();
        Construir();
        pantalla.gameObject.SetActive(false);
        StartCoroutine(Sondear());
    }

    private void Update()
    {
        if (!Input.GetKeyDown(teclaToggle)) return;
        visible = !visible;
        pantalla.gameObject.SetActive(visible);
    }

    private IEnumerator Sondear()
    {
        while (true)
        {
            // Solo se pide mientras el panel está abierto: son cinco series y no
            // tiene sentido calcularlas cada dos segundos si nadie las mira.
            if (visible)
            {
                using (UnityWebRequest peticion = UnityWebRequest.Get(apiBase + "/series"))
                {
                    peticion.timeout = 5;
                    yield return peticion.SendWebRequest();
                    if (peticion.result == UnityWebRequest.Result.Success)
                        Dibujar(peticion.downloadHandler.text);
                }
            }
            yield return new WaitForSeconds(intervalo);
        }
    }

    // ------------------------------------------------------------- dibujo ---

    private void Dibujar(string json)
    {
        DibujarLlegadas(Objeto(json, "llegadas"));
        DibujarEspera(Objeto(json, "espera"));
        DibujarEdad(Objeto(json, "edad"));
        DibujarFila(Objeto(json, "fila"));
        DibujarEmbudo(Objeto(json, "embudo"));
    }

    /// <summary>MODELO C: barras pareadas observado / teórico por tramo horario.
    /// Que las dos series se peguen es la prueba visual de que el NHPP
    /// reproduce la tabla 21.</summary>
    private void DibujarLlegadas(string j)
    {
        Limpiar(zonaLlegadas);
        List<float> obs = Numeros(j, "observado");
        List<float> teo = Numeros(j, "teorico");
        if (obs.Count == 0) return;

        float maximo = Mathf.Max(0.01f, Mathf.Max(Maximo(obs), Maximo(teo)));
        float ancho = 1f / obs.Count;
        float mayorDesvio = 0f;

        for (int i = 0; i < obs.Count; i++)
        {
            float izq = i * ancho;
            Barra(zonaLlegadas, izq + ancho * 0.12f, izq + ancho * 0.46f, obs[i] / maximo, Azul);
            if (i < teo.Count)
            {
                Barra(zonaLlegadas, izq + ancho * 0.54f, izq + ancho * 0.88f, teo[i] / maximo, Gris);
                mayorDesvio = Mathf.Max(mayorDesvio, Mathf.Abs(obs[i] - teo[i]));
            }
            Etiqueta(zonaLlegadas, izq, izq + ancho, Reloj(i));
        }

        pieLlegadas.text = string.Format(CultureInfo.InvariantCulture,
            "azul = observado · gris = perfil teórico   ·   desvío máximo {0:F1} pp   ·   n={1}",
            mayorDesvio * 100f, (int)Numero(j, "total", 0));
    }

    /// <summary>MODELO D: histograma de esperas con la banda del IC 95 % pintada
    /// detrás y la media marcada.</summary>
    private void DibujarEspera(string j)
    {
        Limpiar(zonaEspera);
        List<float> conteo = Numeros(j, "conteo");
        if (conteo.Count == 0) return;

        float ancho_caja = (float)Numero(j, "ancho_caja", 1);
        float tope = ancho_caja * conteo.Count;
        float maximo = Mathf.Max(1f, Maximo(conteo));

        // Banda del intervalo, primero para que quede por detrás de las barras.
        float bajo = (float)Numero(j, "ic95_inferior", 0);
        float alto = (float)Numero(j, "ic95_superior", 0);
        if (tope > 0f && alto > bajo)
            Banda(zonaEspera, Mathf.Clamp01(bajo / tope), Mathf.Clamp01(alto / tope),
                  new Color(0.30f, 0.78f, 0.50f, 0.18f));

        float w = 1f / conteo.Count;
        for (int i = 0; i < conteo.Count; i++)
            Barra(zonaEspera, i * w + w * 0.1f, (i + 1) * w - w * 0.1f, conteo[i] / maximo, Verde);

        float media = (float)Numero(j, "media", 0);
        if (tope > 0f) Banda(zonaEspera, Mathf.Clamp01(media / tope - 0.004f),
                             Mathf.Clamp01(media / tope + 0.004f), Tinta);

        Etiqueta(zonaEspera, 0f, 0.2f, "0 min");
        Etiqueta(zonaEspera, 0.8f, 1f, ((int)tope) + " min");

        pieEspera.text = string.Format(CultureInfo.InvariantCulture,
            "media {0:F1} min · IC 95 % {1:F1}–{2:F1} (banda verde) · n={3} votantes",
            media, bajo, alto, (int)Numero(j, "n", 0));
    }

    /// <summary>Sección 11: por cada grupo de edad, cuántos hay en la lista y
    /// cuántos acuden. La diferencia de alturas ES la participación por edad.</summary>
    private void DibujarEdad(string j)
    {
        Limpiar(zonaEdad);
        List<float> lista = Numeros(j, "en_lista");
        List<float> acuden = Numeros(j, "acuden");
        if (lista.Count == 0) return;

        float maximo = Mathf.Max(1f, Maximo(lista));
        float ancho = 1f / lista.Count;
        float tasaJoven = lista[0] > 0 ? acuden[0] / lista[0] : 0f;
        int ult = lista.Count - 1;
        float tasaMayor = lista[ult] > 0 ? acuden[ult] / lista[ult] : 0f;

        for (int i = 0; i < lista.Count; i++)
        {
            float izq = i * ancho;
            Barra(zonaEdad, izq + ancho * 0.15f, izq + ancho * 0.85f, lista[i] / maximo, Gris);
            if (i < acuden.Count)
                Barra(zonaEdad, izq + ancho * 0.15f, izq + ancho * 0.85f, acuden[i] / maximo, Morado);
        }

        Etiqueta(zonaEdad, 0f, ancho * 2f, "18-29");
        Etiqueta(zonaEdad, 1f - ancho * 2f, 1f, "65+");

        pieEdad.text = string.Format(CultureInfo.InvariantCulture,
            "gris = en la lista · morado = acuden   ·   participación {0:F0} % en 18-24 contra {1:F0} % en 65+",
            tasaJoven * 100f, tasaMayor * 100f);
    }

    /// <summary>La cola a lo largo de la jornada. Es donde se ve el pico de
    /// media mañana que produce el NHPP.</summary>
    private void DibujarFila(string j)
    {
        Limpiar(zonaFila);
        List<float> serie = Numeros(j, "serie");
        if (serie.Count == 0) return;

        float maximo = Mathf.Max(1f, Maximo(serie));
        float w = 1f / serie.Count;
        for (int i = 0; i < serie.Count; i++)
            Barra(zonaFila, i * w, (i + 1) * w - w * 0.15f, serie[i] / maximo, Naranja);

        int duracion = (int)Numero(j, "duracion", 0);
        Etiqueta(zonaFila, 0f, 0.15f, "apertura");
        Etiqueta(zonaFila, 0.75f, 1f, duracion + " min");

        pieFila.text = string.Format(CultureInfo.InvariantCulture,
            "personas formadas a lo largo de la jornada   ·   máximo {0}",
            (int)Numero(j, "maximo", 0));
    }

    /// <summary>El embudo de saturación, en barras horizontales.</summary>
    private void DibujarEmbudo(string j)
    {
        Limpiar(zonaEmbudo);
        float lista = (float)Numero(j, "lista_nominal", 0);
        float acuden = (float)Numero(j, "acudieron", 0);
        float votan = (float)Numero(j, "votaron", 0);
        float fuera = (float)Numero(j, "sin_votar", 0);
        if (lista <= 0f) return;

        BarraHorizontal(zonaEmbudo, 0.68f, 1f, lista / lista, Gris,
                        "lista nominal   " + (int)lista);
        BarraHorizontal(zonaEmbudo, 0.36f, 0.66f, acuden / lista, Azul,
                        "acuden   " + (int)acuden);
        BarraHorizontal(zonaEmbudo, 0.04f, 0.34f, votan / lista, Verde,
                        "alcanzan a votar   " + (int)votan);

        pieEmbudo.text = fuera > 0
            ? string.Format(CultureInfo.InvariantCulture,
                "{0} personas acuden y se quedan sin votar: la casilla satura", (int)fuera)
            : "todos los que acudieron alcanzaron a votar";
    }

    // ------------------------------------------------------- construcción ---

    private void Construir()
    {
        GameObject lienzoGO = new GameObject("CanvasGraficas",
            typeof(Canvas), typeof(CanvasScaler));
        lienzoGO.transform.SetParent(transform, false);

        Canvas lienzo = lienzoGO.GetComponent<Canvas>();
        lienzo.renderMode = RenderMode.ScreenSpaceOverlay;
        lienzo.sortingOrder = 150;

        CanvasScaler escalador = lienzoGO.GetComponent<CanvasScaler>();
        escalador.uiScaleMode = CanvasScaler.ScaleMode.ScaleWithScreenSize;
        escalador.referenceResolution = new Vector2(1920, 1080);
        escalador.matchWidthOrHeight = 0.5f;

        pantalla = Rect("Pantalla", lienzoGO.transform);
        Estirar(pantalla);
        Pintar(pantalla, Fondo);

        Text titulo = Texto(pantalla, "LA CASILLA EN CIFRAS", 34, FontStyle.Bold,
            TextAnchor.MiddleLeft, Tinta);
        Colocar(titulo.rectTransform, 0.03f, 0.60f, 0.925f, 0.975f);

        Text ayuda = Texto(pantalla, "G para cerrar   ·   una gráfica por modelo del documento",
            16, FontStyle.Italic, TextAnchor.MiddleRight, Apagado);
        Colocar(ayuda.rectTransform, 0.55f, 0.97f, 0.93f, 0.965f);

        // Rejilla de 2 columnas x 3 filas. La última fila la ocupa el embudo a
        // lo ancho, porque son barras horizontales y necesita el espacio.
        zonaLlegadas = Tarjeta_("MODELO C · Llegadas contra el perfil NHPP teórico",
            0.03f, 0.485f, 0.615f, 0.905f, out pieLlegadas);
        zonaEspera = Tarjeta_("MODELO D · Tiempo de espera, media e IC 95 %",
            0.515f, 0.97f, 0.615f, 0.905f, out pieEspera);
        zonaEdad = Tarjeta_("SECCIÓN 11 · Quién está en la lista y quién acude",
            0.03f, 0.485f, 0.305f, 0.595f, out pieEdad);
        zonaFila = Tarjeta_("OPERACIÓN · Longitud de la fila durante la jornada",
            0.515f, 0.97f, 0.305f, 0.595f, out pieFila);
        zonaEmbudo = Tarjeta_("SATURACIÓN · De la lista nominal a los votos efectivos",
            0.03f, 0.97f, 0.04f, 0.285f, out pieEmbudo);
    }

    private RectTransform Tarjeta_(string titulo, float x0, float x1, float y0, float y1,
                                   out Text pie)
    {
        RectTransform tarjeta = Rect("Tarjeta", pantalla);
        Colocar(tarjeta, x0, x1, y0, y1);
        Pintar(tarjeta, Tarjeta);

        Text cabecera = Texto(tarjeta, titulo, 17, FontStyle.Bold, TextAnchor.MiddleLeft, Tinta);
        Colocar(cabecera.rectTransform, 0.02f, 0.98f, 0.87f, 0.99f);

        pie = Texto(tarjeta, "", 13, FontStyle.Normal, TextAnchor.MiddleLeft, Apagado);
        Colocar(pie.rectTransform, 0.02f, 0.98f, 0.01f, 0.11f);

        RectTransform zona = Rect("Zona", tarjeta);
        Colocar(zona, 0.03f, 0.97f, 0.17f, 0.84f);
        return zona;
    }

    // ---------------------------------------------------------- primitivas ---

    /// <summary>Una barra vertical: ocupa [x0, x1] del ancho y `altura` (0..1)
    /// del alto de su zona, anclada al piso.</summary>
    private void Barra(RectTransform zona, float x0, float x1, float altura, Color color)
    {
        RectTransform rt = Rect("Barra", zona);
        rt.anchorMin = new Vector2(x0, 0f);
        rt.anchorMax = new Vector2(x1, Mathf.Clamp(altura, 0.004f, 1f));
        rt.offsetMin = Vector2.zero;
        rt.offsetMax = Vector2.zero;
        Pintar(rt, color);
    }

    private void BarraHorizontal(RectTransform zona, float y0, float y1, float largo,
                                 Color color, string etiqueta)
    {
        RectTransform rt = Rect("BarraH", zona);
        rt.anchorMin = new Vector2(0f, y0);
        rt.anchorMax = new Vector2(Mathf.Clamp(largo, 0.004f, 1f), y1);
        rt.offsetMin = Vector2.zero;
        rt.offsetMax = Vector2.zero;
        Pintar(rt, color);

        Text t = Texto(zona, etiqueta, 15, FontStyle.Bold, TextAnchor.MiddleLeft, Tinta);
        Colocar(t.rectTransform, 0.01f, 0.6f, y0, y1);
    }

    /// <summary>Franja vertical translúcida, para marcar el IC y la media.</summary>
    private void Banda(RectTransform zona, float x0, float x1, Color color)
    {
        RectTransform rt = Rect("Banda", zona);
        rt.anchorMin = new Vector2(x0, 0f);
        rt.anchorMax = new Vector2(Mathf.Max(x1, x0 + 0.003f), 1f);
        rt.offsetMin = Vector2.zero;
        rt.offsetMax = Vector2.zero;
        Pintar(rt, color);
    }

    private void Etiqueta(RectTransform zona, float x0, float x1, string texto)
    {
        Text t = Texto(zona, texto, 12, FontStyle.Normal, TextAnchor.UpperCenter, Apagado);
        RectTransform rt = t.rectTransform;
        rt.anchorMin = new Vector2(x0, 0f);
        rt.anchorMax = new Vector2(x1, 0f);
        rt.pivot = new Vector2(0.5f, 1f);
        rt.anchoredPosition = new Vector2(0f, -2f);
        rt.sizeDelta = new Vector2(0f, 16f);
    }

    private static string Reloj(int tramo)
    {
        string[] horas = { "8-10", "10-12", "12-14", "14-16", "16-18" };
        return tramo < horas.Length ? horas[tramo] : "";
    }

    private static void Limpiar(RectTransform zona)
    {
        for (int i = zona.childCount - 1; i >= 0; i--)
            Destroy(zona.GetChild(i).gameObject);
    }

    private static float Maximo(List<float> v)
    {
        float m = 0f;
        foreach (float x in v) if (x > m) m = x;
        return m;
    }

    private static RectTransform Rect(string nombre, Transform padre)
    {
        GameObject go = new GameObject(nombre, typeof(RectTransform));
        go.transform.SetParent(padre, false);
        return (RectTransform)go.transform;
    }

    private static void Estirar(RectTransform rt)
    {
        rt.anchorMin = Vector2.zero;
        rt.anchorMax = Vector2.one;
        rt.offsetMin = Vector2.zero;
        rt.offsetMax = Vector2.zero;
    }

    private static void Colocar(RectTransform rt, float x0, float x1, float y0, float y1)
    {
        rt.anchorMin = new Vector2(x0, y0);
        rt.anchorMax = new Vector2(x1, y1);
        rt.offsetMin = Vector2.zero;
        rt.offsetMax = Vector2.zero;
    }

    private static void Pintar(RectTransform rt, Color color)
    {
        Image imagen = rt.gameObject.AddComponent<Image>();
        imagen.color = color;
        imagen.raycastTarget = false;
    }

    private Text Texto(Transform padre, string contenido, int tamano, FontStyle estilo,
                       TextAnchor alineacion, Color color)
    {
        RectTransform rt = Rect("Texto", padre);
        Text t = rt.gameObject.AddComponent<Text>();
        t.font = fuente;
        t.text = contenido;
        t.fontSize = tamano;
        t.fontStyle = estilo;
        t.alignment = alineacion;
        t.color = color;
        t.horizontalOverflow = HorizontalWrapMode.Overflow;
        t.verticalOverflow = VerticalWrapMode.Overflow;
        t.raycastTarget = false;
        return t;
    }

    private static Font FuenteBase()
    {
        Font f = null;
        try { f = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf"); } catch { }
        if (f == null) { try { f = Resources.GetBuiltinResource<Font>("Arial.ttf"); } catch { } }
        if (f == null) f = Font.CreateDynamicFontFromOSFont("Arial", 16);
        return f;
    }

    // --------------------------------------------------- lectura de JSON ---

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

    /// <summary>Lee un arreglo de números. JsonUtility no sirve aquí porque los
    /// payloads son objetos anidados con arreglos sueltos, no clases planas.</summary>
    private static List<float> Numeros(string json, string clave)
    {
        List<float> salida = new List<float>();
        if (string.IsNullOrEmpty(json)) return salida;
        int abre = InicioValor(json, clave);
        if (abre < 0 || json[abre] != '[') return salida;
        int cierra = json.IndexOf(']', abre + 1);
        if (cierra < 0) return salida;

        foreach (Match m in Regex.Matches(json.Substring(abre, cierra - abre),
                                          "-?[0-9]+(?:\\.[0-9]+)?(?:[eE][-+]?[0-9]+)?"))
        {
            float v;
            if (float.TryParse(m.Value, NumberStyles.Float, CultureInfo.InvariantCulture, out v))
                salida.Add(v);
        }
        return salida;
    }

    private static double Numero(string json, string clave, double porDefecto)
    {
        if (string.IsNullOrEmpty(json)) return porDefecto;
        Match m = Regex.Match(json, "\"" + Regex.Escape(clave)
            + "\"\\s*:\\s*(-?[0-9]+(?:\\.[0-9]+)?(?:[eE][-+]?[0-9]+)?)");
        double v;
        if (!m.Success) return porDefecto;
        return double.TryParse(m.Groups[1].Value, NumberStyles.Float,
            CultureInfo.InvariantCulture, out v) ? v : porDefecto;
    }
}
