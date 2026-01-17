import sys
import os
import threading
import time
import webbrowser
import tkinter as tk
from tkinter import ttk
from streamlit.web import cli as stcli
from translations import get_text
import logging

# Logging disabled - no debug log file needed
# if getattr(sys, "frozen", False):
#     log_dir = os.path.dirname(sys.executable)
# else:
#     log_dir = os.path.dirname(os.path.abspath(__file__))

# log_file = os.path.join(log_dir, 'debug_log.txt')
# logging.basicConfig(
#     filename=log_file, 
#     level=logging.DEBUG,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     filemode='w' # Overwrite each run
# )
logging.disable(logging.CRITICAL)  # Disable all logging

class CanvasLauncher:
    def __init__(self):
        logging.info("Initializing CanvasLauncher")
        self.root = tk.Tk()
        self.root.title("Canvas Downloader")
        self.root.geometry("400x250")
        self.root.resizable(False, False)
        
        # Set icon if available
        try:
            self.root.iconbitmap(resolve_path("assets/icon.ico"))
        except Exception as e:
            logging.warning(f"Could not load icon: {e}")

        self.lang = 'en' # Default to English
        
        self.style = ttk.Style()
        self.style.configure("TLabel", font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 12, "bold"))
        
        self.main_frame = ttk.Frame(self.root, padding="20")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        self.header_label = ttk.Label(
            self.main_frame, 
            text="Canvas Downloader", 
            style="Header.TLabel"
        )
        self.header_label.pack(pady=(0, 20))
        
        # Status Label
        self.status_var = tk.StringVar(value="Starting application...")
        self.status_label = ttk.Label(
            self.main_frame, 
            textvariable=self.status_var, 
            wraplength=360
        )
        self.status_label.pack(pady=10)
        
        # Progress Bar (Indeterminate)
        self.progress = ttk.Progressbar(self.main_frame, mode='indeterminate')
        self.progress.pack(fill=tk.X, pady=10)
        self.progress.start(10)
        
        # Instruction Label
        self.instruction_label = ttk.Label(
            self.main_frame, 
            text="Close this window to stop the application",
            foreground="gray"
        )
        self.instruction_label.pack(side=tk.BOTTOM, pady=10)
        
        self.server_started = False
        
        # Start Streamlit in background thread
        logging.info("Starting Streamlit thread")
        self.thread = threading.Thread(target=self.start_streamlit, daemon=True)
        self.thread.start()
        
        # Start server monitor in background thread (to avoid blocking GUI)
        logging.info("Starting monitor thread")
        self.monitor_thread = threading.Thread(target=self.monitor_server, daemon=True)
        self.monitor_thread.start()

    def start_streamlit(self):
        try:
            app_path = resolve_path("app.py")
            logging.info(f"App path resolved to: {app_path}")
            
            if not os.path.exists(app_path):
                logging.error(f"CRITICAL: app.py not found at {app_path}")
                return

            # Prepare arguments for Streamlit
            # We need to set sys.argv for stcli to parse
            sys.argv = [
                "streamlit",
                "run",
                app_path,
                "--global.developmentMode=false",
                "--server.port=8501",
                "--server.headless=true",
                "--theme.base=dark",
                "--theme.primaryColor=#0072CE", # Canvas Blue
            ]
            logging.info(f"Streamlit args: {sys.argv}")
            
            # Monkeypatch signal.signal to avoid "ValueError: signal only works in main thread"
            # Streamlit tries to register signal handlers, which fails in a thread.
            # We don't need them since the launcher manages the lifecycle.
            import signal
            if threading.current_thread() is not threading.main_thread():
                logging.info("Monkeypatching signal.signal for background thread")
                signal.signal = lambda *args, **kwargs: None
            
            # Run Streamlit directly
            logging.info("Calling stcli.main()")
            stcli.main()
            logging.info("stcli.main() exited normally")
            
        except SystemExit as e:
            logging.info(f"Streamlit exited with code: {e}")
        except Exception as e:
            logging.error(f"Streamlit crashed: {e}", exc_info=True)

    def monitor_server(self):
        # Check for server readiness in a loop
        import urllib.request
        
        logging.info("Monitor thread started")
        attempts = 0
        while not self.server_started:
            try:
                # Short timeout to not block this thread too long
                with urllib.request.urlopen("http://localhost:8501/_stcore/health", timeout=1) as response:
                    if response.status == 200:
                        logging.info("Server health check passed")
                        # Schedule UI update on main thread
                        self.root.after(0, lambda: self.on_server_ready("http://localhost:8501"))
                        return
            except Exception as e:
                # Logging every failure might be too noisy, log every 10th
                if attempts % 10 == 0:
                    logging.debug(f"Health check failed: {e}")
                pass
            
            attempts += 1
            # Wait before next check
            time.sleep(1)

    def on_server_ready(self, url):
        if self.server_started: return
        self.server_started = True
        logging.info(f"Server ready at {url}")
        
        self.status_var.set(get_text('launcher_running', self.lang, url=url))
        self.progress.stop()
        self.progress.pack_forget()
        
        # Add a button to open browser manually
        open_btn = ttk.Button(self.main_frame, text="Open Browser", command=lambda: webbrowser.open(url))
        open_btn.pack(pady=5)
        
        # Open browser automatically
        webbrowser.open(url)

def resolve_path(path):
    """Resolve path for frozen vs normal execution."""
    if getattr(sys, "frozen", False):
        basedir = sys._MEIPASS
    else:
        basedir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(basedir, path)

if __name__ == "__main__":
    # Set up environment
    os.environ["STREAMLIT_SERVER_PORT"] = "8501"
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    
    app = CanvasLauncher()
    app.root.mainloop()
    
    # When window closes, exit the application (killing the background thread)
    sys.exit(0)
