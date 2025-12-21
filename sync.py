#!/usr/bin/env python3
"""
Music sync tool: fetch likes from streaming services (SoundCloud, etc.)
and download via Bandcamp (purchase) or Apple Music (fallback).
"""

import argparse
import json
import os
import subprocess
import sys
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import quote_plus

import browser_cookie3
import requests
from dotenv import load_dotenv


class State:
    """Persistent state to track last sync time."""
    
    def __init__(self, path: Path):
        self.path = path
        self.data = {"last_check": None}
        self.load()
    
    def load(self):
        if self.path.exists():
            with open(self.path) as f:
                self.data = json.load(f)
    
    def save(self):
        with open(self.path, 'w') as f:
            json.dump(self.data, f, indent=2)
    
    @property
    def last_check(self) -> Optional[datetime]:
        if self.data["last_check"]:
            return datetime.fromisoformat(self.data["last_check"])
        return None
    
    @last_check.setter
    def last_check(self, dt: datetime):
        self.data["last_check"] = dt.isoformat()


class Track:
    """Represents a track from any source."""
    
    def __init__(self, title: str, artist: str, url: str, created_at: datetime):
        self.title = title
        self.artist = artist
        self.url = url
        self.created_at = created_at
    
    def __repr__(self):
        return f"Track({self.artist} - {self.title})"
    
    def search_query(self) -> str:
        return f"{self.artist} {self.title}"


class SoundCloudSource:
    """Fetch likes from SoundCloud via API v2."""
    
    def __init__(self, username: str, client_id: Optional[str] = None, oauth_token: Optional[str] = None):
        self.username = username
        self.client_id = client_id or self._get_client_id()
        self.oauth_token = oauth_token or self._get_oauth_token()
        self.base_url = "https://api-v2.soundcloud.com"
    
    def _get_oauth_token(self) -> Optional[str]:
        """Extract oauth_token from browser cookies."""
        try:
            # Try Chrome first, then other browsers
            for cookie_fn in [browser_cookie3.chrome, browser_cookie3.firefox, browser_cookie3.safari]:
                try:
                    cookies = cookie_fn(domain_name='soundcloud.com')
                    for cookie in cookies:
                        if cookie.name == 'oauth_token':
                            token = cookie.value
                            print(f"Found OAuth token from browser cookies: {token[:20]}...")
                            return token
                except:
                    continue
        except Exception as e:
            print(f"Could not extract OAuth token from browser: {e}")
        return None
    
    def _get_client_id(self) -> str:
        """Extract client_id from SoundCloud's JavaScript."""
        import re
        
        # Fetch the main page
        resp = requests.get("https://soundcloud.com")
        resp.raise_for_status()
        
        # Find script URLs
        script_urls = re.findall(r'<script[^>]+src="([^"]+)"', resp.text)
        
        # Look for client_id in script files
        for script_url in script_urls:
            if not script_url.startswith('http'):
                script_url = f"https://soundcloud.com{script_url}"
            
            try:
                script_resp = requests.get(script_url, timeout=5)
                # Try multiple patterns
                patterns = [
                    r'client_id:"([a-zA-Z0-9]{32})"',
                    r'client_id":"([a-zA-Z0-9]{32})"',
                    r'client_id=([a-zA-Z0-9]{32})',
                ]
                for pattern in patterns:
                    match = re.search(pattern, script_resp.text)
                    if match:
                        client_id = match.group(1)
                        print(f"Found client_id: {client_id}")
                        return client_id
            except:
                continue
        
        raise Exception("Could not extract client_id from SoundCloud")
    
    def resolve_user(self) -> int:
        """Resolve username to user ID."""
        url = f"{self.base_url}/resolve"
        params = {
            "url": f"https://soundcloud.com/{self.username}",
            "client_id": self.client_id
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if self.oauth_token:
            headers["Authorization"] = f"OAuth {self.oauth_token}"
            
        resp = requests.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()["id"]
    
    def fetch_likes(self, limit: int = 200) -> List[Track]:
        """Fetch recent likes."""
        user_id = self.resolve_user()
        url = f"{self.base_url}/users/{user_id}/likes"
        params = {
            "limit": limit,
            "client_id": self.client_id
        }
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if self.oauth_token:
            headers["Authorization"] = f"OAuth {self.oauth_token}"
            
        resp = requests.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        
        tracks = []
        for item in data.get("collection", []):
            track_data = item.get("track", {})
            if not track_data:
                continue
            
            title = track_data.get("title", "")
            artist = track_data.get("user", {}).get("username", "")
            url = track_data.get("permalink_url", "")
            created = track_data.get("created_at", "")
            
            # Parse timestamp (SoundCloud uses various formats)
            try:
                dt = datetime.fromisoformat(created.replace("+0000", "+00:00"))
            except:
                try:
                    dt = datetime.strptime(created, "%Y/%m/%d %H:%M:%S %z")
                except:
                    dt = datetime.now(timezone.utc)
            
            tracks.append(Track(title, artist, url, dt))
        
        return tracks


class BandcampSearcher:
    """Search for tracks on Bandcamp via API."""
    
    def search(self, query: str) -> Optional[str]:
        """Search Bandcamp and return first track URL if found."""
        api_url = "https://bandcamp.com/api/fuzzysearch/1/autocomplete"
        
        try:
            params = {"q": query}
            resp = requests.get(api_url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            # Look for track results
            results = data.get("results", [])
            for item in results:
                if item.get("type") == "t":  # 't' = track
                    return item.get("url")
        except Exception as e:
            print(f"  Bandcamp search error: {e}")
        
        return None


class AppleMusicDownloader:
    """Interface to apple-music-downloader tool."""
    
    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self.media_user_token = self._get_media_user_token()
    
    def _get_media_user_token(self) -> Optional[str]:
        """Extract media-user-token from browser cookies."""
        try:
            # Try to get Apple Music token from browser
            for cookie_fn in [browser_cookie3.chrome, browser_cookie3.firefox, browser_cookie3.safari]:
                try:
                    cookies = cookie_fn(domain_name='apple.com')
                    for cookie in cookies:
                        if cookie.name == 'media-user-token':
                            print(f"Found Apple Music media-user-token from browser cookies")
                            return cookie.value
                except:
                    continue
        except Exception as e:
            print(f"Could not extract media-user-token from browser: {e}")
        return None
    
    def search_and_download(self, query: str) -> bool:
        """Search Apple Music and download via go run main.go."""
        if not self.media_user_token:
            print(f"  No Apple Music token found - skipping")
            return False
        
        try:
            # Add filter to exclude [mixed] results
            filtered_query = f"{query} -mixed"
            
            # Use the apple-music-downloader's search + download
            cmd = [
                "go", "run", "main.go",
                "--search", "song",
                filtered_query
            ]
            result = subprocess.run(
                cmd,
                cwd=self.repo_path,
                capture_output=False,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            print(f"  Apple Music download error: {e}")
            return False


def main():
    # Load environment variables
    load_dotenv()
    
    parser = argparse.ArgumentParser(
        description="Sync liked tracks from streaming services to Bandcamp/Apple Music"
    )
    parser.add_argument("--source", default="soundcloud", choices=["soundcloud"],
                        help="Source service to fetch likes from")
    parser.add_argument("--soundcloud-username", 
                        default=os.getenv("SOUNDCLOUD_USERNAME"),
                        help="SoundCloud username")
    parser.add_argument("--soundcloud-client-id", 
                        default=os.getenv("SOUNDCLOUD_CLIENT_ID"),
                        help="SoundCloud client_id")
    parser.add_argument("--state", default=".music-sync-state.json",
                        help="Path to state file")
    parser.add_argument("--limit", type=int, 
                        default=int(os.getenv("LIMIT", "200")),
                        help="Number of recent likes to fetch")
    parser.add_argument("--initial-download", type=int, 
                        default=int(os.getenv("INITIAL_DOWNLOAD", "0")),
                        help="On first run, process N most recent likes")
    parser.add_argument("--open-bandcamp", action="store_true",
                        help="Open Bandcamp pages in browser for manual purchase")
    parser.add_argument("--apple-music-repo", 
                        default=os.getenv("APPLE_MUSIC_REPO", "../apple-music-downloader"),
                        help="Path to apple-music-downloader repo")
    parser.add_argument("--skip-apple-music", action="store_true",
                        help="Skip Apple Music fallback (Bandcamp only)")
    
    args = parser.parse_args()
    
    # Initialize state
    state = State(Path(args.state))
    
    # Fetch likes from source
    if args.source == "soundcloud":
        if not args.soundcloud_username:
            print("Error: --soundcloud-username required")
            sys.exit(1)
        
        print(f"Fetching SoundCloud likes for @{args.soundcloud_username}...")
        source = SoundCloudSource(
            args.soundcloud_username, 
            args.soundcloud_client_id,
            os.getenv("SOUNDCLOUD_OAUTH_TOKEN")
        )
        tracks = source.fetch_likes(args.limit)
    else:
        print(f"Unknown source: {args.source}")
        sys.exit(1)
    
    # Sort newest first
    tracks.sort(key=lambda t: t.created_at, reverse=True)
    
    # Filter by last check time
    to_process = []
    if state.last_check is None:
        if args.initial_download > 0:
            to_process = tracks[:args.initial_download]
            print(f"First run: processing {len(to_process)} recent tracks")
        else:
            print("First run with no initial-download; updating state and exiting")
            state.last_check = datetime.now(timezone.utc)
            state.save()
            return
    else:
        for track in tracks:
            if track.created_at > state.last_check:
                to_process.append(track)
        print(f"Found {len(to_process)} new likes since last run")
    
    if not to_process:
        print("No new tracks to process")
        state.last_check = datetime.now(timezone.utc)
        state.save()
        return
    
    # Initialize downloaders
    bandcamp = BandcampSearcher()
    apple_music = None
    if not args.skip_apple_music:
        am_path = Path(args.apple_music_repo).expanduser().resolve()
        if am_path.exists():
            apple_music = AppleMusicDownloader(am_path)
        else:
            print(f"Warning: Apple Music repo not found at {am_path}")
    
    # Process each track
    for i, track in enumerate(to_process, 1):
        print(f"\n[{i}/{len(to_process)}] {track}")
        
        # Try Bandcamp first
        bc_url = bandcamp.search(track.search_query())
        if bc_url:
            print(f"  ✓ Bandcamp: {bc_url}")
            if args.open_bandcamp:
                webbrowser.open(bc_url)
                time.sleep(1)  # Rate limit browser opens
            continue
        
        print("  ✗ Not found on Bandcamp")
        
        # Fallback to Apple Music
        if apple_music and not args.skip_apple_music:
            print("  → Trying Apple Music...")
            if apple_music.search_and_download(track.search_query()):
                print("  ✓ Downloaded from Apple Music")
            else:
                print("  ✗ Apple Music download failed")
        else:
            print("  (Skipping Apple Music fallback)")
    
    # Update state
    state.last_check = datetime.now(timezone.utc)
    state.save()
    print(f"\n✓ Sync complete. State saved to {args.state}")


if __name__ == "__main__":
    main()
