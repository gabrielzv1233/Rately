### One-file build
```bash
pyinstaller --onefile --name Rately --add-data "templates;templates" --add-data "static;static" --add-data "webhost.py;." --icon=icon.ico app.py
```

### Multi-file build
```bash
pyinstaller --name Rately --add-data "templates;templates" --add-data "static;static" --add-data "webhost.py;." --icon=icon.ico app.py
```