#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import messagebox
import random
import math
import time
import pickle
import os

# Import the separated game logic
from sudoku_game_logic import SudokuGameLogic

# Try to import pygame for audio support
try:
    import pygame
    pygame.mixer.init()
    AUDIO_ENABLED = True
except ImportError:
    AUDIO_ENABLED = False
    print("Pygame not installed. Audio features disabled.")
    print("To enable audio, install pygame: pip install pygame")

# Centering constants for your cell size/font
CENTER_MARGIN = 18  # Updated for cell_size=60 and font size 24; adjust if needed

class SudokuApp:
    def __init__(self, master):
        self.master = master
        master.title("Sudoku App")
        # Set initial window size and position to ensure it's visible
        master.geometry("620x820+100+50")  # width x height + x_offset + y_offset
        master.resizable(False, False)  # Prevent resizing to maintain layout
        self.difficulty = tk.StringVar(value="Easy")
        
        # Initialize the separated game logic
        self.game_logic = SudokuGameLogic()
        
        # Define save file path
        self.save_file_path = os.path.join(os.path.expanduser("~"), "sudoku_save.pkl")
        
        # Initialize default values
        self.resume_available = False
        self.saved_puzzle = None
        self.saved_entries = None
        self.saved_time = 0
        
        # Auto-solve usage tracking
        self.auto_solve_usage = []  # List to store timestamps of auto-solve usage
        self.auto_solved_puzzles = set()  # Set to track which puzzles have been auto-solved
        
        # Initialize audio system
        self.audio_enabled = AUDIO_ENABLED
        self.music_volume = 0.3  # 30% volume for background music
        self.sound_volume = 0.7  # 70% volume for sound effects
        self.music_muted = False
        self.sounds_muted = False
        
        # Audio file paths
        self.audio_dir = os.path.join(os.path.dirname(__file__), "audio")
        self.music_dir = os.path.join(self.audio_dir, "music")
        self.sounds_dir = os.path.join(self.audio_dir, "sounds")
        
        # Load audio files
        self.load_audio_files()
        
        # Initialize game state variables
        self.notes_mode = tk.BooleanVar(value=False)
        self.selected_entry = None
        self.seconds = 0
        self.timer_running = False
        
        # Load any existing saved game from disk
        self.load_persistent_save()
        
        # Set up window close handler to save game state
        master.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.show_welcome_screen()

    def load_persistent_save(self):
        """Load saved game state from disk if it exists"""
        try:
            if os.path.exists(self.save_file_path):
                with open(self.save_file_path, 'rb') as f:
                    save_data = pickle.load(f)
                
                # Restore saved game state
                self.resume_available = save_data.get('resume_available', False)
                self.saved_puzzle = save_data.get('saved_puzzle', None)
                self.saved_entries = save_data.get('saved_entries', None)
                self.saved_notes = save_data.get('saved_notes', None)
                self.saved_time = save_data.get('saved_time', 0)
                self.saved_mistake_count = save_data.get('saved_mistake_count', 0)
                self.saved_hint_count = save_data.get('saved_hint_count', 0)
                self.saved_difficulty = save_data.get('saved_difficulty', None)
                self.auto_solve_usage = save_data.get('auto_solve_usage', [])
                self.saved_solution = save_data.get('saved_solution', None)
                self.saved_current_puzzle = save_data.get('saved_current_puzzle', None)
                
                # Only mark as available if we have valid puzzle data
                if (self.saved_puzzle and self.saved_entries and self.saved_difficulty 
                    and self.saved_solution and self.saved_current_puzzle):
                    self.resume_available = True
                    # Set the difficulty to match the saved game
                    self.difficulty.set(self.saved_difficulty)
                else:
                    self.resume_available = False
        except (FileNotFoundError, pickle.UnpicklingError, KeyError, EOFError):
            # If there's any error loading the save file, start fresh
            self.resume_available = False
            self.saved_puzzle = None
            self.saved_entries = None
            self.saved_time = 0

    def save_persistent_state(self):
        """Save current game state to disk"""
        try:
            save_data = {
                'resume_available': self.resume_available,
                'saved_puzzle': self.saved_puzzle,
                'saved_entries': self.saved_entries,
                'saved_notes': getattr(self, 'saved_notes', None),
                'saved_time': self.saved_time,
                'saved_mistake_count': getattr(self, 'saved_mistake_count', 0),
                'saved_hint_count': getattr(self, 'saved_hint_count', 0),
                'saved_difficulty': getattr(self, 'saved_difficulty', None),
                'auto_solve_usage': getattr(self, 'auto_solve_usage', []),
                'saved_solution': getattr(self, 'saved_solution', None),
                'saved_current_puzzle': getattr(self, 'saved_current_puzzle', None)
            }
            
            with open(self.save_file_path, 'wb') as f:
                pickle.dump(save_data, f)
        except Exception as e:
            # If saving fails, don't crash the program
            print(f"Warning: Could not save game state: {e}")

    def clear_persistent_save(self):
        """Clear the saved game file"""
        try:
            if os.path.exists(self.save_file_path):
                os.remove(self.save_file_path)
        except Exception as e:
            print(f"Warning: Could not clear save file: {e}")

    def on_closing(self):
        """Handle window closing event"""
        # Save current game state if we're in a game (entries exist and we have actual game data)
        if (hasattr(self, 'entries') and self.entries is not None and 
            hasattr(self, 'solution') and hasattr(self, 'current_puzzle')):
            try:
                self.save_current_game()
            except Exception as e:
                # If saving fails, just continue with closing
                print(f"Warning: Could not save game on exit: {e}")
        
        # Save persistent state to disk
        self.save_persistent_state()
        
        # Close the window
        self.master.destroy()

    def load_audio_files(self):
        """Load all audio files"""
        self.music_files = {}
        self.sound_files = {}
        
        if not self.audio_enabled:
            return
        
        # Music files to load
        music_names = {
            'menu': ['menu_music.mp3', 'menu_music.wav'],
            'game': ['game_music.mp3', 'game_music.wav'],  # Fallback generic game music
            'game_easy': ['easy_music.mp3', 'easy_music.wav', 'game_easy.mp3', 'game_easy.wav'],
            'game_moderate': ['moderate_music.mp3', 'moderate_music.wav', 'game_moderate.mp3', 'game_moderate.wav'],
            'game_tough': ['tough_music.mp3', 'tough_music.wav', 'game_tough.mp3', 'game_tough.wav'],
            'game_expert': ['expert_music.mp3', 'expert_music.wav', 'game_expert.mp3', 'game_expert.wav'],
            'game_evil': ['evil_music.mp3', 'evil_music.wav', 'game_evil.mp3', 'game_evil.wav'],
            'game_diabolical': ['diabolical_music.mp3', 'diabolical_music.wav', 'game_diabolical.mp3', 'game_diabolical.wav'],
            'victory': ['victory_music.mp3', 'victory_music.wav'],
            'fail': ['fail_music.mp3', 'fail_music.wav']
        }
        
        # Sound effect files to load
        sound_names = {
            'button_click': ['button_click.wav', 'button_click.mp3'],
            'number_place': ['number_place.wav', 'number_place.mp3'],
            'error': ['error.wav', 'error.mp3'],
            'hint': ['hint.wav', 'hint.mp3'],
            'complete': ['complete.wav', 'complete.mp3'],
            'cell_select': ['cell_select.wav', 'cell_select.mp3'],
            'notes_toggle': ['notes_toggle.wav', 'notes_toggle.mp3'],
            'undo': ['undo.wav', 'undo.mp3'],
            'clear': ['clear.wav', 'clear.mp3'],
            'auto_solve': ['auto_solve.wav', 'auto_solve.mp3'],
            'game_start': ['game_start.wav', 'game_start.mp3'],
            'back_to_menu': ['back_to_menu.wav', 'back_to_menu.mp3']
        }
        
        # Load music files
        for name, filenames in music_names.items():
            for filename in filenames:
                filepath = os.path.join(self.music_dir, filename)
                if os.path.exists(filepath):
                    try:
                        self.music_files[name] = filepath
                        break
                    except Exception as e:
                        print(f"Error loading music {filename}: {e}")
        
        # Load sound files
        for name, filenames in sound_names.items():
            for filename in filenames:
                filepath = os.path.join(self.sounds_dir, filename)
                if os.path.exists(filepath):
                    try:
                        sound = pygame.mixer.Sound(filepath)
                        sound.set_volume(self.sound_volume)
                        self.sound_files[name] = sound
                        break
                    except Exception as e:
                        print(f"Error loading sound {filename}: {e}")

    def get_game_music_name(self, difficulty=None):
        """Get the appropriate game music name based on difficulty level"""
        if difficulty is None:
            difficulty = self.difficulty.get()
        
        # Map difficulty names to music keys
        music_map = {
            'Easy': 'game_easy',
            'Moderate': 'game_moderate', 
            'Tough': 'game_tough',
            'Expert': 'game_expert',
            'Evil': 'game_evil',
            'Diabolical': 'game_diabolical'
        }
        
        music_name = music_map.get(difficulty, 'game')
        
        # Fall back to generic 'game' music if specific difficulty music not found
        if music_name not in self.music_files and 'game' in self.music_files:
            music_name = 'game'
        
        return music_name

    def get_music_display_name(self, music_key):
        """Get a friendly display name for a music track"""
        display_names = {
            'menu': 'Menu Music',
            'game': 'Game Music',
            'game_easy': 'Easy Mode Music',
            'game_moderate': 'Moderate Mode Music',
            'game_tough': 'Tough Mode Music', 
            'game_expert': 'Expert Mode Music',
            'game_evil': 'Evil Mode Music',
            'game_diabolical': 'Diabolical Mode Music',
            'victory': 'Victory Music',
            'fail': 'Failure Music'
        }
        return display_names.get(music_key, music_key)

    def play_music(self, music_name, loop=True):
        """Play background music"""
        if not self.audio_enabled or self.music_muted or music_name not in self.music_files:
            return
        
        try:
            pygame.mixer.music.load(self.music_files[music_name])
            pygame.mixer.music.set_volume(self.music_volume)
            loops = -1 if loop else 0  # -1 means infinite loop
            pygame.mixer.music.play(loops)
        except Exception as e:
            print(f"Error playing music {music_name}: {e}")

    def stop_music(self):
        """Stop background music"""
        if self.audio_enabled:
            try:
                pygame.mixer.music.stop()
            except Exception as e:
                print(f"Error stopping music: {e}")

    def play_sound(self, sound_name):
        """Play a sound effect"""
        if not self.audio_enabled or self.sounds_muted or sound_name not in self.sound_files:
            return
        
        try:
            self.sound_files[sound_name].play()
        except Exception as e:
            print(f"Error playing sound {sound_name}: {e}")

    def set_music_volume(self, volume):
        """Set music volume (0.0 to 1.0)"""
        self.music_volume = max(0.0, min(1.0, volume))
        if self.audio_enabled:
            pygame.mixer.music.set_volume(self.music_volume)

    def set_sound_volume(self, volume):
        """Set sound effects volume (0.0 to 1.0)"""
        self.sound_volume = max(0.0, min(1.0, volume))
        for sound in self.sound_files.values():
            sound.set_volume(self.sound_volume)

    def toggle_music(self):
        """Toggle music on/off"""
        self.music_muted = not self.music_muted
        if self.music_muted:
            self.stop_music()
        else:
            # Resume appropriate music based on current screen
            if hasattr(self, 'entries') and self.entries:
                game_music = self.get_game_music_name()
                self.play_music(game_music)
            else:
                self.play_music('menu')

    def toggle_sounds(self):
        """Toggle sound effects on/off"""
        self.sounds_muted = not self.sounds_muted

    def show_welcome_screen(self):
        # Stop any game music and play menu music
        self.stop_music()
        self.play_music('menu')
        
        for widget in self.master.winfo_children():
            widget.destroy()

        welcome_frame = tk.Frame(self.master)
        welcome_frame.pack(padx=30, pady=30)

        # Embossed "Sadistically Savage Sudoku" title, split into two lines, always visible and centered
        emboss_frame = tk.Frame(welcome_frame)
        emboss_frame.pack(pady=10)

        # Try to use a Gothic-style font; fallback to Arial if not available
        gothic_font = ("Old English Text MT", 26, "bold")
        try:
            test_label = tk.Label(emboss_frame, font=gothic_font)
            test_label.destroy()
        except:
            gothic_font = ("Arial", 26, "bold")

        # First line: "Sadistically Savage"
        tk.Label(
            emboss_frame,
            text="Sadistically Savage",
            font=gothic_font,
            fg="#800000",  # Maroon red, matches Expert level
            bg=emboss_frame.cget("bg")
        ).pack(anchor="center")

        # Second line: "Sudoku"
        tk.Label(
            emboss_frame,
            text="Sudoku",
            font=gothic_font,
            fg="#800000",  # Maroon red, matches Expert level
            bg=emboss_frame.cget("bg")
        ).pack(anchor="center")

        # Change label to "Select Pain Tolerance:"
        tk.Label(welcome_frame, text="Select Pain Tolerance:", font=("Arial", 14)).pack(pady=5)

        # Difficulty button colors
        diff_colors = {
            "Easy": "#228B22",         # Forest green (matches game screen)
            "Moderate": "#ffe066",     # Gold
            "Tough": "#ffa366",        # Orange
            "Expert": "#800000",       # Maroon
            "Evil": "#a366ff",         # Purple
            "Diabolical": "#22223b"    # Dark Blue
        }

        # Center difficulty buttons in a frame
        diff_btn_frame = tk.Frame(welcome_frame)
        diff_btn_frame.pack(pady=10)

        def set_difficulty(diff):
            self.difficulty.set(diff)
            # Visually indicate selection
            for btn in diff_btns:
                btn.config(relief=tk.RAISED, bd=4)
            diff_btns[difficulties.index(diff)].config(relief=tk.SUNKEN, bd=6)

        difficulties = ["Easy", "Moderate", "Tough", "Expert", "Evil", "Diabolical"]
        diff_btns = []
        for diff in difficulties:
            btn = tk.Button(
                diff_btn_frame,
                text=diff,
                font=("Arial", 13, "bold"),
                width=14,
                height=2,
                bg=diff_colors[diff],
                fg="white" if diff != "Moderate" else "#444",
                activebackground=diff_colors[diff],
                activeforeground="white" if diff != "Moderate" else "#444",
                relief=tk.SUNKEN if self.difficulty.get() == diff else tk.RAISED,
                bd=6 if self.difficulty.get() == diff else 4,  # Thicker border for 3D effect
                highlightthickness=2,
                highlightbackground="#888",
                highlightcolor="#fff",
                command=lambda d=diff: set_difficulty(d)
            )
            btn.pack(pady=6)
            diff_btns.append(btn)

        # "Then Play:" text centered below difficulty buttons
        tk.Label(
            welcome_frame,
            text="Then Play:",
            font=("Arial", 14, "bold"),
            fg="#333333"
        ).pack(pady=(15, 5))

        btn_frame = tk.Frame(welcome_frame)
        btn_frame.pack(pady=20)

        # 3D effect for main action buttons as well
        tk.Button(
            btn_frame, text="New Game", font=("Arial", 12, "bold"), width=12,
            bg="#4169e1",  # Bright royal blue
            fg="white",
            activebackground="#27408b",  # Slightly darker blue on press
            activeforeground="white",
            relief=tk.RAISED, bd=6, highlightthickness=2, highlightbackground="#888",
            command=self.start_new_game
        ).pack(side=tk.LEFT, padx=5)

        # Determine resume button text and size based on last started game
        if self.resume_available and hasattr(self, "saved_difficulty") and self.saved_difficulty:
            if self.saved_difficulty == "Diabolical":
                resume_text = "Kill Me Already"
                resume_btn_height = 1
            elif self.saved_difficulty in ("Moderate", "Expert"):
                resume_text = f"Resume {self.saved_difficulty}\nGame"
                resume_btn_height = 3  # Make button taller for wrapped text
            else:
                resume_text = f"Resume {self.saved_difficulty} Game"
                resume_btn_height = 1
            resume_btn_width = 16  # Wider button when there's text to display
        else:
            resume_text = ""  # No text when no game to resume
            resume_btn_height = 1
            resume_btn_width = 12  # Same width as "New Game" button when no game to resume

        # Adjust window height based on resume button height
        if resume_btn_height == 3:
            # Need extra height for two-line resume button
            self.master.geometry("620x860")  # Increased height for taller resume button
        else:
            # Standard height for single-line or no resume button
            self.master.geometry("620x820")  # Standard height with "Then Play:" text

        self.resume_btn = tk.Button(
            btn_frame,
            text=resume_text,
            font=("Arial", 12, "bold"),
            width=resume_btn_width,
            height=resume_btn_height,
            justify="center",
            relief=tk.RAISED,
            bd=6,
            highlightthickness=2,
            highlightbackground="#888",
            bg="#666666",            # Slightly lighter grey background
            fg="white",              # White font
            activebackground="#444", # Slightly darker on press
            activeforeground="white",
            command=self.resume_game,
            state=tk.NORMAL if self.resume_available else tk.DISABLED
        )
        self.resume_btn.pack(side=tk.LEFT, padx=5)

        # TEMPORARY: Test button for reward screen (always visible)
        test_frame = tk.Frame(welcome_frame, bg="red")  # Red background to make it obvious
        test_frame.pack(pady=20, fill="x")
        
        tk.Button(
            test_frame,
            text="🧪 TEST REWARD SCREEN 🧪",
            font=("Arial", 14, "bold"),
            bg="#ff0000",
            fg="white",
            activebackground="#cc0000",
            activeforeground="white",
            relief=tk.RAISED,
            bd=6,
            width=25,
            height=2,
            command=self.test_show_reward_screen
        ).pack(pady=10)

    def test_show_reward_screen(self):
        """Temporary method to test the reward screen without solving a puzzle"""
        # Set a fake completion time for testing
        self.completion_time = "12:34"
        self.show_reward_screen()

    def toggle_music_and_update_ui(self):
        """Toggle music and update the button text"""
        self.toggle_music()
        if hasattr(self, 'music_btn'):
            music_text = "🔇 Music" if self.music_muted else "🔊 Music"
            self.music_btn.config(text=music_text)

    def toggle_sounds_and_update_ui(self):
        """Toggle sounds and update the button text"""
        self.toggle_sounds()
        if hasattr(self, 'sounds_btn'):
            sounds_text = "🔇 Sounds" if self.sounds_muted else "🔊 Sounds"
            self.sounds_btn.config(text=sounds_text)

    def start_new_game(self):
        self.play_sound('button_click')
        
        # Check if there's an unfinished game
        if self.resume_available and hasattr(self, 'saved_difficulty') and self.saved_difficulty:
            # Preserve current window position before showing popup
            current_geometry = self.master.geometry()
            # Show confirmation popup before starting new game
            if not self.show_ditch_game_popup():
                return  # User clicked "No", so don't start new game
            # Restore the window position after popup closes
            self.master.geometry(current_geometry)
        
        self.resume_available = True
        self.saved_puzzle = None
        self.saved_entries = None
        self.saved_time = 0
        self.saved_difficulty = self.difficulty.get()  # Track which difficulty is being played
        self.show_game_screen(new_game=True)

    def show_ditch_game_popup(self):
        """Shows a popup asking if user wants to ditch their current game. Returns True if Yes, False if No."""
        # Get the colors for the saved game difficulty
        diff_colors = {
            "Easy": "#228B22",         # Forest green
            "Moderate": "#ffe066",     # Gold
            "Tough": "#ffa366",        # Orange
            "Expert": "#800000",       # Maroon
            "Evil": "#a366ff",         # Purple
            "Diabolical": "#22223b"    # Dark Blue/Black
        }
        
        saved_diff = getattr(self, 'saved_difficulty', 'Easy')
        bg_color = diff_colors.get(saved_diff, "#ffffff")
        
        # Set text color based on difficulty for best contrast
        if saved_diff == "Easy":
            text_fg = "white"
        elif saved_diff in ("Tough", "Moderate"):
            text_fg = "black"
        elif saved_diff == "Expert":
            text_fg = "white"
        elif saved_diff == "Evil":
            text_fg = "white"
        elif saved_diff == "Diabolical":
            text_fg = "white"
        else:
            text_fg = "black"
        
        # Create popup window
        popup = tk.Toplevel(self.master)
        popup.title("")
        popup.geometry("300x150")
        popup.resizable(False, False)
        popup.configure(bg=bg_color)
        
        # Center the popup over the main window
        popup.transient(self.master)
        popup.grab_set()  # Make it modal
        
        # Center the popup
        popup.update_idletasks()
        x = (popup.winfo_screenwidth() // 2) - (popup.winfo_width() // 2)
        y = (popup.winfo_screenheight() // 2) - (popup.winfo_height() // 2)
        popup.geometry(f"+{x}+{y}")
        
        # Result variable to track user choice
        result = [False]  # Use list so it can be modified in nested functions
        
        def on_yes():
            # Clear the popup and show "That was cold." message
            for widget in popup.winfo_children():
                widget.destroy()
            
            # Choose message based on saved difficulty
            if saved_diff == "Diabolical":
                cold_message = "You'll pay for that."
            else:
                cold_message = "That was cold."
            
            # Show the appropriate message
            cold_label = tk.Label(
                popup,
                text=cold_message,
                font=("Arial", 14, "bold"),
                fg=text_fg,
                bg=bg_color
            )
            cold_label.pack(pady=(30, 20))
            
            # OK button frame
            ok_frame = tk.Frame(popup, bg=bg_color)
            ok_frame.pack(pady=10)
            
            def on_ok():
                result[0] = True
                popup.destroy()
            
            # OK button
            ok_btn = tk.Button(
                ok_frame,
                text="OK",
                font=("Arial", 12, "bold"),
                width=8,
                height=1,
                bg="#cccccc",  # Grey background
                fg="black",    # Black text
                activebackground="#bbbbbb",
                activeforeground="black",
                relief=tk.RAISED,
                bd=4,
                command=on_ok
            )
            ok_btn.pack()
        
        def on_no():
            result[0] = False
            popup.destroy()
        
        # Main text label
        text_label = tk.Label(
            popup,
            text="Ditch your last game?",
            font=("Arial", 14, "bold"),
            fg=text_fg,
            bg=bg_color
        )
        text_label.pack(pady=(30, 20))
        
        # Button frame
        button_frame = tk.Frame(popup, bg=bg_color)
        button_frame.pack(pady=10)
        
        # Yes button
        yes_btn = tk.Button(
            button_frame,
            text="Yes",
            font=("Arial", 12, "bold"),
            width=8,
            height=1,
            bg="#cccccc",  # Grey background
            fg="black",    # Black text
            activebackground="#bbbbbb",
            activeforeground="black",
            relief=tk.RAISED,
            bd=4,
            command=on_yes
        )
        yes_btn.pack(side=tk.LEFT, padx=5)
        
        # No button
        no_btn = tk.Button(
            button_frame,
            text="No",
            font=("Arial", 12, "bold"),
            width=8,
            height=1,
            bg="#cccccc",  # Grey background
            fg="black",    # Black text
            activebackground="#bbbbbb",
            activeforeground="black",
            relief=tk.RAISED,
            bd=4,
            command=on_no
        )
        no_btn.pack(side=tk.LEFT, padx=5)
        
        # Wait for the popup to be closed
        popup.wait_window()
        
        return result[0]

    def resume_game(self):
        self.play_sound('button_click')
        
        # Only resume if resume is available and there is a saved puzzle
        if (
            self.resume_available
            and self.saved_puzzle is not None
            and self.saved_entries is not None
            and hasattr(self, "saved_difficulty")
            and self.saved_difficulty
        ):
            # Set the difficulty to match the saved game before resuming
            self.difficulty.set(self.saved_difficulty)
            self.show_game_screen(new_game=False)
        else:
            # Do nothing if no game is available to resume
            pass

    def show_game_screen(self, new_game=True):
        # Play game start sound
        if new_game:
            self.play_sound('game_start')
        
        # Stop menu music and play difficulty-specific game music
        self.stop_music()
        game_music = self.get_game_music_name()
        self.play_music(game_music)
        
        # Stop any existing timer before creating new screen
        self.timer_running = False
        
        # Preserve current window position when transitioning from popup/welcome to game
        current_geometry = self.master.geometry()
        if '+' in current_geometry:
            # Extract current position from geometry string (format: "WIDTHxHEIGHT+X+Y")
            size_part, pos_part = current_geometry.split('+', 1)
            x_pos = pos_part.split('+')[0] if '+' in pos_part else pos_part.split('-')[0]
            y_pos = pos_part.split('+')[1] if '+' in pos_part else pos_part.split('-')[1]
            # Set new size but keep current position
            self.master.geometry(f"620x950+{x_pos}+{y_pos}")
        else:
            # Fallback to default position if no position info available
            self.master.geometry("620x950+100+50")
        
        for widget in self.master.winfo_children():
            widget.destroy()

        # Difficulty colors (same as welcome screen)
        diff_colors = {
            "Easy": "#228B22",         # Forest green
            "Moderate": "#ffe066",     # Gold
            "Tough": "#ffa366",        # Orange
            "Expert": "#800000",       # Maroon
            "Evil": "#a366ff",         # Purple
            "Diabolical": "#22223b"    # Dark Blue/Black
        }
        current_diff = self.difficulty.get()
        bg_color = diff_colors.get(current_diff, "#ffffff")
        self.master.configure(bg=bg_color)

        # Set text and button color for each difficulty for best contrast
        if current_diff == "Easy":
            text_fg = "white"           # White text for Easy
            btn_bg = "SystemButtonFace"
            btn_font = ("Arial", 12, "bold")
            btn_fg = "black"
        elif current_diff in ("Tough", "Moderate"):
            text_fg = "black"
            btn_bg = "SystemButtonFace"
            btn_font = ("Arial", 12, "bold")
            btn_fg = "black"
        elif current_diff == "Expert":
            text_fg = "white"
            btn_bg = "SystemButtonFace"
            btn_font = ("Arial", 12, "bold")
            btn_fg = "black"
        elif current_diff == "Evil":
            text_fg = "white"
            btn_bg = "SystemButtonFace"
            btn_font = ("Arial", 12, "bold")
            btn_fg = "black"
        elif current_diff == "Diabolical":
            text_fg = "white"
            btn_bg = "#333"
            btn_font = ("Arial", 12)
            btn_fg = text_fg
        else:
            text_fg = "#4169e1"
            btn_bg = bg_color
            btn_font = ("Arial", 12)
            btn_fg = text_fg

        # Difficulty label above the timer (just the name)
        tk.Label(
            self.master,
            text=current_diff,
            font=("Arial", 14, "bold"),
            fg=text_fg,
            bg=bg_color
        ).pack(pady=(10, 0))

        self.timer_label = tk.Label(self.master, text="00:00", font=("Arial", 14), fg=text_fg, bg=bg_color)
        self.timer_label.pack(pady=5)
        self.seconds = 0 if new_game or self.saved_time is None else self.saved_time
        self.timer_running = False

        self.selected_entry = None
        self.notes_mode = tk.BooleanVar(value=False)

        self.create_widgets()



        # Notes mode toggle
        # Create a custom checkbox solution to handle text and checkmark colors separately
        notes_frame = tk.Frame(self.master, bg=bg_color)
        notes_frame.pack(pady=2)
        
        # Set text color based on difficulty for better visibility
        if current_diff in ("Easy", "Expert", "Evil", "Diabolical"):
            notes_text_color = "white"
        else:
            notes_text_color = "black"
        
        # Create a standard checkbox with black foreground (for visible checkmark)
        notes_toggle = tk.Checkbutton(
            notes_frame, text="", variable=self.notes_mode, font=("Arial", 12),
            fg="black", bg=bg_color, selectcolor="white",
            activeforeground="black", activebackground=bg_color,
            command=self.toggle_notes_mode
        )
        notes_toggle.pack(side=tk.LEFT)
        
        # Create a separate label with the desired text color
        notes_label = tk.Label(
            notes_frame, text="Notes Mode", font=("Arial", 12),
            fg=notes_text_color, bg=bg_color
        )
        notes_label.pack(side=tk.LEFT, padx=(2, 0))
        
        # Stone Cold Digit Lock button (initially hidden)
        self.stone_cold_locked = False
        self.stone_cold_selected_digit = None
        self.stone_cold_button = tk.Button(
            notes_frame, text="🔓 Stone Cold Digit Lock", 
            font=("Arial", 12, "bold"),
            fg="black", bg="SystemButtonFace",
            activebackground="SystemButtonFace", activeforeground="black",
            relief=tk.RAISED, bd=2,
            command=self.toggle_stone_cold_lock
        )
        # Don't pack initially - will be shown when notes mode is enabled

        # Number buttons 1-9 arranged in 2 rows
        self.num_buttons = []
        self.original_btn_bg = btn_bg  # Store original button background color
        num_btn_frame = tk.Frame(self.master, bg=bg_color)
        num_btn_frame.pack(pady=5)
        
        # Top row: buttons 1-5
        top_row_frame = tk.Frame(num_btn_frame, bg=bg_color)
        top_row_frame.pack(pady=2)
        
        for n in range(1, 6):
            btn = tk.Button(
                top_row_frame, text=str(n), font=("Arial", 16, "bold"), width=4, height=2,
                fg=btn_fg, bg=btn_bg,
                activebackground=btn_bg, activeforeground=btn_fg,
                relief=tk.RAISED, bd=4,
                command=lambda d=n: self.handle_number_button(d)
            )
            btn.pack(side=tk.LEFT, padx=3)
            self.num_buttons.append(btn)
        
        # Bottom row: buttons 6-9 (centered)
        bottom_row_frame = tk.Frame(num_btn_frame, bg=bg_color)
        bottom_row_frame.pack(pady=2)
        
        for n in range(6, 10):
            btn = tk.Button(
                bottom_row_frame, text=str(n), font=("Arial", 16, "bold"), width=4, height=2,
                fg=btn_fg, bg=btn_bg,
                activebackground=btn_bg, activeforeground=btn_fg,
                relief=tk.RAISED, bd=4,
                command=lambda d=n: self.handle_number_button(d)
            )
            btn.pack(side=tk.LEFT, padx=3)
            self.num_buttons.append(btn)

        # Clear button centered under digits 7 and 8, with Hint and Undo buttons on the right
        clear_row_frame = tk.Frame(num_btn_frame, bg=bg_color)
        clear_row_frame.pack(pady=5)
        
        # Create a grid-like layout to precisely position buttons
        # Calculate the position: buttons 6,7,8,9 with 3 padx spacing each
        # Button width=4 (chars), with font Arial 16 this is about 40 pixels
        # Padding is 3 pixels between buttons
        # So button 6 starts at 0, button 7 starts at ~43, button 8 starts at ~86, button 9 starts at ~129
        # Center of buttons 7 and 8 would be at around position 43 + 43/2 = 64.5
        
        # Use place geometry manager for precise positioning
        clear_row_frame.configure(width=400, height=60)
        clear_row_frame.pack_propagate(False)
        
        # Clear button positioned to align with center of buttons 7 and 8
        clear_button = tk.Button(
            clear_row_frame, text="Clear", font=("Arial", 16, "bold"), width=8, height=2,
            fg=btn_fg, bg=btn_bg,
            activebackground=btn_bg, activeforeground=btn_fg,
            relief=tk.RAISED, bd=4,
            command=self.handle_erase
        )
        clear_button.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        # Right side buttons frame positioned on the right
        right_buttons_frame = tk.Frame(clear_row_frame, bg=bg_color)
        right_buttons_frame.place(relx=0.95, rely=0.5, anchor=tk.E)
        
        # Hint button (only for Easy, Moderate, and Tough levels) - appears above Undo
        if current_diff in ("Easy", "Moderate", "Tough"):
            # Check if hints are exhausted
            hint_exhausted = hasattr(self, 'hint_count') and self.hint_count >= 2
            
            self.hint_button = tk.Button(
                right_buttons_frame, text="💡 Hint", font=("Arial", 12, "bold"), width=8, height=1,
                fg="black" if not hint_exhausted else "#666666",
                bg=btn_bg if not hint_exhausted else "#666666",
                activebackground=btn_bg if not hint_exhausted else "#666666",
                activeforeground="black" if not hint_exhausted else "#666666",
                relief=tk.RAISED, bd=4,
                state="normal" if not hint_exhausted else "disabled",
                command=self.give_hint
            )
            self.hint_button.pack(pady=(0, 2))
        
        # Undo button - appears below Hint (or alone if no Hint button)
        undo_button = tk.Button(
            right_buttons_frame, text="Undo", font=("Arial", 12, "bold"), width=8, height=1,
            fg="black", bg="#cccccc",
            activebackground="#bbbbbb", activeforeground="black",
            relief=tk.RAISED, bd=4,
            command=self.handle_undo
        )
        undo_button.pack(pady=(2, 0))

        # Back button and Auto-solve button - centered below the digit row
        back_btn_frame = tk.Frame(self.master, bg=bg_color)
        back_btn_frame.pack(pady=10)
        
        tk.Button(
            back_btn_frame, text="Back", command=self.back_to_welcome,
            fg=btn_fg, bg=btn_bg,
            activebackground=btn_bg, activeforeground=btn_fg,
            font=("Arial", 12, "bold"), relief=tk.RAISED, bd=4
        ).pack(side=tk.LEFT, padx=5)
        
        # Auto-Solve button (only for Easy, Moderate, Tough, and Expert levels and if usage limit not reached)
        if current_diff in ("Easy", "Moderate", "Tough", "Expert") and self.is_auto_solve_available():
            self.auto_solve_button = tk.Button(
                back_btn_frame, text="Auto-Solve", command=self.auto_solve,
                fg=btn_fg, bg=btn_bg,
                activebackground=btn_bg, activeforeground=btn_fg,
                font=("Arial", 12, "bold"), relief=tk.RAISED, bd=4
            )
            self.auto_solve_button.pack(side=tk.LEFT, padx=5)
            self.auto_solve_button_parent = back_btn_frame  # Store parent for re-packing later

        if new_game or not self.saved_puzzle:
            self.generate_puzzle()
        else:
            self.load_saved_game()

        self.start_timer()

        # Initialize mistake count only for new games
        if new_game or not hasattr(self, 'mistake_count'):
            self.mistake_count = 0
        
        # Initialize hint count for new games
        if new_game or not hasattr(self, 'hint_count'):
            self.hint_count = 0

        # Mistake counter label
        self.mistake_label = tk.Label(
            self.master,
            text=f"Mistakes: {self.mistake_count}",
            font=("Arial", 14, "bold"),
            fg="white" if current_diff == "Expert" else "red",
            bg=bg_color
        )
        self.mistake_label.place(relx=1.0, y=10, anchor="ne", x=-20)

        # Add Reset button (top left)
        reset_btn = tk.Button(
            self.master,
            text="Reset",
            font=("Arial", 12, "bold"),
            bg="SystemButtonFace",  # Same as other buttons
            fg="black",
            activebackground="SystemButtonFace",
            activeforeground="black",
            relief=tk.RAISED,
            bd=4,
            command=self.reset_puzzle
        )
        reset_btn.place(x=20, y=15)  # Top left corner with some padding

        # Initialize the undo stack
        self.undo_stack = []

    def reset_puzzle(self):
        # Stop the current timer to prevent multiple timers running
        self.timer_running = False
        # Regenerate the current puzzle at the same difficulty
        self.show_game_screen(new_game=True)

    def back_to_welcome(self):
        self.play_sound('back_to_menu')
        self.save_current_game()
        self.show_welcome_screen()

    def save_current_game(self):
        # Only save if we're actually in a game with valid entries
        if not (hasattr(self, 'entries') and self.entries is not None):
            return
            
        # Save both the visible text and the notes for each cell
        self.saved_puzzle = [[self.entries[i][j].get("1.0", tk.END).strip() for j in range(9)] for i in range(9)]
        self.saved_entries = [[self.entries[i][j]['state'] for j in range(9)] for i in range(9)]
        self.saved_notes = [[set(self.notes[i][j]) for j in range(9)] for i in range(9)]
        self.saved_time = self.seconds
        self.saved_mistake_count = self.game_logic.mistake_count
        self.saved_hint_count = self.game_logic.hint_count
        
        # Save critical game state for proper restoration
        if hasattr(self, 'solution'):
            self.saved_solution = [row[:] for row in self.solution]
        if hasattr(self, 'current_puzzle'):
            self.saved_current_puzzle = [row[:] for row in self.current_puzzle]
        
        self.resume_available = True
        
        # Also save to disk for persistence
        self.save_persistent_state()

    def load_saved_game(self):
        for i in range(9):
            for j in range(9):
                text = self.entries[i][j]
                text.config(state='normal')
                text.delete('1.0', tk.END)
                val = self.saved_puzzle[i][j]
                if val:
                    text.insert('1.0', val)
                    # Use black for prepopulated digits, blue for user input
                    if self.saved_entries[i][j] == 'disabled':
                        # This is a clue cell - use the standard clue font
                        fg_color = 'black'
                        font_config = ('Copperplate Gothic Bold', 24)
                    else:
                        # This is a user entry - use the game font for user entries
                        fg_color = '#5599cc'  # Lighter blue color to match new games
                        font_config = ('Ink Journal', 28)
                    
                    text.tag_configure(
                        'center',
                        justify='center',
                        font=font_config,
                        foreground=fg_color,
                        lmargin1=0, lmargin2=0, rmargin=0,
                        spacing1=0 if self.saved_entries[i][j] == 'normal' else 8,
                        spacing3=0 if self.saved_entries[i][j] == 'normal' else 8
                    )
                    text.tag_add('center', '1.0', 'end')
                text.config(state=self.saved_entries[i][j])
        
        # Load saved notes if they exist
        if hasattr(self, 'saved_notes') and self.saved_notes:
            for i in range(9):
                for j in range(9):
                    if i < len(self.saved_notes) and j < len(self.saved_notes[i]):
                        self.notes[i][j] = set(self.saved_notes[i][j])
                        # Sync with game logic
                        for note in self.notes[i][j]:
                            self.game_logic.toggle_note(i, j, note)
                        # Update the display to show the notes with correct formatting
                        if self.notes[i][j]:  # Only update display if there are notes
                            self.update_notes_display(i, j)
        
        # Load the saved mistake count and sync with game logic
        self.mistake_count = getattr(self, 'saved_mistake_count', 0)
        self.game_logic.mistake_count = self.mistake_count
        
        # Load the saved hint count and sync with game logic
        self.hint_count = getattr(self, 'saved_hint_count', 0)
        self.game_logic.hint_count = self.hint_count
        
        # Restore critical game state
        if hasattr(self, 'saved_solution') and self.saved_solution:
            self.solution = [row[:] for row in self.saved_solution]
            self.game_logic.solution = [row[:] for row in self.saved_solution]
        if hasattr(self, 'saved_current_puzzle') and self.saved_current_puzzle:
            self.current_puzzle = [row[:] for row in self.saved_current_puzzle]
            self.game_logic.current_puzzle = [row[:] for row in self.saved_current_puzzle]
        
        # Initialize completion tracking for animations
        self.initialize_completion_tracking()

    def create_widgets(self):
        cell_size = 60  # Increased from 54 to 60 for larger board
        board_size = cell_size * 9

        self.board_frame = tk.Frame(self.master, width=board_size, height=board_size)
        self.board_frame.pack()
        self.board_frame.pack_propagate(False)

        self.canvas = tk.Canvas(self.board_frame, width=board_size, height=board_size)
        self.canvas.place(x=0, y=0)

        for i in range(10):
            line_width = 3 if i % 3 == 0 else 1
            self.canvas.create_line(i * cell_size, 0, i * cell_size, board_size, width=line_width)
            self.canvas.create_line(0, i * cell_size, board_size, i * cell_size, width=line_width)

        self.entries = [[None for _ in range(9)] for _ in range(9)]
        self.notes = [[set() for _ in range(9)] for _ in range(9)]
        for i in range(9):
            for j in range(9):
                text = tk.Text(
                    self.board_frame,
                    width=4, height=3,
                    font=('Courier', 10),
                    bd=0, relief='flat', wrap='none',
                    insertbackground='white',  # Hide cursor by making it white on white
                    inactiveselectbackground='white',  # Hide selection
                    selectbackground='white',  # Hide selection even when active
                    cursor='arrow',  # Arrow cursor instead of text
                    takefocus=0,  # Prevents focus and disables blinking cursor
                    insertwidth=0,  # Make cursor width 0 to hide it completely
                    insertofftime=0,  # Disable cursor blinking
                    insertontime=0,  # Disable cursor blinking
                    exportselection=0  # Disable text selection completely
                )
                text.place(
                    x=j * cell_size + 2,
                    y=i * cell_size + 2,
                    width=cell_size-4,
                    height=cell_size-4
                )
                text.bind("<Button-1>", lambda e, row=i, col=j: self.select_entry(row, col))
                text.bind("<FocusIn>", lambda e, row=i, col=j: self.select_entry(row, col))
                # Prevent double-click text selection
                text.bind("<Double-Button-1>", lambda e, row=i, col=j: self.select_entry(row, col))
                text.bind("<Triple-Button-1>", lambda e, row=i, col=j: self.select_entry(row, col))
                text.bind("<B1-Motion>", lambda e: "break")  # Prevent drag selection
                text.bind("<Shift-Button-1>", lambda e: "break")  # Prevent shift-click selection
                # Block all keyboard input in the cell
                text.bind("<Key>", lambda e: "break")
                text.bind("<Control-v>", lambda e: "break")
                text.bind("<Control-c>", lambda e: "break")
                text.bind("<Control-x>", lambda e: "break")
                text.bind("<Control-a>", lambda e: "break")  # Prevent select all
                text.config(state='disabled')
                self.entries[i][j] = text

        # Track the currently highlighted cell
        self.highlighted_cell = None

    def hide_cursor(self, text_widget):
        """Completely hide the cursor in a text widget"""
        text_widget.config(
            insertwidth=0,
            insertofftime=0,
            insertontime=0,
            insertbackground=text_widget.cget('bg')  # Make cursor same color as background
        )

    def select_entry(self, row, col):
        # Play cell selection sound
        self.play_sound('cell_select')
        
        # Prevent double-execution due to both Button-1 and FocusIn events
        if (hasattr(self, '_last_selection_time') and 
            hasattr(self, '_last_selection_cell') and
            self._last_selection_cell == (row, col) and
            time.time() - self._last_selection_time < 0.1):
            return
        
        self._last_selection_time = time.time()
        self._last_selection_cell = (row, col)
        
        # Handle Stone Cold Digit Lock when clicking cells
        if (self.stone_cold_locked and 
            self.stone_cold_selected_digit is not None and 
            self.notes_mode.get()):
            
            # Check if the cell is editable (not a clue cell)
            text = self.entries[row][col]
            
            # Allow adding notes to any cell that is not a clue cell and doesn't have a solution digit
            if (text['state'] == 'normal' and 
                (not hasattr(self, "current_puzzle") or self.current_puzzle[row][col] == 0)):
                
                # Check if cell has a solution digit by looking at the text content and tags
                cell_content = text.get("1.0", "end-1c").strip()
                
                # A solution digit is marked with 'center' tag (main digits), not 'notes' tag
                # If the cell has the 'center' tag, it contains a main digit
                has_solution_digit = 'center' in text.tag_names('1.0')
                
                # Only add note if cell doesn't have a solution digit
                if not has_solution_digit:
                    # Ensure the text widget is in the correct state
                    text.config(state='normal')
                    
                    # Save undo state before making changes
                    self.undo_stack.append({
                        'row': row,
                        'col': col,
                        'value': text.get('1.0', 'end-1c'),
                        'bg': text.cget('bg'),
                        'fg': text.tag_cget('center', 'foreground') if 'center' in text.tag_names() else text.cget('fg'),
                        'notes': set(self.notes[row][col])
                    })
                    
                    # Toggle the selected digit in notes (add if not present, remove if present)
                    digit = self.stone_cold_selected_digit
                    notes = self.notes[row][col]
                    if digit in notes:
                        notes.remove(digit)  # Remove if already present
                    else:
                        notes.add(digit)     # Add if not present
                    self.update_notes_display(row, col)
        
        # Always proceed with normal cell selection logic regardless of Stone Cold Lock state
        # Remove highlight from previous cell
        if hasattr(self, "highlighted_cell") and self.highlighted_cell:
            prev_row, prev_col = self.highlighted_cell
            prev_text = self.entries[prev_row][prev_col]
            # Only reset if not a clue cell
            if prev_text['state'] == 'normal':
                prev_text.config(bg="white")
                # Restore original tag backgrounds for normal cells
                for tag in prev_text.tag_names():
                    if tag == 'center':
                        prev_text.tag_configure(tag, background="white")
                    elif tag == 'notes':
                        prev_text.tag_configure(tag, background="white")
                    elif tag == 'hint':
                        prev_text.tag_configure(tag, background="#90EE90")  # Light green for hints
                    elif tag == 'auto_solve':
                        # Determine auto-solve background based on difficulty
                        current_diff = self.difficulty.get()
                        if current_diff in ("Moderate", "Tough"):
                            prev_text.tag_configure(tag, background="#ADD8E6")  # Light blue
                        else:
                            prev_text.tag_configure(tag, background="#FFD700")  # Gold
            else:
                prev_text.config(bg="SystemButtonFace")
                # Restore original tag backgrounds for clue cells
                for tag in prev_text.tag_names():
                    if tag == 'center':
                        prev_text.tag_configure(tag, background="SystemButtonFace")
        
        # Clear all light blue backgrounds from cells (to handle undo trail)
        for i in range(9):
            for j in range(9):
                cell_text = self.entries[i][j]
                if cell_text.cget('bg') == "#b3daff" and (i != row or j != col):
                    # Reset background to normal color
                    if cell_text['state'] == 'normal':
                        cell_text.config(bg="white")
                        # Restore original tag backgrounds for normal cells
                        for tag in cell_text.tag_names():
                            if tag == 'center':
                                cell_text.tag_configure(tag, background="white")
                            elif tag == 'notes':
                                cell_text.tag_configure(tag, background="white")
                            elif tag == 'hint':
                                cell_text.tag_configure(tag, background="#90EE90")  # Light green for hints
                            elif tag == 'auto_solve':
                                # Determine auto-solve background based on difficulty
                                current_diff = self.difficulty.get()
                                if current_diff in ("Moderate", "Tough"):
                                    cell_text.tag_configure(tag, background="#ADD8E6")  # Light blue
                                else:
                                    cell_text.tag_configure(tag, background="#FFD700")  # Gold
                    else:
                        cell_text.config(bg="SystemButtonFace")
                        # Restore original tag backgrounds for clue cells
                        for tag in cell_text.tag_names():
                            if tag == 'center':
                                cell_text.tag_configure(tag, background="SystemButtonFace")
        
        self.selected_entry = (row, col)
        text = self.entries[row][col]
        # Highlight the selected cell in light blue
        text.config(bg="#b3daff")
        
        # Clear any text selection to prevent white highlighting
        text.tag_remove("sel", "1.0", "end")
        
        # Force removal of any other selection tags that might exist
        try:
            text.selection_clear()
        except tk.TclError:
            pass  # No selection to clear
        
        # Also ensure any text tags use the same blue background when selected
        for tag in text.tag_names():
            if tag in ('center', 'notes', 'hint', 'auto_solve'):
                text.tag_configure(tag, background="#b3daff")
        
        # Remove the text cursor by not calling focus_set()
        self.highlighted_cell = (row, col)
        # Highlight matching digits and notes
        self.highlight_matching_digits_and_notes(row, col)

    def highlight_matching_digits_and_notes(self, row, col):
        # Remove all previous highlights
        self.clear_digit_highlights()

        selected_val = self.entries[row][col].get("1.0", "end-1c").strip()
        if not selected_val or not selected_val.isdigit():
            return

        digit = selected_val

        for i in range(9):
            for j in range(9):
                cell_text = self.entries[i][j]
                cell_val = cell_text.get("1.0", "end-1c").strip()
                
                # Check if this cell is a clue cell (pre-filled)
                is_clue_cell = (hasattr(self, "current_puzzle") and 
                               self.current_puzzle[i][j] != 0)
                
                # Highlight main digit if matches
                if cell_val == digit:
                    # Always highlight matching digits, but distinguish between clue and user-entered
                    cell_text.tag_add('highlight_digit', '1.0', 'end')
                    # Configure with higher priority to override existing tags
                    cell_text.tag_configure('highlight_digit', foreground="#c800ff")
                    # Raise the priority of the highlight_digit tag
                    cell_text.tag_raise('highlight_digit')
                else:
                    cell_text.tag_remove('highlight_digit', '1.0', 'end')
                
                # Highlight notes if present (only if tagged as 'notes')
                cell_text.tag_remove('highlight_digit_note', '1.0', 'end')
                idx = '1.0'
                while True:
                    idx = cell_text.search(digit, idx, stopindex='end')
                    if not idx:
                        break
                    end_idx = f"{idx}+1c"
                    if 'notes' in cell_text.tag_names(idx):
                        cell_text.tag_add('highlight_digit_note', idx, end_idx)
                    idx = end_idx
                cell_text.tag_configure('highlight_digit_note', foreground="#c800ff")
                # Also raise the priority of the highlight_digit_note tag
                cell_text.tag_raise('highlight_digit_note')

    def clear_digit_highlights(self):
        for i in range(9):
            for j in range(9):
                cell_text = self.entries[i][j]
                cell_text.tag_remove('highlight_digit', '1.0', 'end')
                cell_text.tag_remove('highlight_digit_note', '1.0', 'end')

    def highlight_note_digit(self, text_widget, digit):
        # Highlight all occurrences of the digit in notes (do not re-render notes)
        idx = '1.0'
        while True:
            idx = text_widget.search(digit, idx, stopindex='end')
            if not idx:
                break
            end_idx = f"{idx}+1c"
            text_widget.tag_add('highlight_digit', idx, end_idx)
            text_widget.tag_configure('highlight_digit', foreground="#c800ff")
            idx = end_idx

    def toggle_notes_mode(self):
        """Toggle notes mode and show/hide the Stone Cold Digit Lock button"""
        self.play_sound('notes_toggle')
        
        if self.notes_mode.get():
            # Show the Stone Cold Digit Lock button when Notes Mode is enabled
            self.stone_cold_button.pack(side=tk.LEFT, padx=(10, 0))
        else:
            # Hide the Stone Cold Digit Lock button when Notes Mode is disabled
            self.stone_cold_button.pack_forget()
            # If Stone Cold Lock was active, reset it
            if self.stone_cold_locked:
                self.stone_cold_locked = False
                self.stone_cold_selected_digit = None
                self.stone_cold_button.config(text="🔓 Stone Cold Digit Lock", fg="black")
                # Re-enable all number buttons with original color
                for btn in self.num_buttons:
                    btn.config(state='normal', bg=self.original_btn_bg)
                # Restore original window size (keep current position)
                current_geometry = self.master.geometry()
                # Extract current position from geometry string (format: "WIDTHxHEIGHT+X+Y")
                if '+' in current_geometry:
                    size_part, pos_part = current_geometry.split('+', 1)
                    x_pos = pos_part.split('+')[0] if '+' in pos_part else pos_part.split('-')[0]
                    y_pos = pos_part.split('+')[1] if '+' in pos_part else pos_part.split('-')[1]
                    self.master.geometry(f"620x950+{x_pos}+{y_pos}")
                else:
                    self.master.geometry("620x950")  # Fallback if no position info

    def toggle_stone_cold_lock(self):
        """Toggle the Stone Cold Digit Lock state"""
        if not self.stone_cold_locked:
            # Lock mode: Change button to just locked icon
            self.stone_cold_locked = True
            self.stone_cold_button.config(
                text="🔒", 
                font=("Arial", 20, "bold"),
                relief=tk.SUNKEN, 
                bg="lightgray", 
                fg="black"
            )
            # Grey out all number buttons initially
            for btn in self.num_buttons:
                btn.config(state='normal', bg='lightgrey')
            # Expand window vertically to accommodate the feature (keep current position)
            current_geometry = self.master.geometry()
            # Extract current position from geometry string (format: "WIDTHxHEIGHT+X+Y")
            if '+' in current_geometry:
                size_part, pos_part = current_geometry.split('+', 1)
                x_pos = pos_part.split('+')[0] if '+' in pos_part else pos_part.split('-')[0]
                y_pos = pos_part.split('+')[1] if '+' in pos_part else pos_part.split('-')[1]
                self.master.geometry(f"620x830+{x_pos}+{y_pos}")
            else:
                self.master.geometry("620x830")  # Fallback if no position info
        else:
            # Unlock mode: Reset to unlocked icon with text
            self.stone_cold_locked = False
            self.stone_cold_selected_digit = None
            self.stone_cold_button.config(
                text="🔓 Stone Cold Digit Lock", 
                font=("Arial", 12, "bold"),
                relief=tk.RAISED, 
                bg="SystemButtonFace", 
                fg="black"
            )
            # Re-enable all number buttons with original color
            for btn in self.num_buttons:
                btn.config(state='normal', bg=self.original_btn_bg)
            # Restore original window size (keep current position)
            current_geometry = self.master.geometry()
            # Extract current position from geometry string (format: "WIDTHxHEIGHT+X+Y")
            if '+' in current_geometry:
                size_part, pos_part = current_geometry.split('+', 1)
                x_pos = pos_part.split('+')[0] if '+' in pos_part else pos_part.split('-')[0]
                y_pos = pos_part.split('+')[1] if '+' in pos_part else pos_part.split('-')[1]
                self.master.geometry(f"620x950+{x_pos}+{y_pos}")
            else:
                self.master.geometry("620x950")  # Fallback if no position info

    def handle_number_button(self, digit):
        # Handle Stone Cold Digit Lock logic
        if self.stone_cold_locked:
            if self.stone_cold_selected_digit is None:
                # First digit selection in Stone Cold mode
                self.stone_cold_selected_digit = digit
                # Grey out all other buttons, highlight the selected one
                for i, btn in enumerate(self.num_buttons):
                    if i == digit - 1:
                        btn.config(bg=self.original_btn_bg)  # Highlight selected digit with Back button color
                    else:
                        btn.config(bg='lightgrey')  # Grey out others
                return
            elif self.stone_cold_selected_digit != digit:
                # Trying to select a different digit - ignore
                return
            else:
                # Clicking the same selected digit - maintain selection, don't do anything else
                # Notes are added by clicking cells, not by clicking the digit button again
                # Keep the button highlighted and selection active
                return
        
        if self.selected_entry is None:
            return
            
        # Check if this digit button is disabled (all instances used)
        if hasattr(self, 'num_buttons') and self.num_buttons[digit - 1].cget('state') == 'disabled':
            return
            
        row, col = self.selected_entry
        text = self.entries[row][col]

        # Only block editing if it's a pre-filled clue cell (should always be disabled anyway)
        if hasattr(self, "current_puzzle") and self.current_puzzle[row][col] != 0:
            return

        if self.notes_mode.get():
            # Save undo state for notes
            self.undo_stack.append({
                'row': row,
                'col': col,
                'value': text.get('1.0', 'end-1c'),
                'bg': text.cget('bg'),
                'fg': text.tag_cget('center', 'foreground') if 'center' in text.tag_names() else text.cget('fg'),
                'notes': set(self.notes[row][col])
            })
            # Use game logic for note toggling
            self.game_logic.toggle_note(row, col, digit)
            # Sync local notes with game logic
            self.notes[row][col] = self.game_logic.get_notes(row, col)
            self.update_notes_display(row, col)
        else:
            text.config(state='normal')
            # Save notes before clearing them, so Undo can restore them
            prev_notes = set(self.notes[row][col])
            if self.notes[row][col]:
                self.notes[row][col].clear()
                text.delete('1.0', tk.END)
            else:
                text.delete('1.0', tk.END)
            self.undo_stack.append({
                'row': row,
                'col': col,
                'value': '',  # After clearing notes, cell is empty
                'bg': text.cget('bg'),
                'fg': text.tag_cget('center', 'foreground') if 'center' in text.tag_names() else text.cget('fg'),
                'notes': prev_notes  # Save previous notes for undo
            })
            
            # Use game logic to validate the move
            move_result = self.game_logic.make_move(row, col, digit)
            
            if move_result['valid'] and move_result['mistake']:
                cell_bg = "#ff2222"  # Bright red background
                fg_color = "white"   # White font
                self.mistake_count = self.game_logic.mistake_count
                self.mistake_label.config(text=f"Mistakes: {self.mistake_count}")
                self.play_sound('error')  # Play error sound
                if self.mistake_count >= 3:
                    self.show_fail_screen()
            else:
                cell_bg = "white"
                fg_color = "#5599cc"  # Lighter blue color
                self.play_sound('number_place')  # Play number placement sound
            
            # Insert the digit and apply formatting for both correct and incorrect entries
            text.insert('1.0', str(digit))
            
            # Remove all existing tags to ensure clean state
            for tag in text.tag_names():
                text.tag_delete(tag)
            
            text.tag_configure(
                'center',
                justify='center',
                font=('Ink Journal', 28),
                foreground=fg_color,
                lmargin1=0, lmargin2=0, rmargin=0,
                spacing1=0, spacing3=0
            )
            text.tag_add('center', '1.0', 'end')
            text.config(bg=cell_bg)
            self.notes[row][col].clear()
            text.config(state='normal')  # Keep user cells editable
            
            # Only clear conflicting notes and re-apply highlights if the entry is correct
            if not move_result['mistake']:
                # Use game logic to clear conflicting notes
                self.game_logic.clear_conflicting_notes(row, col, digit)
                # Sync local notes with game logic
                for i in range(9):
                    for j in range(9):
                        self.notes[i][j] = self.game_logic.get_notes(i, j)
    
                # --- Re-apply highlight so user-entered digits turn purple if needed ---
                self.highlight_matching_digits_and_notes(row, col)
                
                # Check for completed rows, columns, and sections and animate them
                # Always check for completions, even if the puzzle is fully solved
                self.check_and_animate_completions(row, col)
    
            self.update_number_buttons()

        # --- Auto-check for solution after every digit entry ---
        if not self.notes_mode.get():
            if self.is_puzzle_filled():
                if self.game_logic.is_puzzle_complete():
                    self.timer_running = False
                    self.completion_time = self.timer_label.cget('text')  # Capture completion time
                    
                    # Schedule victory animation to start after a delay to allow any final row/column/section animations to complete
                    self.master.after(1500, self.animate_victory_ripples)  # 1.5 second delay

    def is_puzzle_filled(self):
        # Returns True if all cells are filled with a main digit (not notes)
        for i in range(9):
            for j in range(9):
                text_widget = self.entries[i][j]
                
                # Check if cell has a main digit (tagged with 'center')
                if 'center' not in text_widget.tag_names('1.0'):
                    return False  # Cell has no main digit (only notes or empty)
                
                # Double-check that it's actually a single digit
                val = text_widget.get("1.0", tk.END).strip()
                if len(val) != 1 or not val.isdigit():
                    return False
        return True

    def is_current_solution_correct(self):
        # Returns True if all cells have correct main digits that match the solution
        for i in range(9):
            for j in range(9):
                text_widget = self.entries[i][j]
                
                # Check if cell has a main digit (tagged with 'center')
                if 'center' not in text_widget.tag_names('1.0'):
                    return False  # Cell has no main digit (only notes or empty)
                
                # Get the main digit value
                val = text_widget.get("1.0", tk.END).strip()
                if (len(val) != 1 or not val.isdigit() or 
                    int(val) != self.solution[i][j]):
                    return False
        return True

    def handle_erase(self):
        if self.selected_entry is None:
            return
        
        row, col = self.selected_entry
        text = self.entries[row][col]
        # Only allow erasing if the cell is not a pre-filled clue or hint
        if hasattr(self, "current_puzzle") and self.current_puzzle[row][col] != 0:
            return  # Don't erase pre-filled clues
        if text.cget('bg') == "#90EE90":
            return  # Don't erase hints (green background)
        
        # Check if cell is empty
        current_value = text.get('1.0', 'end-1c').strip()
        if not current_value:
            return  # Don't erase if already empty
        
        self.play_sound('clear')
        
        # Save undo state for erase
        self.undo_stack.append({
            'row': row,
            'col': col,
            'value': text.get('1.0', 'end-1c'),
            'bg': text.cget('bg'),
            'fg': text.tag_cget('center', 'foreground') if 'center' in text.tag_names() else text.cget('fg'),
            'notes': set(self.notes[row][col])
        })
        text.config(state='normal')
        text.delete('1.0', tk.END)
        self.notes[row][col].clear()
        
        # Remove all existing tags to ensure clean state
        for tag in text.tag_names():
            text.tag_delete(tag)
        
        # Reset cell formatting and background to normal user cell state
        text.config(
            font=('Arial', 24), 
            fg='#5599cc',  # Lighter blue color to match other user entries
            bg='white'  # Reset background to white
        )
        # Don't add any tags when clearing - cell should be completely empty
        text.config(state='normal')  # Keep user cells editable, not disabled
        
        # Update button states after erase
        self.master.after_idle(self.update_number_buttons)

    def handle_undo(self):
        if not hasattr(self, "undo_stack") or not self.undo_stack:
            messagebox.showinfo("Undo", "Nothing to undo!")
            return
        
        self.play_sound('undo')
        
        last = self.undo_stack.pop()
        row, col = last['row'], last['col']
        text = self.entries[row][col]
        text.config(state='normal')
        text.delete('1.0', tk.END)
        
        # Remove all existing tags to ensure clean state
        for tag in text.tag_names():
            text.tag_delete(tag)
        
        if last['value']:
            text.insert('1.0', last['value'])
            text.tag_configure(
                'center',
                justify='center',
                font=('Arial', 24),
                foreground=last['fg'],
                lmargin1=0, lmargin2=0, rmargin=0,
                spacing1=8, spacing3=8
            )
            text.tag_add('center', '1.0', 'end')
        text.config(bg=last['bg'])
        self.notes[row][col] = set(last['notes'])
        self.update_notes_display(row, col)
        self.update_number_buttons()

    def update_notes_display(self, row, col):
        # Prevent notes from being displayed or updated in clue cells
        if hasattr(self, "current_puzzle") and self.current_puzzle[row][col] != 0:
            # Always clear any accidental notes in clue cells
            self.notes[row][col].clear()
            text = self.entries[row][col]
            text.config(state='disabled')
            text.delete('1.0', tk.END)
            text.insert('1.0', str(self.current_puzzle[row][col]))
            text.tag_configure(
                'center',
                justify='center',
                font=('Arial', 24),
                foreground='black',
                lmargin1=0, lmargin2=0, rmargin=0,
                spacing1=8, spacing3=8
            )
            text.tag_add('center', '1.0', 'end')
            return

        text = self.entries[row][col]
        notes = self.notes[row][col]
        # Always render all three positions per row, so notes appear in fixed spots
        grid_lines = []
        for r in range(3):
            line = ""
            for c in range(1, 4):
                num = 3 * r + c
                # Add extra spaces between digits for more spread
                line += str(num) if num in notes else " "
                if c < 3:
                    line += "   "  # Increased from one space to three spaces for more horizontal spread
            grid_lines.append(line)
        grid = "\n".join(grid_lines)
        text.config(state='normal')
        text.delete('1.0', tk.END)
        
        # Remove all existing tags to ensure clean state
        for tag in text.tag_names():
            text.tag_delete(tag)
        
        if notes:
            text.insert('1.0', grid)
            text.tag_configure(
                'notes',
                font=('Ink Journal', 9),  # Changed to Ink Journal for notes
                foreground='gray20',
                justify='center',
                lmargin1=0, lmargin2=0, rmargin=0
            )
            text.tag_add('notes', '1.0', 'end')
        text.config(state='normal')

    def start_timer(self):
        self.timer_running = True
        self.update_timer()

    def update_timer(self):
        if self.timer_running:
            mins, secs = divmod(self.seconds, 60)
            self.timer_label.config(text=f"{mins:02d}:{secs:02d}")
            self.seconds += 1
            self.master.after(1000, self.update_timer)

    def reset_timer(self):
        self.seconds = 0
        self.timer_label.config(text="00:00")

    def generate_puzzle(self):
        self.reset_timer()
        self.timer_running = True
        
        # Reset auto-solved puzzles list for new puzzle
        if not hasattr(self, 'auto_solved_puzzles'):
            self.auto_solved_puzzles = set()
        # Don't clear the list - this would allow unlimited auto-solves by starting new games
        
        # Use the separated game logic to generate puzzle
        self.game_logic.set_difficulty(self.difficulty.get())
        puzzle, solution = self.game_logic.generate_puzzle()
        
        # Store references for compatibility
        self.board = self.game_logic.board
        self.solution = solution
        self.current_puzzle = puzzle
        
        for i in range(9):
            for j in range(9):
                text = self.entries[i][j]
                text.config(state='normal')
                text.delete('1.0', tk.END)
                self.notes[i][j].clear()
                if puzzle[i][j] != 0:
                    text.insert('1.0', str(puzzle[i][j]))
                    text.tag_configure(
                        'center',
                        justify='center',
                        font=('Copperplate Gothic Bold', 24),  # Use Copperplate Gothic for clues
                        foreground='black',
                        lmargin1=0, lmargin2=0, rmargin=0,
                        spacing1=8, spacing3=8
                    )
                    text.tag_add('center', '1.0', 'end')
                    text.config(state='disabled', fg='black')  # Clue cells: disabled
                else:
                    text.config(state='normal', font=('Arial', 24), fg='#5599cc', bg='white')  # User cells: enabled
        
        # Initialize completion tracking for animations
        self.initialize_completion_tracking()
        
        # Set flag to prevent animations during initial setup
        self.generating_puzzle = True
        self.update_number_buttons()  # Update button states for new game
        self.generating_puzzle = False  # Clear flag after initial setup

    def get_attempts_for_difficulty(self):
        # Delegate to game logic
        return self.game_logic.difficulty_attempts.get(self.difficulty.get(), 36)

    def show_solved_animation(self):
        # Play victory music and completion sound
        self.stop_music()
        self.play_music('victory', loop=False)  # Play victory music once
        self.play_sound('complete')
        
        # Overlay a canvas for the animation
        board_size = 60 * 9  # Match the new cell size
        anim_canvas = tk.Canvas(self.master, width=board_size, height=board_size, bg='', highlightthickness=0)
        anim_canvas.place(x=0, y=40)  # y=40 to account for timer label and padding

        # Cherry blossom petals (simple circles) and waterfall (vertical blue lines)
        petals = []
        petal_colors = ['#ffb7c5', '#ff69b4', '#fff0f5']
        for _ in range(30):
            x = random.randint(0, board_size)
            y = random.randint(-board_size//2, 0)
            size = random.randint(10, 18)
            speed = random.uniform(2, 4)
            color = random.choice(petal_colors) if petal_colors else '#ffb7c5'
            petals.append({'x': x, 'y': y, 'size': size, 'speed': speed, 'color': color})

        waterfall_lines = []
        for i in range(20):
            x = board_size//2 - 60 + i*6
            waterfall_lines.append({'x': x, 'y': 0, 'length': random.randint(board_size//2, board_size-30), 'offset': random.randint(0, 20)})

        steps = 40
        def animate(step=0):
            anim_canvas.delete("all")
            # Draw waterfall
            for line in waterfall_lines:
                anim_canvas.create_line(
                    line['x'], 60 + line['offset'],
                    line['x'], 60 + line['offset'] + min(line['length'], step*12),
                    fill='#87cefa', width=4, capstyle=tk.ROUND
                )
            # Draw petals
            for petal in petals:
                petal_y = petal['y'] + step * petal['speed']
                anim_canvas.create_oval(
                    petal['x'], petal_y,
                    petal['x'] + petal['size'], petal_y + petal['size'],
                    fill=petal['color'], outline=''
                )
            # Draw "Congratulations!" text with a fade-in effect
            if step > steps//3:
                anim_canvas.create_text(
                    board_size//2, board_size//2,
                    text="Congratulations!",
                    font=("Arial", 36, "bold"),
                    fill="#4169e1"
                )
            if step < steps:
                self.master.after(40, lambda: animate(step + 1))
            else:
                self.master.after(1200, anim_canvas.destroy)

        animate()

    # Replace your check_solution method with this to trigger the animation:
    def check_solution(self):
        # Compare the current entries to the solution board
        for i in range(9):
            for j in range(9):
                text = self.entries[i][j]
                val = text.get("1.0", tk.END).strip()
                # Only accept a single digit for checking
                if len(val) != 1 or not val.isdigit():
                    messagebox.showerror("Incorrect", "The solution is not correct. Try again!")
                    return
                if int(val) != self.solution[i][j]:  # <-- Compare to self.solution
                    messagebox.showerror("Incorrect", "The solution is not correct. Try again!")
                    return
        # If all cells match the solution
        self.timer_running = False
        self.completion_time = self.timer_label.cget('text')  # Capture completion time
        self.show_reward_screen()

    def show_reward_screen(self):
        # Stop game music and play victory music
        self.stop_music()
        self.play_music('victory', loop=False)  # Play victory music once, not looped
        
        # Clear the saved game since puzzle is completed
        self.resume_available = False
        self.clear_persistent_save()
        
        for widget in self.master.winfo_children():
            widget.destroy()

        # Main reward frame with proper background
        self.master.configure(bg="#f8f8ff")
        reward_frame = tk.Frame(self.master, bg="#f8f8ff")
        reward_frame.pack(expand=True, fill="both")

        # Beautiful realistic cherry blossom tree with falling petals animation
        canvas_size = 250  # Larger canvas for more detailed tree
        cherry_canvas = tk.Canvas(reward_frame, width=canvas_size, height=canvas_size, bg="#f8f8ff", highlightthickness=0)
        cherry_canvas.pack(pady=(60, 20), anchor="center")

        # Draw realistic cherry tree with detailed branching structure
        # Main trunk with gradient effect (multiple lines for thickness)
        trunk_base_x, trunk_base_y = 125, 240
        trunk_top_x, trunk_top_y = 125, 160
        
        # Create trunk with multiple brown shades for depth
        for i in range(12):
            offset = i - 6
            shade = "#654321" if abs(offset) < 3 else "#8b4513" if abs(offset) < 5 else "#a0522d"
            cherry_canvas.create_line(
                trunk_base_x + offset, trunk_base_y,
                trunk_top_x + offset//2, trunk_top_y,
                width=1, fill=shade
            )

        # Primary branches with natural curves
        def draw_branch(start_x, start_y, end_x, end_y, width, curve_points=None):
            if curve_points:
                # Draw curved branch using multiple segments
                points = [start_x, start_y] + curve_points + [end_x, end_y]
                cherry_canvas.create_line(points, width=width, fill="#8b4513", smooth=True, capstyle=tk.ROUND)
            else:
                cherry_canvas.create_line(start_x, start_y, end_x, end_y, width=width, fill="#8b4513", capstyle=tk.ROUND)

        # Left main branch with natural curve
        draw_branch(125, 160, 60, 80, 8, [115, 140, 90, 110])
        # Right main branch with natural curve  
        draw_branch(125, 160, 190, 80, 8, [135, 140, 160, 110])
        # Center upward branch
        draw_branch(125, 160, 125, 70, 6)

        # Secondary branches for more realistic structure
        draw_branch(60, 80, 40, 60, 5, [55, 70])  # Left secondary
        draw_branch(60, 80, 80, 50, 5, [70, 65])  # Left upper
        draw_branch(190, 80, 210, 60, 5, [195, 70])  # Right secondary
        draw_branch(190, 80, 170, 50, 5, [180, 65])  # Right upper
        draw_branch(125, 70, 105, 45, 4)  # Center left
        draw_branch(125, 70, 145, 45, 4)  # Center right

        # Tertiary branches for fine detail
        for branch_data in [
            (40, 60, 25, 45, 3), (80, 50, 95, 35, 3), (210, 60, 225, 45, 3),
            (170, 50, 155, 35, 3), (105, 45, 90, 30, 3), (145, 45, 160, 30, 3),
            (60, 80, 45, 95, 3), (190, 80, 205, 95, 3), (125, 70, 110, 55, 3),
            (125, 70, 140, 55, 3)
        ]:
            draw_branch(*branch_data)

        # Create beautiful layered cherry blossoms with varying sizes and shades
        blossom_clusters = [
            # Main branch clusters
            {'center': (50, 70), 'size': 'large', 'density': 8},
            {'center': (75, 60), 'size': 'medium', 'density': 6},
            {'center': (180, 70), 'size': 'large', 'density': 8},
            {'center': (200, 60), 'size': 'medium', 'density': 6},
            {'center': (125, 55), 'size': 'large', 'density': 7},
            
            # Secondary clusters
            {'center': (35, 55), 'size': 'small', 'density': 4},
            {'center': (90, 40), 'size': 'medium', 'density': 5},
            {'center': (215, 55), 'size': 'small', 'density': 4},
            {'center': (160, 40), 'size': 'medium', 'density': 5},
            {'center': (110, 35), 'size': 'small', 'density': 3},
            {'center': (140, 35), 'size': 'small', 'density': 3},
            
            # Scattered blossoms for natural look
            {'center': (65, 85), 'size': 'small', 'density': 3},
            {'center': (155, 85), 'size': 'small', 'density': 3},
            {'center': (125, 75), 'size': 'medium', 'density': 4},
            {'center': (95, 50), 'size': 'small', 'density': 2},
            {'center': (155, 50), 'size': 'small', 'density': 2},
        ]

        # Draw blossom clusters with multiple layers for depth
        for cluster in blossom_clusters:
            cx, cy = cluster['center']
            size = cluster['size']
            density = cluster['density']
            
            # Size parameters
            if size == 'large':
                base_radius, petal_radius = 18, 12
            elif size == 'medium':
                base_radius, petal_radius = 14, 9
            else:  # small
                base_radius, petal_radius = 10, 6
            
            # Create multiple blossoms in cluster
            for i in range(density):
                # Random offset within cluster
                offset_x = random.randint(-base_radius//2, base_radius//2)
                offset_y = random.randint(-base_radius//2, base_radius//2)
                bx, by = cx + offset_x, cy + offset_y
                
                # Multiple layers for each blossom
                # Background layer (darker pink)
                cherry_canvas.create_oval(
                    bx - base_radius, by - base_radius,
                    bx + base_radius, by + base_radius,
                    fill="#ffb6c1", outline="#ff91a4", width=1
                )
                
                # Middle layer (medium pink)
                cherry_canvas.create_oval(
                    bx - petal_radius, by - petal_radius,
                    bx + petal_radius, by + petal_radius,
                    fill="#ffc0cb", outline="#ffb6c1", width=1
                )
                
                # Top layer (light pink/white center)
                center_radius = petal_radius // 2
                cherry_canvas.create_oval(
                    bx - center_radius, by - center_radius,
                    bx + center_radius, by + center_radius,
                    fill="#fff0f5", outline="#ffc0cb", width=1
                )
                
                # Add tiny yellow centers for realism
                cherry_canvas.create_oval(
                    bx - 2, by - 2, bx + 2, by + 2,
                    fill="#fffacd", outline="#fff8dc"
                )

        # Enhanced falling petals with realistic physics
        petals = []
        petal_colors = ["#ffb6c1", "#ffc0cb", "#fff0f5", "#ffe4e1", "#ff91a4"]
        
        for _ in range(35):  # More petals for richness
            px = random.randint(20, canvas_size - 20)
            py = random.randint(-100, 0)
            size = random.randint(8, 14)
            speed = random.uniform(0.8, 2.2)  # Varied falling speeds
            sway = random.uniform(-0.5, 0.5)  # Horizontal drift
            rotation = random.randint(0, 360)  # Initial rotation
            color = random.choice(petal_colors)
            petals.append({
                'x': px, 'y': py, 'size': size, 'speed': speed,
                'sway': sway, 'rotation': rotation, 'color': color,
                'life': random.randint(50, 150)  # How long petal lives on ground
            })

        def animate_petals():
            cherry_canvas.delete("petal")
            
            for petal in petals:
                # Update position with realistic physics
                petal['y'] += petal['speed']
                petal['x'] += petal['sway']
                petal['rotation'] += random.uniform(-2, 2)  # Gentle rotation
                
                # Reset petal when it falls off screen or life expires
                if petal['y'] > canvas_size + 20 or petal['life'] <= 0:
                    petal['y'] = random.randint(-80, -20)
                    petal['x'] = random.randint(20, canvas_size - 20)
                    petal['life'] = random.randint(50, 150)
                
                # Draw petal with slight rotation effect (oval shape)
                if petal['y'] < canvas_size:
                    # Create petal shape (slightly elongated oval)
                    size = petal['size']
                    x, y = petal['x'], petal['y']
                    
                    # Main petal body
                    cherry_canvas.create_oval(
                        x - size//2, y - size,
                        x + size//2, y + size//3,
                        fill=petal['color'], outline="", tags="petal"
                    )
                    
                    # Add slight highlight for 3D effect
                    cherry_canvas.create_oval(
                        x - size//4, y - size//2,
                        x + size//4, y,
                        fill="#ffffff", outline="", tags="petal"
                    )
                elif petal['y'] >= canvas_size:
                    # Petal on ground (smaller, different alpha effect)
                    petal['life'] -= 1
                    size = petal['size'] // 2
                    x = petal['x']
                    y = canvas_size - 5
                    
                    cherry_canvas.create_oval(
                        x - size, y - size//2,
                        x + size, y + size//2,
                        fill=petal['color'], outline="", tags="petal"
                    )
            
            cherry_canvas.after(50, animate_petals)  # Slightly slower for graceful movement

        animate_petals()

        # Content container for centered text and buttons
        content_frame = tk.Frame(reward_frame, bg="#f8f8ff")
        content_frame.pack(pady=(5, 40), anchor="center")

        # Japanese "Congratulations" text below animation
        tk.Label(
            content_frame,
            text="おめでとうございます！",
            font=("Arial", 24, "bold"),
            fg="#e75480",
            bg="#f8f8ff"
        ).pack(pady=(5, 5), anchor="center")

        tk.Label(
            content_frame,
            text="Congratulations!",
            font=("Arial", 26, "bold"),
            fg="#4169e1",
            bg="#f8f8ff"
        ).pack(pady=(5, 5), anchor="center")

        tk.Label(
            content_frame,
            text="You solved the puzzle!",
            font=("Arial", 16),
            fg="#333",
            bg="#f8f8ff"
        ).pack(pady=(5, 10), anchor="center")

        # Display completion time
        completion_time = getattr(self, 'completion_time', '00:00')
        if not completion_time and hasattr(self, 'timer_label'):
            completion_time = self.timer_label.cget('text')
        elif not completion_time:
            completion_time = "00:00"
        
        tk.Label(
            content_frame,
            text=f"Completion Time: {completion_time}",
            font=("Arial", 14, "bold"),
            fg="#4169e1",
            bg="#f8f8ff"
        ).pack(pady=(5, 10), anchor="center")

        tk.Label(
            content_frame,
            text="Ready for another challenge?",
            font=("Arial", 12, "bold"),
            fg="#800000",
            bg="#f8f8ff"
        ).pack(pady=(5, 10), anchor="center")

        # Buttons frame for better layout - centered
        button_frame = tk.Frame(content_frame, bg="#f8f8ff")
        button_frame.pack(pady=(15, 10), anchor="center")

        # New Game button
        tk.Button(
            button_frame,
            text="New Game",
            font=("Arial", 12, "bold"),
            bg="SystemButtonFace",
            fg="black",
            activebackground="SystemButtonFace",
            activeforeground="black",
            relief=tk.RAISED,
            bd=4,
            width=12,
            command=self.start_new_game
        ).pack(side=tk.LEFT, padx=(0, 10))

        # When returning to menu, set resume_available to False and reset bg
        def back_to_menu_and_reset():
            self.resume_available = False
            self.master.configure(bg="SystemButtonFace")
            self.show_welcome_screen()

        # Back to Menu button
        tk.Button(
            button_frame,
            text="Back to Menu",
            font=("Arial", 12, "bold"),
            bg="SystemButtonFace",
            fg="black",
            activebackground="SystemButtonFace",
            activeforeground="black",
            relief=tk.RAISED,
            bd=4,
            width=12,
            command=back_to_menu_and_reset
        ).pack(side=tk.LEFT, padx=(10, 0))

    def show_fail_screen(self):
        # Stop game music and play fail music
        self.stop_music()
        self.play_music('fail', loop=False)  # Play fail music once, not looped
        
        # Disable resume functionality when game fails
        self.resume_available = False
        # Clear the saved game since game failed
        self.clear_persistent_save()
        
        for widget in self.master.winfo_children():
            widget.destroy()

        fail_frame = tk.Frame(self.master, bg="#22223b", width=620, height=780)
        fail_frame.pack(expand=True, fill="both")
        fail_frame.pack_propagate(False)  # Maintain fixed size

        # Create a Canvas for the stop sign
        canvas_size = 260
        stop_canvas = tk.Canvas(fail_frame, width=canvas_size, height=canvas_size, bg="#22223b", highlightthickness=0)
        stop_canvas.pack(pady=(60, 20))

        # Draw octagon (stop sign shape)
        r = 110
        center_x, center_y = canvas_size // 2, canvas_size // 2
        points = []
        for i in range(8):
            angle = math.pi/8 + i * math.pi/4
            x = center_x + r * math.cos(angle)
            y = center_y + r * math.sin(angle)
            points.extend([x, y])
        stop_canvas.create_polygon(points, fill="#ff2222", outline="white", width=14)

        # Draw "FAIL" in the center
        stop_canvas.create_text(
            center_x, center_y,
            text="FAIL",
            font=("Arial", 54, "bold"),
            fill="white"
        )

        tk.Label(
            fail_frame,
            text="(At least it wasn't an epic one)",
            font=("Arial", 14, "italic"),
            fg="white",
            bg="#22223b",
            justify="center"
        ).pack(pady=(0, 10))

        tk.Label(
            fail_frame,
            text="You made 3 mistakes.\nThanks for playing!",
            font=("Arial", 18),
            fg="white",
            bg="#22223b",
            justify="center"
        ).pack(pady=10)

        tk.Label(
            fail_frame,
            text="Start training and make a comeback:",
            font=("Arial", 14, "bold"),
            fg="white",
            bg="#22223b",
            justify="center"
        ).pack(pady=(20, 0))

        tk.Button(
            fail_frame,
            text="Try Again",
            font=("Arial", 12, "bold"),
            bg="SystemButtonFace",
            fg="black",
            activebackground="SystemButtonFace",
            activeforeground="black",
            relief=tk.RAISED,
            bd=4,
            command=self.show_welcome_screen
        ).pack(pady=30)

    def is_valid_solution(self, board):
        # Delegate to game logic
        return self.game_logic.is_valid_solution(board)
        
    def update_number_buttons(self):
        """Update the visual state of number buttons based on completed digits"""
        if not hasattr(self, 'num_buttons') or not hasattr(self, 'solution'):
            return
            
        for digit in range(1, 10):
            # Use game logic to count completed digits
            correct_count = self.game_logic.get_digit_completion_count(digit)
            
            # If all 9 instances of this digit are correctly placed, disable the button
            button = self.num_buttons[digit - 1]  # digit 1 is at index 0
            current_button_state = button.cget('state')
            
            if correct_count >= 9:
                button.config(
                    text="",  # Hide the digit
                    state="disabled",
                    bg="#cccccc",
                    fg="#888888",
                    activebackground="#cccccc",
                    activeforeground="#888888",
                    relief=tk.RAISED, bd=4  # Maintain 3D effect even when disabled
                )
                
                # Note: Digit completion animation is now handled by check_and_animate_completions
                # No need to trigger it here anymore
            else:
                # Reset button to normal state if not all instances are placed
                current_diff = self.difficulty.get()
                if current_diff == "Easy":
                    btn_bg = "SystemButtonFace"
                    btn_fg = "black"
                elif current_diff in ("Tough", "Moderate"):
                    btn_bg = "SystemButtonFace"
                    btn_fg = "black"
                elif current_diff == "Expert":
                    btn_bg = "SystemButtonFace"
                    btn_fg = "black"
                elif current_diff == "Evil":
                    btn_bg = "SystemButtonFace"
                    btn_fg = "black"
                elif current_diff == "Diabolical":
                    btn_bg = "#333"
                    btn_fg = "white"
                else:
                    btn_bg = "SystemButtonFace"
                    btn_fg = "black"
                
                button.config(
                    text=str(digit),  # Show the digit
                    state="normal",
                    bg=btn_bg,
                    fg=btn_fg,
                    activebackground=btn_bg,
                    activeforeground=btn_fg,
                    relief=tk.RAISED, bd=4  # Maintain 3D effect
                )
        
        # After updating button states, maintain Stone Cold Lock appearance if active
        if hasattr(self, 'stone_cold_locked') and self.stone_cold_locked:
            # Re-apply Stone Cold Lock styling
            for i, btn in enumerate(self.num_buttons):
                if (hasattr(self, 'stone_cold_selected_digit') and 
                    self.stone_cold_selected_digit is not None and 
                    i == self.stone_cold_selected_digit - 1):
                    # Keep the selected digit highlighted (if not disabled)
                    if btn.cget('state') != 'disabled':
                        btn.config(bg=self.original_btn_bg)
                else:
                    # Keep other buttons greyed out (if not disabled)
                    if btn.cget('state') != 'disabled':
                        btn.config(bg='lightgrey')

    def give_hint(self):
        """Provide a hint by filling in one correct digit in an empty cell"""
        # Use game logic to get hint
        hint_result = self.game_logic.get_hint()
        
        if hint_result is None:
            self.show_hint_popup("You're fresh out of hints.", is_out_of_hints=True)
            return
        
        # Play hint sound
        self.play_sound('hint')
            
        row = hint_result['row']
        col = hint_result['col'] 
        correct_digit = hint_result['number']
        
        # Fill in the hint
        text = self.entries[row][col]
        text.config(state='normal')
        text.delete('1.0', tk.END)
        
        # Clear any notes in this cell
        self.notes[row][col].clear()
        
        # Insert the correct digit with hint styling (green background)
        text.insert('1.0', str(correct_digit))
        text.tag_configure(
            'hint',
            justify='center',
            font=('Arial', 24, 'bold'),
            foreground='#006400',  # Dark green
            lmargin1=0, lmargin2=0, rmargin=0,
            spacing1=8, spacing3=8
        )
        text.tag_add('hint', '1.0', 'end')
        text.config(bg="#90EE90")  # Light green background for hints
        text.config(state='disabled')  # Make hint cells non-editable
        
        # Use game logic to clear conflicting notes
        self.game_logic.clear_conflicting_notes(row, col, correct_digit)
        # Sync local notes with game logic
        for i in range(9):
            for j in range(9):
                self.notes[i][j] = self.game_logic.get_notes(i, j)
        
        # Update number buttons
        self.update_number_buttons()
        
        # Update hint count from game logic
        self.hint_count = self.game_logic.hint_count
        
        # Update hint button appearance if limit reached
        if self.hint_count >= 2:
            self.update_hint_button_appearance()
        
        # Show hint message
        remaining_hints = hint_result['hints_remaining']
        if remaining_hints > 0:
            hint_word = "hint" if remaining_hints == 1 else "hints"
            self.show_hint_popup(f"Hint: {correct_digit} placed at row {row + 1}, column {col + 1}. You have {remaining_hints} {hint_word} remaining.", is_out_of_hints=False)
        else:
            self.show_hint_popup(f"Hint: {correct_digit} placed at row {row + 1}, column {col + 1}. Sorry - you're fresh out of hints. Good Luck!", is_out_of_hints=False)
    
    def show_hint_popup(self, message, is_out_of_hints=False):
        """Show a custom hint popup with game-matching colors"""
        # Get current game difficulty colors
        diff_colors = {
            "Easy": "#228B22",         # Forest green
            "Moderate": "#ffe066",     # Gold
            "Tough": "#ffa366",        # Orange
            "Expert": "#800000",       # Maroon
            "Evil": "#a366ff",         # Purple
            "Diabolical": "#22223b"    # Dark Blue/Black
        }
        
        current_diff = self.difficulty.get()
        bg_color = diff_colors.get(current_diff, "#ffffff")
        
        # Set text color based on difficulty for best contrast
        if current_diff == "Easy":
            text_fg = "white"
        elif current_diff in ("Tough", "Moderate"):
            text_fg = "black"
        elif current_diff == "Expert":
            text_fg = "white"
        elif current_diff == "Evil":
            text_fg = "white"
        elif current_diff == "Diabolical":
            text_fg = "white"
        else:
            text_fg = "black"
        
        # Calculate hints left (starting with 2 hints total)
        current_hint_count = getattr(self, 'hint_count', 0)
        hints_left = max(0, 2 - current_hint_count)
        
        # Create popup window
        popup = tk.Toplevel(self.master)
        popup.title("")
        popup.geometry("300x150")
        popup.resizable(False, False)
        popup.configure(bg=bg_color)
        
        # Center the popup over the main window
        popup.transient(self.master)
        popup.grab_set()  # Make it modal
        
        # Center the popup
        popup.update_idletasks()
        x = (popup.winfo_screenwidth() // 2) - (popup.winfo_width() // 2)
        y = (popup.winfo_screenheight() // 2) - (popup.winfo_height() // 2)
        popup.geometry(f"+{x}+{y}")
        
        if is_out_of_hints:
            # No hints left - show "Sorry, I have no clue"
            sorry_label = tk.Label(
                popup,
                text="Sorry, I have no clue",
                font=("Arial", 14, "bold"),
                fg=text_fg,
                bg=bg_color
            )
            sorry_label.pack(pady=(40, 20))
            
            # OK button
            ok_btn = tk.Button(
                popup,
                text="OK",
                font=("Arial", 12, "bold"),
                width=10,
                height=1,
                bg="#cccccc",  # Grey background
                fg="black",    # Black text
                activebackground="#bbbbbb",
                activeforeground="black",
                relief=tk.RAISED,
                bd=4,
                command=popup.destroy
            )
            ok_btn.pack(pady=10)
        else:
            # Still have hints - show normal hint message
            # "Psst..." label
            psst_label = tk.Label(
                popup,
                text="Psst...",
                font=("Arial", 14, "bold"),
                fg=text_fg,
                bg=bg_color
            )
            psst_label.pack(pady=(20, 5))
            
            # "Here's a clue for you" label
            clue_label = tk.Label(
                popup,
                text="Here's a clue for you",
                font=("Arial", 12),
                fg=text_fg,
                bg=bg_color
            )
            clue_label.pack(pady=(0, 20))
            
            # Thanks button (grey)
            thanks_btn = tk.Button(
                popup,
                text="Thanks",
                font=("Arial", 12, "bold"),
                width=10,
                height=1,
                bg="#cccccc",  # Grey background
                fg="black",    # Black text
                activebackground="#bbbbbb",
                activeforeground="black",
                relief=tk.RAISED,
                bd=4,
                command=popup.destroy
            )
            thanks_btn.pack(pady=10)
            
            # Hints left label in bottom right corner (only show when providing hint)
            hints_left_label = tk.Label(
                popup,
                text=f"Hints left: {hints_left}",
                font=("Arial", 10),
                fg=text_fg,
                bg=bg_color
            )
            hints_left_label.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)
    
    def update_hint_button_appearance(self):
        """Update the hint button appearance when hints are exhausted"""
        if hasattr(self, 'hint_button') and hasattr(self, 'hint_label'):
            self.hint_button.config(
                fg="#666666",
                bg="#666666",
                activebackground="#666666",
                activeforeground="#666666",
                state="disabled"
            )
            self.hint_label.config(
                text="No Hints Left",
                fg="#666666"
            )

    def is_auto_solve_available(self):
        """Check if auto-solve is available based on usage limits (3 per 30 minutes)"""
        return self.game_logic.is_auto_solve_available()

    def record_auto_solve_usage(self):
        """Record the current time as an auto-solve usage"""
        self.auto_solve_usage.append(time.time())

    def auto_solve(self):
        """Auto-solve the puzzle by filling in the solution"""
        self.play_sound('auto_solve')
        
        # Use game logic to auto-solve
        solution = self.game_logic.auto_solve()
        
        if solution is None:
            # Auto-solve not available or already used on this puzzle
            self.show_auto_solve_popup("limit_reached")
            self.hide_auto_solve_button()
            return
        
        # Create a unique puzzle ID based on the current puzzle state
        puzzle_id = str(self.current_puzzle) if hasattr(self, 'current_puzzle') else str(self.solution)
        
        # If this puzzle has already been auto-solved, do nothing
        if puzzle_id in self.auto_solved_puzzles:
            return
        
        # Check if auto-solve is still available (3 uses in 30 minutes)
        if not self.is_auto_solve_available():
            # Show limit reached popup and hide auto-solve button
            self.show_auto_solve_popup("limit_reached")
            self.hide_auto_solve_button()
            return
        
        # Determine which use this is (1st, 2nd, or 3rd)
        # Sync local usage tracking with game logic
        self.auto_solve_usage = self.game_logic.auto_solve_usage
        use_number = len([t for t in self.auto_solve_usage if time.time() - t < 1800]) + 1
        
        # Show appropriate popup based on use number
        if use_number <= 2:
            # First or second use - show "Looking under the hood?" popup
            if self.show_auto_solve_popup("looking_under_hood"):
                self.perform_auto_solve(puzzle_id)
        else:
            # Third use - show "You can't just do that all day." popup
            if self.show_auto_solve_popup("cant_do_all_day"):
                self.perform_auto_solve(puzzle_id)
                self.hide_auto_solve_button()

    def show_auto_solve_popup(self, popup_type):
        """Show custom auto-solve popup matching puzzle colors"""
        # Get puzzle background and text colors based on difficulty
        current_diff = self.difficulty.get()
        
        # Define colors for each difficulty
        diff_colors = {
            "Easy": {"bg": "#228B22", "fg": "white"},         # Forest green
            "Moderate": {"bg": "#ffe066", "fg": "black"},     # Gold  
            "Tough": {"bg": "#ffa366", "fg": "black"},        # Orange
            "Expert": {"bg": "#800000", "fg": "white"},       # Maroon
            "Evil": {"bg": "#a366ff", "fg": "white"},         # Purple
            "Diabolical": {"bg": "#22223b", "fg": "white"}    # Dark Blue/Black
        }
        
        colors = diff_colors.get(current_diff, {"bg": "#ffffff", "fg": "black"})
        
        # Create popup window
        popup = tk.Toplevel(self.master)
        popup.title("")
        popup.geometry("350x180")
        popup.configure(bg=colors["bg"])
        popup.resizable(False, False)
        
        # Center the popup
        popup.transient(self.master)
        popup.grab_set()
        
        # Center on parent window
        popup.update_idletasks()
        x = (popup.winfo_screenwidth() // 2) - (popup.winfo_width() // 2)
        y = (popup.winfo_screenheight() // 2) - (popup.winfo_height() // 2)
        popup.geometry(f"+{x}+{y}")
        
        # Main frame
        main_frame = tk.Frame(popup, bg=colors["bg"])
        main_frame.pack(expand=True, fill="both", padx=20, pady=20)
        
        # Set message and button text based on popup type
        if popup_type == "looking_under_hood":
            message_text = "Looking under the hood?"
            button_text = "Yep"
        elif popup_type == "cant_do_all_day":
            message_text = "You can't just do that all day."
            button_text = "OK"
        elif popup_type == "limit_reached":
            message_text = "You can't just do that all day."
            button_text = "OK"
        
        # Message label
        message_label = tk.Label(
            main_frame,
            text=message_text,
            font=("Arial", 14, "bold"),
            bg=colors["bg"],
            fg=colors["fg"],
            wraplength=300,
            justify="center"
        )
        message_label.pack(expand=True, pady=(10, 20))
        
        # Button frame
        button_frame = tk.Frame(main_frame, bg=colors["bg"])
        button_frame.pack(pady=(0, 10))
        
        # Result variable to track user choice
        result = [False]
        
        def on_button_click():
            if popup_type == "limit_reached":
                result[0] = False  # Don't auto-solve when limit reached
            else:
                result[0] = True  # User confirmed auto-solve
            popup.destroy()
        
        # Custom styled button (grey)
        button = tk.Button(
            button_frame,
            text=button_text,
            font=("Arial", 11, "bold"),
            bg="#888888",
            fg="white",
            activebackground="#777777",
            activeforeground="white",
            relief=tk.RAISED,
            bd=3,
            width=12,
            height=1,
            command=on_button_click
        )
        button.pack()
        
        # Focus the button for enter key support
        button.focus_set()
        popup.bind('<Return>', lambda e: on_button_click())
        popup.bind('<Escape>', lambda e: on_button_click())
        
        # Wait for the popup to be closed
        popup.wait_window()
        
        return result[0]

    def perform_auto_solve(self, puzzle_id):
        """Actually perform the auto-solve operation"""
        # Record this usage
        self.record_auto_solve_usage()
        
        # Mark this puzzle as auto-solved
        self.auto_solved_puzzles.add(puzzle_id)
        
        # Stop the timer
        self.timer_running = False
        
        # Determine background color based on difficulty
        current_diff = self.difficulty.get()
        if current_diff in ("Moderate", "Tough"):
            bg_color = "#ADD8E6"  # Light blue for Moderate and Tough
            fg_color = "#000080"  # Navy blue text for better contrast
        else:
            bg_color = "#FFD700"  # Gold for other difficulties
            fg_color = "#8B4513"  # Dark brown text
        
        # Fill in all empty cells with the solution
        for i in range(9):
            for j in range(9):
                if hasattr(self, "current_puzzle") and self.current_puzzle[i][j] == 0:
                    text = self.entries[i][j]
                    text.config(state='normal')
                    text.delete('1.0', tk.END)
                    
                    # Clear any notes in this cell
                    self.notes[i][j].clear()
                    
                    # Insert the correct digit with auto-solve styling
                    text.insert('1.0', str(self.solution[i][j]))
                    text.tag_configure(
                        'auto_solve',
                        justify='center',
                        font=('Arial', 24, 'bold'),
                        foreground=fg_color,
                        lmargin1=0, lmargin2=0, rmargin=0,
                        spacing1=8, spacing3=8
                    )
                    text.tag_add('auto_solve', '1.0', 'end')
                    text.config(bg=bg_color)  # Background color based on difficulty
                    text.config(state='disabled')  # Make auto-solved cells non-editable
        
        # Update number buttons
        self.update_number_buttons()

    def hide_auto_solve_button(self):
        """Hide the auto-solve button for 30 minutes"""
        if hasattr(self, 'auto_solve_button'):
            self.auto_solve_button.pack_forget()
        
        # Schedule to show the button again after 30 minutes (1800000 ms)
        self.master.after(1800000, self.show_auto_solve_button)

    def show_auto_solve_button(self):
        """Show the auto-solve button again"""
        if hasattr(self, 'auto_solve_button') and hasattr(self, 'auto_solve_button_parent'):
            # Re-pack the button in its original location
            self.auto_solve_button.pack(side=tk.LEFT, padx=5)

    def check_and_animate_completions(self, row, col):
        """Check for completed rows, columns, and 3x3 sections and animate them with ripple waves"""
        if not hasattr(self, "solution"):
            return
        
        # Collect all new completions
        new_completions = []
        
        # Check if the current row is complete
        if self.is_row_complete(row):
            if not hasattr(self, 'completed_rows'):
                self.completed_rows = set()
            if row not in self.completed_rows:
                self.completed_rows.add(row)
                new_completions.append(('row', row))
        
        # Check if the current column is complete
        if self.is_column_complete(col):
            if not hasattr(self, 'completed_columns'):
                self.completed_columns = set()
            if col not in self.completed_columns:
                self.completed_columns.add(col)
                new_completions.append(('column', col))
        
        # Check if the current 3x3 section is complete
        section_row, section_col = 3 * (row // 3), 3 * (col // 3)
        if self.is_section_complete(section_row, section_col):
            if not hasattr(self, 'completed_sections'):
                self.completed_sections = set()
            section_key = (section_row, section_col)
            if section_key not in self.completed_sections:
                self.completed_sections.add(section_key)
                new_completions.append(('section', section_row, section_col))
        
        # Check if any digit is now completed (all 9 instances placed correctly)
        # Check ALL digits, not just the one that was placed, because placing one digit
        # might reveal that other digits are now complete due to note clearing or other effects
        if not hasattr(self, 'completed_digits'):
            self.completed_digits = set()
            
        for digit in range(1, 10):
            if digit not in self.completed_digits and self.is_digit_complete(digit):
                self.completed_digits.add(digit)
                new_completions.append(('digit', digit))
        
        # If we have completions, start animating them in sequence
        if new_completions:
            self.pending_animations = new_completions
            self.start_next_animation()

    def is_row_complete(self, row):
        """Check if a row is completely and correctly filled"""
        for col in range(9):
            text = self.entries[row][col]
            # Check if cell has a main digit (tagged with 'center') that matches the solution
            if 'center' not in text.tag_names('1.0'):
                return False  # Cell has no main digit (only notes or empty)
            
            val = text.get("1.0", "end-1c").strip()
            # Check if cell has a single digit and it matches the solution
            if (len(val) != 1 or not val.isdigit() or 
                int(val) != self.solution[row][col]):
                return False
        return True

    def is_column_complete(self, col):
        """Check if a column is completely and correctly filled"""
        for row in range(9):
            text = self.entries[row][col]
            # Check if cell has a main digit (tagged with 'center') that matches the solution
            if 'center' not in text.tag_names('1.0'):
                return False  # Cell has no main digit (only notes or empty)
            
            val = text.get("1.0", "end-1c").strip()
            # Check if cell has a single digit and it matches the solution
            if (len(val) != 1 or not val.isdigit() or 
                int(val) != self.solution[row][col]):
                return False
        return True

    def is_section_complete(self, section_row, section_col):
        """Check if a 3x3 section is completely and correctly filled"""
        for i in range(section_row, section_row + 3):
            for j in range(section_col, section_col + 3):
                text = self.entries[i][j]
                # Check if cell has a main digit (tagged with 'center') that matches the solution
                if 'center' not in text.tag_names('1.0'):
                    return False  # Cell has no main digit (only notes or empty)
                
                val = text.get("1.0", "end-1c").strip()
                # Check if cell has a single digit and it matches the solution
                if (len(val) != 1 or not val.isdigit() or 
                    int(val) != self.solution[i][j]):
                    return False
        return True

    def is_digit_complete(self, digit):
        """Check if all 9 instances of a digit are correctly placed"""
        correct_count = 0
        for i in range(9):
            for j in range(9):
                text_widget = self.entries[i][j]
                
                # Only count cells that have the 'center' tag (main digits, not notes)
                if 'center' not in text_widget.tag_names('1.0'):
                    continue  # Skip cells that only have notes or are empty
                
                val = text_widget.get("1.0", "end-1c").strip()
                
                # Only count main digits that match the target digit and solution
                if (val and 
                    len(val) == 1 and 
                    val.isdigit() and
                    int(val) == digit and
                    hasattr(self, "solution") and 
                    int(val) == self.solution[i][j]):
                    correct_count += 1
        
        return correct_count >= 9

    def start_next_animation(self):
        """Start the next animation in the queue"""
        # Don't start new animation if one is already running
        if hasattr(self, 'animation_running') and self.animation_running:
            # Wait a bit and try again
            self.master.after(100, self.start_next_animation)
            return
        
        # Check if we have pending animations
        if not hasattr(self, 'pending_animations') or not self.pending_animations:
            return
        
        # Get the next animation
        next_completion = self.pending_animations.pop(0)
        
        # Check if this is a digit completion animation
        if next_completion[0] == 'digit':
            digit = next_completion[1]
            self.animate_digit_completion(digit)
        else:
            # Start the normal ripple animation for row/column/section
            self.animate_ripple_waves([next_completion])
        
        # If there are more animations, schedule the next one
        if self.pending_animations:
            # Wait for current animation to finish, then start next
            self.master.after(1600, self.start_next_animation)  # 30 frames * 50ms + buffer

    def animate_digit_completion(self, digit):
        """Animate all instances of a completed digit with a special effect"""
        # Don't start if another animation is running
        if hasattr(self, 'animation_running') and self.animation_running:
            # Queue this animation for later
            if not hasattr(self, 'pending_digit_animations'):
                self.pending_digit_animations = []
            self.pending_digit_animations.append(digit)
            return
        
        # Find all cells containing this digit
        digit_cells = []
        original_bgs = {}
        
        for i in range(9):
            for j in range(9):
                text_widget = self.entries[i][j]
                
                # Check if this cell contains the target digit as a main digit
                if 'center' in text_widget.tag_names('1.0'):
                    # Temporarily enable to read content
                    original_state = text_widget.cget('state')
                    text_widget.config(state='normal')
                    cell_val = text_widget.get("1.0", "end-1c").strip()
                    text_widget.config(state=original_state)
                    
                    # Check if this cell contains the completed digit
                    if (cell_val and len(cell_val) == 1 and 
                        cell_val.isdigit() and cell_val == str(digit)):
                        digit_cells.append((i, j))
                        original_bgs[(i, j)] = text_widget.cget('bg')
        
        if not digit_cells:
            return  # No cells found with this digit
        
        # Set up digit completion animation
        self.current_animation = {
            'type': 'digit_completion',
            'digit': digit,
            'cells': digit_cells,
            'color': "#FFD700",  # Gold color for digit completion
            'original_bgs': original_bgs,
            'frame': 0,
            'max_frames': 45  # Slightly longer duration for this special animation
        }
        
        # Start the animation
        self.animation_running = True
        self.update_digit_completion_animation()

    def update_digit_completion_animation(self):
        """Update the digit completion animation with a pulsing gold effect"""
        if not hasattr(self, 'current_animation') or not self.current_animation:
            self.animation_running = False
            return
        
        animation = self.current_animation
        frame = animation['frame']
        max_frames = animation['max_frames']
        
        if frame >= max_frames:
            # Animation completed - restore original backgrounds
            for row, col in animation['cells']:
                # Only restore if the cell isn't currently selected
                if (not hasattr(self, 'selected_entry') or 
                    self.selected_entry != (row, col) or
                    self.entries[row][col].cget('bg') != "#b3daff"):
                    
                    # Restore cell background
                    original_bg = animation['original_bgs'][(row, col)]
                    self.entries[row][col].config(bg=original_bg)
                    
                    # Also restore text tag backgrounds
                    cell_text = self.entries[row][col]
                    for tag in cell_text.tag_names():
                        if tag == 'center':
                            cell_text.tag_configure(tag, background=original_bg)
                        elif tag == 'hint':
                            cell_text.tag_configure(tag, background="#90EE90")  # Light green for hints
                        elif tag == 'auto_solve':
                            # Determine auto-solve background based on difficulty
                            current_diff = self.difficulty.get()
                            if current_diff in ("Moderate", "Tough"):
                                cell_text.tag_configure(tag, background="#ADD8E6")  # Light blue
                            else:
                                cell_text.tag_configure(tag, background="#FFD700")  # Gold
            
            # Clear the current animation
            self.current_animation = None
            self.animation_running = False
            
            # Check if there are any queued digit animations
            if hasattr(self, 'pending_digit_animations') and self.pending_digit_animations:
                next_digit = self.pending_digit_animations.pop(0)
                self.master.after(200, lambda: self.animate_digit_completion(next_digit))
            # Check if we have other types of animations to run
            elif hasattr(self, 'pending_animations') and self.pending_animations:
                self.master.after(200, self.start_next_animation)
            
            return
        
        # Calculate pulsing effect - slower and more elegant than lightning
        progress = frame / max_frames
        
        # Create a smooth pulsing wave effect
        pulse_frequency = 3  # Number of pulses
        pulse_intensity = math.sin(progress * math.pi * pulse_frequency) * 0.7
        
        # Add a fading effect - stronger at the beginning
        fade_factor = 1.0 - (progress * 0.3)  # Gradually fade but keep some intensity
        final_intensity = abs(pulse_intensity) * fade_factor
        
        # Apply the pulsing gold effect to all digit cells
        for cell_row, cell_col in animation['cells']:
            # Don't override selected cell background
            if (not hasattr(self, 'selected_entry') or 
                self.selected_entry != (cell_row, cell_col) or
                self.entries[cell_row][cell_col].cget('bg') != "#b3daff"):
                
                # Create pulsing gold effect
                if final_intensity > 0.1:
                    # Blend gold with the original background
                    original_bg = animation['original_bgs'][(cell_row, cell_col)]
                    blended_color = self.blend_colors(original_bg, "#FFD700", final_intensity)
                    self.entries[cell_row][cell_col].config(bg=blended_color)
                    
                    # Also apply to text tags
                    cell_text = self.entries[cell_row][cell_col]
                    for tag in cell_text.tag_names():
                        if tag in ('center', 'hint', 'auto_solve'):
                            cell_text.tag_configure(tag, background=blended_color)
        
        # Advance to next frame
        animation['frame'] += 1
        
        # Schedule next update (slower than lightning animation)
        self.master.after(60, self.update_digit_completion_animation)

    def animate_ripple_waves(self, completions):
        """Create dramatic lightning effect animations for completed areas"""
        if not completions:
            return
            
        # Handle only the first completion to avoid multiple concurrent animations
        completion = completions[0] if isinstance(completions, list) else completions
        
        # Animation parameters
        lightning_duration = 30  # Shorter duration for quick feedback
        
        # Define unique colors for each completion type
        animation_colors = {
            'row': "#00FFFF",      # Bright cyan for rows
            'column': "#FFFF00",   # Bright yellow for columns  
            'section': "#FF00FF"   # Bright magenta for 3x3 sections
        }
        
        # Get cells for the completion
        if completion[0] == 'row':
            row = completion[1]
            cells = [(row, col) for col in range(9)]
        elif completion[0] == 'column':
            col = completion[1]
            cells = [(row, col) for row in range(9)]
        elif completion[0] == 'section':
            section_row, section_col = completion[1], completion[2]
            cells = [(i, j) for i in range(section_row, section_row + 3) 
                    for j in range(section_col, section_col + 3)]
        
        # Store original backgrounds
        original_bgs = {}
        for row_idx, col_idx in cells:
            original_bgs[(row_idx, col_idx)] = self.entries[row_idx][col_idx].cget('bg')
        
        # Set up single animation
        self.current_animation = {
            'type': completion[0],
            'cells': cells,
            'color': animation_colors[completion[0]],
            'original_bgs': original_bgs,
            'frame': 0,
            'max_frames': lightning_duration
        }
        
        # Start the animation
        self.animation_running = True
        self.update_lightning_animation()

    def update_lightning_animation(self):
        """Update the current lightning effect animation"""
        import math
        import random
        
        if not hasattr(self, 'current_animation') or not self.current_animation:
            self.animation_running = False
            return
        
        # If this is a victory animation, use the special victory animation method
        if self.current_animation.get('type') == 'victory':
            self.update_victory_animation()
            return
        
        animation = self.current_animation
        frame = animation['frame']
        max_frames = animation['max_frames']
        
        if frame >= max_frames:
            # Animation completed - restore original backgrounds
            for row, col in animation['cells']:
                # Only restore if the cell isn't currently selected
                if (not hasattr(self, 'selected_entry') or 
                    self.selected_entry != (row, col) or
                    self.entries[row][col].cget('bg') != "#b3daff"):
                    
                    # Restore cell background
                    original_bg = animation['original_bgs'][(row, col)]
                    self.entries[row][col].config(bg=original_bg)
                    
                    # Also restore text tag backgrounds
                    cell_text = self.entries[row][col]
                    for tag in cell_text.tag_names():
                        if tag == 'center':
                            cell_text.tag_configure(tag, background=original_bg)
                        elif tag == 'notes':
                            cell_text.tag_configure(tag, background=original_bg)
                        elif tag == 'hint':
                            cell_text.tag_configure(tag, background="#90EE90")  # Light green for hints
                        elif tag == 'auto_solve':
                            # Determine auto-solve background based on difficulty
                            current_diff = self.difficulty.get()
                            if current_diff in ("Moderate", "Tough"):
                                cell_text.tag_configure(tag, background="#ADD8E6")  # Light blue
                            else:
                                cell_text.tag_configure(tag, background="#FFD700")  # Gold
            
            # Check if this was a victory animation
            is_victory = animation['type'] == 'victory'
            
            # Clear the current animation
            self.current_animation = None
            self.animation_running = False
            
            # If victory animation, proceed to reward screen
            if is_victory:
                self.master.after(500, self.show_reward_screen)
            else:
                # Check if we have more animations to run
                if hasattr(self, 'pending_animations') and self.pending_animations:
                    self.master.after(200, self.start_next_animation)  # Small delay between animations
            
            return
        
        # Calculate lightning effect
        progress = frame / max_frames
        lightning_color = animation['color']
        
        # Create dramatic lightning flashes
        for cell_row, cell_col in animation['cells']:
            # Lightning strikes randomly but with higher intensity at the beginning
            lightning_probability = max(0.3, 1.0 - progress)
            
            # Create multiple lightning phases
            flash_intensity = 0
            
            # Primary lightning flash (fast and intense)
            if progress < 0.4:
                primary_flash = math.sin(progress * math.pi * 6) * (1.0 - progress / 0.4)
                if random.random() < lightning_probability:
                    flash_intensity += primary_flash * 1.0
            
            # Secondary crackling (medium intensity, random)
            elif progress < 0.8:
                if random.random() < 0.5:
                    crackling = random.uniform(0.4, 0.8)
                    flash_intensity += crackling
            
            # Afterglow (fading out)
            else:
                afterglow = (1.0 - progress) * 0.6
                flash_intensity += afterglow
            
            # Add random lightning bolts (brief intense flashes)
            if random.random() < 0.1:
                flash_intensity += random.uniform(0.9, 1.0)
            
            # Make sure there's ALWAYS some visible effect in the first half
            if progress < 0.5 and flash_intensity < 0.2:
                flash_intensity = random.uniform(0.3, 0.7)
            
            # Apply lightning effect
            if flash_intensity > 0.05:
                # Don't override selected cell background
                if (not hasattr(self, 'selected_entry') or 
                    self.selected_entry != (cell_row, cell_col) or
                    self.entries[cell_row][cell_col].cget('bg') != "#b3daff"):
                    
                    # Get base color and create lightning blend
                    base_color = animation['original_bgs'][(cell_row, cell_col)]
                    
                    # Cap intensity and create dramatic effect
                    intensity = min(flash_intensity, 1.0)
                    blended_color = self.blend_colors(base_color, lightning_color, intensity)
                    
                    # Set cell background
                    self.entries[cell_row][cell_col].config(bg=blended_color)
                    
                    # Also update any text tag backgrounds
                    cell_text = self.entries[cell_row][cell_col]
                    for tag in cell_text.tag_names():
                        if tag in ('center', 'notes', 'hint', 'auto_solve'):
                            cell_text.tag_configure(tag, background=blended_color)
        
        # Advance to next frame
        animation['frame'] += 1
        
        # Schedule next update
        self.master.after(50, self.update_lightning_animation)

    def blend_colors(self, base_color, ripple_color, intensity):
        """Blend two colors with given intensity"""
        try:
            # Handle named colors
            if base_color == "white":
                base_rgb = (255, 255, 255)
            elif base_color == "SystemButtonFace":
                base_rgb = (240, 240, 240)  # Light gray approximation
            elif base_color.startswith('#'):
                base_rgb = tuple(int(base_color[i:i+2], 16) for i in (1, 3, 5))
            else:
                base_rgb = (255, 255, 255)  # Default to white
            
            # Parse ripple color
            if ripple_color.startswith('#'):
                ripple_rgb = tuple(int(ripple_color[i:i+2], 16) for i in (1, 3, 5))
            else:
                ripple_rgb = (255, 255, 255)
            
            # Blend colors
            blended_rgb = tuple(
                int(base_rgb[i] * (1 - intensity) + ripple_rgb[i] * intensity)
                for i in range(3)
            )
            
            return f"#{blended_rgb[0]:02x}{blended_rgb[1]:02x}{blended_rgb[2]:02x}"
        except:
            return base_color  # Return original color if blending fails

    def initialize_completion_tracking(self):
        """Initialize completion tracking and mark any already completed areas"""
        self.completed_rows = set()
        self.completed_columns = set()
        self.completed_sections = set()
        self.completed_digits = set()
        
        # Check for already completed rows
        for row in range(9):
            if self.is_row_complete(row):
                self.completed_rows.add(row)
        
        # Check for already completed columns
        for col in range(9):
            if self.is_column_complete(col):
                self.completed_columns.add(col)
        
        # Check for already completed 3x3 sections
        for section_row in range(0, 9, 3):
            for section_col in range(0, 9, 3):
                if self.is_section_complete(section_row, section_col):
                    self.completed_sections.add((section_row, section_col))
        
        # Check for already completed digits
        for digit in range(1, 10):
            if self.is_digit_complete(digit):
                self.completed_digits.add(digit)

    def animate_victory_ripples(self):
        """Create a beautiful victory animation with golden ripples across the board"""
        
        # Don't start victory animation if already running an animation
        if hasattr(self, 'animation_running') and self.animation_running:
            self.master.after(500, self.animate_victory_ripples)
            return
        
        # Store original backgrounds for all cells
        original_bgs = {}
        for i in range(9):
            for j in range(9):
                original_bgs[(i, j)] = self.entries[i][j].cget('bg')
        
        # Create victory animation - covers the entire board
        self.current_animation = {
            'type': 'victory',
            'cells': [(i, j) for i in range(9) for j in range(9)],  # All cells
            'color': "#FFD700",  # Golden color for victory
            'original_bgs': original_bgs,
            'frame': 0,
            'max_frames': 120  # Longer duration for victory animation
        }
        
        # Start the victory animation
        self.animation_running = True
        self.update_victory_animation()

    def update_victory_animation(self):
        """Update the victory animation with beautiful golden ripples"""
        import math
        
        if not hasattr(self, 'current_animation') or not self.current_animation:
            self.animation_running = False
            return
        
        animation = self.current_animation
        frame = animation['frame']
        max_frames = animation['max_frames']
        
        if frame >= max_frames:
            # Animation completed - restore original backgrounds
            for row, col in animation['cells']:
                # Only restore if the cell isn't currently selected
                if (not hasattr(self, 'selected_entry') or 
                    self.selected_entry != (row, col) or
                    self.entries[row][col].cget('bg') != "#b3daff"):
                    
                    # Restore cell background
                    original_bg = animation['original_bgs'][(row, col)]
                    self.entries[row][col].config(bg=original_bg)
                    
                    # Also restore text tag backgrounds
                    cell_text = self.entries[row][col]
                    for tag in cell_text.tag_names():
                        if tag == 'center':
                            cell_text.tag_configure(tag, background=original_bg)
                        elif tag == 'notes':
                            cell_text.tag_configure(tag, background=original_bg)
                        elif tag == 'hint':
                            cell_text.tag_configure(tag, background="#90EE90")  # Light green for hints
                        elif tag == 'auto_solve':
                            # Determine auto-solve background based on difficulty
                            current_diff = self.difficulty.get()
                            if current_diff in ("Moderate", "Tough"):
                                cell_text.tag_configure(tag, background="#ADD8E6")  # Light blue
                            else:
                                cell_text.tag_configure(tag, background="#FFD700")  # Gold
            
            # Clear the current animation
            self.current_animation = None
            self.animation_running = False
            
            # Proceed to reward screen
            self.master.after(500, self.show_reward_screen)
            return
        
        # Calculate progress through animation
        progress = frame / max_frames
        
        # Create beautiful ripple effect from center outward
        center_row, center_col = 4, 4  # Center of 9x9 grid
        
        for cell_row, cell_col in animation['cells']:
            # Calculate distance from center
            distance = math.sqrt((cell_row - center_row)**2 + (cell_col - center_col)**2)
            
            # Create ripple waves that travel outward
            wave_speed = 8.0  # How fast the wave travels
            wave_position = progress * wave_speed
            
            # Multiple overlapping waves for richer effect
            wave1 = math.sin((wave_position - distance) * 2 * math.pi) 
            wave2 = math.sin((wave_position - distance) * 3 * math.pi + math.pi/4)
            wave3 = math.sin((wave_position - distance) * 1.5 * math.pi + math.pi/2)
            
            # Combine waves with different intensities
            combined_wave = (wave1 * 0.5 + wave2 * 0.3 + wave3 * 0.2)
            
            # Create fade-in effect at the beginning and sparkle at the end
            if progress < 0.2:
                # Fade in effect
                fade_intensity = progress / 0.2
                combined_wave *= fade_intensity
            elif progress > 0.8:
                # Sparkle effect - random bright flashes
                sparkle_chance = (progress - 0.8) / 0.2
                if hash((cell_row, cell_col, frame // 3)) % 100 < sparkle_chance * 30:
                    combined_wave = max(combined_wave, 0.8 + sparkle_chance * 0.2)
            
            # Calculate intensity (always positive, 0 to 1)
            intensity = max(0, min(1, (combined_wave + 1) / 2))
            
            # Apply minimum intensity for subtle glow
            intensity = max(intensity, 0.1 + 0.2 * math.sin(progress * 2 * math.pi))
            
            # Don't override selected cell background
            if (not hasattr(self, 'selected_entry') or 
                self.selected_entry != (cell_row, cell_col) or
                self.entries[cell_row][cell_col].cget('bg') != "#b3daff"):
                
                # Get base color and create golden blend
                base_color = animation['original_bgs'][(cell_row, cell_col)]
                blended_color = self.blend_colors(base_color, animation['color'], intensity)
                
                # Set cell background
                self.entries[cell_row][cell_col].config(bg=blended_color)
                
                # Also update any text tag backgrounds
                cell_text = self.entries[cell_row][cell_col]
                for tag in cell_text.tag_names():
                    if tag in ('center', 'notes', 'hint', 'auto_solve'):
                        cell_text.tag_configure(tag, background=blended_color)
        
        # Advance to next frame
        animation['frame'] += 1
        
        # Schedule next update (slower for smoother effect)
        self.master.after(40, self.update_victory_animation)

# Main execution
if __name__ == "__main__":
    root = tk.Tk()
    app = SudokuApp(root)
    root.mainloop()
