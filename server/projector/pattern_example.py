#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Esempio di utilizzo della libreria DLPC342X I2C per generare pattern progressivi
simili a Gray code per scansione 3D strutturata.
"""

import time
import logging
import argparse

# Configura logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("PatternProgressivi")

# Importa il modulo del proiettore
try:
    # Quando il file è nella stessa directory della libreria
    from server.projector import DLPC342XController, OperatingMode, Color, BorderEnable
except ImportError:
    # Quando importato come modulo esterno
    from dlp342x import DLPC342XController, OperatingMode, Color, BorderEnable


def genera_pattern_progressivi(controller, num_steps=8, tempo_esposizione=1.0):
    """
    Genera una sequenza di pattern con linee che diventano progressivamente più sottili.

    Args:
        controller: Istanza del controller DLPC342X
        num_steps: Numero di pattern da generare per tipo (verticali/orizzontali)
        tempo_esposizione: Tempo in secondi per ogni pattern
    """
    # Imposta il proiettore in modalità pattern
    logger.info("Impostazione proiettore in modalità pattern generator...")
    controller.set_operating_mode(OperatingMode.TestPatternGenerator)
    time.sleep(0.5)  # Attendi che il proiettore cambi modalità

    # Prima genera un pattern bianco per riferimento
    logger.info("Proiezione pattern bianco di riferimento...")
    controller.generate_solid_field(Color.White)
    time.sleep(tempo_esposizione)

    # Sequenza di linee verticali (diventano sempre più sottili)
    logger.info("Inizio sequenza linee verticali...")

    for i in range(num_steps):
        # Calcola la larghezza delle linee per questo step
        # Inizia con linee larghe e dimezza ad ogni passo
        width = max(1, 64 // (2 ** i))

        logger.info(f"Proiezione linee verticali, passo {i + 1}/{num_steps}, larghezza={width}")

        controller.generate_vertical_lines(
            background_color=Color.Black,
            foreground_color=Color.White,
            foreground_line_width=width,
            background_line_width=width
        )

        # Attendi tempo sufficiente per l'acquisizione
        time.sleep(tempo_esposizione)

    # Sequenza di linee orizzontali (diventano sempre più sottili)
    logger.info("Inizio sequenza linee orizzontali...")

    for i in range(num_steps):
        # Calcola la larghezza delle linee per questo step
        width = max(1, 64 // (2 ** i))

        logger.info(f"Proiezione linee orizzontali, passo {i + 1}/{num_steps}, larghezza={width}")

        controller.generate_horizontal_lines(
            background_color=Color.Black,
            foreground_color=Color.White,
            foreground_line_width=width,
            background_line_width=width
        )

        # Attendi tempo sufficiente per l'acquisizione
        time.sleep(tempo_esposizione)

    # Alla fine, genera un pattern nero per riferimento
    logger.info("Proiezione pattern nero di riferimento...")
    controller.generate_solid_field(Color.Black)
    time.sleep(tempo_esposizione)

    # Torna alla modalità video esterna
    logger.info("Ritorno alla modalità video esterna...")
    controller.set_operating_mode(OperatingMode.ExternalVideoPort)


def genera_sequenza_gray_code_semplificata(controller, num_steps=8, tempo_esposizione=1.0):
    """
    Genera una sequenza di pattern simili al Gray code ma semplificati.

    Args:
        controller: Istanza del controller DLPC342X
        num_steps: Numero di pattern per direzione
        tempo_esposizione: Tempo in secondi per ogni pattern
    """
    # Imposta il proiettore in modalità pattern
    logger.info("Impostazione proiettore in modalità pattern generator...")
    controller.set_operating_mode(OperatingMode.TestPatternGenerator)
    time.sleep(0.5)  # Attendi che il proiettore cambi modalità

    # Genera pattern white/black di riferimento
    logger.info("Proiezione pattern bianco di riferimento...")
    controller.generate_solid_field(Color.White)
    time.sleep(tempo_esposizione)

    logger.info("Proiezione pattern nero di riferimento...")
    controller.generate_solid_field(Color.Black)
    time.sleep(tempo_esposizione)

    # Pattern di linee verticali
    for i in range(num_steps):
        # La larghezza delle linee dipende dal bit che stiamo codificando
        # Simula il Gray code utilizzando linee di larghezza diversa
        width = max(1, 512 // (2 ** i))

        logger.info(f"Proiezione Gray code verticale, bit {i + 1}/{num_steps}, larghezza={width}")

        controller.generate_vertical_lines(
            background_color=Color.Black,
            foreground_color=Color.White,
            foreground_line_width=width,
            background_line_width=width
        )

        time.sleep(tempo_esposizione)

    # Pattern di linee orizzontali
    for i in range(num_steps):
        width = max(1, 512 // (2 ** i))

        logger.info(f"Proiezione Gray code orizzontale, bit {i + 1}/{num_steps}, larghezza={width}")

        controller.generate_horizontal_lines(
            background_color=Color.Black,
            foreground_color=Color.White,
            foreground_line_width=width,
            background_line_width=width
        )

        time.sleep(tempo_esposizione)

    # Torna alla modalità video esterna
    logger.info("Ritorno alla modalità video esterna...")
    controller.set_operating_mode(OperatingMode.ExternalVideoPort)


def genera_pattern_singoli(controller):
    """
    Genera i pattern base uno per uno, con pausa tra ciascuno.
    Utile per il debug e per verificare che tutti i pattern funzionano.
    """
    # Imposta il proiettore in modalità pattern
    logger.info("Impostazione proiettore in modalità pattern generator...")
    controller.set_operating_mode(OperatingMode.TestPatternGenerator)
    time.sleep(0.5)

    # Campo solido bianco
    logger.info("Proiezione campo solido bianco...")
    controller.generate_solid_field(Color.White)
    input("Premi INVIO per continuare...")

    # Campo solido nero
    logger.info("Proiezione campo solido nero...")
    controller.generate_solid_field(Color.Black)
    input("Premi INVIO per continuare...")

    # Linee verticali
    logger.info("Proiezione linee verticali...")
    controller.generate_vertical_lines(
        background_color=Color.Black,
        foreground_color=Color.White,
        foreground_line_width=10,
        background_line_width=20
    )
    input("Premi INVIO per continuare...")

    # Linee orizzontali
    logger.info("Proiezione linee orizzontali...")
    controller.generate_horizontal_lines(
        background_color=Color.Black,
        foreground_color=Color.White,
        foreground_line_width=10,
        background_line_width=20
    )
    input("Premi INVIO per continuare...")

    # Griglia
    logger.info("Proiezione griglia...")
    controller.generate_grid(
        background_color=Color.Black,
        foreground_color=Color.White,
        horizontal_foreground_width=4,
        horizontal_background_width=20,
        vertical_foreground_width=4,
        vertical_background_width=20
    )
    input("Premi INVIO per continuare...")

    # Torna alla modalità video esterna
    logger.info("Ritorno alla modalità video esterna...")
    controller.set_operating_mode(OperatingMode.ExternalVideoPort)


def main():
    """Funzione principale dell'esempio."""
    # Analizza gli argomenti
    parser = argparse.ArgumentParser(description='Generatore di pattern per DLPC342X')
    parser.add_argument('--bus', type=int, default=3,
                        help='Numero del bus I2C (default: 3)')
    parser.add_argument('--address', type=int, default=0x36,
                        help='Indirizzo I2C in esadecimale (default: 0x36)')
    parser.add_argument('--mode', type=str, default='progressivi',
                        choices=['progressivi', 'gray', 'singoli'],
                        help='Modalità di pattern (default: progressivi)')
    parser.add_argument('--steps', type=int, default=8,
                        help='Numero di pattern per sequenza (default: 8)')
    parser.add_argument('--exposure', type=float, default=1.0,
                        help='Tempo di esposizione per ogni pattern in secondi (default: 1.0)')
    args = parser.parse_args()

    # Inizializza il controller
    logger.info(f"Inizializzazione controller DLPC342X su bus {args.bus}, indirizzo 0x{args.address:02X}")
    controller = DLPC342XController(bus=args.bus, address=args.address)

    try:
        # Esegui la modalità selezionata
        if args.mode == 'progressivi':
            genera_pattern_progressivi(controller, args.steps, args.exposure)
        elif args.mode == 'gray':
            genera_sequenza_gray_code_semplificata(controller, args.steps, args.exposure)
        elif args.mode == 'singoli':
            genera_pattern_singoli(controller)

    except KeyboardInterrupt:
        logger.info("Operazione interrotta dall'utente")
        # Torna alla modalità video esterna
        controller.set_operating_mode(OperatingMode.ExternalVideoPort)
    except Exception as e:
        logger.error(f"Errore durante l'operazione: {e}")
    finally:
        # Pulizia
        controller.close()
        logger.info("Controller chiuso")


if __name__ == "__main__":
    main()