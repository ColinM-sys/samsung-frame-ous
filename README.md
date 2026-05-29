# Samsung Frame-ous

**Put anything on a Samsung Frame TV. No password. No pairing. No permission. Samsung knows and doesn't care.**

---

## Skip the subscription

Samsung charges a monthly fee to display art on The Frame TV through their Art Store. You don't need it.

This tool lets you put any image you want on your Frame TV for free — your own photos, downloaded art, anything — full screen, instant, no Samsung account, no subscription, no app. Just run it on the same WiFi as your TV and broadcast whatever you want.

Free art on your Frame TV forever. That's it.

---

## What this is (the security side)

This tool also scans your WiFi network, finds every Samsung Frame TV, and broadcasts any image to their screens — full screen, instant, no authentication required.

Your neighbor has a Samsung Frame TV on shared WiFi? You can put whatever you want on it. Hotel guest down the hall? Same thing. Apartment building with one shared network? Every Frame TV on the floor.

No credentials. No pairing. No popup on the TV warning the owner. Nothing.

## Samsung's response

These vulnerabilities were reported to Samsung PSIRT (Samsung's security team) in May 2026 with full technical documentation and live video proof on three TVs simultaneously.

Samsung's reply:

> *"Recently, we have received a lot of reports of the same or similar security vulnerabilities for the ports you reported. And we do not reward for vulnerabilities already received."*
>
> *"Within the same network, the specification is that connections occur without authentication."*
>
> *"Unfortunately, we cannot pay reward for your report."*

That's it. No fix. No CVE. No acknowledgment that millions of customers are affected. They already knew — other researchers reported it before — and they still chose not to fix it. They called it a **specification**.

Meanwhile, Samsung sells The Frame TV with **"Protected by Knox"** displayed on boot. Knox is Samsung's enterprise security platform. The same TV that lets anyone on your WiFi blast content to your screen tells you it's protected by Knox when you turn it on.

---

## What an attacker can do

Everything below requires only being on the same WiFi network. No credentials, no hacking, no special tools beyond this repo.

- **Inject any image full-screen** onto the TV with no warning to the owner
- **Launch or close any app** — YouTube, browser, anything installed
- **Blast volume to maximum** at any time, including while someone is sleeping
- **Read the device serial number, WiFi MAC, Bluetooth MAC, and router info** with a single HTTP request
- **Send a pairing popup with any name** — "Samsung Support", "Samsung Security", anything — and the TV displays it verbatim with no verification
- **Monitor when people enter and leave the room** using the TV's own motion sensor events, passively, with no interaction

The Frame TV's Art Mode broadcasts a `go_to_standby` event over the network when the motion sensor detects the room is empty. It broadcasts when someone enters. Any device on the same WiFi receives this in real time. Zero auth. Zero indication to the owner.

---

## Requirements

```bash
pip install pillow websockets
```

Python 3.8+. Windows, Linux, macOS.

---

## GUI

```bash
python gui.py
```

1. Hit **Start** — scans the network every 15 seconds, found TVs appear in the list
2. Load an image or use the built-in alert
3. Hit **Inject All Found TVs**

Right-click any TV in the list to inject just that one or send a named popup.

---

## CLI

```bash
# Find Samsung TVs on the network
python takeover.py scan

# Inject image to all TVs found
python takeover.py inject --all

# Inject a custom image to one TV
python takeover.py inject --ip 192.168.1.100 --image yourimage.jpg

# Send a named popup to one TV (displays on screen verbatim)
python takeover.py popup --ip 192.168.1.100 --name "Samsung Support"

# Passive presence detection — prints when owner enters or leaves the room
python takeover.py watch --ip 192.168.1.100

# Continuous scan + auto inject loop
python takeover.py auto
```

---

## Confirmed devices

Tested live on latest firmware, no updates available at time of testing:

| Device | Image Injection | Named Popup | Presence Detection |
|--------|----------------|-------------|-------------------|
| QN43LS03FAFXZA (Frame 43") | ✅ | ✅ | ✅ |
| QN50LS03FAFXZA (Frame 50") | ✅ | ✅ | ✅ |
| QN55LS03FAFXZA (Frame 55") | ✅ | ✅ | ✅ |
| QN65S90CAFXZA (S90C 65") | ❌ blocked | ✅ | — |

---

## The Knox contradiction

The Frame TV displays "Protected by Knox" on every boot. It returns `TokenAuthSupport: true` from its own REST API at port 8001.

The Samsung S90C, a different Samsung TV, correctly enforces Knox token authentication — WebSocket connections without a valid token are rejected.

The Frame TV does not enforce it on anything. Not DLNA. Not the REST API. Not 10 of 11 internal WebSocket channels. The only thing blocked is `samsung.remote.control` — the official Samsung remote app channel. Everything else is open.

Samsung is selling two TVs under the same Knox marketing with completely different security implementations, and has confirmed they have no plans to change the Frame TV.

---

## Affected ports

| Port | Service | Auth |
|------|---------|------|
| 9197 | DLNA AVTransport + RenderingControl | None |
| 8001 | Samsung REST + WebSocket API | None |
| 8002 | WebSocket TLS | None |
| 8008 | DIAL / Google Cast | None |
| 8009 | Google Cast TLS | None |

---

## Disclaimer

Only use this on networks and devices you own or have explicit written permission to test. The zero-auth behavior is Samsung's documented specification — this tool just uses it.

---

*Reported by Colin McDonough — [github.com/ColinM-sys](https://github.com/ColinM-sys)*
