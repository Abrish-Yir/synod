import asyncio
import threading
import time
import json
import os
import ctypes
from ctypes import cast, POINTER
import pyautogui
import customtkinter as ctk
import screen_brightness_control as sbc
from tkinter import filedialog
from bleak import BleakScanner, BleakClient

# --- CONFIG ---
WRITE_UUID = "7e400002-b5a3-f393-e0a9-e50e24dcca9d"
NOTIFY_UUID = "7e400003-b5a3-f393-e0a9-e50e24dcca9d"

COLORS = {
    "bg_dark": "#0a0a0a",
    "bg_card": "#141414",
    "bg_card_hover": "#1a1a1a",
    "bg_input": "#1e1e1e",
    "bg_elevated": "#242424",
    "text_primary": "#ffffff",
    "text_secondary": "#a7a7a7",
    "text_muted": "#535353",
    "accent_green": "#1ed760",
    "accent_green_hover": "#1fdf64",
    "accent_blue": "#0a84ff",
    "accent_purple": "#b44dff",
    "accent_red": "#ff3b30",
    "accent_orange": "#ff9f0a",
    "accent_cyan": "#64d2ff",
    "border_subtle": "#282828",
    "border_active": "#3a3a3a",
}


class ModernCard(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_card"], corner_radius=12,
                         border_width=1, border_color=COLORS["border_subtle"], **kwargs)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, event):
        self.configure(border_color=COLORS["border_active"], fg_color=COLORS["bg_card_hover"])

    def _on_leave(self, event):
        self.configure(border_color=COLORS["border_subtle"], fg_color=COLORS["bg_card"])


class ActionCard(ctk.CTkFrame):
    def __init__(self, master, action_name, btn_id, on_edit, **kwargs):
        self.action_name = action_name
        self.btn_id = btn_id
        self.on_edit = on_edit
        self.is_editing = False

        super().__init__(master, fg_color=COLORS["bg_elevated"], corner_radius=10,
                         border_width=1, border_color=COLORS["border_subtle"],
                         cursor="hand2", height=70, **kwargs)
        self.grid_columnconfigure((0, 1, 2), weight=1)

        icon_frame = ctk.CTkFrame(self, fg_color="transparent", width=50)
        icon_frame.grid(row=0, column=0, padx=(12, 0), pady=12, sticky="w")
        ctk.CTkLabel(icon_frame, text=self._get_icon(), font=("Segoe UI Emoji", 22)).pack()

        text_frame = ctk.CTkFrame(self, fg_color="transparent")
        text_frame.grid(row=0, column=1, padx=8, pady=12, sticky="w")
        ctk.CTkLabel(text_frame, text=action_name, font=("Segoe UI", 14, "bold"),
                     text_color=COLORS["text_primary"]).pack(anchor="w")
        self.id_label = ctk.CTkLabel(text_frame, text=self._get_id_text(),
                                     font=("Consolas", 11), text_color=COLORS["text_muted"])
        self.id_label.pack(anchor="w")

        self.edit_btn = ctk.CTkButton(
            self, text="✏️", width=36, height=36,
            fg_color=COLORS["bg_input"], hover_color=COLORS["accent_blue"],
            text_color=COLORS["text_secondary"], font=("Segoe UI Emoji", 14),
            corner_radius=8, border_width=1, border_color=COLORS["border_subtle"],
            command=lambda: self.on_edit(action_name)
        )
        self.edit_btn.grid(row=0, column=2, padx=(0, 12), pady=17, sticky="e")

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _get_icon(self):
        return {"Volume Up": "🔊", "Volume Down": "🔉", "Play/Pause": "⏯️", "Movie Mode": "🎬"}.get(self.action_name, "🔘")

    def _get_id_text(self):
        return f"ID: 0x{self.btn_id:02X}" if self.btn_id is not None else "Not assigned"

    def _on_enter(self, event):
        self.configure(border_color=COLORS["accent_green"], fg_color="#1e1e1e")
        self.edit_btn.configure(fg_color=COLORS["accent_blue"], text_color="white")

    def _on_leave(self, event):
        if not self.is_editing:
            self.configure(border_color=COLORS["border_subtle"], fg_color=COLORS["bg_elevated"])
            self.edit_btn.configure(fg_color=COLORS["bg_input"], text_color=COLORS["text_secondary"])

    def set_editing(self, editing):
        self.is_editing = editing
        if editing:
            self.configure(border_color=COLORS["accent_orange"], fg_color="#2a1a00")
            self.edit_btn.configure(text="⏳", fg_color=COLORS["accent_orange"])
        else:
            self.configure(border_color=COLORS["border_subtle"], fg_color=COLORS["bg_elevated"])
            self.edit_btn.configure(text="✏️", fg_color=COLORS["bg_input"], text_color=COLORS["text_secondary"])

    def update_btn_id(self, btn_id):
        self.btn_id = btn_id
        self.id_label.configure(text=self._get_id_text())


class SynodUniversal(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SYNOD UNIVERSAL")
        self.geometry("680x820")
        self.minsize(680, 820)
        self.configure(fg_color=COLORS["bg_dark"])

        self.target_address = None
        self.mapping = {}
        self.is_running = False
        self.is_learning = False
        self.is_editing_single = False
        self.current_learning_key = None
        self.profile_path = "synod_profile.json"
        self.last_id = None
        self.last_tap_time = 0
        self.action_cards = {}

        self.setup_ui()
        self.load_internal_profile()
        self.refresh_action_cards()

    def setup_ui(self):
        header = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"], height=80)
        header.pack(fill="x", padx=24, pady=(20, 0))
        header.pack_propagate(False)

        logo_frame = ctk.CTkFrame(header, fg_color="transparent")
        logo_frame.pack(side="left")

        self.status_dot = ctk.CTkLabel(logo_frame, text="●", font=("Segoe UI", 28), text_color=COLORS["text_muted"])
        self.status_dot.pack(side="left", padx=(0, 12))

        title_frame = ctk.CTkFrame(logo_frame, fg_color="transparent")
        title_frame.pack(side="left")
        ctk.CTkLabel(title_frame, text="SYNOD", font=("Segoe UI", 24, "bold"), text_color=COLORS["text_primary"]).pack(anchor="w")
        ctk.CTkLabel(title_frame, text="UNIVERSAL  v16.7", font=("Segoe UI", 11), text_color=COLORS["text_muted"]).pack(anchor="w")

        ctk.CTkLabel(header, text=" BT LE ", font=("Consolas", 10, "bold"), text_color=COLORS["accent_cyan"],
                     fg_color="#0a2a3a", corner_radius=6).pack(side="right", padx=(0, 0), pady=20)

        # Removed unsupported scrollbar styling params for compatibility
        self.main_scroll = ctk.CTkScrollableFrame(self, fg_color=COLORS["bg_dark"])
        self.main_scroll.pack(fill="both", expand=True, padx=24, pady=16)

        self._create_section_label(self.main_scroll, "DEVICE CONNECTION")

        device_card = ModernCard(self.main_scroll)
        device_card.pack(fill="x", pady=(0, 8))

        device_inner = ctk.CTkFrame(device_card, fg_color="transparent")
        device_inner.pack(fill="x", padx=16, pady=14)

        self.device_label = ctk.CTkLabel(device_inner, text="No device selected", font=("Segoe UI", 13), text_color=COLORS["text_secondary"])
        self.device_label.pack(anchor="w")

        # Removed border_width, border_color, and dropdown_hover_color — not supported on CTkOptionMenu in all versions
        self.device_list = ctk.CTkOptionMenu(
            device_inner,
            values=["— Scan to discover —"],
            font=("Segoe UI", 12),
            fg_color=COLORS["bg_input"],
            button_color=COLORS["bg_input"],
            button_hover_color=COLORS["bg_elevated"],
            dropdown_fg_color=COLORS["bg_elevated"],
            text_color=COLORS["text_primary"],
            corner_radius=8,
        )
        self.device_list.pack(fill="x", pady=(10, 0))

        btn_row = ctk.CTkFrame(device_inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(12, 0))

        self.scan_btn = ctk.CTkButton(btn_row, text="🔍  Scan", font=("Segoe UI", 12, "bold"),
                                      fg_color=COLORS["accent_blue"], hover_color="#3a9fff",
                                      text_color="white", corner_radius=8, height=38, command=self.start_scan)
        self.scan_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.learn_btn = ctk.CTkButton(btn_row, text="🎓  Learn All", font=("Segoe UI", 12, "bold"),
                                       fg_color=COLORS["accent_purple"], hover_color="#c46bff",
                                       text_color="white", corner_radius=8, height=38, command=self.start_learning)
        self.learn_btn.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.instruction_label = ctk.CTkLabel(device_inner, text="", font=("Segoe UI", 12), text_color=COLORS["text_muted"])
        self.instruction_label.pack(anchor="w", pady=(10, 0))

        self._create_section_label(self.main_scroll, "ACTION MAPPINGS")

        self.actions_card = ModernCard(self.main_scroll)
        self.actions_card.pack(fill="x", pady=(0, 8))

        self.actions_container = ctk.CTkFrame(self.actions_card, fg_color="transparent")
        self.actions_container.pack(fill="x", padx=12, pady=12)

        self._create_section_label(self.main_scroll, "MOVIE MODE PRESETS")

        movie_card = ModernCard(self.main_scroll)
        movie_card.pack(fill="x", pady=(0, 8))

        movie_inner = ctk.CTkFrame(movie_card, fg_color="transparent")
        movie_inner.pack(fill="x", padx=16, pady=16)

        vol_row = ctk.CTkFrame(movie_inner, fg_color="transparent")
        vol_row.pack(fill="x", pady=(0, 12))
        vol_label_frame = ctk.CTkFrame(vol_row, fg_color="transparent", width=140)
        vol_label_frame.pack(side="left")
        vol_label_frame.pack_propagate(False)
        ctk.CTkLabel(vol_label_frame, text="🔊 Volume", font=("Segoe UI", 13, "bold"), text_color=COLORS["text_primary"]).pack(anchor="w")
        self.vol_value_label = ctk.CTkLabel(vol_label_frame, text="80%", font=("Consolas", 11), text_color=COLORS["accent_green"])
        self.vol_value_label.pack(anchor="w")

        # Removed height and corner_radius from CTkSlider — not supported in all versions
        self.vol_slider = ctk.CTkSlider(vol_row, from_=0, to=100, command=self._on_vol_change,
                                        fg_color=COLORS["bg_input"], progress_color=COLORS["accent_green"],
                                        button_color=COLORS["accent_green"], button_hover_color=COLORS["accent_green_hover"])
        self.vol_slider.pack(side="right", fill="x", expand=True, padx=(16, 0))
        self.vol_slider.set(80)

        br_row = ctk.CTkFrame(movie_inner, fg_color="transparent")
        br_row.pack(fill="x")
        br_label_frame = ctk.CTkFrame(br_row, fg_color="transparent", width=140)
        br_label_frame.pack(side="left")
        br_label_frame.pack_propagate(False)
        ctk.CTkLabel(br_label_frame, text="☀️ Brightness", font=("Segoe UI", 13, "bold"), text_color=COLORS["text_primary"]).pack(anchor="w")
        self.br_value_label = ctk.CTkLabel(br_label_frame, text="50%", font=("Consolas", 11), text_color=COLORS["accent_orange"])
        self.br_value_label.pack(anchor="w")

        self.br_slider = ctk.CTkSlider(br_row, from_=0, to=100, command=self._on_br_change,
                                       fg_color=COLORS["bg_input"], progress_color=COLORS["accent_orange"],
                                       button_color=COLORS["accent_orange"], button_hover_color="#ffbf4d")
        self.br_slider.pack(side="right", fill="x", expand=True, padx=(16, 0))
        self.br_slider.set(50)

        self._create_section_label(self.main_scroll, "PROFILE MANAGEMENT")

        profile_card = ModernCard(self.main_scroll)
        profile_card.pack(fill="x", pady=(0, 8))

        profile_inner = ctk.CTkFrame(profile_card, fg_color="transparent")
        profile_inner.pack(fill="x", padx=16, pady=14)

        profile_btns = ctk.CTkFrame(profile_inner, fg_color="transparent")
        profile_btns.pack(fill="x")

        ctk.CTkButton(profile_btns, text="📥  Import", font=("Segoe UI", 12), fg_color=COLORS["bg_elevated"],
                      hover_color=COLORS["border_active"], text_color=COLORS["text_primary"], corner_radius=8,
                      height=38, border_width=1, border_color=COLORS["border_subtle"],
                      command=self.import_profile).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(profile_btns, text="📤  Export", font=("Segoe UI", 12), fg_color=COLORS["bg_elevated"],
                      hover_color=COLORS["border_active"], text_color=COLORS["text_primary"], corner_radius=8,
                      height=38, border_width=1, border_color=COLORS["border_subtle"],
                      command=self.export_profile).pack(side="left", fill="x", expand=True, padx=(6, 0))

        ctk.CTkButton(profile_btns, text="🗑️", font=("Segoe UI Emoji", 14), fg_color=COLORS["bg_elevated"],
                      hover_color="#3a1515", text_color=COLORS["accent_red"], corner_radius=8, width=50,
                      height=38, border_width=1, border_color=COLORS["border_subtle"],
                      command=self.clear_profile).pack(side="left", padx=(6, 0))

        bottom_frame = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"], height=90)
        bottom_frame.pack(fill="x", side="bottom", padx=24, pady=(0, 16))
        bottom_frame.pack_propagate(False)

        ctk.CTkFrame(bottom_frame, fg_color=COLORS["border_subtle"], height=1).pack(fill="x", pady=(0, 12))

        bottom_inner = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        bottom_inner.pack(fill="x")

        self.run_btn = ctk.CTkButton(bottom_inner, text="▶   START ENGINE", font=("Segoe UI", 15, "bold"),
                                     fg_color=COLORS["accent_green"], hover_color=COLORS["accent_green_hover"],
                                     text_color="#000000", corner_radius=12, height=52, command=self.toggle_engine)
        self.run_btn.pack(side="left", fill="x", expand=True)

        self.status_label = ctk.CTkLabel(bottom_inner, text="OFFLINE", font=("Consolas", 11, "bold"),
                                         text_color=COLORS["text_muted"], width=90)
        self.status_label.pack(side="right", padx=(16, 0), pady=14)

    def _create_section_label(self, parent, text):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=(16, 6))
        ctk.CTkLabel(frame, text=text, font=("Segoe UI", 11, "bold"), text_color=COLORS["text_muted"]).pack(anchor="w")

    def _on_vol_change(self, val):
        self.vol_value_label.configure(text=f"{int(val)}%")

    def _on_br_change(self, val):
        self.br_value_label.configure(text=f"{int(val)}%")

    def refresh_action_cards(self):
        for widget in self.actions_container.winfo_children():
            widget.destroy()
        self.action_cards.clear()

        for action in ["Volume Up", "Volume Down", "Play/Pause", "Movie Mode"]:
            btn_id = self.mapping.get(action)
            card = ActionCard(self.actions_container, action, btn_id, on_edit=self.edit_single_action)
            card.pack(fill="x", pady=(0, 8))
            self.action_cards[action] = card

        if not self.mapping:
            ctk.CTkLabel(self.actions_container, text="No mappings yet. Select device + 'Learn All' or edit with ✏️",
                         font=("Segoe UI", 12), text_color=COLORS["text_muted"]).pack(pady=8)

    def edit_single_action(self, action_name):
        if self.is_learning or self.is_editing_single:
            return
        if not self.target_address:
            self.after(0, lambda: self.instruction_label.configure(text="⚠️ Select a device first!", text_color=COLORS["accent_red"]))
            return

        self.is_editing_single = True
        self.current_learning_key = action_name
        if action_name in self.action_cards:
            self.action_cards[action_name].set_editing(True)
        self.after(0, lambda: self.instruction_label.configure(text=f"✏️ Press button for [{action_name}]...", text_color=COLORS["accent_orange"]))
        threading.Thread(target=self._edit_single, daemon=True).start()

    def _edit_single(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._edit_single_task())
        finally:
            loop.close()

    async def _edit_single_task(self):
        action = self.current_learning_key
        try:
            async with BleakClient(self.target_address, timeout=10.0) as client:
                learned = False
                def handler(handle, data):
                    nonlocal learned
                    msg = list(data)
                    if len(msg) >= 6 and msg[3] == 0x1C and self.current_learning_key:
                        self.mapping[self.current_learning_key] = msg[5]
                        learned = True
                        self.current_learning_key = None
                await client.start_notify(NOTIFY_UUID, handler)
                for _ in range(300):
                    if not self.current_learning_key:
                        break
                    await asyncio.sleep(0.1)
                await client.stop_notify(NOTIFY_UUID)

                if learned:
                    with open(self.profile_path, "w") as f:
                        json.dump({"address": self.target_address, "mapping": self.mapping}, f, indent=4)
                    self.after(0, lambda: self.instruction_label.configure(text=f"✅ [{action}] updated!", text_color=COLORS["accent_green"]))
                    self.after(0, self.refresh_action_cards)
                else:
                    self.after(0, lambda: self.instruction_label.configure(text=f"⏰ Timeout for [{action}]", text_color=COLORS["accent_red"]))
        except Exception as e:
            self.after(0, lambda: self.instruction_label.configure(text=f"❌ Error: {e}", text_color=COLORS["accent_red"]))
        finally:
            self.is_editing_single = False
            self.current_learning_key = None
            self.after(0, self.refresh_action_cards)

    def set_pc_volume(self, percentage):
        percentage = max(0, min(100, percentage))
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(percentage / 100.0, None)
            return
        except Exception:
            pass
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            for device in AudioUtilities.GetAllDevices():
                if device.isActive:
                    try:
                        interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                        volume = cast(interface, POINTER(IAudioEndpointVolume))
                        volume.SetMasterVolumeLevelScalar(percentage / 100.0, None)
                        return
                    except Exception:
                        continue
        except Exception:
            pass
        try:
            pyautogui.press('volumemute')
            time.sleep(0.05)
            pyautogui.press('volumemute')
            time.sleep(0.05)
            for _ in range(50):
                pyautogui.press('volumedown')
            for _ in range(int(percentage) // 2):
                pyautogui.press('volumeup')
        except Exception:
            pass

    def load_internal_profile(self):
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r") as f:
                    data = json.load(f)
                    self.target_address = data.get("address")
                    self.mapping = data.get("mapping", {})
                    if self.target_address:
                        self.device_label.configure(text=f"📡 {self.target_address}", text_color=COLORS["accent_green"])
            except Exception:
                pass

    def export_profile(self):
        path = filedialog.asksaveasfilename(defaultextension=".json")
        if path:
            try:
                with open(path, "w") as f:
                    json.dump({"address": self.target_address, "mapping": self.mapping}, f, indent=4)
            except Exception:
                pass

    def import_profile(self):
        path = filedialog.askopenfilename()
        if path:
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                    self.target_address = data.get("address")
                    self.mapping = data.get("mapping", {})
                    if self.target_address:
                        self.device_label.configure(text=f"📡 {self.target_address}", text_color=COLORS["accent_green"])
                    self.refresh_action_cards()
                    self.instruction_label.configure(text="✅ Profile imported!", text_color=COLORS["accent_green"])
            except Exception:
                self.instruction_label.configure(text="❌ Import failed", text_color=COLORS["accent_red"])

    def clear_profile(self):
        if os.path.exists(self.profile_path):
            os.remove(self.profile_path)
        self.target_address = None
        self.mapping = {}
        self.device_label.configure(text="No device selected", text_color=COLORS["text_secondary"])
        self.instruction_label.configure(text="Profile cleared", text_color=COLORS["text_muted"])
        self.refresh_action_cards()

    def start_scan(self):
        self.scan_btn.configure(text="⏳ Scanning...", state="disabled")
        self.device_list.configure(values=["Scanning..."])
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            devices = loop.run_until_complete(BleakScanner.discover(timeout=8.0))
            if devices:
                names = [f"{d.name} ({d.address})" for d in devices if d.name]
                self.after(0, lambda: self.device_list.configure(values=names if names else ["No named devices found"]))
            else:
                self.after(0, lambda: self.device_list.configure(values=["No devices found"]))
        except Exception as e:
            self.after(0, lambda: self.device_list.configure(values=[f"Error: {str(e)[:30]}"]))
        finally:
            loop.close()
            self.after(0, lambda: self.scan_btn.configure(text="🔍  Scan", state="normal"))

    def start_learning(self):
        raw = self.device_list.get()
        if "(" not in raw or ")" not in raw:
            self.instruction_label.configure(text="⚠️ Select a device first!", text_color=COLORS["accent_red"])
            return
        self.target_address = raw.split("(")[1].replace(")", "")
        self.device_label.configure(text=f"📡 {self.target_address}", text_color=COLORS["accent_green"])
        self.is_learning = True
        self.learn_btn.configure(text="⏳ Learning...", state="disabled")
        threading.Thread(target=self._learn, daemon=True).start()

    def _learn(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.learn_task())
        finally:
            loop.close()
            self.is_learning = False
            self.after(0, lambda: self.learn_btn.configure(text="🎓  Learn All", state="normal"))

    async def learn_task(self):
        keys = ["Volume Up", "Volume Down", "Play/Pause", "Movie Mode"]
        try:
            async with BleakClient(self.target_address, timeout=10.0) as client:
                def handler(handle, data):
                    msg = list(data)
                    if len(msg) >= 6 and msg[3] == 0x1C and self.current_learning_key:
                        self.mapping[self.current_learning_key] = msg[5]
                        self.current_learning_key = None
                await client.start_notify(NOTIFY_UUID, handler)
                for k in keys:
                    self.current_learning_key = k
                    self.after(0, lambda key=k: self.instruction_label.configure(text=f"🎓 Press [{key}]...", text_color=COLORS["accent_purple"]))
                    for _ in range(300):
                        if not self.current_learning_key:
                            break
                        await asyncio.sleep(0.1)
                    if self.current_learning_key:
                        self.current_learning_key = None
                await client.stop_notify(NOTIFY_UUID)
            with open(self.profile_path, "w") as f:
                json.dump({"address": self.target_address, "mapping": self.mapping}, f, indent=4)
            self.after(0, lambda: self.instruction_label.configure(text="✅ All saved!", text_color=COLORS["accent_green"]))
            self.after(0, self.refresh_action_cards)
        except Exception as e:
            self.after(0, lambda: self.instruction_label.configure(text=f"❌ {e}", text_color=COLORS["accent_red"]))

    def toggle_engine(self):
        if not self.is_running:
            if not self.target_address:
                self.status_label.configure(text="NO DEVICE", text_color=COLORS["accent_red"])
                return
            if not self.mapping:
                self.status_label.configure(text="NO MAP", text_color=COLORS["accent_red"])
                return
            self.is_running = True
            self.run_btn.configure(text="⏹   STOP ENGINE", fg_color=COLORS["accent_red"], hover_color="#ff5252")
            self.status_label.configure(text="CONNECTING", text_color=COLORS["accent_orange"])
            self.status_dot.configure(text_color=COLORS["accent_orange"])
            threading.Thread(target=self._run, daemon=True).start()
        else:
            self.is_running = False
            self.run_btn.configure(text="▶   START ENGINE", fg_color=COLORS["accent_green"], hover_color=COLORS["accent_green_hover"])
            self.status_label.configure(text="OFFLINE", text_color=COLORS["text_muted"])
            self.status_dot.configure(text_color=COLORS["text_muted"])

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.run_task())
        finally:
            loop.close()

    async def run_task(self):
        try:
            async with BleakClient(self.target_address, timeout=10.0) as client:
                if not client.is_connected:
                    self.after(0, lambda: self.status_label.configure(text="FAILED", text_color=COLORS["accent_red"]))
                    self.after(0, lambda: self.status_dot.configure(text_color=COLORS["accent_red"]))
                    return
                def handler(handle, data):
                    msg = list(data)
                    if len(msg) >= 6 and msg[3] == 0x1C:
                        self.last_id = msg[5]
                        self.last_tap_time = time.time()
                await client.start_notify(NOTIFY_UUID, handler)
                self.after(0, lambda: self.status_label.configure(text="LIVE", text_color=COLORS["accent_green"]))
                self.after(0, lambda: self.status_dot.configure(text_color=COLORS["accent_green"]))
                keepalive = bytearray([0xCD, 0x00, 0x01, 0x01])
                while self.is_running:
                    if self.last_id and (time.time() - self.last_tap_time) > 0.4:
                        self.execute(self.last_id)
                        self.last_id = None
                    try:
                        await client.write_gatt_char(WRITE_UUID, keepalive)
                    except Exception:
                        pass
                    await asyncio.sleep(0.1)
                await client.stop_notify(NOTIFY_UUID)
        except Exception:
            pass
        finally:
            if self.is_running:
                self.is_running = False
                self.after(0, self._reset_engine_ui)

    def _reset_engine_ui(self):
        self.run_btn.configure(text="▶   START ENGINE", fg_color=COLORS["accent_green"], hover_color=COLORS["accent_green_hover"])
        self.status_label.configure(text="OFFLINE", text_color=COLORS["text_muted"])
        self.status_dot.configure(text_color=COLORS["text_muted"])

    def execute(self, btn_id):
        action = next((k for k, v in self.mapping.items() if v == btn_id), None)
        if not action:
            return
        if action == "Movie Mode":
            self.set_pc_volume(self.vol_slider.get())
            try:
                sbc.set_brightness(int(self.br_slider.get()))
            except Exception:
                pass
        elif action == "Volume Up":
            pyautogui.press('volumeup')
        elif action == "Volume Down":
            pyautogui.press('volumedown')
        elif action == "Play/Pause":
            pyautogui.press('playpause')


if __name__ == "__main__":
    app = SynodUniversal()
    app.mainloop()
import asyncio
import threading
import time
import json
import os
import ctypes
import subprocess
from ctypes import cast, POINTER
import pyautogui
import customtkinter as ctk
import screen_brightness_control as sbc
from tkinter import filedialog
from bleak import BleakScanner, BleakClient

# --- Windows media key virtual codes (no extra dependencies needed) ---
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_VOLUME_UP        = 0xAF
VK_VOLUME_DOWN      = 0xAE
VK_VOLUME_MUTE      = 0xAD
KEYEVENTF_KEYUP     = 0x0002

# --- CONFIG ---
WRITE_UUID  = "7e400002-b5a3-f393-e0a9-e50e24dcca9d"
NOTIFY_UUID = "7e400003-b5a3-f393-e0a9-e50e24dcca9d"

COLORS = {
    "bg_dark":           "#0a0a0a",
    "bg_card":           "#141414",
    "bg_card_hover":     "#1a1a1a",
    "bg_input":          "#1e1e1e",
    "bg_elevated":       "#242424",
    "text_primary":      "#ffffff",
    "text_secondary":    "#a7a7a7",
    "text_muted":        "#535353",
    "accent_green":      "#1ed760",
    "accent_green_hover":"#1fdf64",
    "accent_blue":       "#0a84ff",
    "accent_purple":     "#b44dff",
    "accent_red":        "#ff3b30",
    "accent_orange":     "#ff9f0a",
    "accent_cyan":       "#64d2ff",
    "border_subtle":     "#282828",
    "border_active":     "#3a3a3a",
}

ACTION_TYPES = ["Key Press", "Hotkey (Combo)", "Launch App"]


def _send_vk(vk_code):
    """Send a Windows virtual key press + release."""
    ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)


class ModernCard(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=COLORS["bg_card"], corner_radius=12,
                         border_width=1, border_color=COLORS["border_subtle"], **kwargs)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _on_enter(self, event):
        self.configure(border_color=COLORS["border_active"], fg_color=COLORS["bg_card_hover"])

    def _on_leave(self, event):
        self.configure(border_color=COLORS["border_subtle"], fg_color=COLORS["bg_card"])


class ActionCard(ctk.CTkFrame):
    def __init__(self, master, action_name, btn_id, on_edit, **kwargs):
        self.action_name = action_name
        self.btn_id      = btn_id
        self.on_edit     = on_edit
        self.is_editing  = False

        super().__init__(master, fg_color=COLORS["bg_elevated"], corner_radius=10,
                         border_width=1, border_color=COLORS["border_subtle"],
                         cursor="hand2", height=70, **kwargs)
        self.grid_columnconfigure((0, 1, 2), weight=1)

        icon_frame = ctk.CTkFrame(self, fg_color="transparent", width=50)
        icon_frame.grid(row=0, column=0, padx=(12, 0), pady=12, sticky="w")
        ctk.CTkLabel(icon_frame, text=self._get_icon(), font=("Segoe UI Emoji", 22)).pack()

        text_frame = ctk.CTkFrame(self, fg_color="transparent")
        text_frame.grid(row=0, column=1, padx=8, pady=12, sticky="w")
        ctk.CTkLabel(text_frame, text=action_name, font=("Segoe UI", 14, "bold"),
                     text_color=COLORS["text_primary"]).pack(anchor="w")
        self.id_label = ctk.CTkLabel(text_frame, text=self._get_id_text(),
                                     font=("Consolas", 11), text_color=COLORS["text_muted"])
        self.id_label.pack(anchor="w")

        self.edit_btn = ctk.CTkButton(
            self, text="✏️", width=36, height=36,
            fg_color=COLORS["bg_input"], hover_color=COLORS["accent_blue"],
            text_color=COLORS["text_secondary"], font=("Segoe UI Emoji", 14),
            corner_radius=8, border_width=1, border_color=COLORS["border_subtle"],
            command=lambda: self.on_edit(action_name)
        )
        self.edit_btn.grid(row=0, column=2, padx=(0, 12), pady=17, sticky="e")

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _get_icon(self):
        icons = {
            "Volume Up":   "🔊",
            "Volume Down": "🔉",
            "Play/Pause":  "⏯️",
            "Movie Mode":  "🎬",
        }
        return icons.get(self.action_name, "🔘")

    def _get_id_text(self):
        return f"ID: 0x{self.btn_id:02X}" if self.btn_id is not None else "Not assigned"

    def _on_enter(self, event):
        self.configure(border_color=COLORS["accent_green"], fg_color="#1e1e1e")
        self.edit_btn.configure(fg_color=COLORS["accent_blue"], text_color="white")

    def _on_leave(self, event):
        if not self.is_editing:
            self.configure(border_color=COLORS["border_subtle"], fg_color=COLORS["bg_elevated"])
            self.edit_btn.configure(fg_color=COLORS["bg_input"], text_color=COLORS["text_secondary"])

    def set_editing(self, editing):
        self.is_editing = editing
        if editing:
            self.configure(border_color=COLORS["accent_orange"], fg_color="#2a1a00")
            self.edit_btn.configure(text="⏳", fg_color=COLORS["accent_orange"])
        else:
            self.configure(border_color=COLORS["border_subtle"], fg_color=COLORS["bg_elevated"])
            self.edit_btn.configure(text="✏️", fg_color=COLORS["bg_input"],
                                    text_color=COLORS["text_secondary"])

    def update_btn_id(self, btn_id):
        self.btn_id = btn_id
        self.id_label.configure(text=self._get_id_text())


# ---------------------------------------------------------------------------
# Advanced window — lets the user add custom BLE-button actions
# ---------------------------------------------------------------------------
class AdvancedWindow(ctk.CTkToplevel):
    def __init__(self, master, app_ref):
        super().__init__(master)
        self.app   = app_ref
        self.title("Advanced Actions")
        self.geometry("620x640")
        self.minsize(620, 400)
        self.configure(fg_color=COLORS["bg_dark"])
        self.grab_set()

        self._editing_custom_key = None  # action name being learned
        self._learning = False

        self._build_ui()
        self._refresh_list()

    # ------------------------------------------------------------------ UI --
    def _build_ui(self):
        # Header
        hdr = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"], height=60)
        hdr.pack(fill="x", padx=20, pady=(16, 0))
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="⚙️  Advanced Actions", font=("Segoe UI", 18, "bold"),
                     text_color=COLORS["text_primary"]).pack(side="left")
        ctk.CTkLabel(hdr, text="Assign custom PC actions to BLE buttons",
                     font=("Segoe UI", 11), text_color=COLORS["text_muted"]).pack(side="left", padx=(12, 0))

        # Instruction label (shows learn feedback)
        self.info_label = ctk.CTkLabel(self, text="", font=("Segoe UI", 12),
                                       text_color=COLORS["text_muted"])
        self.info_label.pack(anchor="w", padx=20, pady=(6, 0))

        # Scrollable list of custom actions
        self.list_frame = ctk.CTkScrollableFrame(self, fg_color=COLORS["bg_dark"])
        self.list_frame.pack(fill="both", expand=True, padx=20, pady=(8, 0))

        # ── Add-new form ──────────────────────────────────────────────────
        add_card = ctk.CTkFrame(self, fg_color=COLORS["bg_card"], corner_radius=12,
                                border_width=1, border_color=COLORS["border_subtle"])
        add_card.pack(fill="x", padx=20, pady=16)

        form = ctk.CTkFrame(add_card, fg_color="transparent")
        form.pack(fill="x", padx=14, pady=14)

        # Row 1 — name + type
        row1 = ctk.CTkFrame(form, fg_color="transparent")
        row1.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(row1, text="Name", font=("Segoe UI", 12),
                     text_color=COLORS["text_secondary"], width=44).pack(side="left")
        self.name_entry = ctk.CTkEntry(row1, placeholder_text="e.g. Open Spotify",
                                       font=("Segoe UI", 12),
                                       fg_color=COLORS["bg_input"],
                                       text_color=COLORS["text_primary"],
                                       border_color=COLORS["border_subtle"],
                                       corner_radius=8)
        self.name_entry.pack(side="left", fill="x", expand=True, padx=(8, 12))

        ctk.CTkLabel(row1, text="Type", font=("Segoe UI", 12),
                     text_color=COLORS["text_secondary"], width=36).pack(side="left")
        self.type_menu = ctk.CTkOptionMenu(row1, values=ACTION_TYPES,
                                           font=("Segoe UI", 12),
                                           fg_color=COLORS["bg_input"],
                                           button_color=COLORS["bg_elevated"],
                                           button_hover_color=COLORS["border_active"],
                                           dropdown_fg_color=COLORS["bg_elevated"],
                                           text_color=COLORS["text_primary"],
                                           corner_radius=8,
                                           command=self._on_type_change)
        self.type_menu.pack(side="left", padx=(8, 0))

        # Row 2 — value (key / combo / path)
        row2 = ctk.CTkFrame(form, fg_color="transparent")
        row2.pack(fill="x", pady=(0, 10))

        self.value_hint = ctk.CTkLabel(row2, text="Key", font=("Segoe UI", 12),
                                       text_color=COLORS["text_secondary"], width=44)
        self.value_hint.pack(side="left")
        self.value_entry = ctk.CTkEntry(row2,
                                        placeholder_text="e.g.  f5  or  ctrl+shift+n  or  C:\\path\\app.exe",
                                        font=("Segoe UI", 12),
                                        fg_color=COLORS["bg_input"],
                                        text_color=COLORS["text_primary"],
                                        border_color=COLORS["border_subtle"],
                                        corner_radius=8)
        self.value_entry.pack(side="left", fill="x", expand=True, padx=(8, 12))

        self.browse_btn = ctk.CTkButton(row2, text="Browse", width=74,
                                        font=("Segoe UI", 12),
                                        fg_color=COLORS["bg_elevated"],
                                        hover_color=COLORS["border_active"],
                                        text_color=COLORS["text_secondary"],
                                        corner_radius=8, height=34,
                                        command=self._browse_app)
        self.browse_btn.pack(side="left")
        self.browse_btn.pack_forget()  # hidden until "Launch App" selected

        # Add button
        ctk.CTkButton(form, text="＋  Add Action", font=("Segoe UI", 13, "bold"),
                      fg_color=COLORS["accent_green"], hover_color=COLORS["accent_green_hover"],
                      text_color="#000000", corner_radius=8, height=38,
                      command=self._add_action).pack(fill="x")

    def _on_type_change(self, val):
        hints = {
            "Key Press":       ("Key",   "e.g.  f5  or  enter  or  space"),
            "Hotkey (Combo)":  ("Combo", "e.g.  ctrl+c  or  alt+tab  or  win+d"),
            "Launch App":      ("Path",  "e.g.  C:\\Program Files\\Spotify\\Spotify.exe"),
        }
        hint_text, placeholder = hints.get(val, ("Value", ""))
        self.value_hint.configure(text=hint_text)
        self.value_entry.configure(placeholder_text=placeholder)
        if val == "Launch App":
            self.browse_btn.pack(side="left")
        else:
            self.browse_btn.pack_forget()

    def _browse_app(self):
        path = filedialog.askopenfilename(filetypes=[("Executables", "*.exe"), ("All files", "*.*")])
        if path:
            self.value_entry.delete(0, "end")
            self.value_entry.insert(0, path)

    # ----------------------------------------------------- list refresh -----
    def _refresh_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()

        custom = self.app.custom_actions
        if not custom:
            ctk.CTkLabel(self.list_frame,
                         text="No custom actions yet. Add one below.",
                         font=("Segoe UI", 12), text_color=COLORS["text_muted"]).pack(pady=12)
            return

        for name, info in list(custom.items()):
            self._make_row(name, info)

    def _make_row(self, name, info):
        row = ctk.CTkFrame(self.list_frame, fg_color=COLORS["bg_elevated"],
                           corner_radius=10, border_width=1,
                           border_color=COLORS["border_subtle"])
        row.pack(fill="x", pady=(0, 6))
        row.grid_columnconfigure(1, weight=1)

        # icon / name
        ctk.CTkLabel(row, text="🔘", font=("Segoe UI Emoji", 18)).grid(
            row=0, column=0, padx=(12, 8), pady=10)

        details = ctk.CTkFrame(row, fg_color="transparent")
        details.grid(row=0, column=1, sticky="w", pady=10)
        ctk.CTkLabel(details, text=name, font=("Segoe UI", 13, "bold"),
                     text_color=COLORS["text_primary"]).pack(anchor="w")
        btn_id = info.get("btn_id")
        id_txt = f"ID: 0x{btn_id:02X}" if btn_id is not None else "Not assigned"
        type_str = info.get("type", "?")
        val_str  = info.get("value", "")
        ctk.CTkLabel(details, text=f"{type_str}  ·  {val_str}  ·  {id_txt}",
                     font=("Consolas", 11), text_color=COLORS["text_muted"]).pack(anchor="w")

        btn_frame = ctk.CTkFrame(row, fg_color="transparent")
        btn_frame.grid(row=0, column=2, padx=10, pady=10)

        ctk.CTkButton(btn_frame, text="📡", width=36, height=34,
                      font=("Segoe UI Emoji", 14),
                      fg_color=COLORS["bg_input"],
                      hover_color=COLORS["accent_purple"],
                      text_color=COLORS["text_secondary"],
                      corner_radius=8,
                      command=lambda n=name: self._learn_for(n)).pack(side="left", padx=(0, 6))

        ctk.CTkButton(btn_frame, text="🗑️", width=36, height=34,
                      font=("Segoe UI Emoji", 14),
                      fg_color=COLORS["bg_input"],
                      hover_color="#3a1515",
                      text_color=COLORS["accent_red"],
                      corner_radius=8,
                      command=lambda n=name: self._delete_action(n)).pack(side="left")

    # --------------------------------------------------- add / delete -------
    def _add_action(self):
        name  = self.name_entry.get().strip()
        atype = self.type_menu.get()
        value = self.value_entry.get().strip()

        if not name:
            self.info_label.configure(text="⚠️ Please enter a name.", text_color=COLORS["accent_red"])
            return
        if not value:
            self.info_label.configure(text="⚠️ Please enter a value/path.", text_color=COLORS["accent_red"])
            return
        if name in self.app.custom_actions:
            self.info_label.configure(text=f"⚠️ '{name}' already exists.", text_color=COLORS["accent_red"])
            return

        self.app.custom_actions[name] = {"type": atype, "value": value, "btn_id": None}
        self.app._save_profile()
        self.name_entry.delete(0, "end")
        self.value_entry.delete(0, "end")
        self.info_label.configure(
            text=f"✅ '{name}' added. Click 📡 to assign a BLE button.",
            text_color=COLORS["accent_green"])
        self._refresh_list()

    def _delete_action(self, name):
        self.app.custom_actions.pop(name, None)
        self.app._save_profile()
        self._refresh_list()
        self.info_label.configure(text=f"🗑️ '{name}' deleted.", text_color=COLORS["text_muted"])

    # ----------------------------------------------- BLE button learn ------
    def _learn_for(self, action_name):
        if self._learning:
            return
        if not self.app.target_address:
            self.info_label.configure(text="⚠️ Connect a device first!",
                                      text_color=COLORS["accent_red"])
            return
        self._learning = True
        self._editing_custom_key = action_name
        self.info_label.configure(
            text=f"📡 Press the BLE button for [{action_name}]...",
            text_color=COLORS["accent_purple"])
        threading.Thread(target=self._do_learn, daemon=True).start()

    def _do_learn(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._learn_task())
        finally:
            loop.close()
            self._learning = False

    async def _learn_task(self):
        target  = self.app.target_address
        learned = False
        try:
            async with BleakClient(target, timeout=10.0) as client:
                def handler(handle, data):
                    nonlocal learned
                    msg = list(data)
                    if len(msg) >= 6 and msg[3] == 0x1C and self._editing_custom_key:
                        btn_id = msg[5]
                        name   = self._editing_custom_key
                        if name in self.app.custom_actions:
                            self.app.custom_actions[name]["btn_id"] = btn_id
                        learned = True
                        self._editing_custom_key = None
                await client.start_notify(NOTIFY_UUID, handler)
                for _ in range(300):
                    if not self._editing_custom_key:
                        break
                    await asyncio.sleep(0.1)
                await client.stop_notify(NOTIFY_UUID)

            if learned:
                self.app._save_profile()
                self.after(0, self._refresh_list)
                self.after(0, lambda: self.info_label.configure(
                    text="✅ Button assigned!", text_color=COLORS["accent_green"]))
            else:
                self.after(0, lambda: self.info_label.configure(
                    text="⏰ Timed out — no button pressed.", text_color=COLORS["accent_red"]))
        except Exception as e:
            self.after(0, lambda: self.info_label.configure(
                text=f"❌ Error: {e}", text_color=COLORS["accent_red"]))
        finally:
            self._editing_custom_key = None


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class SynodUniversal(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("SYNOD UNIVERSAL")
        self.geometry("680x860")
        self.minsize(680, 820)
        self.configure(fg_color=COLORS["bg_dark"])

        self.target_address       = None
        self.mapping              = {}
        self.custom_actions       = {}   # name → {type, value, btn_id}
        self.is_running           = False
        self.is_learning          = False
        self.is_editing_single    = False
        self.current_learning_key = None
        self.profile_path         = "synod_profile.json"
        self.last_id              = None
        self.last_tap_time        = 0
        self.action_cards         = {}

        # Movie mode state
        self.movie_mode_active    = False
        self.pre_movie_volume     = None   # volume level before movie mode
        self.pre_movie_brightness = None   # brightness before movie mode

        self.setup_ui()
        self.load_internal_profile()
        self.refresh_action_cards()

    # ====================================================================
    # UI
    # ====================================================================
    def setup_ui(self):
        header = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"], height=80)
        header.pack(fill="x", padx=24, pady=(20, 0))
        header.pack_propagate(False)

        logo_frame = ctk.CTkFrame(header, fg_color="transparent")
        logo_frame.pack(side="left")

        self.status_dot = ctk.CTkLabel(logo_frame, text="●", font=("Segoe UI", 28),
                                       text_color=COLORS["text_muted"])
        self.status_dot.pack(side="left", padx=(0, 12))

        title_frame = ctk.CTkFrame(logo_frame, fg_color="transparent")
        title_frame.pack(side="left")
        ctk.CTkLabel(title_frame, text="SYNOD", font=("Segoe UI", 24, "bold"),
                     text_color=COLORS["text_primary"]).pack(anchor="w")
        ctk.CTkLabel(title_frame, text="UNIVERSAL  v16.8", font=("Segoe UI", 11),
                     text_color=COLORS["text_muted"]).pack(anchor="w")

        ctk.CTkLabel(header, text=" BT LE ", font=("Consolas", 10, "bold"),
                     text_color=COLORS["accent_cyan"],
                     fg_color="#0a2a3a", corner_radius=6).pack(side="right", pady=20)

        self.main_scroll = ctk.CTkScrollableFrame(self, fg_color=COLORS["bg_dark"])
        self.main_scroll.pack(fill="both", expand=True, padx=24, pady=16)

        # ── Device ──────────────────────────────────────────────────────
        self._create_section_label(self.main_scroll, "DEVICE CONNECTION")

        device_card = ModernCard(self.main_scroll)
        device_card.pack(fill="x", pady=(0, 8))
        device_inner = ctk.CTkFrame(device_card, fg_color="transparent")
        device_inner.pack(fill="x", padx=16, pady=14)

        self.device_label = ctk.CTkLabel(device_inner, text="No device selected",
                                         font=("Segoe UI", 13),
                                         text_color=COLORS["text_secondary"])
        self.device_label.pack(anchor="w")

        self.device_list = ctk.CTkOptionMenu(
            device_inner,
            values=["— Scan to discover —"],
            font=("Segoe UI", 12),
            fg_color=COLORS["bg_input"],
            button_color=COLORS["bg_input"],
            button_hover_color=COLORS["bg_elevated"],
            dropdown_fg_color=COLORS["bg_elevated"],
            text_color=COLORS["text_primary"],
            corner_radius=8,
        )
        self.device_list.pack(fill="x", pady=(10, 0))

        btn_row = ctk.CTkFrame(device_inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(12, 0))

        self.scan_btn = ctk.CTkButton(btn_row, text="🔍  Scan",
                                      font=("Segoe UI", 12, "bold"),
                                      fg_color=COLORS["accent_blue"], hover_color="#3a9fff",
                                      text_color="white", corner_radius=8, height=38,
                                      command=self.start_scan)
        self.scan_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.learn_btn = ctk.CTkButton(btn_row, text="🎓  Learn All",
                                       font=("Segoe UI", 12, "bold"),
                                       fg_color=COLORS["accent_purple"], hover_color="#c46bff",
                                       text_color="white", corner_radius=8, height=38,
                                       command=self.start_learning)
        self.learn_btn.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.instruction_label = ctk.CTkLabel(device_inner, text="",
                                              font=("Segoe UI", 12),
                                              text_color=COLORS["text_muted"])
        self.instruction_label.pack(anchor="w", pady=(10, 0))

        # ── Action mappings ─────────────────────────────────────────────
        self._create_section_label(self.main_scroll, "ACTION MAPPINGS")

        self.actions_card = ModernCard(self.main_scroll)
        self.actions_card.pack(fill="x", pady=(0, 8))
        self.actions_container = ctk.CTkFrame(self.actions_card, fg_color="transparent")
        self.actions_container.pack(fill="x", padx=12, pady=12)

        # ── Movie mode presets ───────────────────────────────────────────
        self._create_section_label(self.main_scroll, "MOVIE MODE PRESETS")

        movie_card = ModernCard(self.main_scroll)
        movie_card.pack(fill="x", pady=(0, 8))
        movie_inner = ctk.CTkFrame(movie_card, fg_color="transparent")
        movie_inner.pack(fill="x", padx=16, pady=16)

        # Volume row
        vol_row = ctk.CTkFrame(movie_inner, fg_color="transparent")
        vol_row.pack(fill="x", pady=(0, 12))
        vol_lf = ctk.CTkFrame(vol_row, fg_color="transparent", width=140)
        vol_lf.pack(side="left")
        vol_lf.pack_propagate(False)
        ctk.CTkLabel(vol_lf, text="🔊 Volume", font=("Segoe UI", 13, "bold"),
                     text_color=COLORS["text_primary"]).pack(anchor="w")
        self.vol_value_label = ctk.CTkLabel(vol_lf, text="80%", font=("Consolas", 11),
                                            text_color=COLORS["accent_green"])
        self.vol_value_label.pack(anchor="w")
        self.vol_slider = ctk.CTkSlider(vol_row, from_=0, to=100,
                                        command=self._on_vol_change,
                                        fg_color=COLORS["bg_input"],
                                        progress_color=COLORS["accent_green"],
                                        button_color=COLORS["accent_green"],
                                        button_hover_color=COLORS["accent_green_hover"])
        self.vol_slider.pack(side="right", fill="x", expand=True, padx=(16, 0))
        self.vol_slider.set(80)

        # Brightness row
        br_row = ctk.CTkFrame(movie_inner, fg_color="transparent")
        br_row.pack(fill="x")
        br_lf = ctk.CTkFrame(br_row, fg_color="transparent", width=140)
        br_lf.pack(side="left")
        br_lf.pack_propagate(False)
        ctk.CTkLabel(br_lf, text="☀️ Brightness", font=("Segoe UI", 13, "bold"),
                     text_color=COLORS["text_primary"]).pack(anchor="w")
        self.br_value_label = ctk.CTkLabel(br_lf, text="50%", font=("Consolas", 11),
                                           text_color=COLORS["accent_orange"])
        self.br_value_label.pack(anchor="w")
        self.br_slider = ctk.CTkSlider(br_row, from_=0, to=100,
                                       command=self._on_br_change,
                                       fg_color=COLORS["bg_input"],
                                       progress_color=COLORS["accent_orange"],
                                       button_color=COLORS["accent_orange"],
                                       button_hover_color="#ffbf4d")
        self.br_slider.pack(side="right", fill="x", expand=True, padx=(16, 0))
        self.br_slider.set(50)

        # ── Profile management ──────────────────────────────────────────
        self._create_section_label(self.main_scroll, "PROFILE MANAGEMENT")

        profile_card = ModernCard(self.main_scroll)
        profile_card.pack(fill="x", pady=(0, 8))
        profile_inner = ctk.CTkFrame(profile_card, fg_color="transparent")
        profile_inner.pack(fill="x", padx=16, pady=14)
        profile_btns = ctk.CTkFrame(profile_inner, fg_color="transparent")
        profile_btns.pack(fill="x")

        ctk.CTkButton(profile_btns, text="📥  Import", font=("Segoe UI", 12),
                      fg_color=COLORS["bg_elevated"], hover_color=COLORS["border_active"],
                      text_color=COLORS["text_primary"], corner_radius=8, height=38,
                      border_width=1, border_color=COLORS["border_subtle"],
                      command=self.import_profile).pack(side="left", fill="x", expand=True, padx=(0, 6))

        ctk.CTkButton(profile_btns, text="📤  Export", font=("Segoe UI", 12),
                      fg_color=COLORS["bg_elevated"], hover_color=COLORS["border_active"],
                      text_color=COLORS["text_primary"], corner_radius=8, height=38,
                      border_width=1, border_color=COLORS["border_subtle"],
                      command=self.export_profile).pack(side="left", fill="x", expand=True, padx=(6, 6))

        ctk.CTkButton(profile_btns, text="🗑️", font=("Segoe UI Emoji", 14),
                      fg_color=COLORS["bg_elevated"], hover_color="#3a1515",
                      text_color=COLORS["accent_red"], corner_radius=8,
                      width=50, height=38, border_width=1, border_color=COLORS["border_subtle"],
                      command=self.clear_profile).pack(side="left")

        # ── Advanced section ────────────────────────────────────────────
        self._create_section_label(self.main_scroll, "ADVANCED")

        adv_card = ModernCard(self.main_scroll)
        adv_card.pack(fill="x", pady=(0, 20))
        adv_inner = ctk.CTkFrame(adv_card, fg_color="transparent")
        adv_inner.pack(fill="x", padx=16, pady=14)

        adv_desc = ctk.CTkLabel(adv_inner,
                                text="Create custom actions — key presses, hotkeys, or app launches — and assign them to any BLE button.",
                                font=("Segoe UI", 12), text_color=COLORS["text_muted"],
                                wraplength=560, justify="left")
        adv_desc.pack(anchor="w", pady=(0, 10))

        ctk.CTkButton(adv_inner, text="⚙️  Open Advanced Actions",
                      font=("Segoe UI", 13, "bold"),
                      fg_color=COLORS["bg_elevated"],
                      hover_color=COLORS["border_active"],
                      text_color=COLORS["text_primary"],
                      corner_radius=8, height=42,
                      border_width=1, border_color=COLORS["accent_purple"],
                      command=self.open_advanced).pack(fill="x")

        # ── Bottom bar ───────────────────────────────────────────────────
        bottom_frame = ctk.CTkFrame(self, fg_color=COLORS["bg_dark"], height=90)
        bottom_frame.pack(fill="x", side="bottom", padx=24, pady=(0, 16))
        bottom_frame.pack_propagate(False)

        ctk.CTkFrame(bottom_frame, fg_color=COLORS["border_subtle"],
                     height=1).pack(fill="x", pady=(0, 12))

        bottom_inner = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        bottom_inner.pack(fill="x")

        self.run_btn = ctk.CTkButton(bottom_inner, text="▶   START ENGINE",
                                     font=("Segoe UI", 15, "bold"),
                                     fg_color=COLORS["accent_green"],
                                     hover_color=COLORS["accent_green_hover"],
                                     text_color="#000000", corner_radius=12, height=52,
                                     command=self.toggle_engine)
        self.run_btn.pack(side="left", fill="x", expand=True)

        self.status_label = ctk.CTkLabel(bottom_inner, text="OFFLINE",
                                         font=("Consolas", 11, "bold"),
                                         text_color=COLORS["text_muted"], width=90)
        self.status_label.pack(side="right", padx=(16, 0), pady=14)

    def _create_section_label(self, parent, text):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", pady=(16, 6))
        ctk.CTkLabel(frame, text=text, font=("Segoe UI", 11, "bold"),
                     text_color=COLORS["text_muted"]).pack(anchor="w")

    def _on_vol_change(self, val):
        self.vol_value_label.configure(text=f"{int(val)}%")

    def _on_br_change(self, val):
        self.br_value_label.configure(text=f"{int(val)}%")

    def open_advanced(self):
        AdvancedWindow(self, self)

    # ====================================================================
    # Volume helpers — use pycaw for direct absolute setting (no key spam)
    # ====================================================================
    def get_pc_volume(self):
        """Return current master volume as 0-100 float, or None on failure."""
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            devices   = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume    = cast(interface, POINTER(IAudioEndpointVolume))
            return volume.GetMasterVolumeLevelScalar() * 100.0
        except Exception:
            return None

    def set_pc_volume(self, percentage):
        """Set master volume to an absolute percentage (0-100) instantly."""
        percentage = max(0, min(100, percentage))
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            devices   = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume    = cast(interface, POINTER(IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(percentage / 100.0, None)
            return True
        except Exception:
            pass
        # Fallback — PowerShell (slower but no key spam, still absolute)
        try:
            script = (
                f"$vol = {int(percentage)};"
                "$obj = New-Object -ComObject WScript.Shell;"
                "Add-Type -AssemblyName System.Windows.Forms;"
                # set via nircmd if available, otherwise no-op
                "# no-op fallback"
            )
            # Try nircmd if user has it
            subprocess.run(
                ["nircmd.exe", "setsysvolume", str(int(percentage / 100.0 * 65535))],
                timeout=2, capture_output=True)
            return True
        except Exception:
            pass
        return False

    # ====================================================================
    # Play/Pause — Windows virtual key code (works system-wide reliably)
    # ====================================================================
    def press_play_pause(self):
        _send_vk(VK_MEDIA_PLAY_PAUSE)

    def press_volume_up(self):
        _send_vk(VK_VOLUME_UP)

    def press_volume_down(self):
        _send_vk(VK_VOLUME_DOWN)

    # ====================================================================
    # Profile I/O
    # ====================================================================
    def _save_profile(self):
        try:
            with open(self.profile_path, "w") as f:
                json.dump({
                    "address":        self.target_address,
                    "mapping":        self.mapping,
                    "custom_actions": self.custom_actions,
                }, f, indent=4)
        except Exception:
            pass

    def load_internal_profile(self):
        if os.path.exists(self.profile_path):
            try:
                with open(self.profile_path, "r") as f:
                    data = json.load(f)
                self.target_address = data.get("address")
                self.mapping        = data.get("mapping", {})
                self.custom_actions = data.get("custom_actions", {})
                if self.target_address:
                    self.device_label.configure(text=f"📡 {self.target_address}",
                                                text_color=COLORS["accent_green"])
            except Exception:
                pass

    def export_profile(self):
        path = filedialog.asksaveasfilename(defaultextension=".json")
        if path:
            try:
                with open(path, "w") as f:
                    json.dump({
                        "address":        self.target_address,
                        "mapping":        self.mapping,
                        "custom_actions": self.custom_actions,
                    }, f, indent=4)
            except Exception:
                pass

    def import_profile(self):
        path = filedialog.askopenfilename()
        if path:
            try:
                with open(path, "r") as f:
                    data = json.load(f)
                self.target_address = data.get("address")
                self.mapping        = data.get("mapping", {})
                self.custom_actions = data.get("custom_actions", {})
                if self.target_address:
                    self.device_label.configure(text=f"📡 {self.target_address}",
                                                text_color=COLORS["accent_green"])
                self.refresh_action_cards()
                self.instruction_label.configure(text="✅ Profile imported!",
                                                 text_color=COLORS["accent_green"])
            except Exception:
                self.instruction_label.configure(text="❌ Import failed",
                                                 text_color=COLORS["accent_red"])

    def clear_profile(self):
        if os.path.exists(self.profile_path):
            os.remove(self.profile_path)
        self.target_address  = None
        self.mapping         = {}
        self.custom_actions  = {}
        self.movie_mode_active   = False
        self.pre_movie_volume    = None
        self.pre_movie_brightness = None
        self.device_label.configure(text="No device selected",
                                    text_color=COLORS["text_secondary"])
        self.instruction_label.configure(text="Profile cleared",
                                         text_color=COLORS["text_muted"])
        self.refresh_action_cards()

    # ====================================================================
    # Action cards
    # ====================================================================
    def refresh_action_cards(self):
        for widget in self.actions_container.winfo_children():
            widget.destroy()
        self.action_cards.clear()

        for action in ["Volume Up", "Volume Down", "Play/Pause", "Movie Mode"]:
            btn_id = self.mapping.get(action)
            card = ActionCard(self.actions_container, action, btn_id,
                              on_edit=self.edit_single_action)
            card.pack(fill="x", pady=(0, 8))
            self.action_cards[action] = card

        if not self.mapping:
            ctk.CTkLabel(self.actions_container,
                         text="No mappings yet. Select device + 'Learn All' or edit with ✏️",
                         font=("Segoe UI", 12),
                         text_color=COLORS["text_muted"]).pack(pady=8)

    # ====================================================================
    # Single-action learn
    # ====================================================================
    def edit_single_action(self, action_name):
        if self.is_learning or self.is_editing_single:
            return
        if not self.target_address:
            self.after(0, lambda: self.instruction_label.configure(
                text="⚠️ Select a device first!", text_color=COLORS["accent_red"]))
            return
        self.is_editing_single    = True
        self.current_learning_key = action_name
        if action_name in self.action_cards:
            self.action_cards[action_name].set_editing(True)
        self.after(0, lambda: self.instruction_label.configure(
            text=f"✏️ Press button for [{action_name}]...",
            text_color=COLORS["accent_orange"]))
        threading.Thread(target=self._edit_single, daemon=True).start()

    def _edit_single(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._edit_single_task())
        finally:
            loop.close()

    async def _edit_single_task(self):
        action = self.current_learning_key
        try:
            async with BleakClient(self.target_address, timeout=10.0) as client:
                learned = False
                def handler(handle, data):
                    nonlocal learned
                    msg = list(data)
                    if len(msg) >= 6 and msg[3] == 0x1C and self.current_learning_key:
                        self.mapping[self.current_learning_key] = msg[5]
                        learned = True
                        self.current_learning_key = None
                await client.start_notify(NOTIFY_UUID, handler)
                for _ in range(300):
                    if not self.current_learning_key:
                        break
                    await asyncio.sleep(0.1)
                await client.stop_notify(NOTIFY_UUID)

                if learned:
                    self._save_profile()
                    self.after(0, lambda: self.instruction_label.configure(
                        text=f"✅ [{action}] updated!", text_color=COLORS["accent_green"]))
                    self.after(0, self.refresh_action_cards)
                else:
                    self.after(0, lambda: self.instruction_label.configure(
                        text=f"⏰ Timeout for [{action}]", text_color=COLORS["accent_red"]))
        except Exception as e:
            self.after(0, lambda: self.instruction_label.configure(
                text=f"❌ Error: {e}", text_color=COLORS["accent_red"]))
        finally:
            self.is_editing_single    = False
            self.current_learning_key = None
            self.after(0, self.refresh_action_cards)

    # ====================================================================
    # Scan
    # ====================================================================
    def start_scan(self):
        self.scan_btn.configure(text="⏳ Scanning...", state="disabled")
        self.device_list.configure(values=["Scanning..."])
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            devices = loop.run_until_complete(BleakScanner.discover(timeout=8.0))
            if devices:
                names = [f"{d.name} ({d.address})" for d in devices if d.name]
                self.after(0, lambda: self.device_list.configure(
                    values=names if names else ["No named devices found"]))
            else:
                self.after(0, lambda: self.device_list.configure(values=["No devices found"]))
        except Exception as e:
            self.after(0, lambda: self.device_list.configure(
                values=[f"Error: {str(e)[:30]}"]))
        finally:
            loop.close()
            self.after(0, lambda: self.scan_btn.configure(text="🔍  Scan", state="normal"))

    # ====================================================================
    # Learn all
    # ====================================================================
    def start_learning(self):
        raw = self.device_list.get()
        if "(" not in raw or ")" not in raw:
            self.instruction_label.configure(text="⚠️ Select a device first!",
                                             text_color=COLORS["accent_red"])
            return
        self.target_address = raw.split("(")[1].replace(")", "")
        self.device_label.configure(text=f"📡 {self.target_address}",
                                    text_color=COLORS["accent_green"])
        self.is_learning = True
        self.learn_btn.configure(text="⏳ Learning...", state="disabled")
        threading.Thread(target=self._learn, daemon=True).start()

    def _learn(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.learn_task())
        finally:
            loop.close()
            self.is_learning = False
            self.after(0, lambda: self.learn_btn.configure(text="🎓  Learn All", state="normal"))

    async def learn_task(self):
        keys = ["Volume Up", "Volume Down", "Play/Pause", "Movie Mode"]
        try:
            async with BleakClient(self.target_address, timeout=10.0) as client:
                def handler(handle, data):
                    msg = list(data)
                    if len(msg) >= 6 and msg[3] == 0x1C and self.current_learning_key:
                        self.mapping[self.current_learning_key] = msg[5]
                        self.current_learning_key = None
                await client.start_notify(NOTIFY_UUID, handler)
                for k in keys:
                    self.current_learning_key = k
                    self.after(0, lambda key=k: self.instruction_label.configure(
                        text=f"🎓 Press [{key}]...", text_color=COLORS["accent_purple"]))
                    for _ in range(300):
                        if not self.current_learning_key:
                            break
                        await asyncio.sleep(0.1)
                    if self.current_learning_key:
                        self.current_learning_key = None
                await client.stop_notify(NOTIFY_UUID)
            self._save_profile()
            self.after(0, lambda: self.instruction_label.configure(
                text="✅ All saved!", text_color=COLORS["accent_green"]))
            self.after(0, self.refresh_action_cards)
        except Exception as e:
            self.after(0, lambda: self.instruction_label.configure(
                text=f"❌ {e}", text_color=COLORS["accent_red"]))

    # ====================================================================
    # Engine
    # ====================================================================
    def toggle_engine(self):
        if not self.is_running:
            if not self.target_address:
                self.status_label.configure(text="NO DEVICE", text_color=COLORS["accent_red"])
                return
            if not self.mapping:
                self.status_label.configure(text="NO MAP", text_color=COLORS["accent_red"])
                return
            self.is_running = True
            self.run_btn.configure(text="⏹   STOP ENGINE",
                                   fg_color=COLORS["accent_red"], hover_color="#ff5252")
            self.status_label.configure(text="CONNECTING", text_color=COLORS["accent_orange"])
            self.status_dot.configure(text_color=COLORS["accent_orange"])
            threading.Thread(target=self._run, daemon=True).start()
        else:
            self.is_running = False
            self.run_btn.configure(text="▶   START ENGINE",
                                   fg_color=COLORS["accent_green"],
                                   hover_color=COLORS["accent_green_hover"])
            self.status_label.configure(text="OFFLINE", text_color=COLORS["text_muted"])
            self.status_dot.configure(text_color=COLORS["text_muted"])

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.run_task())
        finally:
            loop.close()

    async def run_task(self):
        try:
            async with BleakClient(self.target_address, timeout=10.0) as client:
                if not client.is_connected:
                    self.after(0, lambda: self.status_label.configure(
                        text="FAILED", text_color=COLORS["accent_red"]))
                    self.after(0, lambda: self.status_dot.configure(
                        text_color=COLORS["accent_red"]))
                    return
                def handler(handle, data):
                    msg = list(data)
                    if len(msg) >= 6 and msg[3] == 0x1C:
                        self.last_id       = msg[5]
                        self.last_tap_time = time.time()
                await client.start_notify(NOTIFY_UUID, handler)
                self.after(0, lambda: self.status_label.configure(
                    text="LIVE", text_color=COLORS["accent_green"]))
                self.after(0, lambda: self.status_dot.configure(
                    text_color=COLORS["accent_green"]))
                keepalive = bytearray([0xCD, 0x00, 0x01, 0x01])
                while self.is_running:
                    if self.last_id and (time.time() - self.last_tap_time) > 0.4:
                        self.execute(self.last_id)
                        self.last_id = None
                    try:
                        await client.write_gatt_char(WRITE_UUID, keepalive)
                    except Exception:
                        pass
                    await asyncio.sleep(0.1)
                await client.stop_notify(NOTIFY_UUID)
        except Exception:
            pass
        finally:
            if self.is_running:
                self.is_running = False
                self.after(0, self._reset_engine_ui)

    def _reset_engine_ui(self):
        self.run_btn.configure(text="▶   START ENGINE",
                               fg_color=COLORS["accent_green"],
                               hover_color=COLORS["accent_green_hover"])
        self.status_label.configure(text="OFFLINE", text_color=COLORS["text_muted"])
        self.status_dot.configure(text_color=COLORS["text_muted"])

    # ====================================================================
    # Execute — built-in + custom actions
    # ====================================================================
    def execute(self, btn_id):
        # Check built-in mappings first
        action = next((k for k, v in self.mapping.items() if v == btn_id), None)
        if action:
            self._run_builtin(action)
            return

        # Check custom actions
        for name, info in self.custom_actions.items():
            if info.get("btn_id") == btn_id:
                self._run_custom(info)
                return

    def _run_builtin(self, action):
        if action == "Movie Mode":
            self._toggle_movie_mode()
        elif action == "Volume Up":
            self.press_volume_up()
        elif action == "Volume Down":
            self.press_volume_down()
        elif action == "Play/Pause":
            self.press_play_pause()

    def _toggle_movie_mode(self):
        if not self.movie_mode_active:
            # — Enter movie mode —
            # Save current state before changing anything
            self.pre_movie_volume     = self.get_pc_volume()
            try:
                self.pre_movie_brightness = sbc.get_brightness()[0]
            except Exception:
                self.pre_movie_brightness = None

            # Apply movie mode settings
            self.set_pc_volume(self.vol_slider.get())
            try:
                sbc.set_brightness(int(self.br_slider.get()))
            except Exception:
                pass

            self.movie_mode_active = True

        else:
            # — Exit movie mode — restore saved state —
            if self.pre_movie_volume is not None:
                self.set_pc_volume(self.pre_movie_volume)
            if self.pre_movie_brightness is not None:
                try:
                    sbc.set_brightness(self.pre_movie_brightness)
                except Exception:
                    pass

            self.movie_mode_active    = False
            self.pre_movie_volume     = None
            self.pre_movie_brightness = None

    def _run_custom(self, info):
        atype = info.get("type", "")
        value = info.get("value", "")
        try:
            if atype == "Key Press":
                pyautogui.press(value.strip())
            elif atype == "Hotkey (Combo)":
                keys = [k.strip() for k in value.replace("+", " ").split()]
                pyautogui.hotkey(*keys)
            elif atype == "Launch App":
                subprocess.Popen(value.strip(), shell=True)
        except Exception:
            pass


if __name__ == "__main__":
    app = SynodUniversal()
    app.mainloop()
