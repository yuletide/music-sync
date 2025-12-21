# Music Sync

Sync liked tracks from streaming services (SoundCloud, etc.) to Bandcamp (for purchase) or Apple Music (fallback download).

## Features

- Fetch recent likes from SoundCloud via API
- Search Bandcamp first and open pages for manual purchase
- Fallback to Apple Music download using [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader)
- Track state between runs (only process new likes)
- Modular design for adding more sources later

## Setup

```bash
# Install dependencies
poetry install

# Create .env file from example
cp .env.example .env

# Edit .env and add your SoundCloud credentials
# Get SoundCloud client_id (inspect network tab on soundcloud.com)
# Look for any API request and copy the client_id parameter
```

## Usage

**Important:** Make sure the apple-music-downloader wrapper is running before starting the sync:
```bash
cd ../apple-music-downloader/wrapper
git checkout yuletide/arm64buildall
rm -f rootfs/tmp/2fa.txt && docker run --rm --privileged -v "$(pwd)/rootfs/tmp:/app/rootfs/tmp" -p 10020:10020 -p 20020:20020 -e args="-L email:pass -F -H 0.0.0.0" wrapper
```

### First Run (process recent 10 likes)

```bash
# With .env configured:
poetry run python sync.py --open-bandcamp

# Or override with command-line args:
poetry run python sync.py \
  --soundcloud-username YOUR_USERNAME \
  --soundcloud-client-id YOUR_CLIENT_ID \
  --initial-download 10 \
  --open-bandcamp
```

### Subsequent Runs (only new likes)

```bash
# Simple - just use .env config:
poetry run python sync.py --open-bandcamp
```

### Options

- `--open-bandcamp` - Open Bandcamp pages in your browser for manual purchase
- `--skip-apple-music` - Skip Apple Music fallback (Bandcamp only mode)
- `--apple-music-repo PATH` - Path to apple-music-downloader repo (default: `../apple-music-downloader`)
- `--limit N` - Number of recent likes to fetch (default: 200)
- `--state FILE` - State file path (default: `.music-sync-state.json`)

## How It Works

1. Fetch your recent liked tracks from SoundCloud
2. Compare with last run timestamp (stored in `.music-sync-state.json`)
3. For each new like:
   - Search Bandcamp and open page if found (manual purchase)
   - If not on Bandcamp, fall back to Apple Music download
4. Update state file with current timestamp

## Adding More Sources

The tool is designed to support multiple sources. To add a new source:

1. Create a new class implementing the source API (like `SoundCloudSource`)
2. Return a list of `Track` objects
3. Add the source to `--source` choices in argparse

## Requirements

- Python 3.10+
- Poetry
- [apple-music-downloader](https://github.com/zhaarey/apple-music-downloader) (for Apple Music fallback)
- SoundCloud client_id (obtained from browser network inspector)

## License

MIT
