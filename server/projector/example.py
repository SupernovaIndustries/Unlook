#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Standalone example showing how to use the DLPC342X I2C controller.
This demonstrates generating various test patterns on the projector.
"""

import time
import logging
import sys
import os
import argparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DLPC342XExample")

# Import the projector module - handles both cases where example is in same dir as library
# or when it's used from the server directory structure
try:
    # When used from server directory
    from dlpc342x_i2c import DLPC342XController, OperatingMode, Color, BorderEnable, DiagonalLineSpacing
except ImportError:
    # When example is in same directory as library files
    from dlpc342x_i2c import DLPC342XController, OperatingMode, Color, BorderEnable, DiagonalLineSpacing


def main():
    """Example of using the DLPC342X I2C controller."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='DLPC342X Test Pattern Generator')
    parser.add_argument('--bus', type=int, default=3,
                        help='I2C bus number (default: 1)')
    parser.add_argument('--address', type=int, default=0x1b,
                        help='I2C device address in hex (default: 0x36)')
    parser.add_argument('--pattern', type=str, default='cycle',
                        choices=['cycle', 'horizontal', 'vertical', 'diagonal', 'grid', 'checker', 'colorbars',
                                 'solid'],
                        help='Pattern to display (default: cycle through all)')
    args = parser.parse_args()

    # Initialize the controller
    logger.info(f"Initializing DLPC342X controller on bus {args.bus}, address 0x{args.address:02X}")
    controller = DLPC342XController(bus=args.bus, address=args.address)

    try:
        # Set the projector to test pattern mode
        logger.info("Setting projector to test pattern mode...")
        controller.set_operating_mode(OperatingMode.TestPatternGenerator)
        time.sleep(1)  # Give it time to change modes

        # Display the requested pattern or cycle through all
        if args.pattern == 'cycle':
            run_pattern_cycle(controller)
        elif args.pattern == 'horizontal':
            display_horizontal_lines(controller)
        elif args.pattern == 'vertical':
            display_vertical_lines(controller)
        elif args.pattern == 'diagonal':
            display_diagonal_lines(controller)
        elif args.pattern == 'grid':
            display_grid(controller)
        elif args.pattern == 'checker':
            display_checkerboard(controller)
        elif args.pattern == 'colorbars':
            display_colorbars(controller)
        elif args.pattern == 'solid':
            display_solid_field(controller)

        # Set back to external video mode when done
        logger.info("Setting projector back to external video mode...")
        controller.set_operating_mode(OperatingMode.ExternalVideoPort)

    except KeyboardInterrupt:
        logger.info("Operation interrupted by user")
        # Set back to external video mode
        controller.set_operating_mode(OperatingMode.ExternalVideoPort)
    except Exception as e:
        logger.error(f"Error during operation: {e}")
    finally:
        # Clean up
        controller.close()
        logger.info("Controller closed")


def run_pattern_cycle(controller):
    """Cycle through all available patterns."""
    logger.info("Cycling through all patterns...")

    # Horizontal lines
    display_horizontal_lines(controller)

    # Vertical lines
    display_vertical_lines(controller)

    # Grid
    display_grid(controller)

    # Diagonal lines
    display_diagonal_lines(controller)

    # Checkerboard
    display_checkerboard(controller)

    # Solid field
    display_solid_field(controller)

    # Color bars
    display_colorbars(controller)


def display_horizontal_lines(controller):
    """Display horizontal lines pattern."""
    logger.info("Generating horizontal lines...")
    controller.generate_horizontal_lines(
        background_color=Color.Black,
        foreground_color=Color.White,
        foreground_line_width=10,  # Width of the lines
        background_line_width=20  # Width of spaces between lines
    )
    time.sleep(3)  # Display for 3 seconds


def display_vertical_lines(controller):
    """Display vertical lines pattern."""
    logger.info("Generating vertical lines...")
    controller.generate_vertical_lines(
        background_color=Color.Black,
        foreground_color=Color.White,
        foreground_line_width=10,  # Width of the lines
        background_line_width=20  # Width of spaces between lines
    )
    time.sleep(3)  # Display for 3 seconds


def display_diagonal_lines(controller):
    """Display diagonal lines pattern."""
    logger.info("Generating diagonal lines...")
    controller.generate_diagonal_lines(
        background_color=Color.Black,
        foreground_color=Color.White,
        horizontal_spacing=DiagonalLineSpacing.Dls15,
        vertical_spacing=DiagonalLineSpacing.Dls15
    )
    time.sleep(3)  # Display for 3 seconds


def display_grid(controller):
    """Display grid pattern."""
    logger.info("Generating grid...")
    controller.generate_grid(
        background_color=Color.Black,
        foreground_color=Color.White,
        horizontal_foreground_width=4,  # Width of horizontal lines
        horizontal_background_width=20,  # Width of spaces between horizontal lines
        vertical_foreground_width=4,  # Width of vertical lines
        vertical_background_width=20  # Width of spaces between vertical lines
    )
    time.sleep(3)  # Display for 3 seconds


def display_checkerboard(controller):
    """Display checkerboard pattern."""
    logger.info("Generating checkerboard...")
    controller.generate_checkerboard(
        background_color=Color.Black,
        foreground_color=Color.White,
        horizontal_count=8,  # Number of horizontal checkers
        vertical_count=6  # Number of vertical checkers
    )
    time.sleep(3)  # Display for 3 seconds


def display_solid_field(controller):
    """Display solid color field."""
    logger.info("Generating solid green field...")
    controller.generate_solid_field(Color.Green)
    time.sleep(3)  # Display for 3 seconds


def display_colorbars(controller):
    """Display color bars."""
    logger.info("Generating color bars...")
    controller.generate_colorbars()
    time.sleep(3)  # Display for 3 seconds


if __name__ == "__main__":
    main()