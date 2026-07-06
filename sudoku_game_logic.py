#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pure Sudoku Game Logic Module

This module contains the core Sudoku game logic separated from any UI framework.
It handles board management, move validation, puzzle generation, and solving.
"""

import random
import time
import copy


class SudokuGameLogic:
    """
    Core Sudoku game logic class that handles board state, validation, and puzzle generation.
    This class is UI-agnostic and can be used with any frontend framework.
    """
    
    def __init__(self, difficulty="Easy"):
        """Initialize a new Sudoku game logic instance."""
        self.board = [[0 for _ in range(9)] for _ in range(9)]  # Working board with moves
        self.solution = [[0 for _ in range(9)] for _ in range(9)]
        self.current_puzzle = [[0 for _ in range(9)] for _ in range(9)]  # Original clues only
        self.notes = [[set() for _ in range(9)] for _ in range(9)]
        self.mistake_count = 0
        self.hint_count = 0
        self.difficulty = difficulty
        self.auto_solve_usage = []
        self.auto_solved_puzzles = set()
        
        # Difficulty settings - reduced attempts for difficult levels to improve performance
        self.difficulty_attempts = {
            "Easy": 36,
            "Moderate": 40,
            "Tough": 44,
            "Expert": 48,
            "Evil": 50,        # Reduced from 56
            "Diabolical": 52   # Reduced from 60
        }
    
    def set_difficulty(self, difficulty):
        """Set the puzzle difficulty level."""
        if difficulty in self.difficulty_attempts:
            self.difficulty = difficulty
        else:
            raise ValueError(f"Invalid difficulty: {difficulty}")
    
    def get_difficulty(self):
        """Get the current difficulty level."""
        return self.difficulty
    
    def reset_game_state(self):
        """Reset all game state variables for a new game."""
        self.mistake_count = 0
        self.hint_count = 0
        self.notes = [[set() for _ in range(9)] for _ in range(9)]
    def is_solved(self):
        """Return True if the current board matches the solution (i.e., puzzle is solved)."""
        for row in range(9):
            for col in range(9):
                if self.board[row][col] != self.solution[row][col]:
                    return False
        return True
    
    def generate_puzzle(self):
        """
        Generate a new Sudoku puzzle with the current difficulty setting.
        Returns a tuple of (puzzle, solution) where puzzle has empty cells (0) and clues.
        Includes fallback for difficult puzzles to prevent hanging.
        """
        self.reset_game_state()
        
        # Generate a complete valid Sudoku board
        full_board = self.generate_full_board()
        self.solution = [row[:] for row in full_board]
        
        # Create puzzle by removing cells based on difficulty
        attempts = self.difficulty_attempts[self.difficulty]
        
        # For very difficult puzzles, use more conservative settings if needed
        if self.difficulty in ["Evil", "Diabolical"]:
            print(f"[PUZZLE GEN] Generating {self.difficulty} puzzle with {attempts} attempts")
            # First try with normal timeout
            puzzle = self.make_puzzle(full_board, attempts, timeout_seconds=15)
            
            # If we couldn't remove enough cells, try with reduced attempts as fallback
            empty_count = sum(1 for row in puzzle for cell in row if cell == 0)
            min_empty_for_difficulty = {"Evil": 45, "Diabolical": 47}
            
            if empty_count < min_empty_for_difficulty.get(self.difficulty, 40):
                print(f"[PUZZLE GEN] First attempt only removed {empty_count} cells, trying fallback")
                fallback_attempts = attempts - 8  # Reduce by 8 cells
                puzzle = self.make_puzzle(full_board, fallback_attempts, timeout_seconds=8)
        else:
            puzzle = self.make_puzzle(full_board, attempts)
        
        self.current_puzzle = [row[:] for row in puzzle]
        
        # Initialize working board with the puzzle
        self.board = [row[:] for row in puzzle]
        
        empty_count = sum(1 for row in puzzle for cell in row if cell == 0)
        print(f"[PUZZLE GEN] Final puzzle for {self.difficulty}: {empty_count} empty cells")
        
        return puzzle, self.solution
    
    def generate_full_board(self):
        """Generate a complete valid 9x9 Sudoku board."""
        board = [[0]*9 for _ in range(9)]
        self.solve_board(board)
        return [row[:] for row in board]
    
    def solve_board(self, board):
        """
        Solve a Sudoku board using backtracking algorithm.
        Modifies the board in place and returns True if solved.
        """
        empty = self.find_empty(board)
        if not empty:
            return True
        
        row, col = empty
        nums = list(range(1, 10))
        random.shuffle(nums)  # Add randomness for puzzle generation
        
        for num in nums:
            if self.is_safe(board, row, col, num):
                board[row][col] = num
                if self.solve_board(board):
                    return True
                board[row][col] = 0
        
        return False
    
    def find_empty(self, board):
        """Find the first empty cell (0) in the board."""
        for i in range(9):
            for j in range(9):
                if board[i][j] == 0:
                    return (i, j)
        return None
    
    def is_safe(self, board, row, col, num):
        """
        Check if placing a number at the given position is valid according to Sudoku rules.
        """
        # Check row
        for i in range(9):
            if board[row][i] == num:
                return False
        
        # Check column
        for i in range(9):
            if board[i][col] == num:
                return False
        
        # Check 3x3 box
        start_row, start_col = 3 * (row // 3), 3 * (col // 3)
        for i in range(3):
            for j in range(3):
                if board[start_row + i][start_col + j] == num:
                    return False
        
        return True
    
    def make_puzzle(self, board, attempts=40, timeout_seconds=10):
        """
        Create a puzzle by removing cells from a complete board.
        Ensures the resulting puzzle has a unique solution.
        Added timeout mechanism to prevent hanging on difficult puzzles.
        """
        import time
        start_time = time.time()
        
        puzzle = [row[:] for row in board]
        
        # Randomize cell order for even distribution of clues across the grid
        cells = [(i, j) for i in range(9) for j in range(9)]
        random.shuffle(cells)
        
        removed = 0
        checks_performed = 0
        fast_checks = 0  # Count of quick checks (early termination)
        
        for row, col in cells:
            # Check for timeout
            current_time = time.time()
            if current_time - start_time > timeout_seconds:
                print(f"[PUZZLE GEN] Timeout reached after {timeout_seconds}s, returning puzzle with {removed} cells removed")
                break
                
            if removed >= attempts:
                continue
                
            backup = puzzle[row][col]
            puzzle[row][col] = 0
            board_copy = [r[:] for r in puzzle]
            checks_performed += 1
            
            # Use progressively more restrictive limits as time progresses
            elapsed = current_time - start_time
            if elapsed > timeout_seconds * 0.7:  # In final 30% of time
                max_checks = 2000  # Very restrictive
            elif elapsed > timeout_seconds * 0.4:  # In middle 30% of time  
                max_checks = 3000  # Moderately restrictive
            else:
                max_checks = 5000  # Normal limit
                
            if self.has_unique_solution(board_copy, max_checks):
                removed += 1
            else:
                puzzle[row][col] = backup
        
        print(f"[PUZZLE GEN] Generated puzzle: removed {removed}/{attempts} cells, performed {checks_performed} uniqueness checks in {time.time() - start_time:.2f}s")
        return puzzle
    
    def has_unique_solution(self, board, max_checks=5000):
        """
        Check if a Sudoku puzzle has exactly one unique solution.
        Uses early termination and limits the number of recursive calls to prevent hanging.
        """
        solutions = []
        check_count = [0]  # Use list to allow modification in nested function
        
        def solve(b):
            check_count[0] += 1
            # Early termination if we've exceeded max checks or found multiple solutions
            if check_count[0] > max_checks or len(solutions) > 1:
                return
                
            empty = self.find_empty(b)
            if not empty:
                solutions.append(1)
                return
                
            row, col = empty
            for num in range(1, 10):
                if check_count[0] > max_checks or len(solutions) > 1:
                    return
                if self.is_safe(b, row, col, num):
                    b[row][col] = num
                    solve(b)
                    b[row][col] = 0
        
        solve([row[:] for row in board])
        
        # If we exceeded max checks, assume the puzzle is too complex and skip it
        if check_count[0] > max_checks:
            return False
            
        return len(solutions) == 1
    
    def is_valid_move(self, row, col, num):
        """
        Check if a move is valid without modifying the board.
        Returns True if the move follows Sudoku rules.
        """
        if not (0 <= row < 9 and 0 <= col < 9):
            return False
        
        if not (1 <= num <= 9):
            return False
        
        # Use the current working board to test the move
        return self.is_safe(self.board, row, col, num)
    
    def is_correct_move(self, row, col, num):
        """
        Check if a move matches the solution.
        """
        if not (0 <= row < 9 and 0 <= col < 9):
            return False
        
        return self.solution[row][col] == num
    
    def make_move(self, row, col, num):
        """
        Attempt to make a move on the board.
        Returns a dictionary with move result information.
        """
        if not (0 <= row < 9 and 0 <= col < 9):
            return {"valid": False, "error": "Invalid position"}
        
        if not (1 <= num <= 9):
            return {"valid": False, "error": "Invalid number"}
        
        # Check if cell is a clue cell (cannot be modified)
        if self.current_puzzle[row][col] != 0:
            return {"valid": False, "error": "Cannot modify clue cell"}
        
        # Check if move follows Sudoku rules
        valid_sudoku_move = self.is_valid_move(row, col, num)
        
        # Check if move matches solution
        correct = self.is_correct_move(row, col, num)
        
        # A move is a mistake if it violates Sudoku rules OR doesn't match the solution
        is_mistake = not valid_sudoku_move or not correct
        
        if is_mistake:
            self.mistake_count += 1
            # Still place the move on the working board even if incorrect
            self.board[row][col] = num
            return {
                "valid": True,
                "correct": False,
                "mistake": True,
                "mistake_count": self.mistake_count
            }
        
        # Place the correct move on the working board
        self.board[row][col] = num
        return {
            "valid": True,
            "correct": True,
            "mistake": False,
            "mistake_count": None
        }
    
    def clear_cell(self, row, col):
        """Clear a cell if it's not a clue cell."""
        if not (0 <= row < 9 and 0 <= col < 9):
            return False
        
        if self.current_puzzle[row][col] != 0:
            return False  # Cannot clear clue cells
        
        # Clear the cell on working board
        self.board[row][col] = 0
        # Clear notes for this cell
        self.notes[row][col].clear()
        return True
    
    def toggle_note(self, row, col, num):
        """
        Toggle a note in a cell.
        Returns True if note was added, False if removed.
        """
        if not (0 <= row < 9 and 0 <= col < 9):
            return False
        
        if not (1 <= num <= 9):
            return False
        
        if self.current_puzzle[row][col] != 0:
            return False  # Cannot add notes to clue cells
        
        notes = self.notes[row][col]
        if num in notes:
            notes.remove(num)
            return False
        else:
            notes.add(num)
            return True
    
    def get_notes(self, row, col):
        """Get the set of notes for a cell."""
        if not (0 <= row < 9 and 0 <= col < 9):
            return set()
        
        return self.notes[row][col].copy()
    
    def clear_conflicting_notes(self, row, col, num):
        """
        Clear all notes of a specific number from the same row, column, and 3x3 box.
        This is typically called when a number is placed.
        """
        # Clear from same row
        for j in range(9):
            if j != col and num in self.notes[row][j]:
                self.notes[row][j].remove(num)
        
        # Clear from same column
        for i in range(9):
            if i != row and num in self.notes[i][col]:
                self.notes[i][col].remove(num)
        
        # Clear from same 3x3 box
        start_row, start_col = 3 * (row // 3), 3 * (col // 3)
        for i in range(start_row, start_row + 3):
            for j in range(start_col, start_col + 3):
                if (i != row or j != col) and num in self.notes[i][j]:
                    self.notes[i][j].remove(num)
    
    def is_puzzle_complete(self):
        """Check if the current puzzle is completely and correctly solved."""
        for i in range(9):
            for j in range(9):
                if self.board[i][j] == 0:
                    return False
                if self.board[i][j] != self.solution[i][j]:
                    return False
        return True
    
    def get_hint(self):
        """
        Get a hint by returning the position and number for an empty cell.
        Returns None if no hints available or puzzle is complete.
        """
        if self.hint_count >= 2:
            return None
        
        # Find all empty cells
        empty_cells = []
        for i in range(9):
            for j in range(9):
                if self.current_puzzle[i][j] == 0:
                    empty_cells.append((i, j))
        
        if not empty_cells:
            return None
        
        # Choose a random empty cell
        row, col = random.choice(empty_cells)
        correct_num = self.solution[row][col]
        
        self.hint_count += 1
        
        return {
            "row": row,
            "col": col,
            "number": correct_num,
            "hints_remaining": max(0, 2 - self.hint_count)
        }
    
    def is_auto_solve_available(self):
        """Check if auto-solve is available (max 3 uses per 30 minutes)."""
        current_time = time.time()
        
        # Remove timestamps older than 30 minutes
        self.auto_solve_usage = [timestamp for timestamp in self.auto_solve_usage 
                                if current_time - timestamp < 1800]
        
        return len(self.auto_solve_usage) < 3
    
    def auto_solve(self):
        """
        Auto-solve the current puzzle.
        Returns the complete solution if available, None otherwise.
        """
        if not self.is_auto_solve_available():
            return None
        
        # Create puzzle ID to prevent multiple auto-solves of same puzzle
        puzzle_id = str(self.current_puzzle)
        if puzzle_id in self.auto_solved_puzzles:
            return None
        
        # Record usage
        self.auto_solve_usage.append(time.time())
        self.auto_solved_puzzles.add(puzzle_id)
        
        return [row[:] for row in self.solution]
    
    def get_digit_completion_count(self, digit):
        """
        Count how many times a digit appears correctly placed on the board.
        Used for UI updates (like disabling digit buttons when complete).
        """
        count = 0
        for i in range(9):
            for j in range(9):
                if (self.board[i][j] == digit and 
                    self.solution[i][j] == digit):
                    count += 1
        return count
    
    def get_board_state(self):
        """
        Get the current state of the game board.
        Returns a dictionary with all relevant game state information.
        """
        return {
            "current_puzzle": [row[:] for row in self.current_puzzle],  # Original clues
            "board": [row[:] for row in self.board],  # Current working board with moves
            "solution": [row[:] for row in self.solution],
            "notes": [[notes.copy() for notes in row] for row in self.notes],
            "mistake_count": self.mistake_count,
            "hint_count": self.hint_count,
            "difficulty": self.difficulty,
            "is_complete": self.is_puzzle_complete()
        }
    
    def set_board_state(self, state):
        """
        Restore the game board from a saved state dictionary.
        """
        if "current_puzzle" in state:
            self.current_puzzle = [row[:] for row in state["current_puzzle"]]
        if "board" in state:
            self.board = [row[:] for row in state["board"]]
        if "solution" in state:
            self.solution = [row[:] for row in state["solution"]]
        if "notes" in state:
            self.notes = [[set(notes) for notes in row] for row in state["notes"]]
        if "mistake_count" in state:
            self.mistake_count = state["mistake_count"]
        if "hint_count" in state:
            self.hint_count = state["hint_count"]
        if "difficulty" in state:
            self.difficulty = state["difficulty"]
    
    def is_valid_solution(self, board):
        """Validate that a complete board follows all Sudoku rules."""
        # Check rows
        for i in range(9):
            row = set()
            for j in range(9):
                if board[i][j] in row:
                    return False
                row.add(board[i][j])
        
        # Check columns
        for j in range(9):
            col = set()
            for i in range(9):
                if board[i][j] in col:
                    return False
                col.add(board[i][j])
        
        # Check 3x3 boxes
        for box_row in range(3):
            for box_col in range(3):
                nums = set()
                for i in range(3):
                    for j in range(3):
                        num = board[3*box_row+i][3*box_col+j]
                        if num in nums:
                            return False
                        nums.add(num)
        
        return True


def create_sudoku_game(difficulty="Easy"):
    """
    Convenience function to create a new Sudoku game with specified difficulty.
    """
    game = SudokuGameLogic()
    game.set_difficulty(difficulty)
    puzzle, solution = game.generate_puzzle()
    return game, puzzle, solution


# Example usage and testing
if __name__ == "__main__":
    # Create a new game
    game = SudokuGameLogic()
    game.set_difficulty("Easy")
    
    # Generate a puzzle
    puzzle, solution = game.generate_puzzle()
    
    print("Generated puzzle:")
    for row in puzzle:
        print([x if x != 0 else '.' for x in row])
    
    print("\nSolution:")
    for row in solution:
        print(row)
    
    # Test making a move
    result = game.make_move(0, 0, 5)
    print(f"\nMove result: {result}")
    
    # Test hint system
    hint = game.get_hint()
    if hint:
        print(f"Hint: Place {hint['number']} at position ({hint['row']}, {hint['col']})")
        print(f"Hints remaining: {hint['hints_remaining']}")
    
    # Test note functionality
    game.toggle_note(1, 1, 3)
    game.toggle_note(1, 1, 7)
    notes = game.get_notes(1, 1)
    print(f"Notes in cell (1,1): {notes}")
