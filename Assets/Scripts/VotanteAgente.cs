using UnityEngine;

public class VotanteAgent : MonoBehaviour
{
    private Animator animator;

    [Header("Configuración")]
    public bool esFijo = false; // El freno de mano

    [Header("Banderas de Progreso (Flags)")]
    public bool yaVoto = false;      // Registró ticket en mampara
    public bool yaDeposito = false;  // Tiró voto en la urna
    private string currentStatus = "";

    [Header("Visuales Opcionales")]
    public GameObject ticketObjeto;  // Referencia a una boleta 3D en la mano (opcional)

    [Header("Movimiento")]
    public float moveSpeed = 3.0f;
    public float rotationSpeed = 10.0f;
    public Vector3 targetPosition;
    private bool isMoving = false;

    // Hashes para optimizar el Animator
    private static readonly int IsWalkingHash = Animator.StringToHash("isWalking");
    private static readonly int IsTalkingHash = Animator.StringToHash("isTalking");
    private static readonly int IsVotingHash = Animator.StringToHash("isVoting");
    private static readonly int VoteTriggerHash = Animator.StringToHash("voteTrigger");

    void Awake()
    {
        animator = GetComponent<Animator>();
        targetPosition = transform.position;
    }

    void Update()
    {
        if (esFijo) return; // Si es oficial, ignoramos todo y lo dejamos petrificado

        Vector3 targetOnPlane = new Vector3(targetPosition.x, transform.position.y, targetPosition.z);
        float distance = Vector3.Distance(transform.position, targetOnPlane);

        if (distance > 0.08f)
        {
            isMoving = true;
            Vector3 direction = (targetOnPlane - transform.position).normalized;

            if (direction.sqrMagnitude > 0.001f)
            {
                Quaternion targetRotation = Quaternion.LookRotation(direction);
                transform.rotation = Quaternion.Slerp(transform.rotation, targetRotation, rotationSpeed * Time.deltaTime);
            }

            transform.position = Vector3.MoveTowards(transform.position, targetOnPlane, moveSpeed * Time.deltaTime);
        }
        else
        {
            isMoving = false;
        }

        if (animator != null)
        {
            animator.SetBool(IsWalkingHash, isMoving);
        }
    }

    public void UpdateAgentData(Vector3 newGridPos, string status)
    {
        targetPosition = newGridPos;

        if (esFijo) return;

        // Manejar cambio de estado e hitos únicos
        if (currentStatus != status)
        {
            currentStatus = status;
            ProcesarFlags(currentStatus);
        }

        if (animator == null) return;

        animator.SetBool(IsTalkingHash, false);
        animator.SetBool(IsVotingHash, false);

        switch (status)
        {
            case "PENDING_VERIFICATION":
            case "VERIFYING":
                animator.SetBool(IsTalkingHash, true);
                break;

            case "VOTING":
                animator.SetBool(IsVotingHash, true);
                break;

            case "PENDING_BALLOT":
            case "DROPPING_VOTE":
                // Se asegura de disparar el trigger solo una vez cuando alcanza la urna
                if (yaVoto && !yaDeposito)
                {
                    animator.SetTrigger(VoteTriggerHash);
                }
                break;
        }
    }

    private void ProcesarFlags(string status)
    {
        switch (status)
        {
            case "VOTING":
                if (!yaVoto)
                {
                    yaVoto = true;
                    if (ticketObjeto != null) ticketObjeto.SetActive(true);
                    Debug.Log($"[{gameObject.name}] Registró su ticket en la mampara.");
                }
                break;

            case "PENDING_BALLOT":
            case "DROPPING_VOTE":
                if (yaVoto && !yaDeposito)
                {
                    yaDeposito = true;
                    if (ticketObjeto != null) ticketObjeto.SetActive(false);
                    Debug.Log($"[{gameObject.name}] Depositó su boleta en la urna.");
                }
                break;

            case "DONE":
                Debug.Log($"[{gameObject.name}] Proceso completado, saliendo del aula.");
                break;
        }
    }
}