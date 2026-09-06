from agentes import ModeloCasilla

modelo = ModeloCasilla(n=100)

while modelo.running:
    modelo.step()

print("-" * 50)
print("Simulacion terminada")
print("Resumen:", modelo.resumen())
print("Resultados:", modelo.resultados)