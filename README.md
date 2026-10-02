# Pokémon Binder Tracker

A single-file web app to track your physical Pokémon TCG collection across multiple binders.

## Features
- Binder grid with official card art, prices, and quantities (via the free [PokémonTCG API](https://pokemontcg.io/))
- **📷 Scan card** — OCR a card photo with your phone camera to add it ([Tesseract.js](https://tesseract.js.org/))
- **4 binders** with page/slot tracking — search tells you exactly which binder a card is in
- Set completion tracker and collection-based recommendations
- Export / Import JSON backups
- All data stored locally in your browser

## Run it
Open `index.html` in any browser, or visit the GitHub Pages URL once deployed.

> The camera scan needs an `https://` URL (GitHub Pages) or opening the local file directly — iOS Safari blocks the camera on plain `http://`.
