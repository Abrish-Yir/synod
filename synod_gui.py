import asyncio
import threading
import time
import os
import pyautogui
import pygetwindow as gw
import customtkinter as ctk
import screen_brightness_control as sbc
from datetime import datetime
from bleak import BleakClient

# --- DEVICE CONNECTION SETTINGS ---
ADDRESS = "29:7C:9F:8E:EB:F4"
WRITE_UUID = "7e400002-b5a3-f393-e0a9-e50e24dcca9d"
NOTIFY_UUID = "7e400003-b5a3-f393-e0a9-e50e24dcca9d"

class SynodGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Window Setup
        self.title("SYNOD COMMAND CENTER")
        self.geometry("600x600")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        # System State
        self.is_running = False
        self.client = None
        self.last_id = None
        self.tap_count = 0
        self.last_tap_time = 0

        self.setup_ui()

    def setup_ui(self):
        # Header
        self.label = ctk.CTkLabel(self, text="⚡ SYNOD SYSTEM", font=("Impact", 35), text_color="#3a7ebf")
        self.label.pack(pady=20)

        # Tabs
        self.tabview = ctk.CTkTabview(self, width=540, height=320)
        self.tabview.pack(padx=20, pady=10)
        self.tabview.add("Watch Macros")
        self.tabview.add("Movie Mode Settings")

        # --- Tab 1: Watch Macros ---
        self.m_label = ctk.CTkLabel(self.tabview.tab("Watch Macros"), 
            text="• Find Phone [START]: Activate Movie Mode\n• Find Phone [STOP]: Close Active App (Alt+F4)\n• Swipes: Volume & Media Control\n• Exit/Photo: Show Desktop (Stealth)",
            font=("Arial", 14), justify="left")
        self.m_label.pack(pady=30)
        
        self.app_display = ctk.CTkLabel(self.tabview.tab("Watch Macros"), text="Current App: Searching...", font=("Arial", 12, "italic"))
        self.app_display.pack(pady=10)

        # --- Tab 2: Movie Mode Settings ---
        self.vol_text = ctk.CTkLabel(self.tabview.tab("Movie Mode Settings"), text="Movie Volume Level:")
        self.vol_text.pack(pady=(10, 0))
        self.vol_slider = ctk.CTkSlider(self.tabview.tab("Movie Mode Settings"), from_=0, to=100)
        self.vol_slider.pack(pady=10)
        self.vol_slider.set(80)

        self.br_text = ctk.CTkLabel(self.tabview.tab("Movie Mode Settings"), text="Movie Brightness Level:")
        self.br_text.pack(pady=(10, 0))
        self.br_slider = ctk.CTkSlider(self.tabview.tab("Movie Mode Settings"), from_=0, to=100)
        self.br_slider.pack(pady=10)
        self.br_slider.set(50)

        # Main Control
        self.start_btn = ctk.CTkButton(self, text="CONNECT WATCH", font=("Arial", 20, "bold"), height=50, command=self.toggle_service)
        self.start_btn.pack(pady=20)

        self.status_indicator = ctk.CTkLabel(self, text="● SYSTEM OFFLINE", text_color="gray")
        self.status_indicator.pack(side="bottom", pady=10)

    def toggle_service(self):
        if not self.is_running:
            self.is_running = True
            self.start_btn.configure(text="DISCONNECT", fg_color="#9c2e2e")
            self.status_indicator.configure(text="● SYSTEM LIVE", text_color="green")
            threading.Thread(target=self.run_ble_logic, daemon=True).start()
        else:
            self.is_running = False
            self.start_btn.configure(text="CONNECT WATCH", fg_color="#1f538d")
            self.status_indicator.configure(text="● SYSTEM OFFLINE", text_color="gray")

    def run_ble_logic(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.ble_engine())

    async def ble_engine(self):
        try:
            async with BleakClient(ADDRESS) as client:
                self.client = client
                await client.start_notify(NOTIFY_UUID, self.on_data_received)
                
                # Handshake & Sync
                await client.write_gatt_char(WRITE_UUID, bytearray([0xCD, 0x00, 0x01, 0x01]))
                
                while self.is_running:
                    # Process taps after a short delay
                    if self.last_id is not None and (time.time() - self.last_tap_time) > 0.4:
                        self.execute_synod_command(self.last_id, self.tap_count)
                        self.last_id = None
                        self.tap_count = 0
                    
                    # Keep-alive heartbeat
                    await client.write_gatt_char(WRITE_UUID, bytearray([0xCD, 0x00, 0x01, 0x01]))
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Connection Lost: {e}")
            self.is_running = False

    def on_data_received(self, handle, data):
        msg = list(data)
        if len(msg) >= 6 and msg[3] == 0x1C:
            self.last_id = msg[5]
            self.last_tap_time = time.time()
            self.tap_count += 1

    def apply_movie_mode(self):
        """Sets Volume and Brightness based on GUI sliders."""
        v_level = int(self.vol_slider.get())
        b_level = int(self.br_slider.get())
        
        # 1. Set Volume
        pyautogui.press('volumemute')
        pyautogui.press('volumemute')
        for _ in range(50): pyautogui.press('volumedown') # Reset to 0
        for _ in range(v_level // 2): pyautogui.press('volumeup') # Set to target
        
        # 2. Set Brightness
        try:
            sbc.set_brightness(b_level)
        except: pass 
        print(f"🎬 Movie Mode: Vol {v_level}% | Bright {b_level}%")

    def execute_synod_command(self, cmd_id, taps):
        # App Detection
        app_name = "desktop"
        try:
            win = gw.getActiveWindow()
            app_name = win.title.lower() if win else "desktop"
            self.app_display.configure(text=f"Current App: {app_name[:25]}")
        except: pass

        # --- MOVIE MODE (Find Phone Buttons) ---
        if cmd_id == 0x01: # Start Button
            self.apply_movie_mode()
            return
        elif cmd_id == 0x0E: # Stop Button
            pyautogui.hotkey('alt', 'f4')
            return

        # --- MEDIA CONTROLS ---
        if cmd_id == 0x0C: # Swipe Up
            if taps >= 3 and "spotify" in app_name:
                pyautogui.press('nexttrack')
            else:
                pyautogui.press('volumeup')

        elif cmd_id == 0x0A: # Swipe Down
            if taps >= 3 and "spotify" in app_name:
                pyautogui.press('prevtrack')
            else:
                pyautogui.press('volumedown')

        elif cmd_id == 0x0B: # Center Tap
            pyautogui.press('playpause')

        elif cmd_id in [0x03, 0x05]: # Photo/Exit Button
            pyautogui.hotkey('win', 'd')

if __name__ == "__main__":
    app = SynodGUI()
    app.mainloop()