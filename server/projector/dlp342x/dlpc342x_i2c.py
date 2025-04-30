import struct
import time
from enum import Enum
from smbus2 import SMBus
import logging
from . import packer

# Configure logging
logger = logging.getLogger(__name__)


# Enums for projector settings
class OperatingMode(Enum):
    ExternalVideoPort = 0
    TestPatternGenerator = 1
    SplashScreen = 2
    SensExternalPattern = 3
    SensInternalPattern = 4
    SensSplashPattern = 5
    Standby = 255


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


class BorderEnable(Enum):
    Disable = 0
    Enable = 1


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


class GridLines:
    """Class for grid lines configuration, equivalent to the one in original dlpc342x.py"""

    def __init__(self):
        self.Border = BorderEnable.Enable
        self.BackgroundColor = Color.Black
        self.ForegroundColor = Color.White
        self.HorizontalForegroundLineWidth = 4
        self.HorizontalBackgroundLineWidth = 20
        self.VerticalForegroundLineWidth = 4
        self.VerticalBackgroundLineWidth = 20


class DLPC342XController:
    """Controller for DLPC342X projector via I2C."""

    def __init__(self, bus=3, address=0x1b):
        """Initialize the controller.

        Args:
            bus: I2C bus number (usually 3 for Unlook)
            address: I2C device address (default 0x1b)
        """
        self.bus = SMBus(bus)
        self.address = address
        self.summary = {"Command": "", "CommInterface": "I2C", "Successful": True}
        logger.info(f"DLPC342X I2C controller initialized (bus={bus}, address=0x{address:02X})")

    def close(self):
        """Close the I2C bus."""
        self.bus.close()
        logger.info("I2C bus closed")

    def _write_command(self, command_bytes):
        """Write a command to the projector.

        Args:
            command_bytes: List of bytes to write

        Returns:
            True if successful, False otherwise
        """
        try:
            # The first byte is the command, the rest are parameters
            command = command_bytes[0]
            data = command_bytes[1:] if len(command_bytes) > 1 else []

            # Write to I2C
            self.bus.write_i2c_block_data(self.address, command, data)
            logger.debug(f"I2C write: cmd=0x{command:02X}, data={[hex(b) for b in data]}")
            return True
        except Exception as e:
            logger.error(f"I2C write error: {e}")
            return False

    def _read_command(self, command_byte, length):
        """Read data from the projector.

        Args:
            command_byte: Command byte to specify what to read
            length: Number of bytes to read

        Returns:
            List of read bytes
        """
        try:
            # First write the command to specify what to read
            self.bus.write_byte(self.address, command_byte)
            logger.debug(f"I2C read command: 0x{command_byte:02X}, length={length}")

            # Short delay to ensure device has processed the command
            time.sleep(0.01)

            # Read the response
            read_data = []
            for _ in range(length):
                read_data.append(self.bus.read_byte(self.address))

            logger.debug(f"I2C read response: {[hex(b) for b in read_data]}")
            return read_data
        except Exception as e:
            logger.error(f"I2C read error: {e}")
            return [0] * length

    def set_operating_mode(self, mode):
        """Set the operating mode of the projector.

        Args:
            mode: Operating mode (from OperatingMode enum)

        Returns:
            True if successful, False otherwise
        """
        self.summary["Command"] = "Write Operating Mode Select"

        try:
            # Pack the command byte and mode value
            command_bytes = [5, mode.value]

            # Send the command
            success = self._write_command(command_bytes)
            self.summary["Successful"] = success

            logger.info(f"Set operating mode to {mode.name}: {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logger.error(f"Error setting operating mode: {e}")
            self.summary["Successful"] = False
            return False

    def get_operating_mode(self):
        """Get the current operating mode.

        Returns:
            OperatingMode enum value, or None if error
        """
        self.summary["Command"] = "Read Operating Mode Select"

        try:
            # Send read command and get response
            response = self._read_command(6, 1)

            if response and len(response) > 0:
                mode_value = response[0]
                mode = OperatingMode(mode_value)
                self.summary["Successful"] = True
                logger.info(f"Current operating mode: {mode.name}")
                return mode
            else:
                self.summary["Successful"] = False
                logger.warning("Failed to get operating mode")
                return None
        except Exception as e:
            logger.error(f"Error getting operating mode: {e}")
            self.summary["Successful"] = False
            return None

    def generate_solid_field(self, color, border=BorderEnable.Enable):
        """Generate a solid field of the specified color.

        Args:
            color: Field color (from Color enum)
            border: Whether to enable border (BorderEnable enum)

        Returns:
            True if successful, False otherwise
        """
        self.summary["Command"] = "Write Solid Field"

        try:
            # Pack the data according to the WriteSolidField function
            packer.packerinit()
            value = packer.setbits(0, 4, 0)  # Pattern type 0 = solid field
            value = packer.setbits(border.value, 1, 7)  # Border setting

            packer.packerinit()
            color_value = packer.setbits(color.value, 3, 4)

            # Build the command
            command_bytes = [11, value, color_value]

            # Send the command
            success = self._write_command(command_bytes)
            self.summary["Successful"] = success

            logger.info(f"Generate solid {color.name} field: {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logger.error(f"Error generating solid field: {e}")
            self.summary["Successful"] = False
            return False

    def generate_horizontal_lines(self, background_color, foreground_color,
                                  foreground_line_width, background_line_width,
                                  border=BorderEnable.Enable):
        """Generate horizontal lines on the projector.

        Args:
            background_color: Background color (from Color enum)
            foreground_color: Line color (from Color enum)
            foreground_line_width: Width of foreground lines
            background_line_width: Width of background lines
            border: Whether to enable border (BorderEnable enum)

        Returns:
            True if successful, False otherwise
        """
        self.summary["Command"] = "Write Horizontal Lines"

        try:
            # Pack the data according to the WriteHorizontalLines function
            packer.packerinit()
            value = packer.setbits(3, 4, 0)  # Pattern type 3 = horizontal lines
            value = packer.setbits(border.value, 1, 7)  # Border setting

            packer.packerinit()
            color_value = packer.setbits(background_color.value, 3, 0)
            color_value = packer.setbits(foreground_color.value, 3, 4)

            # Build the command
            command_bytes = [11, value, color_value, foreground_line_width, background_line_width]

            # Send the command
            success = self._write_command(command_bytes)
            self.summary["Successful"] = success

            logger.info(f"Generate horizontal lines: {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logger.error(f"Error generating horizontal lines: {e}")
            self.summary["Successful"] = False
            return False

    def generate_vertical_lines(self, background_color, foreground_color,
                                foreground_line_width, background_line_width,
                                border=BorderEnable.Enable):
        """Generate vertical lines on the projector.

        Args:
            background_color: Background color (from Color enum)
            foreground_color: Line color (from Color enum)
            foreground_line_width: Width of foreground lines
            background_line_width: Width of background lines
            border: Whether to enable border (BorderEnable enum)

        Returns:
            True if successful, False otherwise
        """
        self.summary["Command"] = "Write Vertical Lines"

        try:
            # Pack the data according to the WriteVerticalLines function
            packer.packerinit()
            value = packer.setbits(5, 4, 0)  # Pattern type 5 = vertical lines
            value = packer.setbits(border.value, 1, 7)  # Border setting

            packer.packerinit()
            color_value = packer.setbits(background_color.value, 3, 0)
            color_value = packer.setbits(foreground_color.value, 3, 4)

            # Build the command
            command_bytes = [11, value, color_value, foreground_line_width, background_line_width]

            # Send the command
            success = self._write_command(command_bytes)
            self.summary["Successful"] = success

            logger.info(f"Generate vertical lines: {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logger.error(f"Error generating vertical lines: {e}")
            self.summary["Successful"] = False
            return False

    def generate_diagonal_lines(self, background_color, foreground_color,
                                horizontal_spacing, vertical_spacing,
                                border=BorderEnable.Enable):
        """Generate diagonal lines on the projector.

        Args:
            background_color: Background color (from Color enum)
            foreground_color: Line color (from Color enum)
            horizontal_spacing: Horizontal spacing (from DiagonalLineSpacing enum)
            vertical_spacing: Vertical spacing (from DiagonalLineSpacing enum)
            border: Whether to enable border (BorderEnable enum)

        Returns:
            True if successful, False otherwise
        """
        self.summary["Command"] = "Write Diagonal Lines"

        try:
            # Pack the data according to the WriteDiagonalLines function
            packer.packerinit()
            value = packer.setbits(4, 4, 0)  # Pattern type 4 = diagonal lines
            value = packer.setbits(border.value, 1, 7)  # Border setting

            packer.packerinit()
            color_value = packer.setbits(background_color.value, 3, 0)
            color_value = packer.setbits(foreground_color.value, 3, 4)

            # Build the command
            command_bytes = [11, value, color_value, horizontal_spacing.value, vertical_spacing.value]

            # Send the command
            success = self._write_command(command_bytes)
            self.summary["Successful"] = success

            logger.info(f"Generate diagonal lines: {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logger.error(f"Error generating diagonal lines: {e}")
            self.summary["Successful"] = False
            return False

    def generate_grid(self, background_color, foreground_color,
                      horizontal_foreground_width, horizontal_background_width,
                      vertical_foreground_width, vertical_background_width,
                      border=BorderEnable.Enable):
        """Generate a grid pattern on the projector.

        Args:
            background_color: Background color (from Color enum)
            foreground_color: Line color (from Color enum)
            horizontal_foreground_width: Width of horizontal foreground lines
            horizontal_background_width: Width of spaces between horizontal lines
            vertical_foreground_width: Width of vertical foreground lines
            vertical_background_width: Width of spaces between vertical lines
            border: Whether to enable border (BorderEnable enum)

        Returns:
            True if successful, False otherwise
        """
        self.summary["Command"] = "Write Grid Lines"

        try:
            # Pack the data according to the WriteGridLines function
            packer.packerinit()
            value = packer.setbits(6, 4, 0)  # Pattern type 6 = grid
            value = packer.setbits(border.value, 1, 7)  # Border setting

            packer.packerinit()
            color_value = packer.setbits(background_color.value, 3, 0)
            color_value = packer.setbits(foreground_color.value, 3, 4)

            # Build the command
            command_bytes = [
                11, value, color_value,
                horizontal_foreground_width, horizontal_background_width,
                vertical_foreground_width, vertical_background_width
            ]

            # Send the command
            success = self._write_command(command_bytes)
            self.summary["Successful"] = success

            logger.info(f"Generate grid: {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logger.error(f"Error generating grid: {e}")
            self.summary["Successful"] = False
            return False

    def generate_grid_from_object(self, grid_lines):
        """Generate a grid pattern using a GridLines object.

        Args:
            grid_lines: GridLines object with grid configuration

        Returns:
            True if successful, False otherwise
        """
        return self.generate_grid(
            grid_lines.BackgroundColor,
            grid_lines.ForegroundColor,
            grid_lines.HorizontalForegroundLineWidth,
            grid_lines.HorizontalBackgroundLineWidth,
            grid_lines.VerticalForegroundLineWidth,
            grid_lines.VerticalBackgroundLineWidth,
            grid_lines.Border
        )

    def generate_checkerboard(self, background_color, foreground_color,
                              horizontal_count, vertical_count,
                              border=BorderEnable.Enable):
        """Generate a checkerboard pattern on the projector.

        Args:
            background_color: Background color (from Color enum)
            foreground_color: Foreground color (from Color enum)
            horizontal_count: Number of horizontal checkers
            vertical_count: Number of vertical checkers
            border: Whether to enable border (BorderEnable enum)

        Returns:
            True if successful, False otherwise
        """
        self.summary["Command"] = "Write Checkerboard"

        try:
            # Pack the data according to the WriteCheckerboard function
            packer.packerinit()
            value = packer.setbits(7, 4, 0)  # Pattern type 7 = checkerboard
            value = packer.setbits(border.value, 1, 7)  # Border setting

            packer.packerinit()
            color_value = packer.setbits(background_color.value, 3, 0)
            color_value = packer.setbits(foreground_color.value, 3, 4)

            # Pack horizontal and vertical counts as 16-bit values
            h_count_bytes = list(struct.pack('<H', horizontal_count))
            v_count_bytes = list(struct.pack('<H', vertical_count))

            # Build the command
            command_bytes = [11, value, color_value] + h_count_bytes + v_count_bytes

            # Send the command
            success = self._write_command(command_bytes)
            self.summary["Successful"] = success

            logger.info(f"Generate checkerboard: {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logger.error(f"Error generating checkerboard: {e}")
            self.summary["Successful"] = False
            return False

    def generate_colorbars(self, border=BorderEnable.Enable):
        """Generate color bars pattern on the projector.

        Args:
            border: Whether to enable border (BorderEnable enum)

        Returns:
            True if successful, False otherwise
        """
        self.summary["Command"] = "Write Colorbars"

        try:
            # Pack the data according to the WriteColorbars function
            packer.packerinit()
            value = packer.setbits(8, 4, 0)  # Pattern type 8 = colorbars
            value = packer.setbits(border.value, 1, 7)  # Border setting

            # Build the command
            command_bytes = [11, value]

            # Send the command
            success = self._write_command(command_bytes)
            self.summary["Successful"] = success

            logger.info(f"Generate colorbars: {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logger.error(f"Error generating colorbars: {e}")
            self.summary["Successful"] = False
            return False

    def execute_flash_batch_file(self, batch_file_number):
        """Execute a batch file stored in flash.

        Args:
            batch_file_number: Batch file number to execute

        Returns:
            True if successful, False otherwise
        """
        self.summary["Command"] = "Write Execute Flash Batch File"

        try:
            # Build the command
            command_bytes = [45, batch_file_number]

            # Send the command
            success = self._write_command(command_bytes)
            self.summary["Successful"] = success

            logger.info(f"Execute flash batch file {batch_file_number}: {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logger.error(f"Error executing flash batch file: {e}")
            self.summary["Successful"] = False
            return False

    def select_splash_screen(self, splash_screen_index):
        """Select a splash screen.

        Args:
            splash_screen_index: Index of the splash screen

        Returns:
            True if successful, False otherwise
        """
        self.summary["Command"] = "Write Splash Screen Select"

        try:
            # Build the command
            command_bytes = [13, splash_screen_index]

            # Send the command
            success = self._write_command(command_bytes)
            self.summary["Successful"] = success

            logger.info(f"Select splash screen {splash_screen_index}: {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logger.error(f"Error selecting splash screen: {e}")
            self.summary["Successful"] = False
            return False

    def execute_splash_screen(self):
        """Execute the selected splash screen.

        Returns:
            True if successful, False otherwise
        """
        self.summary["Command"] = "Write Splash Screen Execute"

        try:
            # Build the command
            command_bytes = [53]

            # Send the command
            success = self._write_command(command_bytes)
            self.summary["Successful"] = success

            logger.info(f"Execute splash screen: {'Success' if success else 'Failed'}")
            return success
        except Exception as e:
            logger.error(f"Error executing splash screen: {e}")
            self.summary["Successful"] = False
            return False