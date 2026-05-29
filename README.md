# Samsung Frame-ous

**Broadcast any image to every Samsung Frame TV on a network — zero credentials required.**

Samsung PSIRT confirmed in writing (May 2026) that the zero-authentication behavior on the ports below is **working as intended by specification**. This tool uses those documented behaviors.

> *"Within the same network, the specification is that connections occur without authentication"*
> — Samsung PSIRT response, 2026

---

## What it does

- Scans the local network and finds every Samsung Frame TV automatically
- Broadcasts any image you choose to all of them simultaneously — full screen, no popups, no warnings
- Sends a named WebSocket pairing popup with any text you choose (e.g. "Samsung Support")
- GUI with start/stop, live TV list, image preview, and one-click broadcast

## Affected ports (Samsung spec — no auth by design)

| Port | Service |
|------|---------|
| 9197 | DLNA AVTransport — full-screen image injection |
| 8001 | Samsung WebSocket API — named pairing popup |
| 8002 | Encrypted WebSocket TLS |
| 8008 | DIAL / Google Cast HTTP |
| 8009 | Google Cast TLS |

## Requirements

```
pip install pillow websockets
```

Python 3.8+ required. Works on Windows, Linux, macOS.

## Usage

### GUI (recommended)

```bash
python gui.py
```

1. Hit **Start** — scans the network, TVs appear in the list
2. Select your image (or use the built-in alert)
3. Hit **Inject All Found TVs** to broadcast

### CLI

```bash
# Find all Samsung TVs on LAN
python takeover.py scan

# Inject image to all TVs
python takeover.py inject --all --image alert.jpg

# Inject to one TV
python takeover.py inject --ip 192.168.1.100

# Send named popup ("Samsung Support" shown on TV screen)
python takeover.py popup --ip 192.168.1.100 --name "Samsung Support"

# Passive presence detection — go_to_standby = room empty
python takeover.py watch --ip 192.168.1.100

# Continuous scan + inject loop
python takeover.py auto
```

## Confirmed devices

| Device | DLNA Injection | Named Popup | Presence Detection |
|--------|---------------|-------------|-------------------|
| Samsung Frame TV QN43LS03FAFXZA | ✅ | ✅ | ✅ |
| Samsung Frame TV QN50LS03FAFXZA | ✅ | ✅ | ✅ |
| Samsung Frame TV QN55LS03FAFXZA | ✅ | ✅ | ✅ |
| Samsung S90C QN65S90CAFXZA | ❌ (blocked) | ✅ | — |

All on latest firmware. Samsung confirmed no fix planned.

## Background

Seven zero-authentication findings were reported to Samsung PSIRT (secbugbounty@samsung.com) in May 2026. Samsung responded that the behavior is working as intended by specification and declined to issue a fix or reward.

Findings included:
- Zero-auth DLNA content injection (full-screen image to any TV on the network)
- Zero-auth app launch/close via REST API
- Zero-auth volume and playback control
- Zero-auth device fingerprinting (serial, MAC, router BSSID)
- Zero-auth WebSocket channel enumeration (10 of 11 internal channels open)
- Art Mode data exfiltration and passive presence detection via motion sensor events
- Google Cast popup forcing with attacker-controlled device name

Samsung markets The Frame TV as *"Protected by Knox"* and returns `TokenAuthSupport: true` from its own REST API. The S90C correctly enforces Knox token authentication. The Frame TV does not.

## Disclaimer

This tool uses network APIs that Samsung has confirmed operate without authentication by design. Only use on networks and devices you own or have explicit permission to test.

## Researcher

Colin McDonough — [github.com/ColinM-sys](https://github.com/ColinM-sys)
