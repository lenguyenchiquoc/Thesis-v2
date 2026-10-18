# EthicalQuoc Capture — Chrome extension

One-click workflow: browse the target, click **Complete**, and the captured traffic
is scanned by the local EthicalQuoc tool — no DevTools, no manual HAR export.

## How it works

```
[Extension]  Start -> captures traffic via chrome.debugger (no DevTools needed)
             Complete -> builds a HAR -> POST http://127.0.0.1:8099/scan
[ethicalquoc serve]  runs scan->analyze->assess on the HAR
             -> returns findings -> extension shows them in the popup
```

The server binds to `127.0.0.1` only. The HAR carries real session cookies, so it
never leaves your machine.

## Setup (one time)

1. **Start the local server** (keep it running while you work):
   ```
   cd D:\Thesis\Thesis
   python main.py serve          # listens on 127.0.0.1:8099
   ```
   Optional: `python main.py serve --port 9000`.

2. **Load the extension** in Chrome:
   - Open `chrome://extensions`
   - Turn on **Developer mode** (top-right)
   - **Load unpacked** → select this `Extension/` folder

## Use

1. Make sure the popup shows **● server connected** (green). If it says *server
   offline*, start `python main.py serve` first.
2. Open the target site and log in.
3. Click the extension → **Start capture**. Chrome shows a *"…is debugging this
   browser"* banner — that is the capture running, leave it.
4. Use the site normally (click the features you want tested).
5. Click **Complete**. The popup shows each finding and whether it is likely
   vulnerable.

## Notes

- **Start the server before clicking Complete** — the popup checks this for you and
  disables Complete until the server answers.
- The debugger banner is expected; click **Cancel** (or Complete) to detach.
- Java/.NET payload generation at the `assess` step needs `java` / the .NET runtime
  on the machine running `serve` (same requirement as the CLI). Detection
  (fingerprint/exploit-type) works regardless.
- To change the server address, edit `SERVER` at the top of `popup.js`.
