import json
import os
import csv
from pathlib import Path

# Find HAR file
har_files = [x for x in os.listdir('.') if x.endswith('.har')]
if not har_files:
    print("ERROR: No HAR files found")
    exit(1)

har_file = har_files[0]
print(f"Found HAR file: {har_file}")
print(f"Size: {os.path.getsize(har_file) / 1024 / 1024:.2f} MB")

# Load HAR
print("Loading HAR file...")
with open(har_file, 'r', encoding='utf-8', errors='ignore') as f:
    data = json.load(f)

log = data.get('log', {})
entries = log.get('entries', [])
print(f"Total HTTP entries: {len(entries)}")

# Collect all URLs and methods
print("\n=== HTTP REQUESTS ===")
urls_by_method = {}
for i, entry in enumerate(entries):
    req = entry.get('request', {})
    method = req.get('method', 'UNKNOWN')
    url = req.get('url', 'UNKNOWN')
    
    if method not in urls_by_method:
        urls_by_method[method] = []
    urls_by_method[method].append(url)

for method in sorted(urls_by_method.keys()):
    urls = urls_by_method[method]
    print(f"\n{method}: {len(urls)} requests")
    for url in list(set(urls))[:5]:
        print(f"  - {url[:100]}")

# Investigate response content sizes
print("\n=== RESPONSE ANALYSIS ===")
response_types = {}
for i, entry in enumerate(entries):
    resp = entry.get('response', {})
    content = resp.get('content', {})
    mime_type = content.get('mimeType', 'unknown')
    text = content.get('text', '')
    
    if mime_type not in response_types:
        response_types[mime_type] = {'count': 0, 'total_size': 0, 'samples': []}
    
    response_types[mime_type]['count'] += 1
    response_types[mime_type]['total_size'] += len(text)
    if len(response_types[mime_type]['samples']) < 2:
        response_types[mime_type]['samples'].append({
            'url': entry.get('request', {}).get('url', ''),
            'size': len(text),
            'preview': text[:300] if len(text) < 300 else text[:300] + '...'
        })

for mime_type in sorted(response_types.keys()):
    info = response_types[mime_type]
    print(f"\n{mime_type}:")
    print(f"  Count: {info['count']}")
    print(f"  Total size: {info['total_size'] / 1024:.1f} KB")
    for sample in info['samples']:
        print(f"  Sample: {sample['url'][:80]}")
        if 'json' in mime_type.lower():
            try:
                parsed = json.loads(sample['preview'] if sample['size'] < 300 else sample['preview'][:-3] + '"}')
                print(f"    Keys: {list(parsed.keys())[:5]}")
            except:
                pass

# Extract CSV data - all entries
print("\n=== EXPORTING TO CSV ===")
csv_data = []
for i, entry in enumerate(entries):
    req = entry.get('request', {})
    resp = entry.get('response', {})
    content = resp.get('content', {})
    
    csv_data.append({
        'entry_id': i,
        'method': req.get('method', ''),
        'url': req.get('url', ''),
        'status': resp.get('status', ''),
        'mime_type': content.get('mimeType', ''),
        'response_size': len(content.get('text', '')),
        'response_preview': content.get('text', '')[:200]
    })

# Write to CSV
with open('har_entries.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['entry_id', 'method', 'url', 'status', 'mime_type', 'response_size', 'response_preview'])
    writer.writeheader()
    writer.writerows(csv_data)

print(f"✓ Exported {len(csv_data)} entries to har_entries.csv")

# Try to find route/location data in JSON responses
print("\n=== LOOKING FOR ROUTE/LOCATION DATA ===")
location_data = []
for i, entry in enumerate(entries):
    req = entry.get('request', {})
    resp = entry.get('response', {})
    url = req.get('url', '')
    content = resp.get('content', {})
    text = content.get('text', '')
    
    # Try to parse as JSON
    try:
        if 'json' in content.get('mimeType', '').lower() and text:
            json_data = json.loads(text)
            
            # Look for coordinates, routes, polylines
            json_str = json.dumps(json_data)
            if any(x in json_str.lower() for x in ['lat', 'lon', 'route', 'polyline', 'point', 'stop']):
                location_data.append({
                    'url': url[:150],
                    'size': len(text),
                    'has_coordinates': 'lat' in json_str.lower() or 'lon' in json_str.lower(),
                    'top_keys': str(list(json_data.keys())[:10]) if isinstance(json_data, dict) else 'array',
                    'preview': json.dumps(json_data)[:300]
                })
    except:
        pass

if location_data:
    print(f"Found {len(location_data)} entries with potential location data:")
    for item in location_data[:10]:
        print(f"\n  URL: {item['url']}")
        print(f"  Size: {item['size']} bytes")
        print(f"  Has coordinates: {item['has_coordinates']}")
        print(f"  Top keys: {item['top_keys']}")

print("\nDone! Check har_entries.csv for full data.")
