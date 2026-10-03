# Local card scanner (EasyOCR + OpenCV)

A separate Mac tool that does **heavy image processing** on your card photos —
far better than the browser scanner — and writes a JSON file you **Merge import**
into the web app.

## Why a separate tool
The browser uses Tesseract.js, which struggles with angled/low-light photos and
stylized card fonts. This tool runs on your Mac with real libraries:

- **OpenCV** — finds the card in the photo, straightens (deskews) it, boosts
  contrast, and crops the **name** band (top) and **number** band (bottom) so OCR
  reads the right regions.
- **EasyOCR** — a deep-learning OCR engine, much stronger than Tesseract on card
  fonts, with English / Indonesian / Japanese models.
- Resolves each read to the exact card on the Pokémon TCG API (name + number).

## One-time setup

```bash
cd /Users/muhammadrubyarrazy/.kiro/crew/workspace/pokemon-binder/scanner

# create an isolated environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# install the libraries (EasyOCR pulls in PyTorch — this is a big download, be patient)
python3 -m pip install -r requirements.txt
```

> First actual scan also downloads the EasyOCR models (~1 GB) once, then they're cached.

## Scan a folder of photos

```bash
# simplest — English cards, writes scanned.json in this folder
python3 scan.py ~/Desktop/my-cards

# file them all into a specific binder, and read Indonesian + Japanese too
python3 scan.py ~/Desktop/jp-binder -b "Japanese" --lang en id ja -o jp.json

# see the preprocessed crops it OCR'd (troubleshooting)
python3 scan.py ~/Desktop/my-cards --debug
```

Options:
- `-b "Binder name"` — file every scanned card into that binder (optional).
- `--lang en id ja` — EasyOCR languages. `en`=English, `id`=Indonesian, `ja`=Japanese.
- `-o out.json` — output filename (default `scanned.json`).
- `--api-key KEY` — optional Pokémon TCG API key for a higher rate limit
  (also read from `POKEMONTCG_API_KEY`). Not required.
- `--debug` — write the straightened/cropped images to `./debug/` so you can see
  what the OCR actually saw.

The tool prints each result (`✓ Charizard ex — Obsidian Flames #125`) and lists
any photos it couldn't match so you can add those few by hand.

## Load it into the web app
1. Open the Pokémon Binder web app.
2. **Import → pick your `scanned.json`.**
3. Choose **Merge import** so the scanned cards are **added** to your collection
   (plain Import *replaces* everything).

## Photo tips (same as any OCR)
Straight-on, well-lit, whole card in frame, bottom corner (the number) visible.
OpenCV handles moderate angles, but a clean photo always reads best.
