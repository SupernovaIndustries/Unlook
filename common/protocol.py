#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Definizione del protocollo di comunicazione tra client e server UnLook.
"""

from enum import Enum, auto
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass


class MessageType(Enum):
    """Tipi di messaggi del protocollo."""
    # Messaggi di discovery
    DISCOVER = "UNLOOK_DISCOVER"
    ANNOUNCE = "UNLOOK_ANNOUNCE"

    # Messaggi di controllo
    PING = "PING"
    GET_STATUS = "GET_STATUS"
    START_STREAM = "START_STREAM"
    STOP_STREAM = "STOP_STREAM"
    SET_CONFIG = "SET_CONFIG"
    GET_CONFIG = "GET_CONFIG"
    CAPTURE_FRAME = "CAPTURE_FRAME"

    # Messaggi di risposta
    RESPONSE = "RESPONSE"
    ERROR = "ERROR"

    # Messaggi di streaming
    FRAME = "FRAME"


class StreamFormat(Enum):
    """Formati di streaming supportati."""
    H264 = "h264"
    JPEG = "jpeg"
    RAW = "raw"


class CameraIndex(Enum):
    """Indici delle camere."""
    LEFT = 0
    RIGHT = 1


@dataclass
class Resolution:
    """Rappresenta una risoluzione video."""
    width: int
    height: int

    def as_tuple(self) -> tuple:
        """Restituisce la risoluzione come tupla (larghezza, altezza)."""
        return (self.width, self.height)

    def as_dict(self) -> Dict[str, int]:
        """Restituisce la risoluzione come dizionario."""
        return {"width": self.width, "height": self.height}

    @classmethod
    def from_tuple(cls, res_tuple: tuple) -> 'Resolution':
        """Crea una risoluzione da una tupla."""
        return cls(res_tuple[0], res_tuple[1])

    @classmethod
    def from_dict(cls, res_dict: Dict[str, int]) -> 'Resolution':
        """Crea una risoluzione da un dizionario."""
        return cls(res_dict["width"], res_dict["height"])


# Definizioni delle strutture dei messaggi

@dataclass
class DiscoverMessage:
    """Messaggio di scoperta per trovare scanner sulla rete."""
    client_version: str

    def to_dict(self) -> Dict[str, Any]:
        """Converte il messaggio in un dizionario."""
        return {
            "type": MessageType.DISCOVER.value,
            "client_version": self.client_version
        }


@dataclass
class AnnounceMessage:
    """Messaggio di annuncio inviato da uno scanner in risposta a una richiesta di scoperta."""
    device_id: str
    name: str
    version: str
    cameras: int
    port: int
    capabilities: Dict[str, bool]

    def to_dict(self) -> Dict[str, Any]:
        """Converte il messaggio in un dizionario."""
        return {
            "type": MessageType.ANNOUNCE.value,
            "device_id": self.device_id,
            "name": self.name,
            "version": self.version,
            "cameras": self.cameras,
            "port": self.port,
            "capabilities": self.capabilities
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnnounceMessage':
        """Crea un messaggio da un dizionario."""
        return cls(
            device_id=data["device_id"],
            name=data["name"],
            version=data["version"],
            cameras=data["cameras"],
            port=data["port"],
            capabilities=data["capabilities"]
        )


@dataclass
class PingMessage:
    """Messaggio ping per verificare la connessione."""
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        """Converte il messaggio in un dizionario."""
        return {
            "type": MessageType.PING.value,
            "timestamp": self.timestamp
        }


@dataclass
class StatusMessage:
    """Messaggio di stato per ottenere lo stato corrente del server."""

    def to_dict(self) -> Dict[str, Any]:
        """Converte il messaggio in un dizionario."""
        return {
            "type": MessageType.GET_STATUS.value
        }


@dataclass
class StreamControlMessage:
    """Messaggio per controllare lo streaming."""
    action: MessageType  # START_STREAM o STOP_STREAM
    format: Optional[StreamFormat] = None
    quality: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converte il messaggio in un dizionario."""
        result = {
            "type": self.action.value
        }

        if self.format:
            result["format"] = self.format.value

        if self.quality is not None:
            result["quality"] = self.quality

        return result


@dataclass
class ConfigMessage:
    """Messaggio per ottenere o impostare la configurazione."""
    action: MessageType  # GET_CONFIG o SET_CONFIG
    config: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converte il messaggio in un dizionario."""
        result = {
            "type": self.action.value
        }

        if self.config:
            result["config"] = self.config

        return result


@dataclass
class CaptureMessage:
    """Messaggio per catturare un frame."""

    def to_dict(self) -> Dict[str, Any]:
        """Converte il messaggio in un dizionario."""
        return {
            "type": MessageType.CAPTURE_FRAME.value
        }


@dataclass
class ResponseMessage:
    """Messaggio di risposta generico."""
    status: str  # "ok" o "error"
    original_type: str
    error: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Converte il messaggio in un dizionario."""
        result = {
            "type": MessageType.RESPONSE.value,
            "status": self.status,
            "original_type": self.original_type
        }

        if self.error:
            result["error"] = self.error

        if self.data:
            result.update(self.data)

        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ResponseMessage':
        """Crea un messaggio da un dizionario."""
        original_type = data.pop("original_type", "")
        status = data.pop("status", "error")
        error = data.pop("error", None)

        return cls(
            status=status,
            original_type=original_type,
            error=error,
            data=data
        )


@dataclass
class FrameMessage:
    """Messaggio per un frame video."""
    camera: CameraIndex
    frame_number: int
    timestamp: float
    format: StreamFormat
    resolution: Resolution
    data: bytes

    def to_header_dict(self) -> Dict[str, Any]:
        """Converte l'header del messaggio in un dizionario."""
        return {
            "camera": self.camera.value,
            "frame": self.frame_number,
            "timestamp": self.timestamp,
            "format": self.format.value,
            "resolution": self.resolution.as_tuple()
        }

    @classmethod
    def from_header_and_data(cls, header: Dict[str, Any], data: bytes) -> 'FrameMessage':
        """Crea un messaggio da un header e dai dati."""
        return cls(
            camera=CameraIndex(header["camera"]),
            frame_number=header["frame"],
            timestamp=header["timestamp"],
            format=StreamFormat(header["format"]),
            resolution=Resolution.from_tuple(header["resolution"]),
            data=data
        )


def parse_message(data: Dict[str, Any]) -> Any:
    """
    Parse di un messaggio da un dizionario JSON.

    Args:
        data: Dizionario JSON

    Returns:
        Oggetto messaggio

    Raises:
        ValueError: Se il tipo di messaggio non è valido
    """
    if "type" not in data:
        raise ValueError("Tipo di messaggio mancante")

    message_type = data["type"]

    if message_type == MessageType.DISCOVER.value:
        return DiscoverMessage(client_version=data.get("client_version", "unknown"))

    elif message_type == MessageType.ANNOUNCE.value:
        return AnnounceMessage.from_dict(data)

    elif message_type == MessageType.PING.value:
        return PingMessage(timestamp=data.get("timestamp", 0.0))

    elif message_type == MessageType.GET_STATUS.value:
        return StatusMessage()

    elif message_type == MessageType.START_STREAM.value:
        format_str = data.get("format")
        format_enum = StreamFormat(format_str) if format_str else None
        return StreamControlMessage(
            action=MessageType.START_STREAM,
            format=format_enum,
            quality=data.get("quality")
        )

    elif message_type == MessageType.STOP_STREAM.value:
        return StreamControlMessage(action=MessageType.STOP_STREAM)

    elif message_type == MessageType.GET_CONFIG.value:
        return ConfigMessage(action=MessageType.GET_CONFIG)

    elif message_type == MessageType.SET_CONFIG.value:
        return ConfigMessage(
            action=MessageType.SET_CONFIG,
            config=data.get("config", {})
        )

    elif message_type == MessageType.CAPTURE_FRAME.value:
        return CaptureMessage()

    elif message_type == MessageType.RESPONSE.value:
        return ResponseMessage.from_dict(data)

    else:
        raise ValueError(f"Tipo di messaggio non valido: {message_type}")