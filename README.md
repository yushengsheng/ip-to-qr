# ip-to-qr

Windows desktop tool for converting Socks5 proxy records into QR codes.

## Features

- Import proxy rows from text files or pasted content
- Generate and preview QR codes inside the app
- Test website connectivity through proxies
- Export valid source rows
- Build and run on Windows without extra project setup

## Input format

Supported row formats:

1. `IP|PORT|USER|PASSWORD`
2. `IP|PORT|USER|PASSWORD|DATE`
3. `REMARKS IP|PORT|USER|PASSWORD|DATE`
4. `IP|PORT|USER|PASSWORD|DATE REMARKS`

## Local run

Double-click `start_test.bat`, or run:

```bat
start_test.bat
```

## Release build

Use PyInstaller with the included spec file:

```bat
pyinstaller qrcode_gui.spec --noconfirm --clean
```
