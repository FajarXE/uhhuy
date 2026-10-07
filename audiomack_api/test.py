import sys
import json
import re
from datetime import datetime
from playwright.sync_api import sync_playwright


def format_duration(seconds):
    if not seconds or not isinstance(seconds, (int, float)):
        return "3:30"
    mins = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{mins}:{secs:02d}"


def extract_track_info(url, output_json="track_data.json"):
    print(f"[*] Extracting complete Audiomack metadata for: {url}")

    track_info = {
        "title": "",
        "artist": "",
        "featuringArtists": "",
        "duration": "3:30",
        "genre": "",
        "producer": "",
        "releaseDate": "",
        "year": "",
        "trackNumber": 1,
        "streamingUrl": "",
        "trackImageUrl": ""
    }

    track_obj = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )

        page = context.new_page()

        # Network interceptor — must be attached BEFORE navigation
        def handle_response(response):
            try:
                res_url = response.url
                audio_exts = [".mp3", ".m4a", ".m3u8", "/streaming/", "/hq/"]
                if any(ext in res_url.lower() for ext in audio_exts):
                    if not track_info["streamingUrl"] and "audiomack" in res_url:
                        track_info["streamingUrl"] = res_url
                        print("[*] Intercepted streamingUrl successfully!")
            except Exception:
                pass

        page.on("response", handle_response)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # PHASE 1 — Full React hydration wait (3 seconds)
            page.wait_for_timeout(3000)

            # PHASE 2 — Full React-compatible mouse event chain via JS
            try:
                page.evaluate("""() => {
                    const selectors = [
                        'button[data-amlabs-play-button="true"]',
                        'button[aria-label="Play"]',
                        'button[aria-label*="Play"]',
                        '[class*="PlayButton"]',
                        '[class*="play-button"]',
                        'button.button--play',
                        '.play-button'
                    ];
                    const events = [
                        'pointerover','pointerenter','mouseover','mouseenter',
                        'pointermove','mousemove','pointerdown','mousedown',
                        'pointerup','mouseup','click'
                    ];
                    for (const sel of selectors) {
                        const btns = document.querySelectorAll(sel);
                        for (const btn of btns) {
                            const rect = btn.getBoundingClientRect();
                            if (rect.width > 0 && rect.height > 0) {
                                events.forEach(evName => {
                                    btn.dispatchEvent(new MouseEvent(evName, {
                                        bubbles: true, cancelable: true, view: window
                                    }));
                                });
                                return sel;
                            }
                        }
                    }
                    return 'not_found';
                }""")
            except Exception:
                pass

            # PHASE 3 — Playwright force-click as backup
            try:
                play_btn = page.query_selector(
                    'button[data-amlabs-play-button="true"], '
                    'button[aria-label*="Play"], '
                    '[class*="PlayButton"], .play-button'
                )
                if play_btn:
                    play_btn.click(force=True)
            except Exception:
                pass

            # PHASE 4 — Spacebar fallback
            try:
                page.keyboard.press("Space")
            except Exception:
                pass

            # PHASE 5 — Reactive wait up to 6s, exits the moment URL is captured
            for _ in range(60):
                if track_info["streamingUrl"]:
                    break
                page.wait_for_timeout(100)

            if not track_info["streamingUrl"]:
                print("[!] streamingUrl not captured via network interception.")

            # PHASE 6 — Extract metadata from __NEXT_DATA__
            track_obj = {}
            next_data_elem = page.query_selector("script#__NEXT_DATA__")
            if next_data_elem:
                try:
                    raw_json = next_data_elem.inner_text()
                    data = json.loads(raw_json)
                    page_props = data.get("props", {}).get("pageProps", {})

                    if "music" in page_props and isinstance(page_props["music"], dict):
                        track_obj = page_props["music"]
                    else:
                        redux_music = (
                            page_props
                            .get("initialReduxState", {})
                            .get("music", {})
                        )
                        if isinstance(redux_music, dict):
                            for k, v in redux_music.items():
                                if isinstance(v, dict) and "title" in v:
                                    track_obj = v
                                    break
                except Exception:
                    pass

            # PHASE 7 — DOM extraction for genre/producer/release date
            dom_genre = ""
            dom_producer = ""
            dom_release_date_str = ""
            try:
                rows = page.query_selector_all(
                    "ul.SinglePageMusicCardInfo li.SinglePageMusicCardInfo-row"
                )
                for row in rows:
                    t_elem = row.query_selector(".SinglePageMusicCardInfo-title")
                    v_elem = row.query_selector(".SinglePageMusicCardInfo-value")
                    if t_elem and v_elem:
                        row_title = t_elem.inner_text().strip().lower()
                        row_val = v_elem.inner_text().strip()
                        if "producer" in row_title:
                            dom_producer = row_val
                        elif "genre" in row_title:
                            dom_genre = row_val
                        elif "release date" in row_title:
                            dom_release_date_str = row_val.replace("Ⓡ", "").strip()
            except Exception:
                pass

            # PHASE 8 — Map core fields
            og_title = page.get_attribute('meta[property="og:title"]', "content") or ""
            og_image = page.get_attribute('meta[property="og:image"]', "content") or ""

            track_info["title"] = track_obj.get("title", "")
            track_info["artist"] = track_obj.get("artist", "")

            feat = track_obj.get("featuring", "") or track_obj.get("feat", "")
            if not feat and " & " in track_info["artist"]:
                parts = track_info["artist"].split("&")
                track_info["artist"] = parts[0].strip()
                feat = "&".join(parts[1:]).strip()
            track_info["featuringArtists"] = feat

            track_info["genre"] = track_obj.get("genre", "") or dom_genre
            track_info["producer"] = (
                track_obj.get("producer", "")
                or track_obj.get("credits", "")
                or dom_producer
            )
            track_info["trackNumber"] = (
                track_obj.get("trackNumber")
                or track_obj.get("track_number")
                or 1
            )
            track_info["trackImageUrl"] = (
                track_obj.get("image", "")
                or track_obj.get("cover", "")
                or og_image
            )

            # Use streaming_url from JSON if network interception failed
            if not track_info["streamingUrl"] and track_obj.get("streaming_url"):
                track_info["streamingUrl"] = track_obj["streaming_url"]

            # PHASE 9 — Title/artist fallbacks
            if not track_info["title"]:
                try:
                    h1_elem = page.query_selector("h1")
                    if h1_elem:
                        h1_text = h1_elem.inner_text().strip()
                        if h1_text and "Audiomack" not in h1_text:
                            track_info["title"] = h1_text
                except Exception:
                    pass

            if not track_info["title"] and og_title and "Audiomack - Music platform" not in og_title:
                parts = og_title.split(" by ")
                track_info["title"] = parts[0].strip()
                if len(parts) > 1 and not track_info["artist"]:
                    track_info["artist"] = parts[1].split(":")[0].strip()

            if not track_info["artist"] or not track_info["title"]:
                url_match = re.search(r"audiomack\.com/([^/]+)/song/([^/?]+)", url)
                if url_match:
                    if not track_info["artist"]:
                        track_info["artist"] = url_match.group(1).replace("-", " ").title()
                    if not track_info["title"]:
                        track_info["title"] = url_match.group(2).replace("-", " ").title()

            if "Listen on Audiomack" in track_info["artist"]:
                track_info["artist"] = track_info["artist"].split(":")[0].strip()

            # PHASE 10 — Release date and year
            if dom_release_date_str:
                try:
                    parsed_dt = datetime.strptime(dom_release_date_str, "%B %d, %Y")
                    track_info["releaseDate"] = parsed_dt.strftime("%Y-%m-%d")
                    track_info["year"] = str(parsed_dt.year)
                except Exception:
                    track_info["releaseDate"] = dom_release_date_str
                    track_info["year"] = (
                        dom_release_date_str[-4:]
                        if len(dom_release_date_str) >= 4
                        else str(datetime.now().year)
                    )
            else:
                released_val = (
                    track_obj.get("released")
                    or track_obj.get("uploaded")
                    or track_obj.get("released_at")
                )
                if released_val:
                    try:
                        if str(released_val).isdigit():
                            dt = datetime.fromtimestamp(int(released_val))
                        else:
                            dt = datetime.fromisoformat(str(released_val).replace("Z", "+00:00"))
                        track_info["releaseDate"] = dt.strftime("%Y-%m-%d")
                        track_info["year"] = str(dt.year)
                    except Exception:
                        track_info["releaseDate"] = str(released_val)[:10]
                        track_info["year"] = str(released_val)[:4]
                else:
                    now_year = str(datetime.now().year)
                    track_info["year"] = now_year
                    track_info["releaseDate"] = f"{now_year}-01-01"

            # PHASE 11 — Duration
            duration_sec = track_obj.get("duration")
            if duration_sec:
                track_info["duration"] = format_duration(duration_sec)

        except Exception as e:
            print(f"[!] Processing error: {e}")
        finally:
            browser.close()

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(track_info, f, indent=2, ensure_ascii=False)

    print(f"[✓] Track details successfully saved to: {output_json}")
    return track_info


if __name__ == "__main__":
    target_url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://audiomack.com/kolaboyofficial/song/onu"
    )
    extract_track_info(target_url)
