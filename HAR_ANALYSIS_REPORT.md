# HAR FILE ANALYSIS REPORT - CityFlo App Data Extraction

## Executive Summary

Successfully parsed and extracted data from HAR file (2.28 MB). The file contains network traffic from the **CityFlo** app - a bus/ride-sharing service operating in India. Multiple sensitive personal information items were detected.

---

## FILES EXTRACTED

1. **cityflo_routes.csv** - Route polyline data from CityFlo tracking API
2. **cityflo_coordinates.csv** - 17 GPS coordinates (latitude/longitude pairs)
3. **cityflo_sensitive_data.csv** - 26 sensitive data entries
4. **har_json_responses.csv** - Raw JSON API responses (21 entries)

---

## ROUTE DATA EXTRACTED

### Route Polylines
- **Source**: tracking.cityflo.com/api/get-polylines/
- **Format**: Google Polyline Algorithm (encoded)
- **Endpoints Captured**: 3 unique URLs
- **Response Size**: 6.3+ KB per request

Example polyline string:
```
yokhCid~yOQNSPQNQPOLMLSESESESE[I]I[I[IQCQEOCQE]G_@G]I]G]G_@G]I]G_@G_@G]G_@G_@G_@G]G_@G_@G_@G]...
```

### GPS Coordinates Identified

**17 coordinate pairs extracted** from Kolkata, India region:

| Latitude | Longitude | Location Type |
|----------|-----------|---------------|
| 22.514272 | 88.394367 | Route point |
| 22.520055 | 88.366235 | Route point |
| 22.518555 | 88.358805 | Route point |
| 22.5179477 | 88.369240 | **Pickup Address** |
| 22.5958327 | 88.487708 | **Destination Address** |

---

## SENSITIVE PERSONAL INFORMATION DETECTED

### Category: NAMES (18 entries)
- **Ujan Sen** - Passenger name
- **Priya Cinema** - Landmark/destination
- **Aliah University** - Destination point
- **Kolkata** - City
- **Ballygunge Gardens** - Residential area
- And others...

### Category: PHONE NUMBERS (4 entries)
- **8697920847** - Primary phone number ⚠️
- **01141171417** - Secondary contact ⚠️
- **03340585166** - Tertiary contact ⚠️
- **02248932335** - Additional number ⚠️

### Category: VEHICLE INFORMATION (4 entries)
- **K126** - Bus/Vehicle registration number ⚠️
  - Appears multiple times indicating repeat bus usage
  - Could be linked to driver tracking

### Category: LOCATION DATA
- **Full pickup address**: "3, Fern Place, Ballygunge Gardens, Gariahat, Kolkata, West Bengal, India"
- **Full destination address**: "Amity University Kolkata, Action Area II, Newtown, Kolkata, West Bengal, India"
- **Other locations**: Priya Cinema, various colleges and universities

### Category: SEAT & BOOKING INFO
- "Female Booked" - Seat booking status indicating:
  - Passenger gender (Female) 
  - Seat availability tracking
  - Other passengers' seat assignments visible

---

## API ENDPOINTS ANALYZED

Total HTTP entries: 61
JSON responses: 21

### Key CityFlo API Endpoints:

| Endpoint | Purpose | Data Exposed |
|----------|---------|--------------|
| `/api/v4/rides/get-boarding-pass-with-tracking-data/` | Real-time ride tracking | Name, phone, vehicle ID, coordinates |
| `/api/users/get-home-screen-data/` | User home screen | Saved locations, addresses, history |
| `/tracking.cityflo.com/api/get-polylines/` | Route polylines | Encoded route geometry |
| `/api/v3/rides/vehicle-ride-seat-layout/` | Seat availability | Seat numbers, gender bookings |
| `/api/users/get-home-data-main/` | User profile data | Personal preferences, saved places |

---

## DATA PRIVACY FINDINGS

### ⚠️ HIGH RISK - Personally Identifiable Information

1. **Real Name**: Ujan Sen (directly exposed in API responses)
2. **Phone Numbers**: 4 different phone numbers associated with account
3. **Home Address**: Full residential address with geolocation coordinates
4. **Workplace/School**: University name and location disclosed
5. **Travel Patterns**: Pickup/dropoff locations show commute pattern (Home → Amity University)
6. **Vehicle Identification**: Bus number K126 links to specific vehicle and driver
7. **Seat Assignment**: Gender-based seat bookings and specific seat numbers visible
8. **User ID**: Customer ID and ride reference numbers exposed (customer_pk: 1676562, customer_ride_pk: 22960247)

### TEMPORAL DATA
- Ride timestamps: 1776824940 (April 22, 2026, ~8:15 AM)
- Start timestamp captured for authentication
- Trip duration and timing information available

### INFERENCE RISKS
From this data, one could:
- Identify the specific person by name + phone
- Track daily commute patterns (home to university)
- Identify which bus/driver is assigned
- Cross-reference seat assignments with other passengers
- Determine gender distribution on specific routes
- Map residential location + workplace (deanonymization risk)

---

## TECHNICAL DETAILS

### HAR File Metadata
- **Filename**: privacy-sandbox.appsflyersdk.com_2026_04_22_08_14_58.har
- **File Size**: 2.28 MB
- **HTTP Entries**: 61
- **Date Generated**: April 22, 2026, 08:14:58
- **App Version**: CityFlo 5.12.9 (SDK v6.17.0)

### Network Traffic Summary
| Protocol | Count | Size |
|----------|-------|------|
| CONNECT | 9 | - |
| GET | 27 | - |
| POST | 25 | - |
| Total Responses | 61 | 2.28 MB |

### Mime Types Captured
- application/json: 20 responses (34.4 KB)
- application/binary: 5 responses (1,345.5 KB)
- application/x-octet-stream: 7 responses (326.2 KB)
- Images: 5 PNG files (8.9 KB)
- Other: HTML, JavaScript, gRPC

---

## RECOMMENDATIONS

### For Privacy Protection:
1. **Do not share** these CSV files publicly - they contain PII
2. **Delete the HAR file** if not needed for legitimate debugging
3. **Review app permissions** - location tracking is clearly enabled
4. **Check CityFlo privacy policy** - ensure data collection is disclosed
5. **Consider using VPN** to mask real IP addresses in future HAR captures
6. **Review ride-sharing alternatives** with better privacy practices

### For Data Security:
1. CityFlo appears to transmit your full address, name, and phone in API responses
2. Vehicle/bus numbers could identify specific drivers
3. Seat assignments expose other passengers' information
4. Consider requesting data deletion from CityFlo
5. Be cautious with real-time tracking features

---

## USAGE EXAMPLES

### Query Routes by Location
```python
import pandas as pd
routes = pd.read_csv('cityflo_coordinates.csv')
kolkata_routes = routes[(routes['latitude'] > 22.5) & (routes['latitude'] < 22.6)]
print(kolkata_routes)
```

### Extract Sensitive Data by Type
```python
sensitive = pd.read_csv('cityflo_sensitive_data.csv')
phone_numbers = sensitive[sensitive['data_type'] == 'PHONE']['value'].unique()
names = sensitive[sensitive['data_type'] == 'NAME']['value'].unique()
```

### Decode Polyline Routes
```python
# Use pypolyline library or Google Maps API
import polyline
encoded = "yokhCid~yOQNSPQNQPOLML..."  # From cityflo_routes.csv
decoded_route = polyline.decode(encoded)
print(decoded_route)  # Returns list of (lat, lng) tuples
```

---

## CONCLUSION

The HAR file capture contains **substantial personally identifiable information** including:
- ✓ Real name
- ✓ Phone numbers (4 variants)
- ✓ Home address with GPS coordinates
- ✓ Workplace/school location
- ✓ Vehicle/bus registration numbers
- ✓ Seat assignment information
- ✓ Daily commute patterns
- ✓ User account IDs

**This represents a significant privacy leak.** Recommend careful handling and secure storage of these extracted files.

---

**Report Generated**: April 22, 2026
**Analysis Tool**: HAR File Parser v1.0
**Files Created**: 4 CSV files + this report
