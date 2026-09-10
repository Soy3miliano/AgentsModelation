using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Networking;
using System.Text.RegularExpressions;

public class EscenarioManager : MonoBehaviour
{
    public string apiUrlElementos = "http://localhost:5000/api/elementos";

    [Header("Muebles (Prefabs)")]
    public GameObject puertaPrefab;
    public GameObject moduloIdPrefab;
    public GameObject mamparaPrefab;
    public GameObject urnaPrefab;

    [Header("Escala del Espacio")]
    public float gridScale = 4f;

    [Header("Ajuste fino de mamparas (solo visual)")]
    [Tooltip("Se suma a la posición de mundo de cada mampara. La casilla lógica " +
             "no cambia: úsalo para pegar el mueble a la pared. +Z = hacia el muro " +
             "superior, -X = hacia la izquierda.")]
    public Vector3 offsetMampara = new Vector3(0f, 0f, 1.2f);
    [Tooltip("Rotación (euler) de las mamparas. Suelen mirar hacia el interior del salón.")]
    public Vector3 rotacionMampara = Vector3.zero;

    [Header("Ajuste fino del módulo ID (solo visual)")]
    [Tooltip("La mesa ocupa la celda (0,1). El funcionario está detrás en (0,0) y " +
             "la fila empieza delante, en (0,2): ningún votante pisa la mesa. Este " +
             "offset solo mueve el modelo (centrarlo entre funcionario y votante, etc).")]
    public Vector3 offsetModuloId = Vector3.zero;
    public Vector3 rotacionModuloId = Vector3.zero;

    [Header("Puertas")]
    [Tooltip("Si está DESACTIVADO, este manager no genera las puertas: colócalas " +
             "tú a mano en la escena donde quieras. Las puertas son solo visuales, " +
             "no afectan a la simulación (los agentes caminan a las casillas 0,9 y " +
             "9,9 pase lo que pase).")]
    public bool colocarPuertas = true;

    [Header("Ajuste fino de puertas (solo si 'Colocar Puertas' está activo)")]
    [Tooltip("Offset/rotación de la puerta de ENTRADA para encajarla en el hueco " +
             "del muro. La casilla (0,9) a la que caminan los agentes no cambia.")]
    public Vector3 offsetPuertaEntrada = Vector3.zero;
    public Vector3 rotacionPuertaEntrada = Vector3.zero;
    [Tooltip("Offset/rotación de la puerta de SALIDA. La casilla (9,9) no cambia.")]
    public Vector3 offsetPuertaSalida = Vector3.zero;
    public Vector3 rotacionPuertaSalida = Vector3.zero;

    // Todo lo instanciado por este manager, para poder rehacer el layout tras un reset.
    private readonly List<GameObject> mueblesInstanciados = new List<GameObject>();

    // Props ajustables en vivo desde el Inspector (sin reconstruir): guardamos su
    // Transform + su posicion base en el tablero (sin offset).
    private readonly List<Transform> mamparas = new List<Transform>();
    private readonly List<Vector3> mamparasBasePos = new List<Vector3>();
    private Transform puertaEntradaTf, puertaSalidaTf;
    private Vector3 puertaEntradaBase, puertaSalidaBase;
    private Transform moduloIdTf;
    private Vector3 moduloIdBase;

    void Start()
    {
        StartCoroutine(ConstruirLayout());
    }

    void Update()
    {
        // Aplicar offset/rotacion cada frame: mover los sliders en el Inspector
        // durante Play recoloca los props al instante. Son pocos objetos, es barato.
        Quaternion rotMampara = Quaternion.Euler(rotacionMampara);
        for (int i = 0; i < mamparas.Count; i++)
        {
            if (mamparas[i] == null) continue;
            mamparas[i].SetPositionAndRotation(mamparasBasePos[i] + offsetMampara, rotMampara);
        }

        if (puertaEntradaTf != null)
            puertaEntradaTf.SetPositionAndRotation(
                puertaEntradaBase + offsetPuertaEntrada, Quaternion.Euler(rotacionPuertaEntrada));
        if (puertaSalidaTf != null)
            puertaSalidaTf.SetPositionAndRotation(
                puertaSalidaBase + offsetPuertaSalida, Quaternion.Euler(rotacionPuertaSalida));

        if (moduloIdTf != null)
            moduloIdTf.SetPositionAndRotation(
                moduloIdBase + offsetModuloId, Quaternion.Euler(rotacionModuloId));
    }

    /// <summary>
    /// Vuelve a pedir /api/elementos y reconstruye los muebles. Se llama tras un
    /// reset del backend, porque cambiar voting_booth_capacity cambia las mamparas.
    /// </summary>
    public void Reconstruir()
    {
        StartCoroutine(ConstruirLayout());
    }

    private void LimpiarMuebles()
    {
        foreach (var mueble in mueblesInstanciados)
        {
            if (mueble != null) Destroy(mueble);
        }
        mueblesInstanciados.Clear();
        mamparas.Clear();
        mamparasBasePos.Clear();
        puertaEntradaTf = null;
        puertaSalidaTf = null;
        moduloIdTf = null;
    }

    private IEnumerator ConstruirLayout()
    {
        using (UnityWebRequest request = UnityWebRequest.Get(apiUrlElementos))
        {
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                LimpiarMuebles();
                ColocarMuebles(request.downloadHandler.text);
            }
            else
            {
                Debug.LogError("Error cargando escenario: " + request.error);
            }
        }
    }

    private void Colocar(GameObject prefab, Vector3 posMundo)
    {
        mueblesInstanciados.Add(Instantiate(prefab, posMundo, Quaternion.identity));
    }

    private void ColocarMuebles(string json)
    {
        // 1. Puertas (opcional). Son solo decoración: si 'colocarPuertas' está
        //    apagado, las pones tú a mano en la escena. Si está encendido, el
        //    offset/rotación se ajusta en vivo desde el Inspector.
        if (colocarPuertas)
        {
            puertaEntradaBase = ExtraerUnica(json, "puerta_entrada") * gridScale;
            GameObject pe = Instantiate(puertaPrefab, puertaEntradaBase + offsetPuertaEntrada, Quaternion.Euler(rotacionPuertaEntrada));
            mueblesInstanciados.Add(pe);
            puertaEntradaTf = pe.transform;

            puertaSalidaBase = ExtraerUnica(json, "puerta_salida") * gridScale;
            GameObject ps = Instantiate(puertaPrefab, puertaSalidaBase + offsetPuertaSalida, Quaternion.Euler(rotacionPuertaSalida));
            mueblesInstanciados.Add(ps);
            puertaSalidaTf = ps.transform;
        }

        // 2. Módulo de Identificación (mesa). El offset/rotación se ajusta en vivo.
        moduloIdBase = ExtraerUnica(json, "modulo_id") * gridScale;
        GameObject mid = Instantiate(moduloIdPrefab, moduloIdBase + offsetModuloId, Quaternion.Euler(rotacionModuloId));
        mueblesInstanciados.Add(mid);
        moduloIdTf = mid.transform;

        // 3. Urna
        Colocar(urnaPrefab, ExtraerUnica(json, "urna") * gridScale);

        // 4. Mamparas (pueden ser múltiples). El offset/rotación se aplica en
        //    Update(), no aquí, para poder afinarlo en vivo desde el Inspector.
        List<Vector3> posMamparas = ExtraerMultiples(json, "mamparas");
        foreach (var pos in posMamparas)
        {
            Vector3 basePos = pos * gridScale;
            GameObject m = Instantiate(mamparaPrefab, basePos + offsetMampara, Quaternion.Euler(rotacionMampara));
            mueblesInstanciados.Add(m);
            mamparas.Add(m.transform);
            mamparasBasePos.Add(basePos);
        }
    }
    // --- Funciones para leer el JSON crudo ---
    private Vector3 ExtraerUnica(string json, string clave)
    {
    string patron = $"\"{clave}\"\\s*:\\s*\\[\\s*(\\d+)\\s*,\\s*(\\d+)\\s*\\]";
    Match match = Regex.Match(json, patron);
    if (match.Success)
    {
        return new Vector3(float.Parse(match.Groups[1].Value), 0, float.Parse(match.Groups[2].Value));
    }
    return Vector3.zero;
}
    private List<Vector3> ExtraerMultiples(string json, string clave)
    {
        List<Vector3> lista = new List<Vector3>();
        string strClave = $"\"{clave}\":";
        int index = json.IndexOf(strClave);
        if (index == -1) return lista;

        string sub = json.Substring(index + strClave.Length);
        int start = sub.IndexOf('[');
        int brackets = 0, end = start;

        for (int i = start; i < sub.Length; i++)
        {
            if (sub[i] == '[') brackets++;
            else if (sub[i] == ']') brackets--;

            if (brackets == 0) { end = i; break; }
        }

        string bloque = sub.Substring(start, (end - start) + 1);
        MatchCollection matches = Regex.Matches(bloque, "\\[\\s*(\\d+)\\s*,\\s*(\\d+)\\s*\\]");
        foreach (Match match in matches)
        {
            lista.Add(new Vector3(float.Parse(match.Groups[1].Value), 0, float.Parse(match.Groups[2].Value)));
        }
        return lista;
    }
}
