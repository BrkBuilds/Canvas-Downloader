# 🎓 Canvas Downloader

A simple tool for students to download all files and modules from Canvas courses in one go.

---

## ✨ Features
*   **Save Hours of Clicking**: Download *all* files from a course in seconds. No more clicking "download" on every single PDF.
*   **Stay Organized**: Automatically creates folders that match your Canvas Modules. Perfect for exam prep!
*   **Offline Study**: Get all your materials on your hard drive so you can study without internet.
*   **Downloads Everything**: Supports Files, Modules, Panopto Videos, Pages, and External Links.
*   **Always Up-to-Date**: New courses added to your Canvas account appear automatically in the app.
*   **Study Mode**: Use the "Pdf & Powerpoint only" filter to download only the most important study materials (skips everything else).
*   **Smart & Robust**: Skips files you can't access and retries automatically if the connection fails.
*   **Safe**: Runs locally on your machine. Your token is saved securely on your own computer.

---

## 💻 For Windows Users (How to Run)

1.  **Download**: Download the `Canvas_Downloader.exe` file.
2.  **Run**: Double-click the file to start.
3.  **Security Warnings (Important!)**:
    *   **"Windows protected your PC" (SmartScreen)**:
        *   Because this app is made by a student and not a large corporation (like Microsoft), Windows might try to block it.
        *   **Solution**: Click **"More info"** (under the text) and then click the **"Run anyway"** button.
    *   **Firewall Popup**:
        *   When the app starts, Windows Firewall might ask for permission.
        *   **Why?**: The app runs a small local "web server" on your computer to display the user interface in your browser. It needs permission to "talk" to itself.
        *   **Solution**: Check the boxes and click **"Allow access"**. It is completely safe.

---

## 🍎 For Mac Users (How to Run)

Since the `.exe` file only works on Windows, Mac users need to run the application using Python (don't worry, it's straightforward).

### Prerequisites
1.  **Install Python**: Download and install the latest Python 3 from [python.org](https://www.python.org/downloads/).
    *   *Note: Make sure to check "Add Python to PATH" if asked during installation.*

### Installation & Running
1.  **Download Source**: Download the folder containing these files.
2.  **Open Terminal**: Press `Cmd + Space`, type "Terminal", and press Enter.
3.  **Navigate to Folder**:
    *   Type `cd ` (type cd followed by a space).
    *   Drag the downloaded folder from Finder into the Terminal window (this automatically types the path).
    *   Press **Enter**.
4.  **Install Dependencies** (Only needed the first time):
    *   Copy and paste this command: `pip3 install -r requirements.txt`
    *   Press **Enter**.
5.  **Run the App**:
    *   Type: `python3 start.py`
    *   Press **Enter**.

The application should now open in your browser!


### 🆘 Help! It's not working?
If you're stuck, you might need to install Python.

1.  **Install Python**: Go to [python.org](https://www.python.org/downloads/) and download the latest version.
2.  **Check "Add to PATH"**: When installing, make sure to check the box that says "Add Python to PATH".
3.  **Try again**: Open your terminal, go to the folder, and run `pip3 install -r requirements.txt` followed by `python3 start.py`.


---

### 🍏 Bonus: Make it a double-clickable App (Mac)
You don't want to open the terminal every time? You can make a real app icon in 2 minutes:

1.  Open the **Automator** app on your Mac (Press Cmd+Space and type "Automator").
2.  Choose **"Application"** when asked what to create.
3.  In the search bar, type **"Run Shell Script"** and drag it into the main window.
4.  Delete the text inside and paste this (replace `/path/to/folder` with the actual path to your folder):
    ```bash
    cd /Users/YOUR_USERNAME/Downloads/canvas_downloader
    /usr/local/bin/python3 start.py
    ```
    *(Tip: To get the path, just drag the folder into the text box)*
5.  Press **Cmd + S** to save. Name it "Canvas Downloader" and save it to your **Applications** folder.
6.  **Done!** Now you just double-click that icon to run the app.

---

## 🚀 How to Use

### Step 1: Authentication
1.  Open the app.
2.  **Enter your Canvas URL**:
    *   **Crucial**: You must use the *actual* Canvas URL, not your school's login portal.
    *   **How to find it**: Log in to Canvas in your browser. Look at the address bar **after** you are logged in.
    *   It often looks like `https://schoolname.instructure.com` (even if you went to `canvas.school.edu` to get there).
    *   Copy that URL and paste it into the app.
3.  **Get an API Token**:
    *   Go to **Account** -> **Settings** on Canvas.
    *   Scroll to **Approved Integrations**.
    *   Click **+ New Access Token**.
    *   Copy the long string and paste it into the app.
4.  Click **"Validate & Save Token"**.

### Step 2: Select Courses
1.  You will see a list of your courses.
2.  Select the ones you want to download (or click "Select All").
3.  Click **"Continue"**.

### Step 3: Download
1.  Choose your **Download Structure**:
    *   **With subfolders**: Keeps files organized exactly like in Canvas Modules (Recommended).
    *   **Flat**: Puts all files for a course into one big folder.
2.  Choose a **Destination Folder** on your computer.
3.  Click **"Confirm and Download"**.
4.  Wait for the magic to happen! 🪄

---

## 📂 What are these files?

*   `Canvas_Downloader.exe`: The main program (Windows only).
*   `start.py`: The "Launcher" script that starts the system.
*   `app.py`: The visual interface you see in the browser.
*   `canvas_logic.py`: The "Brain" that talks to Canvas and handles downloads.
*   `translations.py`: Contains all text in English and Danish.
*   `requirements.txt`: List of tools the app needs (for Mac users).

---

## ⚠️ Common Issues & Troubleshooting

*   **"Unauthorized" Error**:
    *   If you see an error saying "unauthorized", your token might be expired, or you might be downloading too fast. The app now has "smart retries" to handle this, so just try again.
*   **White Screen**:
    *   If the browser window turns white and doesn't load, simply **refresh the page** (F5 or Cmd+R) or close the tab and reopen the link shown in the black "Mother" window.
*   **Download Speed**:
    *   To be safe and avoid getting blocked by Canvas, the app downloads 2 files at a time. Large courses might take a minute or two. Grab a coffee! ☕

---

*Made with ❤️ for Students*
