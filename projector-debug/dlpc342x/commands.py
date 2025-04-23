#-------------------------------------
# Copyright (c) 2024 Texas Instruments
#-------------------------------------

# NOTE: This file is auto generated from a command definition file.
#       Please do not modify the file directly.                    
#
# Command Spec Version : 1.0

import sys
import clr

clr.AddReference('DLPComposer.Commands.DLPC342x')
from System import *
from DLPComposer.Commands.DLPC342x import * 

def WriteOperatingModeSelect(OperatingMode) :
    return Command.WriteOperatingModeSelect(OperatingMode)

def ReadOperatingModeSelect() :
    Summary, OperatingMode = \
        Command.ReadOperatingModeSelect()
    return Summary, OperatingMode

def WriteSplashScreenSelect(SplashScreenIndex) :
    return Command.WriteSplashScreenSelect(SplashScreenIndex)

def ReadSplashScreenSelect() :
    Summary, SplashScreenIndex = \
        Command.ReadSplashScreenSelect()
    return Summary, int(SplashScreenIndex)

def WriteSplashScreenExecute() :
    return Command.WriteSplashScreenExecute()

def ReadSplashScreenHeader(SplashScreenIndex) :
    Summary, SplashScreenHeader = \
        Command.ReadSplashScreenHeader(SplashScreenIndex)
    return Summary, SplashScreenHeader

def WriteExternalVideoSourceFormatSelect(VideoFormat) :
    return Command.WriteExternalVideoSourceFormatSelect(VideoFormat)

def ReadExternalVideoSourceFormatSelect() :
    Summary, VideoFormat = \
        Command.ReadExternalVideoSourceFormatSelect()
    return Summary, VideoFormat

def WriteVideoChromaProcessingSelect(ChromaInterpolationMethod, ChromaChannelSwap, CscCoefficientSet) :
    return Command.WriteVideoChromaProcessingSelect(ChromaInterpolationMethod, ChromaChannelSwap, CscCoefficientSet)

def ReadVideoChromaProcessingSelect() :
    Summary, ChromaInterpolationMethod, ChromaChannelSwap, CscCoefficientSet = \
        Command.ReadVideoChromaProcessingSelect()
    return Summary, ChromaInterpolationMethod, ChromaChannelSwap, int(CscCoefficientSet)

def WriteInputImageSize(PixelsPerLine, LinesPerFrame) :
    return Command.WriteInputImageSize(PixelsPerLine, LinesPerFrame)

def ReadInputImageSize() :
    Summary, PixelsPerLine, LinesPerFrame = \
        Command.ReadInputImageSize()
    return Summary, int(PixelsPerLine), int(LinesPerFrame)

def WriteImageCrop(CaptureStartPixel, CaptureStartLine, PixelsPerLine, LinesPerFrame) :
    return Command.WriteImageCrop(CaptureStartPixel, CaptureStartLine, PixelsPerLine, LinesPerFrame)

def ReadImageCrop() :
    Summary, CaptureStartPixel, CaptureStartLine, PixelsPerLine, LinesPerFrame = \
        Command.ReadImageCrop()
    return Summary, int(CaptureStartPixel), int(CaptureStartLine), int(PixelsPerLine), int(LinesPerFrame)

def WriteDisplayImageOrientation(LongAxisImageFlip, ShortAxisImageFlip) :
    return Command.WriteDisplayImageOrientation(LongAxisImageFlip, ShortAxisImageFlip)

def ReadDisplayImageOrientation() :
    Summary, LongAxisImageFlip, ShortAxisImageFlip = \
        Command.ReadDisplayImageOrientation()
    return Summary, LongAxisImageFlip, ShortAxisImageFlip

def WriteDisplayImageCurtain(Enable, Color) :
    return Command.WriteDisplayImageCurtain(Enable, Color)

def ReadDisplayImageCurtain() :
    Summary, Enable, Color = \
        Command.ReadDisplayImageCurtain()
    return Summary, Enable, Color

def WriteImageFreeze(Enable) :
    return Command.WriteImageFreeze(Enable)

def ReadImageFreeze() :
    Summary, Enable = \
        Command.ReadImageFreeze()
    return Summary, bool(Enable)

def WriteMirrorLock(MirrorLockOption) :
    return Command.WriteMirrorLock(MirrorLockOption)

def ReadMirrorLock() :
    Summary, MirrorLockOption = \
        Command.ReadMirrorLock()
    return Summary, MirrorLockOption

def WriteSolidField(Border, ForegroundColor) :
    return Command.WriteSolidField(Border, ForegroundColor)

def WriteHorizontalRamp(Border, ForegroundColor, StartValue, EndValue) :
    return Command.WriteHorizontalRamp(Border, ForegroundColor, StartValue, EndValue)

def WriteVerticalRamp(Border, ForegroundColor, StartValue, EndValue) :
    return Command.WriteVerticalRamp(Border, ForegroundColor, StartValue, EndValue)

def WriteHorizontalLines(Border, BackgroundColor, ForegroundColor, ForegroundLineWidth, BackgroundLineWidth) :
    return Command.WriteHorizontalLines(Border, BackgroundColor, ForegroundColor, ForegroundLineWidth, BackgroundLineWidth)

def WriteDiagonalLines(Border, BackgroundColor, ForegroundColor, HorizontalSpacing, VerticalSpacing) :
    return Command.WriteDiagonalLines(Border, BackgroundColor, ForegroundColor, HorizontalSpacing, VerticalSpacing)

def WriteVerticalLines(Border, BackgroundColor, ForegroundColor, ForegroundLineWidth, BackgroundLineWidth) :
    return Command.WriteVerticalLines(Border, BackgroundColor, ForegroundColor, ForegroundLineWidth, BackgroundLineWidth)

def WriteGridLines(GridLines) :
    return Command.WriteGridLines(GridLines)

def WriteCheckerboard(Border, BackgroundColor, ForegroundColor, HorizontalCheckerCount, VerticalCheckerCount) :
    return Command.WriteCheckerboard(Border, BackgroundColor, ForegroundColor, HorizontalCheckerCount, VerticalCheckerCount)

def WriteColorbars(Border) :
    return Command.WriteColorbars(Border)

def ReadTestPatternSelect() :
    Summary, TestPatternSelect = \
        Command.ReadTestPatternSelect()
    return Summary, TestPatternSelect

def WriteKeystoneProjectionPitchAngle(PitchAngle) :
    return Command.WriteKeystoneProjectionPitchAngle(PitchAngle)

def ReadKeystoneProjectionPitchAngle() :
    Summary, PitchAngle = \
        Command.ReadKeystoneProjectionPitchAngle()
    return Summary, float(PitchAngle)

def WriteKeystoneCorrectionControl(KeystoneCorrectionEnable, OpticalThrowRatio, OpticalDmdOffset) :
    return Command.WriteKeystoneCorrectionControl(KeystoneCorrectionEnable, OpticalThrowRatio, OpticalDmdOffset)

def ReadKeystoneCorrectionControl() :
    Summary, KeystoneCorrectionEnable, OpticalThrowRatio, OpticalDmdOffset = \
        Command.ReadKeystoneCorrectionControl()
    return Summary, bool(KeystoneCorrectionEnable), float(OpticalThrowRatio), float(OpticalDmdOffset)

def WriteExecuteFlashBatchFile(BatchFileNumber) :
    return Command.WriteExecuteFlashBatchFile(BatchFileNumber)

def WriteLedOutputControlMethod(LedControlMethod) :
    return Command.WriteLedOutputControlMethod(LedControlMethod)

def ReadLedOutputControlMethod() :
    Summary, LedControlMethod = \
        Command.ReadLedOutputControlMethod()
    return Summary, LedControlMethod

def WriteRgbLedEnable(RedLedEnable, GreenLedEnable, BlueLedEnable) :
    return Command.WriteRgbLedEnable(RedLedEnable, GreenLedEnable, BlueLedEnable)

def ReadRgbLedEnable() :
    Summary, RedLedEnable, GreenLedEnable, BlueLedEnable = \
        Command.ReadRgbLedEnable()
    return Summary, bool(RedLedEnable), bool(GreenLedEnable), bool(BlueLedEnable)

def WriteRgbLedCurrent(RedLedCurrent, GreenLedCurrent, BlueLedCurrent) :
    return Command.WriteRgbLedCurrent(RedLedCurrent, GreenLedCurrent, BlueLedCurrent)

def ReadRgbLedCurrent() :
    Summary, RedLedCurrent, GreenLedCurrent, BlueLedCurrent = \
        Command.ReadRgbLedCurrent()
    return Summary, int(RedLedCurrent), int(GreenLedCurrent), int(BlueLedCurrent)

def ReadCaicLedMaxAvailablePower() :
    Summary, MaxLedPower = \
        Command.ReadCaicLedMaxAvailablePower()
    return Summary, float(MaxLedPower)

def WriteRgbLedMaxCurrent(MaxRedLedCurrent, MaxGreenLedCurrent, MaxBlueLedCurrent) :
    return Command.WriteRgbLedMaxCurrent(MaxRedLedCurrent, MaxGreenLedCurrent, MaxBlueLedCurrent)

def ReadRgbLedMaxCurrent() :
    Summary, MaxRedLedCurrent, MaxGreenLedCurrent, MaxBlueLedCurrent = \
        Command.ReadRgbLedMaxCurrent()
    return Summary, int(MaxRedLedCurrent), int(MaxGreenLedCurrent), int(MaxBlueLedCurrent)

def ReadCaicRgbLedCurrent() :
    Summary, RedLedCurrent, GreenLedCurrent, BlueLedCurrent = \
        Command.ReadCaicRgbLedCurrent()
    return Summary, int(RedLedCurrent), int(GreenLedCurrent), int(BlueLedCurrent)

def WriteLookSelect(LookNumber) :
    return Command.WriteLookSelect(LookNumber)

def ReadLookSelect() :
    Summary, LookNumber, SequenceIndex, SequenceFrameTime = \
        Command.ReadLookSelect()
    return Summary, int(LookNumber), int(SequenceIndex), float(SequenceFrameTime)

def ReadSequenceHeaderAttributes() :
    Summary, SequenceHeaderAttributes = \
        Command.ReadSequenceHeaderAttributes()
    return Summary, SequenceHeaderAttributes

def WriteLocalAreaBrightnessBoostControl(LabbControl, SharpnessStrength, LabbStrengthSetting) :
    return Command.WriteLocalAreaBrightnessBoostControl(LabbControl, SharpnessStrength, LabbStrengthSetting)

def ReadLocalAreaBrightnessBoostControl() :
    Summary, LabbControl, SharpnessStrength, LabbStrengthSetting, LabbGainValue = \
        Command.ReadLocalAreaBrightnessBoostControl()
    return Summary, LabbControl, int(SharpnessStrength), int(LabbStrengthSetting), int(LabbGainValue)

def WriteCaicImageProcessingControl(CaicGainDisplayScale, CaicGainDisplayEnable, CaicMaxLumensGain, CaicClippingThreshold) :
    return Command.WriteCaicImageProcessingControl(CaicGainDisplayScale, CaicGainDisplayEnable, CaicMaxLumensGain, CaicClippingThreshold)

def ReadCaicImageProcessingControl() :
    Summary, CaicGainDisplayScale, CaicGainDisplayEnable, CaicMaxLumensGain, CaicClippingThreshold = \
        Command.ReadCaicImageProcessingControl()
    return Summary, CaicGainDisplayScale, bool(CaicGainDisplayEnable), float(CaicMaxLumensGain), float(CaicClippingThreshold)

def WriteColorCoordinateAdjustmentControl(CcaEnable) :
    return Command.WriteColorCoordinateAdjustmentControl(CcaEnable)

def ReadColorCoordinateAdjustmentControl() :
    Summary, CcaEnable = \
        Command.ReadColorCoordinateAdjustmentControl()
    return Summary, bool(CcaEnable)

def ReadShortStatus() :
    Summary, ShortStatus = \
        Command.ReadShortStatus()
    return Summary, ShortStatus

def ReadSystemStatus() :
    Summary, SystemStatus = \
        Command.ReadSystemStatus()
    return Summary, SystemStatus

def ReadCommunicationStatus() :
    Summary, CommunicationStatus = \
        Command.ReadCommunicationStatus()
    return Summary, CommunicationStatus

def ReadSystemSoftwareVersion() :
    Summary, PatchVersion, MinorVersion, MajorVersion = \
        Command.ReadSystemSoftwareVersion()
    return Summary, int(PatchVersion), int(MinorVersion), int(MajorVersion)

def ReadControllerDeviceId() :
    Summary, DeviceId = \
        Command.ReadControllerDeviceId()
    return Summary, DeviceId

def ReadDmdDeviceId(DmdDataSelection) :
    Summary, DeviceId = \
        Command.ReadDmdDeviceId(DmdDataSelection)
    return Summary, int(DeviceId)

def ReadFirmwareBuildVersion() :
    Summary, PatchVersion, MinorVersion, MajorVersion = \
        Command.ReadFirmwareBuildVersion()
    return Summary, int(PatchVersion), int(MinorVersion), int(MajorVersion)

def ReadSystemTemperature() :
    Summary, Temperature = \
        Command.ReadSystemTemperature()
    return Summary, float(Temperature)

def ReadFlashUpdatePrecheck(FlashUpdatePackageSize) :
    Summary, PackageSizeStatus, PacakgeConfigurationCollapsed, PacakgeConfigurationIdentifier = \
        Command.ReadFlashUpdatePrecheck(FlashUpdatePackageSize)
    return Summary, PackageSizeStatus, PacakgeConfigurationCollapsed, PacakgeConfigurationIdentifier

def WriteFlashDataTypeSelect(FlashSelect) :
    return Command.WriteFlashDataTypeSelect(FlashSelect)

def WriteFlashDataLength(FlashDataLength) :
    return Command.WriteFlashDataLength(FlashDataLength)

def WriteFlashErase() :
    return Command.WriteFlashErase()

def WriteFlashStart(Data) :
    Data = Array[Byte](Data)
    return Command.WriteFlashStart(Data)

def ReadFlashStart(Length) :
    Summary, Data = \
        Command.ReadFlashStart(Length)
    return Summary, bytearray(Data)

def WriteFlashContinue(Data) :
    Data = Array[Byte](Data)
    return Command.WriteFlashContinue(Data)

def ReadFlashContinue(Length) :
    Summary, Data = \
        Command.ReadFlashContinue(Length)
    return Summary, bytearray(Data)

def WriteInternalRegisterAddress(Address) :
    return Command.WriteInternalRegisterAddress(Address)

def WriteInternalRegister(Data) :
    return Command.WriteInternalRegister(Data)

def ReadInternalRegister() :
    Summary, Data = \
        Command.ReadInternalRegister()
    return Summary, int(Data)

def WritePadRegisterAddress(Address, DataLength, ReadWrite) :
    return Command.WritePadRegisterAddress(Address, DataLength, ReadWrite)

def WritePadRegister(Data) :
    Data = Array[Byte](Data)
    return Command.WritePadRegister(Data)

def ReadPadRegister(Length) :
    Summary, Data = \
        Command.ReadPadRegister(Length)
    return Summary, bytearray(Data)

def WriteDsiPortEnable(Enable) :
    return Command.WriteDsiPortEnable(Enable)

def ReadDsiPortEnable() :
    Summary, Enable = \
        Command.ReadDsiPortEnable()
    return Summary, Enable

def WriteDsiHsClockInput(ClockSpeed) :
    return Command.WriteDsiHsClockInput(ClockSpeed)

def ReadDsiHsClockInput() :
    Summary, ClockSpeed = \
        Command.ReadDsiHsClockInput()
    return Summary, int(ClockSpeed)

