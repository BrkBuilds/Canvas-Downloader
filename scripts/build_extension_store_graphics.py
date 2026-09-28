"""Generate Chrome Web Store screenshots and promotional tiles for Canvas Downloader Connector.

    python scripts/build_extension_store_graphics.py

Outputs generated in packaging/chrome-web-store/assets/:
- screenshot_1_signin_1280x800.png     (1280x800)  One-click sign in from active tab
- screenshot_2_guidance_1280x800.png   (1280x800)  Step-by-step guidance & status detection
- screenshot_3_handoff_1280x800.png    (1280x800)  Instant handoff to desktop app
- screenshot_4_privacy_1280x800.png    (1280x800)  Privacy architecture & local-only connection
- screenshot_5_themes_1280x800.png     (1280x800)  Light and dark theme support
- promo_tile_440x280.png               (440x280)   Small promo tile (required by CWS)
- marquee_promo_1400x560.png           (1400x560)  Featured marquee promo banner
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
EXT_SCREENS = REPO / "packaging" / "chrome-web-store" / "screens"
ASSETS_DIR = REPO / "packaging" / "chrome-web-store" / "assets"
APP_ASSETS = REPO / "assets"
DOCS_ASSETS = REPO / "docs" / "assets" / "screenshots"


def b64_img(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing asset: {path}")
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{data}"


COMMON_CSS = """
* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}
html, body {
    width: 1280px;
    height: 800px;
    box-sizing: border-box;
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #f1f5f9;
    background: #0b111e;
    overflow: hidden;
    position: relative;
    -webkit-font-smoothing: antialiased;
}
.bg-glow {
    position: absolute;
    top: -200px;
    left: 50%;
    transform: translateX(-50%);
    width: 900px;
    height: 500px;
    background: radial-gradient(ellipse at center, rgba(31, 111, 158, 0.35) 0%, rgba(14, 165, 233, 0.12) 45%, transparent 70%);
    pointer-events: none;
    z-index: 0;
}
.bg-glow-bottom {
    position: absolute;
    bottom: -200px;
    right: 10%;
    width: 600px;
    height: 400px;
    background: radial-gradient(ellipse at center, rgba(37, 99, 235, 0.18) 0%, transparent 70%);
    pointer-events: none;
    z-index: 0;
}
.header-area {
    position: relative;
    z-index: 2;
    padding: 22px 48px 12px;
    text-align: center;
}
.header-tag {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    background: rgba(31, 111, 158, 0.22);
    border: 1px solid rgba(56, 189, 248, 0.35);
    color: #38bdf8;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 3px 12px;
    border-radius: 999px;
    margin-bottom: 8px;
}
.header-tag .dot {
    width: 6px;
    height: 6px;
    background: #38bdf8;
    border-radius: 50%;
    box-shadow: 0 0 8px #38bdf8;
}
h1 {
    font-size: 27px;
    font-weight: 700;
    line-height: 1.2;
    color: #ffffff;
    letter-spacing: -0.02em;
    margin-bottom: 5px;
}
h1 span.accent {
    color: #38bdf8;
    background: linear-gradient(135deg, #38bdf8 0%, #60a5fa 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.subtitle {
    font-size: 14.5px;
    color: #94a3b8;
    max-width: 740px;
    margin: 0 auto;
    line-height: 1.4;
}
.footer-pills {
    position: absolute;
    bottom: 22px;
    left: 0;
    right: 0;
    display: flex;
    justify-content: center;
    gap: 14px;
    z-index: 3;
}
.feature-pill {
    display: flex;
    align-items: center;
    gap: 7px;
    background: rgba(15, 23, 42, 0.88);
    border: 1px solid rgba(51, 65, 85, 0.85);
    backdrop-filter: blur(12px);
    border-radius: 999px;
    padding: 6px 15px;
    font-size: 12px;
    color: #cbd5e1;
    font-weight: 500;
}
.feature-pill .check {
    color: #10b981;
    font-weight: 700;
}

/* Chrome Window Mockup */
.browser-window {
    width: 1140px;
    height: 600px;
    background: #1e293b;
    border: 1px solid rgba(71, 85, 105, 0.7);
    border-radius: 12px 12px 0 0;
    box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.65), 0 0 0 1px rgba(255, 255, 255, 0.06);
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    position: relative;
    z-index: 2;
}
.browser-chrome {
    background: #0f172a;
    border-bottom: 1px solid rgba(51, 65, 85, 0.8);
    display: flex;
    flex-direction: column;
}
.browser-tab-bar {
    display: flex;
    align-items: center;
    padding: 9px 12px 0;
    height: 38px;
    gap: 8px;
}
.window-controls {
    display: flex;
    gap: 6px;
    padding-right: 12px;
}
.ctrl-dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
}
.ctrl-close { background: #ef4444; }
.ctrl-min { background: #eab308; }
.ctrl-max { background: #22c55e; }

.tab {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 14px;
    border-radius: 8px 8px 0 0;
    font-size: 12px;
    font-weight: 500;
    color: #94a3b8;
    background: transparent;
    max-width: 210px;
}
.tab.active {
    background: #1e293b;
    color: #f1f5f9;
    border: 1px solid rgba(71, 85, 105, 0.5);
    border-bottom: none;
}
.tab-icon {
    width: 14px;
    height: 14px;
    border-radius: 2px;
}
.tab-title {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.tab-close {
    font-size: 12px;
    color: #64748b;
    margin-left: auto;
}

.browser-toolbar {
    background: #1e293b;
    height: 42px;
    display: flex;
    align-items: center;
    padding: 0 12px;
    gap: 12px;
}
.nav-buttons {
    display: flex;
    gap: 10px;
    color: #64748b;
    font-size: 14px;
}
.url-bar {
    flex: 1;
    height: 28px;
    background: #0f172a;
    border: 1px solid rgba(51, 65, 85, 0.8);
    border-radius: 6px;
    display: flex;
    align-items: center;
    padding: 0 10px;
    gap: 7px;
    font-size: 12px;
    color: #94a3b8;
}
.url-bar .padlock {
    color: #10b981;
    font-size: 11px;
}
.url-bar .host {
    color: #e2e8f0;
    font-weight: 500;
}
.url-bar .path {
    color: #64748b;
}

.extension-toolbar-icons {
    display: flex;
    align-items: center;
    gap: 10px;
    position: relative;
}
.ext-btn {
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 6px;
    color: #94a3b8;
    position: relative;
}
.ext-btn.active {
    background: rgba(31, 111, 158, 0.35);
    border: 1px solid rgba(56, 189, 248, 0.5);
}
.ext-btn img {
    width: 18px;
    height: 18px;
}
.ext-dot {
    position: absolute;
    top: 2px;
    right: 2px;
    width: 6px;
    height: 6px;
    background: #0284c7;
    border: 1.5px solid #1e293b;
    border-radius: 50%;
}

.browser-content {
    flex: 1;
    background: #f8fafc;
    position: relative;
    overflow: hidden;
    display: flex;
}

/* Canvas Mockup Content */
.canvas-sidebar {
    width: 64px;
    background: #2D3B45;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 14px 0;
    gap: 16px;
}
.canvas-logo-mark {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: #E02424;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    font-weight: 800;
    font-size: 15px;
}
.canvas-nav-item {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 3px;
    color: #cbd5e1;
    font-size: 9px;
    text-transform: capitalize;
}
.canvas-nav-item.active {
    color: #ffffff;
    font-weight: 700;
}
.canvas-nav-icon {
    width: 18px;
    height: 18px;
    opacity: 0.85;
}

.canvas-main {
    flex: 1;
    padding: 24px 30px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    background: #f8fafc;
    color: #1e293b;
}
.canvas-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid #e2e8f0;
    padding-bottom: 10px;
}
.canvas-title {
    font-size: 20px;
    font-weight: 700;
    color: #1e293b;
}
.course-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 14px;
    max-width: 650px;
}
.course-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.card-header-bar {
    height: 48px;
}
.bar-blue { background: #0284c7; }
.bar-green { background: #059669; }
.bar-burgundy { background: #991b1b; }
.card-body {
    padding: 10px 12px;
}
.card-title {
    font-size: 12px;
    font-weight: 700;
    color: #0f172a;
    margin-bottom: 2px;
}
.card-code {
    font-size: 10px;
    color: #64748b;
}

/* Extension Popup Dropdown Frame */
.popup-dropdown-container {
    position: absolute;
    top: 6px;
    right: 18px;
    z-index: 100;
    border-radius: 12px;
    box-shadow: 0 20px 45px -8px rgba(0, 0, 0, 0.45), 0 0 0 1px rgba(0, 0, 0, 0.12);
    overflow: hidden;
    background: #ffffff;
    animation: popupDrop 0.3s ease;
}
.popup-dropdown-container.dark-theme {
    background: #171b24;
    box-shadow: 0 20px 45px -8px rgba(0, 0, 0, 0.7), 0 0 0 1px rgba(255, 255, 255, 0.1);
}
.popup-img {
    display: block;
    width: 320px;
    height: auto;
}
"""


def render_html(html: str, out_path: Path, width: int, height: int):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.set_content(html, wait_until="networkidle")
        page.screenshot(path=str(out_path), type="png")
        browser.close()
    print(f"  [OK] {out_path.name} ({width}x{height})")


def generate_screenshot_1():
    popup_b64 = b64_img(EXT_SCREENS / "light" / "06_guide_ready_to-sign-in.png")
    icon_b64 = b64_img(APP_ASSETS / "icon.png")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
{COMMON_CSS}
</style>
</head>
<body>
<div class="bg-glow"></div>
<div class="bg-glow-bottom"></div>

<div class="header-area">
    <div class="header-tag"><span class="dot"></span> 1-Click Browser Connection</div>
    <h1>Sign in to Canvas Downloader <span class="accent">with One Click</span></h1>
    <p class="subtitle">Signs you in directly from the Canvas tab already open in your browser. No access token to copy, nothing to type.</p>
</div>

<div class="browser-window">
    <div class="browser-chrome">
        <div class="browser-tab-bar">
            <div class="window-controls">
                <span class="ctrl-dot ctrl-close"></span>
                <span class="ctrl-dot ctrl-min"></span>
                <span class="ctrl-dot ctrl-max"></span>
            </div>
            <div class="tab active">
                <img src="{icon_b64}" class="tab-icon">
                <span class="tab-title">Dashboard · Canvas LMS</span>
                <span class="tab-close">&times;</span>
            </div>
            <div class="tab">
                <span class="tab-title">Economics 101 · Files</span>
            </div>
        </div>
        <div class="browser-toolbar">
            <div class="nav-buttons">&larr; &rarr; &#8635;</div>
            <div class="url-bar">
                <span class="padlock">&#128274;</span>
                <span class="host">cbscanvas.instructure.com</span><span class="path">/courses/43660</span>
            </div>
            <div class="extension-toolbar-icons">
                <div class="ext-btn active">
                    <img src="{icon_b64}">
                    <span class="ext-dot"></span>
                </div>
            </div>
        </div>
    </div>

    <div class="browser-content">
        <div class="canvas-sidebar">
            <div class="canvas-logo-mark">C</div>
            <div class="canvas-nav-item active"><span style="font-size: 14px;">&#127891;</span>Courses</div>
            <div class="canvas-nav-item"><span style="font-size: 14px;">&#128197;</span>Calendar</div>
            <div class="canvas-nav-item"><span style="font-size: 14px;">&#128172;</span>Inbox</div>
        </div>
        <div class="canvas-main">
            <div class="canvas-header">
                <div class="canvas-title">Dashboard</div>
                <div style="font-size: 12px; color: #64748b;">Fall Semester 2026</div>
            </div>
            <div class="course-grid">
                <div class="course-card">
                    <div class="card-header-bar bar-blue"></div>
                    <div class="card-body">
                        <div class="card-title">Corporate Finance</div>
                        <div class="card-code">CFIN2026_E26 · CBS</div>
                    </div>
                </div>
                <div class="course-card">
                    <div class="card-header-bar bar-green"></div>
                    <div class="card-body">
                        <div class="card-title">Business Analytics & AI</div>
                        <div class="card-code">BAAI3010_E26 · CBS</div>
                    </div>
                </div>
                <div class="course-card">
                    <div class="card-header-bar bar-burgundy"></div>
                    <div class="card-body">
                        <div class="card-title">Macroeconomics</div>
                        <div class="card-code">MACRO101_E26 · CBS</div>
                    </div>
                </div>
            </div>
        </div>

        <div class="popup-dropdown-container">
            <img src="{popup_b64}" class="popup-img">
        </div>
    </div>
</div>

<div class="footer-pills">
    <div class="feature-pill"><span class="check">&#10003;</span> No Access Token Required</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Works on 4,700+ Canvas Universities</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Retains Institutional SSO & 2FA</div>
    <div class="feature-pill"><span class="check">&#10003;</span> 100% Free & Open Source</div>
</div>
</body>
</html>"""
    render_html(html, ASSETS_DIR / "screenshot_1_signin_1280x800.png", 1280, 800)


def generate_screenshot_2():
    popup_b64 = b64_img(EXT_SCREENS / "light" / "05_guide_ready_needs-chrome-permission.png")
    icon_b64 = b64_img(APP_ASSETS / "icon.png")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
{COMMON_CSS}
.dual-container {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 40px;
    padding-top: 4px;
    z-index: 2;
    position: relative;
}}
.guide-card-column {{
    width: 480px;
    display: flex;
    flex-direction: column;
    gap: 13px;
}}
.step-card {{
    background: rgba(15, 23, 42, 0.75);
    border: 1px solid rgba(51, 65, 85, 0.8);
    border-radius: 12px;
    padding: 13px 18px;
    display: flex;
    gap: 14px;
    align-items: flex-start;
    backdrop-filter: blur(10px);
}}
.step-card.active {{
    border-color: rgba(56, 189, 248, 0.6);
    background: rgba(15, 23, 42, 0.92);
    box-shadow: 0 0 25px rgba(56, 189, 248, 0.12);
}}
.step-num {{
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: #1e293b;
    color: #94a3b8;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 13px;
    flex-shrink: 0;
}}
.step-card.active .step-num {{
    background: #0284c7;
    color: #ffffff;
}}
.step-content h3 {{
    font-size: 14.5px;
    color: #ffffff;
    font-weight: 600;
    margin-bottom: 3px;
}}
.step-content p {{
    font-size: 12.5px;
    color: #94a3b8;
    line-height: 1.4;
}}
.popup-showcase {{
    position: relative;
}}
.popup-frame {{
    border-radius: 12px;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.1);
    overflow: hidden;
    background: #ffffff;
}}
.popup-label {{
    text-align: center;
    font-size: 11px;
    color: #94a3b8;
    margin-top: 6px;
    font-weight: 500;
}}
</style>
</head>
<body>
<div class="bg-glow"></div>
<div class="bg-glow-bottom"></div>

<div class="header-area">
    <div class="header-tag"><span class="dot"></span> Smart State Detection</div>
    <h1>Clear <span class="accent">Step-by-Step Guidance</span></h1>
    <p class="subtitle">The connector monitors your open tab and desktop app status, guiding you smoothly from setup to sign-in.</p>
</div>

<div class="dual-container">
    <div class="guide-card-column">
        <div class="step-card">
            <div class="step-num">&#10003;</div>
            <div class="step-content">
                <h3>1. Open your Canvas page</h3>
                <p>Navigate to your school's Canvas portal in any browser tab. The extension automatically verifies your institution domain.</p>
            </div>
        </div>

        <div class="step-card">
            <div class="step-num">&#10003;</div>
            <div class="step-content">
                <h3>2. Choose browser tab in Canvas Downloader</h3>
                <p>In the desktop app, select <em>"Sign in with the extension"</em>. The app opens a secure local listener.</p>
            </div>
        </div>

        <div class="step-card active">
            <div class="step-num">3</div>
            <div class="step-content">
                <h3>3. Click Sign me in</h3>
                <p>Grant one-time access for your specific school domain, then click <strong>Sign me in</strong>. That's all it takes!</p>
            </div>
        </div>
    </div>

    <div class="popup-showcase">
        <div class="popup-frame">
            <img src="{popup_b64}" style="width: 290px; display: block;">
        </div>
        <div class="popup-label">&#128065; One-time permission prompt for your university domain</div>
    </div>
</div>

<div class="footer-pills">
    <div class="feature-pill"><span class="check">&#10003;</span> Auto-Detects Canvas URL</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Real-Time App Liveness Check</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Clear Error Diagnostics</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Self-Guiding UI</div>
</div>
</body>
</html>"""
    render_html(html, ASSETS_DIR / "screenshot_2_guidance_1280x800.png", 1280, 800)


def generate_screenshot_3():
    popup_success_b64 = b64_img(EXT_SCREENS / "light" / "10_success_countdown.png")
    desktop_app_b64 = b64_img(DOCS_ASSETS / "course-selection.png")
    icon_b64 = b64_img(APP_ASSETS / "icon.png")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
{COMMON_CSS}
.handoff-container {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 32px;
    padding: 0 44px;
    z-index: 2;
    position: relative;
}}
.handoff-left {{
    width: 285px;
    flex-shrink: 0;
}}
.handoff-arrow {{
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    color: #38bdf8;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}}
.arrow-circle {{
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: rgba(56, 189, 248, 0.15);
    border: 1px solid rgba(56, 189, 248, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    color: #38bdf8;
    box-shadow: 0 0 20px rgba(56, 189, 248, 0.25);
}}
.handoff-right {{
    flex: 1;
    max-width: 660px;
}}
.desktop-preview {{
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.7), 0 0 0 1px rgba(255, 255, 255, 0.1);
    background: #0f172a;
    border: 1px solid rgba(71, 85, 105, 0.8);
}}
.preview-titlebar {{
    height: 30px;
    background: #090d16;
    border-bottom: 1px solid rgba(51, 65, 85, 0.8);
    display: flex;
    align-items: center;
    padding: 0 12px;
    gap: 8px;
    font-size: 11px;
    color: #94a3b8;
}}
.preview-img {{
    width: 100%;
    height: auto;
    display: block;
}}
</style>
</head>
<body>
<div class="bg-glow"></div>
<div class="bg-glow-bottom"></div>

<div class="header-area">
    <div class="header-tag"><span class="dot"></span> Instant Desktop Handoff</div>
    <h1>Seamless Handoff to <span class="accent">Canvas Downloader</span></h1>
    <p class="subtitle">Once confirmed, your session is immediately handed to the desktop app to load courses, download study materials, and sync files.</p>
</div>

<div class="handoff-container">
    <div class="handoff-left">
        <div style="border-radius: 12px; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255,255,255,0.1); background: #ffffff;">
            <img src="{popup_success_b64}" style="width: 100%; display: block;">
        </div>
        <div style="text-align: center; font-size: 11.5px; color: #10b981; margin-top: 7px; font-weight: 600;">
            &#10003; Session confirmed &bull; Courses loading
        </div>
    </div>

    <div class="handoff-arrow">
        <div class="arrow-circle">&rarr;</div>
        <span>Local Handoff</span>
        <span style="font-size: 9.5px; color: #64748b;">127.0.0.1</span>
    </div>

    <div class="handoff-right">
        <div class="desktop-preview">
            <div class="preview-titlebar">
                <span class="ctrl-dot ctrl-close"></span>
                <span class="ctrl-dot ctrl-min"></span>
                <span class="ctrl-dot ctrl-max"></span>
                <span style="margin-left: 10px; font-weight: 600; color: #cbd5e1;">Canvas Downloader &mdash; Select Courses</span>
            </div>
            <img src="{desktop_app_b64}" class="preview-img">
        </div>
    </div>
</div>

<div class="footer-pills">
    <div class="feature-pill"><span class="check">&#10003;</span> Auto-Loads Enrolled Courses</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Zero-Latency Local Handoff</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Automatic Token Upgrade Where Permitted</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Windows & macOS App Support</div>
</div>
</body>
</html>"""
    render_html(html, ASSETS_DIR / "screenshot_3_handoff_1280x800.png", 1280, 800)


def generate_screenshot_4():
    popup_b64 = b64_img(EXT_SCREENS / "light" / "12_resting_signed-in_app-running.png")
    icon_b64 = b64_img(APP_ASSETS / "icon.png")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
{COMMON_CSS}
.privacy-grid-container {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 40px;
    padding: 0 50px;
    z-index: 2;
    position: relative;
}}
.security-cards {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    max-width: 660px;
}}
.sec-card {{
    background: rgba(15, 23, 42, 0.75);
    border: 1px solid rgba(51, 65, 85, 0.8);
    border-radius: 12px;
    padding: 14px 16px;
    backdrop-filter: blur(10px);
}}
.sec-icon {{
    width: 32px;
    height: 32px;
    border-radius: 8px;
    background: rgba(56, 189, 248, 0.12);
    border: 1px solid rgba(56, 189, 248, 0.3);
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    color: #38bdf8;
    margin-bottom: 8px;
}}
.sec-card h3 {{
    font-size: 14px;
    color: #ffffff;
    font-weight: 600;
    margin-bottom: 4px;
}}
.sec-card p {{
    font-size: 11.5px;
    color: #94a3b8;
    line-height: 1.45;
}}
.resting-showcase {{
    width: 300px;
}}
</style>
</head>
<body>
<div class="bg-glow"></div>
<div class="bg-glow-bottom"></div>

<div class="header-area">
    <div class="header-tag"><span class="dot"></span> Security & Transparency</div>
    <h1>Privacy-First <span class="accent">by Construction</span></h1>
    <p class="subtitle">Built with zero external network access. Operates exclusively on your local machine and only when you explicitly click it.</p>
</div>

<div class="privacy-grid-container">
    <div class="resting-showcase">
        <div style="border-radius: 12px; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(255, 255, 255, 0.1); background: #ffffff;">
            <img src="{popup_b64}" style="width: 100%; display: block;">
        </div>
        <div style="text-align: center; font-size: 11px; color: #94a3b8; margin-top: 8px;">
            &#128737; Resting screen after sign-in completion
        </div>
    </div>

    <div class="security-cards">
        <div class="sec-card">
            <div class="sec-icon">&#128683;</div>
            <h3>No Browsing Tracking</h3>
            <p>No <code>tabs</code> permission. The extension cannot see what pages you browse, what tabs you have open, or your browser history.</p>
        </div>

        <div class="sec-card">
            <div class="sec-icon">&#128279;</div>
            <h3>Localhost Only</h3>
            <p>Passes your login strictly to <code>http://127.0.0.1</code> on your own computer. Zero data is transmitted to external servers or third parties.</p>
        </div>

        <div class="sec-card">
            <div class="sec-icon">&#9757;</div>
            <h3>User-Initiated Action Only</h3>
            <p>Has no background content scripts. It never runs code automatically and only reads authentication cookies when you press <strong>Sign me in</strong>.</p>
        </div>

        <div class="sec-card">
            <div class="sec-icon">&#128214;</div>
            <h3>100% Free & Open Source</h3>
            <p>Licensed under GPL-3.0. Every line of code is open, transparent, and verifiable by the community on GitHub.</p>
        </div>
    </div>
</div>

<div class="footer-pills">
    <div class="feature-pill"><span class="check">&#10003;</span> No Analytics or Telemetry</div>
    <div class="feature-pill"><span class="check">&#10003;</span> No Remote Code</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Strict Loopback Origin Check</div>
    <div class="feature-pill"><span class="check">&#10003;</span> GPL-3.0 Open Source</div>
</div>
</body>
</html>"""
    render_html(html, ASSETS_DIR / "screenshot_4_privacy_1280x800.png", 1280, 800)


def generate_screenshot_5():
    popup_light_b64 = b64_img(EXT_SCREENS / "light" / "06_guide_ready_to-sign-in.png")
    popup_dark_b64 = b64_img(EXT_SCREENS / "dark" / "06_guide_ready_to-sign-in.png")
    icon_b64 = b64_img(APP_ASSETS / "icon.png")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
{COMMON_CSS}
.themes-container {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 48px;
    padding: 0 48px;
    z-index: 2;
    position: relative;
}}
.theme-column {{
    display: flex;
    flex-direction: column;
    align-items: center;
}}
.theme-badge {{
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 4px 12px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    margin-bottom: 10px;
}}
.theme-badge.light-badge {{
    background: rgba(241, 245, 249, 0.15);
    border: 1px solid rgba(241, 245, 249, 0.3);
    color: #f1f5f9;
}}
.theme-badge.dark-badge {{
    background: rgba(56, 189, 248, 0.18);
    border: 1px solid rgba(56, 189, 248, 0.4);
    color: #38bdf8;
}}
.popup-card-wrapper {{
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 25px 60px -15px rgba(0, 0, 0, 0.65), 0 0 0 1px rgba(255, 255, 255, 0.1);
}}
</style>
</head>
<body>
<div class="bg-glow"></div>
<div class="bg-glow-bottom"></div>

<div class="header-area">
    <div class="header-tag"><span class="dot"></span> Design & Accessibility</div>
    <h1>Built for <span class="accent">Light & Dark Mode</span></h1>
    <p class="subtitle">Automatically follows your system and browser appearance preferences with carefully tuned contrast and legible typography.</p>
</div>

<div class="themes-container">
    <div class="theme-column">
        <div class="theme-badge light-badge">&#9728; Light Theme</div>
        <div class="popup-card-wrapper" style="background: #ffffff;">
            <img src="{popup_light_b64}" style="width: 290px; display: block;">
        </div>
    </div>

    <div class="theme-column">
        <div class="theme-badge dark-badge">&#9790; Dark Theme</div>
        <div class="popup-card-wrapper" style="background: #171b24;">
            <img src="{popup_dark_b64}" style="width: 290px; display: block;">
        </div>
    </div>
</div>

<div class="footer-pills">
    <div class="feature-pill"><span class="check">&#10003;</span> Auto-Matches System Theme</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Crisp Contrast in All Lighting</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Chromium & Edge Support</div>
    <div class="feature-pill"><span class="check">&#10003;</span> Compact & Clean Layout</div>
</div>
</body>
</html>"""
    render_html(html, ASSETS_DIR / "screenshot_5_themes_1280x800.png", 1280, 800)



def generate_promo_tile_small():
    icon_b64 = b64_img(APP_ASSETS / "icon.png")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}}
html, body {{
    width: 440px;
    height: 280px;
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #ffffff;
    background: linear-gradient(135deg, #091a32 0%, #0d284a 50%, #153c6c 100%);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    padding: 24px 20px;
    position: relative;
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
}}
.glow {{
    position: absolute;
    top: -40px;
    left: 50%;
    transform: translateX(-50%);
    width: 280px;
    height: 180px;
    background: radial-gradient(ellipse at center, rgba(56, 189, 248, 0.4) 0%, transparent 70%);
    pointer-events: none;
}}
.icon-box {{
    width: 76px;
    height: 76px;
    border-radius: 18px;
    box-shadow: 0 12px 30px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(255, 255, 255, 0.15);
    margin-bottom: 12px;
    position: relative;
    z-index: 2;
}}
.title {{
    font-size: 22px;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: #ffffff;
    line-height: 1.15;
    margin-bottom: 3px;
}}
.title span {{
    color: #38bdf8;
}}
.tagline {{
    font-size: 13.5px;
    font-weight: 500;
    color: #cbd5e1;
    margin-bottom: 12px;
}}
.badge {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(15, 23, 42, 0.7);
    border: 1px solid rgba(56, 189, 248, 0.35);
    border-radius: 999px;
    padding: 3px 12px;
    font-size: 11px;
    font-weight: 600;
    color: #38bdf8;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}}
</style>
</head>
<body>
<div class="glow"></div>
<img src="{icon_b64}" class="icon-box">
<div class="title">Canvas Downloader <span>Connector</span></div>
<div class="tagline">One-click sign-in from your Canvas tab</div>
<div class="badge">&#128274; 100% Private &bull; Open Source</div>
</body>
</html>"""
    render_html(html, ASSETS_DIR / "promo_tile_440x280.png", 440, 280)


def generate_marquee_promo():
    icon_b64 = b64_img(APP_ASSETS / "icon.png")
    popup_b64 = b64_img(EXT_SCREENS / "light" / "06_guide_ready_to-sign-in.png")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}}
html, body {{
    width: 1400px;
    height: 560px;
    margin: 0;
    padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: #ffffff;
    background: linear-gradient(135deg, #070d18 0%, #0d1b2e 50%, #132a48 100%);
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 80px;
    position: relative;
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
}}
.marquee-glow {{
    position: absolute;
    top: -100px;
    left: 20%;
    width: 700px;
    height: 400px;
    background: radial-gradient(ellipse at center, rgba(31, 111, 158, 0.45) 0%, transparent 70%);
    pointer-events: none;
}}
.marquee-left {{
    max-width: 680px;
    z-index: 2;
}}
.brand-lockup {{
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
}}
.brand-icon {{
    width: 38px;
    height: 38px;
    border-radius: 9px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}}
.brand-name {{
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #38bdf8;
}}
h1 {{
    font-size: 42px;
    font-weight: 800;
    line-height: 1.15;
    letter-spacing: -0.025em;
    margin-bottom: 14px;
    color: #ffffff;
}}
h1 span {{
    color: #38bdf8;
}}
p.desc {{
    font-size: 18px;
    color: #94a3b8;
    line-height: 1.5;
    margin-bottom: 24px;
}}
.check-row {{
    display: flex;
    flex-direction: column;
    gap: 10px;
}}
.check-item {{
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 15px;
    color: #cbd5e1;
    font-weight: 500;
}}
.check-icon {{
    color: #10b981;
    font-weight: 800;
    font-size: 16px;
}}

.marquee-right {{
    position: relative;
    z-index: 2;
}}
.popup-card {{
    border-radius: 14px;
    overflow: hidden;
    box-shadow: 0 30px 70px -10px rgba(0, 0, 0, 0.75), 0 0 0 1px rgba(255, 255, 255, 0.12);
    background: #ffffff;
    transform: rotate(-1.5deg);
}}
</style>
</head>
<body>
<div class="marquee-glow"></div>

<div class="marquee-left">
    <div class="brand-lockup">
        <img src="{icon_b64}" class="brand-icon">
        <span class="brand-name">Canvas Downloader Connector</span>
    </div>
    <h1>Sign in from your Canvas tab <br><span>in a single click.</span></h1>
    <p class="desc">Connects the Canvas Downloader desktop app directly to your active browser session. No manual access tokens to copy, no passwords to re-type.</p>
    
    <div class="check-row">
        <div class="check-item"><span class="check-icon">&#10003;</span> Works on 4,700+ Canvas universities & colleges</div>
        <div class="check-item"><span class="check-icon">&#10003;</span> Strictly local handoff via 127.0.0.1 &bull; Zero external servers</div>
        <div class="check-item"><span class="check-icon">&#10003;</span> Free & Open Source under GPL-3.0</div>
    </div>
</div>

<div class="marquee-right">
    <div class="popup-card">
        <img src="{popup_b64}" style="width: 350px; display: block;">
    </div>
</div>
</body>
</html>"""
    render_html(html, ASSETS_DIR / "marquee_promo_1400x560.png", 1400, 560)


def main():
    print("Generating Chrome Web Store graphics...")
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    generate_screenshot_1()
    generate_screenshot_2()
    generate_screenshot_3()
    generate_screenshot_4()
    generate_screenshot_5()
    generate_promo_tile_small()
    generate_marquee_promo()
    print("Done! All assets generated successfully in:", ASSETS_DIR)


if __name__ == "__main__":
    main()
