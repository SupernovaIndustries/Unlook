#-------------------------------------------------------------------------------
# Copyright (c) 2024 Texas Instruments Incorporated - http://www.ti.com/
#-------------------------------------------------------------------------------
#
# NOTE: This file is auto generated from a command definition file.
#       Please do not modify the file directly.                    
#
# Command Spec Version : 1.0
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#   Redistributions of source code must retain the above copyright
#   notice, this list of conditions and the following disclaimer.
#
#   Redistributions in binary form must reproduce the above copyright
#   notice, this list of conditions and the following disclaimer in the
#   documentation and/or other materials provided with the
#   distribution.
#
#   Neither the name of Texas Instruments Incorporated nor the names of
#   its contributors may be used to endorse or promote products derived
#   from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import struct
from enum import Enum

import sys, os.path
python_dir = (os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(python_dir)
from .packer import *

class OperatingMode(Enum):
    ExternalVideoPort = 0
    TestPatternGenerator = 1
    SplashScreen = 2
    SensExternalPattern = 3
    SensInternalPattern = 4
    SensSplashPattern = 5
    Standby = 255

class ChromaInterpolationMethod(Enum):
    ChromaInterpolation = 0
    ChromaCopy = 1

class ChromaChannelSwap(Enum):
    Cbcr = 0
    Crcb = 1

class ImageCurtainEnable(Enum):
    Disable = 0
    Enable = 1

class ControllerDeviceId(Enum):
    Dlpc3430 = 0
    Dlpc3433 = 1
    Dlpc3432 = 2
    Dlpc3434 = 3
    Dlpc3435 = 4
    Dlpc3438 = 5
    Dlpc3436 = 6
    Dlpc3437 = 7
    Dlpc3472 = 8
    Dlpc3439 = 9
    Dlpc3440 = 10
    Dlpc3478 = 11
    Dlpc3479 = 12
    Dlpc3470 = 15
    Dlpc3421 = 14

class ExternalVideoFormat(Enum):
    Dsi = 0
    ParallelRgb565Bw16 = 64
    ParallelRgb666Bw18 = 65
    ParallelRgb888Bw8 = 66
    ParallelRgb888Bw24 = 67
    ParallelYcbcr666Bw18 = 80
    ParallelYcbcr888Bw24 = 81
    ParallelYcbcr422Bw8 = 96
    ParallelYcbcr422Bw16 = 97
    Bt656 = 160

class Color(Enum):
    Black = 0
    Red = 1
    Green = 2
    Blue = 3
    Cyan = 4
    Magenta = 5
    Yellow = 6
    White = 7

class DiagonalLineSpacing(Enum):
    Dls3 = 3
    Dls7 = 7
    Dls15 = 15
    Dls31 = 31
    Dls63 = 63
    Dls127 = 127
    Dls255 = 255

class TestPattern(Enum):
    SolidField = 0
    HorizontalRamp = 1
    VerticalRamp = 2
    HorizontalLines = 3
    DiagonalLines = 4
    VerticalLines = 5
    Grid = 6
    Checkerboard = 7
    Colorbars = 8

class PixelFormats(Enum):
    Rgb565 = 2
    Ycbcr422 = 3

class CompressionTypes(Enum):
    Uncompressed = 0
    RgbRleCompressed = 1
    Unused = 2
    YuvRleCompressed = 3

class ColorOrders(Enum):
    Rgb = 0
    Grb = 1

class ChromaOrders(Enum):
    CrFirst = 0
    CbFirst = 1

class ByteOrders(Enum):
    LittleEndian = 0
    BigEndian = 1

class ImageFlip(Enum):
    ImageNotFlipped = 0
    ImageFlipped = 1

class BorderEnable(Enum):
    Disable = 0
    Enable = 1

class LedControlMethod(Enum):
    Manual = 0
    Automatic = 1

class LabbControl(Enum):
    Disabled = 0
    Manual = 1
    Automatic = 2

class CaicGainDisplayScale(Enum):
    P1024 = 0
    P512 = 1

class SystemInit(Enum):
    NotComplete = 0
    Complete = 1

class Error(Enum):
    NoError = 0
    Error = 1

class SensingError(Enum):
    NoError = 0
    IlluminationTimeNotSupported = 1
    PreIlluminationTimeNotSupported = 2
    PostIlluminationTimeNotSupported = 3
    TriggerOut1DelayNotSupported = 4
    TriggerOut2DelayNotSupported = 5
    MaxPatternOrderTableEntriesExceeded = 6
    InternalPatternDisplayAndTimingConfigurationNotSupported = 7
    InternalPatternDisplayConfigurationNotSupported = 8
    ExternalPatternPeriodError = 9

class FlashErase(Enum):
    Complete = 0
    NotComplete = 1

class Application(Enum):
    BootApp = 0
    MainApp = 1

class LedState(Enum):
    LedOff = 0
    LedOn = 1

class PowerSupply(Enum):
    SupplyVoltageNormal = 0
    SupplyVoltageLow = 1

class ControllerConfiguration(Enum):
    Single = 0
    Dual = 1

class MasterOrSlaveOperation(Enum):
    Master = 0
    Slave = 1

class WatchdogTimeout(Enum):
    NoTimeout = 0
    Timeout = 1

class DmdDataSelection(Enum):
    DmdDeviceId = 0
    DmdFuseGroup0 = 1
    DmdFuseGroup1 = 2
    DmdFuseGroup2 = 3
    DmdFuseGroup3 = 4

class FlashDataTypeSelect(Enum):
    EntireFlash = 0
    EntireFlashNoOem = 2
    MainApp = 16
    TiApp = 32
    BatchFiles = 48
    Looks = 64
    Sequences = 80
    Cmt = 96
    Cca = 112
    Gluts = 128
    Splash = 144
    OemCal = 160
    OemScratchpadFull0 = 176
    OemScratchpadPartial0 = 177
    OemScratchpadFull1 = 178
    OemScratchpadPartial1 = 179
    OemScratchpadFull2 = 180
    OemScratchpadPartial2 = 181
    OemScratchpadFull3 = 181
    OemScratchpadPartial3 = 183
    EntireSensPatternData = 208
    EntireSensSeqData = 224

class DsiEnable(Enum):
    Enable = 0
    Disable = 1

class Summary:
    Command: str
    CommInterface: str
    Successful: bool

class ProtocolData:
    CommandDestination: int
    OpcodeLength: int
    BytesRead: int

class SplashScreenHeader:
     WidthInPixels: int                     # int
     HeightInPixels: int                    # int
     SizeInBytes: int                       # int
     PixelFormat: PixelFormats
     CompressionType: CompressionTypes
     ColorOrder: ColorOrders
     ChromaOrder: ChromaOrders
     ByteOrder: ByteOrders

class GridLines:
     Border: BorderEnable
     BackgroundColor: Color
     ForegroundColor: Color
     HorizontalForegroundLineWidth: int     # int
     HorizontalBackgroundLineWidth: int     # int
     VerticalForegroundLineWidth: int       # int
     VerticalBackgroundLineWidth: int       # int

class TestPatternSelect:
     PatternSelect: TestPattern
     Border: BorderEnable
     BackgroundColor: Color
     ForegroundColor: Color
     StartValue: int                        # int
     EndValue: int                          # int
     ForegroundLineWidth: int               # int
     BackgroundLineWidth: int               # int
     HorizontalSpacing: int                 # int
     VerticalSpacing: int                   # int
     HorizontalForegroundLineWidth: int     # int
     HorizontalBackgroundLineWidth: int     # int
     HorizontalCheckerCount: int            # int
     VerticalForegroundLineWidth: int       # int
     VerticalBackgroundLineWidth: int       # int
     VerticalCheckerCount: int              # int

class SequenceHeaderAttributes:
     LookRedDutyCycle: float
     LookGreenDutyCycle: float
     LookBlueDutyCycle: float
     LookMaxFrameTime: float
     LookMinFrameTime: float
     LookMaxSequenceVectors: int            # int
     SeqRedDutyCycle: float
     SeqGreenDutyCycle: float
     SeqBlueDutyCycle: float
     SeqMaxFrameTime: float
     SeqMinFrameTime: float
     SeqMaxSequenceVectors: int             # int

class ShortStatus:
     SystemInitialized: SystemInit
     CommunicationError: Error
     SystemError: Error
     FlashEraseComplete: FlashErase
     FlashError: Error
     SensingSequenceError: Error
     Application: Application

class SystemStatus:
     DmdDeviceError: Error
     DmdInterfaceError: Error
     DmdTrainingError: Error
     RedLedEnableState: LedState
     GreenLedEnableState: LedState
     BlueLedEnableState: LedState
     RedLedError: Error
     GreenLedError: Error
     BlueLedError: Error
     SequenceAbortError: Error
     SequenceError: Error
     DcPowerSupply: PowerSupply
     SensingError: SensingError
     ControllerConfiguration: ControllerConfiguration
     MasterOrSlaveOperation: MasterOrSlaveOperation
     ProductConfigurationError: Error
     WatchdogTimerTimeout: WatchdogTimeout

class CommunicationStatus:
     InvalidCommandError: Error
     InvalidCommandParameterValue: Error
     CommandProcessingError: Error
     FlashBatchFileError: Error
     ReadCommandError: Error
     InvalidNumberOfCommandParameters: Error
     BusTimeoutByDisplayError: Error
     AbortedOpCode: int                     # int

_readcommand = None
_writecommand = None

def DLPC342Xinit(readcommandcb, writecommandcb):
    global _readcommand
    global _writecommand
    _readcommand = readcommandcb
    _writecommand = writecommandcb

    global Summary
    Summary.CommInterface = "DLPC342X"

    global PortocolData
    ProtocolData.CommandDestination = 0
    ProtocolData.OpcodeLength = 0
    ProtocolData.BytesRead = 0

def WriteOperatingModeSelect(OperatingMode):
    "Selects the image operating mode for the projection module."
    global Summary
    Summary.Command = "Write Operating Mode Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',5))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',OperatingMode.value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadOperatingModeSelect():
    "Reads the state of the image operating mode for the projection module."
    global Summary
    Summary.Command = "Read Operating Mode Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',6))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        OperatingModeObj = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, OperatingMode(OperatingModeObj)

def WriteSplashScreenSelect(SplashScreenIndex):
    "Selects the index of a splash screen that is to be displayed. See also Write Splash Screen Execute."
    global Summary
    Summary.Command = "Write Splash Screen Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',13))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',SplashScreenIndex)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadSplashScreenSelect():
    "Returns the index of a splash screen that is to be displayed (or is being displayed)."
    global Summary
    Summary.Command = "Read Splash Screen Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',14))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        SplashScreenIndex = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, SplashScreenIndex

def WriteSplashScreenExecute():
    "Retrieves the select splash screen from flash for display on the projection module. See also Write Splash Screen Select."
    global Summary
    Summary.Command = "Write Splash Screen Execute"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',53))
        ProtocolData.OpcodeLength = 1;
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadSplashScreenHeader(SplashScreenIndex):
    "Read Splash screen header"
    global Summary
    Summary.Command = "Read Splash Screen Header"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',15))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',SplashScreenIndex)))
        readbytes = _readcommand(13, writebytes, ProtocolData)
        SplashScreenHeader.WidthInPixels = struct.unpack_from ('H', bytearray(readbytes), 0)[0]
        SplashScreenHeader.HeightInPixels = struct.unpack_from ('H', bytearray(readbytes), 2)[0]
        SplashScreenHeader.SizeInBytes = struct.unpack_from ('I', bytearray(readbytes), 4)[0]
        SplashScreenHeader.PixelFormat = struct.unpack_from ('B', bytearray(readbytes), 8)[0]
        SplashScreenHeader.CompressionType = struct.unpack_from ('B', bytearray(readbytes), 9)[0]
        SplashScreenHeader.ColorOrder = struct.unpack_from ('B', bytearray(readbytes), 10)[0]
        SplashScreenHeader.ChromaOrder = struct.unpack_from ('B', bytearray(readbytes), 11)[0]
        SplashScreenHeader.ByteOrder = struct.unpack_from ('B', bytearray(readbytes), 12)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, SplashScreenHeader

def WriteExternalVideoSourceFormatSelect(VideoFormat):
    "Specifies the active external video port and the source data type for the projection module."
    global Summary
    Summary.Command = "Write External Video Source Format Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',7))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',VideoFormat.value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadExternalVideoSourceFormatSelect():
    "Reads the state of the active external video port and the source data type for the projection module."
    global Summary
    Summary.Command = "Read External Video Source Format Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',8))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        VideoFormatObj = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, ExternalVideoFormat(VideoFormatObj)

def WriteVideoChromaProcessingSelect(ChromaInterpolationMethod,  ChromaChannelSwap,  CscCoefficientSet):
    "Specifies the characteristics of the selected YCbCr source and the type of chroma processing that will be used for the YCbCr source in the projection module."
    global Summary
    Summary.Command = "Write Video Chroma Processing Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',9))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(ChromaInterpolationMethod.value, 1, 4)
        value = setbits(ChromaChannelSwap.value, 1, 2)
        writebytes.extend(list(struct.pack('B',value)))
        packerinit()
        value = setbits(int(CscCoefficientSet), 2, 0)
        writebytes.extend(list(struct.pack('B',value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadVideoChromaProcessingSelect():
    "Reads the specified characteristics for the selected YCrCb source and the chroma processing used."
    global Summary
    Summary.Command = "Read Video Chroma Processing Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',10))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(2, writebytes, ProtocolData)
        readdata = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        packerinit(readdata)
        ChromaInterpolationMethodObj = getbits(1, 4);
        ChromaChannelSwapObj = getbits(1, 3);
        readdata = struct.unpack_from ('B', bytearray(readbytes), 1)[0]
        packerinit(readdata)
        CscCoefficientSet = getbits(2, 0);
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, ChromaInterpolationMethod(ChromaInterpolationMethodObj), ChromaChannelSwap(ChromaChannelSwapObj), CscCoefficientSet

def WriteInputImageSize(PixelsPerLine,  LinesPerFrame):
    "Specifies the active data size of the external input image to the projection module."
    global Summary
    Summary.Command = "Write Input Image Size"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',46))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('H',PixelsPerLine)))
        writebytes.extend(list(struct.pack('H',LinesPerFrame)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadInputImageSize():
    "Reads the specified data size of the external input image to the projection module."
    global Summary
    Summary.Command = "Read Input Image Size"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',47))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(4, writebytes, ProtocolData)
        PixelsPerLine = struct.unpack_from ('H', bytearray(readbytes), 0)[0]
        LinesPerFrame = struct.unpack_from ('H', bytearray(readbytes), 2)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, PixelsPerLine, LinesPerFrame

def WriteImageCrop(CaptureStartPixel,  CaptureStartLine,  PixelsPerLine,  LinesPerFrame):
    "Specifies which portion of the input image is to be displayed the projection module."
    global Summary
    Summary.Command = "Write Image Crop"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',16))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('H',CaptureStartPixel)))
        writebytes.extend(list(struct.pack('H',CaptureStartLine)))
        writebytes.extend(list(struct.pack('H',PixelsPerLine)))
        writebytes.extend(list(struct.pack('H',LinesPerFrame)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadImageCrop():
    "Reads the state of the image crop settings from the projection module."
    global Summary
    Summary.Command = "Read Image Crop"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',17))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(8, writebytes, ProtocolData)
        CaptureStartPixel = struct.unpack_from ('H', bytearray(readbytes), 0)[0]
        CaptureStartLine = struct.unpack_from ('H', bytearray(readbytes), 2)[0]
        PixelsPerLine = struct.unpack_from ('H', bytearray(readbytes), 4)[0]
        LinesPerFrame = struct.unpack_from ('H', bytearray(readbytes), 6)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, CaptureStartPixel, CaptureStartLine, PixelsPerLine, LinesPerFrame

def WriteDisplayImageOrientation(LongAxisImageFlip,  ShortAxisImageFlip):
    "Specifies the image orientation of the displayed image for the projection module."
    global Summary
    Summary.Command = "Write Display Image Orientation"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',20))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(LongAxisImageFlip.value, 1, 1)
        value = setbits(ShortAxisImageFlip.value, 1, 2)
        writebytes.extend(list(struct.pack('B',value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadDisplayImageOrientation():
    "Reads the state of the displayed image orientation function for the projection module."
    global Summary
    Summary.Command = "Read Display Image Orientation"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',21))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        readdata = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        packerinit(readdata)
        LongAxisImageFlipObj = getbits(1, 1);
        ShortAxisImageFlipObj = getbits(1, 2);
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, ImageFlip(LongAxisImageFlipObj), ImageFlip(ShortAxisImageFlipObj)

def WriteDisplayImageCurtain(Enable,  Color):
    "Controls the display image curtain for the projection module. An image curtain fills the entire display with the selected color regardless of selected operating mode (except for Internal Pattern Streaming)."
    global Summary
    Summary.Command = "Write Display Image Curtain"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',22))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(Enable.value, 1, 0)
        value = setbits(Color.value, 3, 1)
        writebytes.extend(list(struct.pack('B',value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadDisplayImageCurtain():
    "Reads the state of the image curtain control function for the projection module."
    global Summary
    Summary.Command = "Read Display Image Curtain"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',23))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        readdata = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        packerinit(readdata)
        EnableObj = getbits(1, 0);
        ColorObj = getbits(3, 1);
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, ImageCurtainEnable(EnableObj), Color(ColorObj)

def WriteImageFreeze(Enable):
    "Enables or disables the image freeze function for the projection module. If enabled, this preserves the current image data."
    global Summary
    Summary.Command = "Write Image Freeze"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',26))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',Enable)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadImageFreeze():
    "Reads the state of the image freeze function for the projection module."
    global Summary
    Summary.Command = "Read Image Freeze"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',27))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        Enable = struct.unpack_from ('?', bytearray(readbytes), 0)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, Enable

def WriteSolidField(Border,  ForegroundColor):
    "Writes a solid field pattern as internal test pattern for display."
    global Summary
    Summary.Command = "Write Solid Field"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',11))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(0, 4, 0)
        value = setbits(Border.value, 1, 7)
        writebytes.extend(list(struct.pack('B',value)))
        packerinit()
        value = setbits(ForegroundColor.value, 3, 4)
        writebytes.extend(list(struct.pack('B',value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteHorizontalRamp(Border,  ForegroundColor,  StartValue,  EndValue):
    "Writes a horizontal ramp pattern as internal test pattern for display."
    global Summary
    Summary.Command = "Write Horizontal Ramp"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',11))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(1, 4, 0)
        value = setbits(Border.value, 1, 7)
        writebytes.extend(list(struct.pack('B',value)))
        packerinit()
        value = setbits(ForegroundColor.value, 3, 4)
        writebytes.extend(list(struct.pack('B',value)))
        writebytes.extend(list(struct.pack('B',StartValue)))
        writebytes.extend(list(struct.pack('B',EndValue)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteVerticalRamp(Border,  ForegroundColor,  StartValue,  EndValue):
    "Writes a vertical ramp pattern as internal test pattern for display."
    global Summary
    Summary.Command = "Write Vertical Ramp"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',11))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(2, 4, 0)
        value = setbits(Border.value, 1, 7)
        writebytes.extend(list(struct.pack('B',value)))
        packerinit()
        value = setbits(ForegroundColor.value, 3, 4)
        writebytes.extend(list(struct.pack('B',value)))
        writebytes.extend(list(struct.pack('B',StartValue)))
        writebytes.extend(list(struct.pack('B',EndValue)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteHorizontalLines(Border,  BackgroundColor,  ForegroundColor,  ForegroundLineWidth,  BackgroundLineWidth):
    "Writes a horizontal lines pattern as internal test pattern for display."
    global Summary
    Summary.Command = "Write Horizontal Lines"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',11))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(3, 4, 0)
        value = setbits(Border.value, 1, 7)
        writebytes.extend(list(struct.pack('B',value)))
        packerinit()
        value = setbits(BackgroundColor.value, 3, 0)
        value = setbits(ForegroundColor.value, 3, 4)
        writebytes.extend(list(struct.pack('B',value)))
        writebytes.extend(list(struct.pack('B',ForegroundLineWidth)))
        writebytes.extend(list(struct.pack('B',BackgroundLineWidth)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteDiagonalLines(Border,  BackgroundColor,  ForegroundColor,  HorizontalSpacing,  VerticalSpacing):
    "Writes a diagonal lines pattern as internal test pattern for display."
    global Summary
    Summary.Command = "Write Diagonal Lines"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',11))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(4, 4, 0)
        value = setbits(Border.value, 1, 7)
        writebytes.extend(list(struct.pack('B',value)))
        packerinit()
        value = setbits(BackgroundColor.value, 3, 0)
        value = setbits(ForegroundColor.value, 3, 4)
        writebytes.extend(list(struct.pack('B',value)))
        writebytes.extend(list(struct.pack('B',HorizontalSpacing.value)))
        writebytes.extend(list(struct.pack('B',VerticalSpacing.value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteVerticalLines(Border,  BackgroundColor,  ForegroundColor,  ForegroundLineWidth,  BackgroundLineWidth):
    "Writes a vertical lines pattern as internal test pattern for display."
    global Summary
    Summary.Command = "Write Vertical Lines"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',11))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(5, 4, 0)
        value = setbits(Border.value, 1, 7)
        writebytes.extend(list(struct.pack('B',value)))
        packerinit()
        value = setbits(BackgroundColor.value, 3, 0)
        value = setbits(ForegroundColor.value, 3, 4)
        writebytes.extend(list(struct.pack('B',value)))
        writebytes.extend(list(struct.pack('B',ForegroundLineWidth)))
        writebytes.extend(list(struct.pack('B',BackgroundLineWidth)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteGridLines(GridLines):
    "Writes a grid lines pattern as internal test pattern for display."
    global Summary
    Summary.Command = "Write Grid Lines"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',11))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(6, 4, 0)
        value = setbits(GridLines.Border.value, 1, 7)
        writebytes.extend(list(struct.pack('B',value)))
        packerinit()
        value = setbits(GridLines.BackgroundColor.value, 3, 0)
        value = setbits(GridLines.ForegroundColor.value, 3, 4)
        writebytes.extend(list(struct.pack('B',value)))
        writebytes.extend(list(struct.pack('B',GridLines.HorizontalForegroundLineWidth)))
        writebytes.extend(list(struct.pack('B',GridLines.HorizontalBackgroundLineWidth)))
        writebytes.extend(list(struct.pack('B',GridLines.VerticalForegroundLineWidth)))
        writebytes.extend(list(struct.pack('B',GridLines.VerticalBackgroundLineWidth)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteCheckerboard(Border,  BackgroundColor,  ForegroundColor,  HorizontalCheckerCount,  VerticalCheckerCount):
    "Writes a checkerboard pattern as internal test pattern for display. 0: Disable, 1: Enable"
    global Summary
    Summary.Command = "Write Checkerboard"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',11))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(7, 4, 0)
        value = setbits(Border.value, 1, 7)
        writebytes.extend(list(struct.pack('B',value)))
        packerinit()
        value = setbits(BackgroundColor.value, 3, 0)
        value = setbits(ForegroundColor.value, 3, 4)
        writebytes.extend(list(struct.pack('B',value)))
        writebytes.extend(list(struct.pack('H',HorizontalCheckerCount)))
        writebytes.extend(list(struct.pack('H',VerticalCheckerCount)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteColorbars(Border):
    "Writes a colorbars pattern as internal test pattern for display."
    global Summary
    Summary.Command = "Write Colorbars"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',11))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(8, 4, 0)
        value = setbits(Border.value, 1, 7)
        writebytes.extend(list(struct.pack('B',value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadTestPatternSelect():
    "Reads back the host-specified parameters for an internal test pattern."
    global Summary
    Summary.Command = "Read Test Pattern Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',12))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(6, writebytes, ProtocolData)
        readdata = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        packerinit(readdata)
        TestPatternSelect.PatternSelect = getbits(4, 0);
        TestPatternSelect.Border = getbits(1, 7);
        readdata = struct.unpack_from ('B', bytearray(readbytes), 1)[0]
        packerinit(readdata)
        TestPatternSelect.BackgroundColor = getbits(4, 0);
        TestPatternSelect.ForegroundColor = getbits(4, 4);
        readdata = struct.unpack_from ('H', bytearray(readbytes), 2)[0]
        packerinit(readdata)
        TestPatternSelect.StartValue = getbits(8, 0);
        TestPatternSelect.EndValue = getbits(8, 8);
        TestPatternSelect.ForegroundLineWidth = getbits(8, 0);
        TestPatternSelect.BackgroundLineWidth = getbits(8, 8);
        TestPatternSelect.HorizontalSpacing = getbits(8, 0);
        TestPatternSelect.VerticalSpacing = getbits(8, 8);
        TestPatternSelect.HorizontalForegroundLineWidth = getbits(8, 0);
        TestPatternSelect.HorizontalBackgroundLineWidth = getbits(8, 8);
        TestPatternSelect.HorizontalCheckerCount = getbits(11, 0);
        readdata = struct.unpack_from ('H', bytearray(readbytes), 4)[0]
        packerinit(readdata)
        TestPatternSelect.VerticalForegroundLineWidth = getbits(8, 0);
        TestPatternSelect.VerticalBackgroundLineWidth = getbits(8, 8);
        TestPatternSelect.VerticalCheckerCount = getbits(11, 0);
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, TestPatternSelect

def WriteKeystoneProjectionPitchAngle(PitchAngle):
    "Specifies the keystone projection pitch angle for the projection module."
    global Summary
    Summary.Command = "Write Keystone Projection Pitch Angle"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',187))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('H',int(convertfloattofixed(PitchAngle,256)))))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadKeystoneProjectionPitchAngle():
    "Reads the specified keystone projection pitch angle for the projection module."
    global Summary
    Summary.Command = "Read Keystone Projection Pitch Angle"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',188))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(2, writebytes, ProtocolData)
        PitchAngle = convertfixedtofloat(struct.unpack_from ('H', bytearray(readbytes), 0)[0], 256)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, PitchAngle

def WriteKeystoneCorrectionControl(KeystoneCorrectionEnable,  OpticalThrowRatio,  OpticalDmdOffset):
    "Controls the keystone correction image processing functionality for the projection module."
    global Summary
    Summary.Command = "Write Keystone Correction Control"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',136))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',KeystoneCorrectionEnable)))
        writebytes.extend(list(struct.pack('H',int(convertfloattofixed(OpticalThrowRatio,255)))))
        writebytes.extend(list(struct.pack('H',int(convertfloattofixed(OpticalDmdOffset,255)))))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadKeystoneCorrectionControl():
    "Reads the state of the keystone correction image processing within the projection module."
    global Summary
    Summary.Command = "Read Keystone Correction Control"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',137))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(5, writebytes, ProtocolData)
        KeystoneCorrectionEnable = struct.unpack_from ('?', bytearray(readbytes), 0)[0]
        OpticalThrowRatio = convertfixedtofloat(struct.unpack_from ('H', bytearray(readbytes), 1)[0], 255)
        OpticalDmdOffset = convertfixedtofloat(struct.unpack_from ('H', bytearray(readbytes), 3)[0], 255)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, KeystoneCorrectionEnable, OpticalThrowRatio, OpticalDmdOffset

def WriteExecuteFlashBatchFile(BatchFileNumber):
    "Executes a batch file stored in the flash image."
    global Summary
    Summary.Command = "Write Execute Flash Batch File"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',45))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',BatchFileNumber)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteLedOutputControlMethod(LedControlMethod):
    "Specifies the method for controlling the LED outputs for the projection module."
    global Summary
    Summary.Command = "Write Led Output Control Method"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',80))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',LedControlMethod.value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadLedOutputControlMethod():
    "Reads the state of the LED output control method for the projection module."
    global Summary
    Summary.Command = "Read Led Output Control Method"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',81))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        LedControlMethodObj = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, LedControlMethod(LedControlMethodObj)

def WriteRgbLedEnable(RedLedEnable,  GreenLedEnable,  BlueLedEnable):
    "Enables the LEDs for the projection module."
    global Summary
    Summary.Command = "Write Rgb Led Enable"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',82))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(int(RedLedEnable), 1, 0)
        value = setbits(int(GreenLedEnable), 1, 1)
        value = setbits(int(BlueLedEnable), 1, 2)
        writebytes.extend(list(struct.pack('B',value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadRgbLedEnable():
    "Reads the state of the LED enables for the projection module."
    global Summary
    Summary.Command = "Read Rgb Led Enable"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',83))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        readdata = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        packerinit(readdata)
        RedLedEnable = getbits(1, 0);
        GreenLedEnable = getbits(1, 1);
        BlueLedEnable = getbits(1, 2);
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, RedLedEnable, GreenLedEnable, BlueLedEnable

def WriteRgbLedCurrent(RedLedCurrent,  GreenLedCurrent,  BlueLedCurrent):
    "Sets the IDAC register value of the PMIC for the red, green, and blue LEDs. This value directly controls the LED current."
    global Summary
    Summary.Command = "Write Rgb Led Current"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',84))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('H',RedLedCurrent)))
        writebytes.extend(list(struct.pack('H',GreenLedCurrent)))
        writebytes.extend(list(struct.pack('H',BlueLedCurrent)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadRgbLedCurrent():
    "Reads the state of the current for the red, green, and blue LEDs. This value directly controls the LED current."
    global Summary
    Summary.Command = "Read Rgb Led Current"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',85))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(6, writebytes, ProtocolData)
        RedLedCurrent = struct.unpack_from ('H', bytearray(readbytes), 0)[0]
        GreenLedCurrent = struct.unpack_from ('H', bytearray(readbytes), 2)[0]
        BlueLedCurrent = struct.unpack_from ('H', bytearray(readbytes), 4)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, RedLedCurrent, GreenLedCurrent, BlueLedCurrent

def ReadCaicLedMaxAvailablePower():
    "Reads the specified maximum LED power (Watts) allowed for the projection module."
    global Summary
    Summary.Command = "Read Caic Led Max Available Power"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',87))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(2, writebytes, ProtocolData)
        MaxLedPower = convertfixedtofloat(struct.unpack_from ('H', bytearray(readbytes), 0)[0], 100)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, MaxLedPower

def WriteRgbLedMaxCurrent(MaxRedLedCurrent,  MaxGreenLedCurrent,  MaxBlueLedCurrent):
    "Specifies the maximum LED current allowed for each LED in the projection module."
    global Summary
    Summary.Command = "Write Rgb Led Max Current"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',92))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('H',MaxRedLedCurrent)))
        writebytes.extend(list(struct.pack('H',MaxGreenLedCurrent)))
        writebytes.extend(list(struct.pack('H',MaxBlueLedCurrent)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadRgbLedMaxCurrent():
    "Reads the specified maximum LED current allowed for each LED in the projection module."
    global Summary
    Summary.Command = "Read Rgb Led Max Current"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',93))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(6, writebytes, ProtocolData)
        MaxRedLedCurrent = struct.unpack_from ('H', bytearray(readbytes), 0)[0]
        MaxGreenLedCurrent = struct.unpack_from ('H', bytearray(readbytes), 2)[0]
        MaxBlueLedCurrent = struct.unpack_from ('H', bytearray(readbytes), 4)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, MaxRedLedCurrent, MaxGreenLedCurrent, MaxBlueLedCurrent

def ReadCaicRgbLedCurrent():
    "Reads the state of the current for the red, green, and blue LEDs of the projection module."
    global Summary
    Summary.Command = "Read Caic Rgb Led Current"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',95))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(6, writebytes, ProtocolData)
        RedLedCurrent = struct.unpack_from ('H', bytearray(readbytes), 0)[0]
        GreenLedCurrent = struct.unpack_from ('H', bytearray(readbytes), 2)[0]
        BlueLedCurrent = struct.unpack_from ('H', bytearray(readbytes), 4)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, RedLedCurrent, GreenLedCurrent, BlueLedCurrent

def WriteLookSelect(LookNumber):
    "Specifies the Look for the image on the projection module. A Look typically specifies a target white point."
    global Summary
    Summary.Command = "Write Look Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',34))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',LookNumber)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadLookSelect():
    "Reads the state of the Look select command for the projection module."
    global Summary
    Summary.Command = "Read Look Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',35))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(6, writebytes, ProtocolData)
        LookNumber = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        SequenceIndex = struct.unpack_from ('B', bytearray(readbytes), 1)[0]
        SequenceFrameTime = convertfixedtofloat(struct.unpack_from ('I', bytearray(readbytes), 2)[0], 15)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, LookNumber, SequenceIndex, SequenceFrameTime

def ReadSequenceHeaderAttributes():
    "Reads Look and Sequence header information for the active Look and Sequence of the projection module."
    global Summary
    Summary.Command = "Read Sequence Header Attributes"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',38))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(30, writebytes, ProtocolData)
        SequenceHeaderAttributes.LookRedDutyCycle = convertfixedtofloat(struct.unpack_from ('H', bytearray(readbytes), 0)[0], 255)
        SequenceHeaderAttributes.LookGreenDutyCycle = convertfixedtofloat(struct.unpack_from ('H', bytearray(readbytes), 2)[0], 255)
        SequenceHeaderAttributes.LookBlueDutyCycle = convertfixedtofloat(struct.unpack_from ('H', bytearray(readbytes), 4)[0], 255)
        SequenceHeaderAttributes.LookMaxFrameTime = convertfixedtofloat(struct.unpack_from ('I', bytearray(readbytes), 6)[0], 15)
        SequenceHeaderAttributes.LookMinFrameTime = convertfixedtofloat(struct.unpack_from ('I', bytearray(readbytes), 10)[0], 15)
        SequenceHeaderAttributes.LookMaxSequenceVectors = struct.unpack_from ('B', bytearray(readbytes), 14)[0]
        SequenceHeaderAttributes.SeqRedDutyCycle = convertfixedtofloat(struct.unpack_from ('H', bytearray(readbytes), 15)[0], 255)
        SequenceHeaderAttributes.SeqGreenDutyCycle = convertfixedtofloat(struct.unpack_from ('H', bytearray(readbytes), 17)[0], 255)
        SequenceHeaderAttributes.SeqBlueDutyCycle = convertfixedtofloat(struct.unpack_from ('H', bytearray(readbytes), 19)[0], 255)
        SequenceHeaderAttributes.SeqMaxFrameTime = convertfixedtofloat(struct.unpack_from ('I', bytearray(readbytes), 21)[0], 15)
        SequenceHeaderAttributes.SeqMinFrameTime = convertfixedtofloat(struct.unpack_from ('I', bytearray(readbytes), 25)[0], 15)
        SequenceHeaderAttributes.SeqMaxSequenceVectors = struct.unpack_from ('B', bytearray(readbytes), 29)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, SequenceHeaderAttributes

def WriteLocalAreaBrightnessBoostControl(LabbControl,  SharpnessStrength,  LabbStrengthSetting):
    "Controls the local area brightness boost image processing functionality for the projection module."
    global Summary
    Summary.Command = "Write Local Area Brightness Boost Control"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',128))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(LabbControl.value, 2, 0)
        value = setbits(int(SharpnessStrength), 4, 4)
        writebytes.extend(list(struct.pack('B',value)))
        writebytes.extend(list(struct.pack('B',LabbStrengthSetting)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadLocalAreaBrightnessBoostControl():
    "Reads the state of the local area brightness boost image processing functionality for the projection module."
    global Summary
    Summary.Command = "Read Local Area Brightness Boost Control"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',129))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(3, writebytes, ProtocolData)
        readdata = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        packerinit(readdata)
        LabbControlObj = getbits(2, 0);
        SharpnessStrength = getbits(4, 4);
        LabbStrengthSetting = struct.unpack_from ('B', bytearray(readbytes), 1)[0]
        LabbGainValue = struct.unpack_from ('B', bytearray(readbytes), 2)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, LabbControl(LabbControlObj), SharpnessStrength, LabbStrengthSetting, LabbGainValue

def WriteCaicImageProcessingControl(CaicGainDisplayScale,  CaicGainDisplayEnable,  CaicMaxLumensGain,  CaicClippingThreshold):
    "Controls the CAIC functionality for the projection module."
    global Summary
    Summary.Command = "Write Caic Image Processing Control"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',132))
        ProtocolData.OpcodeLength = 1;
        packerinit()
        value = setbits(CaicGainDisplayScale.value, 1, 6)
        value = setbits(int(CaicGainDisplayEnable), 1, 7)
        writebytes.extend(list(struct.pack('B',value)))
        writebytes.extend(list(struct.pack('B',int(convertfloattofixed(CaicMaxLumensGain,31)))))
        writebytes.extend(list(struct.pack('B',int(convertfloattofixed(CaicClippingThreshold,63)))))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadCaicImageProcessingControl():
    "Reads the state of the CAIC functionality within the projection module."
    global Summary
    Summary.Command = "Read Caic Image Processing Control"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',133))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(3, writebytes, ProtocolData)
        readdata = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        packerinit(readdata)
        CaicGainDisplayScaleObj = getbits(1, 6);
        CaicGainDisplayEnable = getbits(1, 7);
        CaicMaxLumensGain = convertfixedtofloat(struct.unpack_from ('B', bytearray(readbytes), 1)[0], 31)
        CaicClippingThreshold = convertfixedtofloat(struct.unpack_from ('B', bytearray(readbytes), 2)[0], 63)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, CaicGainDisplayScale(CaicGainDisplayScaleObj), CaicGainDisplayEnable, CaicMaxLumensGain, CaicClippingThreshold

def WriteColorCoordinateAdjustmentControl(CcaEnable):
    "Controls the Color Coordinate Adjustment (CCA) image processing functionality for the projection module."
    global Summary
    Summary.Command = "Write Color Coordinate Adjustment Control"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',134))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',CcaEnable)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadColorCoordinateAdjustmentControl():
    "Reads the state of the Color Coordinate Adjustment (CCA) image processing within the projection module."
    global Summary
    Summary.Command = "Read Color Coordinate Adjustment Control"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',135))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        CcaEnable = struct.unpack_from ('?', bytearray(readbytes), 0)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, CcaEnable

def ReadShortStatus():
    "Provides a brief system status for the projection module."
    global Summary
    Summary.Command = "Read Short Status"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',208))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        readdata = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        packerinit(readdata)
        ShortStatus.SystemInitialized = getbits(1, 0);
        ShortStatus.CommunicationError = getbits(1, 1);
        ShortStatus.SystemError = getbits(1, 3);
        ShortStatus.FlashEraseComplete = getbits(1, 4);
        ShortStatus.FlashError = getbits(1, 5);
        ShortStatus.SensingSequenceError = getbits(1, 6);
        ShortStatus.Application = getbits(1, 7);
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, ShortStatus

def ReadSystemStatus():
    "Reads system status information for the projection module."
    global Summary
    Summary.Command = "Read System Status"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',209))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(4, writebytes, ProtocolData)
        readdata = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        packerinit(readdata)
        SystemStatus.DmdDeviceError = getbits(1, 0);
        SystemStatus.DmdInterfaceError = getbits(1, 1);
        SystemStatus.DmdTrainingError = getbits(1, 2);
        readdata = struct.unpack_from ('B', bytearray(readbytes), 1)[0]
        packerinit(readdata)
        SystemStatus.RedLedEnableState = getbits(1, 0);
        SystemStatus.GreenLedEnableState = getbits(1, 1);
        SystemStatus.BlueLedEnableState = getbits(1, 2);
        SystemStatus.RedLedError = getbits(1, 3);
        SystemStatus.GreenLedError = getbits(1, 4);
        SystemStatus.BlueLedError = getbits(1, 5);
        readdata = struct.unpack_from ('B', bytearray(readbytes), 2)[0]
        packerinit(readdata)
        SystemStatus.SequenceAbortError = getbits(1, 0);
        SystemStatus.SequenceError = getbits(1, 1);
        SystemStatus.DcPowerSupply = getbits(1, 2);
        SystemStatus.SensingError = getbits(5, 3);
        readdata = struct.unpack_from ('B', bytearray(readbytes), 3)[0]
        packerinit(readdata)
        SystemStatus.ControllerConfiguration = getbits(1, 2);
        SystemStatus.MasterOrSlaveOperation = getbits(1, 3);
        SystemStatus.ProductConfigurationError = getbits(1, 4);
        SystemStatus.WatchdogTimerTimeout = getbits(1, 5);
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, SystemStatus

def ReadCommunicationStatus():
    "Reads I2C communication status information for the projection module."
    global Summary
    Summary.Command = "Read Communication Status"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',211))
        ProtocolData.OpcodeLength = 1;
        valueArray = [0x02]
        writebytes.extend(valueArray)
        readbytes = _readcommand(2, writebytes, ProtocolData)
        readdata = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        packerinit(readdata)
        CommunicationStatus.InvalidCommandError = getbits(1, 0);
        CommunicationStatus.InvalidCommandParameterValue = getbits(1, 1);
        CommunicationStatus.CommandProcessingError = getbits(1, 2);
        CommunicationStatus.FlashBatchFileError = getbits(1, 3);
        CommunicationStatus.ReadCommandError = getbits(1, 4);
        CommunicationStatus.InvalidNumberOfCommandParameters = getbits(1, 5);
        CommunicationStatus.BusTimeoutByDisplayError = getbits(1, 6);
        CommunicationStatus.AbortedOpCode = struct.unpack_from ('B', bytearray(readbytes), 1)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, CommunicationStatus

def ReadControllerDeviceId():
    "Reads the controller device ID for the projection module."
    global Summary
    Summary.Command = "Read Controller Device Id"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',212))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        DeviceIdObj = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, ControllerDeviceId(DeviceIdObj)

def ReadDmdDeviceId(DmdDataSelection):
    "Reads the DMD device ID or DMD fuse data for the projection module."
    global Summary
    Summary.Command = "Read Dmd Device Id"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',213))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',DmdDataSelection.value)))
        readbytes = _readcommand(4, writebytes, ProtocolData)
        DeviceId = struct.unpack_from ('I', bytearray(readbytes), 0)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, DeviceId

def ReadFirmwareBuildVersion():
    "Reads the controller firmware version for the projection module."
    global Summary
    Summary.Command = "Read Firmware Build Version"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',217))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(4, writebytes, ProtocolData)
        PatchVersion = struct.unpack_from ('H', bytearray(readbytes), 0)[0]
        MinorVersion = struct.unpack_from ('B', bytearray(readbytes), 2)[0]
        MajorVersion = struct.unpack_from ('B', bytearray(readbytes), 3)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, PatchVersion, MinorVersion, MajorVersion

def ReadSystemTemperature():
    "Reads the System Temperature."
    global Summary
    Summary.Command = "Read System Temperature"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',214))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(2, writebytes, ProtocolData)
        Temperature = convertfixedtofloat(struct.unpack_from ('H', bytearray(readbytes), 0)[0], 10)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, Temperature

def ReadFlashUpdatePrecheck(FlashUpdatePackageSize):
    "Verifies that a pending flash update (write) is appropriate for the specified block of the projection module flash. Must have called Write Flash Data Type Select prior."
    global Summary
    Summary.Command = "Read Flash Update Precheck"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',221))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('I',FlashUpdatePackageSize)))
        readbytes = _readcommand(1, writebytes, ProtocolData)
        readdata = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
        packerinit(readdata)
        PackageSizeStatusObj = getbits(1, 0);
        PacakgeConfigurationCollapsedObj = getbits(1, 1);
        PacakgeConfigurationIdentifierObj = getbits(1, 2);
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, Error(PackageSizeStatusObj), Error(PacakgeConfigurationCollapsedObj), Error(PacakgeConfigurationIdentifierObj)

def WriteFlashDataTypeSelect(FlashSelect):
    "Selects the data block that will be written/read from the flash."
    global Summary
    Summary.Command = "Write Flash Data Type Select"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',222))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',FlashSelect.value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteFlashDataLength(FlashDataLength):
    "Specifies the length in bytes of data that will be written/read from the flash."
    global Summary
    Summary.Command = "Write Flash Data Length"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',223))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('H',FlashDataLength)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteFlashErase():
    "Erases the selected flash data."
    global Summary
    Summary.Command = "Write Flash Erase"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',224))
        ProtocolData.OpcodeLength = 1;
        valueArray = [0xAA, 0xBB, 0xCC, 0xDD]
        writebytes.extend(valueArray)
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def WriteFlashStart(Data):
    "Writes data to the flash."
    global Summary
    Summary.Command = "Write Flash Start"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',225))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(Data))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadFlashStart(Length):
    "Reads data from the flash."
    global Summary
    Summary.Command = "Read Flash Start"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',227))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(Length, writebytes, ProtocolData)
        Data = bytearray(readbytes)[0, 1]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, Data

def WriteFlashContinue(Data):
    "Writes data to the flash."
    global Summary
    Summary.Command = "Write Flash Continue"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',226))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(Data))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadFlashContinue(Length):
    "Reads data from the flash."
    global Summary
    Summary.Command = "Read Flash Continue"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',228))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(Length, writebytes, ProtocolData)
        Data = bytearray(readbytes)[0, 1]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, Data

def WriteDsiPortEnable(Enable):
    "Enables the DSI port for the projection module."
    global Summary
    Summary.Command = "Write Dsi Port Enable"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',215))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',Enable.value)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadDsiPortEnable():
    "Returns the state of the DSI port for the projection module."
    global Summary
    Summary.Command = "Read Dsi Port Enable"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',216))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        EnableObj = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, DsiEnable(EnableObj)

def WriteDsiHsClockInput(ClockSpeed):
    "Sets the input DSI high speed clock frequency in MHz."
    global Summary
    Summary.Command = "Write Dsi Hs Clock Input"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',189))
        ProtocolData.OpcodeLength = 1;
        writebytes.extend(list(struct.pack('B',ClockSpeed)))
        _writecommand(writebytes, ProtocolData)
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful == False
    finally:
        return Summary

def ReadDsiHsClockInput():
    "Gets the expected input DSI high speed clock frequency in MHz."
    global Summary
    Summary.Command = "Read Dsi Hs Clock Input"
    Summary.Successful = True
    global ProtocolData
    ProtocolData.CommandDestination = 0;
    try:
        writebytes=list(struct.pack('B',190))
        ProtocolData.OpcodeLength = 1;
        readbytes = _readcommand(1, writebytes, ProtocolData)
        ClockSpeed = struct.unpack_from ('B', bytearray(readbytes), 0)[0]
    except ValueError as ve:
        print("Exception Occurred ", ve)
        Summary.Successful = False
    finally:
        return Summary, ClockSpeed

