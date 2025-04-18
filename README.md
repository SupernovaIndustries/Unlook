# UnLook - Client Scanner 3D

UnLook è uno scanner 3D open source e modulare basato su Raspberry Pi CM4, progettato per essere versatile con modalità di scansione variabili:
- Modalità di scansione a luce strutturata con due camere e proiettore DLP personalizzato
- Modalità di scansione real-time con sensore ToF MLX75027
- Sistema di ottiche intercambiabili come una macchina fotografica

## Architettura del sistema

Il sistema UnLook è composto da due componenti principali:

### Server (Raspberry Pi)
- Gestisce due camere sincronizzate tramite PiCamera2
- Controlla il proiettore DLP per la proiezione dei pattern
- Invia lo stream video al client
- Gestisce l'hardware modulare (ToF, DLP, ecc.)

### Client (PC)
- Interfaccia utente PyQt5 per il controllo dello scanner
- Visualizzazione dual-camera in tempo reale
- Elaborazione e post-processing con OpenCV
- Configurazione dei parametri di scansione
- Discovery automatica degli scanner nella rete

## Funzionalità principali

- **Discovery automatica**: Rilevamento degli scanner disponibili nella rete locale tramite multicast
- **Streaming video dual-camera**: Visualizzazione in tempo reale di entrambe le camere
- **Interfaccia integrata**: Gestione dello scanner e visualizzazione dei dati in un'unica interfaccia
- **Sistema di pairing**: Associazione sicura tra client e scanner
- **Configurazione avanzata**: Controllo dei parametri di acquisizione (risoluzione, FPS, esposizione, ecc.)
- **Acquisizione e processing**: Elaborazione immediata dei dati acquisiti

## Requisiti

### Client
- Python 3.8+
- PySide2 (Qt 5.15+)
- OpenCV 4.5+
- NumPy
- Connessione di rete per la comunicazione con lo scanner

### Server
- Raspberry Pi con Compute Module 4
- Raspberry Pi OS (Bullseye o più recente)
- PiCamera2
- Hardware dedicato (camere, proiettore DLP, sensore ToF)

## Installazione

### Client

1. Clona il repository:
```
git clone https://github.com/supernovaindustries/unlook.git
cd unlook
```

2. Crea un ambiente virtuale (opzionale ma consigliato):
```
python -m venv venv
source venv/bin/activate  # Su Windows: venv\Scripts\activate
```

3. Installa le dipendenze:
```
pip install -r requirements.txt
```

4. Avvia l'applicazione client:
```
python -m client.main
```

## Struttura del progetto

```
unlook/
├── client/
│   ├── controllers/        # Controller per la logica dell'applicazione
│   ├── models/             # Modelli per i dati dell'applicazione
│   ├── views/              # Viste per l'interfaccia utente
│   ├── network/            # Gestione della rete e delle connessioni
│   ├── processing/         # Elaborazione delle immagini e dei dati
│   ├── utils/              # Utilità varie
│   └── main.py             # Punto di ingresso dell'applicazione
├── server/                 # [Implementazione lato server]
├── common/                 # Codice condiviso tra client e server
├── requirements.txt        # Dipendenze del progetto
└── README.md               # Documentazione principale
```

## Roadmap di sviluppo

1. **MVP Giugno 2025**
   - Interfaccia cliente base con discovery e streaming
   - Supporto per la modalità di scansione a luce strutturata
   - Calibrazione semplificata

2. **Sviluppo futuro**
   - Integrazione completa del sensore ToF
   - API per il controllo programmatico dello scanner
   - Supporto per scansioni a colori ad alta risoluzione
   - Integrazione con software di modellazione 3D

## Licenza

Questo progetto è rilasciato sotto licenza MIT. Vedi il file LICENSE per i dettagli.

## Contribuire

I contributi sono benvenuti! Per favore, consulta le linee guida per i contributi nel file CONTRIBUTING.md prima di iniziare.

## Contatti

SupernovaIndustries - info@supernovaindustries.com

---

© 2025 SupernovaIndustries. Tutti i diritti riservati.# Unlook
 
