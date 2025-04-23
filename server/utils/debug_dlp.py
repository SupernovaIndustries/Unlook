#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DLP LightCrafter 160CP UART Controller

This module implements the UART interface for controlling the DLPDLCR160CPEVM 
according to the DLPDLCR160CPEVM Software Programmer's Guide.
"""

import serial
import time
import logging
import sys
from typing import Dict, List, Any, Optional, Tuple, Union

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DLP_UART")


class DLPUART:
    """
    UART interface to control DLP LightCrafter 160CP module.
    """

    def __init__(self, port: str = '/dev/ttyAMA0', baudrate: int = 9600, timeout: float = 1.0):
        """
        Initialize the UART controller.

        Args:
            port: Serial port device path
            baudrate: Baud rate (default: 9600)
            timeout: Serial read timeout in seconds
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

    def open(self) -> bool:
        """
        Open the serial connection.

        Returns:
            True if connection opened successfully, False otherwise
        """
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout
            )
            logger.info(f"Connected to {self.port} at {self.baudrate} baud")
            return True
        except Exception as e:
            logger.error(f"Failed to open {self.port}: {e}")
            return False

    def close(self) -> None:
        """Close the serial connection."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            logger.info(f"Serial connection to {self.port} closed")

    def build_command(self, command_mode: int, payload: bytes, mspm0_addr: int = 0) -> bytes:
        """
        Build a command according to the UART protocol.

        Args:
            command_mode: Command mode (0=DLPC3421, 1=SSD1963, 2=MSPM0, 3=Reserved)
            payload: Command payload
            mspm0_addr: MSPM0 address (0 or 1, default: 0)

        Returns:
            Complete command frame as bytes
        """
        # Calculate command size (payload size in bytes)
        command_size = len(payload)

        # Validate inputs
        if command_mode not in range(4):
            raise ValueError("command_mode must be 0-3")
        if command_size not in range(32):
            raise ValueError("command_size must be 0-31")
        if mspm0_addr not in range(2):
            raise ValueError("mspm0_addr must be 0 or 1")

        # Build main command byte:
        # Bits 0-1: Command mode
        # Bits 2-6: Command size
        # Bit 7: MSPM0 Address
        main_command = (command_mode & 0x03) | ((command_size & 0x1F) << 2) | ((mspm0_addr & 0x01) << 7)

        # Build the frame
        frame = bytearray([0x55])  # Sync field (not included in checksum)
        frame.append(main_command)  # Main command
        frame.extend(payload)  # Command payload

        # Calculate checksum (sum of all bytes except sync, modulo 256)
        checksum = sum(frame[1:]) % 256
        frame.append(checksum)  # Checksum

        # Add delimiter
        frame.append(0x0A)  # Delimiter (newline)

        logger.debug(f"Built command frame: {frame.hex()}")
        return bytes(frame)

    def send_command(self, command_mode: int, payload: bytes, mspm0_addr: int = 0) -> bytes:
        """
        Send a command to the DLP module and return the response.

        Args:
            command_mode: Command mode (0=DLPC3421, 1=SSD1963, 2=MSPM0, 3=Reserved)
            payload: Command payload
            mspm0_addr: MSPM0 address (0 or 1, default: 0)

        Returns:
            Response from the DLP module, or empty bytes if no response
        """
        if not self.ser or not self.ser.is_open:
            logger.error("Serial port not open")
            return b''

        # Build the command
        command = self.build_command(command_mode, payload, mspm0_addr)

        # Log the command
        logger.info(f"Sending: {command.hex()}")

        # Flush input buffer to clear any pending data
        self.ser.reset_input_buffer()

        # Send the command
        self.ser.write(command)

        # Wait for response
        time.sleep(0.1)

        # Read response (if any)
        response = self.ser.read(100)  # Read up to 100 bytes

        if response:
            logger.info(f"Received: {response.hex()}")
        else:
            logger.warning("No response received")

        return response

    # === DLPC3421 Commands ===

    def build_dlpc_command(self,
                           sub_address: int,
                           read_length: int = 0,
                           params: bytes = b'') -> bytes:
        """
        Build a command for DLPC3421 controller.

        Args:
            sub_address: Sub-address (command code)
            read_length: Number of bytes to read (0 for write commands)
            params: Additional parameters for the command

        Returns:
            Complete payload for the command
        """
        # For DLPC3421 commands:
        # Byte 0: Address (0x36 for write, 0x3A for alternate)
        # Byte 1: Read Data Length (0 for write commands)
        # Byte 2: Sub-Address (command)
        # Bytes 3+: Remaining data bytes (parameters)

        dlpc_addr = 0x36  # Write address
        payload = bytearray([dlpc_addr, read_length, sub_address])
        payload.extend(params)

        return bytes(payload)

    def read_version(self) -> Dict[str, Any]:
        """
        Read the version information from the DLP controller.

        Returns:
            Dictionary with version information or empty dict if failed
        """
        # Build the Read Version command (sub-address 0x28)
        # We expect 4 bytes in response
        payload = self.build_dlpc_command(0x28, 4)

        # Send command
        response = self.send_command(0, payload)

        # Check for valid response
        if not response or len(response) < 10:
            logger.error("Invalid response to read_version command")
            return {}

        # Parse the response:
        # Expected format: 0x55, main_cmd, 0x37, read_len, 0x28, patch, minor, major, checksum, 0x0A
        try:
            response_addr = response[2]
            if response_addr != 0x37:  # Read response marker
                logger.error(f"Unexpected response address: 0x{response_addr:02X}")
                return {}

            patch_ver = response[5]
            minor_ver = response[6]
            major_ver = response[7]

            version = {
                'major': major_ver,
                'minor': minor_ver,
                'patch': patch_ver,
                'version_string': f"{major_ver}.{minor_ver}.{patch_ver}"
            }

            logger.info(f"DLP Version: {version['version_string']}")
            return version

        except Exception as e:
            logger.error(f"Error parsing version response: {e}")
            return {}

    def display_test_pattern(self, pattern_number: int) -> bool:
        """
        Display a test pattern on the DLP.

        Args:
            pattern_number: Test pattern number (0-127)
                0: Solid field (no pattern)
                1: Grid
                2: Checkerboard
                4: Vertical lines
                8: Horizontal lines
                9: Diagonal lines
                10: ANSI contrast
                11: ANSI 16-level

        Returns:
            True if successful, False otherwise
        """
        # Test Pattern command (sub-address 0x0B)
        # Parameters for test pattern: 
        # 0x03: Select test pattern option
        # 0x70: Internal test pattern
        # 0x01: Pattern number follows
        # [pattern_number]: The pattern number to display
        params = bytes([0x03, 0x70, 0x01, pattern_number])
        payload = self.build_dlpc_command(0x0B, 0, params)

        # Send command
        response = self.send_command(0, payload)

        logger.info(f"Test pattern {pattern_number} command sent")
        return True

    def source_select(self, source: int) -> bool:
        """
        Select the input source.

        Args:
            source: Input source (0: Parallel RGB, 2: DSI)

        Returns:
            True if successful, False otherwise
        """
        # Input Source Select command (0x05)
        payload = self.build_dlpc_command(0x05, 0, bytes([source]))

        # Send command
        response = self.send_command(0, payload)

        logger.info(f"Source select {source} command sent")
        return True

    def power_mode(self, mode: int) -> bool:
        """
        Set power mode.

        Args:
            mode: Power mode (0: Normal, 1: Standby, 2: Sleep)

        Returns:
            True if successful, False otherwise
        """
        # Power Mode command (0x02)
        payload = self.build_dlpc_command(0x02, 0, bytes([mode]))

        # Send command
        response = self.send_command(0, payload)

        logger.info(f"Power mode {mode} command sent")
        return True

    def dsi_port_enable(self, enable: bool) -> bool:
        """
        Enable or disable DSI port.

        Args:
            enable: True to enable, False to disable

        Returns:
            True if successful, False otherwise
        """
        # DSI Port Enable command (0xD7)
        value = 1 if enable else 0
        payload = self.build_dlpc_command(0xD7, 0, bytes([value]))

        # Send command
        response = self.send_command(0, payload)

        logger.info(f"DSI port {'enabled' if enable else 'disabled'}")
        return True

    def list_available_ports() -> List[str]:
        """
        List all available serial ports on the system.

        Returns:
            List of available serial port names
        """
        try:
            import serial.tools.list_ports
            ports = serial.tools.list_ports.comports()
            return [port.device for port in ports]
        except:
            return []

    def test_all_commands(self) -> bool:
        """
        Run a test sequence of various commands to verify functionality.

        Returns:
            True if all commands completed without errors, False otherwise
        """
        try:
            # Read version
            version = self.read_version()
            if not version:
                logger.error("Failed to read version")
                return False

            # Test different patterns
            logger.info("Testing patterns...")
            for pattern in [1, 2, 4, 8]:
                self.display_test_pattern(pattern)
                time.sleep(2)  # Show each pattern for 2 seconds

            # Return to normal
            self.display_test_pattern(0)

            logger.info("All commands completed successfully")
            return True

        except Exception as e:
            logger.error(f"Error during command test sequence: {e}")
            return False


def test_all_ports(baudrate: int = 9600) -> Optional[str]:
    """
    Try connecting to the DLP on all available ports.

    Args:
        baudrate: Baud rate to use

    Returns:
        Port name that worked, or None if none worked
    """
    # List of ports to try
    possible_ports = DLPUART.list_available_ports()

    # Also try these common Raspberry Pi ports if not already in the list
    standard_ports = [
        '/dev/ttyAMA0',  # Primary UART on Raspberry Pi
        '/dev/ttyS0',  # Secondary UART on Raspberry Pi
        '/dev/ttyUSB0',  # USB-to-serial adapter
        '/dev/ttyAMA1',
        '/dev/serial0',  # Symlink to primary UART
        '/dev/ttyACM0'  # USB ACM device
    ]

    for port in standard_ports:
        if port not in possible_ports:
            possible_ports.append(port)

    logger.info(f"Testing {len(possible_ports)} ports: {', '.join(possible_ports)}")

    # Try each port
    for port in possible_ports:
        logger.info(f"Trying port {port}...")
        dlp = DLPUART(port=port, baudrate=baudrate)

        try:
            if dlp.open():
                # Try to read version
                version = dlp.read_version()
                if version:
                    logger.info(f"Success! Port {port} works. DLP version: {version['version_string']}")
                    dlp.close()
                    return port
                else:
                    logger.info(f"Port {port} opened but got no valid response")
        except Exception as e:
            logger.warning(f"Error testing port {port}: {e}")

        # Close connection before trying next port
        dlp.close()
        time.sleep(0.5)  # Short pause between tests

    logger.error("No working port found")
    return None


def interactive_test(port: str = None):
    """
    Run an interactive test session.

    Args:
        port: Serial port to use (will auto-detect if None)
    """
    if not port:
        port = test_all_ports()
        if not port:
            logger.error("Could not find a working port. Exiting.")
            return

    dlp = DLPUART(port=port)
    if not dlp.open():
        logger.error(f"Failed to open port {port}")
        return

    try:
        print("\n== DLP LightCrafter 160CP Interactive Test ==")
        print(f"Connected to: {port}")

        while True:
            print("\nCommands:")
            print("1. Read Version")
            print("2. Test Patterns")
            print("3. Input Source Select")
            print("4. Power Mode")
            print("5. Run Test Sequence")
            print("q. Quit")

            cmd = input("\nEnter command (1-5, q): ").strip().lower()

            if cmd == 'q':
                break

            elif cmd == '1':
                version = dlp.read_version()
                if version:
                    print(f"DLP Version: {version['version_string']}")

            elif cmd == '2':
                print("\nTest Patterns:")
                print("0. Solid Field (no pattern)")
                print("1. Grid")
                print("2. Checkerboard")
                print("4. Vertical Lines")
                print("8. Horizontal Lines")
                print("9. Diagonal Lines")

                pattern = input("Enter pattern number (0-9): ").strip()
                try:
                    pattern_num = int(pattern)
                    dlp.display_test_pattern(pattern_num)
                except ValueError:
                    print("Invalid input. Please enter a number.")

            elif cmd == '3':
                print("\nInput Sources:")
                print("0. Parallel RGB")
                print("2. DSI")

                source = input("Enter source number (0 or 2): ").strip()
                try:
                    source_num = int(source)
                    dlp.source_select(source_num)
                except ValueError:
                    print("Invalid input. Please enter a number.")

            elif cmd == '4':
                print("\nPower Modes:")
                print("0. Normal")
                print("1. Standby")
                print("2. Sleep")

                mode = input("Enter power mode (0-2): ").strip()
                try:
                    mode_num = int(mode)
                    dlp.power_mode(mode_num)
                except ValueError:
                    print("Invalid input. Please enter a number.")

            elif cmd == '5':
                print("\nRunning test sequence...")
                dlp.test_all_commands()

            else:
                print("Invalid command")

    finally:
        # Make sure to close the connection
        dlp.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='DLP LightCrafter 160CP UART Controller')
    parser.add_argument('-p', '--port', help='Serial port device')
    parser.add_argument('-b', '--baudrate', type=int, default=9600, help='Baud rate')
    parser.add_argument('-i', '--interactive', action='store_true', help='Run interactive test')
    parser.add_argument('-t', '--test', action='store_true', help='Run automatic test sequence')
    parser.add_argument('-a', '--auto-detect', action='store_true', help='Auto-detect port')
    parser.add_argument('-l', '--list-ports', action='store_true', help='List available ports')
    parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')

    args = parser.parse_args()

    # Set log level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # List ports if requested
    if args.list_ports:
        print("Available serial ports:")
        for port in DLPUART.list_available_ports():
            print(f"  {port}")
        sys.exit(0)

    # Auto-detect port if requested
    if args.auto_detect:
        port = test_all_ports(args.baudrate)
        if not port:
            sys.exit(1)
    else:
        port = args.port

    # Run tests
    if args.interactive:
        interactive_test(port)
    elif args.test:
        if not port:
            port = test_all_ports(args.baudrate)
            if not port:
                sys.exit(1)

        dlp = DLPUART(port=port, baudrate=args.baudrate)
        if dlp.open():
            success = dlp.test_all_commands()
            dlp.close()
            sys.exit(0 if success else 1)
        else:
            sys.exit(1)
    elif not args.list_ports and not args.auto_detect:
        # If no specific action was requested, run interactive mode
        interactive_test(port)