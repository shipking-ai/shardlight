@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  py -3.12 -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
if not exist assets\audio\MANIFEST.json (
  echo Rendering the procedural audio once ^(about a minute^)...
  .venv\Scripts\python.exe tools\gen_audio.py
)
.venv\Scripts\python.exe -m shardlight %*
