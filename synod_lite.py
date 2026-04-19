import asyncio
import os
import pyautogui
import pygetwindow as gw
from bleak import BleakClient

# --- CONFIG ---
ADDRESS = "29:7C:9F:8E:EB:F4"
WRITE_UUID = "7e400002-b5a3-f393-e0a9-e50e24dcca9d"
NOTIFY_UUID = "7e400003-b5a3-f393-e0a9-e50e24dcca9d"

def handle_notify(handle, data):
    msg = list(data)
    if len(msg) >= 6 and msg[3] == 0x1C:
        cmd_id = msg[5]
        
        # Action Logic
        if cmd_id == 0x01: os.system("calc") # Start Button
        elif cmd_id == 0x0E: pyautogui.hotkey('alt', 'f4') # Stop Button
        elif cmd_id == 0x0C: pyautogui.press('volumeup')
        elif cmd_id == 0x0A: pyautogui.press('volumedown')
        elif cmd_id == 0x0B: pyautogui.press('playpause')
        elif cmd_id in [0x03, 0x05]: pyautogui.hotkey('win', 'd')

async def main():
    print("🛰️ SYNOD LITE: RUNNING")
    async with BleakClient(ADDRESS) as client:
        await client.start_notify(NOTIFY_UUID, handle_notify)
        while True:
            # Keep-alive heartbeat
            await client.write_gatt_char(WRITE_UUID, bytearray([0xCD, 0x00, 0x01, 0x01]))
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())