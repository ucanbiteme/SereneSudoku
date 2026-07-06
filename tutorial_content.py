
TUTORIAL_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>How to Play Sudoku</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(to bottom, #eff6ff, #dbeafe);
            overflow: hidden;
            touch-action: pan-y pinch-zoom;
        }
        
        .container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: flex-start;
            height: 100vh;
            overflow: hidden;
            padding: 2rem 1rem;
        }
        
        .content {
            width: 100%;
            max-width: 28rem;
        }
        
        h1 {
            font-size: 1.875rem;
            font-weight: bold;
            text-align: center;
            color: #1e3a8a;
            margin-bottom: 1.5rem;
        }
        
        .board-container {
            background: white;
            padding: 1rem;
            border-radius: 0.5rem;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            margin-bottom: 1.5rem;
        }
        
        .sudoku-grid {
            display: grid;
            grid-template-columns: repeat(9, 1fr);
            gap: 0;
            border: 4px solid #111827;
        }
        
        .cell {
            aspect-ratio: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.125rem;
            font-weight: 600;
            border: 1px solid #6b7280;
            transition: all 0.5s;
            background: white;
        }
        
        .cell.highlight-row { background: #bfdbfe; }
        .cell.highlight-column { background: #d8b4fe; }
        .cell.highlight-box { background: #fbcfe8; }
        .cell.highlight-target { background: #fde047; }
        .cell.solved { background: #86efac; color: #14532d; }
        
        .cell.border-right { border-right: 2px solid #111827; }
        .cell.border-bottom { border-bottom: 2px solid #111827; }
        
        .text-container {
            background: white;
            padding: 1.5rem;
            border-radius: 0.5rem;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
            margin-bottom: 1.5rem;
            min-height: 8rem;
        }
        
        .narrative-text {
            color: #1f2937;
            font-size: 1.125rem;
            line-height: 1.75rem;
            text-align: center;
            white-space: pre-line;
        }
        
        .progress-container {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 0.25rem;
            margin-bottom: 1rem;
        }
        
        .progress-dot {
            height: 0.5rem;
            width: 0.5rem;
            border-radius: 9999px;
            background: #d1d5db;
            transition: all 0.3s;
        }
        
        .progress-dot.active {
            width: 2rem;
            background: #2563eb;
        }
        
        .controls {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 1rem;
        }
        
        button {
            padding: 0.5rem 1rem;
            border: none;
            border-radius: 0.5rem;
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.2s;
            font-size: 1rem;
            color: white;
        }
        
        .btn-restart {
            background: #6b7280;
        }
        
        .btn-restart:hover {
            background: #4b5563;
        }
        
        .btn-prev, .btn-next {
            background: #3b82f6;
        }
        
        .btn-prev:hover, .btn-next:hover {
            background: #2563eb;
        }
        
        .btn-play {
            padding: 0.5rem 1.5rem;
            background: #22c55e;
        }
        
        .btn-play:hover {
            background: #16a34a;
        }
        
        button:disabled {
            background: #d1d5db;
            cursor: not-allowed;
        }
    </style>
</head>
<body>
    <div class="container" id="container">
        <div class="content">
            <h1>How to Play Sudoku</h1>
            
            <div class="board-container">
                <div class="sudoku-grid" id="grid"></div>
            </div>
            
            <div class="text-container">
                <p class="narrative-text" id="narrative"></p>
            </div>
            
            <div class="progress-container" id="progress"></div>
            
            <div class="controls">
                <button class="btn-restart" onclick="restart()">Restart</button>
                <button class="btn-prev" id="prevBtn" onclick="prevStep()">Previous</button>
                <button class="btn-play" id="playBtn" onclick="togglePlay()">Play</button>
                <button class="btn-next" id="nextBtn" onclick="nextStep()">Next</button>
            </div>
        </div>
    </div>

    <script>
        const initialBoard = [
            [0, 0, 0, 2, 6, 0, 7, 0, 1],
            [6, 8, 0, 0, 7, 0, 0, 9, 0],
            [1, 9, 0, 0, 0, 4, 5, 0, 0],
            [8, 2, 0, 1, 0, 0, 0, 4, 0],
            [0, 0, 4, 6, 0, 2, 9, 0, 0],
            [0, 5, 0, 0, 0, 3, 0, 2, 8],
            [0, 0, 9, 3, 0, 0, 0, 7, 4],
            [0, 4, 0, 0, 5, 0, 0, 3, 6],
            [7, 0, 3, 0, 1, 8, 0, 0, 0]
        ];

        const steps = [
            {
                text: "Welcome to Sudoku! The goal is to fill a 9×9 grid with numbers 1-9.",
                highlights: [],
                type: '',
                placed: {},
                target: null
            },
            {
                text: "Each row must contain the numbers 1 through 9, with no repeats.",
                highlights: [[0, 0], [0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [0, 6], [0, 7], [0, 8]],
                type: 'row',
                placed: {},
                target: null
            },
            {
                text: "Each column must also contain the numbers 1 through 9, with no repeats.",
                highlights: [[0, 4], [1, 4], [2, 4], [3, 4], [4, 4], [5, 4], [6, 4], [7, 4], [8, 4]],
                type: 'column',
                placed: {},
                target: null
            },
            {
                text: "The grid is divided into nine 3×3 boxes. Each box must contain 1-9 with no repeats.",
                highlights: [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2], [2, 0], [2, 1], [2, 2]],
                type: 'box',
                placed: {},
                target: null
            },
            {
                text: "Let's solve a cell! Look at row 1, column 2. What number goes here?",
                highlights: [[0, 1]],
                type: 'target',
                placed: {},
                target: [0, 1]
            },
            {
                text: "Check the row: it has 2, 6, 7, and 1. These can't go in our target cell.",
                highlights: [[0, 0], [0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [0, 6], [0, 7], [0, 8]],
                type: 'row',
                placed: {},
                target: [0, 1]
            },
            {
                text: "Check the column: it has 8, 9, 2, 5, and 4. Our target can't be any of these.",
                highlights: [[0, 1], [1, 1], [2, 1], [3, 1], [4, 1], [5, 1], [6, 1], [7, 1], [8, 1]],
                type: 'column',
                placed: {},
                target: [0, 1]
            },
            {
                text: "Check the 3×3 box: it has 6, 8, 1, and 9. These are also eliminated.",
                highlights: [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1], [1, 2], [2, 0], [2, 1], [2, 2]],
                type: 'box',
                placed: {},
                target: [0, 1]
            },
            {
                text: "We've eliminated 1, 2, 4, 5, 6, 7, 8, and 9. By logic, this cell must be 3!",
                highlights: [[0, 1]],
                type: 'target',
                placed: { '0-1': 3 },
                target: null
            },
            {
                text: "Excellent! Let's solve another. Look at row 9, column 2.",
                highlights: [[8, 1]],
                type: 'target',
                placed: { '0-1': 3 },
                target: [8, 1]
            },
            {
                text: "The row has 7, 3, 1, and 8. Let's check the other constraints.",
                highlights: [[8, 0], [8, 1], [8, 2], [8, 3], [8, 4], [8, 5], [8, 6], [8, 7], [8, 8]],
                type: 'row',
                placed: { '0-1': 3 },
                target: [8, 1]
            },
            {
                text: "The column has 3 (just placed), 8, 9, 2, 5, and 4. The box has 7, 3, 9, and 4.",
                highlights: [[6, 0], [6, 1], [6, 2], [7, 0], [7, 1], [7, 2], [8, 0], [8, 1], [8, 2]],
                type: 'box',
                placed: { '0-1': 3 },
                target: [8, 1]
            },
            {
                text: "We've eliminated 1, 2, 3, 4, 5, 7, 8, and 9. This cell must be 6!",
                highlights: [[8, 1]],
                type: 'target',
                placed: { '0-1': 3, '8-1': 6 },
                target: null
            },
            {
                text: "Perfect! Keep using rows, columns, and boxes to eliminate options.\n\nGood luck!",
                highlights: [],
                type: '',
                placed: { '0-1': 3, '8-1': 6 },
                target: null
            }
        ];

        let currentStep = 0;
        let isPlaying = false;
        let playTimer = null;
        let touchStartX = 0;
        let touchEndX = 0;

        function initGrid() {
            const grid = document.getElementById('grid');
            grid.innerHTML = '';
            
            for (let row = 0; row < 9; row++) {
                for (let col = 0; col < 9; col++) {
                    const cell = document.createElement('div');
                    cell.className = 'cell';
                    cell.id = `cell-${row}-${col}`;
                    
                    if ((col + 1) % 3 === 0 && col !== 8) {
                        cell.classList.add('border-right');
                    }
                    if ((row + 1) % 3 === 0 && row !== 8) {
                        cell.classList.add('border-bottom');
                    }
                    
                    grid.appendChild(cell);
                }
            }
            
            initProgress();
            updateDisplay();
        }

        function initProgress() {
            const progress = document.getElementById('progress');
            progress.innerHTML = '';
            
            for (let i = 0; i < steps.length; i++) {
                const dot = document.createElement('div');
                dot.className = 'progress-dot';
                dot.id = `progress-${i}`;
                progress.appendChild(dot);
            }
        }

        function updateDisplay() {
            const step = steps[currentStep];
            
            // Clear all highlights
            for (let row = 0; row < 9; row++) {
                for (let col = 0; col < 9; col++) {
                    const cell = document.getElementById(`cell-${row}-${col}`);
                    cell.className = 'cell';
                    
                    if ((col + 1) % 3 === 0 && col !== 8) {
                        cell.classList.add('border-right');
                    }
                    if ((row + 1) % 3 === 0 && row !== 8) {
                        cell.classList.add('border-bottom');
                    }
                    
                    // Set value
                    const key = `${row}-${col}`;
                    if (step.placed[key]) {
                        cell.textContent = step.placed[key];
                        cell.classList.add('solved');
                    } else {
                        cell.textContent = initialBoard[row][col] || '';
                    }
                }
            }
            
            // Apply highlights
            step.highlights.forEach(([row, col]) => {
                const cell = document.getElementById(`cell-${row}-${col}`);
                if (step.target && step.target[0] === row && step.target[1] === col) {
                    cell.classList.add('highlight-target');
                } else if (step.type === 'row') {
                    cell.classList.add('highlight-row');
                } else if (step.type === 'column') {
                    cell.classList.add('highlight-column');
                } else if (step.type === 'box') {
                    cell.classList.add('highlight-box');
                }
            });
            
            // Show target cell
            if (step.target) {
                const [row, col] = step.target;
                const cell = document.getElementById(`cell-${row}-${col}`);
                cell.classList.add('highlight-target');
            }
            
            // Update narrative
            document.getElementById('narrative').textContent = step.text;
            
            // Update progress
            for (let i = 0; i < steps.length; i++) {
                const dot = document.getElementById(`progress-${i}`);
                if (i === currentStep) {
                    dot.classList.add('active');
                } else {
                    dot.classList.remove('active');
                }
            }
            
            // Update buttons
            document.getElementById('prevBtn').disabled = currentStep === 0;
            document.getElementById('nextBtn').disabled = currentStep === steps.length - 1;
            
            const playBtn = document.getElementById('playBtn');
            if (currentStep === steps.length - 1) {
                playBtn.textContent = 'Replay';
            } else {
                playBtn.textContent = isPlaying ? 'Pause' : 'Play';
            }
        }

        function nextStep() {
            if (currentStep < steps.length - 1) {
                currentStep++;
                updateDisplay();
            }
        }

        function prevStep() {
            if (currentStep > 0) {
                currentStep--;
                updateDisplay();
            }
        }

        function togglePlay() {
            if (currentStep === steps.length - 1) {
                currentStep = 0;
                isPlaying = true;
            } else {
                isPlaying = !isPlaying;
            }
            
            if (isPlaying) {
                playTimer = setInterval(() => {
                    if (currentStep < steps.length - 1) {
                        nextStep();
                    } else {
                        isPlaying = false;
                        clearInterval(playTimer);
                        updateDisplay();
                    }
                }, 6000);
            } else {
                clearInterval(playTimer);
            }
            
            updateDisplay();
        }

        function restart() {
            currentStep = 0;
            isPlaying = false;
            clearInterval(playTimer);
            updateDisplay();
        }

        // Touch handling
        const container = document.getElementById('container');
        
        container.addEventListener('touchstart', (e) => {
            touchStartX = e.touches[0].clientX;
            touchEndX = e.touches[0].clientX;
        });
        
        container.addEventListener('touchmove', (e) => {
            touchEndX = e.touches[0].clientX;
            
            const swipeDistance = Math.abs(touchStartX - touchEndX);
            if (swipeDistance > 10) {
                e.preventDefault();
            }
        }, { passive: false });
        
        container.addEventListener('touchend', () => {
            const swipeDistance = touchStartX - touchEndX;
            const minSwipeDistance = 50;
            
            if (Math.abs(swipeDistance) > minSwipeDistance) {
                if (swipeDistance > 0) {
                    nextStep();
                } else {
                    prevStep();
                }
            }
        });

        // Initialize on load
        window.onload = initGrid;
    </script>
</body>
</html>"""
