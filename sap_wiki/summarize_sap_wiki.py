import os
import re

# ----- Pet lists -----
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

ordered_pets = [name for tier_list in pets.values() for name in tier_list]
ordered_foods = [name for tier_list in foods.values() for name in tier_list]
ordered_tokens = tokens  # keep order as given

# ------------------------------------------------------------
# Helper: read saved .txt file
# ------------------------------------------------------------
def read_entry_file(category, name):
    safe_name = name.replace(" ", "_")
    filepath = os.path.join("superautopets_wiki_dump", category, f"{safe_name}.txt")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    for i, line in enumerate(lines):
        if line.startswith("CONTENT (plain text or raw wikitext):"):
            return "".join(lines[i+1:]).lstrip()
    return None

# ------------------------------------------------------------
# Generic infobox extractor (works for any {{...InfoBox}})
# ------------------------------------------------------------
def extract_infobox_data(wikitext, box_pattern):
    """Return a dict of key:value pairs from any infobox matching box_pattern."""
    match = re.search(box_pattern, wikitext, re.DOTALL)
    if not match:
        return {}
    infobox = match.group(1) if match.groups() else match.group(0)
    lines = infobox.splitlines()
    data = {}
    for line in lines:
        line = line.strip()
        if not line.startswith('|'):
            continue
        if '=' not in line:
            continue
        key, value = line[1:].split('=', 1)
        data[key.strip()] = value.strip()
    return data

# ------------------------------------------------------------
# Description extractor (same for all)
# ------------------------------------------------------------
def extract_description(wikitext, infobox_pattern):
    match = re.search(infobox_pattern, wikitext, re.DOTALL)
    if not match:
        return ""
    after = wikitext[match.end():].lstrip()
    lines = after.splitlines()
    desc_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("=="):
            break
        if stripped.startswith("{{Navbox") or stripped.startswith("[[Category:"):
            break
        desc_lines.append(line)
    return "\n".join(desc_lines).rstrip()

# ------------------------------------------------------------
# Processing functions per category
# ------------------------------------------------------------
def process_pets():
    summaries = []
    for name in ordered_pets:
        print(f"Processing pet – {name}...")
        wikitext = read_entry_file("pets", name)
        if wikitext is None:
            print(f"  ⚠️ File not found for {name}, skipping.")
            continue
        data = extract_infobox_data(wikitext, r'\{\{AnimalInfoBox\s*\n(.*?)\}\}')
        if not data:
            print(f"  ⚠️ Could not parse infobox for {name}, skipping.")
            continue
        attack_health = data.get('attack/health', '?')
        l1 = re.sub(r'\{\{IconSAP\|damage[^}]*\}\}', '', data.get('level_1', '')).strip()
        l2 = re.sub(r'\{\{IconSAP\|damage[^}]*\}\}', '', data.get('level_2', '')).strip()
        l3 = re.sub(r'\{\{IconSAP\|damage[^}]*\}\}', '', data.get('level_3', '')).strip()
        description = extract_description(wikitext, r'\{\{AnimalInfoBox.*?\}\}')
        lines = [f"{name}:{attack_health}"]
        if l1: lines.append(f"level_1={l1}")
        if l2: lines.append(f"level_2={l2}")
        if l3: lines.append(f"level_3={l3}")
        if description: lines.append(description)
        summaries.append("\n".join(lines))
    return summaries

def process_foods():
    summaries = []
    for name in ordered_foods:
        print(f"Processing food – {name}...")
        wikitext = read_entry_file("foods", name)
        if wikitext is None:
            print(f"  ⚠️ File not found for {name}, skipping.")
            continue
        data = extract_infobox_data(wikitext, r'\{\{FoodInfoBox\s*\n(.*?)\}\}')
        effect = data.get('effect', '').strip()
        description = extract_description(wikitext, r'\{\{FoodInfoBox.*?\}\}')
        lines = [f"{name}:{effect}"]
        if description: lines.append(description)
        summaries.append("\n".join(lines))
    return summaries

def process_tokens():
    summaries = []
    for name in ordered_tokens:
        print(f"Processing token – {name}...")
        wikitext = read_entry_file("tokens", name)
        if wikitext is None:
            print(f"  ⚠️ File not found for {name}, skipping.")
            continue
        # Try to find any infobox (common ones: ItemInfoBox, TokenInfoBox, etc.)
        data = extract_infobox_data(wikitext, r'\{\{(?:Item|Token)\s*InfoBox\s*\n(.*?)\}\}')
        effect = data.get('effect', '').strip() if data else ''
        # If no effect, maybe try "description" or "stats"?
        if not effect:
            # Fallback: if no infobox, treat the whole first paragraph as effect?
            # Instead, we'll just leave effect empty.
            pass
        description = extract_description(wikitext, r'\{\{(?:Item|Token)\s*InfoBox.*?\}\}')
        # If no infobox found, description extraction might fail – we can use the entire wikitext.
        if not description and not wikitext:
            description = wikitext.strip()
        lines = [f"{name}:{effect}"]
        if description: lines.append(description)
        summaries.append("\n".join(lines))
    return summaries

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------
def main():
    print("=== Pet summaries ===")
    pet_summaries = process_pets()
    with open("pets_summary.txt", "w", encoding="utf-8") as f:
        f.write("\n\n".join(pet_summaries))
    print(f"✅ pets_summary.txt written with {len(pet_summaries)} entries.\n")

    print("=== Food summaries ===")
    food_summaries = process_foods()
    with open("foods_summary.txt", "w", encoding="utf-8") as f:
        f.write("\n\n".join(food_summaries))
    print(f"✅ foods_summary.txt written with {len(food_summaries)} entries.\n")

    print("=== Token summaries ===")
    token_summaries = process_tokens()
    with open("tokens_summary.txt", "w", encoding="utf-8") as f:
        f.write("\n\n".join(token_summaries))
    print(f"✅ tokens_summary.txt written with {len(token_summaries)} entries.\n")

    print("🎉 All done!")

if __name__ == "__main__":
    main()