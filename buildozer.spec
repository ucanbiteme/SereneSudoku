[app]
title = Serene Sudoku
package.name = serenesudoku
package.domain = com.serenesudoku

source.dir = .
# include all needed asset extensions including gif for animated backgrounds and wav for sounds
source.include_exts = py,png,jpg,jpeg,mp3,ogg,wav,ttf,ttc,html,gif
source.include_patterns = Images/*,fonts/*,Sounds/*,sudoku_tutorial.html
# exclude obvious non-essential files and backups
source.exclude_patterns = *_backup*,*.mp4,*.MP4,*.pyc,*.log,*.zip
# drop any development or large support directories
source.exclude_dirs = tests, bin, venv, .venv, venv_wsl, .venv_wsl, wsl_venv, __pycache__, .buildozer, SudokuDesktopApp, SereneSudokuClean, SereneSudokuClean 11.4.2025 - 2nd - Use This, kivy_env, kivy_venv, kivy_venv_wsl, kivy_build_env, kivy_buildozer_env_310, kivy_buildozer_env_311, myvenv, buildenv, sudoku_build_env, clean_build_env, install_time_assets, Images_backup, Images_originals_backup, OLD_DEBUG_FILES, .idea, .vscode, WORKING_Sudoku_Android_APK_Backup_WITH_Purchases

version = 1.8.52
requirements = python3,kivy==2.2.1,pillow,pyjnius==1.6.1

presplash.filename = %(source.dir)s/Images/splash.png
icon.filename = %(source.dir)s/Images/app_icon_circle.png

# Android adaptive icon configuration
android.icon_foreground = %(source.dir)s/Images/app_icon_circle.png
android.icon_background = #00000000

# Android permissions - includes BILLING for in-app purchases
android.permissions = INTERNET,ACCESS_NETWORK_STATE,WAKE_LOCK,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,com.android.vending.BILLING
orientation = portrait
fullscreen = 0

# Gradle dependencies - Google Play Billing, Play Review, WebKit
android.gradle_dependencies = com.android.billingclient:billing:6.1.0,com.google.android.play:review:2.0.1,androidx.webkit:webkit:1.4.0

# Release signing configuration
android.release_artifact = aab
android.keystore = /home/timpe/release-key.jks
android.keyalias = sudoku-key
android.keystore_passwd = Sudoku4Ever
android.keyalias_passwd = Sudoku4Ever

# Android build settings
# API 34 used instead of 35 to avoid 16KB page size requirement
# which is not yet supported by python-for-android/SDL2 bootstrap
android.api = 34
android.minapi = 21
android.ndk = 25b
android.ndk_api = 21
android.archs = arm64-v8a
android.private_storage = True

# Increment this for each release to Google Play
android.numeric_version = 87

# Hook to fix pyjnius 1.6.1 Python 2 syntax compatibility + 16KB page size
p4a.hook = ./fix_pyjnius.py

[buildozer]
log_level = 2
