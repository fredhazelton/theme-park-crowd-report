#!/usr/bin/env python3

import os
import sys
import json
import subprocess
import time
import urllib.request
from urllib.error import URLError, HTTPError

# Configuration
API_KEY = os.environ.get("OPENAI_API_KEY", "")
OUTPUT_DIR = "/home/wilma/theme-park-crowd-report/docs/stream/images/attractions/"
STYLE_TEMPLATE = "Realistic illustration of {}, painted in a rich detailed digital art style, like concept art. Cinematic atmosphere, moody lighting. Square format. No text, no logos, no words, no letters, no signage."

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Attraction data (excluding already generated ones: MK13, MK01)
attractions = [
    ("EP197", "a cosmic roller coaster zooming through a swirling galaxy with purple and blue nebula lighting"),
    ("EP09", "hang gliders soaring over sweeping world landscapes, mountains and rivers below, golden hour light"),
    ("EP186", "a tiny rat's perspective racing through a giant Parisian kitchen with copper pots and flames"),
    ("HS113", "a Star Wars resistance base under attack, dramatic red and blue laser fire, massive Star Destroyer overhead"),
    ("HS111", "a whimsical cartoon-style runaway train crashing through colorful animated scenes"),
    ("MK23", "a gothic Victorian haunted mansion at night, eerie green glow, ghostly spirits floating, dark and atmospheric"),
    ("MK141", "a mine train coaster winding through sparkling gem-filled caverns, warm lantern glow"),
    ("AK11", "a mountain coaster climbing through snowy Himalayan peaks, mysterious yeti lurking in shadows"),
    ("HS22", "a haunted art deco hotel tower at night with lightning, ominous and dark, elevator shaft visible"),
    ("AK07", "an open-air safari jeep driving through golden African savanna at sunset with elephants and giraffes"),
    ("MK191", "futuristic TRON-style lightcycle motorcycle racing on a glowing blue grid track"),
    ("HS12", "an indoor high-speed launch coaster with neon rock concert lighting, guitar-shaped track"),
    ("AK86", "riding a flying creature (banshee) soaring over alien bioluminescent floating mountains"),
    ("HS103", "a colorful slinky-dog shaped coaster car racing through an oversized toy-filled backyard"),
    ("EP02", "a massive geodesic sphere structure at twilight, reflecting golden and purple sky"),
    ("AK85", "a gentle boat floating through a bioluminescent alien forest, glowing blue and purple plants"),
    ("EP07", "a peaceful greenhouse boat ride through lush green growing gardens with warm sunlight"),
    ("HS112", "the cockpit of the Millennium Falcon spaceship, hyperspace stars streaking past the windshield"),
    ("MK28", "a colorful whimsical boat ride through a world of international dolls and miniature landmarks, bright and cheerful"),
    ("MK05", "a flying pirate ship soaring over moonlit London with Big Ben and stars below"),
    ("MK44", "a futuristic elevated monorail-style ride gliding through a retro-futuristic city"),
    ("MK210", "a log flume boat floating through a magical Louisiana bayou with fireflies and jazz atmosphere"),
    ("AK18", "a jeep racing through a prehistoric jungle with dinosaurs lurking in dense vegetation"),
    ("EU07", "a wizard's wand battle in an ornate magical government ministry building, spell effects flying"),
    ("IA65", "a motorbike racing through a dark enchanted forest with magical creatures in the shadows"),
    ("MK142", "an underwater clamshell ride through a colorful coral reef kingdom"),
    ("EP155", "a Viking boat sailing through a frozen Nordic ice palace with aurora borealis"),
    ("EU11", "a suspended coaster soaring alongside dragons over a Viking island landscape"),
    ("HS15", "a 3D space flight simulator cockpit view, stars and planets rushing past"),
    ("MK06", "a whimsical honey pot ride floating through a storybook forest with butterflies"),
    ("EU06", "a mine cart racing through colorful jungle mines with barrels and platforms"),
    ("EU13", "a dark ride through a monster-filled gothic castle laboratory"),
    ("DL40", "pirates and treasure in a Caribbean cave, candlelit, with boats on dark water"),
    ("EU04", "a go-kart racing through a colorful mushroom kingdom racetrack, bright and vibrant"),
    ("EP04", "an underwater ride vehicle gliding past tropical fish and coral reefs in deep blue water"),
    ("EU14", "a horror-themed coaster through a dark werewolf forest with full moon"),
    ("UF63", "a roller coaster through a grand marble bank vault with golden treasure and a fire-breathing dragon"),
    ("DL05", "a wild west mine train coaster through red rock desert canyon at sunset"),
    ("HS104", "colorful alien flying saucer spinning ride in a retro space-themed area"),
    ("IA69", "a high-speed roller coaster with velociraptors running alongside the track through jungle"),
    ("EP13", "a whimsical ride through rooms of imagination with rainbow colors and a playful purple dragon"),
    ("AK123", "a vibrant ride through the city of Zootopia with diverse animal characters"),
    ("DL28", "a jungle river cruise boat passing ancient temple ruins overgrown with vines"),
    ("CA109", "race cars speeding through a desert canyon with towering red rock formations"),
    ("MK34", "a space ranger in a car shooting lasers at colorful alien targets, neon glow"),
    ("MK43", "a small circus-themed biplane coaster swooping over a carnival tent"),
    ("EP08", "astronauts in a spinning space capsule launching toward Mars, dramatic rocket flames"),
]

def generate_image(prompt, output_path):
    """Generate image using DALL-E 3 API"""
    
    # Prepare the API request
    data = {
        "model": "dall-e-3",
        "prompt": prompt,
        "size": "1024x1024",
        "quality": "standard",
        "n": 1
    }
    
    # Convert to JSON
    json_data = json.dumps(data)
    
    # Use curl to make the API request
    curl_cmd = [
        'curl', '-s', '-X', 'POST',
        'https://api.openai.com/v1/images/generations',
        '-H', 'Content-Type: application/json',
        '-H', f'Authorization: Bearer {API_KEY}',
        '-d', json_data
    ]
    
    try:
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"❌ curl failed: {result.stderr}")
            return False
            
        response = json.loads(result.stdout)
        
        if 'error' in response:
            print(f"❌ API error: {response['error']}")
            return False
            
        if 'data' not in response or not response['data']:
            print(f"❌ No image data in response")
            return False
            
        image_url = response['data'][0]['url']
        
        # Download the image
        urllib.request.urlretrieve(image_url, output_path)
        
        return True
        
    except subprocess.TimeoutExpired:
        print(f"❌ API request timeout")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ JSON decode error: {e}")
        return False
    except (URLError, HTTPError) as e:
        print(f"❌ Download error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def main():
    successful = 0
    failed = 0
    
    print("🚀 Starting AI illustration generation for theme park attractions...")
    print(f"📁 Output directory: {OUTPUT_DIR}")
    print(f"🎨 Total attractions to generate: {len(attractions)}")
    print()
    
    # Handle MK16 special case (copy MK01.png)
    mk01_path = os.path.join(OUTPUT_DIR, "MK01.png")
    mk16_path = os.path.join(OUTPUT_DIR, "MK16.png")
    
    if os.path.exists(mk01_path):
        try:
            subprocess.run(['cp', mk01_path, mk16_path], check=True)
            print("📋 MK16.png - Copied from MK01.png ✅")
            successful += 1
        except subprocess.CalledProcessError:
            print("📋 MK16.png - Failed to copy MK01.png ❌")
            failed += 1
    else:
        print("⚠️  MK01.png not found - cannot copy to MK16.png")
        failed += 1
    
    print()
    
    # Generate each attraction image
    for i, (code, description) in enumerate(attractions, 1):
        output_path = os.path.join(OUTPUT_DIR, f"{code}.png")
        
        # Skip if already exists
        if os.path.exists(output_path):
            print(f"⏭️  {i:2d}/47 {code}.png - Already exists, skipping")
            successful += 1
            continue
            
        prompt = STYLE_TEMPLATE.format(description)
        print(f"🎨 {i:2d}/47 Generating {code}.png...")
        print(f"    Prompt: {description}")
        
        if generate_image(prompt, output_path):
            print(f"    ✅ Generated successfully")
            successful += 1
        else:
            print(f"    ❌ Generation failed")
            failed += 1
        
        # Sleep between requests to avoid rate limits (except for last image)
        if i < len(attractions):
            print(f"    ⏱️  Waiting 3 seconds...")
            time.sleep(3)
        print()
    
    print("=" * 60)
    print("🖼️  Resizing all images to 400x400...")
    
    # Resize all images to 400x400
    resize_cmd = [
        'bash', '-c', 
        f'for f in {OUTPUT_DIR}*.png; do convert "$f" -resize 400x400 "$f"; done'
    ]
    
    try:
        result = subprocess.run(resize_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ All images resized successfully")
        else:
            print(f"⚠️  Resize warning: {result.stderr}")
    except Exception as e:
        print(f"❌ Resize failed: {e}")
    
    print("=" * 60)
    print("📊 FINAL REPORT")
    print(f"✅ Successful generations: {successful}")
    print(f"❌ Failed generations: {failed}")
    print(f"📁 Total images in directory: {successful}")
    print("=" * 60)

if __name__ == "__main__":
    main()