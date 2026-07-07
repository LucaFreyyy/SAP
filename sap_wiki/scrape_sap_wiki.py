import requests
import time
import json
import os
import random
import re

BASE_URL = "https://superautopets.wiki.gg/api.php"
OUTPUT_DIR = "superautopets_wiki_dump"
PETS_DIR = os.path.join(OUTPUT_DIR, "pets")
FOODS_DIR = os.path.join(OUTPUT_DIR, "foods")
TOKENS_DIR = os.path.join(OUTPUT_DIR, "tokens")
ICONS_BASE = os.path.join(OUTPUT_DIR, "icons")
ICONS_PETS = os.path.join(ICONS_BASE, "pets")
ICONS_FOODS = os.path.join(ICONS_BASE, "foods")
ICONS_TOKENS = os.path.join(ICONS_BASE, "tokens")

for folder in [PETS_DIR, FOODS_DIR, TOKENS_DIR, ICONS_PETS, ICONS_FOODS, ICONS_TOKENS]:
    os.makedirs(folder, exist_ok=True)

# ----- Your exact lists -----
pets = {
    "Tier 1": ["Duck", "Beaver", "Pigeon", "Otter", "Pig", "Ant", "Mosquito", "Fish", "Cricket", "Horse"],
    "Tier 2": ["Snail", "Crab", "Swan", "Rat", "Hedgehog", "Peacock", "Flamingo", "Worm", "Kangaroo", "Spider"],
    "Tier 3": ["Dodo", "Badger", "Dolphin", "Giraffe", "Elephant", "Camel", "Rabbit", "Ox", "Dog", "Sheep"],
    "Tier 4": ["Skunk", "Hippo", "Bison", "Blowfish", "Turtle", "Squirrel", "Penguin", "Deer", "Whale", "Parrot"],
    "Tier 5": ["Scorpion", "Crocodile", "Rhino", "Monkey", "Armadillo", "Cow", "Seal", "Rooster", "Shark", "Turkey"],
    "Tier 6": ["Leopard", "Boar", "Tiger", "Wolverine", "Gorilla", "Dragon", "Mammoth", "Cat", "Snake", "Fly"]
}

foods = {
    "Tier 1": ["Apple", "Honey"],
    "Tier 2": ["Sleeping Pill", "Meat Bone", "Cupcake"],
    "Tier 3": ["Garlic", "Salad Bowl", "Cake"],
    "Tier 4": ["Bread", "Canned Food", "Pear"],
    "Tier 5": ["Chili", "Chocolate", "Sushi"],
    "Tier 6": ["Steak", "Melon", "Mushroom", "Pizza"]
}

tokens = [
    "Bread Crumbs", "Zombie Cricket", "Dirty Rat", "Better Apple", "Best Apple",
    "Ram", "Bus", "Peanut", "Milk", "Better Milk", "Best Milk", "Coconut", "Zombie Fly"
]

session = requests.Session()
session.headers.update({
    "User-Agent": "SAPWikiScraper/1.0 (contact: your-email@example.com) - polite educational script"
})

def fetch_with_retry(title, max_retries=5):
    backoff = 2
    for attempt in range(max_retries):
        try:
            params = {
                "action": "query",
                "format": "json",
                "titles": title,
                "prop": "extracts|revisions",
                "explaintext": 1,
                "rvprop": "content",
                "redirects": 1,
            }
            resp = session.get(BASE_URL, params=params, timeout=15)
            if resp.status_code == 429:
                wait = backoff * (2 ** attempt) + random.uniform(0, 1)
                print(f"  ⚠️  429 for '{title}', waiting {wait:.1f}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})
            for page_id, page_data in pages.items():
                if page_id == "-1":
                    return None, f"Page not found: {title}", None
                actual = page_data.get("title", title)
                extract = page_data.get("extract", "")
                revisions = page_data.get("revisions", [])
                wikitext = revisions[0].get("*", "") if revisions else ""
                content = extract if extract.strip() else wikitext
                if not content.strip():
                    content = "[No content retrieved – page may be empty or require special handling]"
                return actual, content, wikitext
            return None, "No pages in response", None
        except requests.exceptions.RequestException as e:
            print(f"  ⚠️ Request error for '{title}': {e}")
            if attempt < max_retries - 1:
                wait = backoff * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(wait)
            else:
                return None, f"Request error after {max_retries} attempts: {e}", None
    return None, f"Max retries exceeded for {title}", None

def extract_image_filename(wikitext):
    """Look for |image=... in any {{...InfoBox}} block."""
    # Try to find any infobox that might contain image
    match = re.search(r'\{\{(?:Animal|Food|Item|Token)\s*InfoBox\s*\n(.*?)\}\}', wikitext, re.DOTALL)
    if not match:
        return None
    infobox = match.group(1)
    lines = infobox.splitlines()
    for line in lines:
        line = line.strip()
        if line.startswith('|image='):
            # Extract filename, may include spaces
            filename = line[7:].strip()
            # Remove any extra stuff like {{!}} or [[File:...]]
            if '[[' in filename:
                # e.g., [[File:Chocolate.png|...]] -> extract inner
                match2 = re.search(r'\[\[File:([^|\]]+)', filename)
                if match2:
                    filename = match2.group(1)
            return filename
    return None

def get_image_url(filename):
    """Given a filename (e.g., 'Chocolate.png'), return the full URL to the image."""
    params = {
        "action": "query",
        "format": "json",
        "titles": f"File:{filename}",
        "prop": "imageinfo",
        "iiprop": "url"
    }
    try:
        resp = session.get(BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        pages = data.get("query", {}).get("pages", {})
        for page_id, page_data in pages.items():
            if page_id == "-1":
                return None
            imageinfo = page_data.get("imageinfo", [])
            if imageinfo:
                return imageinfo[0].get("url")
        return None
    except Exception as e:
        print(f"    ⚠️ Could not get image URL for {filename}: {e}")
        return None

def download_image(url, save_path):
    """Download an image from url and save to save_path."""
    if not url:
        return False
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(resp.content)
        return True
    except Exception as e:
        print(f"    ⚠️ Could not download image from {url}: {e}")
        return False

def fetch_and_save(category, name, tier, base_dir, icon_dir):
    print(f"Fetching {category} – {tier}: {name} ...")
    actual_title, content, wikitext = fetch_with_retry(name)
    if actual_title is None:
        actual_title = name
        content = f"ERROR: {content}"
        wikitext = ""

    # Save the .txt file
    safe_name = name.replace(" ", "_")
    txt_path = os.path.join(base_dir, f"{safe_name}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"Title: {actual_title}\n")
        f.write(f"Category: {category}\n")
        f.write(f"Tier: {tier}\n")
        f.write("=" * 60 + "\n\n")
        f.write("CONTENT (plain text or raw wikitext):\n")
        f.write(content)
        if wikitext and wikitext != content:
            f.write("\n\n--- RAW WIKITEXT (for reference) ---\n")
            f.write(wikitext)

    # --- Image download ---
    # Try to extract image filename from wikitext
    image_filename = None
    if wikitext:
        image_filename = extract_image_filename(wikitext)
    # Fallback: assume <name>.png
    if not image_filename:
        image_filename = f"{name.replace(' ', '_')}.png"
    # Get URL and download
    image_url = get_image_url(image_filename)
    if image_url:
        # Determine file extension from URL or filename
        ext = image_filename.split('.')[-1] if '.' in image_filename else 'png'
        icon_path = os.path.join(icon_dir, f"{safe_name}.{ext}")
        # If the URL gives a different extension (e.g., .jpg), we might need to adjust.
        # But we'll use the filename from the infobox; if it has .png, we use that.
        # To be safe, we can use the extension from the URL path, but we'll keep the original filename.
        # Override with the exact filename from the URL to preserve extension.
        # Actually, we want to save with the same filename as on the wiki.
        url_filename = os.path.basename(image_url).split('?')[0]
        if url_filename:
            # Use the actual filename from the URL
            icon_path = os.path.join(icon_dir, url_filename)
        success = download_image(image_url, icon_path)
        if success:
            print(f"    ✓ Downloaded icon: {url_filename}")
        else:
            print(f"    ⚠️ Failed to download icon for {name}")
    else:
        print(f"    ⚠️ No image URL found for {image_filename}")

def process_category(category, items, base_dir, icon_dir):
    all_data = []
    if isinstance(items, dict):
        for tier, names in items.items():
            for name in names:
                fetch_and_save(category, name, tier, base_dir, icon_dir)
                # Delay after each item
                delay = 1.5 + random.uniform(0, 1.0)
                time.sleep(delay)
    else:  # list for tokens
        for name in items:
            fetch_and_save(category, name, "Token", base_dir, icon_dir)
            delay = 1.5 + random.uniform(0, 1.0)
            time.sleep(delay)

def main():
    print("Starting pets ...")
    process_category("Pet", pets, PETS_DIR, ICONS_PETS)
    print("Starting foods ...")
    process_category("Food", foods, FOODS_DIR, ICONS_FOODS)
    print("Starting tokens ...")
    process_category("Token", tokens, TOKENS_DIR, ICONS_TOKENS)
    print("\n✅ All done! Files and icons saved in 'superautopets_wiki_dump/'.")

if __name__ == "__main__":
    main()