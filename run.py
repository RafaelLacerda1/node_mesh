import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    # Garante que a pasta de dados existe
    if not os.path.exists('data'):
        os.makedirs('data')
        
    print("--> Iniciando Monitor de Nós Modular...")
    app.run(host="0.0.0.0", port=8080, debug=True)
