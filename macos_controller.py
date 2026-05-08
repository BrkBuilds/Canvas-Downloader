import sys
import os
import subprocess
import threading
try:
    import customtkinter as ctk
except ImportError:
    pass  # Allow importing for type checking on Windows

try:
    from PIL import Image as _PILImage
except ImportError:
    _PILImage = None

# ── Constants ──
CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
WINDOW_WIDTH = 420
WINDOW_HEIGHT = 380

# ── Theme (matches Streamlit dark theme + app design tokens) ──
BG_DARK       = '#0e1117'
BG_CARD       = '#161b24'
TEXT_PRIMARY  = '#fafafa'
TEXT_SECONDARY= '#8A91A6'
TEXT_MUTED    = '#666666'
ACCENT_BLUE   = '#4DA8DA'
SUCCESS_GREEN = '#4ade80'
WARNING_AMBER = '#f59e0b'
ERROR_RED     = '#ef4444'
BTN_SUBTLE    = '#2D3248'

class CanvasController:
    """macOS Server Controller Window using CustomTkinter."""
    
    def __init__(self, streamlit_url: str, on_quit: callable):
        self.url = streamlit_url
        self.on_quit = on_quit
        self.state = 'starting'  # starting | ready | error
        
        # Configure appearance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        self.app = ctk.CTk()
        self.app.title("Canvas Downloader")
        self.app.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.app.resizable(False, False)
        self.app.configure(fg_color=BG_DARK)
        self.app.protocol('WM_DELETE_WINDOW', self._on_window_close)
        
        self._build_ui()
        self._apply_state('starting')

    def _resolve_path(self, path):
        """Resolve path for frozen (PyInstaller) vs normal execution."""
        if getattr(sys, "frozen", False):
            basedir = sys._MEIPASS
        else:
            basedir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(basedir, path)

    def _build_ui(self):
        """Construct the CustomTkinter UI."""
        # --- Main Container ---
        self.container = ctk.CTkFrame(self.app, fg_color=BG_DARK)
        self.container.pack(fill="both", expand=True, padx=28, pady=24)
        
        # --- Header ---
        self.header_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.header_frame.pack(fill="x", pady=(0, 16))
        
        # Load Icon
        icon_path = self._resolve_path(os.path.join("assets", "icon.png"))
        try:
            if _PILImage is None:
                raise ImportError("Pillow not available")
            self.icon_image = ctk.CTkImage(light_image=_PILImage.open(icon_path),
                                           dark_image=_PILImage.open(icon_path),
                                           size=(32, 32))
            self.icon_label = ctk.CTkLabel(self.header_frame, image=self.icon_image, text="")
            self.icon_label.pack(side="left", padx=(0, 10))
        except Exception:
            self.icon_label = ctk.CTkLabel(self.header_frame, text="📥", font=("Arial", 28))
            self.icon_label.pack(side="left", padx=(0, 10))
            
        self.title_label = ctk.CTkLabel(self.header_frame, text="Canvas Downloader", 
                                        font=ctk.CTkFont(family="Helvetica", size=18, weight="bold"),
                                        text_color=TEXT_PRIMARY)
        self.title_label.pack(side="left")
        
        # Divider
        self.divider = ctk.CTkFrame(self.container, height=1, fg_color="#ffffff")
        self.divider.pack(fill="x", pady=(0, 18))
        # CustomTkinter frame opacity is tricky, so we use a very dark gray to simulate low opacity white
        self.divider.configure(fg_color="#2a2e36")

        # --- Status Area ---
        self.status_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.status_frame.pack(fill="x", pady=(0, 18))
        
        # We use a Canvas to draw the circle so we can easily change its color
        self.status_canvas = ctk.CTkCanvas(self.status_frame, width=48, height=48, 
                                           bg=BG_DARK, highlightthickness=0)
        self.status_canvas.pack(pady=(0, 10))
        self.circle_id = self.status_canvas.create_oval(4, 4, 44, 44, fill="#facc15", outline="")
        
        # Countdown text inside the circle (hidden by default)
        self.countdown_text_id = self.status_canvas.create_text(24, 24, text="", 
                                                                fill="white", 
                                                                font=("Helvetica", 20, "bold"))

        self.status_title = ctk.CTkLabel(self.status_frame, text="Starting up...", 
                                         font=ctk.CTkFont(family="Helvetica", size=15, weight="bold"),
                                         text_color=TEXT_PRIMARY)
        self.status_title.pack()
        
        self.status_sub = ctk.CTkLabel(self.status_frame, text="Getting Canvas Downloader ready for you", 
                                       font=ctk.CTkFont(family="Helvetica", size=13),
                                       text_color=TEXT_SECONDARY,
                                       wraplength=320)
        self.status_sub.pack()

        # --- Buttons ---
        self.buttons_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.buttons_frame.pack(fill="x", pady=(0, 16))
        
        self.btn_primary = ctk.CTkButton(self.buttons_frame, text="Open Canvas Downloader", 
                                         font=ctk.CTkFont(family="Helvetica", size=14, weight="bold"),
                                         fg_color=ACCENT_BLUE, hover_color="#3b93c4",
                                         height=40, corner_radius=8,
                                         command=self.open_chrome)
        self.btn_primary.pack(fill="x", pady=(0, 8))
        
        self.btn_secondary = ctk.CTkButton(self.buttons_frame, text="Close Canvas Downloader", 
                                           font=ctk.CTkFont(family="Helvetica", size=14, weight="bold"),
                                           fg_color="transparent", hover_color=BG_CARD,
                                           border_width=1.5, border_color=BTN_SUBTLE,
                                           text_color=TEXT_SECONDARY,
                                           height=40, corner_radius=8,
                                           command=self._on_quit_click)
        self.btn_secondary.pack(fill="x")

        self.quit_warning = ctk.CTkLabel(self.buttons_frame, 
                                         text="Closing this window will also shut down Canvas Downloader",
                                         font=ctk.CTkFont(family="Helvetica", size=11),
                                         text_color=TEXT_MUTED)
        self.quit_warning.pack(pady=(6, 0))

        # --- Footer ---
        self.footer_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        self.footer_frame.pack(fill="x", side="bottom")
        
        try:
            import version as _version
            _ver_str = f"v{_version.__version__}"
        except Exception:
            _ver_str = "v?"
        self.version_label = ctk.CTkLabel(self.footer_frame, text=_ver_str,
                                          font=ctk.CTkFont(family="Helvetica", size=11),
                                          text_color="#444444")
        self.version_label.pack(side="left")
        
        self.dot_label = ctk.CTkLabel(self.footer_frame, text=" · ", 
                                      font=ctk.CTkFont(family="Helvetica", size=11),
                                      text_color="#444444")
        self.dot_label.pack(side="left", padx=4)
        
        self.help_label = ctk.CTkLabel(self.footer_frame, text="Need help? Visit our website", 
                                       font=ctk.CTkFont(family="Helvetica", size=11),
                                       text_color=ACCENT_BLUE, cursor="hand2")
        self.help_label.pack(side="left")
        self.help_label.bind("<Button-1>", lambda e: self._open_website())
        self.help_label.bind("<Enter>", lambda e: self.help_label.configure(font=ctk.CTkFont(family="Helvetica", size=11, underline=True)))
        self.help_label.bind("<Leave>", lambda e: self.help_label.configure(font=ctk.CTkFont(family="Helvetica", size=11, underline=False)))

    def _open_website(self):
        """Open the help website."""
        subprocess.Popen(['open', 'https://birkls.github.io/Canvas_LMS_batch_file_downloader/'])

    def set_state(self, state: str, message: str = '', sub_message: str = ''):
        """Thread-safe state transition."""
        self.app.after(0, self._apply_state, state, message, sub_message)

    def _apply_state(self, state: str, message: str = '', sub_message: str = ''):
        """Update the UI widgets to reflect the current state."""
        self.state = state
        self.status_canvas.itemconfig(self.countdown_text_id, text="")
        
        if state == 'starting':
            self.status_canvas.itemconfig(self.circle_id, fill="#facc15")
            self.status_title.configure(text="Starting up...", text_color=TEXT_PRIMARY)
            self.status_sub.configure(text="Getting Canvas Downloader ready for you")
            self.btn_primary.configure(state="disabled", fg_color="#2b4c5e", text_color="#5a687a")
            self.btn_secondary.configure(state="disabled", text_color="#444444", border_color="#1a1e28")
            
        elif state == 'ready':
            self.status_canvas.itemconfig(self.circle_id, fill=SUCCESS_GREEN)
            self.status_title.configure(text="Canvas Downloader is running", text_color=TEXT_PRIMARY)
            self.status_sub.configure(text="Your app is open in Google Chrome.\nCan't find it? Press the button below to reopen it.")
            self.btn_primary.configure(state="normal", fg_color=ACCENT_BLUE, text_color=TEXT_PRIMARY, text="Open Canvas Downloader")
            self.btn_secondary.configure(state="normal", text_color=TEXT_SECONDARY, border_color=BTN_SUBTLE)
            
        elif state == 'error':
            self.status_canvas.itemconfig(self.circle_id, fill=ERROR_RED)
            self.status_title.configure(text=message or "Google Chrome not found", text_color=ERROR_RED)
            self.status_sub.configure(text=sub_message or "Canvas Downloader requires Google Chrome.\nPlease install it from google.com/chrome")
            self.btn_primary.configure(state="normal", fg_color=ACCENT_BLUE, text_color=TEXT_PRIMARY, text="Try Again")
            self.btn_secondary.configure(state="normal", text_color=TEXT_SECONDARY, border_color=BTN_SUBTLE)

    def _on_window_close(self):
        """Handle the native window close button (red X)."""
        self._on_quit_click()

    def _on_quit_click(self):
        """Handle application exit."""
        self.on_quit()
        self.app.destroy()

    def open_chrome(self):
        """Open/reopen the Streamlit URL in Chrome."""
        if self.state == 'error':
            # The user clicked "Try Again"
            self.set_state('starting')
            if hasattr(self, 'retry_callback'):
                threading.Thread(target=self.retry_callback, daemon=True).start()
            return

        if os.path.exists(CHROME_PATH):
            subprocess.Popen([CHROME_PATH, '--new-window', self.url])
        else:
            # Fallback: let macOS Launch Services find Chrome regardless of install location
            # (covers ~/Applications installs, non-standard paths, etc.)
            # --args passes flags through to Chrome; --new-window forces a focused new window
            # even when Chrome is already running with other tabs open.
            result = subprocess.run(
                ['open', '-a', 'Google Chrome', '--args', '--new-window', self.url],
                capture_output=True,
            )
            if result.returncode != 0:
                self.set_state('error', 'Google Chrome not found', 'Canvas Downloader requires Google Chrome.\nPlease install it from google.com/chrome')

    def run(self):
        """Start the CustomTkinter main loop (must be called from main thread)."""
        self.app.mainloop()
