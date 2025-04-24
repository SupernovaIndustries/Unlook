"""
DLPC342X I2C Controller Library

This library provides an interface to control Texas Instruments DLPC342X
projectors via I2C from a Raspberry Pi.

It's designed for use in structured light applications and focuses on
pattern generation capabilities.
"""

from .dlpc342x_i2c import (
    DLPC342XController,
    OperatingMode,
    Color,
    BorderEnable,
    TestPattern,
    DiagonalLineSpacing,
    GridLines
)

__version__ = "1.0.0"
__author__ = "Claude AI for SupernovaIndustries"