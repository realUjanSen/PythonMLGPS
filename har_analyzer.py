#!/usr/bin/env python3
"""
Analyze HAR file to extract:
1. Route polylines
2. Bus stops/points
3. Sensitive personal information (PII)
"""

import json
import re
import os
from pathlib import Path
from datetime import datetime

HAR_FILE = "privacy-sandbox.appsflyersdk.com_2026_04_22_08_14_58.har"

# Patterns for detecting sensitive data
PII_PATTERNS = {
    'phone': r'(\+?\d{1,3}[-.\s]?\d{3}[-.\s]?\d{3}[-.\s]?\d{4}|\b\d{10}\b)',
    'email': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    'credit_card': r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b',
    'ssn': r'\b\d{3}-\d{2}-\d{4}\b',
    'name_pattern': r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',  # Firstname Lastname
    'license_plate': r'\b[A-Z]{2,3}\d{3,4}[A-Z]{0,2}\b',
    'coordinates': r'[-+]?\d+\.\d+,[-+]?\d+\.\d+'
}

def find_pii(text, limit=100):
    """Scan text for sensitive information"""
    pii_found = {}
    for pii_type, pattern in PII_PATTERNS.items():
        matches = re.findall(pattern, text)
        if matches:
            unique_matches = list(set(matches))[:limit]
            pii_found[pii_type] = unique_matches
    return pii_found

def parse_har():
    """Parse HAR file and extract data"""
    try:
        with open(HAR_FILE, 'r', encoding='utf-8') as f:
            har_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse HAR file as JSON: {e}")
        return None
    except FileNotFoundError:
        print(f"ERROR: HAR file not found: {HAR_FILE}")
        return None
    
    return har_data

def extract_routes_and_stops(har_data):
    """Extract polylines and bus stop coordinates from HAR entries"""
    routes = []
    bus_stops = []
    
    try:
        entries = har_data.get('log', {}).get('entries', [])
        print(f"\n[INFO] Found {len(entries)} HTTP entries in HAR")
        
        for i, entry in enumerate(entries):
            url = entry.get('request', {}).get('url', '')
            method = entry.get('request', {}).get('method', '')
            response_text = entry.get('response', {}).get('content', {}).get('text', '')
            
            # Look for route/polyline API calls
            if 'route' in url.lower() or 'polyline' in url.lower() or 'navigation' in url.lower():
                print(f"\n[ROUTE] Entry {i}: {url[:100]}")
                print(f"  Method: {method}")
                if response_text:
                    try:
                        data = json.loads(response_text)
                        # Look for polyline data
                        polyline_matches = extract_polylines(response_text)
                        if polyline_matches:
                            routes.append({
                                'url': url,
                                'polylines': polyline_matches[:5]  # First 5 polylines
                            })
                    except:
                        pass
            
            # Look for bus stop data
            if any(x in url.lower() for x in ['stop', 'station', 'point', 'location', 'address']):
                print(f"\n[BUS_STOP] Entry {i}: {url[:100]}")
                print(f"  Method: {method}")
                if response_text and len(response_text) < 5000:
                    print(f"  Response preview: {response_text[:200]}")
                    # Extract coordinates
                    coords = re.findall(r'[-+]?\d+\.\d+', response_text)
                    if coords and len(coords) >= 2:
                        bus_stops.append({
                            'url': url,
                            'coordinates': coords[:100]  # Limit to 100 coords
                        })
            
            # Also capture any response that looks like location/coordinate data
            if response_text:
                coords = re.findall(r'(?:"lat(?:itude)?"\s*:\s*[-+]?\d+\.\d+|"lng(?:itude)?"\s*:\s*[-+]?\d+\.\d+)', response_text)
                if coords and len(coords) > 2:
                    if 'map' in url.lower() or 'location' in url.lower():
                        print(f"\n[COORDS_FOUND] Entry {i}: Found coordinates in {url[:80]}")
    
    except Exception as e:
        print(f"ERROR extracting routes: {e}")
    
    return routes, bus_stops

def extract_polylines(text):
    """Try to extract polyline-encoded strings"""
    # Common polyline patterns (encoded Google polyline format usually starts with _ or a letter)
    patterns = [
        r'"polyline"\s*:\s*"([a-zA-Z0-9_\-~]+)"',
        r'"routes"\s*:\s*\[.*?"polyline"\s*:\s*"([a-zA-Z0-9_\-~]+)"',
        r'polyline["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_\-~]{20,})["\']?'
    ]
    
    polylines = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        polylines.extend(matches)
    
    return polylines[:10]

def scan_all_content_for_pii(har_data):
    """Scan all HTTP response content for PII"""
    pii_results = {}
    
    try:
        entries = har_data.get('log', {}).get('entries', [])
        total_content_size = 0
        
        for i, entry in enumerate(entries):
            response_text = entry.get('response', {}).get('content', {}).get('text', '')
            if not response_text:
                continue
            
            total_content_size += len(response_text)
            
            # Skip very large responses (likely binary)
            if len(response_text) > 100000:
                continue
            
            pii = find_pii(response_text)
            if pii:
                url = entry.get('request', {}).get('url', 'unknown')
                pii_results[url] = pii
        
        print(f"\n[SCAN] Total response content scanned: {total_content_size / 1024 / 1024:.2f} MB")
    
    except Exception as e:
        print(f"ERROR scanning for PII: {e}")
    
    return pii_results

def main():
    print("=" * 80)
    print("HAR FILE ANALYZER - City Flow Routes & Bus Stops Extraction")
    print("=" * 80)
    
    # Check file
    if not os.path.exists(HAR_FILE):
        print(f"ERROR: {HAR_FILE} not found in current directory")
        print(f"Current directory: {os.getcwd()}")
        return
    
    file_size_mb = os.path.getsize(HAR_FILE) / 1024 / 1024
    print(f"\n[FILE] {HAR_FILE}")
    print(f"[SIZE] {file_size_mb:.2f} MB")
    
    # Parse HAR
    print(f"\n[PARSING] Reading HAR file...")
    har_data = parse_har()
    if not har_data:
        return
    
    print("[SUCCESS] HAR file parsed")
    
    # Extract routes and bus stops
    print(f"\n[EXTRACTING] Routes and Bus Stops...")
    routes, bus_stops = extract_routes_and_stops(har_data)
    print(f"\n[RESULTS] Found {len(routes)} route entries, {len(bus_stops)} bus stop entries")
    
    # Scan for PII
    print(f"\n[SCANNING] Looking for sensitive information (PII)...")
    pii_results = scan_all_content_for_pii(har_data)
    
    # Report PII findings
    if pii_results:
        print(f"\n{'='*80}")
        print("⚠️  SENSITIVE DATA FOUND:")
        print(f"{'='*80}")
        for url, pii_data in list(pii_results.items())[:20]:  # First 20 URLs
            print(f"\n[URL] {url[:120]}")
            for pii_type, values in pii_data.items():
                if values:
                    print(f"  {pii_type.upper()}: {values[:3]}")  # Show first 3 examples
    else:
        print("\n✓ No obvious PII patterns detected in responses")
    
    # Create CSV output
    print(f"\n[EXPORT] Creating CSV outputs...")
    
    # Export routes
    if routes:
        with open('extracted_routes.csv', 'w', encoding='utf-8') as f:
            f.write('url,polyline_sample\n')
            for route in routes[:50]:
                polyline = route['polylines'][0] if route['polylines'] else 'N/A'
                f.write(f'"{route["url"][:100]}","{polyline}"\n')
        print(f"✓ Saved {len(routes)} routes to extracted_routes.csv")
    
    # Export bus stops
    if bus_stops:
        with open('extracted_bus_stops.csv', 'w', encoding='utf-8') as f:
            f.write('url,latitude,longitude\n')
            stop_count = 0
            for stop in bus_stops:
                for i in range(0, len(stop['coordinates']), 2):
                    if i+1 < len(stop['coordinates']):
                        lat = stop['coordinates'][i]
                        lng = stop['coordinates'][i+1]
                        f.write(f'"{stop["url"][:80]}",{lat},{lng}\n')
                        stop_count += 1
                        if stop_count >= 1000:  # Limit output
                            break
                if stop_count >= 1000:
                    break
        print(f"✓ Saved coordinates to extracted_bus_stops.csv")
    
    # Export PII findings
    if pii_results:
        with open('pii_findings.txt', 'w', encoding='utf-8') as f:
            f.write("SENSITIVE DATA DETECTED IN HAR FILE\n")
            f.write("=" * 80 + "\n\n")
            for url, pii_data in pii_results.items():
                f.write(f"URL: {url}\n")
                for pii_type, values in pii_data.items():
                    f.write(f"  {pii_type.upper()}:\n")
                    for value in values[:5]:
                        f.write(f"    - {value}\n")
                f.write("\n")
        print(f"✓ Saved {len(pii_results)} URLs with PII to pii_findings.txt")
    
    print(f"\n[SUMMARY] Analysis complete. Check output files in current directory.")
    print(f"Files created:")
    print(f"  - extracted_routes.csv (polylines)")
    print(f"  - extracted_bus_stops.csv (coordinates)")
    print(f"  - pii_findings.txt (sensitive data)")

if __name__ == '__main__':
    main()
