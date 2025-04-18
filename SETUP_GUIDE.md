# Guida all'Installazione e alla Risoluzione dei Problemi di UnLook

Questa guida dettagliata ti aiuterà a configurare correttamente l'ambiente di sviluppo per il progetto UnLook, sia per il lato client che per il lato server.

## 1. Requisiti di Sistema

### Client (PC)
- Sistema operativo: Windows 10/11, macOS, o Linux
- Python 3.8 o superiore
- RAM: almeno 4GB
- Spazio su disco: almeno 1GB libero
- Connessione di rete (preferibilmente via cavo per la migliore performance)

### Server (Raspberry Pi)
- Raspberry Pi con Compute Module 4
- Raspberry Pi OS Bullseye o più recente (64-bit consigliato)
- Moduli camera compatibili con Pi Camera
- Almeno 2GB di RAM
- Scheda microSD da almeno 16GB

## 2. Installazione del Client

### 2.1 Preparazione dell'Ambiente

1. **Installa Python**:
   - Windows: Scarica l'installer da [python.org](https://www.python.org/downloads/)
   - macOS: `brew install python3` (con Homebrew)
   - Linux: `sudo apt install python3 python3-pip` (Debian/Ubuntu)

2. **Clona il Repository**:
   ```bash
   git clone https://github.com/supernovaindustries/unlook.git
   cd unlook
   ```

3. **Crea un Ambiente Virtuale**:
   ```bash
   # Windows
   python -m venv .venv
   .venv\Scripts\activate

   # macOS/Linux
   python3 -m venv .venv
   source .venv/bin/activate
   ```

4. **Installa le Dipendenze**:
   ```bash
   pip install -r requirements.txt
   ```

   **Nota importante**: Se riscontri problemi durante l'installazione di PySide6, prova:
   ```bash
   # Installa wheel prima
   pip install wheel
   
   # Installa PySide6 separatamente
   pip install PySide6
   
   # Poi installa il resto delle dipendenze
   pip install -r requirements.txt
   ```

### 2.2 Esecuzione del Client

1. **Usa lo script launcher**:
   ```bash
   python start_unlook.py
   ```

2. **Diagnosi problemi**:
   Se incontri errori, esegui lo script di diagnostica:
   ```bash
   python diagnostic.py
   ```

3. **Risoluzione automatica dei problemi**:
   ```bash
   python diagnostic.py --fix
   ```

## 3. Installazione del Server (Raspberry Pi)

### 3.1 Preparazione della Raspberry Pi

1. **Installa Raspberry Pi OS**:
   - Usa Raspberry Pi Imager per installare Raspberry Pi OS Bullseye (64-bit consigliato)
   - Abilita SSH durante la configurazione
   - Configura WiFi se necessario

2. **Aggiorna il Sistema**:
   ```bash
   sudo apt update
   sudo apt upgrade -y
   ```

3. **Abilita la Camera**:
   ```bash
   sudo raspi-config
   ```
   Seleziona "Interface Options" > "Camera" e abilita l'interfaccia camera.

### 3.2 Installazione del Software UnLook

1. **Clona il Repository**:
   ```bash
   git clone https://github.com/supernovaindustries/unlook.git
   cd unlook/server
   ```

2. **Esegui lo Script di Installazione**:
   ```bash
   chmod +x install.sh
   sudo ./install.sh
   ```

3. **Verifica l'Installazione**:
   ```bash
   sudo systemctl status unlook.service
   ```

4. **Riavvia il Servizio** (se necessario):
   ```bash
   sudo systemctl restart unlook.service
   ```

## 4. Risoluzione dei Problemi Comuni

### 4.1 Problemi di Importazione nel Client

**Problema**: `ModuleNotFoundError: No module named 'views.main_window'`

**Soluzioni**:
1. Usa lo script launcher `start_unlook.py` invece di eseguire direttamente `client/main.py`
2. Esegui lo script di diagnostica: `python diagnostic.py --fix`
3. Verifica che tutti i file `__init__.py` siano presenti nelle directory del progetto

### 4.2 Problemi di Installazione di PySide6

**Problema**: `ERROR: No matching distribution found for PySide6`

**Soluzioni**:
1. Aggiorna pip: `pip install --upgrade pip`
2. Installa wheel: `pip install wheel`
3. Prova a installare direttamente dal sito ufficiale:
   ```bash
   pip install PySide6 --index-url=https://download.qt.io/official_releases/QtForPython/
   ```
4. Su Windows, assicurati di avere installato Visual C++ Redistributable: [Download](https://aka.ms/vs/17/release/vc_redist.x64.exe)

### 4.3 Problemi di Camera su Raspberry Pi

**Problema**: "Nessuna camera trovata" nel log del server

**Soluzioni**:
1. Verifica che la camera sia abilitata in raspi-config
2. Controlla che il cavo della camera sia collegato correttamente
3. Prova a riavviare la Raspberry Pi: `sudo reboot`
4. Verifica che la camera sia funzionante:
   ```bash
   libcamera-hello --timeout 5000
   ```

### 4.4 Problemi di Rete

**Problema**: Client non trova gli scanner sulla rete

**Soluzioni**:
1. Verifica che client e server siano sulla stessa rete locale
2. Controlla che non ci siano firewall che bloccano le porte:
   - Porta Discovery UDP: 5678
   - Porta Comandi TCP: 5680
   - Porta Streaming TCP: 5681
3. Verifica che il server sia in esecuzione: `sudo systemctl status unlook.service`
4. Prova a connetterti direttamente all'indirizzo IP del server tramite l'interfaccia manuale

## 5. Debugging Avanzato

### 5.1 Verifica dei Log

**Client**:
- I log del client si trovano in `~/.unlook/unlook.log`

**Server**:
- Visualizza i log del servizio: `sudo journalctl -u unlook.service -f`
- Log dettagliati: `/var/log/unlook/server.log`

### 5.2 Strumenti di Diagnostica di Rete

1. **Verifica la comunicazione di base**:
   ```bash
   ping <indirizzo-ip-raspberry>
   ```

2. **Verifica che le porte siano in ascolto**:
   ```bash
   # Sul server (Raspberry Pi)
   netstat -tuln | grep 568
   ```

3. **Test della porta di discovery**:
   ```bash
   # Dal client
   nc -u <indirizzo-ip-raspberry> 5678
   ```

### 5.3 Debug dello Stream Video

Se lo streaming video è lento o ha problemi:

1. **Riduci la risoluzione** nel file di configurazione del server (`/etc/unlook/config.json`)
2. **Cambia formato di streaming** da H.264 a JPEG se la decodifica H.264 è problematica
3. **Aumenta la compressione** (aumenta il valore "quality" per H.264, da 0-51, valori più alti = più compressione)
4. **Usa una connessione via cavo** invece di WiFi quando possibile

## 6. Sviluppo Futuro e Accesso ai Frame

Per integrare algoritmi di scansione 3D, è possibile accedere ai frame catturati in diversi modi:

### 6.1 Accesso Diretto ai Frame nel Client

I frame sono disponibili tramite il segnale `frame_received` della classe `StreamReceiver`:

```python
from client.network.stream_receiver import StreamReceiver

def process_frame(camera_index, frame):
    # frame è una matrice NumPy pronta per OpenCV
    # Implementa qui il tuo algoritmo di scansione 3D
    pass

# Collega il tuo handler al segnale
stream_receiver.frame_received.connect(process_frame)
```

### 6.2 Implementare un Nuovo Controller per l'Elaborazione 3D

Puoi creare un nuovo controller dedicato alla scansione 3D:

```python
# In client/controllers/scan_controller.py
class Scan3DController(QObject):
    scan_completed = Signal(object)  # Emette il risultato della scansione
    
    def __init__(self, stream_receiver):
        super().__init__()
        self.stream_receiver = stream_receiver
        self.stream_receiver.frame_received.connect(self._process_frame)
        self.frames_buffer = []
    
    def _process_frame(self, camera_index, frame):
        # Memorizza i frame per l'elaborazione
        self.frames_buffer.append((camera_index, frame))
        
        # Quando hai abbastanza frame, esegui la scansione 3D
        if len(self.frames_buffer) >= 10:  # esempio
            self._perform_3d_scan()
    
    def _perform_3d_scan(self):
        # Implementa qui il tuo algoritmo di scansione 3D
        # ...
        
        # Emetti il risultato
        self.scan_completed.emit(result)
```

## 7. Manutenzione e Aggiornamenti

1. **Aggiornamento del Client**:
   ```bash
   git pull
   pip install -r requirements.txt
   ```

2. **Aggiornamento del Server**:
   ```bash
   git pull
   cd server
   sudo ./install.sh
   sudo systemctl restart unlook.service
   ```

3. **Backup della Configurazione**:
   ```bash
   # Client
   cp ~/.unlook/config.json ~/.unlook/config.json.backup
   
   # Server
   sudo cp /etc/unlook/config.json /etc/unlook/config.json.backup
   ```

---

Per ulteriori informazioni o supporto, contatta:
- Email: info@supernovaindustries.com
- Documentazione aggiornata: https://github.com/supernovaindustries/unlook/wiki

© 2025 SupernovaIndustries