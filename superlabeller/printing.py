"""Sending raw TSPL data to a printer.

Targets are dicts:
  {"kind": "windows", "printer": "TSC TTP-244 Pro"}      Windows spooler, RAW
  {"kind": "cups", "printer": "TSC"}                     Linux/macOS: lp -o raw
  {"kind": "network", "host": "192.168.1.50", "port": 9100}
  {"kind": "serial", "port": "COM3", "baud": 9600}
  {"kind": "file", "path": "label.prn"}
"""
import socket
import subprocess
import sys

IS_WINDOWS = sys.platform.startswith("win")


def list_printers():
    if IS_WINDOWS:
        try:
            import win32print
        except ImportError:
            return []
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        return sorted(p[2] for p in win32print.EnumPrinters(flags))
    try:
        out = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=5).stdout
        return sorted(line.strip() for line in out.splitlines() if line.strip())
    except (OSError, subprocess.SubprocessError):
        return []


def default_printer():
    if IS_WINDOWS:
        try:
            import win32print
            return win32print.GetDefaultPrinter()
        except Exception:
            return ""
    return ""


def list_serial_ports():
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except ImportError:
        return []


def describe(target):
    kind = target.get("kind")
    if kind in ("windows", "cups"):
        return target.get("printer", "?")
    if kind == "network":
        return f"{target.get('host')}:{target.get('port', 9100)}"
    if kind == "serial":
        return f"{target.get('port')} @ {target.get('baud')}"
    if kind == "file":
        return target.get("path", "?")
    if kind == "mock":
        return "mock printer"
    return "?"


def send(target, data):
    kind = target.get("kind")
    if kind == "windows":
        import win32print
        h = win32print.OpenPrinter(target["printer"])
        try:
            win32print.StartDocPrinter(h, 1, ("TSPL label", None, "RAW"))
            try:
                win32print.StartPagePrinter(h)
                win32print.WritePrinter(h, data)
                win32print.EndPagePrinter(h)
            finally:
                win32print.EndDocPrinter(h)
        finally:
            win32print.ClosePrinter(h)
    elif kind == "cups":
        subprocess.run(["lp", "-d", target["printer"], "-o", "raw"], input=data, check=True, timeout=30)
    elif kind == "network":
        with socket.create_connection((target["host"], int(target.get("port", 9100))), timeout=5) as s:
            s.sendall(data)
    elif kind == "serial":
        import serial
        with serial.Serial(target["port"], int(target.get("baud", 9600)), timeout=2, write_timeout=10) as s:
            s.write(data)
            s.flush()
    elif kind == "file":
        with open(target["path"], "wb") as f:
            f.write(data)
    else:
        raise ValueError("No printer selected")
