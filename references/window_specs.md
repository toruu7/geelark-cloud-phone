# GeeLark Phone Window Specifications & Normalized Coordinates

## Window Anatomy

When GeeLark launches a Cloud Phone profile, it opens a dedicated window named:
- Pattern: `#<index> GeeLarkPhone|<Profile Name>` or `<Profile Name> - GeeLark Phone`
- Window Class: `Chrome_WidgetWin_1`

### Dimensions & Offsets
Typical window size on Windows 10/11:
- Total Window Width: ~`394px`
- Total Window Height: ~`710px`
- Title Bar (Top): `30px` (y: `0` to `30`)
- Right-side Toolbar: `44px` (x: `350` to `394`)
- **Active Phone Touch Display**:
  - `x`: `0` to `350px`
  - `y`: `30` to `706px`

---

## Normalized Touch Grid (`0.0` to `1.0`)

Using `--norm` with `geelark.py tap <x> <y> --norm` automatically maps your normalized coordinates to the active phone display area:

```
(0.0, 0.0) --------------------- (1.0, 0.0)
     |                                |
     |      Android Status Bar        |  y ≈ 0.00 - 0.04
     |                                |
     |      App Header / Search       |  y ≈ 0.05 - 0.12
     |                                |
     |                                |
     |        Content / Feed          |  y ≈ 0.12 - 0.88
     |                                |
     |                                |
     |       Bottom Navigation        |  y ≈ 0.88 - 0.94
     |                                |
     |    Android System Bar (Back/Home/Recent)  y ≈ 0.95 - 1.00
(0.0, 1.0) --------------------- (1.0, 1.0)
```

### Key UI Touch Targets

| Element | Normalized X | Normalized Y | Command Equivalent |
| :--- | :--- | :--- | :--- |
| **Android Back Button** | `0.18` | `0.97` | `python scripts/geelark.py key back` |
| **Android Home Button** | `0.50` | `0.97` | `python scripts/geelark.py key home` |
| **Android Recent Apps** | `0.82` | `0.97` | `python scripts/geelark.py key recent` |
| **App Header Search Icon** | `0.83` | `0.08` | `python scripts/geelark.py tap 0.83 0.08 --norm` |
| **Virtual Keyboard Enter/Search**| `0.80` | `0.90` | `python scripts/geelark.py key enter` |
| **YouTube Ad "Skip" Button** | `0.75` | `0.78` | `python scripts/geelark.py tap 0.75 0.78 --norm` |
| **Close Overlay / Modal (X)**| `0.88` | `0.07` | `python scripts/geelark.py tap 0.88 0.07 --norm` |

---

## Multi-Monitor Handling
GeeLark windows can reside on secondary screens with negative coordinates (e.g. `x = -1157, y = -379`).
`geelark.py` queries `SM_XVIRTUALSCREEN` and `SM_YVIRTUALSCREEN` so you never have to manually calculate monitor offsets.
