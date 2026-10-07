# Interview

Windows 10/11. Run in PowerShell, in this order.

```powershell
winget install -e --id Python.Python.3.13
```

Close PowerShell, open a new one, then:

```powershell
python --version
```

```powershell
git clone https://github.com/Hiteshacu/Interview.git
```

```powershell
cd Interview
```

```powershell
python -m pip install pynput pillow
```

Paste the keys into `API_KEYS`, then save and close:

```powershell
notepad overlay_alert.py
```

Check the Groq key (prints model names):

```powershell
python overlay_alert.py --models groq
```

Start:

```powershell
python overlay_alert.py
```

Hold **A** for 1 second to open. **Esc** to close.

Stop:

```powershell
taskkill /im python.exe /f
```
