import os
import sys
import traceback
import tempfile
import ctypes

# Fix frozen / packaged desktop startup when there is no attached console.
# Kivy can otherwise initialize Python logging handlers with None streams,
# which leads to repeated AttributeError/RecursionError during import.
class _AppNullIO:
    def write(self, *args, **kwargs):
        pass
    def writelines(self, seq):
        pass
    def flush(self):
        pass
    def close(self):
        pass
    def __getattr__(self, name):
        return self

if sys.stdout is None:
    sys.stdout = _AppNullIO()
if sys.stderr is None:
    sys.stderr = _AppNullIO()
if sys.stdin is None:
    try:
        sys.stdin = open(os.devnull, 'r')
    except Exception:
        pass

os.environ.setdefault('KIVY_NO_CONSOLELOG', '1')
os.environ.setdefault('KIVY_NO_FILELOG', '1')
os.environ.setdefault('KIVY_LOG_LEVEL', 'info')
os.environ.setdefault('GST_REGISTRY', os.path.join(tempfile.gettempdir(), 'gst_registry.bin'))

from kivy.utils import platform
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.graphics import Color, Rectangle, Line, Ellipse
from kivy.metrics import dp, sp
from kivy.core.window import Window
from kivy.clock import Clock
# Only set window size on desktop platforms - defer until app is ready
if platform not in ('android', 'ios'):
    Window.minimum_width = 480
    Window.minimum_height = 600
from kivy.uix.popup import Popup
from kivy.core.audio import SoundLoader
# Wrap audio loading so unavailable GStreamer resources don't crash startup
_original_soundloader_load = SoundLoader.load

def _safe_soundloader_load(path):
    try:
        return _original_soundloader_load(path)
    except Exception as e:
        print(f"[SOUND] Exception loading audio {path}: {e}")
        return None

SoundLoader.load = _safe_soundloader_load
# Import your game logic
from sudoku_game_logic import SudokuGameLogic
# Import cross-platform Billing integration
from billing import create_billing_manager
# Import Google Play Review Manager integration
from review_manager import ReviewManager, show_review_prompt_if_eligible
import functools
import time
import threading
import queue


def resource_path(relative_path):
    """Get the correct path for resources (sounds, images) on all platforms.

    When large files have been moved into the install‑time asset pack we
    still want existing code to reference them with their original paths
    (e.g. ``Images/diabolical_level.gif``).  This helper first tests the
    usual location; if the file doesn't exist it will transparently look
    inside ``install_time_assets/`` so the same call works on desktop,
    in debug builds and when the pack is installed on Android.
    """
    from kivy.utils import platform
    # very simple search order:
    # 1. provided path as-is
    # 2. same path under "install_time_assets" subdir
    # 3. fallback rules below (android/pyinstaller)
    #
    # ``os.path.exists`` works on Android assets when the path is
    # prefixed with the asset-relative directory, which is what
    # Buildozer does when copying the string verbatim into the APK.
    # first check filesystem locations (desktop, debug build)
    if os.path.exists(relative_path):
        return relative_path
    alt = os.path.join('install_time_assets', relative_path)
    if os.path.exists(alt):
        return alt

    if platform == 'android':
        # On Android we cannot rely on os.path.exists for APK assets; use
        # resource_find which knows how to look inside the package.
        from kivy.resources import resource_find
        # try the standard path first
        if resource_find(relative_path):
            return relative_path
        # if it's been moved into our pack, try that location
        if resource_find(alt):
            return alt
        # fallback to original; Kivy will log if it's missing
        return relative_path
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath(os.path.dirname(__file__)), relative_path)


def get_nav_bar_height():
    """Return the Android navigation bar height in pixels, or 0 on other platforms.  
    Used to add bottom padding so UI elements are not hidden behind the nav bar."""
    from kivy.utils import platform
    if platform != 'android':
        return 0
    try:
        from jnius import autoclass
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity
        resources = activity.getResources()
        res_id = resources.getIdentifier('navigation_bar_height', 'dimen', 'android')
        if res_id > 0:
            nav_height = resources.getDimensionPixelSize(res_id)
            print(f"[NAV] Navigation bar height: {nav_height}px")
            return nav_height
    except Exception as e:
        print(f"[NAV] Could not detect nav bar height: {e}")
    # Fallback: assume a typical 48dp nav bar
    from kivy.metrics import dp
    return dp(48)


def get_status_bar_height():
    """Return the Android status bar height in pixels, or 0 on other platforms.
    Used to add top padding so UI elements are not hidden behind the status bar,
    especially on Android 15+ where edge-to-edge display is enforced."""
    from kivy.utils import platform
    if platform != 'android':
        return 0
    try:
        from jnius import autoclass
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        activity = PythonActivity.mActivity
        resources = activity.getResources()
        res_id = resources.getIdentifier('status_bar_height', 'dimen', 'android')
        if res_id > 0:
            status_height = resources.getDimensionPixelSize(res_id)
            print(f"[STATUS_BAR] Status bar height: {status_height}px")
            return status_height
    except Exception as e:
        print(f"[STATUS_BAR] Could not detect status bar height: {e}")
    # Fallback: assume a typical 24dp status bar
    from kivy.metrics import dp
    return dp(24)

def get_font_path(font_name):
    """Get font path that works on both desktop and Android"""
    from kivy.utils import platform
    if platform == 'android':
        # On Android, fonts are bundled in the fonts/ asset folder
        # Return the relative path including the folder
        return 'fonts/' + font_name
    else:
        # On desktop, use the fonts folder next to main.py
        font_dir = os.path.join(os.path.dirname(__file__), 'fonts')
        return os.path.join(font_dir, font_name)

# Robust font path for Japanese and Brush Script - use helper function for Android compatibility
FONT_PATH_MSGOTHIC = get_font_path('msgothic.ttc')
FONT_PATH_BRUSHSCI = get_font_path('BRUSHSCI.TTF')
FONT_PATH_PAPYRUS = get_font_path('PAPYRUS.TTF')

# Register Brush font robustly so Android assets are found correctly.
# Try Kivy's resource_find first (works with APK assets), then try common filename
# variants. Log precisely which path was used or why registration failed.
from kivy.core.text import LabelBase
from kivy.resources import resource_find
BRUSH_REGISTERED = False
try:
    candidate_paths = []
    # For Android, the font is packaged as an asset - try multiple resolution strategies
    if platform == 'android':
        # Android: fonts are in the APK assets, accessed via relative paths
        candidate_paths.append('fonts/BRUSHSCI.TTF')
        candidate_paths.append('fonts/brushsci.ttf')
        candidate_paths.append('BRUSHSCI.TTF')
        candidate_paths.append('brushsci.ttf')
    else:
        # Desktop: try resource_find first, then absolute paths
        rf = resource_find(FONT_PATH_BRUSHSCI)
        if rf:
            candidate_paths.append(rf)
        candidate_paths.append(FONT_PATH_BRUSHSCI)
        candidate_paths.append(FONT_PATH_BRUSHSCI.replace('.TTF', '.ttf'))

    found = None
    for p in candidate_paths:
        if not p:
            continue
        try:
            LabelBase.register(name='BrushSci', fn_regular=p)
            BRUSH_REGISTERED = True
            found = p
            print(f"[INFO] Successfully registered Brush font as 'BrushSci' using: {found}")
            break
        except Exception as e:
            # Keep trying but log the failure for debugging
            print(f"[DEBUG] Failed to register Brush font using '{p}': {e}")
            continue
    if not BRUSH_REGISTERED:
        print("[WARN] Brush font not registered (BRUSHSCI not found or registration failed). Candidates tried:", candidate_paths)
except Exception as e:
    print('[WARN] Could not register BrushSci font due to unexpected error:', e)

# Register Papyrus font for the title
PAPYRUS_REGISTERED = False
try:
    papyrus_paths = []
    if platform == 'android':
        papyrus_paths.append('fonts/PAPYRUS.TTF')
        papyrus_paths.append('fonts/papyrus.ttf')
        papyrus_paths.append('PAPYRUS.TTF')
        papyrus_paths.append('papyrus.ttf')
    else:
        rf = resource_find(FONT_PATH_PAPYRUS)
        if rf:
            papyrus_paths.append(rf)
        papyrus_paths.append(FONT_PATH_PAPYRUS)
        papyrus_paths.append(FONT_PATH_PAPYRUS.replace('.TTF', '.ttf'))

    found = None
    for p in papyrus_paths:
        if not p:
            continue
        try:
            LabelBase.register(name='Papyrus', fn_regular=p)
            PAPYRUS_REGISTERED = True
            found = p
            print(f"[INFO] Successfully registered Papyrus font using: {found}")
            break
        except Exception as e:
            print(f"[DEBUG] Failed to register Papyrus font using '{p}': {e}")
            continue
    if not PAPYRUS_REGISTERED:
        print("[WARN] Papyrus font not registered. Candidates tried:", papyrus_paths)
except Exception as e:
    print('[WARN] Could not register Papyrus font due to unexpected error:', e)

# UI sizing constants — tweak these to restore previous proportions
# Increase board default (mobile) to make the board significantly larger
BOARD_DEFAULT_MOBILE = dp(495)  # used for initial mobile board size (increased 10% from 450)
# Minimum allowed board side when auto-scaling
BOARD_MIN_SIDE = dp(308)  # increased 10% from 280
# Digit button sizing - base values (will be scaled for tablets)
DIGIT_BUTTON_SIZE_BASE = dp(34)  # reduced from 36
DIGIT_BUTTON_FONT_BASE = dp(17)  # reduced from 18

def is_tablet():
    """
    Detect if the current device is a tablet based on screen diagonal size.
    Returns True for tablets (7"+), False for phones.
    """
    from kivy.core.window import Window
    from kivy.metrics import Metrics
    
    if platform not in ('android', 'ios'):
        return False  # Desktop is not a tablet
    
    try:
        width_px = Window.width
        height_px = Window.height
        dpi = Metrics.dpi
        if dpi <= 0:
            dpi = 160
        
        diagonal_px = (width_px ** 2 + height_px ** 2) ** 0.5
        diagonal_inches = diagonal_px / dpi
        
        return diagonal_inches >= 7
    except:
        return False

def get_board_max_ratio():
    """
    Get the maximum ratio of screen the board should occupy.
    Tablets get a smaller ratio to leave room for larger buttons.
    """
    if is_tablet():
        return 0.70  # Tablets: board takes 70% max
    else:
        return 0.98  # Phones: board takes 98% max

def get_digit_button_size():
    """Get digit button size, scaled up for tablets."""
    if is_tablet():
        return DIGIT_BUTTON_SIZE_BASE * 1.6  # 60% larger on tablets
    return DIGIT_BUTTON_SIZE_BASE

def get_digit_button_font():
    """Get digit button font size, scaled up for tablets."""
    if is_tablet():
        return DIGIT_BUTTON_FONT_BASE * 1.6  # 60% larger on tablets
    return DIGIT_BUTTON_FONT_BASE

# Keep these for backwards compatibility - they'll be used by DigitButton
DIGIT_BUTTON_SIZE = DIGIT_BUTTON_SIZE_BASE
DIGIT_BUTTON_FONT = DIGIT_BUTTON_FONT_BASE

class SudokuCell(Button):
    def show_neon_outline(self):
        # Draw a purple neon outline around the cell
        if self.neon_outline:
            return  # Already shown
        with self.canvas.after:
            from kivy.graphics import Color, Line
            Color(0.6, 0.2, 0.8, 1)  # Purple
            self.neon_outline = Line(rectangle=(self.x, self.y, self.width, self.height), width=3)
        # Keep outline in sync with cell size/pos
        self.bind(pos=self.update_neon_outline, size=self.update_neon_outline)

    def update_neon_outline(self, *args):
        if self.neon_outline:
            self.neon_outline.rectangle = (self.x, self.y, self.width, self.height)
    def set_user_value(self, digit):
        if self.is_clue:
            return
        self.text = str(digit)
        self.font_name = 'Papyrus'  # User-placed digits use Papyrus font
        self.bold = True
        base = getattr(self, 'base_font_size', self.font_size)
        self.font_size = base * 1.35  # Larger than clue digits
        self.outline_width = 1.2  # Slightly bolder outline for placed digits
        
        # Get reference to app to check dark mode setting
        app = self.app if hasattr(self, 'app') and self.app else None
        dark_mode = app.settings_dark_mode if app and hasattr(app, 'settings_dark_mode') else False
        
        if dark_mode:
            self.color = (1.0, 1.0, 1.0, 1)  # White font for user entries in dark mode
            self.outline_color = (0.7, 0.7, 0.7, 1)  # Subtle outline matching text
            self.background_color = (0.15, 0.15, 0.15, 1)  # Darker gray for user entries
        else:
            self.color = (0.0, 0.3, 1.0, 1)  # Blue for user entries in light mode
            self.outline_color = (0.0, 0.2, 0.7, 1)  # Subtle outline matching text
            self.background_color = (1, 1, 1, 1)  # White for user entries
        
        self.clear_notes()
    
    def restore_user_value(self, digit):
        """Set user value without selection highlighting (for resume functionality)"""
        if self.is_clue:
            return
        self.text = str(digit)
        self.font_name = 'Papyrus'  # User-placed digits use Papyrus font
        self.bold = True
        base = getattr(self, 'base_font_size', self.font_size)
        self.font_size = base * 1.35  # Larger than clue digits
        self.outline_width = 1.2  # Slightly bolder outline for placed digits
        
        # Get reference to app to check dark mode setting
        app = self.app if hasattr(self, 'app') and self.app else None
        dark_mode = app.settings_dark_mode if app and hasattr(app, 'settings_dark_mode') else False
        
        if dark_mode:
            self.color = (1.0, 1.0, 1.0, 1)  # White font for user entries in dark mode
            self.outline_color = (0.7, 0.7, 0.7, 1)  # Subtle outline matching text
            self.background_color = (0.15, 0.15, 0.15, 1)  # Dark background (no highlight)
        else:
            self.color = (0.0, 0.3, 1.0, 1)  # Blue for user entries in light mode
            self.outline_color = (0.0, 0.2, 0.7, 1)  # Subtle outline matching text
            self.background_color = (1, 1, 1, 1)  # White background (no highlight)
        
        self.clear_notes()
    
    def set_as_clue(self, digit):
        self.text = str(digit)
        self.is_clue = True
        
        # Get reference to app to check dark mode setting
        app = self.app if hasattr(self, 'app') and self.app else None
        dark_mode = app.settings_dark_mode if app and hasattr(app, 'settings_dark_mode') else False
        
        if dark_mode:
            self.color = (0.9, 0.9, 0.9, 1)  # Light gray text for clues in dark mode
            self.background_color = (0.2, 0.2, 0.2, 1)  # Dark gray background
        else:
            self.color = (0, 0, 0, 1)  # Black text for clues in light mode
            self.background_color = (1, 1, 1, 1)  # White background
        # self.disabled = True  # Do not disable, allow selection/highlighting
    def highlight_selected(self, selected):
        # Track selection state for note display
        self.is_selected = selected
        
        # Get reference to app to check dark mode setting
        app = self.app if hasattr(self, 'app') and self.app else None
        dark_mode = app.settings_dark_mode if app and hasattr(app, 'settings_dark_mode') else False
        
        if selected:
            if dark_mode:
                self.background_color = (0.3, 0.3, 0.6, 1)  # Dark blue for selection in dark mode
            else:
                self.background_color = (0.9, 0.9, 1, 1)  # Light blue for selection in light mode
        else:
            if dark_mode:
                if self.is_clue:
                    self.background_color = (0.2, 0.2, 0.2, 1)  # Dark gray for clues
                    self.color = (0.9, 0.9, 0.9, 1)  # Light gray text for clues
                else:
                    if self.text and self.text != "0" and self.text != "":
                        self.background_color = (0.15, 0.15, 0.15, 1)  # Darker gray for user entries
                        self.color = (1.0, 1.0, 1.0, 1)  # White text for user entries
                    else:
                        self.background_color = (0.1, 0.1, 0.1, 1)  # Very dark gray for empty
                        self.color = (0.9, 0.9, 0.9, 1)  # Light gray text for empty
            else:
                self.background_color = (1, 1, 1, 1)  # White for unselected in light mode
                if self.is_clue:
                    self.color = (0, 0, 0, 1)  # Black text for clues
                else:
                    if self.text and self.text != "0" and self.text != "":
                        self.color = (0.0, 0.3, 1.0, 1)  # Blue text for user entries
                    else:
                        self.color = (0, 0, 0, 1)  # Black text for empty
        
        # Update notes display colors when selection state changes
        self.update_notes_display()
    def update_cell_border(self, *args):
        # Update the border and highlights/shadows when the cell is resized or moved
        if hasattr(self, 'cell_border'):
            self.cell_border.rectangle = (self.x, self.y, self.width, self.height)
        if hasattr(self, 'highlight_top'):
            self.highlight_top.points = [self.x, self.y + self.height, self.x + self.width, self.y + self.height]
        if hasattr(self, 'highlight_left'):
            self.highlight_left.points = [self.x, self.y, self.x, self.y + self.height]
        if hasattr(self, 'shadow_bottom'):
            self.shadow_bottom.points = [self.x, self.y, self.x + self.width, self.y]
        if hasattr(self, 'shadow_right'):
            self.shadow_right.points = [self.x + self.width, self.y, self.x + self.width, self.y + self.height]
    def on_cell_click(self, *args):
        app = App.get_running_app()
        if hasattr(app, 'select_cell'):
            app.select_cell(self.row, self.col)
    def hide_neon_outline(self):
        if self.neon_outline:
            self.canvas.after.remove(self.neon_outline)
            self.neon_outline = None
            self.unbind(pos=self.update_neon_outline, size=self.update_neon_outline)
    """Individual cell in the Sudoku grid"""
    def __init__(self, row, col, app=None, **kwargs):
        super().__init__(**kwargs)
        self.app = app  # Reference to the SudokuApp instance
        self.row = row
        self.col = col
        self.is_clue = False
        self.font_size = dp(24)
        self.background_color = (1, 1, 1, 1)  # White background
        self.background_normal = ''  # Disable default button background
        self.background_down = ''    # Disable default button pressed background
        self.color = (0, 0, 0, 1)  # Black text
        self.bind(on_release=self.on_cell_click)
        # Add tan border around each cell with 3D embossed effect
        with self.canvas.after:
            Color(0.82, 0.71, 0.55, 1)  # Tan color for main border
            self.cell_border = Line(rectangle=(self.x, self.y, self.width, self.height), width=1)
            Color(0.95, 0.85, 0.7, 1)  # Light tan for highlight
            self.highlight_top = Line(points=[self.x, self.y + self.height, self.x + self.width, self.y + self.height], width=2)
            self.highlight_left = Line(points=[self.x, self.y, self.x, self.y + self.height], width=2)
            Color(0.6, 0.5, 0.35, 1)  # Dark tan for shadow
            self.shadow_bottom = Line(points=[self.x, self.y, self.x + self.width, self.y], width=2)
            self.shadow_right = Line(points=[self.x + self.width, self.y, self.x + self.width, self.y + self.height], width=2)
        self.bind(pos=self.update_cell_border, size=self.update_cell_border)
        # Neon green outline (feature not implemented)
        self.neon_outline = None
        # self.bind(pos=self.update_neon_outline, size=self.update_neon_outline)  # Removed: method not defined
        # Notes: store as set of digits
        self.notes = set()
        self.notes_labels = [None] * 9  # For 9 positions
        self.notes_grid = None
        self.is_selected = False  # Track selection state for note colors
        self.bind(size=self.update_notes_display, pos=self.update_notes_display)
    def add_note(self, digit):
        if 1 <= digit <= 9:
            self.notes.add(digit)
            self.update_notes_display()
    def remove_note(self, digit):
        if digit in self.notes:
            self.notes.remove(digit)
            self.update_notes_display()
    def clear_notes(self):
        self.notes.clear()
        self.update_notes_display()

    def clear_cell(self):
        self.text = ""
        self.is_clue = False
        self.font_name = 'Roboto'  # Reset to default font
        self.bold = False
        self.font_size = getattr(self, 'base_font_size', self.font_size)  # Restore base size
        self.outline_width = 0  # Reset outline
        self.clear_notes()
        self.highlight_selected(False)
        # Reset any other custom state here if needed
    def update_notes_display(self, *args):
        # Remove previous notes labels
        if self.notes_grid:
            self.remove_widget(self.notes_grid)
            self.notes_grid = None
        # Only show notes if cell is empty and not a clue
        if not self.text and not self.is_clue and self.notes:
            print(f"[CELL] Creating notes display for notes: {self.notes}")
            from kivy.uix.gridlayout import GridLayout
            from kivy.uix.label import Label
            from kivy.graphics import Color, Rectangle
            self.notes_grid = GridLayout(cols=3, rows=3, spacing=0, padding=0,
                                         size_hint=(1, 1), pos=self.pos, size=self.size)
            
            # Get the currently highlighted digit if any
            highlighted_digit = None
            if self.app:
                highlighted_digit = self.app.get_currently_highlighted_digit()
            
            # Get reference to app to check dark mode setting
            app = self.app if hasattr(self, 'app') and self.app else None
            dark_mode = app.settings_dark_mode if app and hasattr(app, 'settings_dark_mode') else False
            
            # Create 9 positions
            for i in range(1, 10):
                if i in self.notes:
                    # Check if this note should be highlighted
                    if highlighted_digit == i:
                        # For highlighted notes, use white font with purple background
                        if dark_mode:
                            color = (1.0, 1.0, 1.0, 1)  # White font
                        else:
                            color = (1.0, 1.0, 1.0, 1)  # White font for contrast against purple
                    else:
                        # Normal notes - check if cell is selected
                        if getattr(self, 'is_selected', False):
                            # When cell is selected (purple/dark background), use white text for visibility
                            if dark_mode:
                                color = (1.0, 1.0, 1.0, 1)  # White text for visibility on purple selection
                            else:
                                color = (0.0, 0.0, 0.2, 1)  # Dark blue for light mode
                        else:
                            # When cell is not selected, use visible light text in dark mode for visibility
                            if dark_mode:
                                color = (0.7, 0.7, 0.7, 1)  # Light gray for notes in dark mode - visible on dark background
                            else:
                                color = (0.0, 0.0, 0.2, 1)  # Very dark blue for notes in light mode
                    
                    lbl = Label(text=str(i), font_size=dp(12), color=color,
                                font_name='Papyrus', bold=True,
                                halign='center', valign='middle', size_hint=(1, 1))
                    
                    # Add purple background for highlighted notes
                    if highlighted_digit == i:
                        with lbl.canvas.before:
                            Color(0.6, 0.2, 0.8, 1)  # Purple background
                            lbl._highlight_rect = Rectangle(size=lbl.size, pos=lbl.pos)
                        lbl.bind(size=lambda inst, val, rect=lbl._highlight_rect: setattr(rect, 'size', val))
                        lbl.bind(pos=lambda inst, val, rect=lbl._highlight_rect: setattr(rect, 'pos', val))
                else:
                    lbl = Label(text='', font_size=dp(12), size_hint=(1, 1))
                lbl.text_size = (None, None)
                self.notes_grid.add_widget(lbl)
            
            # Actually add the notes grid to the cell widget!
            self.add_widget(self.notes_grid)
            print(f"[CELL] Notes grid added to cell with {len(self.notes)} notes")

        # Add a little space before button
        # (Do not set background_color here; highlight_selected controls selection highlight)
    def mark_as_mistake(self):
        """Mark this cell as containing a mistake"""
        self.is_mistake = True
        self.background_color = (0.5, 0, 0, 1)  # Maroon background
        self.color = (1, 1, 1, 1)  # White text
    def clear_mistake(self):
        """Clear mistake marking from this cell"""
        if hasattr(self, 'is_mistake'):
            self.is_mistake = False
        
        # Get reference to app to check dark mode setting
        app = self.app if hasattr(self, 'app') and self.app else None
        dark_mode = app.settings_dark_mode if app and hasattr(app, 'settings_dark_mode') else False
        
        if dark_mode:
            if self.is_clue:
                self.background_color = (0.2, 0.2, 0.2, 1)  # Dark gray for clues
                self.color = (0.9, 0.9, 0.9, 1)  # Light gray text for clues
            else:
                if self.text and self.text != "0" and self.text != "":
                    self.background_color = (0.15, 0.15, 0.15, 1)  # Darker gray for user entries
                    self.color = (1.0, 1.0, 1.0, 1)  # White font for user entries
                else:
                    self.background_color = (0.1, 0.1, 0.1, 1)  # Very dark gray for empty
                    self.color = (0.9, 0.9, 0.9, 1)  # Light gray text
        else:
            self.background_color = (1, 1, 1, 1)  # White background for light mode
            if self.is_clue:
                self.color = (0, 0, 0, 1)  # Black text for clues
            else:
                if self.text and self.text != "0" and self.text != "":
                    self.color = (0.0, 0.3, 1.0, 1)  # Blue for user entries
                else:
                    self.color = (0, 0, 0, 1)  # Black text for empty
    def set_given_digit(self, digit):
        """Set a given/clue digit"""
        self.set_as_clue(digit)
    def clear_digit(self):
        """Clear the digit from the cell"""
        if not self.is_clue:
            self.text = ""
            self.font_name = 'Roboto'  # Reset to default font
            self.bold = False
            self.font_size = getattr(self, 'base_font_size', self.font_size)  # Restore base size
            self.outline_width = 0  # Reset outline
            
            # Get reference to app to check dark mode setting
            app = self.app if hasattr(self, 'app') and self.app else None
            dark_mode = app.settings_dark_mode if app and hasattr(app, 'settings_dark_mode') else False
            
            if dark_mode:
                self.color = (0.9, 0.9, 0.9, 1)  # Light text for dark mode
                self.background_color = (0.1, 0.1, 0.1, 1)  # Very dark gray for empty cells
            else:
                self.color = (0, 0, 0, 1)  # Black text for light mode
                self.background_color = (1, 1, 1, 1)  # White background for light mode
    
    def highlight_note(self, digit, highlight=True):
        """Highlight or unhighlight a specific note digit with purple background"""
        if not self.notes_grid or digit not in self.notes:
            return
        
        # Get reference to app to check dark mode setting
        app = self.app if hasattr(self, 'app') and self.app else None
        dark_mode = app.settings_dark_mode if app and hasattr(app, 'settings_dark_mode') else False
        
        # Find the label for this digit in the notes grid
        for i, label in enumerate(self.notes_grid.children):
            # Grid children are in reverse order (9, 8, 7, ..., 1)
            note_digit = 9 - i
            if note_digit == digit:
                if highlight:
                    # Add purple background and set white font
                    from kivy.graphics import Color, Rectangle
                    label.canvas.before.clear()
                    with label.canvas.before:
                        Color(0.6, 0.2, 0.8, 1)  # Purple background
                        label._highlight_rect = Rectangle(size=label.size, pos=label.pos)
                    label.bind(size=lambda inst, val, rect=label._highlight_rect: setattr(rect, 'size', val))
                    label.bind(pos=lambda inst, val, rect=label._highlight_rect: setattr(rect, 'pos', val))
                    
                    if dark_mode:
                        label.color = (1.0, 1.0, 1.0, 1)  # White font in dark mode
                    else:
                        label.color = (1.0, 1.0, 1.0, 1)  # White font for contrast against purple
                else:
                    # Remove purple background and restore normal color
                    label.canvas.before.clear()
                    if hasattr(label, '_highlight_rect'):
                        delattr(label, '_highlight_rect')
                    
                    if dark_mode:
                        label.color = (1.0, 1.0, 1.0, 1)  # White for notes in dark mode
                    else:
                        label.color = (0.0, 0.0, 0.8, 1)  # Default blue for notes in light mode
                break
    
    def clear_all_note_highlights(self):
        """Clear purple highlighting from all notes in this cell"""
        if not self.notes_grid:
            return
        
        # Get reference to app to check dark mode setting
        app = self.app if hasattr(self, 'app') and self.app else None
        dark_mode = app.settings_dark_mode if app and hasattr(app, 'settings_dark_mode') else False
        
        for label in self.notes_grid.children:
            # Remove any purple background
            label.canvas.before.clear()
            if hasattr(label, '_highlight_rect'):
                delattr(label, '_highlight_rect')
            
            # Restore normal text color
            if dark_mode:
                label.color = (1.0, 1.0, 1.0, 1)  # White for notes in dark mode
            else:
                label.color = (0.0, 0.0, 0.8, 1)  # Default blue for notes in light mode
class SudokuSubGrid(GridLayout):
    """3x3 subgrid with thick borders"""
    def __init__(self, start_row, start_col, app=None, **kwargs):
        super().__init__(**kwargs)
        self.app = app  # Reference to the SudokuApp instance
        self.cols = 3
        self.rows = 3
        self.spacing = dp(1)  # Thin lines between cells
        self.start_row = start_row
        self.start_col = start_col
        # Add tan borders around each subgrid
        with self.canvas.after:
            Color(0.82, 0.71, 0.55, 1)  # Tan color for subgrid borders
            self.subgrid_border = []
        self.bind(pos=self.update_subgrid_border, size=self.update_subgrid_border)
        # Create 3x3 grid of cells
        self.cells = []
        for row in range(3):
            cell_row = []
            for col in range(3):
                cell = SudokuCell(start_row + row, start_col + col, app=self.app)
                cell_row.append(cell)
                self.add_widget(cell)
            self.cells.append(cell_row)
    def update_subgrid_border(self, *args):
        """Update subgrid border lines"""
        self.canvas.after.clear()
        with self.canvas.after:
            Color(0.82, 0.71, 0.55, 1)  # Tan color
            # Draw borders around the subgrid
            Line(rectangle=(self.x, self.y, self.width, self.height), width=1)

class SudokuBoard(GridLayout):
    """Main 9x9 Sudoku board made of 9 subgrids"""
    def __init__(self, app=None, **kwargs):
        super().__init__(**kwargs)
        self.app = app  # Reference to the SudokuApp instance
        self.cols = 3
        self.rows = 3
        self.spacing = dp(5)
        self.padding = dp(5)
        # Responsive: let parent control size, but keep square aspect
        if platform in ('android', 'ios'):
            self.size_hint = (None, None)
            # Use a slightly larger default for mobile so the board appears larger
            self.size = (BOARD_DEFAULT_MOBILE, BOARD_DEFAULT_MOBILE)
            self.pos_hint = {'center_x': 0.5, 'center_y': 0.5}
        else:
            # On desktop, let the board expand to fill width (with margin), keep square
            self.size_hint = (None, None)
            # Margin: 0.5% of width on each side (1% total)
            margin = Window.width * 0.005
            # Board should fill 99% of window width, unless height is limiting
            max_board_side = Window.width * 0.99
            if Window.height < max_board_side:
                board_side = Window.height * 0.99
            else:
                board_side = max_board_side
            self.size = (board_side, board_side)
            self.pos_hint = {'center_x': 0.5, 'center_y': 0.5}
        self.bind(parent=self._update_square_size)
        Window.bind(size=self._update_square_size)
        # Create 9 subgrids (3x3 arrangement of 3x3 subgrids) ONCE
        self.subgrids = []
        for big_row in range(3):
            subgrid_row = []
            for big_col in range(3):
                start_row = big_row * 3
                start_col = big_col * 3
                subgrid = SudokuSubGrid(start_row, start_col, app=self.app)
                subgrid_row.append(subgrid)
                self.add_widget(subgrid)
            self.subgrids.append(subgrid_row)

        # Create background and border graphics ONCE
        with self.canvas.before:
            from kivy.graphics import Color, Rectangle
            self._bg_color = Color(0.3, 0.3, 0.3, 1)
            self.bg_rect = Rectangle(size=self.size, pos=self.pos)
        with self.canvas.after:
            from kivy.graphics import Color, Line
            self._border_color = Color(0.82, 0.71, 0.55, 1)
            self.border = Line(rectangle=(self.x, self.y, self.width, self.height), width=3)
        self.bind(pos=self.update_graphics, size=self.update_graphics)

    def _update_square_size(self, *args):
        parent = self.parent
        min_side = BOARD_MIN_SIDE  # Slightly larger minimum side for small screens
        board_ratio = get_board_max_ratio()  # Use tablet-aware ratio
        if platform in ('android', 'ios'):
            max_side = min(Window.width, Window.height) * board_ratio
            if parent:
                avail_w, avail_h = parent.width, parent.height
                side = max(min_side, min(max_side, board_ratio * min(avail_w, avail_h)))
                self.size = (side, side)
                self.pos = (
                    parent.x + (avail_w - side) / 2,
                    parent.y + (avail_h - side) / 2
                )
            else:
                side = max(min_side, min(max_side, board_ratio * min(Window.width, Window.height)))
                self.size = (side, side)
        else:
            # Desktop: fill width with margin, keep square
            margin = Window.width * 0.005
            if parent:
                avail_w, avail_h = parent.width, parent.height
                max_board_side = avail_w * 0.99
                if avail_h < max_board_side:
                    side = avail_h * 0.99
                else:
                    side = max_board_side
                side = max(min_side, side)
                self.size = (side, side)
                # Optionally, adjust window height if board would not fit with margin
                if side > avail_h * 0.99:
                    from kivy.core.window import Window as KivyWindow
                    new_height = int(side / 0.99 + dp(180))
                    if KivyWindow.height < new_height:
                        KivyWindow.size = (KivyWindow.width, new_height)
            else:
                max_board_side = Window.width * 0.99
                if Window.height < max_board_side:
                    side = Window.height * 0.99
                else:
                    side = max_board_side
                side = max(min_side, side)
                self.size = (side, side)
        # Only update graphics, do not recreate them
        self.update_graphics()
        # Dynamically scale cell font sizes
        cell_font = max(dp(12), self.size[0] / 18)
        for subgrid_row in self.subgrids:
            for subgrid in subgrid_row:
                for cell_row in subgrid.cells:
                    for cell in cell_row:
                        cell.base_font_size = cell_font  # Store base size for user-digit scaling
                        if not cell.is_clue and cell.text and cell.text not in ('', '0'):
                            cell.font_size = cell_font * 1.35  # User-placed digits larger
                        else:
                            cell.font_size = cell_font
    def update_graphics(self, *args):
        """Update background and border when size/position changes"""
        if hasattr(self, 'bg_rect'):
            self.bg_rect.size = self.size
            self.bg_rect.pos = self.pos
        if hasattr(self, 'border'):
            self.border.rectangle = (self.x, self.y, self.width, self.height)
    def get_cell(self, row, col):
        """Get cell at specific row, col"""
        big_row, small_row = divmod(row, 3)
        big_col, small_col = divmod(col, 3)
        return self.subgrids[big_row][big_col].cells[small_row][small_col]
    def set_puzzle(self, puzzle, solution):
        """Set up the board with a new puzzle"""
        # Reset solution revealed flag when starting a new puzzle
        if hasattr(self, 'solution_revealed'):
            self.solution_revealed = False
        for row in range(9):
            for col in range(9):
                cell = self.get_cell(row, col)
                cell.clear_cell()
                cell.is_clue = False
                if puzzle[row][col] != 0:
                    cell.set_as_clue(puzzle[row][col])

class DigitButton(Button):
    """Number button (1-9) for input"""
    def __init__(self, digit, **kwargs):
        super().__init__(**kwargs)
        self.digit = digit
        self.text = str(digit)
        # Use dynamic sizing for tablet support
        btn_size = get_digit_button_size()
        btn_font = get_digit_button_font()
        self.font_size = btn_font
        self.background_color = (0.75, 0.75, 0.75, 1)
        self.background_normal = ''
        self.background_down = ''
        self.color = (0, 0, 0, 1)
        self.size_hint = (None, None)
        self.size = (btn_size, btn_size)
        self.bind(on_release=self.on_digit_click)
        # Add 3D embossed effect to digit buttons
        # Use dp() for line widths to scale properly on high-DPI screens
        emboss_width = max(1.5, dp(1.5))
        with self.canvas.after:
            Color(0.5, 0.5, 0.5, 1)
            self.button_border = Line(rectangle=(self.x, self.y, self.width, self.height), width=1)
            Color(0.9, 0.9, 0.9, 1)
            self.button_highlight_top = Line(points=[self.x, self.y + self.height, self.x + self.width, self.y + self.height], width=emboss_width)
            self.button_highlight_left = Line(points=[self.x, self.y, self.x, self.y + self.height], width=emboss_width)
            Color(0.4, 0.4, 0.4, 1)
            self.button_shadow_bottom = Line(points=[self.x, self.y, self.x + self.width, self.y], width=emboss_width)
            self.button_shadow_right = Line(points=[self.x + self.width, self.y, self.x + self.width, self.y + self.height], width=emboss_width)
        self.bind(pos=self.update_button_border, size=self.update_button_border)
        # Disable dynamic button sizing to maintain consistent spacing
        # Window.bind(size=self._update_button_size)

    def _update_button_size(self, *args):
        # Disabled: Make digit buttons scale with window/board size
        # This was causing buttons to lose spacing when window expanded
        pass
        # side = max(dp(28), min(dp(60), Window.width / 13, Window.height / 18))
        # self.size = (side, side)
        # self.font_size = max(dp(12), side * 0.5)
    def update_button_border(self, *args):
        self.button_border.rectangle = (self.x, self.y, self.width, self.height)
        self.button_highlight_top.points = [self.x, self.y + self.height, self.x + self.width, self.y + self.height]
        self.button_highlight_left.points = [self.x, self.y, self.x, self.y + self.height]
        self.button_shadow_bottom.points = [self.x, self.y, self.x + self.width, self.y]
        self.button_shadow_right.points = [self.x + self.width, self.y, self.x + self.width, self.y + self.height]
    def on_digit_click(self, instance):
        app = App.get_running_app()
        if hasattr(app, 'handle_digit_button'):
            app.handle_digit_button(self.digit)


import os

class SudokuApp(App):
    def _get_device_scale(self):
        """
        Calculate UI scale factor based on device type (phone vs tablet).
        Returns a scale factor that makes UI elements appropriately sized.
        """
        from kivy.core.window import Window
        from kivy.utils import platform as kivy_platform
        from kivy.metrics import Metrics
        
        if kivy_platform not in ('android', 'ios'):
            return 1.0  # Desktop
        
        # Calculate screen diagonal in inches
        try:
            # Get screen dimensions in pixels
            width_px = Window.width
            height_px = Window.height
            
            # Get DPI (dots per inch)
            dpi = Metrics.dpi
            if dpi <= 0:
                dpi = 160  # Default fallback
            
            # Calculate diagonal in inches
            diagonal_px = (width_px ** 2 + height_px ** 2) ** 0.5
            diagonal_inches = diagonal_px / dpi
            
            print(f"[SCALE] Screen: {width_px}x{height_px}, DPI: {dpi}, Diagonal: {diagonal_inches:.1f} inches")
            
            # Determine device type and scale
            if diagonal_inches >= 9:
                # Large tablet (10"+)
                scale = 1.2
                print("[SCALE] Device type: Large tablet, scale=1.2")
            elif diagonal_inches >= 7:
                # Small tablet (7-9")
                scale = 1.0
                print("[SCALE] Device type: Small tablet, scale=1.0")
            else:
                # Phone
                scale = 0.7
                print("[SCALE] Device type: Phone, scale=0.7")
            
            return scale
            
        except Exception as e:
            print(f"[SCALE] Error detecting device type: {e}, defaulting to phone scale")
            return 0.7
    
    def build_welcome_screen(self):
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.metrics import dp
        from kivy.uix.floatlayout import FloatLayout
        from kivy.uix.image import Image

        # FloatLayout for layering background and UI
        root = FloatLayout()

        # Water drop background image
        bg_img = Image(source=resource_path('Images/water_drop.png'), allow_stretch=True, keep_ratio=False, size_hint=(1, 1), pos_hint={'x': 0, 'y': 0})
        root.add_widget(bg_img)

        # Platform-specific scale factor for welcome screen (now with tablet detection)
        mobile_scale = self._get_device_scale()

        # Main vertical layout for UI with transparent background
        # Add extra padding on Android to keep content clear of system bars
        _welcome_nav_pad = get_nav_bar_height()
        _welcome_status_pad = get_status_bar_height()
        _pad = dp(30 * mobile_scale)
        layout = BoxLayout(orientation='vertical', padding=[_pad, _pad + _welcome_status_pad, _pad, _pad + _welcome_nav_pad], spacing=dp(20 * mobile_scale), size_hint=(1, 1), pos_hint={'x': 0, 'y': 0})
        from kivy.graphics import Color, Rectangle
        with layout.canvas.before:
            Color(1, 1, 1, 0)  # Fully transparent
            self._welcome_bg_rect = Rectangle(size=layout.size, pos=layout.pos)
        layout.bind(size=lambda inst, val: setattr(self._welcome_bg_rect, 'size', val))
        layout.bind(pos=lambda inst, val: setattr(self._welcome_bg_rect, 'pos', val))

        # Title (updated) - use registered 'BrushSci' font if registration succeeded, otherwise fall back
        title_font_used = "default"
        try:
            # Try registered Papyrus font first
            if PAPYRUS_REGISTERED:
                print(f"[FONT] Using registered Papyrus font for title")
                title_label = Label(
                    text="Serene Sudoku",
                    font_size=dp(70 * mobile_scale),
                    font_name='Papyrus',
                    color=(1, 1, 1, 1),
                    size_hint=(1, None),
                    height=dp(120 * mobile_scale)
                )
                title_font_used = "Papyrus (registered)"
            else:
                # Registration failed - try direct paths as last resort
                print(f"[FONT] Papyrus not registered, trying direct paths")
                # On Android, use the relative asset path directly
                if platform == 'android':
                    papyrus_candidates = ['fonts/PAPYRUS.TTF', 'fonts/papyrus.ttf', FONT_PATH_PAPYRUS]
                else:
                    # Desktop: try resource_find or absolute path
                    papyrus_path = resource_find(FONT_PATH_PAPYRUS) or FONT_PATH_PAPYRUS
                    papyrus_candidates = [papyrus_path]
                
                title_label = None
                for papyrus_path in papyrus_candidates:
                    try:
                        print(f"[FONT] Trying direct Papyrus path for title: {papyrus_path}")
                        title_label = Label(
                            text="Serene Sudoku",
                            font_size=dp(70 * mobile_scale),
                            font_name=papyrus_path,
                            color=(1, 1, 1, 1),
                            size_hint=(1, None),
                            height=dp(120 * mobile_scale)
                        )
                        title_font_used = f"Direct path: {papyrus_path}"
                        print(f"[FONT] Successfully created title with font: {papyrus_path}")
                        break
                    except Exception as e:
                        print(f"[FONT] Failed to use {papyrus_path}: {e}")
                        continue
                
                # If all paths failed, fall back to default
                if title_label is None:
                    raise Exception("All font paths failed")
        except Exception as e:
            print(f"[WARN] Could not use Brush font; falling back to default: {e}")
            import traceback
            traceback.print_exc()
            title_label = Label(
                text="Serene Sudoku",
                font_size=dp(70 * mobile_scale),
                color=(1, 1, 1, 1),
                size_hint=(1, None),
                height=dp(120 * mobile_scale)
            )
            title_font_used = "default (error)"
        print(f"[FONT] Title font used: {title_font_used}")
        layout.add_widget(title_label)

        # Japanese translation
        layout.add_widget(Label(
            text="静かな数独",
            font_size=dp(48 * mobile_scale),
            font_name="msgothic",  # Use registered font name
            color=(1, 1, 1, 1),
            size_hint=(1, None),
            height=dp(80 * mobile_scale)
        ))

        # "Choose your path..."
        layout.add_widget(Label(
            text="Choose your path...",
            font_size=dp(22 * mobile_scale),
            color=(0.8, 0.9, 0.8, 1),
            size_hint=(1, None),
            height=dp(40 * mobile_scale)
        ))

        # Difficulty buttons with fixed width container
        difficulties = ["Easy", "Moderate", "Tough", "Expert", "Evil", "Diabolical"]
        self.difficulty_buttons = []
        
        # Create a centered container for difficulty buttons
        from kivy.uix.anchorlayout import AnchorLayout
        buttons_container = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, None), height=dp((50 * mobile_scale) * len(difficulties) + (20 * mobile_scale) * (len(difficulties) - 1)))
        buttons_layout = BoxLayout(orientation='vertical', spacing=dp(20 * mobile_scale), size_hint=(None, None), width=dp(300 * mobile_scale))
        buttons_layout.height = dp((50 * mobile_scale) * len(difficulties) + (20 * mobile_scale) * (len(difficulties) - 1))
        
        for diff in difficulties:
            btn = Button(
                text=diff,
                font_size=dp(24 * mobile_scale),
                background_color=(0.15, 0.4, 0.15, 1),  # Unselected color
                color=(1, 1, 1, 1),
                size_hint=(1, None),
                height=dp(50 * mobile_scale)
            )
            btn.is_selected = False
            def add_3d_effect(button):
                from kivy.graphics import Color, Line, Rectangle
                with button.canvas.after:
                    # Main border
                    Color(0.5, 0.5, 0.5, 1)
                    button._border = Line(rectangle=(button.x, button.y, button.width, button.height), width=1)
                    # 3D embossed effect - light highlight on top/left, dark shadow on bottom/right
                    Color(0.9, 0.9, 0.9, 1)
                    button._highlight_top = Line(points=[button.x, button.y + button.height, button.x + button.width, button.y + button.height], width=2)
                    button._highlight_left = Line(points=[button.x, button.y, button.x, button.y + button.height], width=2)
                    Color(0.4, 0.4, 0.4, 1)
                    button._shadow_bottom = Line(points=[button.x, button.y, button.x + button.width, button.y], width=2)
                    button._shadow_right = Line(points=[button.x + button.width, button.y, button.x + button.width, button.y + button.height], width=2)
                    # Depressed effect for selected button
                    if button.is_selected:
                        Color(0, 0, 0, 0.18)
                        button._depressed_overlay = Rectangle(pos=(button.x+2, button.y+2), size=(button.width-4, button.height-4))
                    else:
                        button._depressed_overlay = None
                def update_btn_border(instance, *args):
                    button._border.rectangle = (button.x, button.y, button.width, button.height)
                    button._highlight_top.points = [button.x, button.y + button.height, button.x + button.width, button.y + button.height]
                    button._highlight_left.points = [button.x, button.y, button.x, button.y + button.height]
                    button._shadow_bottom.points = [button.x, button.y, button.x + button.width, button.y]
                    button._shadow_right.points = [button.x + button.width, button.y, button.x + button.width, button.y + button.height]
                    # Update depressed overlay position if it exists
                    if hasattr(button, '_depressed_overlay') and button._depressed_overlay:
                        button._depressed_overlay.pos = (button.x+2, button.y+2)
                        button._depressed_overlay.size = (button.width-4, button.height-4)
                button.bind(pos=update_btn_border, size=update_btn_border)
            add_3d_effect(btn)
            def on_press(instance, d=diff):
                self.select_difficulty(d)
            btn.bind(on_press=on_press)
            self.difficulty_buttons.append(btn)
            buttons_layout.add_widget(btn)
        
        # Add the buttons layout to the centered container, then add container to main layout
        buttons_container.add_widget(buttons_layout)
        
        # Create custom RelativeLayout that allows touches on children outside its bounds
        from kivy.uix.relativelayout import RelativeLayout
        class TouchableRelativeLayout(RelativeLayout):
            def collide_point(self, x, y):
                # Allow touches within our bounds OR within any child's bounds
                if super().collide_point(x, y):
                    return True
                for child in self.children:
                    local_x, local_y = child.to_widget(x, y, relative=False)
                    if child.collide_point(local_x, local_y):
                        return True
                return False

            def on_touch_down(self, touch):
                if super().on_touch_down(touch):
                    return True
                for child in self.children:
                    local_x, local_y = child.to_widget(touch.x, touch.y, relative=False)
                    if child.collide_point(local_x, local_y):
                        if child.on_touch_down(touch):
                            return True
                return False

            def on_touch_move(self, touch):
                if super().on_touch_move(touch):
                    return True
                for child in self.children:
                    local_x, local_y = child.to_widget(touch.x, touch.y, relative=False)
                    if child.collide_point(local_x, local_y):
                        if child.on_touch_move(touch):
                            return True
                return False

            def on_touch_up(self, touch):
                if super().on_touch_up(touch):
                    return True
                for child in self.children:
                    local_x, local_y = child.to_widget(touch.x, touch.y, relative=False)
                    if child.collide_point(local_x, local_y):
                        if child.on_touch_up(touch):
                            return True
                return False
        
        buttons_relative = TouchableRelativeLayout(size_hint=(1, None), height=dp((50 * mobile_scale) * len(difficulties) + (20 * mobile_scale) * (len(difficulties) - 1)))
        buttons_relative.add_widget(buttons_container)
        
        # Add How to Play icon with text labels
        how_to_play_btn = Button(
            background_normal=resource_path('Images/how_to_play_icon.png'),
            background_down=resource_path('Images/how_to_play_icon.png'),
            size_hint=(None, None),
            size=(dp(70 * mobile_scale), dp(70 * mobile_scale))
        )
        
        # Create "How to" label
        icon_size = dp(70 * mobile_scale)
        text_font_size = (icon_size / 6) * 1.65 * 0.8  # Font size calculation
        
        how_to_label = Label(
            text='How to',
            color=(1, 1, 1, 1),  # White
            font_size=text_font_size,
            size_hint=(None, None),
            size=(icon_size * 1.98, text_font_size),  # Height matches font size
            halign='center',
            valign='top',
            padding=(0, 0)
        )
        how_to_label.bind(size=how_to_label.setter('text_size'))
        
        # Create "Play" label
        play_label = Label(
            text='Play',
            color=(1, 1, 1, 1),  # White
            font_size=text_font_size,
            size_hint=(None, None),
            size=(icon_size * 1.98, text_font_size),  # Height matches font size
            halign='center',
            valign='top',
            padding=(0, 0)
        )
        play_label.bind(size=play_label.setter('text_size'))

        # TEMP: touch logger to verify taps reach the icon on mobile
        def _log_touch_down(instance, touch):
            if instance.collide_point(*touch.pos):
                print(f"[ICON] on_touch_down at {touch.pos}")
            return False
        how_to_play_btn.bind(on_touch_down=_log_touch_down)
        
        def position_icon(*args):
            # Position icon's top edge aligned with the top edge of the Easy button with left margin
            icon_width = how_to_play_btn.width
            icon_height = how_to_play_btn.height
            button_height = dp(50 * mobile_scale)
            
            # Easy button top edge is at: buttons_relative.height - button_height
            # Icon y position should be set to that same value
            how_to_play_btn.x = dp(3)  # Slightly away from the edge for reliable taps
            how_to_play_btn.y = buttons_relative.height - button_height  # Top edge aligned with Easy button top
            
            # Position "How to" label centered and flush below icon
            # Add offset to compensate for transparent padding in icon image
            icon_padding_offset = icon_height * 0.3  # Adjust for image padding
            how_to_label.x = how_to_play_btn.x + (icon_width - how_to_label.width) / 2
            how_to_label.y = how_to_play_btn.y - how_to_label.height + icon_padding_offset
            
            # Position "Play" label centered and flush below "How to" label
            play_label.x = how_to_play_btn.x + (icon_width - play_label.width) / 2
            play_label.y = how_to_label.y - play_label.height
            
            print(f"[ICON] Positioned at y={how_to_play_btn.y}, x={how_to_play_btn.x}")

            # Keep the hitbox aligned with the icon
            icon_hit_btn.x = how_to_play_btn.x
            icon_hit_btn.y = how_to_play_btn.y
        
        from kivy.clock import Clock
        Clock.schedule_once(position_icon, 0.1)
        how_to_play_btn.bind(size=position_icon)
        def open_tutorial(instance):
            self._open_tutorial()
        how_to_play_btn.bind(on_press=open_tutorial)
        buttons_relative.add_widget(how_to_play_btn)
        buttons_relative.add_widget(how_to_label)
        buttons_relative.add_widget(play_label)

        # Root-level touch routing to ensure taps reach the icon on mobile
        self.how_to_play_btn = how_to_play_btn
        if not getattr(self, '_icon_touch_bound', False):
            from kivy.core.window import Window
            def _global_icon_touch(window, touch):
                # Enable global listener ALL platforms to verification.
                # if platform != 'android':
                #    return False

                try:
                    btn = getattr(self, 'how_to_play_btn', None)
                    # verify button exists and is actually in the widget tree
                    # If how_to_play_btn is None or has no parent, we're not on welcome screen
                    if not btn or not btn.parent:
                        return False
                    
                    # Verify the button's parent is actually visible/in the tree
                    # This prevents ghost touches when on puzzle screens
                    parent = btn.parent
                    if not parent or not parent.parent:
                        return False
                    
                    # Manual Hit Test Logic:
                    # 1. Get the RelativeLayout parent
                    
                    # 2. Convert global touch to the RelativeLayout's local space
                    #    (This is usually robust even if the child's transform is weird)
                    lx, ly = parent.to_widget(touch.x, touch.y)
                    
                    # 3. Get the button's defined position/size within that RelativeLayout
                    #    (Since it's a RelativeLayout, btn.x/btn.y are local to it)
                    bx, by = btn.x, btn.y
                    bw, bh = btn.width, btn.height
                    
                    # Generous padding
                    pad = dp(20)
                    
                    # 4. Check collision in Parent Local Space
                    hit = ((bx - pad) <= lx <= (bx + bw + pad)) and \
                          ((by - pad) <= ly <= (by + bh + pad))
                    
                    # Update debug label
                    if hasattr(self, 'debug_label') and self.debug_label:
                        status = "HIT" if hit else "MISS"
                        # Show: Global Touch -> Parent Local Touch -> Button Frame
                        msg = f"G:{int(touch.x)},{int(touch.y)} > L:{int(lx)},{int(ly)} > B:{int(bx)},{int(by)} | {status}"
                        self.debug_label.text = msg

                    if hit:
                        if hasattr(self, 'debug_label') and self.debug_label:
                            self.debug_label.text += " -> OPENING..."
                        
                        # FORCE execution on the main thread to ensure _open_tutorial is called
                        # print(f"Global touch detected on icon at {touch.pos}") 
                        self._open_tutorial()
                        return True
                except Exception as e:
                    print(f"Global touch error: {e}")
                    if hasattr(self, 'debug_label') and self.debug_label:
                        self.debug_label.text = f"Error: {e}"
                    pass
                return False
            Window.bind(on_touch_down=_global_icon_touch)
            self._icon_touch_bound = True

        # Transparent hitbox on top of the icon to ensure taps register
        icon_hit_btn = Button(
            size_hint=(None, None),
            size=(dp(90 * mobile_scale), dp(90 * mobile_scale)),
            background_normal='',
            background_down='',
            background_color=(0, 0, 0, 0),
            opacity=0
        )
        icon_hit_btn.bind(on_press=open_tutorial)
        buttons_relative.add_widget(icon_hit_btn)
        
        layout.add_widget(buttons_relative)

        # "And begin..." (updated)
        layout.add_widget(Label(
            text="And begin...",
            font_size=dp(22 * mobile_scale),  # Match 'Choose your path...'
            color=(0.8, 0.9, 0.8, 1),
            size_hint=(1, None),
            height=dp(40 * mobile_scale)
        ))

        # New Game and Resume buttons row with fixed width container
        if self.last_game_in_progress and self.last_difficulty:
            # Create a centered container for the button row
            button_row_container = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, None), height=dp(50 * mobile_scale))
            button_row = BoxLayout(orientation='horizontal', spacing=dp(20 * mobile_scale), size_hint=(None, None), height=dp(50 * mobile_scale), width=dp(500 * mobile_scale))
            
            new_game_btn = Button(
                text="New Game",
                font_size=dp(20 * mobile_scale),
                background_color=(0.3, 0.3, 0.5, 1),
                color=(1, 1, 1, 1),
                size_hint=(None, None),
                size=(dp(180 * mobile_scale), dp(50 * mobile_scale))
            )
            from kivy.graphics import Color, Line
            with new_game_btn.canvas.after:
                Color(0.5, 0.5, 0.5, 1)
                new_game_btn._border = Line(rectangle=(new_game_btn.x, new_game_btn.y, new_game_btn.width, new_game_btn.height), width=1)
                Color(0.9, 0.9, 0.9, 1)
                new_game_btn._highlight_top = Line(points=[new_game_btn.x, new_game_btn.y + new_game_btn.height, new_game_btn.x + new_game_btn.width, new_game_btn.y + new_game_btn.height], width=2)
                new_game_btn._highlight_left = Line(points=[new_game_btn.x, new_game_btn.y, new_game_btn.x, new_game_btn.y + new_game_btn.height], width=2)
                Color(0.4, 0.4, 0.4, 1)
                new_game_btn._shadow_bottom = Line(points=[new_game_btn.x, new_game_btn.y, new_game_btn.x + new_game_btn.width, new_game_btn.y], width=2)
                new_game_btn._shadow_right = Line(points=[new_game_btn.x + new_game_btn.width, new_game_btn.y, new_game_btn.x + new_game_btn.width, new_game_btn.y + new_game_btn.height], width=2)
            def update_new_game_btn_border(instance, *args):
                new_game_btn._border.rectangle = (new_game_btn.x, new_game_btn.y, new_game_btn.width, new_game_btn.height)
                new_game_btn._highlight_top.points = [new_game_btn.x, new_game_btn.y + new_game_btn.height, new_game_btn.x + new_game_btn.width, new_game_btn.y + new_game_btn.height]
                new_game_btn._highlight_left.points = [new_game_btn.x, new_game_btn.y, new_game_btn.x, new_game_btn.y + new_game_btn.height]
                new_game_btn._shadow_bottom.points = [new_game_btn.x, new_game_btn.y, new_game_btn.x + new_game_btn.width, new_game_btn.y]
                new_game_btn._shadow_right.points = [new_game_btn.x + new_game_btn.width, new_game_btn.y, new_game_btn.x + new_game_btn.width, new_game_btn.y + new_game_btn.height]
            new_game_btn.bind(pos=update_new_game_btn_border, size=update_new_game_btn_border)
            # Intercept New Game click to show ditch popup
            def on_new_game(instance):
                self.show_dropped_game_popup(getattr(self, 'selected_difficulty', None))
            new_game_btn.bind(on_press=on_new_game)

            resume_btn = Button(
                text=f"Resume {self.last_difficulty} Game",
                font_size=dp(20 * mobile_scale),
                background_color=(0.3, 0.3, 0.5, 1),
                color=(1, 1, 1, 1),
                size_hint=(None, None),
                size=(dp(300 * mobile_scale), dp(50 * mobile_scale))
            )
            from kivy.graphics import Color, Line
            with resume_btn.canvas.after:
                Color(0.5, 0.5, 0.5, 1)
                resume_btn._border = Line(rectangle=(resume_btn.x, resume_btn.y, resume_btn.width, resume_btn.height), width=1)
                Color(0.9, 0.9, 0.9, 1)
                resume_btn._highlight_top = Line(points=[resume_btn.x, resume_btn.y + resume_btn.height, resume_btn.x + resume_btn.width, resume_btn.y + resume_btn.height], width=2)
                resume_btn._highlight_left = Line(points=[resume_btn.x, resume_btn.y, resume_btn.x, resume_btn.y + resume_btn.height], width=2)
                Color(0.4, 0.4, 0.4, 1)
                resume_btn._shadow_bottom = Line(points=[resume_btn.x, resume_btn.y, resume_btn.x + resume_btn.width, resume_btn.y], width=2)
                resume_btn._shadow_right = Line(points=[resume_btn.x + resume_btn.width, resume_btn.y, resume_btn.x + resume_btn.width, resume_btn.y + resume_btn.height], width=2)
            def update_resume_btn_border(instance, *args):
                resume_btn._border.rectangle = (resume_btn.x, resume_btn.y, resume_btn.width, resume_btn.height)
                resume_btn._highlight_top.points = [resume_btn.x, resume_btn.y + resume_btn.height, resume_btn.x + resume_btn.width, resume_btn.y + resume_btn.height]
                resume_btn._highlight_left.points = [resume_btn.x, resume_btn.y, resume_btn.x, resume_btn.y + resume_btn.height]
                resume_btn._shadow_bottom.points = [resume_btn.x, resume_btn.y, resume_btn.x + resume_btn.width, resume_btn.y]
                resume_btn._shadow_right.points = [resume_btn.x + resume_btn.width, resume_btn.y, resume_btn.x + resume_btn.width, resume_btn.y + resume_btn.height]
            resume_btn.bind(pos=update_resume_btn_border, size=update_resume_btn_border)
            resume_btn.bind(on_press=lambda x: self.start_game(self.last_difficulty, resume=True))
            button_row.add_widget(new_game_btn)
            button_row.add_widget(resume_btn)
            
            # Add the button row to the centered container, then add container to main layout
            button_row_container.add_widget(button_row)
            layout.add_widget(button_row_container)
        else:
            # Only show centered New Game button with fixed width container
            button_row_container = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, None), height=dp(50 * mobile_scale))
            button_row = BoxLayout(orientation='horizontal', spacing=dp(20 * mobile_scale), size_hint=(None, None), height=dp(50 * mobile_scale), width=dp(180 * mobile_scale))
            
            new_game_btn = Button(
                text="New Game",
                font_size=dp(20 * mobile_scale),
                background_color=(0.3, 0.3, 0.5, 1),
                color=(1, 1, 1, 1),
                size_hint=(1, None),
                height=dp(50 * mobile_scale)
            )
            from kivy.graphics import Color, Line
            with new_game_btn.canvas.after:
                Color(0.5, 0.5, 0.5, 1)
                new_game_btn._border = Line(rectangle=(new_game_btn.x, new_game_btn.y, new_game_btn.width, new_game_btn.height), width=1)
                Color(0.9, 0.9, 0.9, 1)
                new_game_btn._highlight_top = Line(points=[new_game_btn.x, new_game_btn.y + new_game_btn.height, new_game_btn.x + new_game_btn.width, new_game_btn.y + new_game_btn.height], width=2)
                new_game_btn._highlight_left = Line(points=[new_game_btn.x, new_game_btn.y, new_game_btn.x, new_game_btn.y + new_game_btn.height], width=2)
                Color(0.4, 0.4, 0.4, 1)
                new_game_btn._shadow_bottom = Line(points=[new_game_btn.x, new_game_btn.y, new_game_btn.x + new_game_btn.width, new_game_btn.y], width=2)
                new_game_btn._shadow_right = Line(points=[new_game_btn.x + new_game_btn.width, new_game_btn.y, new_game_btn.x + new_game_btn.width, new_game_btn.y + new_game_btn.height], width=2)
            def update_new_game_btn_border(instance, *args):
                new_game_btn._border.rectangle = (new_game_btn.x, new_game_btn.y, new_game_btn.width, new_game_btn.height)
                new_game_btn._highlight_top.points = [new_game_btn.x, new_game_btn.y + new_game_btn.height, new_game_btn.x + new_game_btn.width, new_game_btn.y + new_game_btn.height]
                new_game_btn._highlight_left.points = [new_game_btn.x, new_game_btn.y, new_game_btn.x, new_game_btn.y + new_game_btn.height]
                new_game_btn._shadow_bottom.points = [new_game_btn.x, new_game_btn.y, new_game_btn.x + new_game_btn.width, new_game_btn.y]
                new_game_btn._shadow_right.points = [new_game_btn.x + new_game_btn.width, new_game_btn.y, new_game_btn.x + new_game_btn.width, new_game_btn.y + new_game_btn.height]
            new_game_btn.bind(pos=update_new_game_btn_border, size=update_new_game_btn_border)
            new_game_btn.bind(on_press=lambda x: self.start_game(getattr(self, 'selected_difficulty', None)))
            button_row.add_widget(new_game_btn)
            
            # Add the button row to the centered container, then add container to main layout
            button_row_container.add_widget(button_row)
            layout.add_widget(button_row_container)


        root.add_widget(layout)
        
        # Play welcome music
        self._play_welcome_music()

        # (pygame excluded from build; no background audio init needed)

        return root

    def _update_puzzle_screen_sizes(self):
        from kivy.metrics import dp
        from kivy.core.window import Window
        min_w, min_h = 320, 480
        win_w, win_h = max(Window.width, min_w), max(Window.height, min_h)
        btn_fs = max(dp(10), min(dp(24), win_h * 0.03, win_w * 0.045))
        btn_h = max(dp(24), min(dp(44), win_h * 0.07, win_w * 0.09))
        # Board container height
        self._puzzle_board_container.height = win_h * 0.7
        # Digit buttons: two rows, always centered and fit
        available_w = win_w - dp(32)
        min_btn_size = dp(32)
        max_btn_size = min(btn_h, dp(56))
        spacing = dp(8)
        # First row: 5 buttons
        btn_count1 = 5
        total_spacing1 = (btn_count1 - 1) * spacing
        btn_size1 = min(max_btn_size, max(min_btn_size, (available_w - total_spacing1) / btn_count1))
        row_width1 = btn_count1 * btn_size1 + total_spacing1
        # Second row: 4 buttons
        btn_count2 = 4
        total_spacing2 = (btn_count2 - 1) * spacing
        btn_size2 = min(max_btn_size, max(min_btn_size, (available_w - total_spacing2) / btn_count2))
        row_width2 = btn_count2 * btn_size2 + total_spacing2
        # Use direct references for the two digit rows
        if hasattr(self, '_digit_row1') and hasattr(self, '_digit_row2'):
            self._digit_row1.width = row_width1
            self._digit_row1.height = btn_size1
            self._digit_row1.size_hint = (None, None)
            self._digit_row1.pos_hint = {'center_x': 0.5}
            self._digit_row2.width = row_width2
            self._digit_row2.height = btn_size2
            self._digit_row2.size_hint = (None, None)
            self._digit_row2.pos_hint = {'center_x': 0.5}
            # Set button sizes
            for i, btn in enumerate(self._digit_buttons):
                if i < 5:
                    btn.size = (btn_size1, btn_size1)
                    btn.font_size = max(dp(12), btn_size1 * 0.45)
                else:
                    btn.size = (btn_size2, btn_size2)
                    btn.font_size = max(dp(12), btn_size2 * 0.45)
        # Action buttons: shrink to fit if needed
        action_btn_count = len(self._action_buttons)
        action_min_w = dp(48)
        action_max_w = max(btn_h * 1.2, dp(60))
        action_total_spacing = (action_btn_count - 1) * spacing
        action_btn_w = min(action_max_w, max(action_min_w, (available_w - action_total_spacing) / action_btn_count))
        for btn in self._action_buttons:
            btn.size = (action_btn_w, btn_h)
            btn.font_size = btn_fs
        self._action_row.height = btn_h
        self._action_row.width = action_btn_count * action_btn_w + action_total_spacing
        self._action_scroll.height = btn_h
    def _save_last_game(self, puzzle, solution, board, difficulty, in_progress):
        import json
        import hashlib
        import os
        import time
        try:
            print(f"[SAVE] _save_last_game called with difficulty={difficulty}, in_progress={in_progress}")
            
            # Validate inputs before saving
            if not puzzle or not solution:
                print(f"[SAVE] ERROR: Invalid puzzle or solution data - puzzle={bool(puzzle)}, solution={bool(solution)}")
                return
            
            # Generate a unique puzzle ID based on the puzzle content
            puzzle_str = str(puzzle)
            puzzle_id = hashlib.md5(puzzle_str.encode()).hexdigest()[:8]
            print(f"[SAVE] Puzzle ID: {puzzle_id}")
            
            # Build comprehensive state including user progress
            state = {
                'puzzle': puzzle,
                'solution': solution,
                'board': board,
                'difficulty': difficulty,
                'in_progress': in_progress,
                'puzzle_id': puzzle_id,
                'save_timestamp': time.time()
            }
            
            # Log puzzle details for debugging
            if puzzle:
                print(f"[SAVE] Saving puzzle type: {type(puzzle)}, length: {len(puzzle)}")
                for i in range(min(3, len(puzzle))):
                    print(f"[SAVE] Puzzle row {i}: {puzzle[i]}")
            else:
                print(f"[SAVE] WARNING: puzzle is None or empty!")
                
            if solution:
                print(f"[SAVE] Saving solution type: {type(solution)}, length: {len(solution)}")
                print(f"[SAVE] Solution first row: {solution[0]}")
            else:
                print(f"[SAVE] WARNING: solution is None or empty!")
            
            # Add additional game state if we're in an active game
            if hasattr(self, 'mistake_count'):
                state['mistake_count'] = self.mistake_count
                print(f"[SAVE] Saving mistake_count: {self.mistake_count}")
            else:
                print(f"[SAVE] No mistake_count attribute found")
                
            if hasattr(self, 'start_time'):
                state['start_time'] = self.start_time
                print(f"[SAVE] Saving start_time: {self.start_time}")
            else:
                print(f"[SAVE] No start_time attribute found")
                
            if hasattr(self, 'action_history'):
                # Convert any sets in action_history to lists for JSON serialization
                serializable_history = []
                for i, action in enumerate(self.action_history):
                    try:
                        if len(action) >= 4 and isinstance(action[3], set):
                            # Convert the set to list (prev_notes)
                            new_action = list(action)
                            new_action[3] = list(action[3])
                            if len(action) >= 5 and isinstance(action[4], set):
                                # Convert additional set if present
                                new_action[4] = list(action[4])
                            serializable_history.append(tuple(new_action))
                            print(f"[SAVE] Converted action {i} with sets to lists")
                        else:
                            # Check if there are any sets in other positions
                            clean_action = []
                            for j, item in enumerate(action):
                                if isinstance(item, set):
                                    clean_action.append(list(item))
                                    print(f"[SAVE] Found and converted set at action {i}, position {j}")
                                else:
                                    clean_action.append(item)
                            serializable_history.append(tuple(clean_action))
                    except Exception as action_err:
                        print(f"[SAVE] Error processing action {i}: {action_err}")
                        print(f"[SAVE] Action contents: {action}")
                        # Skip problematic actions
                        continue
                        
                state['action_history'] = serializable_history
                print(f"[SAVE] Saving action_history length: {len(serializable_history)}")
            else:
                print(f"[SAVE] No action_history attribute found")
                
            if hasattr(self, 'auto_solve_timestamps'):
                state['auto_solve_timestamps'] = self.auto_solve_timestamps
            
            # Save IAP variables
            state['auto_solve_date'] = self.auto_solve_date
            state['auto_solve_count'] = self.auto_solve_count
            state['auto_solve_credits'] = self.auto_solve_credits
            state['unlimited_until'] = self.unlimited_until
            state['unlimited_forever'] = self.unlimited_forever
            
            # Save hints remaining count to persist across sessions
            if hasattr(self, 'hints_remaining'):
                state['hints_remaining'] = self.hints_remaining
                print(f"[SAVE] Saving hints_remaining: {self.hints_remaining}")
            else:
                print(f"[SAVE] No hints_remaining attribute found")
            
            # Save cell notes if sudoku board exists
            if hasattr(self, 'sudoku_board') and self.sudoku_board:
                notes_data = {}
                for r in range(9):
                    for c in range(9):
                        cell = self.sudoku_board.get_cell(r, c)
                        if cell and hasattr(cell, 'notes') and cell.notes:
                            try:
                                # Ensure notes is converted to list for JSON serialization
                                notes_list = list(cell.notes) if hasattr(cell.notes, '__iter__') else []
                                if notes_list:  # Only save if there are actual notes
                                    notes_data[f"{r},{c}"] = notes_list
                            except Exception as notes_err:
                                print(f"[SAVE] Error converting notes for cell ({r},{c}): {notes_err}")
                state['notes_data'] = notes_data
                print(f"[SAVE] Saving notes for {len(notes_data)} cells")

                # Save mistake cells (cells currently marked as mistake)
                mistake_cells = []
                for r in range(9):
                    for c in range(9):
                        cell = self.sudoku_board.get_cell(r, c)
                        if cell and hasattr(cell, 'is_mistake') and cell.is_mistake:
                            mistake_cells.append([r, c])
                state['mistake_cells'] = mistake_cells
                print(f"[SAVE] Saving {len(mistake_cells)} mistake cells: {mistake_cells}")
            else:
                print(f"[SAVE] No sudoku_board found for notes")
            
            # Use platform-specific paths for Android compatibility
            from kivy.app import App
            save_dir = App.get_running_app().user_data_dir
            # Ensure directory exists
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
                
            current_dir = os.getcwd()
            save_path = os.path.join(save_dir, 'last_game.json')
            temp_path = os.path.join(save_dir, 'last_game_temp.json')
            print(f"[SAVE] Current working directory: {current_dir}")
            print(f"[SAVE] User data directory: {save_dir}")
            print(f"[SAVE] Saving to path: {save_path}")
            
            # Use atomic save to prevent corruption
            with open(temp_path, 'w') as f:
                json.dump(state, f, indent=2)  # Added indentation for better debugging
            
            # Verify the temp file was written correctly
            if os.path.exists(temp_path):
                file_size = os.path.getsize(temp_path)
                print(f"[SAVE] Temp file created successfully, size: {file_size} bytes")
                
                # Test that we can load it back
                try:
                    with open(temp_path, 'r') as f:
                        test_state = json.load(f)
                    print(f"[SAVE] Temp file verified - can be loaded, puzzle ID: {test_state.get('puzzle_id', 'MISSING')}")
                    print(f"[SAVE] Temp file puzzle first row: {test_state['puzzle'][0]}")
                    
                    # Atomic rename to final location
                    if os.path.exists(save_path):
                        os.remove(save_path)
                    os.rename(temp_path, save_path)
                    print(f"[SAVE] Successfully saved game state for {difficulty} with puzzle ID {puzzle_id}")
                    print(f"[SAVE] Final state keys: {list(state.keys())}")
                    print(f"[SAVE] File exists after save: {os.path.exists(save_path)}")
                    
                    # CRITICAL FIX: Update the in-memory last_game_state immediately after successful save
                    # This ensures resume uses the current game, not an old loaded one
                    print(f"[SAVE] Updating in-memory last_game_state with current puzzle ID {puzzle_id}")
                    self.last_game_state = state.copy()
                    self.last_game_in_progress = in_progress
                    self.last_difficulty = difficulty
                    print(f"[SAVE] Updated last_game_state puzzle ID: {self.last_game_state.get('puzzle_id', 'MISSING')}")
                    
                except Exception as verify_err:
                    print(f"[SAVE] ERROR: Temp file verification failed: {verify_err}")
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
            else:
                print(f"[SAVE] ERROR: Temp file was not created")
                
        except Exception as e:
            print(f"Error saving last game: {e}")
            import traceback
            traceback.print_exc()
            # Clean up temp file if it exists
            from kivy.app import App
            save_dir = App.get_running_app().user_data_dir
            temp_path = os.path.join(save_dir, 'last_game_temp.json')
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                    print(f"[SAVE] Cleaned up temp file after error")
                except:
                    pass

    def _load_last_game(self):
        import json
        import os
        # Use platform-specific paths for Android compatibility
        # During __init__, use self.user_data_dir directly instead of App.get_running_app()
        try:
            save_dir = self.user_data_dir
        except Exception:
            # Fallback for very early initialization
            from kivy.utils import platform
            if platform == 'android':
                save_dir = '/data/data/org.yourname.sudokumobileapp/files'
            else:
                save_dir = os.path.dirname(__file__)
        current_dir = os.getcwd()
        load_path = os.path.join(save_dir, 'last_game.json')
        print(f"[LOAD] Current working directory: {current_dir}")
        print(f"[LOAD] User data directory: {save_dir}")
        print(f"[LOAD] Looking for file at: {load_path}")
        print(f"[LOAD] File exists: {os.path.exists(load_path)}")
        
        if os.path.exists(load_path):
            try:
                file_size = os.path.getsize(load_path)
                print(f"[LOAD] File size: {file_size} bytes")
                
                with open(load_path, 'r') as f:
                    state = json.load(f)
                    
                # Validate the loaded state
                required_keys = ['puzzle', 'solution', 'difficulty', 'in_progress']
                missing_keys = [key for key in required_keys if key not in state]
                if missing_keys:
                    print(f"[LOAD] ERROR: Missing required keys: {missing_keys}")
                    self.last_game_state = None
                    self.last_game_in_progress = False
                    self.last_difficulty = None
                    return
                
                # Validate puzzle data
                puzzle = state.get('puzzle')
                solution = state.get('solution')
                if not puzzle or not solution:
                    print(f"[LOAD] ERROR: Invalid puzzle or solution data")
                    self.last_game_state = None
                    self.last_game_in_progress = False
                    self.last_difficulty = None
                    return
                
                if len(puzzle) != 9 or len(solution) != 9:
                    print(f"[LOAD] ERROR: Invalid puzzle/solution dimensions - puzzle: {len(puzzle)}, solution: {len(solution)}")
                    self.last_game_state = None
                    self.last_game_in_progress = False
                    self.last_difficulty = None
                    return
                
                self.last_game_state = state
                self.last_game_in_progress = state.get('in_progress', False)
                self.last_difficulty = state.get('difficulty')
                
                # Restore IAP variables from saved state (DISABLED FOR TESTING)
                # self.auto_solve_date = state.get('auto_solve_date')
                # self.auto_solve_count = state.get('auto_solve_count', 0)
                # self.auto_solve_credits = state.get('auto_solve_credits', 0)
                # self.unlimited_until = state.get('unlimited_until')
                # self.unlimited_forever = state.get('unlimited_forever', False)
                
                # Show puzzle ID for tracking
                puzzle_id = state.get('puzzle_id', 'UNKNOWN')
                save_timestamp = state.get('save_timestamp', 'UNKNOWN')
                
                print(f"[LOAD] Successfully loaded game state: difficulty={self.last_difficulty}, in_progress={self.last_game_in_progress}")
                print(f"[LOAD] Puzzle ID: {puzzle_id}, Save timestamp: {save_timestamp}")
                print(f"[LOAD] State keys: {list(state.keys())}")
                print(f"[LOAD] Loaded puzzle first row: {puzzle[0]}")
                print(f"[LOAD] Loaded solution first row: {solution[0]}")
                print(f"[LOAD] Loaded board first row: {state.get('board', [[]])[0] if state.get('board') else 'None'}")
                print(f"[LOAD] Notes data count: {len(state.get('notes_data', {}))}")
                print(f"[LOAD] Action history length: {len(state.get('action_history', []))}")
                
            except json.JSONDecodeError as je:
                print(f"[LOAD] JSON decode error: {je}")
                print(f"[LOAD] File may be corrupted, removing it")
                try:
                    os.remove(load_path)
                    print(f"[LOAD] Corrupted file removed")
                except:
                    print(f"[LOAD] Failed to remove corrupted file")
                self.last_game_state = None
                self.last_game_in_progress = False
                self.last_difficulty = None
            except Exception as e:
                print(f"Error loading last game: {e}")
                import traceback
                traceback.print_exc()
                self.last_game_state = None
                self.last_game_in_progress = False
                self.last_difficulty = None
        else:
            print("[LOAD] No last_game.json file found")
            self.last_game_state = None
            self.last_game_in_progress = False
            self.last_difficulty = None
    def show_fail_screen(self):
        from kivy.uix.popup import Popup
        from kivy.uix.label import Label
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.uix.button import Button
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle
        from kivy.core.window import Window
        
        # Reset puzzle win streak on failure
        if hasattr(self, 'game_stats'):
            self.game_stats['puzzle_win_streak'] = 0
            self._save_stats_and_achievements()
            print("[STATS] Win streak reset due to failure")
        
        # Calculate responsive sizing
        win_w, win_h = Window.width, Window.height
        scale_factor = min(win_w / 600.0, win_h / 850.0)
        scale_factor = max(0.5, min(1.5, scale_factor))  # Clamp scaling
        
        # Calculate popup size - responsive to window size
        popup_w = min(win_w * 0.9, dp(480) * scale_factor)
        popup_h = min(win_h * 0.6, dp(260) * scale_factor)
        
        # Root layout for popup content
        root = BoxLayout(orientation='vertical', padding=dp(12) * scale_factor, spacing=dp(8) * scale_factor)
        # Maroon background
        with root.canvas.before:
            Color(0.4, 0, 0, 1)  # Maroon
            bg_rect = Rectangle(size=root.size, pos=root.pos)
        root.bind(size=lambda inst, val: setattr(bg_rect, 'size', val))
        root.bind(pos=lambda inst, val: setattr(bg_rect, 'pos', val))

        # Game Over label - no top spacer to prevent overflow
        over_label = Label(
            text="Game Over",
            font_size=dp(38) * scale_factor,
            color=(1, 1, 1, 1),
            size_hint=(1, None),
            height=dp(50) * scale_factor,  # Reduced height
            halign='center',
            valign='middle',
            text_size=(popup_w * 0.9, None)  # Set text_size for proper wrapping
        )
        root.add_widget(over_label)

        # Message label
        msg_label = Label(
            text="You made 3 mistakes. Better luck next time!",
            font_size=dp(20) * scale_factor,
            color=(1, 1, 1, 1),
            size_hint=(1, None),
            height=dp(60) * scale_factor,  # Increased height for potential wrapping
            halign='center',
            valign='middle',
            text_size=(popup_w * 0.9, None)  # Set text_size for proper wrapping
        )
        root.add_widget(msg_label)
        root.add_widget(BoxLayout(size_hint_y=None, height=dp(16) * scale_factor))

        # Back to Menu button
        btn = Button(
            text="Back to Menu",
            font_size=dp(18) * scale_factor,
            size_hint=(None, None),
            size=(dp(180) * scale_factor, dp(44) * scale_factor),
            background_color=(0.75, 0.75, 0.75, 1),
            color=(0, 0, 0, 1),
            background_normal='',
            background_down=''
        )
        # Add 3D embossed effect
        from kivy.graphics import Color, Line
        with btn.canvas.after:
            Color(0.5, 0.5, 0.5, 1)
            btn._border = Line(rectangle=(btn.x, btn.y, btn.width, btn.height), width=1)
            Color(0.9, 0.9, 0.9, 1)
            btn._highlight_top = Line(points=[btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height], width=2)
            btn._highlight_left = Line(points=[btn.x, btn.y, btn.x, btn.y + btn.height], width=2)
            Color(0.4, 0.4, 0.4, 1)
            btn._shadow_bottom = Line(points=[btn.x, btn.y, btn.x + btn.width, btn.y], width=2)
            btn._shadow_right = Line(points=[btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height], width=2)
        def update_btn_border(instance, *args):
            btn._border.rectangle = (btn.x, btn.y, btn.width, btn.height)
            btn._highlight_top.points = [btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height]
            btn._highlight_left.points = [btn.x, btn.y, btn.x, btn.y + btn.height]
            btn._shadow_bottom.points = [btn.x, btn.y, btn.x + btn.width, btn.y]
            btn._shadow_right.points = [btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height]
        btn.bind(pos=update_btn_border, size=update_btn_border)
        btn_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, None), height=dp(60) * scale_factor)
        btn_layout.add_widget(btn)
        root.add_widget(btn_layout)

        popup = Popup(title='', content=root, size_hint=(None, None), size=(popup_w, popup_h), auto_dismiss=False, separator_height=0, background='')
        def go_to_menu(instance):
            self._play_button_click_sound()
            # Mark game as not in-progress when failing
            self.last_game_in_progress = False
            # Save state as not in-progress
            if hasattr(self, 'game') and hasattr(self.game, 'puzzle') and hasattr(self.game, 'solution'):
                self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, False)
            popup.dismiss()
            self._reward_screen_showing = False
            # Stop ALL sounds (including game over sound)
            self._stop_all_sounds()
            # Stop clock updates
            self._stop_clock_updates()
            self._navigation_pause_time = time.time()  # Record pause when leaving puzzle
            # Reset game state flags
            if hasattr(self, '_fail_screen_active'):
                self._fail_screen_active = False
            self.root.clear_widgets()
            from kivy.core.window import Window
            from kivy.clock import Clock
            # Un-maximize the window if maximized (Windows only)
            # Do NOT maximize the window here; preserve user window state when returning to menu
            self.welcome_layout = self.build_welcome_screen()
            self.root.add_widget(self.welcome_layout)
            # Schedule window size/position after layout is rebuilt
            # Do NOT reset window size/position here; preserve user window state when returning to menu
        btn.bind(on_release=go_to_menu)
        
        # Stop ALL music (including native MCI tracks) before game over sound
        if hasattr(self, '_music') and self._music:
            self._music.stop()
        try:
            if self._supports_native_windows_audio():
                self._native_audio_stop('serene_music')
                self._native_audio_stop('serene_welcome')
                self._native_music = False
                print("[SOUND] Stopped native MCI music for game over screen")
        except Exception as e:
            print(f"[SOUND] Error stopping native music before game over: {e}")
        self._reward_screen_showing = True

        # Play game over sound
        self._play_game_over_sound()
        
        # Set flag to prevent input during fail screen
        self._fail_screen_active = True
        
        popup.open()
    def check_section_completion(self, row, col):
        """Check if a 3x3 section is completed and correct, and play a gentle pulse animation if so."""
        if not hasattr(self, 'game') or not hasattr(self.game, 'solution'):
            return
        box_row = (row // 3) * 3
        box_col = (col // 3) * 3
        for r in range(box_row, box_row + 3):
            for c in range(box_col, box_col + 3):
                cell = self.sudoku_board.get_cell(r, c)
                val = cell.text.strip()
                sol = str(self.game.solution[r][c])
                if val != sol:
                    return  # Section not complete or incorrect
        # Section is complete and correct
        self.animate_section_pulse(box_row, box_col)

    def animate_section_pulse(self, box_row, box_col):
        """Animate a gentle pulse for all cells in the completed 3x3 section."""
        from kivy.animation import Animation
        cells = [self.sudoku_board.get_cell(r, c) for r in range(box_row, box_row + 3) for c in range(box_col, box_col + 3)]
        for cell in cells:
            base = getattr(cell, 'base_font_size', cell.font_size)
            # User-placed digits are displayed at 1.35x, clues at 1x
            if not cell.is_clue and cell.text and cell.text not in ('', '0'):
                target_size = base * 1.35
            else:
                target_size = base
            # Animate font size up and back for a pulse effect
            anim = Animation(font_size=target_size * 1.18, duration=0.13, t='out_quad') + \
                   Animation(font_size=target_size * 0.96, duration=0.10, t='in_out_quad') + \
                   Animation(font_size=target_size, duration=0.10, t='out_quad')
            anim.start(cell)

    def show_premium_popup(self):
        """Show popup displaying Premium player benefits."""
        from kivy.uix.popup import Popup
        from kivy.uix.label import Label
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.uix.image import Image
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle
        from kivy.core.window import Window
        
        # Calculate responsive sizing
        win_w, win_h = Window.width, Window.height
        scale_factor = min(win_w / 600.0, win_h / 850.0)
        scale_factor = max(0.5, min(1.5, scale_factor))
        
        # Calculate popup size - increased height to fit all content
        popup_w = min(win_w * 0.85, dp(400) * scale_factor)
        popup_h = min(win_h * 0.6, dp(420) * scale_factor)
        
        # Root layout for popup content
        root = BoxLayout(orientation='vertical', padding=dp(16) * scale_factor, spacing=dp(10) * scale_factor)
        # Grey background
        with root.canvas.before:
            Color(0.35, 0.35, 0.35, 1)  # Grey
            bg_rect = Rectangle(size=root.size, pos=root.pos)
        root.bind(size=lambda inst, val: setattr(bg_rect, 'size', val))
        root.bind(pos=lambda inst, val: setattr(bg_rect, 'pos', val))
        
        # Premium icon at top, centered
        icon_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, None), height=dp(60) * scale_factor)
        premium_img = Image(
            source=resource_path('Images/premium_icon.PNG'),
            size_hint=(None, None),
            size=(dp(100) * scale_factor, dp(45) * scale_factor),
            fit_mode='fill'
        )
        icon_layout.add_widget(premium_img)
        root.add_widget(icon_layout)
        
        # Header text
        header_label = Label(
            text="As a Premium player, you are enjoying:",
            font_size=dp(18) * scale_factor,
            color=(1, 1, 1, 1),
            size_hint=(1, None),
            height=dp(30) * scale_factor,
            halign='center',
            valign='middle'
        )
        header_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (inst.width, None)))
        root.add_widget(header_label)
        
        # Add vertical space before bullet points
        root.add_widget(BoxLayout(size_hint_y=None, height=dp(20) * scale_factor))
        
        # Bullet points
        bullets = [
            "• Unlimited hints",
            "• Unlimited auto-solves",
            "• Advanced statistics",
            "• Achievement system"
        ]
        for bullet_text in bullets:
            bullet_label = Label(
                text=bullet_text,
                font_size=dp(16) * scale_factor,
                color=(1, 1, 1, 1),
                size_hint=(1, None),
                height=dp(26) * scale_factor,
                halign='center',
                valign='middle'
            )
            bullet_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (inst.width, None)))
            root.add_widget(bullet_label)
        
        # Spacer at bottom
        root.add_widget(BoxLayout(size_hint_y=None, height=dp(10) * scale_factor))
        
        popup = Popup(
            title='',
            content=root,
            size_hint=(None, None),
            size=(popup_w, popup_h),
            auto_dismiss=True,
            separator_height=0,
            background=''
        )
        popup.open()

    def show_dropped_game_popup(self, difficulty):
        # If no difficulty selected, show the difficulty selection popup instead
        if not difficulty:
            self.show_select_difficulty_popup()
            return
        
        # Reset puzzle win streak on abandonment
        if hasattr(self, 'game_stats'):
            self.game_stats['puzzle_win_streak'] = 0
            self._save_stats_and_achievements()
            print("[STATS] Win streak reset due to game abandonment")
        
        from kivy.utils import platform
        from kivy.uix.widget import Widget
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.uix.popup import Popup
        from kivy.metrics import dp
        from kivy.core.window import Window
        from kivy.graphics import Color, Rectangle, Line

        win_w, win_h = Window.width, Window.height
        is_mobile = platform in ('android', 'ios')
        if is_mobile:
            scale_factor = min(win_w / 600.0, win_h / 850.0) * 0.85
            scale_factor = max(0.45, min(1.1, scale_factor))
            popup_w = min(win_w * 0.92, dp(420) * scale_factor)
            popup_h = min(win_h * 0.36, dp(120) * scale_factor)
            label_fs = dp(15) * scale_factor
            btn_fs = dp(12) * scale_factor
            btn_w = dp(70) * scale_factor
            btn_h = dp(26) * scale_factor
            pad = dp(16) * scale_factor
            spacing = dp(8) * scale_factor
            bg_color = (1.0, 0.5, 0.0, 1)  # Bright orange
        else:
            scale_factor = min(win_w / 600.0, win_h / 850.0)
            scale_factor = max(0.5, min(1.5, scale_factor))
            popup_w = min(win_w * 0.8, dp(480) * scale_factor)
            popup_h = min(win_h * 0.4, dp(160) * scale_factor)
            label_fs = dp(20) * scale_factor
            btn_fs = dp(16) * scale_factor
            btn_w = dp(80) * scale_factor
            btn_h = dp(32) * scale_factor
            pad = dp(24) * scale_factor
            spacing = dp(16) * scale_factor
            bg_color = (1.0, 0.5, 0.0, 1)  # Bright orange

        content = BoxLayout(orientation='vertical', padding=pad, spacing=spacing)
        with content.canvas.before:
            Color(*bg_color)
            _bg_rect = Rectangle(size=content.size, pos=content.pos)
        content.bind(size=lambda inst, val: setattr(_bg_rect, 'size', val))
        content.bind(pos=lambda inst, val: setattr(_bg_rect, 'pos', val))
        label = Label(text="You dropped that game like a bad habit.", font_size=label_fs, color=(1, 1, 1, 1), halign='center', valign='middle', text_size=(popup_w * 0.9, None))
        content.add_widget(label)
        content.add_widget(Widget(size_hint_y=None, height=spacing))
        true_btn = Button(text="True", font_size=btn_fs, size_hint=(None, None), size=(btn_w, btn_h), background_color=(0.75, 0.75, 0.75, 1), color=(0, 0, 0, 1), background_normal='', background_down='')
        with true_btn.canvas.after:
            Color(0.5, 0.5, 0.5, 1)
            true_btn._border = Line(rectangle=(true_btn.x, true_btn.y, true_btn.width, true_btn.height), width=1)
            Color(0.9, 0.9, 0.9, 1)
            true_btn._highlight_top = Line(points=[true_btn.x, true_btn.y + true_btn.height, true_btn.x + true_btn.width, true_btn.y + true_btn.height], width=2)
            true_btn._highlight_left = Line(points=[true_btn.x, true_btn.y, true_btn.x, true_btn.y + true_btn.height], width=2)
            Color(0.4, 0.4, 0.4, 1)
            true_btn._shadow_bottom = Line(points=[true_btn.x, true_btn.y, true_btn.x + true_btn.width, true_btn.y], width=2)
            true_btn._shadow_right = Line(points=[true_btn.x + true_btn.width, true_btn.y, true_btn.x + true_btn.width, true_btn.y + true_btn.height], width=2)
        def update_true_btn_border(instance, *args):
            true_btn._border.rectangle = (true_btn.x, true_btn.y, true_btn.width, true_btn.height)
            true_btn._highlight_top.points = [true_btn.x, true_btn.y + true_btn.height, true_btn.x + true_btn.width, true_btn.y + true_btn.height]
            true_btn._highlight_left.points = [true_btn.x, true_btn.y, true_btn.x, true_btn.y + true_btn.height]
            true_btn._shadow_bottom.points = [true_btn.x, true_btn.y, true_btn.x + true_btn.width, true_btn.y]
            true_btn._shadow_right.points = [true_btn.x + true_btn.width, true_btn.y, true_btn.x + true_btn.width, true_btn.y + true_btn.height]
        true_btn.bind(pos=update_true_btn_border, size=update_true_btn_border)
        btn_layout = AnchorLayout(anchor_x='center', anchor_y='center')
        btn_layout.add_widget(true_btn)
        content.add_widget(btn_layout)
        popup = Popup(title='', content=content, size_hint=(None, None), size=(popup_w, popup_h), auto_dismiss=False, separator_height=0, background='')
        def on_true(instance):
            self._play_button_click_sound()
            popup.dismiss()
            self.start_game(difficulty)
        true_btn.bind(on_release=on_true)
        popup.open()
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.locked_digit = None  # For Stone Cold Digit Lock
        self.padlock_img = None
        self.auto_solve_timestamps = []
        self.last_game_state = None
        self.last_game_in_progress = False
        self.last_difficulty = None
        self.action_history = []
        
        # Window maximization tracking
        self.window_maximized = False
        self.original_window_size = (600, 850)  # Default welcome screen size
        
        # Initialize sound variables
        self._welcome_music = None
        self._reward_sound = None
        self._game_over_sound = None
        self._button_click_sound = None
        self._cell_fill_sound = None
        self._cell_select_sound = None
        self._pencil_click_sound = None
        self._game_start_sound = None
        self._pencil_write_sound = None
        self._pencil_erase_sound = None
        self._undo_sound = None
        self._error_sound = None
        self._hint_sound = None
        self._complete_sound = None
        
        # Initialize game state flags
        self._fail_screen_active = False
        
        # Initialize settings (defaults: Music=On, ShowClock=Off, Sounds=On, CheckMistakes=On, DarkMode=Off, ShowCounts=Off)
        self.settings_music = True
        self.settings_show_clock = False
        self.settings_sounds = True
        self.settings_check_mistakes = True
        self.settings_dark_mode = False
        self.settings_show_counts = False  # Show hints/auto-solves remaining on buttons
        
        # Initialize clock tracking
        self._clock_event = None
        self._pause_time = None  # Track when app is paused to subtract from total time
        self._navigation_pause_time = None  # Track when user navigates away from puzzle to subtract gap from completion time
        
        # Initialize Auto-Solve IAP attributes (RESET FOR TESTING)
        import datetime
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        self.auto_solve_date = yesterday  # Reset to yesterday to allow daily use
        self.auto_solve_count = 0
        self.auto_solve_credits = 0
        self.unlimited_until = None
        self.unlimited_forever = False
        
        # Premium status
        self.has_premium = False
        self.review_debug_mode = False
        
        # Initialize game statistics
        self.game_stats = {
            'puzzles_started': 0,
            'puzzles_completed': 0,
            'puzzles_by_difficulty': {'easy': 0, 'moderate': 0, 'tough': 0, 'expert': 0, 'evil': 0, 'diabolical': 0},
            'qualified_by_difficulty': {'easy': 0, 'moderate': 0, 'tough': 0, 'expert': 0, 'evil': 0, 'diabolical': 0},  # Completions with ≤3 hints
            'total_play_time_seconds': 0,
            'hints_used_total': 0,
            'auto_solves_used': 0,
            'mistakes_made_total': 0,
            'perfect_games': 0,  # No mistakes
            'fastest_easy': None,
            'fastest_moderate': None,
            'fastest_tough': None,
            'fastest_expert': None,
            'fastest_evil': None,
            'fastest_diabolical': None,
            'current_streak': 0,
            'best_streak': 0,
            'last_completed_date': None,
            'puzzle_win_streak': 0,  # Consecutive puzzles completed without failing
            'best_puzzle_win_streak': 0,  # Best consecutive puzzle streak
            'last_review_prompt_shown': 0,  # Unix timestamp of last review prompt
            'review_prompt_shown_count': 0  # Total times review prompt has been shown
        }
        
        # Initialize achievements (unlocked status)
        self.achievements = {
            'first_victory': False,
            'speed_demon': False,  # Complete easy in under 3 min
            'perfectionist': False,  # Complete without mistakes
            'marathon': False,  # 10 puzzles completed
            'centurion': False,  # 100 puzzles completed
            'streak_3': False,  # 3-day streak
            'streak_7': False,  # 7-day streak
            'streak_30': False,  # 30-day streak
            'hint_free': False,  # Complete without hints
            'master_easy': False,  # 10 easy completed
            'master_medium': False,  # 10 medium completed
            'master_hard': False,  # 10 hard completed
            'expert': False,  # Complete 1 expert puzzle
            'diabolical_mastermind': False,  # Complete diabolical without hints
            'time_traveler': False,  # 1 hour total play time
            'dedicated': False  # 10 hours total play time
        }
        
        # Load saved stats and achievements
        self._load_stats_and_achievements()
        
        # Bind to window resize events to track maximization
        from kivy.core.window import Window
        Window.bind(on_resize=self._on_window_resize)
        
        # Load global hints counter (separate from game state)
        self._load_global_hints()
        
        self._load_last_game()

    def _load_global_hints(self):
        """Load the global hints counter that persists across all games and app restarts"""
        import datetime
        import sys
        try:
            from kivy.app import App
            save_dir = App.get_running_app().user_data_dir
            hints_path = os.path.join(save_dir, 'global_hints.json')
            
            # Detect if running in development mode (from venv, not packaged Store app)
            is_development = '.venv' in sys.executable or 'AppData\\Local\\Programs\\PythonSoftwareFoundation' in sys.executable
            
            # Default: 1 hint, and set refill date to TODAY so new users can't exploit
            today = datetime.date.today().isoformat()
            self.global_hints_remaining = 1
            self.last_hint_refill_date = today  # Default to today for new users
            self._daily_refill_used_this_session = True  # Mark as used since they start with 1 free hint
            
            # Load saved hints - do NOT clamp, allow purchased hints to persist
            if os.path.exists(hints_path):
                import json
                try:
                    with open(hints_path, 'r') as f:
                        data = json.load(f)
                        # In development mode, always reset to 1 hint for testing
                        if is_development:
                            self.global_hints_remaining = 1
                            print(f"[HINTS] Development mode detected - hints reset to 1 for testing")
                        else:
                            # In packaged app, persist hints (including purchased)
                            self.global_hints_remaining = int(data.get('hints_remaining', 1))
                        
                        saved_date = data.get('last_refill_date', None)
                        # Only use saved date if it exists, otherwise keep today
                        if saved_date:
                            self.last_hint_refill_date = saved_date
                        # Restore session flag from file (prevents double refill across app restarts)
                        self._daily_refill_used_this_session = data.get('daily_refill_used', False)
                        # If it's a new day AND we have hints left, reset session flag to allow refill
                        if self.last_hint_refill_date != today and self.global_hints_remaining <= 0:
                            self._daily_refill_used_this_session = False
                        # If it's the same day and we have hints, mark refill as already used
                        elif self.last_hint_refill_date == today and self.global_hints_remaining > 0:
                            self._daily_refill_used_this_session = True
                        print(f"[HINTS] Loaded from file: hints={self.global_hints_remaining}, last_refill={self.last_hint_refill_date}, session_used={self._daily_refill_used_this_session}")
                except Exception as e:
                    print(f"[HINTS] Error reading global hints file: {e}")
            else:
                # First time user - save initial state immediately
                print(f"[HINTS] First time user - initializing with 1 hint")
                self._save_global_hints()
            print(f"[HINTS] Final loaded state: global_hints_remaining={self.global_hints_remaining}, last_refill_date={self.last_hint_refill_date}")
        except Exception as e:
            print(f"[HINTS] Error loading global hints: {e}")
            import traceback
            traceback.print_exc()
            self.global_hints_remaining = 1
            self.last_hint_refill_date = datetime.date.today().isoformat()
            self._daily_refill_used_this_session = False
    
    def _save_global_hints(self):
        """Save the global hints counter and session flag to prevent double refills"""
        try:
            from kivy.app import App
            import datetime
            import json
            save_dir = App.get_running_app().user_data_dir
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
            
            hints_path = os.path.join(save_dir, 'global_hints.json')
            # Reset session flag if it's a new day
            today = datetime.date.today().isoformat()
            if self.last_hint_refill_date != today:
                self._daily_refill_used_this_session = False
            data = {
                'hints_remaining': self.global_hints_remaining,
                'last_refill_date': self.last_hint_refill_date,
                'daily_refill_used': self._daily_refill_used_this_session  # Persist session flag
            }
            
            with open(hints_path, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"[HINTS] Saved global hints: {self.global_hints_remaining}, last refill: {self.last_hint_refill_date}, session_used: {self._daily_refill_used_this_session}")
        except Exception as e:
            print(f"[HINTS] Error saving global hints: {e}")
            import traceback
            traceback.print_exc()
    
    def _check_daily_hint_refill(self):
        """Check if user should get their daily 1-hint refill (only when at 0 hints)"""
        import datetime
        today = datetime.date.today().isoformat()
        
        print(f"[HINTS] _check_daily_hint_refill called: today={today}, last_refill={self.last_hint_refill_date}, hints={self.global_hints_remaining}, session_used={self._daily_refill_used_this_session}")
        
        # If it's a new day, reset the session flag
        if self.last_hint_refill_date != today:
            self._daily_refill_used_this_session = False
        
        # Safety check: prevent multiple refills in same day
        if self._daily_refill_used_this_session:
            print(f"[HINTS] Daily refill already used today - no refill")
            return False
        
        # Check if we should give daily refill - only when:
        # 1. User has 0 hints
        # 2. Last refill was on a different day
        if self.global_hints_remaining == 0 and self.last_hint_refill_date != today:
            # Give 1 free hint for the day
            self.global_hints_remaining = 1
            self.last_hint_refill_date = today
            self._daily_refill_used_this_session = True  # Prevent refill for rest of day
            self._save_global_hints()  # Save state immediately including session flag
            print(f"[HINTS] Daily refill granted! User now has {self.global_hints_remaining} hints")
            return True
        
        print(f"[HINTS] No refill: hints={self.global_hints_remaining}, same_day={self.last_hint_refill_date == today}")
        return False

    def _update_hint_button_text(self):
        """Update the hint button text to show current hints remaining"""
        if hasattr(self, 'hint_btn') and self.hint_btn:
            try:
                has_premium = getattr(self, 'has_premium', False)
                show_counts = getattr(self, 'settings_show_counts', True)
                # Use sp() for density-aware font size on mobile
                font_size = int(sp(11))
                if not show_counts:
                    # Just show "Hint" without any count
                    self.hint_btn.text = "Hint"
                elif has_premium:
                    self.hint_btn.text = f"Hint\n[size={font_size}]Unlimited[/size]"
                else:
                    self.hint_btn.text = f"Hint\n[size={font_size}]{self.global_hints_remaining} left[/size]"
                print(f"[HINTS] Updated hint button text: {self.global_hints_remaining} remaining, font_size={font_size}, show_counts={show_counts}")
            except Exception as e:
                print(f"[HINTS] Error updating hint button: {e}")

    def _update_auto_solve_button_text(self):
        """Update the auto-solve button text to show current status"""
        if hasattr(self, 'auto_btn') and self.auto_btn:
            try:
                import datetime
                has_premium = getattr(self, 'has_premium', False)
                unlimited_forever = getattr(self, 'unlimited_forever', False)
                unlimited_until = getattr(self, 'unlimited_until', None)
                auto_solve_credits = getattr(self, 'auto_solve_credits', 0)
                show_counts = getattr(self, 'settings_show_counts', True)
                
                # Use sp() for density-aware font size on mobile
                font_size = int(sp(11))
                
                if not show_counts:
                    # Just show "Auto-Solve" without any count
                    self.auto_btn.text = "Auto-Solve"
                elif has_premium or unlimited_forever:
                    self.auto_btn.text = f"Auto-Solve\n[size={font_size}]Unlimited[/size]"
                elif unlimited_until:
                    try:
                        if datetime.datetime.now() < datetime.datetime.fromisoformat(unlimited_until):
                            self.auto_btn.text = f"Auto-Solve\n[size={font_size}]24h Pass[/size]"
                        else:
                            self.auto_btn.text = f"Auto-Solve\n[size={font_size}]{auto_solve_credits} left[/size]"
                    except:
                        self.auto_btn.text = f"Auto-Solve\n[size={font_size}]{auto_solve_credits} left[/size]"
                elif auto_solve_credits > 0:
                    self.auto_btn.text = f"Auto-Solve\n[size={font_size}]{auto_solve_credits} left[/size]"
                else:
                    self.auto_btn.text = f"Auto-Solve\n[size={font_size}]1 free/day[/size]"
                print(f"[AUTO-SOLVE] Updated button text: credits={auto_solve_credits}, show_counts={show_counts}")
            except Exception as e:
                print(f"[AUTO-SOLVE] Error updating button: {e}")

    def create_loading_widget_and_start_async_generation(self, difficulty):
        """Create a loading screen widget and start async puzzle generation in background."""
        print(f"[ASYNC] Creating loading widget for {difficulty}")
        
        # Create the loading screen widget
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.floatlayout import FloatLayout
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle
        from kivy.animation import Animation
        
        # Create root widget (FloatLayout to match other screens)
        root = FloatLayout()
        
        # Set background color
        from kivy.core.window import Window
        Window.clearcolor = (0.05, 0.1, 0.15, 1)  # Dark blue for loading
        
        # Main content
        content = BoxLayout(orientation='vertical', padding=dp(50), spacing=dp(20), 
                           size_hint=(0.8, 0.6), pos_hint={'center_x': 0.5, 'center_y': 0.5})
        
        with content.canvas.before:
            Color(0.1, 0.1, 0.2, 0.9)  # Semi-transparent dark background
            self._loading_bg_rect = Rectangle(size=content.size, pos=content.pos)
        content.bind(size=lambda inst, val: setattr(self._loading_bg_rect, 'size', val))
        content.bind(pos=lambda inst, val: setattr(self._loading_bg_rect, 'pos', val))
        
        # Title
        title_label = Label(
            text="Generating Puzzle...",
            font_size=dp(32),
            color=(1, 1, 1, 1),
            size_hint_y=None,
            height=dp(60),
            halign='center'
        )
        content.add_widget(title_label)
        
        # Difficulty label
        difficulty_label = Label(
            text=f"Difficulty: {difficulty}",
            font_size=dp(20),
            color=(0.8, 0.8, 1, 1),
            size_hint_y=None,
            height=dp(40),
            halign='center'
        )
        content.add_widget(difficulty_label)
        
        # Message
        message_label = Label(
            text="This may take a moment for difficult puzzles...",
            font_size=dp(16),
            color=(0.7, 0.7, 0.9, 1),
            size_hint_y=None,
            height=dp(80),
            halign='center',
            text_size=(dp(400), None)
        )
        content.add_widget(message_label)
        
        # Loading animation - improved spinning circle with fallback
        from kivy.uix.widget import Widget
        from kivy.graphics import PushMatrix, PopMatrix, Rotate, Ellipse, Line

        loading_container = Widget(size_hint=(None, None), size=(dp(120), dp(120)))
        loading_container.pos_hint = {'center_x': 0.5}

        # Create a spinning loading circle with better graphics
        with loading_container.canvas:
            PushMatrix()
            self._loading_rotation = Rotate(angle=0, origin=(dp(60), dp(60)))

            # Outer ring (stationary)
            Color(0.3, 0.3, 0.5, 0.5)  # Semi-transparent dark blue
            Line(circle=(dp(60), dp(60), dp(35)), width=2)

            # Inner spinning arc
            Color(0.5, 0.8, 1, 1)  # Bright blue
            Line(circle=(dp(60), dp(60), dp(30), 0, 120), width=4)  # 120-degree arc

            # Additional spinning dots for better visual effect
            Color(0.8, 1, 0.5, 1)  # Green accent
            Ellipse(pos=(dp(85), dp(55)), size=(dp(8), dp(8)))  # Dot at the end of arc

            PopMatrix()

        content.add_widget(loading_container)

        # Start spinning animation with smooth rotation
        def update_rotation(dt):
            if hasattr(self, '_loading_rotation'):
                self._loading_rotation.angle += 6  # Rotate 6 degrees per frame for smooth motion
                if self._loading_rotation.angle >= 360:
                    self._loading_rotation.angle = 0

        # Store the animation event for cleanup later
        self._loading_animation_event = update_rotation
        from kivy.clock import Clock
        Clock.schedule_interval(update_rotation, 1/30.0)  # 30 FPS rotation

        root.add_widget(content)
        
        # Start async generation
        self.start_async_puzzle_generation(difficulty, root)
        
        return root

    def start_async_puzzle_generation(self, difficulty, loading_widget):
        """Start puzzle generation in background thread."""
        print(f"[ASYNC] Starting background generation for {difficulty}")
        
        # Create puzzle generation queue
        self.puzzle_queue = queue.Queue()
        
        # Start puzzle generation in background thread
        thread = threading.Thread(target=self._generate_puzzle_worker, args=(difficulty, loading_widget))
        thread.daemon = True
        thread.start()
        
        # Schedule check for completion
        Clock.schedule_interval(self._check_puzzle_generation, 0.1)



    def _generate_puzzle_worker(self, difficulty, loading_widget):
        """Worker function that runs in background thread to generate puzzle."""
        try:
            print(f"[ASYNC] Worker thread started for {difficulty}")
            print(f"[ASYNC] Creating NEW SudokuGameLogic object for {difficulty}")
            game = SudokuGameLogic(difficulty)
            print(f"[ASYNC] Calling generate_puzzle() on new game object")
            puzzle, solution = game.generate_puzzle()
            
            # Put result in queue
            result = {
                'success': True,
                'game': game,
                'puzzle': puzzle,
                'solution': solution,
                'difficulty': difficulty,
                'loading_widget': loading_widget
            }
            self.puzzle_queue.put(result)
            print(f"[ASYNC] Puzzle generation completed for {difficulty}, queued result")
            
        except Exception as e:
            print(f"[ASYNC] Error generating puzzle: {e}")
            import traceback
            traceback.print_exc()
            # Put error in queue
            result = {
                'success': False,
                'error': str(e),
                'difficulty': difficulty,
                'loading_widget': loading_widget
            }
            self.puzzle_queue.put(result)

    def _check_puzzle_generation(self, dt):
        """Check if puzzle generation is complete."""
        try:
            # Non-blocking check for result
            result = self.puzzle_queue.get_nowait()
            
            if result['success']:
                # Success - replace the loading widget with the actual game screen
                self.game = result['game']
                puzzle = result['puzzle']
                solution = result['solution']
                difficulty = result['difficulty']
                
                print(f"[ASYNC] Setting up game with generated puzzle")
                self.game.puzzle = puzzle
                self.game.solution = solution
                
                # Don't reset hints for new games - hints persist across games
                # Only initialize if not already set
                if not hasattr(self, 'hints_remaining'):
                    self.hints_remaining = 10
                    print(f"[ASYNC] Initialized hints_remaining: {self.hints_remaining}")
                else:
                    print(f"[ASYNC] Using existing hints_remaining: {self.hints_remaining}")
                
                # Save new game state as in-progress
                self.last_game_in_progress = True
                self._save_last_game(puzzle, solution, self.game.board, difficulty, True)
                
                # Replace the loading screen with the actual puzzle screen
                # IMPORTANT: Build the screen directly without going through difficulty checks again
                
                # Clean up any scheduled loading animations
                if hasattr(self, '_loading_animation_event'):
                    Clock.unschedule(self._loading_animation_event)
                    
                self.root.clear_widgets()
                actual_puzzle_screen = self._build_puzzle_screen_direct(difficulty)
                self.root.add_widget(actual_puzzle_screen)
                
                # Stop checking since we're done
                return False
                
            else:
                # Error - show error and return to menu
                print(f"[ASYNC] Puzzle generation failed: {result['error']}")
                
                # Clean up any scheduled loading animations
                if hasattr(self, '_loading_animation_event'):
                    Clock.unschedule(self._loading_animation_event)
                    
                self.show_puzzle_generation_error()
                
                # Stop checking since we're done (with error)
                return False
                
        except queue.Empty:
            # Nothing in queue yet, keep checking
            pass
        except Exception as e:
            print(f"[ASYNC] Error checking puzzle generation: {e}")
            import traceback
            traceback.print_exc()
            
            # Clean up any scheduled loading animations
            if hasattr(self, '_loading_animation_event'):
                Clock.unschedule(self._loading_animation_event)
                
            self.show_puzzle_generation_error()
            
            # Stop checking since we encountered an error
            return False



    def show_puzzle_generation_error(self):
        """Show error popup when puzzle generation fails."""
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.uix.popup import Popup
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle
        
        content = BoxLayout(orientation='vertical', padding=dp(24), spacing=dp(16))
        with content.canvas.before:
            Color(0.5, 0.1, 0.1, 1)  # Dark red background
            _bg_rect = Rectangle(size=content.size, pos=content.pos)
        content.bind(size=lambda inst, val: setattr(_bg_rect, 'size', val))
        content.bind(pos=lambda inst, val: setattr(_bg_rect, 'pos', val))
        
        error_label = Label(
            text="Failed to Generate Puzzle",
            font_size=dp(20),
            color=(1, 1, 1, 1),
            halign='center',
            valign='middle',
            text_size=(dp(300), None),
            size_hint_y=None,
            height=dp(80)
        )
        content.add_widget(error_label)
        
        btn = Button(
            text="Back to Menu",
            font_size=dp(16),
            size_hint=(None, None),
            size=(dp(150), dp(40)),
            background_color=(0.75, 0.75, 0.75, 1),
            color=(0, 0, 0, 1),
            background_normal='',
            background_down=''
        )
        content.add_widget(btn)
        
        popup = Popup(
            title='',
            content=content,
            size_hint=(None, None),
            size=(dp(350), dp(200)),
            auto_dismiss=False,
            separator_height=0,
            background=''
        )
        
        def go_back(instance):
            popup.dismiss()
            self.root.clear_widgets()
            self.welcome_layout = self.build_welcome_screen()
            self.root.add_widget(self.welcome_layout)
        
        btn.bind(on_release=go_back)
        popup.open()

    def _on_window_resize(self, instance, width, height):
        """Track when the window gets maximized to maintain it throughout the session"""
        # Consider window maximized if it's significantly larger than our default sizes
        # This handles various screen resolutions and maximized states
        if width > 800 or height > 900:
            if not self.window_maximized:
                print(f"[WINDOW] Window maximized detected: {width}x{height}")
                self.window_maximized = True
        else:
            # Check if this is a manual resize back to smaller size (user choice)
            # Only reset maximized flag if it's close to our original sizes
            if width <= 650 and height <= 850:
                if self.window_maximized:
                    print(f"[WINDOW] Window manually resized to smaller size: {width}x{height}")
                    self.window_maximized = False

    def _start_clock_updates(self):
        """Start updating the clock display"""
        if not self.settings_show_clock or not hasattr(self, 'clock_label'):
            return
            
        from kivy.clock import Clock
        if self._clock_event:
            self._clock_event.cancel()
        self._clock_event = Clock.schedule_interval(self._update_clock, 1.0)
        
    def _stop_clock_updates(self):
        """Stop updating the clock display"""
        if self._clock_event:
            self._clock_event.cancel()
            self._clock_event = None
            
    def _update_clock(self, dt):
        """Update the clock display with elapsed time"""
        if not self.settings_show_clock or not hasattr(self, 'clock_label') or not hasattr(self, 'start_time'):
            return False
            
        try:
            elapsed = time.time() - self.start_time
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            
            if hours > 0:
                self.clock_label.text = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                self.clock_label.text = f"{minutes:02d}:{seconds:02d}"
        except Exception as e:
            print(f"[CLOCK] Error updating clock: {e}")
            return False
        return True

    def _stop_all_sounds(self):
        """Stop all currently playing sounds and music"""
        try:
            if hasattr(self, '_welcome_music') and self._welcome_music:
                self._welcome_music.stop()
        except Exception as e:
            print(f"[SOUND] Error stopping welcome music: {e}")

        # Stop native Windows audio tracks (used in packaged .exe builds)
        try:
            if self._supports_native_windows_audio():
                self._native_audio_stop('serene_welcome')
                self._native_audio_stop('serene_music')
                # Only stop reward/gameover tracks if their screens are not active
                if not getattr(self, '_reward_screen_showing', False):
                    self._native_audio_stop('serene_reward')
                    self._native_audio_stop('serene_gameover')
                self._native_welcome_music = False
                self._native_music = False
                print("[SOUND] Stopped native Windows audio tracks")
        except Exception as e:
            print(f"[SOUND] Error stopping native Windows audio: {e}")

        try:
            if hasattr(self, '_music') and self._music:
                self._music.stop()
        except Exception as e:
            print(f"[SOUND] Error stopping game music: {e}")
            
        try:
            if hasattr(self, '_game_over_sound') and self._game_over_sound:
                self._game_over_sound.stop()
        except Exception as e:
            print(f"[SOUND] Error stopping game over sound: {e}")
            
        try:
            if hasattr(self, '_reward_sound') and self._reward_sound:
                self._reward_sound.stop()
        except Exception as e:
            print(f"[SOUND] Error stopping reward sound: {e}")

        try:
            if hasattr(self, '_error_sound') and self._error_sound:
                self._error_sound.stop()
        except Exception as e:
            print(f"[SOUND] Error stopping error sound: {e}")

        try:
            if hasattr(self, '_hint_sound') and self._hint_sound:
                self._hint_sound.stop()
        except Exception as e:
            print(f"[SOUND] Error stopping hint sound: {e}")

        try:
            if hasattr(self, '_complete_sound') and self._complete_sound:
                self._complete_sound.stop()
        except Exception as e:
            print(f"[SOUND] Error stopping complete sound: {e}")

    def _supports_pygame_fallback(self):
        """Only attempt pygame audio fallback in non-packaged desktop runs."""
        if hasattr(sys, '_MEIPASS'):
            print("[MUSIC] Skipping pygame fallback inside packaged app")
            return False
        return True

    def _supports_native_windows_audio(self):
        return sys.platform == 'win32'

    def _mci_command(self, command):
        buf = ctypes.create_unicode_buffer(255)
        rc = ctypes.windll.winmm.mciSendStringW(command, buf, 255, None)
        if rc != 0:
            print(f"[AUDIO] MCI command failed ({rc}): {command} -> {buf.value}")
            return False
        return True

    def _native_audio_open(self, path, alias):
        ext = os.path.splitext(path)[1].lower()
        if ext == '.mp3':
            type_name = 'mpegvideo'
        elif ext == '.wav':
            type_name = 'waveaudio'
        else:
            type_name = 'mpegvideo'
        return self._mci_command(f'open "{path}" type {type_name} alias {alias}')

    def _native_audio_play(self, alias, loop=False):
        cmd = f"play {alias} {'repeat' if loop else ''}".strip()
        return self._mci_command(cmd)

    def _native_audio_stop(self, alias):
        self._mci_command(f'stop {alias}')
        self._mci_command(f'close {alias}')

    def _native_audio_play_file(self, path, alias, loop=False):
        if not self._supports_native_windows_audio():
            return False
        if not self._native_audio_open(path, alias):
            return False
        if not self._native_audio_play(alias, loop=loop):
            self._native_audio_stop(alias)
            return False
        return True

    def _restart_game_music(self):
        """Restart the current game's music based on difficulty"""
        if not self.settings_music:
            return
            
        if hasattr(self, 'last_difficulty') and self.last_difficulty:
            try:
                from kivy.core.audio import SoundLoader
                music_file = resource_path(f"Sounds/{str(self.last_difficulty).lower()}.mp3")
                print(f"[MUSIC] Restarting game music: {music_file}")
                
                # Stop current music first
                if hasattr(self, '_music') and self._music:
                    self._music.stop()
                    
                abs_path = os.path.abspath(music_file)
                if hasattr(sys, '_MEIPASS') and self._supports_native_windows_audio():
                    if self._native_audio_play_file(abs_path, 'serene_music', loop=True):
                        self._native_music = True
                        print(f"[MUSIC] Native Windows audio playback started for packaged build: {abs_path}")
                        return
                    print(f"[MUSIC] Native Windows audio fallback failed for packaged build: {abs_path}")

                self._music = SoundLoader.load(music_file)
                if self._music:
                    self._music.loop = True
                    self._music.play()
                    if getattr(self._music, 'state', None) != 'play' and self._supports_native_windows_audio():
                        print(f"[MUSIC] Kivy failed to start playback; using native Windows audio for {music_file}")
                        self._native_audio_stop('serene_music')
                        if self._native_audio_play_file(abs_path, 'serene_music', loop=True):
                            self._music = None
                            self._native_music = True
                    else:
                        print(f"[MUSIC] Successfully restarted: {music_file}")
                else:
                    print(f"[MUSIC] Failed to load: {music_file}")
                    if self._supports_native_windows_audio():
                        abs_path = os.path.abspath(resource_path(f"Sounds/{str(self.last_difficulty).lower()}.mp3"))
                        if self._native_audio_play_file(abs_path, 'serene_music', loop=True):
                            self._native_music = True
                            print(f"[MUSIC] Native Windows audio playback started: {abs_path}")
                        else:
                            print(f"[MUSIC] Native Windows audio fallback failed: {abs_path}")
                    elif self._supports_pygame_fallback():
                        try:
                            import pygame
                            if not getattr(self, '_pygame_inited', False):
                                pygame.mixer.init()
                                self._pygame_inited = True
                            abs_path = os.path.abspath(resource_path(f"Sounds/{str(self.last_difficulty).lower()}.mp3"))
                            print(f"[MUSIC] Pygame fallback loading: {abs_path}")
                            pygame.mixer.music.load(abs_path)
                            pygame.mixer.music.play(-1)
                            self._pygame_music = True
                            print(f"[MUSIC] Pygame fallback playing: {abs_path}")
                        except Exception as e:
                            print(f"[MUSIC] Pygame fallback failed: {e}")
            except Exception as e:
                print(f"[MUSIC] Error restarting game music: {e}")

    def _stop_menu_sounds(self):
        """Stop welcome music and other menu sounds"""
        try:
            if self._welcome_music:
                self._welcome_music.stop()
        except Exception as e:
            print(f"[SOUND] Error stopping welcome music: {e}")
        try:
            # Also stop pygame-based playback if used
            import pygame
            if getattr(self, '_pygame_music', False):
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
        except Exception:
            pass
        if getattr(self, '_native_music', False):
            try:
                self._native_audio_stop('serene_music')
            except Exception as e:
                print(f"[AUDIO] Error stopping native music: {e}")
        if getattr(self, '_native_welcome_music', False):
            try:
                self._native_audio_stop('serene_welcome')
            except Exception as e:
                print(f"[AUDIO] Error stopping native welcome music: {e}")
            
    def _play_welcome_music(self):
        """Play welcome music on loop"""
        if not self.settings_music:
            return
            
        try:
            # Stop any existing welcome music first
            self._stop_menu_sounds()
            
            abs_path = os.path.abspath(resource_path('Sounds/welcome.mp3'))
            if hasattr(sys, '_MEIPASS') and self._supports_native_windows_audio():
                if self._native_audio_play_file(abs_path, 'serene_welcome', loop=True):
                    self._native_music = True
                    self._native_welcome_music = True
                    print(f"[SOUND] Native Windows audio playing welcome music: {abs_path}")
                    return
                print(f"[SOUND] Native Windows audio fallback failed for packaged build: {abs_path}")

            if not self._welcome_music:
                self._welcome_music = SoundLoader.load(abs_path)
            if self._welcome_music:
                self._welcome_music.loop = True
                self._welcome_music.play()
                if getattr(self._welcome_music, 'state', None) != 'play' and self._supports_native_windows_audio():
                    print(f"[SOUND] Kivy failed to start playback; using native Windows audio for {abs_path}")
                    self._native_audio_stop('serene_welcome')
                    if self._native_audio_play_file(abs_path, 'serene_welcome', loop=True):
                        self._native_music = True
                        self._native_welcome_music = True
                        self._welcome_music = None
                        print(f"[SOUND] Native Windows audio playing welcome music: {abs_path}")
                    else:
                        print(f"[SOUND] Native Windows audio fallback failed: {abs_path}")
                else:
                    print("[SOUND] Playing welcome music")
            else:
                print("[SOUND] Failed to load welcome.mp3")
                if self._supports_native_windows_audio():
                    abs_path = os.path.abspath(resource_path('Sounds/welcome.mp3'))
                    if self._native_audio_play_file(abs_path, 'serene_welcome', loop=True):
                        self._native_music = True
                        self._native_welcome_music = True
                        print(f"[SOUND] Native Windows audio playing welcome music: {abs_path}")
                    else:
                        print(f"[SOUND] Native Windows audio fallback failed: {abs_path}")
                elif self._supports_pygame_fallback():
                    print("[SOUND] Trying pygame fallback")
                    try:
                        import pygame
                        if not getattr(self, '_pygame_inited', False):
                            pygame.mixer.init()
                            self._pygame_inited = True
                        abs_path = os.path.abspath(resource_path('Sounds/welcome.mp3'))
                        pygame.mixer.music.load(abs_path)
                        pygame.mixer.music.play(-1)
                        self._pygame_music = True
                        print(f"[SOUND] Pygame playing welcome music: {abs_path}")
                    except Exception as e:
                        print(f"[SOUND] Pygame fallback failed: {e}")
                else:
                    print("[SOUND] No desktop audio fallback available")
        except Exception as e:
            print(f"[SOUND] Error playing welcome music: {e}")
            
    def _play_reward_sound(self):
        """Play reward sound once, in full, using native MCI (no auto-close timer)."""
        if not self.settings_sounds:
            print("[SOUND] Reward sound suppressed because sounds are disabled")
            return
        if hasattr(sys, '_MEIPASS') and self._supports_native_windows_audio():
            import os as _os
            abs_path = _os.path.abspath(resource_path('Sounds/reward.mp3'))
            self._native_audio_stop('serene_reward')  # clear any previous
            if self._native_audio_play_file(abs_path, 'serene_reward', loop=False):
                print("[SOUND] Native MCI playing reward sound in full")
                return
        # Non-packaged fallback
        from kivy.clock import Clock
        Clock.schedule_once(lambda dt: self._play_sfx('Sounds/reward.mp3'), 0.06)
            
    def _play_game_over_sound(self):
        """Play game over sound once, in full, using native MCI (no auto-close timer)."""
        if not self.settings_sounds:
            return
        if hasattr(sys, '_MEIPASS') and self._supports_native_windows_audio():
            import os as _os
            abs_path = _os.path.abspath(resource_path('Sounds/game_over.mp3'))
            self._native_audio_stop('serene_gameover')  # clear any previous
            if self._native_audio_play_file(abs_path, 'serene_gameover', loop=False):
                print("[SOUND] Native MCI playing game over sound in full")
                return
        # Non-packaged fallback
        self._play_sfx('Sounds/game_over.mp3')

    def _init_pygame_sfx(self):
        pass  # pygame excluded from build; no-op

    def _play_sfx(self, relative_path, alias=None):
        """Play a one-shot sound effect in the packaged .exe.

        Strategy:
          - WAV  -> winsound (instant, built-in, rapid-fire safe)
          - MP3  -> MCI with a unique alias per call (rapid-fire safe because
                    each open/play gets its own handle; auto-closed after 4 s)
          - OGG  -> not supported by MCI; must be converted to WAV beforehand
        Falls back to Kivy SoundLoader in non-packaged / dev runs.
        """
        import os as _os
        abs_path = _os.path.abspath(resource_path(relative_path))
        ext = _os.path.splitext(relative_path)[1].lower()

        if hasattr(sys, '_MEIPASS'):
            if ext == '.wav':
                try:
                    import winsound
                    winsound.PlaySound(
                        abs_path,
                        winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
                    )
                    print(f"[SOUND] winsound playing: {relative_path}")
                    return
                except Exception as e:
                    print(f"[SOUND] winsound failed for {relative_path}: {e}")

            elif ext == '.mp3':
                import time as _time
                # Unique alias per call — lets multiple SFX overlap safely
                sfx_alias = f"sfx{int(_time.time()*10000) % 99999999}"
                try:
                    if self._mci_command(f'open "{abs_path}" type mpegvideo alias {sfx_alias}'):
                        self._mci_command(f'play {sfx_alias}')
                        print(f"[SOUND] MCI playing: {relative_path} ({sfx_alias})")
                        from kivy.clock import Clock
                        Clock.schedule_once(
                            lambda dt, a=sfx_alias: self._mci_command(f'close {a}'), 4
                        )
                        return
                except Exception as e:
                    print(f"[SOUND] MCI failed for {relative_path}: {e}")

            else:
                print(f"[SOUND] Unsupported format in packaged build: {relative_path}")
            return

        # Non-packaged dev run: use Kivy SoundLoader
        try:
            snd = SoundLoader.load(abs_path)
            if snd:
                snd.loop = False
                snd.play()
                print(f"[SOUND] SoundLoader playing: {relative_path}")
            else:
                print(f"[SOUND] SoundLoader failed to load: {relative_path}")
        except Exception as e:
            print(f"[SOUND] SoundLoader error for {relative_path}: {e}")

    def _play_button_click_sound(self):
        """Play button click sound once"""
        if not self.settings_sounds:
            return
            
        self._play_sfx('Sounds/button_click.mp3', alias='sfx_btn_click')

    def _play_cell_select_sound(self):
        """Play cell select sound once"""
        if not self.settings_sounds:
            return

        self._play_sfx('Sounds/cell_select.wav', alias='sfx_cell_select')

    def _play_cell_fill_sound(self):
        """Play cell fill sound once"""
        if not self.settings_sounds:
            return
            
        self._play_sfx('Sounds/cell_fill.mp3', alias='sfx_cell_fill')

    def _play_pencil_click_sound(self):
        """Play pencil click sound once (with fallbacks)."""
        if not self.settings_sounds:
            return

        self._play_sfx('Sounds/pencil_write.wav', alias='sfx_pencil_write')

    def _play_game_start_sound(self):
        """Play game start sound once"""
        if not self.settings_sounds:
            return
            
        print("[DEBUG] _play_game_start_sound() called")
        self._play_sfx('Sounds/game_start.mp3', alias='sfx_game_start')

    def _play_pencil_write_sound(self):
        """Play pencil write sound once (with fallbacks and robust handling)."""
        if not self.settings_sounds:
            print("[SOUND] Not playing pencil write sound because sounds are disabled")
            return

        self._play_sfx('Sounds/pencil_write.wav', alias='sfx_pencil_write')

    def _play_pencil_erase_sound(self):
        """Play pencil erase sound once"""
        if not self.settings_sounds:
            return
            
        self._play_sfx('Sounds/clear.wav', alias='sfx_clear')

    def _play_undo_sound(self):
        """Play undo sound once"""
        if not self.settings_sounds:
            return
            
        self._play_sfx('Sounds/undo.mp3', alias='sfx_undo')

    def _play_error_sound(self):
        """Play error sound once"""
        if not self.settings_sounds:
            return
            
        self._play_sfx('Sounds/error.wav', alias='sfx_error')

    def _play_hint_sound(self):
        """Play hint sound once"""
        if not self.settings_sounds:
            return
            
        self._play_sfx('Sounds/hint.mp3', alias='sfx_hint')

    def _open_tutorial(self):
        """Open the How to Play tutorial HTML file."""
        print("[TUTORIAL] _open_tutorial called!")
        if hasattr(self, 'debug_label') and self.debug_label:
            self.debug_label.text = "TUTORIAL: Preparing File..."

        import os
        from kivy.utils import platform

        try:
            # Retrieve content
            try:
                from tutorial_content import TUTORIAL_HTML
            except ImportError:
                # Fallback content if import fails
                TUTORIAL_HTML = "<html><body><h1>Error</h1><p>Tutorial content missing.</p></body></html>"

            if platform == 'android':
                # In-app WebView with Back to Menu button
                try:
                    from jnius import autoclass
                    from android.runnable import run_on_ui_thread

                    print("[TUTORIAL] Importing Android classes...")
                    PythonActivity = autoclass('org.kivy.android.PythonActivity')
                    activity = PythonActivity.mActivity
                    WebView = autoclass('android.webkit.WebView')
                    WebViewClient = autoclass('android.webkit.WebViewClient')
                    WebChromeClient = autoclass('android.webkit.WebChromeClient')
                    Dialog = autoclass('android.app.Dialog')
                    FrameLayout = autoclass('android.widget.FrameLayout')
                    LinearLayout = autoclass('android.widget.LinearLayout')
                    LinearLayout_LayoutParams = autoclass('android.widget.LinearLayout$LayoutParams')
                    Button = autoclass('android.widget.Button')
                    FrameLayout_LayoutParams = autoclass('android.widget.FrameLayout$LayoutParams')
                    View = autoclass('android.view.View')
                    Gravity = autoclass('android.view.Gravity')
                    
                    # Write HTML to cache
                    cache_dir = activity.getCacheDir().getAbsolutePath()
                    file_path = os.path.join(cache_dir, "tutorial.html")
                    print(f"[TUTORIAL] Writing content to: {file_path}")
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(TUTORIAL_HTML)
                    
                    url_to_load = "file://" + file_path

                    @run_on_ui_thread
                    def show_webview():
                        from kivy.clock import Clock
                        print("[TUTORIAL] UI Thread: Starting...")
                        
                        try:
                            # Create fullscreen dialog
                            if hasattr(self, 'debug_label'):
                                self.debug_label.text = 'TUTORIAL: Creating Dialog'
                            
                            # Use fullscreen theme
                            THEME_NO_TITLE_FULLSCREEN = 0x01030007  # android.R.style.Theme_NoTitleBar_Fullscreen
                            dialog = Dialog(activity, THEME_NO_TITLE_FULLSCREEN)
                            print("[TUTORIAL] Dialog created")
                            
                            # Create WebView with explicit size
                            if hasattr(self, 'debug_label'):
                                self.debug_label.text = 'TUTORIAL: Creating WebView'
                            webview = WebView(activity)
                            
                            # Set WebView layout params to MATCH_PARENT
                            print("[TUTORIAL] WebView created")
                            
                            # Create vertical LinearLayout so button gets its own space below WebView
                            if hasattr(self, 'debug_label'):
                                self.debug_label.text = 'TUTORIAL: Creating Layout'
                            layout = LinearLayout(activity)
                            layout.setOrientation(LinearLayout.VERTICAL)
                            
                            # Add bottom padding for navigation bar so button isn't hidden
                            try:
                                resources = activity.getResources()
                                nav_res_id = resources.getIdentifier("navigation_bar_height", "dimen", "android")
                                nav_height = 0
                                if nav_res_id > 0:
                                    nav_height = resources.getDimensionPixelSize(nav_res_id)
                                layout.setPadding(0, 0, 0, nav_height)
                                print(f"[TUTORIAL] Nav bar padding set: {nav_height}px")
                            except Exception as e:
                                print(f"[TUTORIAL] Could not get nav bar height: {e}")
                                layout.setPadding(0, 0, 0, 100)  # Fallback padding
                            
                            # Add WebView with weight=1 to fill remaining space above button
                            webview_lp = LinearLayout_LayoutParams(
                                LinearLayout_LayoutParams.MATCH_PARENT,
                                0,   # height 0
                                1.0  # weight 1 fills remaining space
                            )
                            layout.addView(webview, webview_lp)
                            print("[TUTORIAL] Layout created with LinearLayout")
                            
                            # Configure WebView settings
                            if hasattr(self, 'debug_label'):
                                self.debug_label.text = 'TUTORIAL: Getting Settings'
                            settings = webview.getSettings()
                            settings.setJavaScriptEnabled(True)
                            settings.setAllowFileAccess(True)
                            settings.setAllowContentAccess(True)
                            settings.setAllowFileAccessFromFileURLs(True)
                            settings.setAllowUniversalAccessFromFileURLs(True)
                            settings.setLoadWithOverviewMode(True)
                            settings.setUseWideViewPort(True)
                            print("[TUTORIAL] WebView configured")
                            
                            # Set WebView clients
                            webview.setWebViewClient(WebViewClient())
                            webview.setWebChromeClient(WebChromeClient())
                            webview.setBackgroundColor(-1)  # White (0xFFFFFFFF as signed int)
                            
                            # Create Back to Menu button
                            if hasattr(self, 'debug_label'):
                                self.debug_label.text = 'TUTORIAL: Creating Button'
                            
                            # Create button using proper Android API
                            String = autoclass('java.lang.String')
                            back_button = Button(activity)
                            button_text = String("Back to Menu")
                            back_button.setText(button_text)
                            
                            # Set button colors using ColorDrawable
                            ColorDrawable = autoclass('android.graphics.drawable.ColorDrawable')
                            maroon_drawable = ColorDrawable(-8388608)  # Maroon
                            back_button.setBackground(maroon_drawable)
                            back_button.setTextColor(-1)  # White
                            
                            # Button click handler - keep reference to prevent garbage collection
                            from jnius import PythonJavaClass, java_method
                            
                            class ClickListener(PythonJavaClass):
                                __javainterfaces__ = ['android/view/View$OnClickListener']
                                
                                def __init__(self, dialog_to_dismiss):
                                    super().__init__()
                                    self.dialog_to_dismiss = dialog_to_dismiss
                                
                                @java_method('(Landroid/view/View;)V')
                                def onClick(self, view):
                                    try:
                                        print("[TUTORIAL] Back button clicked")
                                        self.dialog_to_dismiss.dismiss()
                                        print("[TUTORIAL] Dialog dismissed successfully")
                                    except Exception as e:
                                        print(f"[TUTORIAL] Error dismissing dialog: {e}")
                                        import traceback
                                        traceback.print_exc()
                            
                            # Keep reference to listener to prevent garbage collection
                            click_listener = ClickListener(dialog)
                            back_button.setOnClickListener(click_listener)
                            
                            # Button at bottom of LinearLayout with its own dedicated space
                            button_lp = LinearLayout_LayoutParams(
                                LinearLayout_LayoutParams.MATCH_PARENT,
                                LinearLayout_LayoutParams.WRAP_CONTENT
                            )
                            
                            # Add padding to button so text is visible
                            back_button.setPadding(20, 40, 20, 40)
                            
                            layout.addView(back_button, button_lp)
                            print("[TUTORIAL] Button added")
                            
                            # Load URL and show dialog
                            if hasattr(self, 'debug_label'):
                                self.debug_label.text = 'TUTORIAL: Loading Content'
                            webview.loadUrl(url_to_load)
                            
                            # Set dialog content and make it fullscreen
                            dialog.setContentView(layout)
                            
                            # Get window and set to fullscreen
                            window = dialog.getWindow()
                            if window:
                                WindowManager_LayoutParams = autoclass('android.view.WindowManager$LayoutParams')
                                window.setLayout(
                                    WindowManager_LayoutParams.MATCH_PARENT,
                                    WindowManager_LayoutParams.MATCH_PARENT
                                )
                            
                            dialog.setCancelable(True)
                            dialog.show()
                            
                            if hasattr(self, 'debug_label'):
                                self.debug_label.text = 'TUTORIAL: SUCCESS!'
                            print("[TUTORIAL] Tutorial displayed successfully")
                            
                        except Exception as e:
                            print(f"[TUTORIAL] Error: {e}")
                            import traceback
                            traceback.print_exc()
                            if hasattr(self, 'debug_label'):
                                error_msg = str(e)[:30] if len(str(e)) > 30 else str(e)
                                self.debug_label.text = f'TUTORIAL FAIL: {error_msg}'
                    
                    show_webview()

                except Exception as e:
                    print(f"[TUTORIAL] Android setup failed: {e}")
                    import traceback
                    traceback.print_exc()
                    if hasattr(self, 'debug_label') and self.debug_label:
                        self.debug_label.text = f"Err: {str(e)[:15]}"
                    
                    # 1. Write HTML to Cache Dir (Python side)
                    cache_dir = activity.getCacheDir().getAbsolutePath()
                    file_path = os.path.join(cache_dir, "tutorial_gen.html")
                    print(f"[TUTORIAL] Writing content to: {file_path}")
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(TUTORIAL_HTML)
                    
                    url_to_load = "file://" + file_path
                    
                    # 2. Setup Dialog (UI Thread)
                    # android.R.style.Theme_NoTitleBar_Fullscreen = 0x01030007
                    THEME_FULLSCREEN = 0x01030007 

                    # Helper functions for WebView configuration
                    def tutorial_step4_config(app_instance, webview):
                        from kivy.clock import Clock
                        # Set the "getting settings" message and immediately try to get settings
                        app_instance.debug_label.text = 'TUTORIAL: GETTING SETTINGS'

                        # Try some very basic WebView operations first
                        try:
                            print(f"[TUTORIAL] WebView object: {webview}")
                            print(f"[TUTORIAL] WebView class: {type(webview)}")

                            # Try basic WebView methods that should work
                            print("[TUTORIAL] Trying basic WebView methods...")
                            webview.getUrl()  # This should work even if no URL is loaded
                            print("[TUTORIAL] getUrl() worked")

                            webview.canGoBack()  # Basic navigation check
                            print("[TUTORIAL] canGoBack() worked")

                        except Exception as e:
                            print(f"[TUTORIAL] Basic WebView methods failed: {e}")
                            app_instance.debug_label.text = f'TUTORIAL: BASIC FAIL - {str(e)[:15]}'
                            return

                        # Use a very short delay to avoid blocking the UI thread
                        Clock.schedule_once(lambda dt: tutorial_get_settings(app_instance, webview), 0.1)
                    
                    def tutorial_get_settings(app_instance, webview):
                        try:
                            print("[TUTORIAL] About to call getSettings()...")
                            print(f"[TUTORIAL] WebView object: {webview}")
                            print(f"[TUTORIAL] WebView class: {type(webview)}")

                            # Try to call getSettings
                            settings = webview.getSettings()
                            print("[TUTORIAL] getSettings() succeeded")
                            print(f"[TUTORIAL] Settings object: {settings}")

                            # Set success message immediately
                            app_instance.debug_label.text = 'TUTORIAL: SETTINGS OK'
                            # Continue with JS settings
                            Clock.schedule_once(lambda dt: tutorial_js_setting(app_instance, settings), 0.1)
                        except Exception as e:
                            print(f"[TUTORIAL] getSettings() failed with error: {e}")
                            print(f"[TUTORIAL] Exception type: {type(e)}")
                            import traceback
                            traceback.print_exc()

                            # Show detailed error immediately
                            error_msg = str(e)[:20] if len(str(e)) > 20 else str(e)
                            app_instance.debug_label.text = f'TUTORIAL: FAIL - {error_msg}'
                    
                    def tutorial_js_setting(app_instance, settings):
                        app_instance.debug_label.text = 'TUTORIAL: SETTING JS'
                        Clock.schedule_once(lambda dt: tutorial_js_enable(app_instance, settings), 0.1)
                    
                    def tutorial_js_enable(app_instance, settings):
                        try:
                            settings.setJavaScriptEnabled(True)
                            app_instance.debug_label.text = 'TUTORIAL: JS OK'
                            Clock.schedule_once(lambda dt: tutorial_file_access(app_instance, settings), 0.1)
                        except Exception as e:
                            app_instance.debug_label.text = 'TUTORIAL: JS FAIL'
                    
                    def tutorial_file_access(app_instance, settings):
                        app_instance.debug_label.text = 'TUTORIAL: SETTING FILE'
                        Clock.schedule_once(lambda dt: tutorial_file_enable(app_instance, settings), 0.1)
                    
                    def tutorial_file_enable(app_instance, settings):
                        try:
                            settings.setAllowFileAccess(True)
                            app_instance.debug_label.text = 'TUTORIAL: FILE OK'
                            Clock.schedule_once(lambda dt: tutorial_finish_config(app_instance, settings, webview, url_to_load, dialog), 0.1)
                        except Exception as e:
                            app_instance.debug_label.text = 'TUTORIAL: FILE FAIL'
                    
                    def tutorial_finish_config(app_instance, settings, webview, url_to_load, dialog):
                        # Finish remaining settings quickly
                        try:
                            settings.setAllowContentAccess(True)
                            settings.setAllowFileAccessFromFileURLs(True)
                            settings.setAllowUniversalAccessFromFileURLs(True)
                            settings.setDomStorageEnabled(True)
                            settings.setDatabaseEnabled(True)
                            settings.setLoadWithOverviewMode(True)
                            settings.setUseWideViewPort(True)
                            settings.setBuiltInZoomControls(True)
                            settings.setDisplayZoomControls(False)
                            
                            # Configure WebView clients
                            webview.setWebChromeClient(WebChromeClient())
                            webview.setBackgroundColor(0xFFFFFFFF)
                            webview.setWebViewClient(WebViewClient())
                            
                            # Load URL and show dialog
                            webview.loadUrl(url_to_load)
                            dialog.setContentView(layout)  # Use layout instead of webview directly
                            dialog.setCancelable(True)
                            dialog.show()
                            
                            app_instance.debug_label.text = 'TUTORIAL: SUCCESS!'
                        except Exception as e:
                            app_instance.debug_label.text = 'TUTORIAL: FINAL FAIL'

                    @run_on_ui_thread
                    def show_webview():
                        from kivy.clock import Clock
                        print("[TUTORIAL] UI Thread: Function started")

                        # Step 1: Basic dialog creation
                        try:
                            Clock.schedule_once(lambda dt: setattr(self.debug_label, 'text', 'TUTORIAL: Step 1 - Dialog'), 0)
                            print("[TUTORIAL] Creating basic dialog...")
                            dialog = Dialog(activity)
                            print("[TUTORIAL] Basic dialog created")
                            Clock.schedule_once(lambda dt: setattr(self.debug_label, 'text', 'TUTORIAL: Step 1 - OK'), 0)

                            # Step 2: Set theme
                            Clock.schedule_once(lambda dt: setattr(self.debug_label, 'text', 'TUTORIAL: Step 2 - Theme'), 0)
                            print("[TUTORIAL] Setting fullscreen theme...")
                            # Try without theme first to see if that works
                            # dialog.getWindow().setFlags(0x00000400, 0x00000400)  # FLAG_FULLSCREEN
                            print("[TUTORIAL] Theme set")
                            Clock.schedule_once(lambda dt: setattr(self.debug_label, 'text', 'TUTORIAL: Step 2 - OK'), 0)

                            # Step 3: Create WebView
                            Clock.schedule_once(lambda dt: setattr(self.debug_label, 'text', 'TUTORIAL: Step 3 - WebView'), 0)
                            print("[TUTORIAL] Creating WebView...")
                            
                            # Try different WebView creation approaches
                            try:
                                # Method 1: Standard constructor with activity
                                webview = WebView(activity)
                                print("[TUTORIAL] WebView created with activity context")
                            except Exception as e:
                                print(f"[TUTORIAL] Standard constructor failed: {e}")
                                try:
                                    # Method 2: Try with application context
                                    app_context = activity.getApplicationContext()
                                    webview = WebView(app_context)
                                    print("[TUTORIAL] WebView created with app context")
                                except Exception as e2:
                                    print(f"[TUTORIAL] App context failed: {e2}")
                                    try:
                                        # Method 3: Try with null context (sometimes works)
                                        webview = WebView(None)
                                        print("[TUTORIAL] WebView created with null context")
                                    except Exception as e3:
                                        print(f"[TUTORIAL] Null context failed: {e3}")
                                        raise e  # Re-raise original error

                            # Create a FrameLayout and add WebView to it for proper initialization
                            layout = FrameLayout(activity)
                            layout.addView(webview)
                            print("[TUTORIAL] WebView added to layout")

                            # Try some basic WebView initialization calls
                            try:
                                webview.setWebViewClient(WebViewClient())
                                webview.setWebChromeClient(WebChromeClient())
                                print("[TUTORIAL] WebView clients set")

                                # Try getSettings immediately after basic setup
                                print("[TUTORIAL] Testing getSettings right after creation...")
                                test_settings = webview.getSettings()
                                print("[TUTORIAL] getSettings worked immediately after creation!")

                            except Exception as e:
                                print(f"[TUTORIAL] Setting clients or immediate getSettings failed: {e}")

                            Clock.schedule_once(lambda dt: setattr(self.debug_label, 'text', 'TUTORIAL: Step 3 - OK'), 0)

                            # Step 4: Configure WebView
                            Clock.schedule_once(lambda dt: setattr(self.debug_label, 'text', 'TUTORIAL: Step 4 - Config'), 0)
                            
                            # Start the configuration process
                            tutorial_step4_config(self, webview)

                        except Exception as e:
                            print(f"[TUTORIAL] Error in step-by-step: {e}")
                            import traceback
                            traceback.print_exc()
                            Clock.schedule_once(lambda dt: setattr(self.debug_label, 'text', f'TUTORIAL ERROR: {str(e)[:15]}'), 0)

                    show_webview()
                    if hasattr(self, 'debug_label') and self.debug_label:
                        self.debug_label.text = "TUTORIAL: Window Launched"

                except Exception as e:
                    print(f"[TUTORIAL] Android setup failed: {e}")
                    import traceback
                    traceback.print_exc()
                    if hasattr(self, 'debug_label') and self.debug_label:
                        self.debug_label.text = f"Err: {str(e)[:15]}"
                        # Show full error on screen for debugging
                        from kivy.uix.popup import Popup
                        from kivy.uix.label import Label
                        from kivy.uix.button import Button
                        from kivy.metrics import dp
                        
                        error_popup = Popup(
                            title='Tutorial Error',
                            content=Label(text=f'Error opening tutorial:\n{str(e)}\n\nTraceback:\n{traceback.format_exc()[:200]}...'),
                            size_hint=(0.8, 0.6),
                            auto_dismiss=True
                        )
                        error_popup.open()
                    print(f"[TUTORIAL] Android setup failed: {e}")
                    import traceback
                    traceback.print_exc()
                    if hasattr(self, 'debug_label') and self.debug_label:
                        self.debug_label.text = f"Err: {str(e)[:15]}"
                        # Show full error on screen for debugging
                        from kivy.uix.popup import Popup
                        from kivy.uix.label import Label
                        from kivy.uix.button import Button
                        from kivy.metrics import dp
                        
                        error_popup = Popup(
                            title='Tutorial Error',
                            content=Label(text=f'Error opening tutorial:\n{str(e)}\n\nTraceback:\n{traceback.format_exc()[:200]}...'),
                            size_hint=(0.8, 0.6),
                            auto_dismiss=True
                        )
                        error_popup.open()

            else:
                # Desktop fallback - open the local HTML file with the system default handler.
                try:
                    path = os.path.abspath(resource_path('sudoku_tutorial.html'))
                    if not os.path.exists(path):
                        path = os.path.abspath('sudoku_tutorial.html')

                    # On Windows prefer os.startfile to avoid malformed file:// URIs
                    if os.name == 'nt':
                        os.startfile(path)
                    else:
                        from pathlib import Path
                        import webbrowser
                        url = Path(path).absolute().as_uri()
                        webbrowser.open(url)

                    if hasattr(self, 'debug_label') and self.debug_label:
                        self.debug_label.text = "TUTORIAL: Browser (Desktop)"
                except Exception as e:
                    print(f"[TUTORIAL] Desktop open failed: {e}")

        except Exception as e:
            print(f"[TUTORIAL] Error opening tutorial: {e}")
            if hasattr(self, 'debug_label') and self.debug_label:
                self.debug_label.text = f"Err: {str(e)[:15]}"

    def _play_complete_sound(self):
        if not self.settings_sounds:
            return
        self._play_sfx('Sounds/complete.mp3', alias='sfx_complete')

    def on_pause(self):
        """
        Called when the application is paused on Android/iOS.
        Save current game state and stop the timer when paused.
        """
        print("[LIFECYCLE] Application paused")
        # Stop clock timer when paused to not count pause time
        if self._clock_event:
            self._stop_clock_updates()
        # Track pause time to subtract from completion time
        self._pause_time = time.time()
        if hasattr(self, 'game') and hasattr(self.game, 'puzzle') and hasattr(self.game, 'solution'):
            self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, 
                                 self.last_difficulty, self.last_game_in_progress)
            print("[LIFECYCLE] Saved game state on pause")
        # Return True to prevent the app from being stopped
        return True
    
    def on_resume(self):
        """
        Called when the application resumes from pause on Android/iOS.
        Resume the timer if puzzle is still active.
        """
        print("[LIFECYCLE] Application resumed")
        # If pause time was recorded, add it to start_time to offset the pause duration
        if hasattr(self, '_pause_time') and self._pause_time and hasattr(self, 'start_time'):
            pause_duration = time.time() - self._pause_time
            self.start_time += pause_duration  # Shift start_time forward to exclude pause
            print(f"[LIFECYCLE] Adjusted start_time by {pause_duration:.1f}s to exclude pause")
            self._pause_time = None
        # Restart the clock if the puzzle is still active
        if hasattr(self, 'settings_show_clock') and self.settings_show_clock:
            if hasattr(self, 'clock_label'):
                self._start_clock_updates()
        return
        
    def on_stop(self):
        """
        Called when the application is stopped/closed.
        Save any unsaved game state and stop the timer.
        """
        print("[LIFECYCLE] Application stopping")
        # Stop the clock timer
        if self._clock_event:
            self._stop_clock_updates()
        if hasattr(self, 'game') and hasattr(self.game, 'puzzle') and hasattr(self.game, 'solution'):
            self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, 
                                 self.last_difficulty, self.last_game_in_progress)
            print("[LIFECYCLE] Saved game state on stop")
        return
    
    def build(self):
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.metrics import dp
        from kivy.core.window import Window
        from kivy.uix.image import Image
        from kivy.uix.floatlayout import FloatLayout
        import os
        from kivy.clock import Clock
        
        # Initialize Cross-Platform Billing Manager (Android: Google Play, Windows: Store)
        self.billing_manager = create_billing_manager(self)
        # Initialize billing connection (will be deferred on Android/Windows until needed)
        Clock.schedule_once(lambda dt: self.billing_manager.initialize(), 2)
        print("[BILLING] Billing Manager initialized")
        
        # Register Japanese font for Android - CRITICAL for Japanese text display
        from kivy.core.text import LabelBase
        try:
            LabelBase.register(name="msgothic", fn_regular=FONT_PATH_MSGOTHIC)
            print(f"[FONT] Successfully registered Japanese font: {FONT_PATH_MSGOTHIC}")
        except Exception as e:
            print(f"[FONT] WARNING: Could not register Japanese font: {e}")

        Window.clearcolor = (0.05, 0.25, 0.08, 1)  # Dark green

        # Only set window size if not maximized
        if not self.window_maximized:
            # Set desktop dev window size only
            # if platform not in ('android','ios'):
            #     Window.size = (600, 850)
            Window.top = 50  # Position window higher up on screen to avoid taskbar
            print("[WINDOW] Setting default welcome screen size: 600x850")
        else:
            print(f"[WINDOW] Maintaining maximized window size: {Window.size}")

        self.last_difficulty = getattr(self, "last_difficulty", None)
        # Do not overwrite last_game_in_progress here; it is loaded in __init__

        self.locked_digit = None
        self.padlock_img = None

        # --- Splash Screen Logic ---
        splash_path = resource_path('Images/splash.png')
        splash_layout = FloatLayout(size_hint=(1, 1))
        # Full-screen splash that maintains aspect ratio and is centered
        splash_img = Image(source=splash_path, allow_stretch=True, keep_ratio=True, 
                          size_hint=(1, 1), pos_hint={'center_x': 0.5, 'center_y': 0.5})
        splash_layout.add_widget(splash_img)
        self._splash_layout = splash_layout
        self._splash_img = splash_img  # Store reference for later removal
        
        # Maximize window immediately on desktop so splash displays fullscreen
        if platform not in ('android', 'ios'):
            Window.maximize()

        # Pre-build welcome screen in background during splash (after short delay for UI to render)
        # This eliminates the blank white screen between splash and welcome
        self._prebuilt_welcome = None
        self._splash_start_time = time.time()
        def prebuild_welcome(dt):
            try:
                self._prebuilt_welcome = self.build_welcome_screen()
                # Add welcome to the splash layout BEHIND the splash (at index 0)
                self._splash_layout.add_widget(self._prebuilt_welcome, index=0)
                # Calculate remaining time to show splash (minimum 8 seconds total)
                elapsed = time.time() - self._splash_start_time
                remaining = max(0, 8.0 - elapsed)
                Clock.schedule_once(self._show_welcome_screen, remaining)
            except Exception as e:
                print(f"[ERROR] Failed to pre-build welcome screen: {e}")
        Clock.schedule_once(prebuild_welcome, 6.0)  # Start prebuilding after 6.0s to let splash display
        return self._splash_layout

    def _show_welcome_screen(self, *args):
        try:
            # Remove splash image to reveal welcome screen
            if hasattr(self, '_splash_img') and hasattr(self, '_splash_layout'):
                if self._splash_img in self._splash_layout.children:
                    self._splash_layout.remove_widget(self._splash_img)
        except Exception as e:
            import traceback
            print(f"[ERROR] Failed to transition to welcome screen: {e}")
            print(traceback.format_exc())

    def select_difficulty(self, difficulty):
        # Play button click sound
        self._play_button_click_sound()
        
        self.selected_difficulty = difficulty
        # Update button colors and depressed effect to reflect selection
        for btn in getattr(self, 'difficulty_buttons', []):
            btn.is_selected = (btn.text == difficulty)
            if btn.is_selected:
                # Silver color for selected button, matching digit buttons
                btn.background_color = (0.75, 0.75, 0.75, 1)
                btn.color = (1, 1, 1, 1)  # Pure white text when selected
            else:
                btn.background_color = (0.15, 0.4, 0.15, 1)
                btn.color = (1, 1, 1, 0.85)  # Slightly off-white for unselected
            btn.canvas.after.clear()
            from kivy.graphics import Color, Line, Rectangle
            with btn.canvas.after:
                Color(0.5, 0.5, 0.5, 1)
                btn._border = Line(rectangle=(btn.x, btn.y, btn.width, btn.height), width=1)
                Color(0.9, 0.9, 0.9, 1)
                btn._highlight_top = Line(points=[btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height], width=2)
                btn._highlight_left = Line(points=[btn.x, btn.y, btn.x, btn.y + btn.height], width=2)
                Color(0.4, 0.4, 0.4, 1)
                btn._shadow_bottom = Line(points=[btn.x, btn.y, btn.x + btn.width, btn.y], width=2)
                btn._shadow_right = Line(points=[btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height], width=2)
                if btn.is_selected:
                    Color(0, 0, 0, 0.18)
                    btn._depressed_overlay = Rectangle(pos=(btn.x+2, btn.y+2), size=(btn.width-4, btn.height-4))
                else:
                    btn._depressed_overlay = None
            def update_btn_border(instance, *args):
                btn._border.rectangle = (btn.x, btn.y, btn.width, btn.height)
                btn._highlight_top.points = [btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height]
                btn._highlight_left.points = [btn.x, btn.y, btn.x, btn.y + btn.height]
                btn._shadow_bottom.points = [btn.x, btn.y, btn.x + btn.width, btn.y]
                btn._shadow_right.points = [btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height]
                # Update depressed overlay position if it exists
                if hasattr(btn, '_depressed_overlay') and btn._depressed_overlay:
                    btn._depressed_overlay.pos = (btn.x+2, btn.y+2)
                    btn._depressed_overlay.size = (btn.width-4, btn.height-4)
            btn.bind(pos=update_btn_border, size=update_btn_border)

    def start_game(self, difficulty, resume=False):
        if not difficulty:
            self.show_select_difficulty_popup()
            return
        self.last_difficulty = difficulty
        # If resuming, use last saved board; else, start new game
        if resume and self.last_game_state and self.last_game_state.get('difficulty') == difficulty:
            print(f"[RESUME] Resuming game with difficulty {difficulty}")
            puzzle = self.last_game_state.get('puzzle')
            solution = self.last_game_state.get('solution')
            board = self.last_game_state.get('board')
            self.last_game_in_progress = True
            # Don't save here during resume - we want to preserve the detailed state
        else:
            print(f"[NEW GAME] Starting new game with difficulty {difficulty}")
            # New game: CLEAR old game state completely to force new puzzle generation
            self.last_game_state = None
            self.last_game_in_progress = True
            # Clear any existing game object to force fresh puzzle generation
            if hasattr(self, 'game'):
                delattr(self, 'game')
            print(f"[NEW GAME] Cleared old game state and game object")
            
            # Track puzzle started stat
            if hasattr(self, 'game_stats'):
                self.game_stats['puzzles_started'] += 1
                # Track hints/mistakes for this game session
                self._current_game_hints_used = 0
                self._current_game_mistakes = 0
                self._save_stats_and_achievements()
                print(f"[STATS] Puzzle started - total: {self.game_stats['puzzles_started']}")
        
        # Stop ALL sounds when starting game (including any lingering game over sound)
        self._stop_all_sounds()
        
        # Play game start sound for new games (after stopping other sounds)
        if not resume:
            print("[DEBUG] Scheduling game start sound...")
            # Use Clock.schedule_once to ensure the game start sound plays after other sounds are stopped
            from kivy.clock import Clock
            Clock.schedule_once(lambda dt: self._play_game_start_sound(), 0.1)
        else:
            print("[DEBUG] Resume mode - no game start sound")
        
        # Reset game state flags
        if hasattr(self, '_fail_screen_active'):
            self._fail_screen_active = False
        # Reset solution_revealed flag so reward screen works for new games
        self.solution_revealed = False
        self._reward_screen_active = False
        
        # CRITICAL: Clear the how_to_play_btn reference to prevent ghost touches
        # on puzzle screen. The global touch handler checks this reference.
        self.how_to_play_btn = None
        
        self.root.clear_widgets()
        puzzle_layout = self.build_puzzle_screen(difficulty, resume=resume)
        self.root.add_widget(puzzle_layout)

    def show_select_difficulty_popup(self):
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.uix.popup import Popup
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle, Line
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.core.window import Window
        
        # Calculate responsive sizing and check platform
        from kivy.utils import platform as kivy_platform
        is_mobile = kivy_platform in ('android', 'ios')
        win_w, win_h = Window.width, Window.height
        if is_mobile:
            scale_factor = 0.7
            popup_w = min(win_w * 0.95, dp(320))
            popup_h = min(win_h * 0.28, dp(120))  # Increased from 0.22 and dp(90) to give more vertical space
            label_font = dp(15)
            ok_font = dp(13)
            ok_w = dp(70)
            ok_h = dp(28)
            pad = dp(12)  # Increased from dp(10)
            spacing = dp(12)  # Increased from dp(8)
        else:
            scale_factor = min(win_w / 600.0, win_h / 850.0)
            scale_factor = max(0.5, min(1.5, scale_factor))
            popup_w = min(win_w * 0.8, dp(400) * scale_factor)
            popup_h = min(win_h * 0.4, dp(180) * scale_factor)
            label_font = dp(20) * scale_factor
            ok_font = dp(18) * scale_factor
            ok_w = dp(100) * scale_factor
            ok_h = dp(40) * scale_factor
            pad = dp(24) * scale_factor
            spacing = dp(16) * scale_factor
        # Maroon background, white font, custom message, silver OK button centered
        content = BoxLayout(orientation='vertical', padding=pad, spacing=spacing)
        with content.canvas.before:
            Color(0.5, 0, 0, 1)  # Maroon
            self._popup_bg_rect = Rectangle(size=content.size, pos=content.pos)
        content.bind(size=lambda inst, val: setattr(self._popup_bg_rect, 'size', val))
        content.bind(pos=lambda inst, val: setattr(self._popup_bg_rect, 'pos', val))
        label = Label(text="Please choose a difficulty first.", font_size=label_font, color=(1, 1, 1, 1), halign='center', valign='middle', text_size=(popup_w * 0.98, None), shorten=True, shorten_from='right', max_lines=1)
        content.add_widget(label)
        ok_btn = Button(text="OK", font_size=ok_font, size_hint=(None, None), size=(ok_w, ok_h), background_color=(0.75, 0.75, 0.75, 1), color=(0, 0, 0, 1), background_normal='', background_down='')
        # 3D/embossed effect for OK button
        with ok_btn.canvas.after:
            Color(0.5, 0.5, 0.5, 1)
            ok_btn._border = Line(rectangle=(ok_btn.x, ok_btn.y, ok_btn.width, ok_btn.height), width=1)
            Color(0.9, 0.9, 0.9, 1)
            ok_btn._highlight_top = Line(points=[ok_btn.x, ok_btn.y + ok_btn.height, ok_btn.x + ok_w, ok_btn.y + ok_h], width=2)
            ok_btn._highlight_left = Line(points=[ok_btn.x, ok_btn.y, ok_btn.x, ok_btn.y + ok_h], width=2)
            Color(0.4, 0.4, 0.4, 1)
            ok_btn._shadow_bottom = Line(points=[ok_btn.x, ok_btn.y, ok_btn.x + ok_w, ok_btn.y], width=2)
            ok_btn._shadow_right = Line(points=[ok_btn.x + ok_w, ok_btn.y, ok_btn.x + ok_w, ok_btn.y + ok_h], width=2)
        def update_ok_btn_border(instance, *args):
            ok_btn._border.rectangle = (ok_btn.x, ok_btn.y, ok_btn.width, ok_btn.height)
            ok_btn._highlight_top.points = [ok_btn.x, ok_btn.y + ok_btn.height, ok_btn.x + ok_btn.width, ok_btn.y + ok_btn.height]
            ok_btn._highlight_left.points = [ok_btn.x, ok_btn.y, ok_btn.x, ok_btn.y + ok_btn.height]
            ok_btn._shadow_bottom.points = [ok_btn.x, ok_btn.y, ok_btn.x + ok_btn.width, ok_btn.y]
            ok_btn._shadow_right.points = [ok_btn.x + ok_btn.width, ok_btn.y, ok_btn.x + ok_btn.width, ok_btn.y + ok_btn.height]
        ok_btn.bind(pos=update_ok_btn_border, size=update_ok_btn_border)
        ok_btn_layout = AnchorLayout(anchor_x='center', anchor_y='center')
        ok_btn_layout.add_widget(ok_btn)
        content.add_widget(ok_btn_layout)
        popup = Popup(title='', content=content, size_hint=(None, None), size=(popup_w, popup_h), auto_dismiss=False, separator_height=0, background='')
        def ok_clicked(instance):
            self._play_button_click_sound()
            popup.dismiss()
        ok_btn.bind(on_release=ok_clicked)
        popup.open()

    def show_settings_popup(self):
        """Show the Settings popup with toggle switches for various game options"""
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.uix.popup import Popup
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle, Line
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.uix.widget import Widget
        
        # Create temporary settings that can be changed without affecting the app until Apply is pressed
        temp_settings = {
            'music': self.settings_music,
            'show_clock': self.settings_show_clock,
            'sounds': self.settings_sounds,
            'check_mistakes': self.settings_check_mistakes,
            'dark_mode': self.settings_dark_mode,
            'show_counts': self.settings_show_counts
        }
        
        # Main content container with bright orange background
        content = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(12))
        with content.canvas.before:
            Color(1.0, 0.5, 0.0, 1)  # Bright orange background
            self._settings_bg_rect = Rectangle(size=content.size, pos=content.pos)
        content.bind(size=lambda inst, val: setattr(self._settings_bg_rect, 'size', val))
        content.bind(pos=lambda inst, val: setattr(self._settings_bg_rect, 'pos', val))
        
        # Title
        title_label = Label(
            text="Settings",
            font_size=dp(28),
            color=(1, 1, 1, 1),
            size_hint=(1, None),
            height=dp(40),
            halign='center',
            valign='middle'
        )
        title_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
        content.add_widget(title_label)
        
        # Add some spacing (reduced to make room for more settings)
        content.add_widget(Widget(size_hint_y=None, height=dp(4)))
        
        # Helper function to create toggle buttons
        def create_toggle_button(is_on):
            btn = Button(
                text="ON" if is_on else "OFF",
                font_size=dp(14),
                size_hint=(None, None),
                size=(dp(60), dp(30)),
                background_color=(0.2, 0.7, 0.2, 1) if is_on else (0.7, 0.2, 0.2, 1),
                color=(1, 1, 1, 1),
                background_normal='',
                background_down=''
            )
            
            # Add 3D effect
            with btn.canvas.after:
                Color(0.5, 0.5, 0.5, 1)
                btn._border = Line(rectangle=(btn.x, btn.y, btn.width, btn.height), width=1)
                Color(0.9, 0.9, 0.9, 1)
                btn._highlight_top = Line(points=[btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height], width=2)
                btn._highlight_left = Line(points=[btn.x, btn.y, btn.x, btn.y + btn.height], width=2)
                Color(0.4, 0.4, 0.4, 1)
                btn._shadow_bottom = Line(points=[btn.x, btn.y, btn.x + btn.width, btn.y], width=2)
                btn._shadow_right = Line(points=[btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height], width=2)
            
            def update_toggle_btn_border(instance, *args):
                btn._border.rectangle = (btn.x, btn.y, btn.width, btn.height)
                btn._highlight_top.points = [btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height]
                btn._highlight_left.points = [btn.x, btn.y, btn.x, btn.y + btn.height]
                btn._shadow_bottom.points = [btn.x, btn.y, btn.x + btn.width, btn.y]
                btn._shadow_right.points = [btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height]
            btn.bind(pos=update_toggle_btn_border, size=update_toggle_btn_border)
            
            return btn
        
        # Helper function to create a settings row
        def create_settings_row(label_text, setting_key):
            row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(40), spacing=dp(10))
            
            # Label
            label = Label(
                text=label_text,
                font_size=dp(16),
                color=(1, 1, 1, 1),
                size_hint=(0.7, 1),
                halign='left',
                valign='middle'
            )
            label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            row.add_widget(label)
            
            # Toggle button
            current_value = temp_settings[setting_key]
            toggle_btn = create_toggle_button(current_value)
            
            def toggle_setting(instance):
                if self.settings_sounds:  # Only play sound if sounds are enabled
                    self._play_button_click_sound()
                current = temp_settings[setting_key]
                new_value = not current
                temp_settings[setting_key] = new_value
                
                # Update button appearance
                instance.text = "ON" if new_value else "OFF"
                instance.background_color = (0.2, 0.7, 0.2, 1) if new_value else (0.7, 0.2, 0.2, 1)
                
                print(f"[SETTINGS] {setting_key} temporarily set to: {new_value}")
            
            toggle_btn.bind(on_release=toggle_setting)
            
            toggle_container = BoxLayout(orientation='horizontal', size_hint=(0.3, 1))
            toggle_container.add_widget(Widget())  # Spacer to push button right
            toggle_container.add_widget(toggle_btn)
            row.add_widget(toggle_container)
            
            return row
        
        # Create all setting rows
        content.add_widget(create_settings_row("Music", "music"))
        content.add_widget(create_settings_row("Show Clock", "show_clock"))
        content.add_widget(create_settings_row("Sounds", "sounds"))
        content.add_widget(create_settings_row("Check for Mistakes", "check_mistakes"))
        
        # Dark Mode option is now available for all users
        content.add_widget(create_settings_row("Dark Mode", "dark_mode"))
        
        # Show hints and auto-solves left on buttons
        content.add_widget(create_settings_row("Show Hints/Auto-Solves Left", "show_counts"))
        
        # Add spacing before buttons
        content.add_widget(Widget(size_hint_y=None, height=dp(15)))
        
        # Apply button
        apply_btn = Button(
            text="Apply",
            font_size=dp(16),
            size_hint=(None, None),
            size=(dp(150), dp(35)),
            background_color=(0.2, 0.6, 0.2, 1),  # Green for apply action
            color=(1, 1, 1, 1),
            background_normal='',
            background_down=''
        )
        
        # Add 3D effect to apply button
        with apply_btn.canvas.after:
            Color(0.5, 0.5, 0.5, 1)
            apply_btn._border = Line(rectangle=(apply_btn.x, apply_btn.y, apply_btn.width, apply_btn.height), width=1)
            Color(0.9, 0.9, 0.9, 1)
            apply_btn._highlight_top = Line(points=[apply_btn.x, apply_btn.y + apply_btn.height, apply_btn.x + apply_btn.width, apply_btn.y + apply_btn.height], width=2)
            apply_btn._highlight_left = Line(points=[apply_btn.x, apply_btn.y, apply_btn.x, apply_btn.y + apply_btn.height], width=2)
            Color(0.4, 0.4, 0.4, 1)
            apply_btn._shadow_bottom = Line(points=[apply_btn.x, apply_btn.y, apply_btn.x + apply_btn.width, apply_btn.y], width=2)
            apply_btn._shadow_right = Line(points=[apply_btn.x + apply_btn.width, apply_btn.y, apply_btn.x + apply_btn.width, apply_btn.y + apply_btn.height], width=2)
        
        def update_apply_btn_border(instance, *args):
            apply_btn._border.rectangle = (apply_btn.x, apply_btn.y, apply_btn.width, apply_btn.height)
            apply_btn._highlight_top.points = [apply_btn.x, apply_btn.y + apply_btn.height, apply_btn.x + apply_btn.width, apply_btn.y + apply_btn.height]
            apply_btn._highlight_left.points = [apply_btn.x, apply_btn.y, apply_btn.x, apply_btn.y + apply_btn.height]
            apply_btn._shadow_bottom.points = [apply_btn.x, apply_btn.y, apply_btn.x + apply_btn.width, apply_btn.y]
            apply_btn._shadow_right.points = [apply_btn.x + apply_btn.width, apply_btn.y, apply_btn.x + apply_btn.width, apply_btn.y + apply_btn.height]
        apply_btn.bind(pos=update_apply_btn_border, size=update_apply_btn_border)
        
        def apply_settings(instance):
            if self.settings_sounds:  # Only play sound if sounds are enabled
                self._play_button_click_sound()
            
            # Apply temporary settings to actual settings
            old_music = self.settings_music
            old_show_clock = self.settings_show_clock
            old_check_mistakes = self.settings_check_mistakes
            old_dark_mode = self.settings_dark_mode
            old_show_counts = self.settings_show_counts
            
            self.settings_music = temp_settings['music']
            self.settings_show_clock = temp_settings['show_clock']
            self.settings_sounds = temp_settings['sounds']
            self.settings_check_mistakes = temp_settings['check_mistakes']
            self.settings_dark_mode = temp_settings['dark_mode']
            self.settings_show_counts = temp_settings['show_counts']
            
            print("[SETTINGS] Applied all settings changes")
            
            # Handle music changes
            if old_music != self.settings_music:
                if not self.settings_music:
                    # Stop all music
                    if hasattr(self, '_music') and self._music:
                        self._music.stop()
                    if hasattr(self, '_welcome_music') and self._welcome_music:
                        self._welcome_music.stop()
                    print("[SETTINGS] Music disabled - stopped all music")
                else:
                    # Restart appropriate music based on current screen
                    if hasattr(self, 'last_difficulty') and hasattr(self, 'game'):
                        # In game - restart game music
                        self._restart_game_music()
                    else:
                        # In welcome screen - restart welcome music
                        self._play_welcome_music()
                    print("[SETTINGS] Music enabled - restarted appropriate music")
            
            # Handle show clock changes
            if old_show_clock != self.settings_show_clock:
                if hasattr(self, 'clock_label'):
                    self.clock_label.opacity = 1.0 if self.settings_show_clock else 0.0
                    if self.settings_show_clock:
                        # Start clock updates when enabled
                        self._start_clock_updates()
                    else:
                        # Stop clock updates when disabled
                        self._stop_clock_updates()
                    print(f"[SETTINGS] Clock visibility toggled - visible: {self.settings_show_clock}")
            
            # Handle check for mistakes changes
            if old_check_mistakes != self.settings_check_mistakes:
                if hasattr(self, 'mistake_label'):
                    self.mistake_label.opacity = 1.0 if self.settings_check_mistakes else 0.0
                    print(f"[SETTINGS] Mistake counter visibility toggled - visible: {self.settings_check_mistakes}")
            
            # Handle dark mode changes
            if old_dark_mode != self.settings_dark_mode:
                self.apply_dark_mode_theme()
                # Refresh note displays after dark mode theme is applied
                from kivy.clock import Clock
                def refresh_notes_after_dark_mode(*args):
                    if hasattr(self, 'sudoku_board') and self.sudoku_board:
                        for row in range(9):
                            for col in range(9):
                                cell = self.sudoku_board.get_cell(row, col)
                                if cell and cell.notes:
                                    cell.update_notes_display()
                        print("[NOTES] Refreshed all note displays after dark mode toggle")
                Clock.schedule_once(refresh_notes_after_dark_mode, 0.05)
                print(f"[SETTINGS] Dark mode toggled - enabled: {self.settings_dark_mode}")
            
            # Handle show counts changes
            if old_show_counts != self.settings_show_counts:
                # Update hint and auto-solve buttons to reflect the new setting
                self._update_hint_button_text()
                self._update_auto_solve_button_text()
                print(f"[SETTINGS] Show counts toggled - enabled: {self.settings_show_counts}")
            
            popup.dismiss()
        
        apply_btn.bind(on_release=apply_settings)
        
        apply_btn_layout = AnchorLayout(anchor_x='center', anchor_y='center')
        apply_btn_layout.add_widget(apply_btn)
        content.add_widget(apply_btn_layout)
        
        # Add spacing between apply and reset
        content.add_widget(Widget(size_hint_y=None, height=dp(8)))
        
        # Reset to Defaults button
        reset_btn = Button(
            text="Reset to Defaults",
            font_size=dp(16),
            size_hint=(None, None),
            size=(dp(180), dp(35)),
            background_color=(0.1, 0.1, 0.4, 1),  # Dark blue color
            color=(1, 1, 1, 1),
            background_normal='',
            background_down=''
        )
        
        # Add 3D effect to reset button
        with reset_btn.canvas.after:
            Color(0.5, 0.5, 0.5, 1)
            reset_btn._border = Line(rectangle=(reset_btn.x, reset_btn.y, reset_btn.width, reset_btn.height), width=1)
            Color(0.9, 0.9, 0.9, 1)
            reset_btn._highlight_top = Line(points=[reset_btn.x, reset_btn.y + reset_btn.height, reset_btn.x + reset_btn.width, reset_btn.y + reset_btn.height], width=2)
            reset_btn._highlight_left = Line(points=[reset_btn.x, reset_btn.y, reset_btn.x, reset_btn.y + reset_btn.height], width=2)
            Color(0.4, 0.4, 0.4, 1)
            reset_btn._shadow_bottom = Line(points=[reset_btn.x, reset_btn.y, reset_btn.x + reset_btn.width, reset_btn.y], width=2)
            reset_btn._shadow_right = Line(points=[reset_btn.x + reset_btn.width, reset_btn.y, reset_btn.x + reset_btn.width, reset_btn.y + reset_btn.height], width=2)
        
        def update_reset_btn_border(instance, *args):
            reset_btn._border.rectangle = (reset_btn.x, reset_btn.y, reset_btn.width, reset_btn.height)
            reset_btn._highlight_top.points = [reset_btn.x, reset_btn.y + reset_btn.height, reset_btn.x + reset_btn.width, reset_btn.y + reset_btn.height]
            reset_btn._highlight_left.points = [reset_btn.x, reset_btn.y, reset_btn.x, reset_btn.y + reset_btn.height]
            reset_btn._shadow_bottom.points = [reset_btn.x, reset_btn.y, reset_btn.x + reset_btn.width, reset_btn.y]
            reset_btn._shadow_right.points = [reset_btn.x + reset_btn.width, reset_btn.y, reset_btn.x + reset_btn.width, reset_btn.y + reset_btn.height]
        reset_btn.bind(pos=update_reset_btn_border, size=update_reset_btn_border)
        
        def reset_to_defaults(instance):
            if self.settings_sounds:  # Only play sound if sounds are enabled
                self._play_button_click_sound()
            # Reset temporary settings to default values
            temp_settings['music'] = True
            temp_settings['show_clock'] = False
            temp_settings['sounds'] = True
            temp_settings['check_mistakes'] = True
            temp_settings['dark_mode'] = False
            temp_settings['show_counts'] = False
            print("[SETTINGS] Reset temporary settings to defaults")
            
            # Update all toggle button states to reflect the reset values
            # Find all toggle buttons in the content and update them
            def update_toggle_buttons(widget):
                for child in widget.children:
                    if hasattr(child, 'children'):
                        update_toggle_buttons(child)
                    if isinstance(child, Button) and hasattr(child, 'text') and child.text in ['ON', 'OFF']:
                        # This is a toggle button, find which setting it belongs to
                        parent = child.parent
                        if parent and hasattr(parent, 'parent'):
                            row = parent.parent
                            if row and hasattr(row, 'children'):
                                for row_child in row.children:
                                    if isinstance(row_child, Label):
                                        label_text = row_child.text
                                        if label_text == "Music":
                                            new_state = temp_settings['music']
                                        elif label_text == "Show Clock":
                                            new_state = temp_settings['show_clock']
                                        elif label_text == "Sounds":
                                            new_state = temp_settings['sounds']
                                        elif label_text == "Check for Mistakes":
                                            new_state = temp_settings['check_mistakes']
                                        elif label_text == "Dark Mode":
                                            new_state = temp_settings['dark_mode']
                                        elif label_text == "Show Hints/Auto-Solves Left":
                                            new_state = temp_settings['show_counts']
                                        else:
                                            continue
                                        
                                        child.text = "ON" if new_state else "OFF"
                                        child.background_color = (0.2, 0.7, 0.2, 1) if new_state else (0.7, 0.2, 0.2, 1)
                                        break
            
            update_toggle_buttons(content)
        
        reset_btn.bind(on_release=reset_to_defaults)
        
        reset_btn_layout = AnchorLayout(anchor_x='center', anchor_y='center')
        reset_btn_layout.add_widget(reset_btn)
        content.add_widget(reset_btn_layout)
        
        # Add spacing before close button
        content.add_widget(Widget(size_hint_y=None, height=dp(10)))
        
        # Close button
        close_btn = Button(
            text="Close",
            font_size=dp(18),
            size_hint=(None, None),
            size=(dp(120), dp(40)),
            background_color=(0.75, 0.75, 0.75, 1),
            color=(0, 0, 0, 1),
            background_normal='',
            background_down=''
        )
        
        # Add 3D effect to close button
        with close_btn.canvas.after:
            Color(0.5, 0.5, 0.5, 1)
            close_btn._border = Line(rectangle=(close_btn.x, close_btn.y, close_btn.width, close_btn.height), width=1)
            Color(0.9, 0.9, 0.9, 1)
            close_btn._highlight_top = Line(points=[close_btn.x, close_btn.y + close_btn.height, close_btn.x + close_btn.width, close_btn.y + close_btn.height], width=2)
            close_btn._highlight_left = Line(points=[close_btn.x, close_btn.y, close_btn.x, close_btn.y + close_btn.height], width=2)
            Color(0.4, 0.4, 0.4, 1)
            close_btn._shadow_bottom = Line(points=[close_btn.x, close_btn.y, close_btn.x + close_btn.width, close_btn.y], width=2)
            close_btn._shadow_right = Line(points=[close_btn.x + close_btn.width, close_btn.y, close_btn.x + close_btn.width, close_btn.y + close_btn.height], width=2)
        
        def update_close_btn_border(instance, *args):
            close_btn._border.rectangle = (close_btn.x, close_btn.y, close_btn.width, close_btn.height)
            close_btn._highlight_top.points = [close_btn.x, close_btn.y + close_btn.height, close_btn.x + close_btn.width, close_btn.y + close_btn.height]
            close_btn._highlight_left.points = [close_btn.x, close_btn.y, close_btn.x, close_btn.y + close_btn.height]
            close_btn._shadow_bottom.points = [close_btn.x, close_btn.y, close_btn.x + close_btn.width, close_btn.y]
            close_btn._shadow_right.points = [close_btn.x + close_btn.width, close_btn.y, close_btn.x + close_btn.width, close_btn.y + close_btn.height]
        close_btn.bind(pos=update_close_btn_border, size=update_close_btn_border)
        
        close_btn_layout = AnchorLayout(anchor_x='center', anchor_y='center')
        close_btn_layout.add_widget(close_btn)
        content.add_widget(close_btn_layout)
        
        # Create popup
        popup = Popup(
            title='',
            content=content,
            size_hint=(None, None),
            size=(dp(400), dp(610)),  # Increased height for Show Hints/Auto-Solves setting
            auto_dismiss=False,
            separator_height=0,
            background=''
        )
        
        def close_settings(instance):
            if self.settings_sounds:  # Only play sound if sounds are enabled
                self._play_button_click_sound()
            popup.dismiss()
        close_btn.bind(on_release=close_settings)
        
        popup.open()

    def show_shop_screen(self):
        """Show the Shop popup for non-premium users.
        Premium users are routed to stats/achievements by the touch handler and never reach here."""
        try:
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.label import Label
            from kivy.uix.button import Button
            from kivy.uix.popup import Popup
            from kivy.uix.anchorlayout import AnchorLayout
            from kivy.uix.widget import Widget
            from kivy.uix.floatlayout import FloatLayout
            from kivy.metrics import dp
            from kivy.graphics import Color, Rectangle, Line
            from kivy.core.window import Window

            def add_3d_silver_button_effect(btn):
                with btn.canvas.after:
                    Color(0.5, 0.5, 0.5, 1)
                    border = Line(rectangle=(btn.x, btn.y, btn.width, btn.height), width=1)
                    Color(0.95, 0.95, 0.95, 1)
                    highlight_top = Line(points=[btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height], width=2)
                    highlight_left = Line(points=[btn.x, btn.y, btn.x, btn.y + btn.height], width=2)
                    Color(0.45, 0.45, 0.45, 1)
                    shadow_bottom = Line(points=[btn.x, btn.y, btn.x + btn.width, btn.y], width=2)
                    shadow_right = Line(points=[btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height], width=2)
                def update(instance, *args):
                    border.rectangle = (btn.x, btn.y, btn.width, btn.height)
                    highlight_top.points = [btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height]
                    highlight_left.points = [btn.x, btn.y, btn.x, btn.y + btn.height]
                    shadow_bottom.points = [btn.x, btn.y, btn.x + btn.width, btn.y]
                    shadow_right.points = [btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height]
                btn.bind(pos=update, size=update)

            def add_3d_gold_button_effect(btn):
                with btn.canvas.after:
                    Color(0.6, 0.45, 0.08, 1)
                    border = Line(rectangle=(btn.x, btn.y, btn.width, btn.height), width=1)
                    Color(1, 0.9, 0.4, 1)
                    highlight_top = Line(points=[btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height], width=2)
                    highlight_left = Line(points=[btn.x, btn.y, btn.x, btn.y + btn.height], width=2)
                    Color(0.5, 0.35, 0.05, 1)
                    shadow_bottom = Line(points=[btn.x, btn.y, btn.x + btn.width, btn.y], width=2)
                    shadow_right = Line(points=[btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height], width=2)
                def update(instance, *args):
                    border.rectangle = (btn.x, btn.y, btn.width, btn.height)
                    highlight_top.points = [btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height]
                    highlight_left.points = [btn.x, btn.y, btn.x, btn.y + btn.height]
                    shadow_bottom.points = [btn.x, btn.y, btn.x + btn.width, btn.y]
                    shadow_right.points = [btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height]
                btn.bind(pos=update, size=update)

            win_w, win_h = Window.width, Window.height
            scale_factor = min(win_w / 600.0, win_h / 850.0)
            scale_factor = max(0.5, min(1.5, scale_factor))
            popup_w = min(win_w * 0.92, dp(350) * scale_factor)
            popup_h = min(win_h * 0.92, dp(680) * scale_factor)

            # Outer white border shell
            outer = FloatLayout()
            with outer.canvas.before:
                Color(1, 1, 1, 1)
                outer_rect = Rectangle(size=outer.size, pos=outer.pos)
            outer.bind(size=lambda inst, val: setattr(outer_rect, 'size', val))
            outer.bind(pos=lambda inst, val: setattr(outer_rect, 'pos', val))

            # Tan body
            content = BoxLayout(
                orientation='vertical',
                padding=(dp(14) * scale_factor, dp(14) * scale_factor, dp(14) * scale_factor, dp(14) * scale_factor),
                spacing=dp(8) * scale_factor,
                size_hint=(0.97, 0.97),
                pos_hint={'center_x': 0.5, 'center_y': 0.5}
            )
            with content.canvas.before:
                Color(0.82, 0.71, 0.55, 1)
                bg_rect = Rectangle(size=content.size, pos=content.pos)
            content.bind(size=lambda inst, val: setattr(bg_rect, 'size', val))
            content.bind(pos=lambda inst, val: setattr(bg_rect, 'pos', val))
            outer.add_widget(content)

            header_block = BoxLayout(
                orientation='vertical',
                size_hint=(1, None),
                height=dp(62) * scale_factor,
                spacing=dp(2) * scale_factor
            )

            title_label = Label(
                text="Unlock Everything",
                font_size=dp(18) * scale_factor,
                color=(0.35, 0.2, 0.1, 1),
                size_hint=(1, None),
                height=dp(28) * scale_factor,
                bold=True,
                halign='center',
                valign='top'
            )
            title_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            header_block.add_widget(title_label)

            title_divider = Widget(size_hint=(0.7, None), height=dp(2) * scale_factor)
            with title_divider.canvas:
                Color(0.55, 0.4, 0.25, 1)
                title_divider_rect = Rectangle(size=title_divider.size, pos=title_divider.pos)
            title_divider.bind(size=lambda inst, val: setattr(title_divider_rect, 'size', val))
            title_divider.bind(pos=lambda inst, val: setattr(title_divider_rect, 'pos', val))
            divider_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(4) * scale_factor)
            divider_layout.add_widget(title_divider)
            header_block.add_widget(divider_layout)

            subtitle_label = Label(
                text="Remove all limits. Play without interruption.",
                font_size=dp(12) * scale_factor,
                color=(0.3, 0.25, 0.2, 1),
                size_hint=(1, None),
                height=dp(24) * scale_factor,
                halign='center',
                valign='middle'
            )
            subtitle_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], val[1])))
            header_block.add_widget(subtitle_label)

            content.add_widget(header_block)

            # Premium "Best Value" badge
            best_value_label = Label(
                text="Best Value",
                font_size=dp(11) * scale_factor,
                color=(0.7, 0.5, 0.05, 1),
                size_hint=(1, None),
                height=dp(16) * scale_factor,
                halign='center',
                valign='middle',
                bold=True
            )
            best_value_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            content.add_widget(best_value_label)

            # Premium row — gold Buy button to distinguish it
            premium_row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(44) * scale_factor, spacing=dp(8) * scale_factor)
            premium_name_label = Label(
                text="Premium Unlock",
                font_size=dp(13) * scale_factor,
                color=(0.15, 0.1, 0.05, 1),
                size_hint=(0.5, 1),
                halign='left',
                valign='middle'
            )
            premium_name_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], val[1])))
            premium_price_label = Label(
                text="$4.99",
                font_size=dp(13) * scale_factor,
                color=(0.0, 0.4, 0.0, 1),
                size_hint=(0.22, 1),
                halign='center',
                valign='middle',
                bold=True
            )
            buy_premium_btn = Button(
                text="Buy",
                font_size=dp(13) * scale_factor,
                size_hint=(0.28, 1),
                background_color=(0.85, 0.65, 0.13, 1),
                color=(0, 0, 0, 1),
                background_normal='',
                background_down=''
            )
            add_3d_gold_button_effect(buy_premium_btn)
            premium_row.add_widget(premium_name_label)
            premium_row.add_widget(premium_price_label)
            premium_row.add_widget(buy_premium_btn)
            content.add_widget(premium_row)

            # Premium benefits line
            benefits_label = Label(
                text="Unlimited hints and auto-solves\nIncludes stats and achievements",
                font_size=dp(10) * scale_factor,
                color=(0.4, 0.3, 0.15, 1),
                size_hint=(1, None),
                height=dp(30) * scale_factor,
                halign='center',
                valign='middle'
            )
            benefits_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], val[1])))
            content.add_widget(benefits_label)

            content.add_widget(Widget(size_hint_y=None, height=dp(2) * scale_factor))

            # Mid-section divider with real lines (avoids font glyph issues)
            mid_divider_row = BoxLayout(
                orientation='horizontal',
                size_hint=(1, None),
                height=dp(18) * scale_factor,
                spacing=dp(6) * scale_factor
            )

            left_line = Widget(size_hint=(1, None), height=dp(1) * scale_factor)
            with left_line.canvas:
                Color(0.6, 0.5, 0.35, 0.8)
                left_line_rect = Rectangle(size=left_line.size, pos=left_line.pos)
            left_line.bind(size=lambda inst, val: setattr(left_line_rect, 'size', val))
            left_line.bind(pos=lambda inst, val: setattr(left_line_rect, 'pos', val))

            mid_divider_label = Label(
                text="or top up hints only",
                font_size=dp(11) * scale_factor,
                color=(0.5, 0.38, 0.22, 1),
                size_hint=(None, 1),
                width=dp(130) * scale_factor,
                halign='center',
                valign='middle'
            )
            mid_divider_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], val[1])))

            right_line = Widget(size_hint=(1, None), height=dp(1) * scale_factor)
            with right_line.canvas:
                Color(0.6, 0.5, 0.35, 0.8)
                right_line_rect = Rectangle(size=right_line.size, pos=right_line.pos)
            right_line.bind(size=lambda inst, val: setattr(right_line_rect, 'size', val))
            right_line.bind(pos=lambda inst, val: setattr(right_line_rect, 'pos', val))

            line_left_wrap = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, 1))
            line_left_wrap.add_widget(left_line)
            line_right_wrap = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, 1))
            line_right_wrap.add_widget(right_line)

            mid_divider_row.add_widget(line_left_wrap)
            mid_divider_row.add_widget(mid_divider_label)
            mid_divider_row.add_widget(line_right_wrap)
            content.add_widget(mid_divider_row)

            # Hint pack rows
            hint_packs = [
                ("10 Hints", "$0.99"),
                ("50 Hints", "$1.99"),
                ("100 Hints", "$2.99")
            ]
            hint_purchase_buttons = []

            for pack_name, price in hint_packs:
                row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(38) * scale_factor, spacing=dp(8) * scale_factor)
                name_label = Label(
                    text=pack_name,
                    font_size=dp(13) * scale_factor,
                    color=(0.15, 0.1, 0.05, 1),
                    size_hint=(0.5, 1),
                    halign='left',
                    valign='middle'
                )
                name_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], val[1])))
                price_label = Label(
                    text=price,
                    font_size=dp(13) * scale_factor,
                    color=(0.0, 0.4, 0.0, 1),
                    size_hint=(0.22, 1),
                    halign='center',
                    valign='middle',
                    bold=True
                )
                buy_btn = Button(
                    text="Buy",
                    font_size=dp(13) * scale_factor,
                    size_hint=(0.28, 1),
                    background_color=(0.75, 0.75, 0.75, 1),
                    color=(0, 0, 0, 1),
                    background_normal='',
                    background_down=''
                )
                add_3d_silver_button_effect(buy_btn)
                hint_purchase_buttons.append((buy_btn, pack_name, price))
                row.add_widget(name_label)
                row.add_widget(price_label)
                row.add_widget(buy_btn)
                content.add_widget(row)

            # Bottom decorative divider
            bottom_divider = Widget(size_hint=(0.85, None), height=dp(1) * scale_factor)
            with bottom_divider.canvas:
                Color(0.6, 0.5, 0.35, 0.6)
                bottom_divider_rect = Rectangle(size=bottom_divider.size, pos=bottom_divider.pos)
            bottom_divider.bind(size=lambda inst, val: setattr(bottom_divider_rect, 'size', val))
            bottom_divider.bind(pos=lambda inst, val: setattr(bottom_divider_rect, 'pos', val))
            bottom_divider_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(10) * scale_factor)
            bottom_divider_layout.add_widget(bottom_divider)
            content.add_widget(bottom_divider_layout)

            # "Maybe Later" close button
            close_btn = Button(
                text="Maybe Later",
                font_size=dp(13) * scale_factor,
                size_hint=(None, None),
                size=(dp(110) * scale_factor, dp(34) * scale_factor),
                background_color=(0.75, 0.75, 0.75, 1),
                color=(0, 0, 0, 1),
                background_normal='',
                background_down=''
            )
            add_3d_silver_button_effect(close_btn)
            close_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(40) * scale_factor)
            close_layout.add_widget(close_btn)
            content.add_widget(close_layout)

            # Restore Purchases
            restore_btn = Button(
                text="Restore Purchases",
                font_size=dp(11) * scale_factor,
                size_hint=(None, None),
                size=(dp(120) * scale_factor, dp(28) * scale_factor),
                background_color=(0.2, 0.6, 0.2, 1),
                background_normal='',
                background_down='',
                color=(1, 1, 1, 1)
            )
            restore_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(32) * scale_factor)
            restore_layout.add_widget(restore_btn)
            content.add_widget(restore_layout)

            popup = Popup(
                title='',
                content=outer,
                size_hint=(None, None),
                size=(popup_w, popup_h),
                auto_dismiss=True,
                separator_height=0,
                background=''
            )

            close_btn.bind(on_release=popup.dismiss)

            def on_buy_premium(instance):
                try:
                    self._play_button_click_sound()
                    self.show_purchase_confirmation("Premium Unlock", "$4.99", self.purchase_premium, popup)
                except Exception as e:
                    import traceback
                    print(f"[ERROR] premium purchase failed: {e}\n{traceback.format_exc()}")
            buy_premium_btn.bind(on_release=on_buy_premium)

            for buy_btn, pack_name, price in hint_purchase_buttons:
                def make_hint_callback(pname, pr):
                    def callback(instance):
                        try:
                            self._play_button_click_sound()
                            self.show_purchase_confirmation(pname, pr, lambda: self.purchase_hints(pname), popup)
                        except Exception as e:
                            import traceback
                            print(f"[ERROR] hint purchase failed: {e}\n{traceback.format_exc()}")
                    return callback
                buy_btn.bind(on_release=make_hint_callback(pack_name, price))

            def _restore_click(instance):
                try:
                    self.restore_purchases(popup)
                except Exception as e:
                    import traceback
                    tb = traceback.format_exc()
                    print(f"[ERROR] restore_purchases failed: {e}\n{tb}")
                    try:
                        with open('/sdcard/sudoku_error.txt', 'w') as f:
                            f.write(tb)
                    except Exception:
                        pass
                    try:
                        err = Popup(title='Restore Error', content=Label(text='Unable to restore purchases at this time.'), size_hint=(None, None), size=(dp(320), dp(160)))
                        err.open()
                    except Exception:
                        pass
            restore_btn.bind(on_release=_restore_click)

            popup.open()

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"[ERROR] show_shop_screen failed: {e}\n{tb}")
            try:
                with open('/sdcard/sudoku_error.txt', 'w') as f:
                    f.write(tb)
            except Exception:
                pass
            try:
                from kivy.uix.popup import Popup
                from kivy.uix.label import Label
                from kivy.metrics import dp
                err_popup = Popup(title='Shop Unavailable', content=Label(text='Unable to open the Shop right now. Please try again.'), size_hint=(None, None), size=(dp(300), dp(160)))
                err_popup.open()
            except Exception:
                pass

    def show_purchase_confirmation(self, item_name, price, on_confirm_callback, parent_popup=None):
        """Immediately trigger purchase without confirmation dialog (Microsoft Store IAP dialog will appear)"""
        from kivy.clock import Clock
        
        # Dismiss parent shop popup first
        if parent_popup:
            parent_popup.dismiss()
        
        # Schedule purchase on next event loop cycle to ensure popup dismissal happens first
        Clock.schedule_once(lambda dt: on_confirm_callback(), 0.1)

    def purchase_premium(self):
        """Handle premium purchase via Google Play Billing"""
        self._play_button_click_sound()
        print("[BILLING] Premium purchase initiated")
        
        # Use BillingManager for real Google Play purchase
        if self.billing_manager:
            self.billing_manager.purchase("Premium Unlock")
        else:
            # Fallback for testing on non-Android platforms
            print("[BILLING] BillingManager not available - simulating purchase")
            self._on_billing_purchase_success("premium_unlock", "Premium Unlock")
    

    def restore_purchases(self, popup_to_close=None):
        """
        Restore previously purchased non-consumable products.
        
        This queries the store (Google Play on Android, Windows Store on Windows)
        for owned items and restores:
        - Premium unlock
        - Forever Unlimited Auto-Solve
        
        Consumable items (hint packs, auto-solve credits) cannot be restored.
        """
        self._play_button_click_sound()
        mgr_type = type(self.billing_manager).__name__
        print(f"\n[BILLING] >>> Restore purchases initiated <<<")
        print(f"[BILLING] Billing Manager type: {mgr_type}")
        print(f"[BILLING] Platform: {platform}")
        
        # Store the popup to close after restore completes
        self._restore_popup_to_close = popup_to_close
        
        # Use billing manager (Google Play on Android, Windows Store on Windows)
        if self.billing_manager:
            self.billing_manager.restore_purchases(callback=self._on_billing_restore_complete)
        else:
            # Fallback for testing on non-Android platforms
            print("[BILLING] BillingManager not available - no restore on desktop")
            self._on_billing_restore_complete([])
        
    def purchase_hints(self, pack_name):
        """Handle hint pack purchase via Google Play Billing"""
        self._play_button_click_sound()
        print(f"[BILLING] Hint pack purchase initiated: {pack_name}")
        
        # Map pack name to BillingManager product name
        if self.billing_manager:
            self.billing_manager.purchase(pack_name)
        else:
            # Fallback for testing on non-Android platforms
            print("[BILLING] BillingManager not available - simulating purchase")
            # Parse hints to add for desktop simulation
            product_id = None
            if "10 Hints" in pack_name:
                product_id = "hint_pack_10"
            elif "50 Hints" in pack_name:
                product_id = "hint_pack_50"
            elif "100 Hints" in pack_name:
                product_id = "hint_pack_100"
            if product_id:
                self._on_billing_purchase_success(product_id, pack_name)
        
    def purchase_auto_solve_option(self, option_name):
        """Handle Auto-Solve in-app purchase via Google Play Billing"""
        self._play_button_click_sound()
        print(f"[BILLING] Auto-Solve purchase initiated: {option_name}")
        
        # Use BillingManager for real Google Play purchase
        if self.billing_manager:
            self.billing_manager.purchase(option_name)
        else:
            # Fallback for testing on non-Android platforms
            print("[BILLING] BillingManager not available - simulating purchase")
            product_id = None
            if option_name == "5 Auto-Solves":
                product_id = "auto_solve_5"
            elif option_name == "24h Unlimited":
                product_id = "auto_solve_24h"
            elif option_name == "Forever Unlimited":
                product_id = "auto_solve_forever"
            if product_id:
                self._on_billing_purchase_success(product_id, option_name)
        
    def select_theme(self, theme_name):
        """Handle theme selection (placeholder)"""
        self._play_button_click_sound()
        print(f"[SHOP] Theme selected: {theme_name}")
        # TODO: Implement theme switching here

    def _on_billing_purchase_success(self, product_id, product_name):
        """
        Callback when a purchase is successfully completed.
        Called by BillingManager after Google Play confirms the purchase.
        """
        import datetime
        from kivy.clock import Clock
        
        print(f"[BILLING] Purchase successful: {product_id} ({product_name})")
        
        # Deliver the product based on product_id
        if product_id == "premium_unlock":
            self.has_premium = True
            self._save_stats_and_achievements()
            print("[BILLING] Premium status activated!")
            
        elif product_id == "hint_pack_10":
            self.global_hints_remaining += 10
            self._save_global_hints()
            print(f"[BILLING] Added 10 hints. Total: {self.global_hints_remaining}")
            
        elif product_id == "hint_pack_50":
            self.global_hints_remaining += 50
            self._save_global_hints()
            print(f"[BILLING] Added 50 hints. Total: {self.global_hints_remaining}")
            
        elif product_id == "hint_pack_100":
            self.global_hints_remaining += 100
            self._save_global_hints()
            print(f"[BILLING] Added 100 hints. Total: {self.global_hints_remaining}")
            
        elif product_id == "auto_solve_5":
            self.auto_solve_credits += 5
            print(f"[BILLING] Added 5 auto-solve credits. Total: {self.auto_solve_credits}")
            
        elif product_id == "auto_solve_24h":
            self.unlimited_until = (datetime.datetime.now() + datetime.timedelta(hours=24)).isoformat()
            print(f"[BILLING] 24h unlimited access until: {self.unlimited_until}")
            
        elif product_id == "auto_solve_forever":
            self.unlimited_forever = True
            print("[BILLING] Forever unlimited auto-solve activated!")
        
        # Update UI elements on main thread
        def update_ui(dt):
            try:
                self._update_hint_button_text()
                self._update_auto_solve_button_text()
            except Exception as e:
                print(f"[BILLING] Error updating UI after purchase: {e}")
        
        Clock.schedule_once(update_ui, 0)
        
        # Save game state
        if hasattr(self, 'game') and hasattr(self.game, 'puzzle'):
            self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, True)
        
        # Show success popup
        Clock.schedule_once(lambda dt: self._show_purchase_success_popup(product_name), 0.1)
    
    def _on_billing_purchase_error(self, error_message):
        """
        Callback when a purchase fails.
        Called by BillingManager when Google Play returns an error.
        """
        from kivy.clock import Clock
        print(f"[BILLING] Purchase error: {error_message}")
        
        Clock.schedule_once(lambda dt: self._show_purchase_error_popup(error_message), 0.1)
    
    def _on_billing_restore_complete(self, restored_products):
        """
        Callback when restore purchases completes.
        Called by BillingManager after querying Google Play for owned items.
        """
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle
        from kivy.core.window import Window
        from kivy.clock import Clock
        
        print(f"[BILLING] Restore complete. Products: {restored_products}")
        
        # Show result popup on main thread
        def show_popup(dt):
            from kivy.uix.image import Image
            from kivy.uix.widget import Widget
            import os
            
            win_w, win_h = Window.width, Window.height
            result_popup_w = min(win_w * 0.8, dp(300))
            
            # Check if Premium is in the restored products
            has_premium = any(p in ["premium_unlock", "Premium Unlock"] for p in restored_products) if restored_products else False
            has_forever = any(p in ["auto_solve_forever", "Forever Unlimited"] for p in restored_products) if restored_products else False
            
            # Adjust popup height based on content (ensure OK button not overlapping text)
            if has_premium:
                result_popup_h = dp(360)  # Slightly taller to avoid overlap
            else:
                result_popup_h = dp(360)
            
            result_content = BoxLayout(orientation='vertical', padding=[dp(15), dp(60), dp(15), dp(15)], spacing=dp(10))
            with result_content.canvas.before:
                Color(0.5, 0, 0, 1)  # Maroon
                self._restore_bg_rect = Rectangle(size=result_content.size, pos=result_content.pos)
            result_content.bind(size=lambda inst, val: setattr(self._restore_bg_rect, 'size', val))
            result_content.bind(pos=lambda inst, val: setattr(self._restore_bg_rect, 'pos', val))
            
            if restored_products:
                # Title (spacer is now in top padding of container)
                title_label = Label(
                    text="Purchase Restored!",
                    font_size=dp(18),
                    bold=True,
                    color=(1, 1, 1, 1),
                    size_hint=(1, None),
                    height=dp(35),
                    halign='center',
                    valign='middle'
                )
                title_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
                result_content.add_widget(title_label)
                
                if has_premium:
                    # Show Premium icon (trumps Forever Unlimited text)
                    icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Images', 'premium_icon.PNG')
                    premium_img = Image(
                        source=icon_path,
                        size_hint=(None, None),
                        size=(dp(110), dp(110)),
                        pos_hint={'center_x': 0.5}
                    )
                    img_layout = BoxLayout(size_hint=(1, None), height=dp(120))
                    img_layout.add_widget(Widget())
                    img_layout.add_widget(premium_img)
                    img_layout.add_widget(Widget())
                    result_content.add_widget(img_layout)
                elif has_forever:
                    # Show Forever Unlimited text only (no Premium)
                    item_label = Label(
                        text="Forever Unlimited Auto-Solves",
                        font_size=dp(14),
                        color=(1, 1, 1, 1),
                        size_hint=(1, None),
                        height=dp(40),
                        halign='center',
                        valign='middle'
                    )
                    item_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
                    result_content.add_widget(item_label)
                
                # Update UI
                try:
                    self._update_hint_button_text()
                    self._update_auto_solve_button_text()
                except:
                    pass
            else:
                message = "No Purchases Found\n\nNo previous purchases were found to restore.\n\nNote: Hint packs and Auto-Solve credits cannot be restored."
                result_label = Label(
                    text=message,
                    font_size=dp(14),
                    color=(1, 1, 1, 1),
                    size_hint=(1, 1),
                    halign='center',
                    valign='middle'
                )
                result_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
                result_content.add_widget(result_label)
            
            ok_btn = Button(
                text="OK",
                font_size=dp(14),
                size_hint=(None, None),
                size=(dp(80), dp(36)),
                background_color=(0.75, 0.75, 0.75, 1),
                color=(1, 1, 1, 1)
            )
            btn_layout = BoxLayout(size_hint=(1, None), height=dp(45))
            btn_layout.add_widget(BoxLayout(size_hint_x=1))
            btn_layout.add_widget(ok_btn)
            btn_layout.add_widget(BoxLayout(size_hint_x=1))
            result_content.add_widget(btn_layout)
            
            result_popup = Popup(
                title='',
                content=result_content,
                size_hint=(None, None),
                size=(result_popup_w, result_popup_h),
                auto_dismiss=True,
                separator_height=0,
                background=''
            )
            
            def on_ok(instance):
                result_popup.dismiss()
                # Dismiss the original shop popup if it's still open
                popup_to_close = getattr(self, '_restore_popup_to_close', None)
                if popup_to_close:
                    try:
                        popup_to_close.dismiss()
                    except:
                        pass
                self._restore_popup_to_close = None
            
            ok_btn.bind(on_release=on_ok)
            result_popup.open()
        
        Clock.schedule_once(show_popup, 0)
    
    def _show_purchase_success_popup(self, product_name):
        """Show a success popup after a purchase is completed."""
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.uix.image import Image
        from kivy.uix.widget import Widget
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle
        from kivy.core.window import Window
        
        # Map product_id or product_name to friendly display names
        display_name_map = {
            "hint_pack_10": "10 Hints",
            "hint_pack_50": "50 Hints",
            "hint_pack_100": "100 Hints",
            "auto_solve_5": "5 Auto-Solves",
            "auto_solve_24h": "24 Hours of Unlimited Auto-Solves",
            "auto_solve_forever": "Forever Unlimited Auto-Solves",
            "premium_unlock": "premium_icon",
            # Also handle friendly names passed from fallback code
            "10 Hints": "10 Hints",
            "50 Hints": "50 Hints",
            "100 Hints": "100 Hints",
            "5 Auto-Solves": "5 Auto-Solves",
            "24h Unlimited": "24 Hours of Unlimited Auto-Solves",
            "Forever Unlimited": "Forever Unlimited Auto-Solves",
            "Premium Unlock": "premium_icon",
        }
        
        display_name = display_name_map.get(product_name, product_name)
        is_premium = (display_name == "premium_icon")
        
        win_w, win_h = Window.width, Window.height
        popup_w = min(win_w * 0.8, dp(280))
        popup_h = dp(250) if is_premium else dp(210)
        
        content = BoxLayout(orientation='vertical', padding=[dp(15), dp(50), dp(15), dp(15)], spacing=dp(10))
        with content.canvas.before:
            Color(0.1, 0.4, 0.15, 1)  # Dark green
            self._success_popup_bg = Rectangle(size=content.size, pos=content.pos)
        content.bind(size=lambda inst, val: setattr(self._success_popup_bg, 'size', val))
        content.bind(pos=lambda inst, val: setattr(self._success_popup_bg, 'pos', val))
        
        # Spacer to push content down
        from kivy.uix.widget import Widget
        content.add_widget(Widget(size_hint=(1, None), height=dp(30)))
        
        # Title label
        title_label = Label(
            text="Purchase Successful!",
            font_size=dp(16),
            bold=True,
            color=(1, 1, 1, 1),
            size_hint=(1, None),
            height=dp(30),
            halign='center',
            valign='middle'
        )
        title_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
        content.add_widget(title_label)
        
        if is_premium:
            # Show premium icon image
            import os
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Images', 'premium_icon.PNG')
            premium_img = Image(
                source=icon_path,
                size_hint=(None, None),
                size=(dp(96), dp(96)),
                pos_hint={'center_x': 0.5}
            )
            img_layout = BoxLayout(size_hint=(1, None), height=dp(100))
            img_layout.add_widget(Widget())
            img_layout.add_widget(premium_img)
            img_layout.add_widget(Widget())
            content.add_widget(img_layout)
        else:
            # Show product display name
            product_label = Label(
                text=display_name,
                font_size=dp(14),
                color=(1, 1, 1, 1),
                size_hint=(1, None),
                height=dp(30),
                halign='center',
                valign='middle'
            )
            product_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            content.add_widget(product_label)
        
        # Spacer before OK button
        content.add_widget(Widget(size_hint=(1, 1)))
        
        ok_btn = Button(
            text="OK",
            font_size=dp(14),
            size_hint=(None, None),
            size=(dp(80), dp(36)),
            background_color=(0.75, 0.75, 0.75, 1),
            color=(1, 1, 1, 1)
        )
        btn_layout = BoxLayout(size_hint=(1, None), height=dp(40))
        btn_layout.add_widget(BoxLayout(size_hint_x=1))
        btn_layout.add_widget(ok_btn)
        btn_layout.add_widget(BoxLayout(size_hint_x=1))
        content.add_widget(btn_layout)
        
        success_popup = Popup(
            title='',
            content=content,
            size_hint=(None, None),
            size=(popup_w, popup_h),
            auto_dismiss=True,
            separator_height=0,
            background=''
        )
        
        ok_btn.bind(on_release=lambda x: success_popup.dismiss())
        success_popup.open()
    
    def _show_purchase_error_popup(self, error_message):
        """Show an error popup when a purchase fails."""
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle
        from kivy.core.window import Window
        
        win_w, win_h = Window.width, Window.height
        popup_w = min(win_w * 0.8, dp(300))
        popup_h = dp(170)
        
        content = BoxLayout(orientation='vertical', padding=dp(15), spacing=dp(10))
        with content.canvas.before:
            Color(0.5, 0, 0, 1)  # Maroon
            self._error_popup_bg = Rectangle(size=content.size, pos=content.pos)
        content.bind(size=lambda inst, val: setattr(self._error_popup_bg, 'size', val))
        content.bind(pos=lambda inst, val: setattr(self._error_popup_bg, 'pos', val))
        
        msg_label = Label(
            text=f"Purchase Failed\n\n{error_message}",
            font_size=dp(14),
            color=(1, 1, 1, 1),
            size_hint=(1, 1),
            halign='center',
            valign='middle'
        )
        msg_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
        content.add_widget(msg_label)
        
        ok_btn = Button(
            text="OK",
            font_size=dp(14),
            size_hint=(None, None),
            size=(dp(80), dp(36)),
            background_color=(0.75, 0.75, 0.75, 1),
            color=(1, 1, 1, 1)
        )
        btn_layout = BoxLayout(size_hint=(1, None), height=dp(40))
        btn_layout.add_widget(BoxLayout(size_hint_x=1))
        btn_layout.add_widget(ok_btn)
        btn_layout.add_widget(BoxLayout(size_hint_x=1))
        content.add_widget(btn_layout)
        
        error_popup = Popup(
            title='',
            content=content,
            size_hint=(None, None),
            size=(popup_w, popup_h),
            auto_dismiss=True,
            separator_height=0,
            background=''
        )
        
        ok_btn.bind(on_release=lambda x: error_popup.dismiss())
        error_popup.open()

    def _load_stats_and_achievements(self):
        """Load saved game statistics and achievements from storage"""
        try:
            import json
            import os
            import sys
            from kivy.app import App
            save_dir = App.get_running_app().user_data_dir
            stats_path = os.path.join(save_dir, 'game_stats.json')
            
            # Detect if running in development mode (from venv, not packaged Store app)
            is_development = '.venv' in sys.executable or 'AppData\\Local\\Programs\\PythonSoftwareFoundation' in sys.executable
            
            if os.path.exists(stats_path):
                with open(stats_path, 'r') as f:
                    data = json.load(f)
                    if 'game_stats' in data:
                        self.game_stats.update(data['game_stats'])
                    if 'achievements' in data:
                        self.achievements.update(data['achievements'])
                    if 'has_premium' in data:
                        loaded_has_premium = data['has_premium']
                        # In development mode, always reset premium for testing
                        if is_development:
                            self.has_premium = False
                            print(f"[STATS] Development mode detected - premium reset to False for testing")
                        else:
                            # In packaged app, persist premium status
                            self.has_premium = loaded_has_premium
                            if loaded_has_premium:
                                print("[STATS] Premium status loaded from Store app")
                print(f"[STATS] Loaded stats: {self.game_stats['puzzles_completed']} puzzles completed")
        except Exception as e:
            print(f"[STATS] Error loading stats: {e}")

    def _save_stats_and_achievements(self):
        """Save game statistics and achievements to storage"""
        try:
            import json
            import os
            from kivy.app import App
            save_dir = App.get_running_app().user_data_dir
            stats_path = os.path.join(save_dir, 'game_stats.json')
            
            data = {
                'game_stats': self.game_stats,
                'achievements': self.achievements,
                'has_premium': self.has_premium
            }
            
            with open(stats_path, 'w') as f:
                json.dump(data, f, indent=2)
            print(f"[STATS] Saved stats successfully")
        except Exception as e:
            print(f"[STATS] Error saving stats: {e}")

    def _format_time(self, seconds):
        """Format seconds into readable time string"""
        if seconds is None:
            return "--:--"
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

    def _check_and_unlock_achievements(self):
        """Check if any new achievements should be unlocked"""
        import datetime
        stats = self.game_stats
        changed = False
        
        # First Victory
        if stats['puzzles_completed'] >= 1 and not self.achievements['first_victory']:
            self.achievements['first_victory'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: First Victory!")
        
        # Marathon (10 puzzles)
        if stats['puzzles_completed'] >= 10 and not self.achievements['marathon']:
            self.achievements['marathon'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: Marathon!")
        
        # Centurion (100 puzzles)
        if stats['puzzles_completed'] >= 100 and not self.achievements['centurion']:
            self.achievements['centurion'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: Centurion!")
        
        # Mastery achievements (10 of each difficulty) - must have ≤3 hints per puzzle
        qualified = stats.get('qualified_by_difficulty', {'easy': 0, 'moderate': 0, 'tough': 0, 'expert': 0, 'evil': 0, 'diabolical': 0})
        
        if qualified.get('easy', 0) >= 10 and not self.achievements['master_easy']:
            self.achievements['master_easy'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: Easy Master!")
        
        if qualified.get('moderate', 0) >= 10 and not self.achievements['master_medium']:
            self.achievements['master_medium'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: Moderate Master!")
        
        if qualified.get('tough', 0) >= 10 and not self.achievements['master_hard']:
            self.achievements['master_hard'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: Tough Master!")
        
        # Expert (complete 1 expert puzzle with ≤3 hints)
        if qualified.get('expert', 0) >= 1 and not self.achievements.get('expert', False):
            self.achievements['expert'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: Expert!")
        
        # Note: Diabolical Mastermind is checked at puzzle completion time
        # when we can verify no hints were used during that specific game
        
        # Streak achievements
        if stats['current_streak'] >= 3 and not self.achievements['streak_3']:
            self.achievements['streak_3'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: 3-Day Streak!")
        
        if stats['current_streak'] >= 7 and not self.achievements['streak_7']:
            self.achievements['streak_7'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: Week Warrior!")
        
        if stats['current_streak'] >= 30 and not self.achievements['streak_30']:
            self.achievements['streak_30'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: Monthly Master!")
        
        # Time played achievements
        if stats['total_play_time_seconds'] >= 3600 and not self.achievements['time_traveler']:
            self.achievements['time_traveler'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: Time Traveler!")
        
        if stats['total_play_time_seconds'] >= 36000 and not self.achievements['dedicated']:
            self.achievements['dedicated'] = True
            changed = True
            print("[ACHIEVEMENT] Unlocked: Dedicated!")
        
        if changed:
            self._save_stats_and_achievements()

    def show_stats_achievements_screen(self):
        """Show the Stats & Achievements screen for premium users - Full screen version"""
        print("[STATS] show_stats_achievements_screen called")
        
        # Check if stats screen is already open to prevent duplicates
        if hasattr(self, 'stats_screen') and self.stats_screen is not None:
            print("[STATS] Stats screen already open, ignoring")
            return
        
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.floatlayout import FloatLayout
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.uix.scrollview import ScrollView
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.uix.widget import Widget
        from kivy.uix.image import Image
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle
        from kivy.core.window import Window
        
        # Store reference to close later
        self.stats_screen = None
        
        # Path to yin yang PNG with transparency
        yin_yang_path = resource_path('Images/yin_yang.png')
        
        # Helper function to create a yin-yang icon image
        def create_yin_yang_icon(size=dp(24)):
            """Create a yin-yang image widget"""
            icon = Image(
                source=yin_yang_path,
                size_hint=(None, None),
                size=(size, size)
            )
            return icon
        
        # Paths to Enso circle PNGs for Achievements tab
        enso_circle_path = resource_path('Images/Enso_Circle.png')
        complete_enso_path = resource_path('Images/Complete_Enso_Circle.png')
        
        # Helper function to create an Enso circle icon image
        def create_enso_icon(complete=True, size=dp(24)):
            """Create an Enso circle image widget - complete or incomplete"""
            icon = Image(
                source=complete_enso_path if complete else enso_circle_path,
                size_hint=(None, None),
                size=(size, size)
            )
            return icon
        
        # Main full-screen container
        screen = FloatLayout(size_hint=(1, 1))
        
        # Background image - use keep_ratio=True and scale to cover screen (crop excess)
        # Calculate size to fill screen while maintaining aspect ratio
        from kivy.uix.stencilview import StencilView
        
        # Create a stencil container to clip the image
        bg_container = StencilView(size_hint=(1, 1), pos_hint={'x': 0, 'y': 0})
        
        bg_image = Image(
            source=resource_path('Images/Achievement_Screen.JPG'),
            allow_stretch=True,
            keep_ratio=True,
            size_hint=(None, None)
        )
        
        # Bind to resize the image to cover the screen (like CSS background-size: cover)
        def update_bg_size(*args):
            # Get container size
            container_w = bg_container.width
            container_h = bg_container.height
            
            if bg_image.texture:
                img_w = bg_image.texture.width
                img_h = bg_image.texture.height
                
                # Calculate scale to cover (fill) the container
                scale_w = container_w / img_w
                scale_h = container_h / img_h
                scale = max(scale_w, scale_h)  # Use max to cover entire area
                
                # Set new size
                bg_image.size = (img_w * scale, img_h * scale)
                
                # Center the image
                bg_image.pos = (
                    (container_w - bg_image.width) / 2,
                    (container_h - bg_image.height) / 2
                )
        
        bg_container.bind(size=update_bg_size)
        bg_image.bind(texture=update_bg_size)
        bg_container.add_widget(bg_image)
        screen.add_widget(bg_container)
        
        # Centered content container
        center_anchor = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, 1))
        
        # Main content box - centered with padding
        main_box = BoxLayout(
            orientation='vertical',
            padding=dp(20),
            spacing=dp(15),
            size_hint=(0.95, 0.95)
        )
        
        # Title with dark purple styling
        title_label = Label(
            text="Stats & Achievements",
            font_size=dp(28),
            color=(0.4, 0.2, 0.5, 1),  # Dark purple
            size_hint=(1, None),
            height=dp(50),
            bold=True,
            halign='center',
            valign='middle'
        )
        title_label.text_size = (None, None)  # Let text be naturally centered
        main_box.add_widget(title_label)
        
        # Custom tab implementation with spacing between tabs
        from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
        
        # Container for tabs and content
        tabs_container = BoxLayout(orientation='vertical', size_hint=(1, 1))
        
        # Tab buttons row with spacing
        tab_buttons_row = BoxLayout(
            orientation='horizontal',
            size_hint=(1, None),
            height=dp(50),
            spacing=dp(48),  # Half inch gap between tabs
            padding=(dp(20), 0)  # Horizontal padding
        )
        
        # Screen manager for tab content
        screen_manager = ScreenManager(transition=NoTransition())
        
        # Stats tab button
        stats_btn = Button(
            text='Statistics',
            font_size=dp(16),
            size_hint=(0.5, 1),
            background_color=(0.4, 0.2, 0.5, 0.8),
            background_normal='',
            color=(1, 1, 1, 1),
            bold=True
        )
        
        # Achievements tab button
        achieve_btn = Button(
            text='Achievements',
            font_size=dp(16),
            size_hint=(0.5, 1),
            background_color=(0.3, 0.15, 0.35, 0.6),
            background_normal='',
            color=(0.8, 0.8, 0.8, 1),
            bold=True
        )
        
        def switch_to_stats(instance):
            screen_manager.current = 'stats'
            stats_btn.background_color = (0.4, 0.2, 0.5, 0.8)
            stats_btn.color = (1, 1, 1, 1)
            achieve_btn.background_color = (0.3, 0.15, 0.35, 0.6)
            achieve_btn.color = (0.8, 0.8, 0.8, 1)
        
        def switch_to_achievements(instance):
            screen_manager.current = 'achievements'
            achieve_btn.background_color = (0.4, 0.2, 0.5, 0.8)
            achieve_btn.color = (1, 1, 1, 1)
            stats_btn.background_color = (0.3, 0.15, 0.35, 0.6)
            stats_btn.color = (0.8, 0.8, 0.8, 1)
        
        stats_btn.bind(on_release=switch_to_stats)
        achieve_btn.bind(on_release=switch_to_achievements)
        
        tab_buttons_row.add_widget(stats_btn)
        tab_buttons_row.add_widget(achieve_btn)
        tabs_container.add_widget(tab_buttons_row)
        
        # ===== STATS SCREEN =====
        stats_screen = Screen(name='stats')
        stats_scroll = ScrollView(size_hint=(1, 1))
        stats_content = BoxLayout(
            orientation='vertical',
            padding=dp(15),
            spacing=dp(10),
            size_hint_y=None
        )
        stats_content.bind(minimum_height=stats_content.setter('height'))
        
        # Add stat rows
        stats = self.game_stats

        def create_stat_row(label_text, value_text):
            """Create a centered stat row with limited width for better readability."""
            from kivy.uix.anchorlayout import AnchorLayout

            inner_width = min(dp(820), Window.width * 0.9)

            outer = AnchorLayout(size_hint=(1, None), height=dp(48))

            inner = BoxLayout(
                orientation='horizontal',
                size_hint=(None, None),
                height=dp(40),
                width=inner_width
            )

            with inner.canvas.before:
                Color(0.1, 0.05, 0.15, 0.65)
                row_bg = Rectangle(size=inner.size, pos=inner.pos)

            inner.bind(size=lambda inst, val: setattr(row_bg, 'size', val))
            inner.bind(pos=lambda inst, val: setattr(row_bg, 'pos', val))

            # LEFT HALF
            left_side = AnchorLayout(
                anchor_x='center',
                anchor_y='center',
                size_hint=(0.5, 1)
            )

            left_content = BoxLayout(
                orientation='horizontal',
                spacing=dp(8),
                size_hint=(None, None),
                width=dp(260),
                height=dp(24)
            )

            icon = create_yin_yang_icon(dp(24))
            left_content.add_widget(icon)

            lbl = Label(
                text=label_text,
                font_size=dp(15),
                color=(0.95, 0.95, 0.95, 1),
                halign='left',
                valign='middle',
                size_hint=(1, 1)
            )
            lbl.bind(size=lbl.setter('text_size'))

            left_content.add_widget(lbl)
            left_side.add_widget(left_content)

            # RIGHT HALF
            right_side = AnchorLayout(
                anchor_x='center',
                anchor_y='center',
                size_hint=(0.5, 1)
            )

            val = Label(
                text=str(value_text),
                font_size=dp(15),
                color=(1, 0.85, 0.3, 1),
                halign='center',
                valign='middle',
                size_hint=(None, None),
                size=(dp(140), dp(24))
            )
            val.bind(size=val.setter('text_size'))

            right_side.add_widget(val)

            inner.add_widget(left_side)
            inner.add_widget(right_side)

            outer.add_widget(inner)
            return outer
        
        def create_section_header(text):
            """Create a section header - larger bold white text, centered"""
            lbl = Label(
                text=text,
                font_size=dp(20),
                color=(1, 1, 1, 1),  # White
                halign='center',
                valign='middle',
                bold=True,
                size_hint=(1, None),
                height=dp(38)
            )
            lbl.bind(size=lbl.setter('text_size'))
            return lbl
        
        # General Stats
        stats_content.add_widget(create_section_header("General"))
        stats_content.add_widget(create_stat_row("Puzzles Started", stats['puzzles_started']))
        stats_content.add_widget(create_stat_row("Puzzles Completed", stats['puzzles_completed']))
        completion_rate = (stats['puzzles_completed'] / max(1, stats['puzzles_started'])) * 100
        stats_content.add_widget(create_stat_row("Completion Rate", f"{completion_rate:.1f}%"))
        stats_content.add_widget(create_stat_row("Perfect Games", stats['perfect_games']))
        stats_content.add_widget(create_stat_row("Total Play Time", self._format_time(stats['total_play_time_seconds'])))
        
        # Streak Stats
        stats_content.add_widget(Widget(size_hint_y=None, height=dp(10)))
        stats_content.add_widget(create_section_header("Streaks"))
        stats_content.add_widget(create_stat_row("Current Day Streak", f"{stats['current_streak']} days"))
        stats_content.add_widget(create_stat_row("Best Day Streak", f"{stats['best_streak']} days"))
        stats_content.add_widget(create_stat_row("Current Win Streak", f"{stats.get('puzzle_win_streak', 0)} puzzles"))
        stats_content.add_widget(create_stat_row("Best Win Streak", f"{stats.get('best_puzzle_win_streak', 0)} puzzles"))
        
        # Difficulty Breakdown
        stats_content.add_widget(Widget(size_hint_y=None, height=dp(10)))
        stats_content.add_widget(create_section_header("By Difficulty"))
        stats_content.add_widget(create_stat_row("Easy", stats['puzzles_by_difficulty'].get('easy', 0)))
        stats_content.add_widget(create_stat_row("Moderate", stats['puzzles_by_difficulty'].get('moderate', 0)))
        stats_content.add_widget(create_stat_row("Tough", stats['puzzles_by_difficulty'].get('tough', 0)))
        stats_content.add_widget(create_stat_row("Expert", stats['puzzles_by_difficulty'].get('expert', 0)))
        stats_content.add_widget(create_stat_row("Evil", stats['puzzles_by_difficulty'].get('evil', 0)))
        stats_content.add_widget(create_stat_row("Diabolical", stats['puzzles_by_difficulty'].get('diabolical', 0)))
        
        # Best Times
        stats_content.add_widget(Widget(size_hint_y=None, height=dp(10)))
        stats_content.add_widget(create_section_header("Best Times"))
        stats_content.add_widget(create_stat_row("Easy", self._format_time(stats.get('fastest_easy'))))
        stats_content.add_widget(create_stat_row("Moderate", self._format_time(stats.get('fastest_moderate'))))
        stats_content.add_widget(create_stat_row("Tough", self._format_time(stats.get('fastest_tough'))))
        stats_content.add_widget(create_stat_row("Expert", self._format_time(stats.get('fastest_expert'))))
        stats_content.add_widget(create_stat_row("Evil", self._format_time(stats.get('fastest_evil'))))
        stats_content.add_widget(create_stat_row("Diabolical", self._format_time(stats.get('fastest_diabolical'))))
        
        # Usage Stats
        stats_content.add_widget(Widget(size_hint_y=None, height=dp(10)))
        stats_content.add_widget(create_section_header("Usage"))
        stats_content.add_widget(create_stat_row("Hints Used", stats['hints_used_total']))
        stats_content.add_widget(create_stat_row("Auto-Solves Used", stats['auto_solves_used']))
        stats_content.add_widget(create_stat_row("Total Mistakes", stats['mistakes_made_total']))
        
        stats_scroll.add_widget(stats_content)
        stats_screen.add_widget(stats_scroll)
        screen_manager.add_widget(stats_screen)
        
        # ===== ACHIEVEMENTS SCREEN =====
        achieve_screen = Screen(name='achievements')
        achieve_scroll = ScrollView(size_hint=(1, 1))
        achieve_content = BoxLayout(
            orientation='vertical',
            padding=dp(15),
            spacing=dp(10),
            size_hint_y=None
        )
        achieve_content.bind(minimum_height=achieve_content.setter('height'))
        
        # Achievement definitions - descriptions updated with hint limits
        achievement_defs = [
            ('first_victory', 'First Victory', 'Solved your first puzzle', '1 puzzle'),
            ('perfectionist', 'Perfectionist', 'Solved a puzzle with no mistakes (max 3 hints)', '\u2264 3 hints'),
            ('hint_free', 'Self-Reliant', 'Solved a puzzle without using any hints', 'No hints'),
            ('speed_demon', 'Speed Demon', 'Solved Easy in under 3 min (max 2 hints)', '< 3 min'),
            ('marathon', 'Marathon', 'Solved 10 puzzles', '10 puzzles'),
            ('centurion', 'Centurion', 'Solved 100 puzzles', '100 puzzles'),
            ('master_easy', 'Easy Master', 'Solved 10 Easy puzzles (max 3 hints each)', '10 Easy'),
            ('master_medium', 'Medium Master', 'Solved 10 Medium puzzles (max 3 hints each)', '10 Medium'),
            ('master_hard', 'Hard Master', 'Solved 10 Hard puzzles (max 3 hints each)', '10 Hard'),
            ('expert', 'Expert', 'Solved an Expert puzzle (max 3 hints)', '1 Expert'),
            ('diabolical_mastermind', 'Diabolical Mastermind', 'Solved a Diabolical puzzle without any hints', 'No hints'),
            ('streak_3', 'On Fire', 'Solved puzzles 3 days in a row', '3-day streak'),
            ('streak_7', 'Week Warrior', 'Solved puzzles 7 days in a row', '7-day streak'),
            ('streak_30', 'Monthly Master', 'Solved puzzles 30 days in a row', '30-day streak'),
            ('time_traveler', 'Time Traveler', 'Played for 1 hour total', '1 hour'),
            ('dedicated', 'Dedicated', 'Played for 10 hours total', '10 hours')
        ]
        
        def create_achievement_row(key, title, description, requirement):
            """Create a centered achievement row matching the width of stat rows."""
            from kivy.uix.anchorlayout import AnchorLayout
            inner_width = min(dp(820), Window.width * 0.9)

            outer = AnchorLayout(size_hint=(1, None), height=dp(65))

            inner = BoxLayout(
                orientation='vertical',
                size_hint=(None, None),
                height=dp(65),
                width=inner_width,
                padding=dp(5)
            )
            with inner.canvas.before:
                Color(0.1, 0.2, 0.1, 0.65)
                row_bg = Rectangle(size=inner.size, pos=inner.pos)
            inner.bind(size=lambda inst, val: setattr(row_bg, 'size', val))
            inner.bind(pos=lambda inst, val: setattr(row_bg, 'pos', val))

            # Title row with centered left/right halves
            title_row = BoxLayout(orientation='horizontal', size_hint=(1, 0.5))

            # LEFT HALF
            left_side = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(0.5, 1))
            left_content = BoxLayout(
                orientation='horizontal',
                spacing=dp(8),
                size_hint=(None, None),
                width=dp(260),
                height=dp(24)
            )
            icon = create_enso_icon(complete=True, size=dp(22))
            left_content.add_widget(icon)
            title_lbl = Label(
                text=title,
                font_size=dp(15),
                color=(1, 0.85, 0.3, 1),
                halign='left',
                valign='middle',
                size_hint=(1, 1)
            )
            title_lbl.bind(size=title_lbl.setter('text_size'))
            left_content.add_widget(title_lbl)
            left_side.add_widget(left_content)

            # RIGHT HALF
            right_side = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(0.5, 1))
            req_lbl = Label(
                text=requirement,
                font_size=dp(12),
                color=(0.5, 1, 0.5, 1),
                halign='center',
                valign='middle',
                size_hint=(None, None),
                size=(dp(180), dp(24))
            )
            req_lbl.bind(size=req_lbl.setter('text_size'))
            right_side.add_widget(req_lbl)

            title_row.add_widget(left_side)
            title_row.add_widget(right_side)

            # Description row - mirrors left_content structure so text
            # aligns directly under the title label (past icon + spacing)
            desc_row = BoxLayout(orientation='horizontal', size_hint=(1, 0.5))

            # Left half: spacer matching left_content layout (icon=22dp + spacing=8dp + padding=8dp)
            left_desc = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(0.5, 1))
            left_desc_content = BoxLayout(
                orientation='horizontal',
                size_hint=(None, None),
                width=dp(260),
                height=dp(18)
            )
            from kivy.uix.widget import Widget as _W
            # Spacer = icon width + spacing (matches left_content icon + spacing)
            left_desc_content.add_widget(_W(size_hint=(None, 1), width=dp(22 + 8)))
            desc_lbl = Label(
                text=description,
                font_size=dp(12),
                color=(0.8, 0.8, 0.8, 1),
                halign='left',
                valign='middle',
                size_hint=(1, 1)
            )
            desc_lbl.bind(size=desc_lbl.setter('text_size'))
            left_desc_content.add_widget(desc_lbl)
            left_desc.add_widget(left_desc_content)
            desc_row.add_widget(left_desc)

            # Right half: empty placeholder to keep layout balanced
            desc_row.add_widget(AnchorLayout(size_hint=(0.5, 1)))

            inner.add_widget(title_row)
            inner.add_widget(desc_row)
            outer.add_widget(inner)
            return outer
        
        # Count unlocked achievements and only show those
        unlocked_achievements = [(k, t, d, r) for k, t, d, r in achievement_defs if self.achievements.get(k, False)]
        unlocked_count = len(unlocked_achievements)
        total_count = len(achievement_defs)
        
        # Progress header - centered, same width as rows
        from kivy.uix.anchorlayout import AnchorLayout
        all_unlocked = (unlocked_count == total_count)
        inner_width = min(dp(820), Window.width * 0.9)
        progress_outer = AnchorLayout(size_hint=(1, None), height=dp(40))
        progress_inner = BoxLayout(
            orientation='horizontal',
            size_hint=(None, None),
            height=dp(40),
            width=inner_width,
            spacing=dp(10)
        )
        progress_icon = create_enso_icon(complete=all_unlocked, size=dp(24))
        progress_inner.add_widget(progress_icon)
        progress_lbl = Label(
            text=f"Achievements Unlocked: {unlocked_count}/{total_count}",
            font_size=dp(17),
            color=(1, 0.85, 0.3, 1),
            halign='left',
            valign='middle',
            size_hint=(1, 1)
        )
        progress_lbl.bind(size=progress_lbl.setter('text_size'))
        progress_inner.add_widget(progress_lbl)
        progress_outer.add_widget(progress_inner)
        achieve_content.add_widget(progress_outer)
        
        if unlocked_count == 0:
            # Show a message if no achievements unlocked yet
            no_achieve_lbl = Label(
                text="No achievements unlocked yet.\nComplete puzzles to earn achievements!",
                font_size=dp(15),
                color=(0.8, 0.8, 0.8, 1),
                size_hint=(1, None),
                height=dp(80),
                halign='center',
                valign='middle'
            )
            no_achieve_lbl.bind(size=no_achieve_lbl.setter('text_size'))
            achieve_content.add_widget(no_achieve_lbl)
        else:
            # Only show unlocked achievements
            for key, title, desc, req in unlocked_achievements:
                achieve_content.add_widget(create_achievement_row(key, title, desc, req))
        
        achieve_scroll.add_widget(achieve_content)
        achieve_screen.add_widget(achieve_scroll)
        screen_manager.add_widget(achieve_screen)
        
        # Add screen manager to tabs container
        tabs_container.add_widget(screen_manager)
        
        main_box.add_widget(tabs_container)
        
        # Close button - smaller and centered, using on_release for reliable mobile touch
        from kivy.uix.anchorlayout import AnchorLayout as CloseAnchor
        close_btn_anchor = CloseAnchor(anchor_x='center', anchor_y='center', size_hint=(1, None), height=dp(40))
        
        # Store references before creating button
        _screen_ref = screen
        _app_ref = self
        
        def close_stats_screen(*args):
            print("[STATS] Close button pressed!")
            from kivy.clock import Clock
            def do_close(dt):
                try:
                    if _screen_ref.parent:
                        _screen_ref.parent.remove_widget(_screen_ref)
                    _app_ref.stats_screen = None
                    print("[STATS] Screen removed successfully")
                except Exception as e:
                    print(f"[STATS] Close error: {e}")
            Clock.schedule_once(do_close, 0)
        
        close_btn = Button(
            text="Close",
            font_size=dp(14),
            size_hint=(None, None),
            size=(dp(100), dp(35)),
            background_color=(0.5, 0.25, 0.5, 1),
            background_normal='',
            background_down='',
            color=(1, 1, 1, 1)
        )
        close_btn.bind(on_release=close_stats_screen)
        
        close_btn_anchor.add_widget(close_btn)
        main_box.add_widget(close_btn_anchor)
        
        center_anchor.add_widget(main_box)
        screen.add_widget(center_anchor)
        
        # Add to root widget
        self.stats_screen = screen
        self.root.add_widget(screen)
        print("[STATS] Stats screen displayed successfully")

    def show_premium_offer_popup(self):
        """Show Out of Hints popup using the same visual language as Auto-Solve Magic."""
        try:
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.label import Label
            from kivy.uix.button import Button
            from kivy.uix.popup import Popup
            from kivy.uix.anchorlayout import AnchorLayout
            from kivy.uix.widget import Widget
            from kivy.uix.floatlayout import FloatLayout
            from kivy.metrics import dp
            from kivy.graphics import Color, Rectangle, Line
            from kivy.core.window import Window

            def add_3d_silver_button_effect(btn):
                with btn.canvas.after:
                    Color(0.5, 0.5, 0.5, 1)
                    border = Line(rectangle=(btn.x, btn.y, btn.width, btn.height), width=1)
                    Color(0.95, 0.95, 0.95, 1)
                    highlight_top = Line(points=[btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height], width=2)
                    highlight_left = Line(points=[btn.x, btn.y, btn.x, btn.y + btn.height], width=2)
                    Color(0.45, 0.45, 0.45, 1)
                    shadow_bottom = Line(points=[btn.x, btn.y, btn.x + btn.width, btn.y], width=2)
                    shadow_right = Line(points=[btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height], width=2)

                def update(instance, *args):
                    border.rectangle = (btn.x, btn.y, btn.width, btn.height)
                    highlight_top.points = [btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height]
                    highlight_left.points = [btn.x, btn.y, btn.x, btn.y + btn.height]
                    shadow_bottom.points = [btn.x, btn.y, btn.x + btn.width, btn.y]
                    shadow_right.points = [btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height]

                btn.bind(pos=update, size=update)

            print("[POPUP] Showing Out of Hints popup")

            win_w, win_h = Window.width, Window.height
            scale_factor = min(win_w / 600.0, win_h / 850.0)
            scale_factor = max(0.5, min(1.5, scale_factor))
            popup_w = min(win_w * 0.92, dp(350) * scale_factor)
            popup_h = min(win_h * 0.88, dp(560) * scale_factor)

            # Outer white border shell
            outer = FloatLayout()
            with outer.canvas.before:
                Color(1, 1, 1, 1)
                outer_rect = Rectangle(size=outer.size, pos=outer.pos)
            outer.bind(size=lambda inst, val: setattr(outer_rect, 'size', val))
            outer.bind(pos=lambda inst, val: setattr(outer_rect, 'pos', val))

            # Tan body to match Auto-Solve Magic popup
            content = BoxLayout(
                orientation='vertical',
                padding=(dp(14) * scale_factor, dp(14) * scale_factor, dp(14) * scale_factor, dp(14) * scale_factor),
                spacing=dp(10) * scale_factor,
                size_hint=(0.97, 0.97),
                pos_hint={'center_x': 0.5, 'center_y': 0.5}
            )
            with content.canvas.before:
                Color(0.82, 0.71, 0.55, 1)
                bg_rect = Rectangle(size=content.size, pos=content.pos)
            content.bind(size=lambda inst, val: setattr(bg_rect, 'size', val))
            content.bind(pos=lambda inst, val: setattr(bg_rect, 'pos', val))
            outer.add_widget(content)

            title_label = Label(
                text="\n Out of Hints!",
                font_size=dp(20) * scale_factor,
                color=(0.35, 0.2, 0.1, 1),
                size_hint=(1, None),
                height=dp(32) * scale_factor,
                bold=True,
                halign='center',
                valign='top'
            )
            title_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            content.add_widget(title_label)

            title_divider = Widget(size_hint=(0.7, None), height=dp(2) * scale_factor)
            with title_divider.canvas:
                Color(0.55, 0.4, 0.25, 1)
                title_divider_rect = Rectangle(size=title_divider.size, pos=title_divider.pos)
            title_divider.bind(size=lambda inst, val: setattr(title_divider_rect, 'size', val))
            title_divider.bind(pos=lambda inst, val: setattr(title_divider_rect, 'pos', val))
            divider_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(6) * scale_factor)
            divider_layout.add_widget(title_divider)
            content.add_widget(divider_layout)

            message_label = Label(
                text="Your free daily hint is used.\nChoose an upgrade to keep solving:",
                font_size=dp(13) * scale_factor,
                color=(0.3, 0.25, 0.2, 1),
                size_hint=(1, None),
                height=dp(40) * scale_factor,
                halign='center',
                valign='middle'
            )
            message_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            content.add_widget(message_label)
            content.add_widget(Widget(size_hint_y=None, height=dp(4) * scale_factor))

            iap_options = [
                ("Premium Unlock", "$4.99", "premium"),
                ("10 Hints", "$0.99", "hint"),
                ("50 Hints", "$1.99", "hint"),
                ("100 Hints", "$2.99", "hint")
            ]

            purchase_buttons = []
            for option_name, price, option_type in iap_options:
                row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(40) * scale_factor, spacing=dp(8) * scale_factor)

                name_label = Label(
                    text=option_name,
                    font_size=dp(13) * scale_factor,
                    color=(0.15, 0.1, 0.05, 1),
                    size_hint=(0.5, 1),
                    halign='left',
                    valign='middle'
                )
                name_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], val[1])))

                price_label = Label(
                    text=price,
                    font_size=dp(13) * scale_factor,
                    color=(0.0, 0.4, 0.0, 1),
                    size_hint=(0.22, 1),
                    halign='center',
                    valign='middle',
                    bold=True
                )

                purchase_btn = Button(
                    text="Buy",
                    font_size=dp(13) * scale_factor,
                    size_hint=(0.28, 1),
                    background_color=(0.75, 0.75, 0.75, 1),
                    color=(0, 0, 0, 1),
                    background_normal='',
                    background_down=''
                )
                add_3d_silver_button_effect(purchase_btn)

                purchase_buttons.append((purchase_btn, option_name, price, option_type))
                row.add_widget(name_label)
                row.add_widget(price_label)
                row.add_widget(purchase_btn)
                content.add_widget(row)

            bottom_divider = Widget(size_hint=(0.85, None), height=dp(1) * scale_factor)
            with bottom_divider.canvas:
                Color(0.6, 0.5, 0.35, 0.6)
                bottom_divider_rect = Rectangle(size=bottom_divider.size, pos=bottom_divider.pos)
            bottom_divider.bind(size=lambda inst, val: setattr(bottom_divider_rect, 'size', val))
            bottom_divider.bind(pos=lambda inst, val: setattr(bottom_divider_rect, 'pos', val))
            bottom_divider_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(12) * scale_factor)
            bottom_divider_layout.add_widget(bottom_divider)
            content.add_widget(bottom_divider_layout)

            close_btn = Button(
                text="Maybe Later",
                font_size=dp(13) * scale_factor,
                size_hint=(None, None),
                size=(dp(110) * scale_factor, dp(34) * scale_factor),
                background_color=(0.75, 0.75, 0.75, 1),
                color=(0, 0, 0, 1),
                background_normal='',
                background_down=''
            )
            add_3d_silver_button_effect(close_btn)
            close_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(40) * scale_factor)
            close_layout.add_widget(close_btn)
            content.add_widget(close_layout)

            restore_btn = Button(
                text="Restore Purchases",
                font_size=dp(11) * scale_factor,
                size_hint=(None, None),
                size=(dp(120) * scale_factor, dp(28) * scale_factor),
                background_color=(0.2, 0.6, 0.2, 1),
                background_normal='',
                background_down='',
                color=(1, 1, 1, 1)
            )
            restore_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(32) * scale_factor)
            restore_layout.add_widget(restore_btn)
            content.add_widget(restore_layout)

            popup = Popup(
                title='',
                content=outer,
                size_hint=(None, None),
                size=(popup_w, popup_h),
                auto_dismiss=True,
                separator_height=0,
                background=''
            )

            for btn, option_name, price, option_type in purchase_buttons:
                def make_purchase(instance, opt=option_name, pr=price, typ=option_type):
                    try:
                        self._play_button_click_sound()
                        if typ == "premium":
                            self.show_purchase_confirmation("Premium Unlock", pr, self.purchase_premium, popup)
                        else:
                            self.show_purchase_confirmation(opt, pr, lambda p=opt: self.purchase_hints(p), popup)
                    except Exception as e:
                        import traceback
                        tb = traceback.format_exc()
                        print(f"[ERROR] hint popup purchase action failed: {e}\\n{tb}")
                btn.bind(on_release=make_purchase)

            def close_popup(instance):
                self._play_button_click_sound()
                popup.dismiss()

            close_btn.bind(on_release=close_popup)

            def _restore_click(instance):
                try:
                    self.restore_purchases(popup)
                except Exception as e:
                    import traceback
                    tb = traceback.format_exc()
                    print(f"[ERROR] restore_purchases failed: {e}\\n{tb}")
                    try:
                        with open('/sdcard/sudoku_error.txt', 'w') as f:
                            f.write(tb)
                    except Exception:
                        pass
                    try:
                        from kivy.uix.popup import Popup
                        from kivy.uix.label import Label
                        err = Popup(title='Restore Error', content=Label(text='Unable to restore purchases at this time.'), size_hint=(None, None), size=(dp(320), dp(160)))
                        err.open()
                    except Exception:
                        pass

            restore_btn.bind(on_release=_restore_click)
            popup.open()
            print("[POPUP] Out of Hints popup opened successfully")

        except Exception as e:
            print(f"[POPUP] Error showing premium offer popup: {e}")
            import traceback
            traceback.print_exc()

    def show_stuck_popup(self):
        """Show 'Stuck?' popup offering hint purchases when user is truly blocked."""
        try:
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.label import Label
            from kivy.uix.button import Button
            from kivy.uix.popup import Popup
            from kivy.uix.anchorlayout import AnchorLayout
            from kivy.uix.widget import Widget
            from kivy.uix.floatlayout import FloatLayout
            from kivy.metrics import dp
            from kivy.graphics import Color, Rectangle, Line
            from kivy.core.window import Window

            def add_3d_silver_button_effect(btn):
                with btn.canvas.after:
                    Color(0.5, 0.5, 0.5, 1)
                    border = Line(rectangle=(btn.x, btn.y, btn.width, btn.height), width=1)
                    Color(0.95, 0.95, 0.95, 1)
                    highlight_top = Line(points=[btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height], width=2)
                    highlight_left = Line(points=[btn.x, btn.y, btn.x, btn.y + btn.height], width=2)
                    Color(0.45, 0.45, 0.45, 1)
                    shadow_bottom = Line(points=[btn.x, btn.y, btn.x + btn.width, btn.y], width=2)
                    shadow_right = Line(points=[btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height], width=2)

                def update(instance, *args):
                    border.rectangle = (btn.x, btn.y, btn.width, btn.height)
                    highlight_top.points = [btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height]
                    highlight_left.points = [btn.x, btn.y, btn.x, btn.y + btn.height]
                    shadow_bottom.points = [btn.x, btn.y, btn.x + btn.width, btn.y]
                    shadow_right.points = [btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height]

                btn.bind(pos=update, size=update)

            print("[STUCK] Showing Stuck? popup with hint offers")

            win_w, win_h = Window.width, Window.height
            scale_factor = min(win_w / 600.0, win_h / 850.0)
            scale_factor = max(0.5, min(1.5, scale_factor))
            popup_w = min(win_w * 0.92, dp(320) * scale_factor)
            popup_h = min(win_h * 0.75, dp(420) * scale_factor)

            # Outer white border shell
            outer = FloatLayout()
            with outer.canvas.before:
                Color(1, 1, 1, 1)
                outer_rect = Rectangle(size=outer.size, pos=outer.pos)
            outer.bind(size=lambda inst, val: setattr(outer_rect, 'size', val))
            outer.bind(pos=lambda inst, val: setattr(outer_rect, 'pos', val))

            # Tan body
            content = BoxLayout(
                orientation='vertical',
                padding=(dp(12) * scale_factor, dp(12) * scale_factor, dp(12) * scale_factor, dp(12) * scale_factor),
                spacing=dp(8) * scale_factor,
                size_hint=(0.97, 0.97),
                pos_hint={'center_x': 0.5, 'center_y': 0.5}
            )
            with content.canvas.before:
                Color(0.82, 0.71, 0.55, 1)
                bg_rect = Rectangle(size=content.size, pos=content.pos)
            content.bind(size=lambda inst, val: setattr(bg_rect, 'size', val))
            content.bind(pos=lambda inst, val: setattr(bg_rect, 'pos', val))
            outer.add_widget(content)

            # Header
            header_block = BoxLayout(
                orientation='vertical',
                size_hint=(1, None),
                height=dp(58) * scale_factor,
                spacing=dp(2) * scale_factor
            )

            title = Label(
                text="Stuck?",
                font_size=dp(24) * scale_factor,
                color=(0.15, 0.1, 0.05, 1),
                size_hint=(1, None),
                height=dp(28) * scale_factor,
                halign='center',
                valign='top',
                bold=True
            )
            title.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            header_block.add_widget(title)

            divider = Widget(size_hint=(0.6, None), height=dp(2) * scale_factor)
            with divider.canvas:
                Color(0.55, 0.4, 0.25, 1)
                div_rect = Rectangle(size=divider.size, pos=divider.pos)
            divider.bind(size=lambda inst, val: setattr(div_rect, 'size', val))
            divider.bind(pos=lambda inst, val: setattr(div_rect, 'pos', val))
            divider_anchor = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, None), height=dp(4) * scale_factor)
            divider_anchor.add_widget(divider)
            header_block.add_widget(divider_anchor)

            subtitle = Label(
                text="Get a hint to keep going",
                font_size=dp(11) * scale_factor,
                color=(0.5, 0.4, 0.28, 1),
                size_hint=(1, None),
                height=dp(24) * scale_factor,
                halign='center',
                valign='middle'
            )
            subtitle.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], val[1])))
            header_block.add_widget(subtitle)

            content.add_widget(header_block)

            # Message
            message = Label(
                text="Choose a hint pack:",
                font_size=dp(11) * scale_factor,
                color=(0.3, 0.25, 0.2, 1),
                size_hint=(1, None),
                height=dp(20) * scale_factor,
                halign='center',
                valign='top'
            )
            message.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
            content.add_widget(message)

            content.add_widget(Widget(size_hint_y=None, height=dp(2) * scale_factor))

            # Hint packs to offer
            hint_packs = [
                ("10 Hints", "$0.99"),
                ("50 Hints", "$1.99"),
                ("100 Hints", "$2.99")
            ]
            purchase_buttons = []

            for pack_name, price in hint_packs:
                row = BoxLayout(
                    orientation='horizontal',
                    size_hint_y=None,
                    height=dp(36) * scale_factor,
                    spacing=dp(6) * scale_factor
                )

                name_label = Label(
                    text=pack_name,
                    font_size=dp(12) * scale_factor,
                    color=(0.15, 0.1, 0.05, 1),
                    size_hint=(0.55, 1),
                    halign='left',
                    valign='middle'
                )
                name_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], val[1])))

                price_label = Label(
                    text=price,
                    font_size=dp(12) * scale_factor,
                    color=(0.0, 0.4, 0.0, 1),
                    size_hint=(0.2, 1),
                    halign='center',
                    valign='middle',
                    bold=True
                )

                buy_btn = Button(
                    text="Buy",
                    font_size=dp(12) * scale_factor,
                    size_hint=(0.25, 1),
                    background_color=(0.75, 0.75, 0.75, 1),
                    color=(0, 0, 0, 1),
                    background_normal='',
                    background_down=''
                )
                add_3d_silver_button_effect(buy_btn)
                purchase_buttons.append((buy_btn, pack_name, price))

                row.add_widget(name_label)
                row.add_widget(price_label)
                row.add_widget(buy_btn)
                content.add_widget(row)

            content.add_widget(Widget(size_hint_y=None, height=dp(4) * scale_factor))

            # Close button
            close_btn = Button(
                text="Keep Trying",
                font_size=dp(12) * scale_factor,
                size_hint=(None, None),
                size=(dp(100) * scale_factor, dp(32) * scale_factor),
                background_color=(0.75, 0.75, 0.75, 1),
                color=(0, 0, 0, 1),
                background_normal='',
                background_down=''
            )
            add_3d_silver_button_effect(close_btn)
            close_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(36) * scale_factor)
            close_layout.add_widget(close_btn)
            content.add_widget(close_layout)

            popup = Popup(
                title='',
                content=outer,
                size_hint=(None, None),
                size=(popup_w, popup_h),
                auto_dismiss=True,
                separator_height=0,
                background=''
            )

            # Bind purchase buttons
            for btn, pack_name, price in purchase_buttons:
                def make_purchase_callback(pname, pr):
                    def callback(instance):
                        try:
                            self._play_button_click_sound()
                            self.show_purchase_confirmation(pname, pr, lambda: self.purchase_hints(pname), popup)
                        except Exception as e:
                            print(f"[STUCK] Purchase action error: {e}")
                    return callback
                btn.bind(on_release=make_purchase_callback(pack_name, price))

            def close_popup(instance):
                self._play_button_click_sound()
                popup.dismiss()

            close_btn.bind(on_release=close_popup)

            popup.open()
            print("[STUCK] Stuck? popup opened successfully")

        except Exception as e:
            print(f"[STUCK] Error showing stuck popup: {e}")
            import traceback
            traceback.print_exc()

    def apply_dark_mode_theme(self):
        """Apply or remove dark mode theme to the puzzle screen"""
        if not hasattr(self, 'sudoku_board') or not self.sudoku_board:
            return  # No puzzle screen to theme
        
        # Apply theme to Sudoku board cells
        for row in range(9):
            for col in range(9):
                cell = self.sudoku_board.get_cell(row, col)
                if cell:
                    if self.settings_dark_mode:
                        # Dark mode colors
                        if cell.is_clue:
                            cell.background_color = (0.2, 0.2, 0.2, 1)  # Dark gray for clues
                            cell.color = (0.9, 0.9, 0.9, 1)  # Light gray text for clues
                        else:
                            if cell.text and cell.text != "0" and cell.text != "":  # User entry
                                cell.background_color = (0.15, 0.15, 0.15, 1)  # Darker gray for user entries
                                cell.color = (1.0, 1.0, 1.0, 1)  # White font for user entries
                            else:  # Empty cell
                                cell.background_color = (0.1, 0.1, 0.1, 1)  # Very dark gray for empty
                                cell.color = (0.9, 0.9, 0.9, 1)  # Light text
                        
                        # Update cell border colors for dark mode (tan borders become lighter)
                        if hasattr(cell, 'cell_border'):
                            with cell.canvas.after:
                                from kivy.graphics import Color
                                Color(0.6, 0.6, 0.6, 1)  # Light gray border
                                cell.cell_border.width = 1
                                Color(0.8, 0.8, 0.8, 1)  # Lighter highlight
                                if hasattr(cell, 'highlight_top'):
                                    cell.highlight_top.width = 2
                                if hasattr(cell, 'highlight_left'):
                                    cell.highlight_left.width = 2
                                Color(0.3, 0.3, 0.3, 1)  # Darker shadow
                                if hasattr(cell, 'shadow_bottom'):
                                    cell.shadow_bottom.width = 2
                                if hasattr(cell, 'shadow_right'):
                                    cell.shadow_right.width = 2
                    else:
                        # Light mode colors (original)
                        if cell.is_clue:
                            cell.background_color = (1, 1, 1, 1)  # White for clues
                            cell.color = (0, 0, 0, 1)  # Black text for clues
                        else:
                            if cell.text and cell.text != "0" and cell.text != "":  # User entry
                                cell.background_color = (1, 1, 1, 1)  # White for user entries
                                cell.color = (0.0, 0.3, 1.0, 1)  # Blue for user entries
                            else:  # Empty cell
                                cell.background_color = (1, 1, 1, 1)  # White for empty
                                cell.color = (0, 0, 0, 1)  # Black text
                        
                        # Restore original tan borders for light mode
                        if hasattr(cell, 'cell_border'):
                            with cell.canvas.after:
                                from kivy.graphics import Color
                                Color(0.82, 0.71, 0.55, 1)  # Tan color for main border
                                cell.cell_border.width = 1
                                Color(0.95, 0.85, 0.7, 1)  # Light tan for highlight
                                if hasattr(cell, 'highlight_top'):
                                    cell.highlight_top.width = 2
                                if hasattr(cell, 'highlight_left'):
                                    cell.highlight_left.width = 2
                                Color(0.6, 0.5, 0.35, 1)  # Dark tan for shadow
                                if hasattr(cell, 'shadow_bottom'):
                                    cell.shadow_bottom.width = 2
                                if hasattr(cell, 'shadow_right'):
                                    cell.shadow_right.width = 2
                    
                    # Update notes display to reflect the new theme
                    cell.update_notes_display()
        
        # Apply theme to digit buttons
        if hasattr(self, 'digit_buttons'):
            for btn in self.digit_buttons:
                if self.settings_dark_mode:
                    btn.background_color = (0.25, 0.25, 0.25, 1)  # Dark gray
                    btn.color = (0.9, 0.9, 0.9, 1)  # Light text
                else:
                    btn.background_color = (0.75, 0.75, 0.75, 1)  # Silver (original)
                    btn.color = (0, 0, 0, 1)  # Black text (original)
        
        # Apply theme to utility buttons (Auto-Solve, Hint, Back to Menu)
        utility_buttons = []
        if hasattr(self, 'auto_btn') and self.auto_btn:
            utility_buttons.append(self.auto_btn)
        if hasattr(self, 'hint_btn') and self.hint_btn:
            utility_buttons.append(self.hint_btn)
        if hasattr(self, 'back_btn') and self.back_btn:
            utility_buttons.append(self.back_btn)
        
        for btn in utility_buttons:
            if self.settings_dark_mode:
                btn.background_color = (0.3, 0.3, 0.3, 1)  # Slightly lighter dark gray for utility buttons
                btn.color = (0.9, 0.9, 0.9, 1)  # Light text
            else:
                btn.background_color = (0.75, 0.75, 0.75, 1)  # Silver (original)
                btn.color = (0, 0, 0, 1)  # Black text (original)
        
        # Apply theme to labels
        if hasattr(self, 'mistake_label') and self.mistake_label:
            if self.settings_dark_mode:
                self.mistake_label.color = (0.9, 0.7, 0.7, 1)  # Light red for dark mode
            else:
                self.mistake_label.color = (1, 1, 1, 1)  # White (original)
        
        if hasattr(self, 'clock_label') and self.clock_label:
            # Preserve dark tan color for Evil level, otherwise apply theme
            if hasattr(self, 'last_difficulty') and self.last_difficulty == 'Evil':
                self.clock_label.color = (0.6, 0.5, 0.35, 1)  # Keep dark tan for Evil
            elif self.settings_dark_mode:
                self.clock_label.color = (0.7, 0.8, 0.9, 1)  # Light blue for dark mode
            else:
                self.clock_label.color = (1, 1, 1, 1)  # White (original)
        
        print(f"[DARK_MODE] Applied theme - dark mode: {self.settings_dark_mode}")

    def _build_puzzle_screen_direct(self, difficulty):
        """Build the puzzle screen directly without difficulty checks (for async generation)."""
        print(f"[DIRECT] Building puzzle screen directly for {difficulty}")
        
        # Simply call build_puzzle_screen with a flag to skip the difficulty check
        # Set a temporary flag to indicate this is a direct call (skip async generation check)
        self._skip_async_check = True
        try:
            result = self.build_puzzle_screen(difficulty, resume=False)
            return result
        finally:
            self._skip_async_check = False

    def build_puzzle_screen(self, difficulty, resume=False):
        # Determine if hints are supported for this difficulty
        difficulty_supports_hints = difficulty in ("Easy", "Normal", "Tough")
        # Clear any lingering graphics from welcome screen (fixes transparent artifact)
        if hasattr(self, 'difficulty_buttons'):
            for btn in self.difficulty_buttons:
                try:
                    btn.canvas.after.clear()
                    if hasattr(btn, '_depressed_overlay'):
                        btn._depressed_overlay = None
                except Exception:
                    pass
        # Stop any previous music/sounds first
        try:
            if hasattr(self, '_music') and self._music:
                self._music.stop()
                self._music.unload()
        except Exception:
            pass
        # Make sure all other sounds are stopped too
        try:
            if hasattr(self, '_game_over_sound') and self._game_over_sound:
                self._game_over_sound.stop()
        except Exception:
            pass
        # Play music for this difficulty (only if music setting is enabled)
        # Don't interrupt reward/game over sounds
        self._reward_screen_showing = False
        if self.settings_music:
            import os as _os
            from kivy.core.audio import SoundLoader
            music_file = resource_path(f"Sounds/{str(difficulty).lower()}.mp3")
            abs_path = _os.path.abspath(music_file)
            print(f"[MUSIC] Attempting to load: {abs_path}")

            # Packaged .exe: try native Windows audio first (Kivy/GStreamer can't
            # decode MP3s reliably in PyInstaller builds, same fix as welcome music)
            if hasattr(sys, '_MEIPASS') and self._supports_native_windows_audio():
                self._native_audio_stop('serene_music')  # clear any previous alias
                if self._native_audio_play_file(abs_path, 'serene_music', loop=True):
                    self._native_music = True
                    self._native_welcome_music = False
                    print(f"[MUSIC] Native Windows audio playing game music: {abs_path}")
                else:
                    print(f"[MUSIC] Native Windows audio failed for packaged build: {abs_path}")
            else:
                # Non-packaged run: use SoundLoader as primary
                self._music = SoundLoader.load(music_file)
                if self._music:
                    print(f"[MUSIC] Loaded and playing: {music_file}")
                    self._music.loop = True
                    self._music.play()
                    # Kivy loaded but didn't actually start (common desktop edge case)
                    if getattr(self._music, 'state', None) != 'play' and self._supports_native_windows_audio():
                        print(f"[MUSIC] Kivy failed to start playback; using native Windows audio")
                        self._music = None
                        self._native_audio_stop('serene_music')
                        if self._native_audio_play_file(abs_path, 'serene_music', loop=True):
                            self._native_music = True
                            print(f"[MUSIC] Native Windows audio playing game music: {abs_path}")
                else:
                    print(f"[MUSIC] SoundLoader failed to load: {music_file}")
                    if self._supports_native_windows_audio():
                        self._native_audio_stop('serene_music')
                        if self._native_audio_play_file(abs_path, 'serene_music', loop=True):
                            self._native_music = True
                            print(f"[MUSIC] Native Windows audio fallback: {abs_path}")
                        else:
                            print(f"[MUSIC] Native Windows audio fallback failed: {abs_path}")
                    elif self._supports_pygame_fallback():
                        try:
                            import pygame
                            if not getattr(self, '_pygame_inited', False):
                                pygame.mixer.init()
                                self._pygame_inited = True
                            pygame.mixer.music.load(abs_path)
                            pygame.mixer.music.play(-1)
                            self._pygame_music = True
                            print(f"[MUSIC] Pygame playing game music: {abs_path}")
                        except Exception as e:
                            print(f"[MUSIC] Pygame fallback failed: {e}")
        else:
            print(f"[MUSIC] Music disabled in settings")
        # This is your original build() logic for the puzzle UI.
        from kivy.uix.image import Image
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.metrics import dp
        from kivy.utils import platform
        from kivy.core.window import Window
        from kivy.uix.widget import Widget
        Window.clearcolor = (0.05, 0.25, 0.08, 1)  # Dark green
        # Window stays maximized on desktop; no manual resize needed
        if False:
            pass
        else:
            print("[WINDOW] Keeping window size as set by welcome screen (600x850)")
        # Reset game state variables (will be overridden if resuming)
        self.selected_cell = None
        self.mistake_count = 0
        self.start_time = time.time()
        self._fail_screen_active = False
        if resume and self.last_game_state and self.last_game_state.get('difficulty') == difficulty:
            print(f"[RESUME] Resuming game with difficulty {difficulty}")
            print(f"[RESUME] Debug - resume={resume}, last_game_state exists={self.last_game_state is not None}")
            if self.last_game_state:
                print(f"[RESUME] Debug - saved difficulty={self.last_game_state.get('difficulty')}, current difficulty={difficulty}")
                print(f"[RESUME] Debug - difficulty match={self.last_game_state.get('difficulty') == difficulty}")
            puzzle = self.last_game_state.get('puzzle')
            solution = self.last_game_state.get('solution')
            board = self.last_game_state.get('board')
            saved_puzzle_id = self.last_game_state.get('puzzle_id', 'UNKNOWN')
            print(f"[RESUME] Loaded puzzle ID: {saved_puzzle_id}")
            print(f"[RESUME] Loaded puzzle first row: {puzzle[0] if puzzle else 'None'}")
            print(f"[RESUME] Loaded solution first row: {solution[0] if solution else 'None'}")
            print(f"[RESUME] Puzzle type: {type(puzzle)}, length: {len(puzzle) if puzzle else 'None'}")
            # Log the entire first few rows for debugging
            if puzzle:
                for i in range(min(3, len(puzzle))):
                    print(f"[RESUME] Puzzle row {i}: {puzzle[i]}")
            
            # Create SudokuGameLogic - this may generate a puzzle that we need to override
            self.game = SudokuGameLogic(difficulty)
            
            # IMMEDIATELY override any auto-generated puzzle with our saved data
            print(f"[RESUME] BEFORE override - game puzzle first row: {self.game.puzzle[0] if hasattr(self.game, 'puzzle') and self.game.puzzle else 'None'}")
            self.game.puzzle = puzzle
            self.game.solution = solution
            self.game.board = board if board else [[0 for _ in range(9)] for _ in range(9)]
            print(f"[RESUME] AFTER override - game puzzle first row: {self.game.puzzle[0]}")
            print(f"[RESUME] AFTER override - game solution first row: {self.game.solution[0]}")
            
            # Verify puzzle ID matches
            import hashlib
            restored_puzzle_str = str(self.game.puzzle)
            restored_puzzle_id = hashlib.md5(restored_puzzle_str.encode()).hexdigest()[:8]
            print(f"[RESUME] Restored puzzle ID: {restored_puzzle_id}")
            print(f"[RESUME] Puzzle ID match: {saved_puzzle_id == restored_puzzle_id}")
            print(f"[RESUME] Game board initialized with saved state")
            
            # Restore saved game state
            self.mistake_count = self.last_game_state.get('mistake_count', 0)
            self.start_time = self.last_game_state.get('start_time', time.time())
            # If user navigated away from puzzle and is now resuming, adjust start_time to exclude the gap
            if hasattr(self, '_navigation_pause_time') and self._navigation_pause_time:
                navigation_gap = time.time() - self._navigation_pause_time
                self.start_time += navigation_gap  # Shift start_time forward to exclude gap from completion time
                print(f"[RESUME] Adjusted start_time by {navigation_gap:.1f}s to exclude navigation gap")
                self._navigation_pause_time = None  # Reset for next navigation
            # Convert action_history lists back to sets for prev_notes
            saved_actions = self.last_game_state.get('action_history', [])
            self.action_history = []
            for action in saved_actions:
                if len(action) >= 4 and isinstance(action[3], list):
                    # Convert the list back to set (prev_notes)
                    new_action = list(action)
                    new_action[3] = set(action[3])
                    if len(action) >= 5 and isinstance(action[4], list):
                        # Convert additional list if present
                        new_action[4] = set(action[4])
                    self.action_history.append(tuple(new_action))
                else:
                    self.action_history.append(action)
            self.auto_solve_timestamps = self.last_game_state.get('auto_solve_timestamps', [])
            
            # Restore hints remaining count for this specific puzzle
            saved_hints = self.last_game_state.get('hints_remaining')
            if saved_hints is not None:
                self.hints_remaining = saved_hints
                print(f"[RESUME] Restored hints_remaining: {self.hints_remaining}")
            else:
                # Fallback: free users start with 10 hints if not saved
                self.hints_remaining = 10
                print(f"[RESUME] No saved hints_remaining, using default: {self.hints_remaining}")
            
            print(f"[RESUME] Restored: mistakes={self.mistake_count}, actions={len(self.action_history)}, hints={self.hints_remaining}")
            print(f"[RESUME] Game puzzle first row: {self.game.puzzle[0] if hasattr(self.game, 'puzzle') and self.game.puzzle else 'None'}")
        else:
            print(f"[NEW GAME] Starting new game with difficulty {difficulty}")
            print(f"[NEW GAME] Debug - resume={resume}, last_game_state exists={self.last_game_state is not None}")
            if self.last_game_state:
                print(f"[NEW GAME] Debug - saved difficulty={self.last_game_state.get('difficulty')}, current difficulty={difficulty}")
                print(f"[NEW GAME] Debug - difficulty match={self.last_game_state.get('difficulty') == difficulty}")
            
            # For Diabolical, generate asynchronously to prevent UI hang
            # UNLESS we're being called from the async completion handler (skip_async_check flag)
            if str(difficulty).lower() == "diabolical" and not getattr(self, '_skip_async_check', False):
                # Return a loading screen widget immediately while puzzle generates in background
                return self.create_loading_widget_and_start_async_generation(difficulty)
            else:
                # For all other puzzles, generate synchronously (fast enough)
                # OR for async-completed difficult puzzles (game already set up)
                if not hasattr(self, 'game') or not hasattr(self.game, 'puzzle'):
                    # Only generate if we don't already have a game (async case has already set it up)
                    self.game = SudokuGameLogic(difficulty)
                    puzzle, solution = self.game.generate_puzzle()
                    print(f"[NEW GAME] Generated puzzle first row: {puzzle[0] if puzzle else 'None'}")
                    print(f"[NEW GAME] Generated solution first row: {solution[0] if solution else 'None'}")
                    # Ensure the game object has puzzle and solution attributes
                    self.game.puzzle = puzzle
                    self.game.solution = solution
                else:
                    print(f"[NEW GAME] Using existing game object from async generation")
                    # Get puzzle and solution from the existing game object
                    puzzle = self.game.puzzle
                    solution = self.game.solution
                board = None
                # Don't reset hints for new games - hints persist across games
                # Only initialize if not already set
                if not hasattr(self, 'hints_remaining'):
                    self.hints_remaining = 10
                    print(f"[NEW GAME] Initialized hints_remaining: {self.hints_remaining}")
                else:
                    print(f"[NEW GAME] Using existing hints_remaining: {self.hints_remaining}")
                # Save new game state as in-progress
                self.last_game_in_progress = True
                self._save_last_game(puzzle, solution, self.game.board, difficulty, True)

        # Use FloatLayout to layer background, UI, and settings icon with absolute positioning
        from kivy.uix.floatlayout import FloatLayout
        root = FloatLayout()
        
        # Set background (animated GIF if available, fallback to PNG), with Android support
        from kivy.uix.image import Image
        from kivy.core.image import Image as CoreImage
        import os
        # Always resolve image paths relative to the directory of main.py
        project_dir = os.path.dirname(os.path.abspath(__file__))
        # Use relative paths for Android compatibility
        from kivy.utils import platform
        # determine candidate filenames, but do *not* hard-code the final path
        # here; we'll run them through resource_path() so that install_time_assets
        # migrates work automatically on all platforms.
        # use relative paths everywhere so that resource_path() can
        # correctly swap to install_time_assets when the file has been
        # relocated.  Android already prefers relative names, but we
        # previously built absolute paths on desktop which prevented the
        # helper from finding moved assets.
        bg_files = {
            "easy": ("Images/easy.gif", "Images/easy.png"),
            "moderate": ("Images/bamboo_zen_garden.gif", "Images/bamboo_zen_garden.png"),
            "tough": ("Images/bonsai_zen_garden.gif", "Images/bonsai_zen_garden.png"),
            "expert": ("Images/bridge_lanterns.gif", "Images/bridge_lanterns.png"),
            "evil": ("Images/stone_garden.gif", "Images/stone_garden.png"),
            "diabolical": ("Images/diabolical_level.gif", None),
        }
        diff_key = str(difficulty).lower()
        gif_path, png_path = bg_files.get(diff_key, (None, None))
        # video only used for diabolical on desktop
        video_path = "Images/diabolical_level.mp4" if diff_key == "diabolical" else None
        # convert to resource paths to pick up install_time_assets fallback
        if gif_path:
            gif_path = resource_path(gif_path)
        if png_path:
            png_path = resource_path(png_path)
        if video_path:
            video_path = resource_path(video_path)
        bg_img = None
        def file_exists(path):
            if not path:
                return False
            if os.path.exists(path):
                return True
            # Try Android paths
            if platform == 'android':
                try:
                    import sys
                    # Try relative to sys.path[0] (app directory)
                    rel_path = os.path.relpath(path, project_dir)
                    android_path = os.path.join(sys.path[0], rel_path)
                    if os.path.exists(android_path):
                        return True
                    # Also try just the relative path
                    if os.path.exists(rel_path):
                        return True
                except Exception as e:
                    print(f"[DEBUG] Android path check failed: {e}")
            return False
        def get_best_path(path):
            if not path:
                return None
            if os.path.exists(path):
                return path
            if platform == 'android':
                try:
                    # On Android, files are in the app's private directory
                    import sys
                    # Try relative to sys.path[0] (app directory)
                    rel_path = os.path.relpath(path, project_dir)
                    android_path = os.path.join(sys.path[0], rel_path)
                    print(f"[DEBUG] Android trying path: {android_path}")
                    if os.path.exists(android_path):
                        return android_path
                    # Also try just the relative path
                    if os.path.exists(rel_path):
                        return rel_path
                except Exception as e:
                    print(f"[DEBUG] Android path get failed: {e}")
            return path  # fallback
        gif_path = get_best_path(gif_path)
        png_path = get_best_path(png_path)
        video_path = get_best_path(video_path)  # CRITICAL: Process video path through get_best_path
        print(f"[DEBUG] Checking for GIF: {gif_path}, exists: {file_exists(gif_path)}")
        print(f"[DEBUG] Checking for PNG: {png_path}, exists: {file_exists(png_path)}")
        print(f"[DEBUG] Checking for VIDEO: {video_path}, exists: {file_exists(video_path)}")
        try:
            bg_loaded = False
            # Try GIF first for all difficulties (including Diabolical on Android)
            if gif_path and file_exists(gif_path):
                print(f"[BACKGROUND] Animated GIF candidate: {gif_path}")
                try:
                    bg_img = Image(source=gif_path, allow_stretch=True, keep_ratio=False, size_hint=(1, 1), pos_hint={'x': 0, 'y': 0}, anim_delay=0.08)
                    root.add_widget(bg_img)
                    bg_loaded = True
                    print(f"[DEBUG] Kivy Image widget loaded GIF: {gif_path}")
                except Exception as e:
                    print(f"[DEBUG] Kivy Image widget failed for GIF: {e}")
                    bg_loaded = False
            
            # Try PNG fallback if GIF didn't load
            if not bg_loaded and png_path and file_exists(png_path):
                print(f"[BACKGROUND] GIF failed/missing, using static PNG: {png_path}")
                try:
                    bg_img = Image(source=png_path, allow_stretch=True, keep_ratio=False, size_hint=(1, 1), pos_hint={'x': 0, 'y': 0})
                    root.add_widget(bg_img)
                    bg_loaded = True
                except Exception as e:
                    print(f"[DEBUG] PNG also failed: {e}")
                    bg_loaded = False
            
            # Green fallback if no background loaded (especially for Diabolical which has no PNG)
            if not bg_loaded:
                print(f"[BACKGROUND] No image loaded, using green fallback for {difficulty}")
                from kivy.graphics import Color, Rectangle
                with root.canvas.before:
                    Color(0, 0.5, 0, 1)  # Dark green fallback
                    green_bg = Rectangle(size=root.size, pos=root.pos)
                root.bind(size=lambda inst, val: setattr(green_bg, 'size', val))
                root.bind(pos=lambda inst, val: setattr(green_bg, 'pos', val))
        except Exception as e:
            print(f"[BACKGROUND] Error loading background: {e}")
            # Emergency green fallback
            from kivy.graphics import Color, Rectangle
            with root.canvas.before:
                Color(0, 0.5, 0, 1)
                green_bg = Rectangle(size=root.size, pos=root.pos)
            root.bind(size=lambda inst, val: setattr(green_bg, 'size', val))
            root.bind(pos=lambda inst, val: setattr(green_bg, 'pos', val))

        # Container for the main UI (centered)
        ui_container = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, 1), pos_hint={'x': 0, 'y': 0})
        # Add padding for Android system bars so content is not hidden
        nav_bar_pad = get_nav_bar_height()
        status_bar_pad = get_status_bar_height()
        main_layout = BoxLayout(orientation='vertical', padding=[0, dp(2) + status_bar_pad, 0, nav_bar_pad])  # top + bottom padding for system bars

        # Top bar with mistake counter flush to top right, minimal vertical space
        top_bar = BoxLayout(size_hint_y=None, height=dp(28), orientation='horizontal', padding=[0,0,dp(30),0])
        top_bar.add_widget(BoxLayout())  # Left spacer (fills space)
        self.mistake_label = Label(
            text="Mistakes: 0",
            font_size=dp(17),
            color=(1, 1, 1, 1),
            size_hint=(None, None),
            size=(dp(120), dp(20)),
            halign='right',
            valign='middle',
            opacity=1.0 if self.settings_check_mistakes else 0.0  # Hide if mistake checking is off
        )
        self.mistake_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], val[1])))
        # Update mistake label with restored count
        self.mistake_label.text = f"Mistakes: {self.mistake_count}"
        top_bar.add_widget(self.mistake_label)
        main_layout.add_widget(top_bar)
        
        # Clock label above difficulty (only visible if settings allow)
        self.clock_label = Label(
            text="00:00",
            font_size=dp(16),
            color=(1, 1, 1, 1),
            size_hint=(1, None),
            height=dp(24),
            halign='center',
            valign='middle',
            opacity=1.0 if self.settings_show_clock else 0.0  # Hide if show clock is off
        )
        # For Evil level, make clock bold and dark tan (internal box line color) so it's visible on white background
        if difficulty == 'Evil':
            self.clock_label.bold = True
            self.clock_label.color = (0.6, 0.5, 0.35, 1)  # Dark tan matching internal box lines
        self.clock_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
        main_layout.add_widget(self.clock_label)
        
        # Start clock update if enabled
        if self.settings_show_clock:
            self._start_clock_updates()
        
        # Japanese translations for difficulty names
        japanese_translations = {
            "Easy": "易しい",
            "Moderate": "中級",
            "Tough": "難しい",
            "Expert": "エキスパート",
            "Evil": "悪",
            "Diabolical": "極悪"
        }
        
        # English difficulty name label, centered
        difficulty_label_en = Label(
            text=str(difficulty),
            font_size=dp(22),
            color=(1, 1, 1, 1),
            size_hint=(1, None),
            height=dp(24),
            halign='center',
            valign='top'
        )
        difficulty_label_en.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
        main_layout.add_widget(difficulty_label_en)
        
        # Japanese difficulty name label, centered underneath
        japanese_text = japanese_translations.get(str(difficulty), str(difficulty))
        difficulty_label_jp = Label(
            text=japanese_text,
            font_size=dp(18),
            font_name="msgothic",  # Use registered font name, not file path
            color=(0.9, 0.9, 0.9, 1),  # Slightly dimmer than English
            size_hint=(1, None),
            height=dp(28),
            halign='center',
            valign='top'
        )
        difficulty_label_jp.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
        main_layout.add_widget(difficulty_label_jp)

        # Add spacer after difficulty labels to move text UP and keep board position constant
        main_layout.add_widget(BoxLayout(size_hint_y=None, height=dp(12)))

        from kivy.uix.anchorlayout import AnchorLayout

        board_container = AnchorLayout(size_hint=(1, 1))
        self.sudoku_board = SudokuBoard(app=self)
        board_container.add_widget(self.sudoku_board)
        # Ensure the board resizes when the parent (container) size changes
        def update_board_size_on_parent(*args):
            self.sudoku_board._update_square_size()
        board_container.bind(size=update_board_size_on_parent)

        main_layout.add_widget(board_container)
        main_layout.add_widget(BoxLayout(size_hint_y=None, height=dp(20)))  # Gap

        # --- Board setup and restore logic (must be inside method) ---
        # Set puzzle and restore user entries if resuming
        print(f"[BOARD] Setting puzzle on board - first row: {self.game.puzzle[0] if hasattr(self.game, 'puzzle') and self.game.puzzle else 'None'}")
        self.sudoku_board.set_puzzle(self.game.puzzle, self.game.solution)
        
        # Verify what was actually set on the board
        if hasattr(self.sudoku_board, 'puzzle'):
            print(f"[BOARD] Sudoku board puzzle after set_puzzle: {self.sudoku_board.puzzle[0] if self.sudoku_board.puzzle else 'None'}")
        
        # Check a few cells to see what's actually displayed
        print(f"[BOARD] Cell (0,0) text: '{self.sudoku_board.get_cell(0, 0).text}' if cell exists")
        print(f"[BOARD] Cell (0,1) text: '{self.sudoku_board.get_cell(0, 1).text}' if cell exists")
        
        if resume and self.last_game_state:
            print(f"[RESTORE] Restoring board state...")
            # Restore user digits from the saved board state
            saved_board = self.last_game_state.get('board')
            saved_puzzle = self.last_game_state.get('puzzle')
            restored_digits = 0
            if saved_board and saved_puzzle:
                for r in range(9):
                    for c in range(9):
                        val = saved_board[r][c]
                        cell = self.sudoku_board.get_cell(r, c)
                        # Get mistake_cells from save (list of [r, c])
                        mistake_cells = self.last_game_state.get('mistake_cells', [])
                        is_mistake_cell = [r, c] in mistake_cells
                        if saved_puzzle[r][c] == 0:
                            if is_mistake_cell:
                                # Do not restore digit for mistake cells; clear them
                                cell.text = ""
                                cell.clear_notes()
                                if hasattr(cell, 'clear_mistake'):
                                    cell.clear_mistake()
                                self.game.board[r][c] = 0
                            elif val != 0:
                                cell.restore_user_value(val)
                                # Also update the game logic board
                                self.game.board[r][c] = val
                                restored_digits += 1
                            else:
                                # Ensure cell is empty if board value is 0
                                cell.text = ""
                                cell.clear_notes()
                                self.game.board[r][c] = 0
            print(f"[RESTORE] Restored {restored_digits} user digits and cleared empty cells")
            
            # Restore notes if available
            notes_data = self.last_game_state.get('notes_data', {})
            restored_notes = 0
            for position, note_list in notes_data.items():
                r, c = map(int, position.split(','))
                cell = self.sudoku_board.get_cell(r, c)
                if cell and note_list:
                    for digit in note_list:
                        cell.add_note(digit)
                        restored_notes += 1
            print(f"[RESTORE] Restored {restored_notes} notes across {len(notes_data)} cells")

        from kivy.uix.image import Image
        # Create vertical container for two digit rows
        digit_container = BoxLayout(
            orientation='vertical',
            size_hint_y=None,
            height=dp(120),
            spacing=dp(8)
        )
        
        # First row: digits 1-5 (centered with flexible spacers)
        digit_row1_container = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(56)
        )
        digit_row1_container.add_widget(BoxLayout())  # Left spacer
        digit_row1 = BoxLayout(
            orientation='horizontal',
            size_hint=(None, None),
            height=dp(56),
            spacing=dp(8)
        )
        
        # Second row: digits 6-9 (centered with flexible spacers)
        digit_row2_container = BoxLayout(
            orientation='horizontal',
            size_hint_y=None,
            height=dp(56)
        )
        digit_row2_container.add_widget(BoxLayout())  # Left spacer
        digit_row2 = BoxLayout(
            orientation='horizontal',
            size_hint=(None, None),
            height=dp(56),
            spacing=dp(8)
        )
        
        self.digit_buttons = []
        self.padlock_imgs = [None]*9
        
        # Create buttons for first row (1-5)
        for i in range(1, 6):
            btn = DigitButton(i)
            # Override the dynamic sizing to ensure consistent spacing
            btn.size = (dp(40), dp(40))
            btn.size_hint = (None, None)
            btn.index = i-1
            btn._touch_time = None
            def on_touch_down(instance, touch, b=btn):
                if b.collide_point(*touch.pos):
                    b._touch_time = touch.time_start
            def on_touch_up(instance, touch, b=btn, idx=i-1):
                if b.collide_point(*touch.pos) and b._touch_time:
                    duration = time.time() - b._touch_time
                    if duration > 0.5:
                        self.toggle_digit_lock(b.digit, idx)
                    b._touch_time = None
            btn.bind(on_touch_down=on_touch_down)
            btn.bind(on_touch_up=on_touch_up)
            self.digit_buttons.append(btn)
            # Safe image loading with error handling for Android
            try:
                padlock = Image(source=resource_path('Images/stone_cold_digit_lock.png'), size_hint=(None, None), size=(dp(26), dp(26)), opacity=0, allow_stretch=True, keep_ratio=True)
                self.padlock_imgs[i-1] = padlock
            except Exception as e:
                print(f"Failed to load padlock image: {e}")
                # Create a blank image as fallback
                padlock = Image(size_hint=(None, None), size=(dp(26), dp(26)), opacity=0)
                self.padlock_imgs[i-1] = padlock
            padlock_layout = BoxLayout(orientation='vertical', size_hint=(None, None), size=(dp(40), dp(56)), padding=[0, 0, 0, 0], spacing=0)
            padlock_layout.add_widget(BoxLayout(size_hint=(1, None), height=dp(4)))
            padlock_box = BoxLayout(size_hint=(1, None), height=dp(28), padding=[0, 0, 0, 0])
            padlock_box.add_widget(BoxLayout(size_hint=(None, 1), width=dp(7)))
            padlock_box.add_widget(padlock)
            padlock_box.add_widget(BoxLayout(size_hint=(None, 1), width=dp(7)))
            padlock_layout.add_widget(padlock_box)
            padlock_layout.add_widget(BoxLayout(size_hint=(1, None), height=dp(4)))
            padlock_layout.add_widget(btn)
            digit_row1.add_widget(padlock_layout)
            
        # Create buttons for second row (6-9)
        for i in range(6, 10):
            btn = DigitButton(i)
            # Override the dynamic sizing to ensure consistent spacing
            btn.size = (dp(40), dp(40))
            btn.size_hint = (None, None)
            btn.index = i-1
            btn._touch_time = None
            def on_touch_down(instance, touch, b=btn):
                if b.collide_point(*touch.pos):
                    b._touch_time = touch.time_start
            def on_touch_up(instance, touch, b=btn, idx=i-1):
                if b.collide_point(*touch.pos) and b._touch_time:
                    duration = time.time() - b._touch_time
                    if duration > 0.5:
                        self.toggle_digit_lock(b.digit, idx)
                    b._touch_time = None
            btn.bind(on_touch_down=on_touch_down)
            btn.bind(on_touch_up=on_touch_up)
            self.digit_buttons.append(btn)
            # Safe image loading with error handling for Android
            try:
                padlock = Image(source=resource_path('Images/stone_cold_digit_lock.png'), size_hint=(None, None), size=(dp(26), dp(26)), opacity=0, allow_stretch=True, keep_ratio=True)
                self.padlock_imgs[i-1] = padlock
            except Exception as e:
                print(f"Failed to load padlock image: {e}")
                # Create a blank image as fallback
                padlock = Image(size_hint=(None, None), size=(dp(26), dp(26)), opacity=0)
                self.padlock_imgs[i-1] = padlock
            padlock_layout = BoxLayout(orientation='vertical', size_hint=(None, None), size=(dp(40), dp(56)), padding=[0, 0, 0, 0], spacing=0)
            padlock_layout.add_widget(BoxLayout(size_hint=(1, None), height=dp(4)))
            padlock_box = BoxLayout(size_hint=(1, None), height=dp(28), padding=[0, 0, 0, 0])
            padlock_box.add_widget(BoxLayout(size_hint=(None, 1), width=dp(7)))
            padlock_box.add_widget(padlock)
            padlock_box.add_widget(BoxLayout(size_hint=(None, 1), width=dp(7)))
            padlock_layout.add_widget(padlock_box)
            padlock_layout.add_widget(BoxLayout(size_hint=(1, None), height=dp(4)))
            padlock_layout.add_widget(btn)
            digit_row2.add_widget(padlock_layout)
            
        # Set widths based on actual content (5 buttons * 40dp + 4 spacings * 8dp = 232dp for row 1)
        # (4 buttons * 40dp + 3 spacings * 8dp = 184dp for row 2)
        digit_row1.width = 5 * dp(40) + 4 * dp(8)  # 232dp
        digit_row2.width = 4 * dp(40) + 3 * dp(8)  # 184dp
            
        # Add rows to their containers with centering spacers, then add containers to main container
        digit_row1_container.add_widget(digit_row1)
        digit_row1_container.add_widget(BoxLayout())  # Right spacer
        digit_row2_container.add_widget(digit_row2)
        digit_row2_container.add_widget(BoxLayout())  # Right spacer
        digit_container.add_widget(digit_row1_container)
        digit_container.add_widget(digit_row2_container)
        main_layout.add_widget(digit_container)
        # Responsive icon row: Notes, Erase, Undo (centered)
        icon_row = BoxLayout(orientation='horizontal', spacing=dp(16), size_hint_y=None, height=dp(60))
        self.notes_mode = False
        notes_layout = BoxLayout(size_hint=(None, None), size=(dp(100), dp(44)))
        # Use resource_path for Android compatibility
        pencil_img_path = resource_path('Images/pencil.png')
        print(f"[DEBUG] Loading pencil image from: {pencil_img_path}")
        pencil_img = Image(source=pencil_img_path, allow_stretch=True, keep_ratio=True)
            
        def pencil_touch(instance, touch):
            if pencil_img.collide_point(*touch.pos):
                self._play_pencil_click_sound()
                self.toggle_notes_mode(pencil_img)
                return True
            return False
        pencil_img.bind(on_touch_down=pencil_touch)
        notes_layout.add_widget(pencil_img)
        
        # Add 3D embossed effect that follows the actual image bounds (not container)
        from kivy.graphics import Color, Line
        with pencil_img.canvas.after:
            Color(0.9, 0.9, 0.9, 1)  # Light highlight
            pencil_img._highlight_top = Line(points=[0, 0, 0, 0], width=1.5)
            pencil_img._highlight_left = Line(points=[0, 0, 0, 0], width=1.5)
            Color(0.4, 0.4, 0.4, 1)  # Dark shadow
            pencil_img._shadow_bottom = Line(points=[0, 0, 0, 0], width=1.5)
            pencil_img._shadow_right = Line(points=[0, 0, 0, 0], width=1.5)
        def update_pencil_border(*args):
            if pencil_img.texture:
                # Calculate actual image bounds based on norm_image_size
                iw, ih = pencil_img.norm_image_size
                ix = pencil_img.center_x - iw / 2
                iy = pencil_img.center_y - ih / 2
                pencil_img._highlight_top.points = [ix, iy + ih, ix + iw, iy + ih]
                pencil_img._highlight_left.points = [ix, iy, ix, iy + ih]
                pencil_img._shadow_bottom.points = [ix, iy, ix + iw, iy]
                pencil_img._shadow_right.points = [ix + iw, iy, ix + iw, iy + ih]
        pencil_img.bind(pos=update_pencil_border, size=update_pencil_border, texture=update_pencil_border)

        clear_btn = Button(
            background_normal='',
            background_down='',
            background_color=(0, 0, 0, 0),
            size_hint=(None, None),
            size=(dp(100), dp(44))
        )
        eraser_img = Image(
            source=resource_path('Images/eraser.png'),
            allow_stretch=True,
            keep_ratio=True,
            size_hint=(1, 1)
        )
        def eraser_touch(instance, touch):
            if eraser_img.collide_point(*touch.pos):
                self._play_button_click_sound()
                self.clear_selected_cell(eraser_img)
                return True
            return False
        eraser_img.bind(on_touch_down=eraser_touch)
        clear_layout = AnchorLayout(size_hint=(None, None), size=(dp(100), dp(44)))
        clear_layout.add_widget(clear_btn)
        clear_layout.add_widget(eraser_img)
        
        # Add 3D embossed effect that follows the actual image bounds
        with eraser_img.canvas.after:
            Color(0.9, 0.9, 0.9, 1)  # Light highlight
            eraser_img._highlight_top = Line(points=[0, 0, 0, 0], width=1.5)
            eraser_img._highlight_left = Line(points=[0, 0, 0, 0], width=1.5)
            Color(0.4, 0.4, 0.4, 1)  # Dark shadow
            eraser_img._shadow_bottom = Line(points=[0, 0, 0, 0], width=1.5)
            eraser_img._shadow_right = Line(points=[0, 0, 0, 0], width=1.5)
        def update_eraser_border(*args):
            if eraser_img.texture:
                iw, ih = eraser_img.norm_image_size
                ix = eraser_img.center_x - iw / 2
                iy = eraser_img.center_y - ih / 2
                eraser_img._highlight_top.points = [ix, iy + ih, ix + iw, iy + ih]
                eraser_img._highlight_left.points = [ix, iy, ix, iy + ih]
                eraser_img._shadow_bottom.points = [ix, iy, ix + iw, iy]
                eraser_img._shadow_right.points = [ix + iw, iy, ix + iw, iy + ih]
        eraser_img.bind(pos=update_eraser_border, size=update_eraser_border, texture=update_eraser_border)

        boomerang_img = Image(
            source=resource_path('Images/boomerang.png'),
            allow_stretch=True,
            keep_ratio=True,
            size_hint=(1, 1)
        )
        # Store reference to boomerang for reliable touch detection
        self.boomerang_img = boomerang_img
        
        # Use on_touch_down on the Image directly, same as pencil and eraser buttons
        # This ensures reliable touch detection on Android
        def boomerang_touch(instance, touch):
            if boomerang_img.collide_point(*touch.pos):
                self._play_undo_sound()
                self.undo_last_action(boomerang_img)
                return True
            return False
        boomerang_img.bind(on_touch_down=boomerang_touch)
        
        undo_layout = AnchorLayout(size_hint=(None, None), size=(dp(100), dp(44)))
        undo_layout.add_widget(boomerang_img)
        
        # Add 3D embossed effect that follows the actual image bounds
        with boomerang_img.canvas.after:
            Color(0.9, 0.9, 0.9, 1)  # Light highlight
            boomerang_img._highlight_top = Line(points=[0, 0, 0, 0], width=1.5)
            boomerang_img._highlight_left = Line(points=[0, 0, 0, 0], width=1.5)
            Color(0.4, 0.4, 0.4, 1)  # Dark shadow
            boomerang_img._shadow_bottom = Line(points=[0, 0, 0, 0], width=1.5)
            boomerang_img._shadow_right = Line(points=[0, 0, 0, 0], width=1.5)
        def update_boomerang_border(*args):
            if boomerang_img.texture:
                iw, ih = boomerang_img.norm_image_size
                ix = boomerang_img.center_x - iw / 2
                iy = boomerang_img.center_y - ih / 2
                boomerang_img._highlight_top.points = [ix, iy + ih, ix + iw, iy + ih]
                boomerang_img._highlight_left.points = [ix, iy, ix, iy + ih]
                boomerang_img._shadow_bottom.points = [ix, iy, ix + iw, iy]
                boomerang_img._shadow_right.points = [ix + iw, iy, ix + iw, iy + ih]
        boomerang_img.bind(pos=update_boomerang_border, size=update_boomerang_border, texture=update_boomerang_border)

        # Center all three icons
        icon_row.add_widget(BoxLayout(size_hint_x=1))
        icon_row.add_widget(notes_layout)
        icon_row.add_widget(clear_layout)
        icon_row.add_widget(undo_layout)
        icon_row.add_widget(BoxLayout(size_hint_x=1))
        main_layout.add_widget(icon_row)

        # Add space between action row and utility buttons
        main_layout.add_widget(BoxLayout(size_hint_y=None, height=dp(16)))

        # Utility buttons row: Auto-Solve, Hint, Back to Menu
        from kivy.metrics import dp
        # Create utility buttons first - Auto-Solve with remaining count
        has_premium = getattr(self, 'has_premium', False)
        unlimited_forever = getattr(self, 'unlimited_forever', False)
        unlimited_until = getattr(self, 'unlimited_until', None)
        auto_solve_credits = getattr(self, 'auto_solve_credits', 0)
        show_counts = getattr(self, 'settings_show_counts', False)
        
        # Determine auto-solve status text - use sp() for density-aware font size
        sub_font_size = int(sp(11))
        if not show_counts:
            auto_text = "Auto-Solve"
        elif has_premium or unlimited_forever:
            auto_text = f"Auto-Solve\n[size={sub_font_size}]Unlimited[/size]"
        elif unlimited_until:
            import datetime
            try:
                if datetime.datetime.now() < datetime.datetime.fromisoformat(unlimited_until):
                    auto_text = f"Auto-Solve\n[size={sub_font_size}]24h Pass[/size]"
                else:
                    auto_text = f"Auto-Solve\n[size={sub_font_size}]{auto_solve_credits} left[/size]"
            except:
                auto_text = f"Auto-Solve\n[size={sub_font_size}]{auto_solve_credits} left[/size]"
        elif auto_solve_credits > 0:
            auto_text = f"Auto-Solve\n[size={sub_font_size}]{auto_solve_credits} left[/size]"
        else:
            auto_text = f"Auto-Solve\n[size={sub_font_size}]1 free/day[/size]"
        
        auto_btn = Button(
            text=auto_text,
            markup=True,
            font_size=dp(16),
            size_hint=(None, None),
            size=(dp(120), dp(36)),
            background_color=(0.75, 0.75, 0.75, 1),
            background_normal='',
            background_down='',
            color=(0, 0, 0, 1),
            halign='center',
            valign='middle',
            line_height=0.8
        )
        auto_btn.bind(size=auto_btn.setter('text_size'))
        self.auto_btn = auto_btn
        from kivy.graphics import Color, Line
        with auto_btn.canvas.after:
            Color(0.5, 0.5, 0.5, 1)
            auto_btn._border = Line(rectangle=(auto_btn.x, auto_btn.y, auto_btn.width, auto_btn.height), width=1)
            Color(0.9, 0.9, 0.9, 1)
            auto_btn._highlight_top = Line(points=[auto_btn.x, auto_btn.y + auto_btn.height, auto_btn.x + auto_btn.width, auto_btn.y + auto_btn.height], width=2)
            auto_btn._highlight_left = Line(points=[auto_btn.x, auto_btn.y, auto_btn.x, auto_btn.y + auto_btn.height], width=2)
            Color(0.4, 0.4, 0.4, 1)
            auto_btn._shadow_bottom = Line(points=[auto_btn.x, auto_btn.y, auto_btn.x + auto_btn.width, auto_btn.y], width=2)
            auto_btn._shadow_right = Line(points=[auto_btn.x + auto_btn.width, auto_btn.y, auto_btn.x + auto_btn.width, auto_btn.y + auto_btn.height], width=2)
        def update_auto_btn_border(instance, *args):
            auto_btn._border.rectangle = (auto_btn.x, auto_btn.y, auto_btn.width, auto_btn.height)
            auto_btn._highlight_top.points = [auto_btn.x, auto_btn.y + auto_btn.height, auto_btn.x + auto_btn.width, auto_btn.y + auto_btn.height]
            auto_btn._highlight_left.points = [auto_btn.x, auto_btn.y, auto_btn.x, auto_btn.y + auto_btn.height]
            auto_btn._shadow_bottom.points = [auto_btn.x, auto_btn.y, auto_btn.x + auto_btn.width, auto_btn.y]
            auto_btn._shadow_right.points = [auto_btn.x + auto_btn.width, auto_btn.y, auto_btn.x + auto_btn.width, auto_btn.y + auto_btn.height]
        auto_btn.bind(pos=update_auto_btn_border, size=update_auto_btn_border)
        auto_btn.bind(on_release=self.auto_solve_puzzle)
        self.update_auto_solve_button_state()

        # Always create and add the Hint button with hints remaining count
        has_premium = getattr(self, 'has_premium', False)
        show_counts = getattr(self, 'settings_show_counts', False)
        hint_sub_font_size = int(sp(11))
        if not show_counts:
            hint_text = "Hint"
        elif has_premium:
            hint_text = f"Hint\n[size={hint_sub_font_size}]Unlimited[/size]"
        else:
            hint_text = f"Hint\n[size={hint_sub_font_size}]{self.global_hints_remaining} left[/size]"
        hint_btn = Button(
            text=hint_text,
            markup=True,
            font_size=dp(16),
            size_hint=(None, None),
            size=(dp(120), dp(36)),
            background_color=(0.75, 0.75, 0.75, 1),
            background_normal='',
            background_down='',
            color=(0, 0, 0, 1),
            halign='center',
            valign='middle',
            line_height=0.8
        )
        hint_btn.bind(size=hint_btn.setter('text_size'))
        self.hint_btn = hint_btn
        self.hint_btn.disabled = False
        with self.hint_btn.canvas.after:
            Color(0.5, 0.5, 0.5, 1)
            self.hint_btn._border = Line(rectangle=(self.hint_btn.x, self.hint_btn.y, self.hint_btn.width, self.hint_btn.height), width=1)
            Color(0.9, 0.9, 0.9, 1)
            self.hint_btn._highlight_top = Line(points=[self.hint_btn.x, self.hint_btn.y + self.hint_btn.height, self.hint_btn.x + self.hint_btn.width, self.hint_btn.y + self.hint_btn.height], width=2)
            self.hint_btn._highlight_left = Line(points=[self.hint_btn.x, self.hint_btn.y, self.hint_btn.x, self.hint_btn.y + self.hint_btn.height], width=2)
            Color(0.4, 0.4, 0.4, 1)
            self.hint_btn._shadow_bottom = Line(points=[self.hint_btn.x, self.hint_btn.y, self.hint_btn.x + self.hint_btn.width, self.hint_btn.y], width=2)
            self.hint_btn._shadow_right = Line(points=[self.hint_btn.x + self.hint_btn.width, self.hint_btn.y, self.hint_btn.x + self.hint_btn.width, self.hint_btn.y + self.hint_btn.height], width=2)
        def update_hint_btn_border(instance, *args):
            self.hint_btn._border.rectangle = (self.hint_btn.x, self.hint_btn.y, self.hint_btn.width, self.hint_btn.height)
            self.hint_btn._highlight_top.points = [self.hint_btn.x, self.hint_btn.y + self.hint_btn.height, self.hint_btn.x + self.hint_btn.width, self.hint_btn.y + self.hint_btn.height]
            self.hint_btn._highlight_left.points = [self.hint_btn.x, self.hint_btn.y, self.hint_btn.x, self.hint_btn.y + self.hint_btn.height]
            self.hint_btn._shadow_bottom.points = [self.hint_btn.x, self.hint_btn.y, self.hint_btn.x + self.hint_btn.width, self.hint_btn.y]
            self.hint_btn._shadow_right.points = [self.hint_btn.x + self.hint_btn.width, self.hint_btn.y, self.hint_btn.x + self.hint_btn.width, self.hint_btn.y + self.hint_btn.height]
        self.hint_btn.bind(pos=update_hint_btn_border, size=update_hint_btn_border)
        self.hint_btn.bind(on_release=self.use_hint)

        back_btn = Button(
            text="Back to Menu",
            font_size=dp(16),
            size_hint=(None, None),
            size=(dp(120), dp(32)),
            background_color=(0.75, 0.75, 0.75, 1),
            background_normal='',
            background_down='',
            color=(0, 0, 0, 1)
        )
        self.back_btn = back_btn
        with self.back_btn.canvas.after:
            Color(0.5, 0.5, 0.5, 1)
            self.back_btn._border = Line(rectangle=(self.back_btn.x, self.back_btn.y, self.back_btn.width, self.back_btn.height), width=1)
            Color(0.9, 0.9, 0.9, 1)
            self.back_btn._highlight_top = Line(points=[self.back_btn.x, self.back_btn.y + self.back_btn.height, self.back_btn.x + self.back_btn.width, self.back_btn.y + self.back_btn.height], width=2)
            self.back_btn._highlight_left = Line(points=[self.back_btn.x, self.back_btn.y, self.back_btn.x, self.back_btn.y + self.back_btn.height], width=2)
            Color(0.4, 0.4, 0.4, 1)
            self.back_btn._shadow_bottom = Line(points=[self.back_btn.x, self.back_btn.y, self.back_btn.x + self.back_btn.width, self.back_btn.y], width=2)
            self.back_btn._shadow_right = Line(points=[self.back_btn.x + self.back_btn.width, self.back_btn.y, self.back_btn.x + self.back_btn.width, self.back_btn.y + self.back_btn.height], width=2)
        def update_back_btn_border(instance, *args):
            self.back_btn._border.rectangle = (self.back_btn.x, self.back_btn.y, self.back_btn.width, self.back_btn.height)
            self.back_btn._highlight_top.points = [self.back_btn.x, self.back_btn.y + self.back_btn.height, self.back_btn.x + self.back_btn.width, self.back_btn.y + self.back_btn.height]
            self.back_btn._highlight_left.points = [self.back_btn.x, self.back_btn.y, self.back_btn.x, self.back_btn.y + self.back_btn.height]
            self.back_btn._shadow_bottom.points = [self.back_btn.x, self.back_btn.y, self.back_btn.x + self.back_btn.width, self.back_btn.y]
            self.back_btn._shadow_right.points = [self.back_btn.x + self.back_btn.width, self.back_btn.y, self.back_btn.x + self.back_btn.width, self.back_btn.y + self.back_btn.height]
        self.back_btn.bind(pos=update_back_btn_border, size=update_back_btn_border)
        def go_to_menu(instance):
            self._play_button_click_sound()
            if hasattr(self, 'game') and hasattr(self.game, 'puzzle') and hasattr(self.game, 'solution'):
                self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, self.last_game_in_progress)
                print(f"[MENU] Saved current game state before returning to menu (in_progress={self.last_game_in_progress})")
            if hasattr(self, '_music') and self._music:
                self._music.stop()
            self._stop_clock_updates()
            self._navigation_pause_time = time.time()  # Record pause when leaving puzzle
            self.root.clear_widgets()
            self.welcome_layout = self.build_welcome_screen()
            self.root.add_widget(self.welcome_layout)
        self.back_btn.bind(on_release=go_to_menu)

        # Now build the layout rows (fix indentation and ensure all code is inside the function)
        util_row1 = BoxLayout(orientation='horizontal', spacing=dp(16), size_hint_y=None, height=dp(44))
        util_row2 = BoxLayout(orientation='horizontal', spacing=dp(16), size_hint_y=None, height=dp(44))
        util_row1.add_widget(BoxLayout(size_hint_x=1))
        util_row1.add_widget(auto_btn)
        util_row1.add_widget(hint_btn)
        util_row1.add_widget(BoxLayout(size_hint_x=1))
        util_row2.add_widget(BoxLayout(size_hint_x=1))
        util_row2.add_widget(back_btn)
        util_row2.add_widget(BoxLayout(size_hint_x=1))
        main_layout.add_widget(util_row1)
        main_layout.add_widget(util_row2)
        # Add larger spacer below utility button row for bottom margin
        main_layout.add_widget(BoxLayout(size_hint_y=None, height=dp(60)))

        # Puzzle and solution already generated above; do not generate again here.

        # Add main layout to the centered UI container
        ui_container.add_widget(main_layout)
        root.add_widget(ui_container)

        # Add settings icon in lower-left corner with absolute positioning
        # Offset bottom icons above the Android navigation bar
        _nav_offset = get_nav_bar_height()
        settings_icon = Image(
            source=resource_path('Images/settings_icon.png'),
            size_hint=(None, None),
            size=(dp(36), dp(36)),  # Slightly smaller than digit buttons (was 40dp)
            pos=(dp(2), dp(2) + _nav_offset),  # Shifted up by nav bar height
            allow_stretch=True,
            keep_ratio=True
        )

        # Make settings icon clickable
        def settings_touch(instance, touch):
            if settings_icon.collide_point(*touch.pos):
                self._play_button_click_sound()
                self.show_settings_popup()
                return True
            return False
        settings_icon.bind(on_touch_down=settings_touch)

        root.add_widget(settings_icon)

        # Premium icon flush to the right of settings icon, 80% as tall
        # Only show if user has purchased premium
        if getattr(self, 'has_premium', False):
            # Settings icon is size=(dp(36), dp(36)) and pos=(dp(2), dp(2))
            from kivy.metrics import dp as dp_func
            prem_height = dp_func(26)  # 10% smaller than 29
            prem_width = dp_func(58)   # Wider aspect ratio, 10% smaller than ~64
            prem_x = dp_func(44)       # Added ~1mm gap from gear icon
            prem_y = dp_func(2) + _nav_offset
            print(f"[PREMIUM] size=({prem_width}, {prem_height}), x={prem_x}, y={prem_y}")
            premium_icon = Image(
                source=resource_path('Images/premium_icon.PNG'),
                size_hint=(None, None),
                size=(prem_width, prem_height),
                pos=(prem_x, prem_y),
                fit_mode='fill'
            )
            # Make premium icon clickable
            def premium_touch(instance, touch):
                if premium_icon.collide_point(*touch.pos):
                    self._play_button_click_sound()
                    self.show_premium_popup()
                    return True
                return False
            premium_icon.bind(on_touch_down=premium_touch)
            root.add_widget(premium_icon)

        # Shop icon (pagoda) in lower right - flush against bottom edge
        from kivy.core.window import Window as Win
        shop_icon = Image(
            source=resource_path('Images/ancient_stone_pagoda_store.png'),
            size_hint=(None, None),
            size=(dp(110), dp(110)),  # Reduced by 10% from dp(122)
            allow_stretch=True,
            keep_ratio=True
        )
        # Position flush against bottom-right corner, with negative y to counteract image padding
        shop_icon.pos = (Win.width - dp(110), dp(-15) + _nav_offset)
        # Update position when window resizes
        def update_shop_pos(*args):
            shop_icon.pos = (Win.width - dp(110), dp(-15) + _nav_offset)
        Win.bind(size=update_shop_pos)

        # Make shop icon clickable - shows Stats & Achievements for premium users, Shop for others
        def shop_touch(instance, touch):
            if shop_icon.collide_point(*touch.pos):
                self._play_button_click_sound()
                # Schedule on next frame to avoid blocking UI
                from kivy.clock import Clock
                if getattr(self, 'has_premium', False):
                    Clock.schedule_once(lambda dt: self.show_stats_achievements_screen(), 0)
                else:
                    Clock.schedule_once(lambda dt: self.show_shop_screen(), 0)
                return True
            return False
        shop_icon.bind(on_touch_down=shop_touch)

        root.add_widget(shop_icon)

        # Apply dark mode theme if enabled
        self.apply_dark_mode_theme()
        
        # Force refresh of all note displays after layout is complete
        # This ensures notes from resumed games display immediately when resuming in dark mode
        from kivy.clock import Clock
        def refresh_all_notes_display(*args):
            """Refresh note displays after cells are fully laid out"""
            if hasattr(self, 'sudoku_board') and self.sudoku_board:
                for row in range(9):
                    for col in range(9):
                        cell = self.sudoku_board.get_cell(row, col)
                        if cell and cell.notes:
                            cell.update_notes_display()
                print("[NOTES] Refreshed all note displays after layout completion")
        
        # Schedule on next frame to ensure layout is complete
        Clock.schedule_once(refresh_all_notes_display, 0.1)

        return root

    def auto_solve_puzzle(self, *args):
        """Fill the board with the solution and disable further input, with daily usage limit."""
        import datetime
        self._play_button_click_sound()
        
        # Premium users get unlimited auto-solves - bypass all limits
        if getattr(self, 'has_premium', False):
            print("[AUTO-SOLVE] Premium user - unlimited auto-solves")
        # Check daily limit and IAP status for non-premium users
        else:
            today = datetime.date.today().isoformat()
            
            # Reset count if it's a new day
            if self.auto_solve_date != today:
                self.auto_solve_date = today
                self.auto_solve_count = 0
                self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, True)
            
            # Check if unlimited access is active
            if self.unlimited_until and datetime.datetime.now() < datetime.datetime.fromisoformat(self.unlimited_until):
                print(f"[AUTO-SOLVE] Unlimited access active until {self.unlimited_until}")
            elif self.unlimited_forever:
                print("[AUTO-SOLVE] Permanent unlimited access active")
            elif self.auto_solve_count >= 1 and self.auto_solve_credits <= 0:
                # Daily limit reached and no credits - show IAP popup
                self.show_auto_solve_iap_popup()
                return
            else:
                # Use daily free use or credits
                if self.auto_solve_count < 1:
                    self.auto_solve_count += 1
                    print(f"[AUTO-SOLVE] Used daily free use ({self.auto_solve_count}/1)")
                elif self.auto_solve_credits > 0:
                    self.auto_solve_credits -= 1
                    print(f"[AUTO-SOLVE] Used credit, {self.auto_solve_credits} remaining")
                
                # Update button text to show new count
                self._update_auto_solve_button_text()
                
                self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, True)
        if not hasattr(self.game, 'solution'):
            return
        
        # Track auto-solve usage stat
        if hasattr(self, 'game_stats'):
            self.game_stats['auto_solves_used'] += 1
            self._save_stats_and_achievements()
            print(f"[STATS] Auto-solve used - total: {self.game_stats['auto_solves_used']}")
        
        # Clear all purple highlights/neon outlines before auto-solving
        for row in range(9):
            for col in range(9):
                cell = self.sudoku_board.get_cell(row, col)
                cell.hide_neon_outline()
        self.clear_all_note_highlights()
        
        # Clear any selected cell highlighting
        if hasattr(self, 'selected_cell') and self.selected_cell:
            old_row, old_col = self.selected_cell
            old_cell = self.sudoku_board.get_cell(old_row, old_col)
            old_cell.highlight_selected(False)
        self.selected_cell = None
        
        # Fill the entire board with the correct solution
        for row in range(9):
            for col in range(9):
                cell = self.sudoku_board.get_cell(row, col)
                val = str(self.game.solution[row][col])
                
                # Set the value using set_user_value to ensure proper display
                cell.set_user_value(val)
                cell.clear_notes()

                # Keep solved digits clearly visible after disabling the cell
                cell.color = (1.0, 1.0, 1.0, 1)
                if hasattr(cell, 'disabled_color'):
                    cell.disabled_color = (1.0, 1.0, 1.0, 1)
                
                # Update the game board state
                self.game.board[row][col] = int(val)
                
                # Disable the cell to prevent further input
                cell.disabled = True
                
                print(f"Auto-solve: Set cell ({row}, {col}) to {val}")
        
        # Optionally, disable digit buttons and action buttons
        for btn in getattr(self, 'digit_buttons', []):
            btn.disabled = True
        # After auto-solve, do not allow resume of this game
        self.last_game_in_progress = False
        # Save state as not in-progress
        self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, False)
        
        # Play complete sound when auto-solve is finished
        self._play_complete_sound()

        # Set solution revealed flag
        self.solution_revealed = True

    def update_auto_solve_button_state(self):
        """Enable or disable the auto-solve button based on usage in last 30 minutes."""
        now = time.time()
        self.auto_solve_timestamps = [t for t in self.auto_solve_timestamps if now - t < 1800]
        if hasattr(self, 'auto_btn'):
            self.auto_btn.disabled = len(self.auto_solve_timestamps) >= 3

    def show_auto_solve_iap_popup(self):
        """Show a compact Auto-Solve in-app purchase popup for mobile."""
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.uix.popup import Popup
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.uix.widget import Widget
        from kivy.uix.floatlayout import FloatLayout
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle, Line
        from kivy.core.window import Window
        
        def add_3d_silver_button_effect(btn):
            """Add 3D raised/embossed silver effect to a button"""
            with btn.canvas.after:
                Color(0.5, 0.5, 0.5, 1)
                border = Line(rectangle=(btn.x, btn.y, btn.width, btn.height), width=1)
                Color(0.95, 0.95, 0.95, 1)
                highlight_top = Line(points=[btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height], width=2)
                highlight_left = Line(points=[btn.x, btn.y, btn.x, btn.y + btn.height], width=2)
                Color(0.45, 0.45, 0.45, 1)
                shadow_bottom = Line(points=[btn.x, btn.y, btn.x + btn.width, btn.y], width=2)
                shadow_right = Line(points=[btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height], width=2)
            def update(instance, *args):
                border.rectangle = (btn.x, btn.y, btn.width, btn.height)
                highlight_top.points = [btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height]
                highlight_left.points = [btn.x, btn.y, btn.x, btn.y + btn.height]
                shadow_bottom.points = [btn.x, btn.y, btn.x + btn.width, btn.y]
                shadow_right.points = [btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height]
            btn.bind(pos=update, size=update)
        
        win_w, win_h = Window.width, Window.height
        scale_factor = min(win_w / 600.0, win_h / 850.0)
        scale_factor = max(0.5, min(1.5, scale_factor))
        # Compact popup for mobile - reduce height by 8%
        popup_w = min(win_w * 0.92, dp(340) * scale_factor)
        popup_h = min(win_h * 0.749 * 0.92, dp(407) * scale_factor * 0.92)
        
        # Outer container for white border effect
        outer = FloatLayout()
        with outer.canvas.before:
            Color(1, 1, 1, 1)  # White border
            outer_rect = Rectangle(size=outer.size, pos=outer.pos)
        outer.bind(size=lambda inst, val: setattr(outer_rect, 'size', val))
        outer.bind(pos=lambda inst, val: setattr(outer_rect, 'pos', val))
        
        # Inner content with tan background
        content = BoxLayout(orientation='vertical', padding=(dp(14) * scale_factor, dp(14) * scale_factor, dp(14) * scale_factor, dp(14) * scale_factor), spacing=dp(10) * scale_factor,
                           size_hint=(0.97, 0.97), pos_hint={'center_x': 0.5, 'center_y': 0.5})
        with content.canvas.before:
            Color(0.82, 0.71, 0.55, 1)  # Tan background
            bg_rect = Rectangle(size=content.size, pos=content.pos)
        content.bind(size=lambda inst, val: setattr(bg_rect, 'size', val))
        content.bind(pos=lambda inst, val: setattr(bg_rect, 'pos', val))
        outer.add_widget(content)
        
        # Title with decorative styling - use markup for vertical offset
        title_label = Label(
            text="\n Auto-Solve Magic",
            font_size=dp(20) * scale_factor,
            color=(0.35, 0.2, 0.1, 1),  # Rich brown
            size_hint=(1, None),
            height=dp(32) * scale_factor,
            bold=True,
            halign='center',
            valign='top'
        )
        title_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
        content.add_widget(title_label)
        
        # Decorative line under title
        title_divider = Widget(size_hint=(0.7, None), height=dp(2) * scale_factor)
        with title_divider.canvas:
            Color(0.55, 0.4, 0.25, 1)  # Dark tan/brown line
            title_divider_rect = Rectangle(size=title_divider.size, pos=title_divider.pos)
        title_divider.bind(size=lambda inst, val: setattr(title_divider_rect, 'size', val))
        title_divider.bind(pos=lambda inst, val: setattr(title_divider_rect, 'pos', val))
        divider_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(6) * scale_factor)
        divider_layout.add_widget(title_divider)
        content.add_widget(divider_layout)
        
        # Daily limit message
        limit_label = Label(
            text="You've used your daily free Auto-Solve.\nChoose an upgrade:",
            font_size=dp(13) * scale_factor,
            color=(0.3, 0.25, 0.2, 1),
            size_hint=(1, None),
            height=dp(40) * scale_factor,
            halign='center',
            valign='middle'
        )
        limit_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], None)))
        content.add_widget(limit_label)
        
        # Small spacer
        content.add_widget(Widget(size_hint_y=None, height=dp(4) * scale_factor))
        
        # IAP Options with enhanced styling
        iap_options = [
            ("5 Auto-Solves", "$0.99"),
            ("24h Unlimited", "$1.49"),
            ("Forever Unlimited", "$3.99")
        ]
        
        # Store buttons for popup reference
        purchase_buttons = []
        
        for option_name, price in iap_options:
            row = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(40) * scale_factor, spacing=dp(8) * scale_factor)
            
            name_label = Label(
                text=option_name,
                font_size=dp(13) * scale_factor,
                color=(0.15, 0.1, 0.05, 1),
                size_hint=(0.5, 1),
                halign='left',
                valign='middle'
            )
            name_label.bind(size=lambda inst, val: setattr(inst, 'text_size', (val[0], val[1])))
            price_label = Label(
                text=price,
                font_size=dp(13) * scale_factor,
                color=(0.0, 0.4, 0.0, 1),  # Green price
                size_hint=(0.22, 1),
                halign='center',
                valign='middle',
                bold=True
            )
            
            purchase_btn = Button(
                text="Buy",
                font_size=dp(13) * scale_factor,
                size_hint=(0.28, 1),
                background_color=(0.75, 0.75, 0.75, 1),  # Silver
                color=(0, 0, 0, 1),
                background_normal='',
                background_down=''
            )
            add_3d_silver_button_effect(purchase_btn)
            
            purchase_buttons.append((purchase_btn, option_name))
            row.add_widget(name_label)
            row.add_widget(price_label)
            row.add_widget(purchase_btn)
            content.add_widget(row)
        
        # Decorative divider before close button
        bottom_divider = Widget(size_hint=(0.85, None), height=dp(1) * scale_factor)
        with bottom_divider.canvas:
            Color(0.6, 0.5, 0.35, 0.6)  # Subtle tan line
            bottom_divider_rect = Rectangle(size=bottom_divider.size, pos=bottom_divider.pos)
        bottom_divider.bind(size=lambda inst, val: setattr(bottom_divider_rect, 'size', val))
        bottom_divider.bind(pos=lambda inst, val: setattr(bottom_divider_rect, 'pos', val))
        bottom_divider_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(12) * scale_factor)
        bottom_divider_layout.add_widget(bottom_divider)
        content.add_widget(bottom_divider_layout)
        
        # Close button with 3D silver effect
        close_btn = Button(
            text="Maybe Later",
            font_size=dp(13) * scale_factor,
            size_hint=(None, None),
            size=(dp(110) * scale_factor, dp(34) * scale_factor),
            background_color=(0.75, 0.75, 0.75, 1),  # Silver
            color=(0, 0, 0, 1),
            background_normal='',
            background_down=''
        )
        add_3d_silver_button_effect(close_btn)
        close_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(40) * scale_factor)
        close_layout.add_widget(close_btn)
        content.add_widget(close_layout)
        
        # Add Restore Purchases button
        restore_btn = Button(
            text="Restore Purchases",
            font_size=dp(11) * scale_factor,
            size_hint=(None, None),
            size=(dp(120) * scale_factor, dp(28) * scale_factor),
            background_color=(0.2, 0.6, 0.2, 1),  # Standard green
            background_normal='',
            background_down='',
            color=(1, 1, 1, 1)
        )
        restore_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint_y=None, height=dp(32) * scale_factor)
        restore_layout.add_widget(restore_btn)
        content.add_widget(restore_layout)
        
        popup = Popup(
            title='',
            content=outer,
            size_hint=(None, None),
            size=(popup_w, popup_h * 1.2),
            auto_dismiss=True,
            separator_height=0,
            background=''
        )
        
        # Bind purchase buttons after popup is created - with confirmation dialogs
        # Need to get prices for confirmation
        iap_prices = {
            "5 Auto-Solves": "$0.99",
            "24h Unlimited": "$1.49",
            "Forever Unlimited": "$3.99"
        }
        
        for btn, option_name in purchase_buttons:
            def make_purchase(instance, option=option_name, pr=iap_prices.get(option_name, "$0.99")):
                try:
                    self._play_button_click_sound()
                    self.show_purchase_confirmation(option, pr, lambda opt=option: self.purchase_auto_solve_option(opt), popup)
                except Exception as e:
                    import traceback
                    tb = traceback.format_exc()
                    print(f"[ERROR] purchase action failed: {e}\n{tb}")
                    try:
                        with open('/sdcard/sudoku_error.txt', 'w') as f:
                            f.write(tb)
                    except Exception:
                        pass
                    # friendly popup to inform user
                    try:
                        from kivy.uix.popup import Popup
                        from kivy.uix.label import Label
                        err = Popup(title='Purchase Error', content=Label(text='Unable to complete purchase action. Please try again.'), size_hint=(None, None), size=(dp(320), dp(160)))
                        err.open()
                    except Exception:
                        pass
            btn.bind(on_release=make_purchase)
        
        def close_popup(instance):
            self._play_button_click_sound()
            popup.dismiss()
        close_btn.bind(on_release=close_popup)
        def _restore_click(instance):
            try:
                self.restore_purchases(popup)
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                print(f"[ERROR] restore_purchases failed: {e}\n{tb}")
                try:
                    with open('/sdcard/sudoku_error.txt', 'w') as f:
                        f.write(tb)
                except Exception:
                    pass
                try:
                    from kivy.uix.popup import Popup
                    from kivy.uix.label import Label
                    err = Popup(title='Restore Error', content=Label(text='Unable to restore purchases at this time.'), size_hint=(None, None), size=(dp(320), dp(160)))
                    err.open()
                except Exception:
                    pass
        restore_btn.bind(on_release=_restore_click)
        
        popup.open()

    def use_hint(self, *args):
        """Fill one correct digit in a random empty cell. Uses global hint counter."""
        self._play_button_click_sound()
        
        # Check if user has premium (unlimited hints)
        has_premium = getattr(self, 'has_premium', False)
        print(f"[HINTS] use_hint called: has_premium={has_premium}, hints_remaining={self.global_hints_remaining}")
        
        if not has_premium:
            print(f"[HINTS] BEFORE use: {self.global_hints_remaining}")
            if self.global_hints_remaining <= 0:
                print(f"[HINTS] At 0 hints, checking daily refill...")
                refill_granted = self._check_daily_hint_refill()
                print(f"[HINTS] Refill check result: {refill_granted}, now have: {self.global_hints_remaining}")
                if self.global_hints_remaining <= 0:
                    print(f"[HINTS] Still at 0 after refill check - showing premium popup")
                    self.show_premium_offer_popup()
                    return
            # Decrement hints
            self.global_hints_remaining -= 1
            print(f"[HINTS] AFTER decrement: {self.global_hints_remaining}")
            self._save_global_hints()
            # Update hint button text to show remaining hints
            self._update_hint_button_text()
            
        if not hasattr(self.game, 'solution'):
            return
            
        # Find all empty cells
        empty_cells = [(r, c) for r in range(9) for c in range(9)
                       if not self.sudoku_board.get_cell(r, c).text.strip()]
        if not empty_cells:

            return
        import random
        row, col = random.choice(empty_cells)
        correct_val = str(self.game.solution[row][col])
        cell = self.sudoku_board.get_cell(row, col)

        # Play hint sound when a hint is used
        self._play_hint_sound()
        
        # Track hint usage stat
        if hasattr(self, 'game_stats'):
            self.game_stats['hints_used_total'] += 1
            if hasattr(self, '_current_game_hints_used'):
                self._current_game_hints_used += 1
            self._save_stats_and_achievements()
        
        # Save previous state for undo functionality
        prev_value = cell.text
        prev_notes = set(cell.notes) if cell.notes else set()
        
        cell.set_user_value(correct_val)
        cell.clear_notes()
        self.game.board[row][col] = int(correct_val)
        
        # Add hint action to history for undo functionality
        self.action_history.append(('digit', row, col, prev_value, prev_notes))
        
        # ...existing code...
        
        # Optionally, check for puzzle completion
        if self.is_puzzle_complete():
            self.show_reward_screen_delayed()

    def toggle_notes_mode(self, instance):
        """Toggle notes mode on/off"""
        # ALWAYS play pencil write sound FIRST, before toggling mode
        try:
            print("[SOUND] Playing pencil write sound for notes toggle")
            self._play_pencil_write_sound()
        except Exception as e:
            print(f"[SOUND] Error playing pencil write sound: {e}")
            import traceback
            traceback.print_exc()
        
        self.notes_mode = not self.notes_mode
        print(f"[NOTES] Notes mode toggled to: {self.notes_mode}")
        
        # Reverse: notes mode ON greys out button, OFF is full brightness
        try:
            from kivy.uix.image import Image
            from os.path import basename
            for child in self.root.walk():
                if isinstance(child, Image):
                    src = getattr(child, 'source', '')
                    # Check if this is the pencil image (works with different path formats)
                    if src and basename(src) == 'pencil.png':
                        child.opacity = 0.6 if self.notes_mode else 1.0
                        print(f"[NOTES] Pencil opacity set to: {child.opacity}")
        except Exception:
            pass

    def clear_selected_cell(self, instance):
        """Clear the selected cell if not a clue. If cell has notes, clear notes. If cell has digit, clear digit."""
        # Play pencil erase sound when eraser is clicked
        self._play_pencil_erase_sound()
        
        if self.selected_cell:
            row, col = self.selected_cell
            cell = self.sudoku_board.get_cell(row, col)
            if not cell.is_clue:
                if hasattr(cell, 'is_mistake') and cell.is_mistake:
                    # Find last action for this cell
                    for action in reversed(self.action_history):
                        if action[1] == row and action[2] == col and action[0] == 'digit':
                            prev_value = action[3]
                            prev_notes = action[4]
                            cell.clear_mistake()
                            if prev_notes:
                                cell.clear_digit()
                                cell.notes = set(prev_notes)
                                cell.update_notes_display()
                            else:
                                cell.clear_digit()
                                cell.notes.clear()
                                cell.update_notes_display()
                            break
                else:
                    cell.clear_mistake()  # Always clear mistake marking when erasing
                if cell.notes:
                    cell.clear_notes()
                    print(f"Cleared notes from cell ({row}, {col})")
                if cell.text:
                    cell.clear_digit()
                    self.game.board[row][col] = 0
                    print(f"Cleared digit from cell ({row}, {col})")
                    self.update_digit_buttons()
                
                # Save game state after clearing
                if hasattr(self, 'game') and hasattr(self.game, 'puzzle') and hasattr(self.game, 'solution') and hasattr(self.game, 'board'):
                    self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, True)

    def select_cell(self, row, col):
        """Select a cell on the board and highlight all cells with the same digit, or place digit/note if locked digit mode is active."""
        # If Stone Cold Digit Lock is active, place digit or note
        if self.locked_digit:
            cell = self.sudoku_board.get_cell(row, col)
            if cell.is_clue:
                print(f"Attempted to modify a clue cell at ({row}, {col}); action ignored.")
                return
            if self.notes_mode:
                prev_notes = set(cell.notes)
                if self.locked_digit in cell.notes:
                    cell.remove_note(self.locked_digit)
                else:
                    cell.add_note(self.locked_digit)
                self.action_history.append(('note', row, col, prev_notes))
            else:
                prev_value = cell.text
                prev_notes = set(cell.notes) if cell.notes else set()
                cell.set_user_value(self.locked_digit)
                self.game.board[row][col] = self.locked_digit
                self.update_digit_buttons()
                self.action_history.append(('digit', row, col, prev_value, prev_notes))
                print(f"Placed {self.locked_digit} at ({row}, {col}) [Stone Cold Digit Lock]")
                # Show purple outline on this cell too
                cell.show_neon_outline()
                # Mistake recognition (only if checking is enabled)
                if self.settings_check_mistakes and hasattr(self.game, 'solution'):
                    correct_digit = self.game.solution[row][col]
                    if self.locked_digit != correct_digit:
                        cell.mark_as_mistake()
                        self.mistake_count += 1
                        self.mistake_label.text = f"Mistakes: {self.mistake_count}"
                        print(f"Mistake at ({row}, {col})! Total mistakes: {self.mistake_count}")
                        
                        # Track mistake stats
                        if hasattr(self, 'game_stats'):
                            self.game_stats['mistakes_made_total'] += 1
                            if hasattr(self, '_current_game_mistakes'):
                                self._current_game_mistakes += 1
                        
                        # Immediately clear the incorrect digit and update board state
                        prev_value = cell.text
                        prev_notes = set(cell.notes) if cell.notes else set()
                        cell.clear_digit()
                        self.game.board[row][col] = 0
                        # Save this as an action for undo
                        self.action_history.append(('mistake', row, col, prev_value, prev_notes))
                        # Debug: print board state being saved after mistake
                        print(f"[DEBUG] Saving board after mistake at ({row},{col}):")
                        for debug_r in range(9):
                            print(self.game.board[debug_r])
                        # Force save game state immediately after mistake is processed
                        if hasattr(self, 'game') and hasattr(self.game, 'puzzle') and hasattr(self.game, 'solution') and hasattr(self.game, 'board'):
                            self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, True)
                        if self.mistake_count >= 3:
                            self.show_fail_screen()
                    else:
                        cell.clear_mistake()
                    # Also save after any mistake check, even if not locked digit mode
                    if self.locked_digit != correct_digit:
                        if hasattr(self, 'game') and hasattr(self.game, 'puzzle') and hasattr(self.game, 'solution') and hasattr(self.game, 'board'):
                            self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, True)
                    else:
                        cell.clear_mistake()
                self.check_row_completion(row)
                if self.is_puzzle_complete():
                    self.show_reward_screen_delayed()
            return
        # Play cell selection sound for normal selection
        self._play_cell_select_sound()
        # ...existing code for normal selection...
        if self.selected_cell:
            old_row, old_col = self.selected_cell
            old_cell = self.sudoku_board.get_cell(old_row, old_col)
            old_cell.highlight_selected(False)
            if hasattr(old_cell, 'is_mistake') and old_cell.is_mistake:
                # Find last action for this cell
                for action in reversed(self.action_history):
                    if action[1] == old_row and action[2] == old_col and action[0] == 'digit':
                        prev_value = action[3]
                        prev_notes = action[4]
                        old_cell.clear_mistake()
                        if prev_notes:
                            old_cell.clear_digit()
                            old_cell.notes = set(prev_notes)
                            old_cell.update_notes_display()
                        else:
                            old_cell.clear_digit()
                            old_cell.notes.clear()
                            old_cell.update_notes_display()
                        break
        # Remove all neon outlines and note highlights
        for r in range(9):
            for c in range(9):
                self.sudoku_board.get_cell(r, c).hide_neon_outline()
        self.clear_all_note_highlights()
        
        cell = self.sudoku_board.get_cell(row, col)
        self.selected_cell = (row, col)
        cell.highlight_selected(True)
        print(f"Selected cell ({row}, {col})")
        digit = cell.text.strip()
        if digit:
            # Highlight all cells with the same digit
            for r in range(9):
                for c in range(9):
                    other_cell = self.sudoku_board.get_cell(r, c)
                    if other_cell.text.strip() == digit:
                        other_cell.show_neon_outline()
            # Also highlight all notes with the same digit
            self.highlight_notes_for_digit(int(digit))

    def toggle_digit_lock(self, digit, idx):
        """Toggle Stone Cold Digit Lock mode for a digit. Show/hide padlock icon above the button and purple outlines."""
        if self.locked_digit == digit:
            # Unlock
            self.locked_digit = None
            if self.padlock_imgs[idx]:
                self.padlock_imgs[idx].opacity = 0
            # Remove purple outline from all cells and clear note highlights
            for r in range(9):
                for c in range(9):
                    self.sudoku_board.get_cell(r, c).hide_neon_outline()
            self.clear_all_note_highlights()
        else:
            # Lock this digit, unlock any other
            self.locked_digit = digit
            for i, img in enumerate(self.padlock_imgs):
                img.opacity = 1 if (i == idx) else 0
            # Show purple outline on all cells with this digit
            for r in range(9):
                for c in range(9):
                    cell = self.sudoku_board.get_cell(r, c)
                    if cell.text.strip() == str(digit):
                        cell.show_neon_outline()
                    else:
                        cell.hide_neon_outline()
            # Clear all previous note highlights before highlighting new digit's notes
            self.clear_all_note_highlights()
            self.highlight_notes_for_digit(digit)

    def highlight_notes_for_digit(self, digit):
        """Highlight all notes with the specified digit in purple across the board"""
        for r in range(9):
            for c in range(9):
                cell = self.sudoku_board.get_cell(r, c)
                cell.highlight_note(digit, highlight=True)
    
    def clear_all_note_highlights(self):
        """Clear purple highlighting from all notes across the board"""
        for r in range(9):
            for c in range(9):
                cell = self.sudoku_board.get_cell(r, c)
                cell.clear_all_note_highlights()
    
    def get_currently_highlighted_digit(self):
        """Get the digit that should currently be highlighted, either from selection or digit lock"""
        if self.locked_digit:
            return self.locked_digit
        elif self.selected_cell:
            row, col = self.selected_cell
            cell = self.sudoku_board.get_cell(row, col)
            digit_text = cell.text.strip()
            if digit_text:
                return int(digit_text)
        return None

    def update_digit_buttons(self):
        """Disable digit buttons for digits that have all 9 instances placed."""
        if not hasattr(self, 'digit_buttons') or not hasattr(self, 'sudoku_board'):
            return
        digit_counts = {str(i): 0 for i in range(1, 10)}
        for r in range(9):
            for c in range(9):
                val = self.sudoku_board.get_cell(r, c).text.strip()
                if val in digit_counts:
                    digit_counts[val] += 1
        for btn in self.digit_buttons:
            btn.disabled = digit_counts[str(btn.digit)] >= 9

    def is_puzzle_complete(self):
        """Check if the puzzle is complete and correct.
        Returns False if solution was revealed via auto-solve."""
        # Auto-solved puzzles don't count as completed
        if getattr(self, 'solution_revealed', False):
            return False
        if not hasattr(self, 'game') or not hasattr(self.game, 'solution'):
            return False
        for r in range(9):
            for c in range(9):
                cell = self.sudoku_board.get_cell(r, c)
                val = cell.text.strip()
                sol = str(self.game.solution[r][c])
                if val != sol:
                    return False
        return True

    # Patch handle_digit_button to call update_digit_buttons and show_reward_screen_delayed
    def handle_digit_button(self, digit):
        # Prevent input if fail screen is active
        if hasattr(self, '_fail_screen_active') and self._fail_screen_active:
            print("[INPUT] Blocked: Fail screen is active")
            return
            
        # Make sure we have a game and selected cell
        if not hasattr(self, 'game') or not self.game:
            print("[INPUT] Blocked: No active game")
            return
            
        print(f"[INPUT] handle_digit_button called with digit {digit}")
        print(f"[INPUT] Notes mode: {self.notes_mode}")
        print(f"[INPUT] Selected cell: {self.selected_cell}")
        
        if self.selected_cell:
            row, col = self.selected_cell
            cell = self.sudoku_board.get_cell(row, col)
            print(f"[INPUT] Cell at ({row}, {col}) - is_clue: {cell.is_clue}, text: '{cell.text}'")
            if not cell.is_clue:
                if self.notes_mode:
                    print(f"[NOTES] Notes mode active - processing digit {digit} for cell ({row}, {col})")
                    prev_notes = set(cell.notes)
                    if digit in cell.notes:
                        print(f"[NOTES] Removing note {digit} from cell ({row}, {col})")
                        cell.remove_note(digit)
                    else:
                        print(f"[NOTES] Adding note {digit} to cell ({row}, {col})")
                        cell.add_note(digit)
                    print(f"[NOTES] Cell notes after update: {cell.notes}")
                    self.action_history.append(('note', row, col, prev_notes))
                else:
                    print(f"[DIGIT] Normal mode - placing digit {digit} in cell ({row}, {col})")
                    prev_value = cell.text
                    prev_notes = set(cell.notes) if cell.notes else set()
                    cell.set_user_value(digit)
                    self._play_cell_fill_sound()
                    cell.clear_notes()  # Automatically clear notes when a digit is placed
                    self.game.board[row][col] = digit
                    # --- Clear conflicting notes in row, column, and section ---
                    # Clear notes in the same row
                    for c in range(9):
                        if c != col:
                            other_cell = self.sudoku_board.get_cell(row, c)
                            if digit in other_cell.notes:
                                other_cell.notes.discard(digit)
                                other_cell.update_notes_display()
                    # Clear notes in the same column
                    for r in range(9):
                        if r != row:
                            other_cell = self.sudoku_board.get_cell(r, col)
                            if digit in other_cell.notes:
                                other_cell.notes.discard(digit)
                                other_cell.update_notes_display()
                    # Clear notes in the same 3x3 section
                    box_row = (row // 3) * 3
                    box_col = (col // 3) * 3
                    for r in range(box_row, box_row + 3):
                        for c in range(box_col, box_col + 3):
                            if (r, c) != (row, col):
                                other_cell = self.sudoku_board.get_cell(r, c)
                                if digit in other_cell.notes:
                                    other_cell.notes.discard(digit)
                                    other_cell.update_notes_display()
                    # --- End clear conflicting notes ---
                    self.update_digit_buttons()
                    self.action_history.append(('digit', row, col, prev_value, prev_notes))
                    print(f"Placed {digit} at ({row}, {col})")
                    # Mistake recognition (only if checking is enabled)
                    if self.settings_check_mistakes and hasattr(self.game, 'solution'):
                        correct_digit = self.game.solution[row][col]
                        if digit != correct_digit:
                            cell.mark_as_mistake()
                            self.mistake_count += 1
                            self.mistake_label.text = f"Mistakes: {self.mistake_count}"
                            print(f"Mistake at ({row}, {col})! Total mistakes: {self.mistake_count}")
                            # Play error sound when user makes a mistake
                            self._play_error_sound()
                            
                            # Track mistake stats
                            if hasattr(self, 'game_stats'):
                                self.game_stats['mistakes_made_total'] += 1
                                if hasattr(self, '_current_game_mistakes'):
                                    self._current_game_mistakes += 1
                            
                            # Do NOT clear the cell or board; leave the mistake visible until user acts
                            # Optionally, add to action history for undo
                            prev_value = cell.text
                            prev_notes = set(cell.notes) if cell.notes else set()
                            self.action_history.append(('mistake', row, col, prev_value, prev_notes))
                            # Save state after mistake
                            print(f"[DEBUG] Saving board after mistake at ({row},{col}):")
                            for debug_r in range(9):
                                print(self.game.board[debug_r])
                            if hasattr(self, 'game') and hasattr(self.game, 'puzzle') and hasattr(self.game, 'solution') and hasattr(self.game, 'board'):
                                self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, True)
                            
                            # Show "Stuck?" popup after 2nd mistake to offer hints before game over
                            if self.mistake_count == 2:
                                print("[STUCK] User made 2nd mistake - showing Stuck? popup")
                                Clock.schedule_once(lambda dt: self.show_stuck_popup(), 0.5)
                            
                            if self.mistake_count == 3:
                                self._fail_screen_active = True
                                self.show_fail_screen()
                            return
                        else:
                            cell.clear_mistake()
                    # Check for row, column, and section completion, and puzzle completion
                    self.check_row_completion(row)
                    self.check_column_completion(col)
                    self.check_section_completion(row, col)
                    if self.is_puzzle_complete():
                        self.show_reward_screen_delayed()
        else:
            print("[INPUT] No cell selected - cannot place digit or note")
        # Save game state after every move
        if hasattr(self, 'game') and hasattr(self.game, 'puzzle') and hasattr(self.game, 'solution') and hasattr(self.game, 'board'):
            print(f"[SAVE] About to save game state after move: mistakes={self.mistake_count}")
            self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, True)

    def show_reward_screen_delayed(self):
        print("[REWARD] show_reward_screen_delayed() called")
        # Don't show reward screen for auto-solved puzzles
        if getattr(self, 'solution_revealed', False):
            print("[REWARD] Skipped - puzzle was auto-solved")
            return
        # Only show reward screen if not already active
        if getattr(self, '_reward_screen_active', False):
            print("[REWARD] Skipped - reward screen already active")
            return
        
        current_hints = getattr(self, '_current_game_hints_used', 0)
        
        # Block reward screen if more than 3 hints were used
        if current_hints > 3:
            print(f"[REWARD] Skipped - too many hints used ({current_hints} > 3)")
            # Still record stats if <= 5 hints (but no reward screen)
            if current_hints <= 5:
                try:
                    self._record_puzzle_completion()
                except Exception as e:
                    print(f"[REWARD] Error recording completion: {e}")
            else:
                print(f"[REWARD] Stats not recorded - too many hints ({current_hints} > 5)")
            return
        
        print("[REWARD] Setting _reward_screen_active = True")
        self._reward_screen_active = True
        
        # Track puzzle completion stats (only if <= 5 hints)
        try:
            self._record_puzzle_completion()
        except Exception as e:
            print(f"[REWARD] Error recording completion: {e}")
        
        from kivy.clock import Clock
        print("[REWARD] Scheduling show_reward_screen in 0.4 seconds")
        
        def safe_show_reward(dt):
            try:
                self.show_reward_screen()
            except Exception as e:
                print(f"[REWARD] ERROR in show_reward_screen: {e}")
                import traceback
                traceback.print_exc()
                self._reward_screen_active = False
        
        Clock.schedule_once(safe_show_reward, 0.4)  # Delay for animation
    
    def _record_puzzle_completion(self):
        """Record stats when a puzzle is completed"""
        import datetime
        import time
        
        if not hasattr(self, 'game_stats'):
            return
        
        stats = self.game_stats
        difficulty = getattr(self, 'last_difficulty', 'easy').lower()
        
        # Increment completion count
        stats['puzzles_completed'] += 1
        
        # Increment by difficulty
        if difficulty in stats['puzzles_by_difficulty']:
            stats['puzzles_by_difficulty'][difficulty] += 1
        
        # Track qualified completions (max 3 hints) for mastery achievements
        current_hints = getattr(self, '_current_game_hints_used', 0)
        if current_hints <= 3:
            # Ensure qualified_by_difficulty exists (for backwards compatibility)
            if 'qualified_by_difficulty' not in stats:
                stats['qualified_by_difficulty'] = {'easy': 0, 'moderate': 0, 'tough': 0, 'expert': 0, 'evil': 0, 'diabolical': 0}
            if difficulty in stats['qualified_by_difficulty']:
                stats['qualified_by_difficulty'][difficulty] += 1
                print(f"[STATS] Qualified completion for {difficulty} (hints used: {current_hints})")
        
        # Calculate time taken
        time_taken = None
        if hasattr(self, 'start_time') and self.start_time:
            time_taken = time.time() - self.start_time
            stats['total_play_time_seconds'] += time_taken
            
            # Check for best time
            best_key = f'fastest_{difficulty}'
            if best_key in stats:
                if stats[best_key] is None or time_taken < stats[best_key]:
                    stats[best_key] = time_taken
                    print(f"[STATS] New best time for {difficulty}: {time_taken:.1f}s")
        
        # Track perfect game (no mistakes this session) - max 3 hints allowed
        current_mistakes = getattr(self, '_current_game_mistakes', 0)
        current_hints = getattr(self, '_current_game_hints_used', 0)
        
        # Perfectionist: no mistakes AND max 3 hints used
        if current_mistakes == 0 and current_hints <= 3:
            stats['perfect_games'] += 1
            if not self.achievements.get('perfectionist', False):
                self.achievements['perfectionist'] = True
                print("[ACHIEVEMENT] Unlocked: Perfectionist!")
        
        # Track hint-free game (truly zero hints)
        if current_hints == 0 and not self.achievements.get('hint_free', False):
            self.achievements['hint_free'] = True
            print("[ACHIEVEMENT] Unlocked: Self-Reliant!")
        
        # Diabolical Mastermind - complete Diabolical without hints (strict - no hints at all)
        if difficulty and str(difficulty).lower() == 'diabolical' and current_hints == 0:
            if not self.achievements.get('diabolical_mastermind', False):
                self.achievements['diabolical_mastermind'] = True
                print("[ACHIEVEMENT] Unlocked: Diabolical Mastermind!")
        
        # Check for speed demon (Easy under 3 min) - max 2 hints allowed
        if difficulty == 'easy' and time_taken and time_taken < 180 and current_hints <= 2:
            if not self.achievements.get('speed_demon', False):
                self.achievements['speed_demon'] = True
                print("[ACHIEVEMENT] Unlocked: Speed Demon!")
        
        # Update streak
        today = datetime.date.today().isoformat()
        last_date = stats.get('last_completed_date')
        
        if last_date:
            try:
                last = datetime.date.fromisoformat(last_date)
                today_date = datetime.date.today()
                days_diff = (today_date - last).days
                
                if days_diff == 1:
                    # Consecutive day
                    stats['current_streak'] += 1
                elif days_diff == 0:
                    # Same day, streak continues
                    pass
                else:
                    # Streak broken
                    stats['current_streak'] = 1
            except:
                stats['current_streak'] = 1
        else:
            stats['current_streak'] = 1
        
        # Update best streak
        if stats['current_streak'] > stats['best_streak']:
            stats['best_streak'] = stats['current_streak']
        
        stats['last_completed_date'] = today
        
        # Update puzzle win streak (consecutive puzzles without failing)
        if 'puzzle_win_streak' not in stats:
            stats['puzzle_win_streak'] = 0
        if 'best_puzzle_win_streak' not in stats:
            stats['best_puzzle_win_streak'] = 0
        
        stats['puzzle_win_streak'] += 1
        if stats['puzzle_win_streak'] > stats['best_puzzle_win_streak']:
            stats['best_puzzle_win_streak'] = stats['puzzle_win_streak']
        print(f"[STATS] Win streak: {stats['puzzle_win_streak']} (best: {stats['best_puzzle_win_streak']})")
        
        # Check all achievements
        self._check_and_unlock_achievements()
        
        # Save stats
        self._save_stats_and_achievements()
        print(f"[STATS] Puzzle completed! Total: {stats['puzzles_completed']}, Streak: {stats['current_streak']}")
        
        # Flag that a review check should run when the user returns to the menu
        if stats['puzzles_completed'] >= 3:
            self._review_check_pending = True
            print(f"[REVIEW] Flagged review check pending (puzzles_completed={stats['puzzles_completed']})")

    # Removed duplicate, incomplete show_reward_screen definition
    def show_reward_screen(self):
        print("[REWARD] show_reward_screen() called")
        # Import Kivy UI classes at the top to avoid UnboundLocalError
        from kivy.uix.popup import Popup
        from kivy.uix.label import Label
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.uix.button import Button
        from kivy.uix.image import Image
        from kivy.metrics import dp
        from kivy.graphics import Color, Rectangle
        from kivy.core.window import Window
        import time

        # Calculate responsive sizing based on actual window size
        win_w, win_h = Window.width, Window.height
        scale_factor = min(win_w / 600.0, win_h / 850.0)
        scale_factor = max(0.4, min(2.0, scale_factor))  # Clamp scaling
        
        # Calculate popup size - responsive to window size
        popup_w = min(win_w * 0.95, dp(720) * scale_factor)
        popup_h = min(win_h * 0.9, dp(600) * scale_factor)
        # On Android shrink so bottom border does not blend with navigation strip
        from kivy.utils import platform as _plat
        if _plat == 'android':
            _nav_h = get_nav_bar_height()
            # Popup is centered, so bottom gap = (win_h - popup_h) / 2
            # Ensure this gap exceeds nav bar height + small visual buffer
            _max_popup_h = win_h - 2 * _nav_h - dp(8)
            popup_h = min(popup_h, _max_popup_h)
            popup_h = max(popup_h, dp(200))  # ensure usable minimum height

        # Root layout for popup content
        root = BoxLayout(orientation='vertical', padding=dp(12) * scale_factor, spacing=dp(8) * scale_factor)
        # Maroon background
        with root.canvas.before:
            Color(0.4, 0, 0, 1)  # Maroon
            bg_rect = Rectangle(size=root.size, pos=root.pos)
        root.bind(size=lambda inst, val: setattr(bg_rect, 'size', val))
        root.bind(pos=lambda inst, val: setattr(bg_rect, 'pos', val))

        # Responsive image sizing
        is_mobile = platform in ('android', 'ios')
        img_width = min(dp(640) * scale_factor, popup_w * 0.9)
        img_height = min(dp(360) * scale_factor, popup_h * 0.4)
        # Reduce padding below image to eliminate excess space before text
        if is_mobile:
            video_height = img_height + dp(2) * scale_factor  # Reduced from dp(4)
        else:
            video_height = img_height + dp(8) * scale_factor  # Reduced from dp(20)
        
        # Centered animated image (cherry tree mountains)
        video_layout = AnchorLayout(anchor_x='center', anchor_y='bottom', size_hint=(1, None), height=video_height)
        
        # Try animated GIF first, fall back to static image if not found
        # Use resource_path for Android compatibility
        gif_path = resource_path('Images/cherry_tree_mountains.gif')
        png_path = resource_path('Images/cherry_tree_mountains.PNG')
        
        # Check if file exists (works on desktop, on Android we just try to load)
        from kivy.utils import platform as plat
        gif_exists = os.path.exists(gif_path) if plat != 'android' else True
        png_exists = os.path.exists(png_path) if plat != 'android' else True
        
        if gif_exists:
            img = Image(
                source=gif_path,
                allow_stretch=True, 
                size_hint=(None, None), 
                size=(img_width, img_height),
                anim_delay=max(0.05, 0.1 / scale_factor)  # Faster animation for larger screens
            )
        elif png_exists:
            img = Image(
                source=png_path,
                allow_stretch=True, 
                size_hint=(None, None), 
                size=(img_width, img_height)
            )
        else:
            # Create a placeholder colored rectangle using Image widget
            img = Image(
                size_hint=(None, None), 
                size=(img_width, img_height)
            )
            # Add a colored background using canvas instructions
            with img.canvas.before:
                Color(0.2, 0.4, 0.2, 1)  # Dark green placeholder
                img._placeholder_rect = Rectangle(size=img.size, pos=img.pos)
            # Update rectangle when widget moves/resizes
            def update_placeholder_rect(instance, value):
                if hasattr(instance, '_placeholder_rect'):
                    instance._placeholder_rect.size = instance.size
                    instance._placeholder_rect.pos = instance.pos
            img.bind(size=update_placeholder_rect, pos=update_placeholder_rect)
        
        video_layout.add_widget(img)
        root.add_widget(video_layout)
        
        # Spacing and text for mobile/desktop
        is_mobile = platform in ('android', 'ios')
        if is_mobile:
            # Negative spacer to pull Japanese text up closer to the animation
            # This compensates for the BoxLayout spacing without changing other spacing
            root.add_widget(BoxLayout(size_hint_y=None, height=dp(-35) * scale_factor))
            
            # Japanese text, smaller font, one line
            jp_font_size = dp(18) * scale_factor
            jp_height = jp_font_size * 1.2
            jp_label = Label(
                text="すばらしい!",
                font_size=jp_font_size,
                color=(1, 1, 1, 1),
                font_name="msgothic",  # Use registered font name
                size_hint=(1, None),
                height=jp_height,
                halign='center',
                valign='middle',
                text_size=(popup_w * 0.95, None)
            )
            root.add_widget(jp_label)
            
            # Reduce spacing between Japanese and English text
            root.add_widget(BoxLayout(size_hint_y=None, height=dp(2) * scale_factor))  # Reduced from dp(4)
            en_font_size = dp(13) * scale_factor
            en_height = en_font_size * 2.4
            en_label = Label(
                text="Congratulations!\nYou solved the puzzle!",
                font_size=en_font_size,
                color=(1, 1, 1, 1),
                size_hint=(1, None),
                height=en_height,
                halign='center',
                valign='middle',
                text_size=(popup_w * 0.95, None)
            )
            root.add_widget(en_label)
            
            # Diabolical level only: Add Japanese "You are a legend" text
            if hasattr(self, 'last_difficulty') and self.last_difficulty == "Diabolical":
                root.add_widget(BoxLayout(size_hint_y=None, height=dp(2) * scale_factor))  # Reduced from dp(4)
                legend_jp_label = Label(
                    text="あなたは伝説です",
                    font_size=jp_font_size,
                    color=(1, 1, 1, 1),
                    font_name="msgothic",
                    size_hint=(1, None),
                    height=jp_height,
                    halign='center',
                    valign='middle',
                    text_size=(popup_w * 0.95, None)
                )
                root.add_widget(legend_jp_label)
                
                legend_en_label = Label(
                    text="You are a legend",
                    font_size=en_font_size,
                    color=(1, 1, 1, 1),
                    size_hint=(1, None),
                    height=en_font_size * 1.2,
                    halign='center',
                    valign='middle',
                    text_size=(popup_w * 0.95, None)
                )
                root.add_widget(legend_en_label)
            
            # Reduce spacing before completion time
            root.add_widget(BoxLayout(size_hint_y=None, height=dp(3) * scale_factor))  # Reduced from dp(6)
        else:
            # Desktop: original spacing and font sizes
            jp_font_size = dp(32) * scale_factor
            jp_height = jp_font_size * 1.5
            jp_label = Label(
                text="すばらしい!",
                font_size=jp_font_size,
                color=(1, 1, 1, 1),
                font_name="msgothic",  # Use registered font name
                size_hint=(1, None),
                height=jp_height,
                halign='center',
                valign='middle',
                text_size=(popup_w * 0.9, None)
            )
            root.add_widget(jp_label)
            
            # Reduce spacing between Japanese and English on desktop
            root.add_widget(BoxLayout(size_hint_y=None, height=dp(8) * scale_factor))  # Reduced from dp(14)
            en_font_size = dp(22) * scale_factor
            en_height = en_font_size * 2.4
            en_label = Label(
                text="Congratulations!\nYou solved the puzzle!",
                font_size=en_font_size,
                color=(1, 1, 1, 1),
                size_hint=(1, None),
                height=en_height,
                halign='center',
                valign='middle',
                text_size=(popup_w * 0.9, None)
            )
            root.add_widget(en_label)
            
            # Diabolical level only: Add Japanese "You are a legend" text
            if hasattr(self, 'last_difficulty') and self.last_difficulty == "Diabolical":
                root.add_widget(BoxLayout(size_hint_y=None, height=dp(6) * scale_factor))  # Reduced from dp(10)
                legend_jp_label = Label(
                    text="あなたは伝説です",
                    font_size=jp_font_size,
                    color=(1, 1, 1, 1),
                    font_name="msgothic",
                    size_hint=(1, None),
                    height=jp_height,
                    halign='center',
                    valign='middle',
                    text_size=(popup_w * 0.9, None)
                )
                root.add_widget(legend_jp_label)
                
                legend_en_label = Label(
                    text="You are a legend",
                    font_size=en_font_size,
                    color=(1, 1, 1, 1),
                    size_hint=(1, None),
                    height=en_font_size * 1.5,
                    halign='center',
                    valign='middle',
                    text_size=(popup_w * 0.9, None)
                )
                root.add_widget(legend_en_label)
            
            # Reduce spacing before completion time on desktop
            root.add_widget(BoxLayout(size_hint_y=None, height=dp(8) * scale_factor))  # Reduced from dp(12)

        # Show completion time - responsive sizing
        if hasattr(self, 'start_time'):
            elapsed = int(time.time() - self.start_time)
            minutes = elapsed // 60
            seconds = elapsed % 60
            time_str = f"Completion Time: {minutes}:{seconds:02d}"
            if is_mobile:
                time_font_size = dp(12.5) * scale_factor
                time_height = time_font_size * 1.3
            else:
                time_font_size = dp(20) * scale_factor
                time_height = time_font_size * 1.6
            time_label = Label(
                text=time_str,
                font_size=time_font_size,
                color=(1, 1, 1, 1),
                size_hint=(1, None),
                height=time_height,
                halign='center',
                valign='middle',
                text_size=(popup_w * 0.9, None)
            )
            root.add_widget(time_label)
            # Reduce spacing after completion time
            root.add_widget(BoxLayout(size_hint_y=None, height=dp(4) * scale_factor if is_mobile else dp(10) * scale_factor))  # Reduced
        else:
            # Reduce spacing when no completion time shown
            root.add_widget(BoxLayout(size_hint_y=None, height=dp(4) * scale_factor if is_mobile else dp(10) * scale_factor))  # Reduced

        # Button - responsive sizing
        if is_mobile:
            btn_font_size = dp(13) * scale_factor
            btn_width = dp(110) * scale_factor
            btn_height = dp(30) * scale_factor
            btn_layout_height = btn_height + dp(3) * scale_factor  # Reduced from dp(6)
        else:
            btn_font_size = dp(18) * scale_factor
            btn_width = dp(180) * scale_factor
            btn_height = dp(44) * scale_factor
            btn_layout_height = btn_height + dp(10) * scale_factor  # Reduced from dp(16)
        btn = Button(
            text="Back to Menu",
            font_size=btn_font_size,
            size_hint=(None, None),
            size=(btn_width, btn_height),
            background_color=(0.75, 0.75, 0.75, 1),
            color=(0, 0, 0, 1),
            background_normal='',
            background_down=''
        )
        # Add 3D embossed effect
        from kivy.graphics import Color, Line
        with btn.canvas.after:
            Color(0.5, 0.5, 0.5, 1)
            btn._border = Line(rectangle=(btn.x, btn.y, btn.width, btn.height), width=1)
            Color(0.9, 0.9, 0.9, 1)
            btn._highlight_top = Line(points=[btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height], width=2)
            btn._highlight_left = Line(points=[btn.x, btn.y, btn.x, btn.y + btn.height], width=2)
            Color(0.4, 0.4, 0.4, 1)
            btn._shadow_bottom = Line(points=[btn.x, btn.y, btn.x + btn.width, btn.y], width=2)
            btn._shadow_right = Line(points=[btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height], width=2)
        def update_btn_border(instance, *args):
            btn._border.rectangle = (btn.x, btn.y, btn.width, btn.height)
            btn._highlight_top.points = [btn.x, btn.y + btn.height, btn.x + btn.width, btn.y + btn.height]
            btn._highlight_left.points = [btn.x, btn.y, btn.x, btn.y + btn.height]
            btn._shadow_bottom.points = [btn.x, btn.y, btn.x + btn.width, btn.y]
            btn._shadow_right.points = [btn.x + btn.width, btn.y, btn.x + btn.width, btn.y + btn.height]
        btn.bind(pos=update_btn_border, size=update_btn_border)
        btn_layout = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, None), height=btn_layout_height)
        btn_layout.add_widget(btn)
        root.add_widget(btn_layout)

        # Popup - responsive sizing
        popup = Popup(title='', content=root, size_hint=(None, None), size=(popup_w, popup_h), auto_dismiss=False, separator_height=0, background='')
        def go_to_menu(instance):
            self._play_button_click_sound()
            popup.dismiss()
            # Stop ALL sounds
            self._stop_all_sounds()
            # Stop clock updates
            self._stop_clock_updates()
            self._navigation_pause_time = time.time()  # Record pause when leaving puzzle
            self._reward_screen_active = False  # Allow reward screen again for new games
            # Mark game as no longer in progress and update saved state
            self.last_game_in_progress = False
            # Optionally clear last_game_state as well
            if self.last_game_state:
                self.last_game_state['in_progress'] = False
                # Save the cleared state to disk
                try:
                    import json
                    with open('last_game.json', 'w') as f:
                        json.dump(self.last_game_state, f)
                except Exception as e:
                    print(f"Error updating last game state: {e}")
            self.root.clear_widgets()
            self.welcome_layout = self.build_welcome_screen()
            self.root.add_widget(self.welcome_layout)
            
            # Schedule review prompt after returning to menu (1 second delay)
            from kivy.clock import Clock
            def _review_check(dt):
                try:
                    print("[REVIEW] Running scheduled review check from reward screen go_to_menu")
                    show_review_prompt_if_eligible(self)
                except Exception as e:
                    import traceback
                    print(f"[REVIEW] ERROR in scheduled review check: {e}")
                    traceback.print_exc()
            Clock.schedule_once(_review_check, 1.0)
        btn.bind(on_release=go_to_menu)
        
        # Stop ALL music (including native MCI tracks) before reward sound
        try:
            self._stop_menu_sounds()
        except Exception as e:
            print(f"[SOUND] Error stopping menu sounds before reward: {e}")
        try:
            if hasattr(self, '_music') and self._music:
                self._music.stop()
                print("[SOUND] Stopped puzzle music for reward screen")
        except Exception as e:
            print(f"[SOUND] Error stopping puzzle music before reward: {e}")
        try:
            if self._supports_native_windows_audio():
                self._native_audio_stop('serene_music')
                self._native_audio_stop('serene_welcome')
                self._native_music = False
                print("[SOUND] Stopped native MCI music for reward screen")
        except Exception as e:
            print(f"[SOUND] Error stopping native music before reward: {e}")
        self._reward_screen_showing = True
        self._play_reward_sound()
        
        print("[REWARD] Opening popup")
        popup.open()

    def _show_enjoyment_dialog(self):
        """Show a positive-gate dialog asking if user is enjoying the app.
        
        If they say 'Yes', request the Google Play review prompt.
        If they say 'No', show a feedback form.
        """
        try:
            self._show_enjoyment_dialog_impl()
        except Exception as e:
            import traceback
            print(f"[REVIEW] ERROR showing enjoyment dialog: {e}")
            traceback.print_exc()

    def _show_review_debug_popup(self, message, title='Review Debug'):
        """Temporary on-screen diagnostics for review prompt testing."""
        if not getattr(self, 'review_debug_mode', False):
            return

        try:
            from kivy.uix.popup import Popup
            from kivy.uix.boxlayout import BoxLayout
            from kivy.uix.label import Label
            from kivy.uix.button import Button
            from kivy.metrics import dp
            from kivy.core.window import Window

            popup_w = min(Window.width * 0.9, dp(460))
            popup_h = min(Window.height * 0.5, dp(320))

            root = BoxLayout(orientation='vertical', padding=dp(20), spacing=dp(16))
            label = Label(
                text=message,
                color=(0, 0, 0, 1),
                halign='left',
                valign='middle',
                text_size=(popup_w - dp(40), None)
            )
            root.add_widget(label)

            close_btn = Button(
                text='OK',
                size_hint=(1, None),
                height=dp(44),
                background_normal='',
                background_down='',
                background_color=(0.35, 0.6, 0.45, 1),
                color=(1, 1, 1, 1)
            )
            root.add_widget(close_btn)

            popup = Popup(
                title=title,
                content=root,
                size_hint=(None, None),
                size=(popup_w, popup_h),
                auto_dismiss=False
            )
            close_btn.bind(on_release=lambda *_: popup.dismiss())
            popup.open()
        except Exception as e:
            print(f"[REVIEW] Failed to show debug popup: {e}")
    
    def _show_enjoyment_dialog_impl(self):
        """Internal implementation of the enjoyment dialog."""
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.uix.floatlayout import FloatLayout
        from kivy.uix.image import Image
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.core.window import Window
        from kivy.metrics import dp
        
        print("[REVIEW] Showing enjoyment dialog")
        
        # Calculate responsive sizing
        win_w, win_h = Window.width, Window.height
        scale_factor = min(win_w / 600.0, win_h / 850.0)
        scale_factor = max(0.4, min(2.0, scale_factor))
        
        popup_w = min(win_w * 0.94, dp(520) * scale_factor)
        popup_h = min(win_h * 0.68, dp(500) * scale_factor)
        
        # Root layout keeps ring high, then title, then buttons.
        root = BoxLayout(orientation='vertical', padding=(0, dp(10) * scale_factor, 0, dp(8) * scale_factor), spacing=dp(2) * scale_factor)

        # art_layout is 46% of popup — reduced from 58% to account for transparent
        # bottom padding in the PNG and give the text container more room.
        art_layout = FloatLayout(size_hint=(1, None), height=popup_h * 0.46)

        # Ring size bounded by the smaller art_layout height; center_y=0.5 so any
        # transparent PNG padding distributes equally top/bottom.
        ring_size = min(popup_w * 0.88, popup_h * 0.50)
        art_image = Image(
            source=resource_path('Images/review_enjoyment_ring.png'),
            allow_stretch=True,
            keep_ratio=True,
            size_hint=(None, None),
            size=(ring_size, ring_size),
            pos_hint={'center_x': 0.5, 'center_y': 0.5}
        )
        art_layout.add_widget(art_image)
        root.add_widget(art_layout)

        # Keep a tall title area and intentionally bias the text upward.
        title_layout = FloatLayout(size_hint=(1, None), height=popup_h * 0.26)
        question_label = Label(
            text='Are you enjoying\nthe game?',
            font_size=dp(21) * scale_factor,
            bold=True,
            color=(0.83, 0.84, 0.87, 1),
            size_hint=(1, None),
            height=dp(56) * scale_factor,
            pos_hint={'center_x': 0.5, 'center_y': 0.82},
            halign='center',
            valign='middle',
            text_size=(popup_w * 0.84, None)
        )
        title_layout.add_widget(question_label)
        root.add_widget(title_layout)

        btn_layout = BoxLayout(
            orientation='horizontal',
            spacing=dp(18) * scale_factor,
            size_hint=(None, None),
            size=(popup_w * 0.78, dp(64) * scale_factor),
            pos_hint={'center_x': 0.5}
        )

        btn_container = AnchorLayout(anchor_x='center', anchor_y='top', size_hint=(1, None), height=popup_h * 0.22)
        
        # Embossed maroon buttons with white text
        yes_btn = Button(
            text='Yes!',
            font_size=dp(18) * scale_factor,
            bold=True,
            background_color=(0.44, 0.08, 0.12, 1),
            color=(1, 1, 1, 1),
            background_normal='',
            background_down=''
        )
        
        # No button - soft muted coral
        no_btn = Button(
            text='Not Yet',
            font_size=dp(18) * scale_factor,
            bold=True,
            background_color=(0.44, 0.08, 0.12, 1),
            color=(1, 1, 1, 1),
            background_normal='',
            background_down=''
        )
        
        btn_layout.add_widget(yes_btn)
        btn_layout.add_widget(no_btn)
        btn_container.add_widget(btn_layout)
        root.add_widget(btn_container)
        
        # Create popup
        popup = Popup(
            title='',
            content=root,
            size_hint=(None, None),
            size=(popup_w, popup_h),
            auto_dismiss=False,
            separator_height=0,
            background=''
        )
        # Keep no panel, but add a soft translucent veil for text contrast.
        popup.background_color = (0, 0, 0, 0)
        if hasattr(popup, 'overlay_color'):
            popup.overlay_color = (0, 0, 0, 0.58)

        def _apply_embossed_maroon(button):
            from kivy.graphics import Color, Line
            with button.canvas.after:
                Color(0.2, 0.03, 0.05, 0.9)
                button._border = Line(rectangle=(button.x, button.y, button.width, button.height), width=1)
                Color(0.62, 0.16, 0.22, 0.95)
                button._highlight_top = Line(points=[button.x, button.y + button.height, button.x + button.width, button.y + button.height], width=2)
                button._highlight_left = Line(points=[button.x, button.y, button.x, button.y + button.height], width=2)
                Color(0.16, 0.02, 0.04, 0.95)
                button._shadow_bottom = Line(points=[button.x, button.y, button.x + button.width, button.y], width=2)
                button._shadow_right = Line(points=[button.x + button.width, button.y, button.x + button.width, button.y + button.height], width=2)

            def _update_btn_emboss(instance, *args):
                button._border.rectangle = (button.x, button.y, button.width, button.height)
                button._highlight_top.points = [button.x, button.y + button.height, button.x + button.width, button.y + button.height]
                button._highlight_left.points = [button.x, button.y, button.x, button.y + button.height]
                button._shadow_bottom.points = [button.x, button.y, button.x + button.width, button.y]
                button._shadow_right.points = [button.x + button.width, button.y, button.x + button.width, button.y + button.height]

            button.bind(pos=_update_btn_emboss, size=_update_btn_emboss)

        _apply_embossed_maroon(yes_btn)
        _apply_embossed_maroon(no_btn)
        
        def on_yes(instance):
            print("[REVIEW] User said YES - requesting review flow")
            popup.dismiss()
            # Update tracking
            import time
            self.game_stats['last_review_prompt_shown'] = time.time()
            self.game_stats['review_prompt_shown_count'] += 1
            self._save_stats_and_achievements()
            # Request review from Google Play
            self._request_google_play_review()
        
        def on_no(instance):
            print("[REVIEW] User said NO - showing feedback form")
            popup.dismiss()
            # Update tracking so we don't ask too soon
            import time
            self.game_stats['last_review_prompt_shown'] = time.time()
            self.game_stats['review_prompt_shown_count'] += 1
            self._save_stats_and_achievements()
            # Show feedback form (optional)
            self._show_feedback_form()
        
        yes_btn.bind(on_release=on_yes)
        no_btn.bind(on_release=on_no)
        
        popup.open()
    
    def _request_google_play_review(self):
        """Request the Google Play review flow from ReviewManager."""
        print("[REVIEW] Requesting Google Play review flow...")
        
        try:
            # Reset review flow tracking before handing off to ReviewManager.
            self._review_flow_pending = True
            self._review_fallback_shown = False
            if hasattr(self, '_review_fallback_watchdog') and self._review_fallback_watchdog is not None:
                try:
                    self._review_fallback_watchdog.cancel()
                except Exception:
                    pass
                self._review_fallback_watchdog = None

            # Safety net: if neither on_complete nor on_error ever arrives,
            # show fallback so the user is never left with no UI response.
            from kivy.clock import Clock
            self._review_fallback_watchdog = Clock.schedule_once(
                lambda dt: self._review_watchdog_timeout(),
                15.0
            )

            if not hasattr(self, '_review_manager'):
                self._review_manager = ReviewManager()

            if not self._review_manager or not self._review_manager.review_manager:
                print("[REVIEW] ReviewManager unavailable - showing fallback rate dialog")
                self._cancel_review_watchdog()
                self._review_flow_pending = False
                self._show_rate_fallback_dialog()
                return
            
            def on_review_ready():
                print("[REVIEW] Review flow ready, launching...")
                self._review_launch_requested_at = time.time()
                self._review_manager.launch_review_flow(
                    on_complete=self._on_review_complete,
                    on_error=lambda exc: self._handle_review_launch_error(exc)
                )
            
            def on_review_error(exc):
                print(f"[REVIEW] Review flow error: {exc}")
                self._cancel_review_watchdog()
                self._review_flow_pending = False
                self._show_rate_fallback_dialog()
            
            self._review_manager.request_review_flow(
                on_success=on_review_ready,
                on_error=on_review_error
            )
            
        except Exception as e:
            print(f"[REVIEW] Exception requesting review: {e}")
            self._cancel_review_watchdog()
            self._review_flow_pending = False
            self._show_rate_fallback_dialog()
    
    def _on_review_complete(self):
        """Called when the Play review flow returns control to the app."""
        self._cancel_review_watchdog()
        self._review_flow_pending = False
        elapsed = time.time() - getattr(self, '_review_launch_requested_at', time.time())
        print(f"[REVIEW] Review flow completed after {elapsed:.2f}s")

        # Heuristic: Play returns control very quickly (< 5s) when it suppresses
        # the sheet due to quotas or user eligibility. In that case show the
        # fallback so the user still has a path to rate.
        # If the flow ran for >= 5s the user very likely interacted with an
        # actual Play sheet and we don't need to do anything extra.
        if elapsed < 5.0:
            print("[REVIEW] Quick completion - Play likely suppressed sheet; scheduling fallback")
            from kivy.clock import Clock
            Clock.schedule_once(lambda dt: self._show_rate_fallback_dialog(), 1.0)
        else:
            print("[REVIEW] Extended completion - user likely saw the Play review sheet")

    def _handle_review_launch_error(self, exc):
        """Handle actual review launch failures only."""
        print(f"[REVIEW] Launch failed: {exc}")
        self._cancel_review_watchdog()
        self._review_flow_pending = False
        self._show_rate_fallback_dialog()

    def _review_watchdog_timeout(self):
        """Safety timeout if review flow state was never cleared."""
        self._review_fallback_watchdog = None
        if getattr(self, '_review_flow_pending', False):
            print("[REVIEW] Watchdog timeout reached; forcing fallback dialog")
            self._review_flow_pending = False
            self._show_rate_fallback_dialog()

    def _cancel_review_watchdog(self):
        if hasattr(self, '_review_fallback_watchdog') and self._review_fallback_watchdog is not None:
            try:
                self._review_fallback_watchdog.cancel()
            except Exception:
                pass
            self._review_fallback_watchdog = None

    def _show_rate_fallback_dialog(self):
        """Fallback path when Play in-app review is unavailable or errors out."""
        if getattr(self, '_review_fallback_shown', False):
            print("[REVIEW] Fallback dialog already shown for this flow; skipping duplicate")
            return

        # If a popup is already open/closing from the previous step, opening a
        # new popup in the same event cycle can occasionally fail silently.
        # Defer one frame and mark as shown up-front to keep behavior stable.
        self._review_fallback_shown = True

        from kivy.clock import Clock

        def _open_fallback_popup(dt):
            self._open_rate_fallback_dialog_now()

        Clock.schedule_once(_open_fallback_popup, 0)

    def _open_rate_fallback_dialog_now(self):
        """Render and open the fallback rate dialog immediately."""
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.metrics import dp
        from kivy.core.window import Window

        win_w, win_h = Window.width, Window.height
        popup_w = min(win_w * 0.86, dp(420))
        popup_h = min(win_h * 0.42, dp(250))

        root = BoxLayout(orientation='vertical', padding=dp(22), spacing=dp(14))
        label = Label(
            text='Google Play did not show the in-app\nrating sheet this time.\nWould you like to rate Serene Sudoku on\nthe Play Store?',
            color=(1, 1, 1, 1),
            bold=True,
            halign='center',
            valign='middle',
            text_size=(popup_w * 0.88, None)
        )
        root.add_widget(label)

        btn_row = BoxLayout(spacing=dp(10), size_hint_y=None, height=dp(44))
        rate_btn = Button(text='Rate on Play Store', bold=True, color=(1, 1, 1, 1), background_normal='', background_down='', background_color=(0.44, 0.08, 0.12, 1))
        later_btn = Button(text='Maybe Later', bold=True, color=(1, 1, 1, 1), background_normal='', background_down='', background_color=(0.44, 0.08, 0.12, 1))
        btn_row.add_widget(rate_btn)
        btn_row.add_widget(later_btn)
        root.add_widget(btn_row)

        from kivy.graphics import Color, Line, RoundedRectangle
        with root.canvas.before:
            Color(0.18, 0.20, 0.24, 0.96)
            root._bg_rect = RoundedRectangle(size=root.size, pos=root.pos, radius=[dp(16)])
        with root.canvas.after:
            Color(1, 1, 1, 0.72)
            root._border_line = Line(rounded_rectangle=(root.x, root.y, root.width, root.height, dp(16)), width=1)

        def _update_fallback_bg(instance, *args):
            root._bg_rect.size = root.size
            root._bg_rect.pos = root.pos
            root._border_line.rounded_rectangle = (root.x, root.y, root.width, root.height, dp(16))

        root.bind(pos=_update_fallback_bg, size=_update_fallback_bg)

        popup = Popup(title='', content=root, size_hint=(None, None), size=(popup_w, popup_h), auto_dismiss=False, separator_height=0, background='')

        rate_btn.bind(on_release=lambda *_: (popup.dismiss(), self._open_play_store_rating_page()))
        later_btn.bind(on_release=lambda *_: popup.dismiss())
        print("[REVIEW] Opening fallback rate dialog")
        popup.open()

    def _open_play_store_rating_page(self):
        """Ope        cd /mnt/c/Users/timpe/Desktop/SudokuMobileApp_Copy
        source .venv_wsl/bin/activate
        
        rm -rf .buildozer/android/app
        rm -rf .buildozer/android/platform/build-*
        rm -f bin/*.aab
        
        buildozer -v android release
        
        grep -E "^version =|^android.numeric_version =" buildozer.spec
        ls -lh bin/*1.8.33*-release.aabn Play Store listing as a fallback when in-app review is not shown."""
        try:
            from kivy.utils import platform
            if platform != 'android':
                print('[REVIEW] Non-Android platform, skipping Play Store open')
                return

            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Intent = autoclass('android.content.Intent')
            Uri = autoclass('android.net.Uri')

            activity = PythonActivity.mActivity
            package_name = activity.getPackageName()

            # Prefer Google Play Store directly and fall back to https if needed
            intent = Intent(Intent.ACTION_VIEW, Uri.parse(f'market://details?id={package_name}'))
            intent.setPackage('com.android.vending')
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            activity.startActivity(intent)
            print(f'[REVIEW] Opened Play Store page for {package_name}')
        except Exception as e:
            print(f'[REVIEW] Failed to open market URI, trying https fallback: {e}')
            try:
                from jnius import autoclass
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                Intent = autoclass('android.content.Intent')
                Uri = autoclass('android.net.Uri')

                activity = PythonActivity.mActivity
                package_name = activity.getPackageName()
                https_intent = Intent(Intent.ACTION_VIEW, Uri.parse(f'https://play.google.com/store/apps/details?id={package_name}'))
                https_intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                activity.startActivity(https_intent)
                print(f'[REVIEW] Opened HTTPS Play Store page for {package_name}')
            except Exception as e2:
                print(f'[REVIEW] Could not open Play Store page: {e2}')
    
    def _show_feedback_form(self):
        """Show a feedback form when user says they're not enjoying the app."""
        from kivy.uix.popup import Popup
        from kivy.uix.boxlayout import BoxLayout
        from kivy.uix.anchorlayout import AnchorLayout
        from kivy.uix.label import Label
        from kivy.uix.button import Button
        from kivy.core.window import Window
        from kivy.metrics import dp
        from kivy.graphics import Color, Line, RoundedRectangle
        
        print("[REVIEW] Showing feedback form")
        
        # Calculate responsive sizing
        win_w, win_h = Window.width, Window.height
        scale_factor = min(win_w / 600.0, win_h / 850.0)
        scale_factor = max(0.4, min(2.0, scale_factor))
        
        popup_w = min(win_w * 0.85, dp(400) * scale_factor)
        popup_h = min(win_h * 0.62, dp(320) * scale_factor)  # Taller to fit all content
        
        email_btn_h = dp(58) * scale_factor
        done_btn_h = dp(44) * scale_factor
        
        # Root layout
        root = BoxLayout(orientation='vertical', padding=dp(24) * scale_factor, spacing=dp(14) * scale_factor)
        
        # Message label - white text
        msg_label = Label(
            text='Thanks for trying!\nWe\'d love to improve.\nEmail us your feedback.',
            font_size=dp(14) * scale_factor,
            color=(1, 1, 1, 1),
            size_hint=(1, 1),  # Expand to fill remaining space above buttons
            valign='middle',
            halign='center',
            text_size=(popup_w * 0.85, None)
        )
        root.add_widget(msg_label)
        
        # Email button - wider so the entire address stays on one line.
        email_btn = Button(
            text='The_Zen_Shoppe@icloud.com',
            font_size=dp(11) * scale_factor,
            bold=True,
            background_color=(0.72, 0.72, 0.72, 1),  # Silver
            color=(0.12, 0.12, 0.12, 1),  # Dark text on silver
            background_normal='',
            background_down='',
            halign='center',
            valign='middle',
            size_hint=(None, None),
            size=(popup_w * 0.92, email_btn_h),
            text_size=(popup_w * 0.88, email_btn_h)
        )
        email_btn_wrap = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, None), height=email_btn_h + dp(6) * scale_factor)
        email_btn_wrap.add_widget(email_btn)
        root.add_widget(email_btn_wrap)
        
        # Done button - intentionally smaller and less prominent than email.
        close_btn = Button(
            text='Done',
            font_size=dp(13) * scale_factor,
            bold=True,
            background_color=(0.44, 0.08, 0.12, 1),
            color=(1, 1, 1, 1),
            background_normal='',
            background_down='',
            size_hint=(None, None),
            size=(popup_w * 0.56, done_btn_h)
        )
        close_btn_wrap = AnchorLayout(anchor_x='center', anchor_y='center', size_hint=(1, None), height=done_btn_h + dp(4) * scale_factor)
        close_btn_wrap.add_widget(close_btn)
        root.add_widget(close_btn_wrap)
        
        # Create popup - transparent so root canvas shows orange background
        popup = Popup(
            title='',
            content=root,
            size_hint=(None, None),
            size=(popup_w, popup_h),
            auto_dismiss=False,
            separator_height=0,
            background='',
            background_color=(0, 0, 0, 0)
        )
        
        # Orange background + white border — bound to pos/size so they update after layout
        with root.canvas.before:
            _bg_color = Color(0.96, 0.65, 0.14, 1)
            _bg_rect = RoundedRectangle(pos=root.pos, size=root.size, radius=[dp(12) * scale_factor])
        with root.canvas.after:
            _border_color = Color(1, 1, 1, 1)
            _border_line = Line(rectangle=(root.x, root.y, root.width, root.height),
                                width=dp(3) * scale_factor)
        
        def _update_feedback_bg(instance, *args):
            _bg_rect.pos = instance.pos
            _bg_rect.size = instance.size
            _border_line.rectangle = (instance.x, instance.y, instance.width, instance.height)
        
        root.bind(pos=_update_feedback_bg, size=_update_feedback_bg)
        
        def _apply_embossed_button(button, light=False):
            """Apply raised emboss effect to button."""
            with button.canvas.after:
                if light:
                    Color(0.9, 0.9, 0.9, 1)
                    button._highlight_top = Line(points=[button.x, button.y + button.height, button.x + button.width, button.y + button.height], width=2)
                    button._highlight_left = Line(points=[button.x, button.y, button.x, button.y + button.height], width=2)
                    Color(0.45, 0.45, 0.45, 1)
                    button._shadow_bottom = Line(points=[button.x, button.y, button.x + button.width, button.y], width=2)
                    button._shadow_right = Line(points=[button.x + button.width, button.y, button.x + button.width, button.y + button.height], width=2)
                else:
                    Color(0.62, 0.16, 0.22, 0.95)
                    button._highlight_top = Line(points=[button.x, button.y + button.height, button.x + button.width, button.y + button.height], width=2)
                    button._highlight_left = Line(points=[button.x, button.y, button.x, button.y + button.height], width=2)
                    Color(0.16, 0.02, 0.04, 0.95)
                    button._shadow_bottom = Line(points=[button.x, button.y, button.x + button.width, button.y], width=2)
                    button._shadow_right = Line(points=[button.x + button.width, button.y, button.x + button.width, button.y + button.height], width=2)

            def _update_btn_emboss(instance, *args):
                button._highlight_top.points = [button.x, button.y + button.height, button.x + button.width, button.y + button.height]
                button._highlight_left.points = [button.x, button.y, button.x, button.y + button.height]
                button._shadow_bottom.points = [button.x, button.y, button.x + button.width, button.y]
                button._shadow_right.points = [button.x + button.width, button.y, button.x + button.width, button.y + button.height]

            button.bind(pos=_update_btn_emboss, size=_update_btn_emboss)
        
        _apply_embossed_button(email_btn, light=True)   # Silver button gets light emboss
        _apply_embossed_button(close_btn, light=False)  # Maroon button gets dark emboss
        
        def on_close(instance):
            popup.dismiss()
        
        def on_email(instance):
            """Open email client pre-addressed to The_Zen_Shoppe@icloud.com"""
            popup.dismiss()
            try:
                from jnius import autoclass
                Intent = autoclass('android.content.Intent')
                Uri = autoclass('android.net.Uri')
                PythonActivity = autoclass('org.kivy.android.PythonActivity')
                email_intent = Intent(Intent.ACTION_SENDTO)
                email_intent.setData(Uri.parse('mailto:The_Zen_Shoppe@icloud.com'))
                email_intent.putExtra(Intent.EXTRA_SUBJECT, 'Feedback for Serene Sudoku')
                PythonActivity.mActivity.startActivity(email_intent)
                print("[REVIEW] Email client opened")
            except Exception as e:
                print(f"[REVIEW] Could not open email client: {e}")
        
        close_btn.bind(on_release=on_close)
        email_btn.bind(on_release=on_email)
        
        popup.open()

    def check_row_completion(self, row):
        """Check if a row is completed and correct, and play a gentle slide animation if so."""
        if hasattr(self.game, 'solution'):
            for col in range(9):
                cell = self.sudoku_board.get_cell(row, col)
                val = cell.text.strip()
                sol = str(self.game.solution[row][col])
                if val != sol:
                    break  # Row not complete or incorrect
            else:
                # Row is complete and correct
                self.animate_row_slide(row)

    def check_column_completion(self, col):
        """Check if a column is completed and correct, and play a gentle slide animation if so."""
        if hasattr(self.game, 'solution'):
            for row in range(9):
                cell = self.sudoku_board.get_cell(row, col)
                val = cell.text.strip()
                sol = str(self.game.solution[row][col])
                if val != sol:
                    break  # Column not complete or incorrect
            else:
                # Column is complete and correct
                self.animate_column_slide(col)

    def animate_column_slide(self, col):
        """Animate a gentle up-down slide for all cells in the completed column."""
        from kivy.animation import Animation
        cells = [self.sudoku_board.get_cell(r, col) for r in range(9)]
        # Store original y positions
        orig_y = [cell.y for cell in cells]
        # Slide up by 20px, then down by 10px, then back to original
        def reset_pos(cell, orig):
            cell.pos = (cell.x, orig)
        for idx, cell in enumerate(cells):
            anim = Animation(y=cell.y + 20, duration=0.12, t='out_quad') + \
                   Animation(y=cell.y - 10, duration=0.10, t='in_out_quad') + \
                   Animation(y=cell.y, duration=0.10, t='out_quad')
            anim.bind(on_complete=functools.partial(lambda a, w, orig: reset_pos(w, orig), orig=orig_y[idx]))
            anim.start(cell)

    def animate_row_slide(self, row):
        """Animate a gentle left-right slide for all cells in the completed row."""
        from kivy.animation import Animation
        import functools
        cells = [self.sudoku_board.get_cell(row, c) for c in range(9)]
        # Store original x positions
        orig_x = [cell.x for cell in cells]
        # Slide right by 20px, then back to original
        def reset_pos(cell, orig):
            cell.pos = (orig, cell.y)
        for idx, cell in enumerate(cells):
            anim = Animation(x=cell.x + 20, duration=0.12, t='out_quad') + \
                   Animation(x=cell.x - 10, duration=0.10, t='in_out_quad') + \
                   Animation(x=cell.x, duration=0.10, t='out_quad')
            anim.bind(on_complete=functools.partial(lambda a, w, orig: reset_pos(w, orig), orig=orig_x[idx]))
            anim.start(cell)

    def undo_last_action(self, *args):
        """Undo the last digit or note action."""
        # Block undo if solution is revealed
        if hasattr(self, 'solution_revealed') and self.solution_revealed:
            print("Undo is disabled when the solution is revealed.")
            return
        self._play_undo_sound()
        if not self.action_history:
            print("No actions to undo.")
            return
        last_action = self.action_history.pop()
        action_type = last_action[0]
        row = last_action[1]
        col = last_action[2]
        cell = self.sudoku_board.get_cell(row, col)
        
        # Never undo clue/prepopulated digits
        if cell.is_clue:
            print(f"Cannot undo clue digit at ({row}, {col})")
            # Put the action back since we can't undo it
            self.action_history.append(last_action)
            return
        
        if action_type == 'digit':
            prev_value = last_action[3]
            prev_notes = last_action[4]
            
            if prev_value:  # Restoring a previous digit
                cell.restore_user_value(int(prev_value))
                # Update board state
                self.game.board[row][col] = int(prev_value)
            else:  # Clearing the cell
                cell.clear_digit()
                # Update board state
                self.game.board[row][col] = 0
            
            if prev_notes:
                cell.notes = set(prev_notes)
                cell.update_notes_display()
            else:
                cell.notes.clear()
                cell.update_notes_display()
                
            cell.clear_mistake()
            self.update_digit_buttons()
            print(f"Undo digit at ({row}, {col})")
        elif action_type == 'note':
            prev_notes = last_action[3]
            cell.notes = set(prev_notes)
            cell.update_notes_display()
            print(f"Undo note at ({row}, {col})")
        else:
            print("Unknown action type for undo.")
        
        # Save game state after undo
        if hasattr(self, 'game') and hasattr(self.game, 'puzzle') and hasattr(self.game, 'solution') and hasattr(self.game, 'board'):
            self._save_last_game(self.game.puzzle, self.game.solution, self.game.board, self.last_difficulty, True)


if __name__ == "__main__":
    # Register Japanese font BEFORE app starts - CRITICAL for Android
    from kivy.core.text import LabelBase
    try:
        LabelBase.register(name="msgothic", fn_regular=FONT_PATH_MSGOTHIC)
        print(f"[FONT] Pre-registered Japanese font: {FONT_PATH_MSGOTHIC}")
    except Exception as e:
        print(f"[FONT] WARNING: Could not pre-register Japanese font: {e}")
    
    SudokuApp().run()
