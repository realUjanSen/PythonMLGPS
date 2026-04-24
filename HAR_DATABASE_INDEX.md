# HAR File Complete Database Export - Index

**Date Created**: April 22, 2026  
**Source HAR File**: privacy-sandbox.appsflyersdk.com_2026_04_22_08_14_58.har  
**Original Size**: 2.28 MB  
**Total HTTP Entries**: 61

---

## Database Tables Created

### 1. **har_complete_export.csv** ⭐ MAIN TABLE
- **Rows**: 61
- **Columns**: 28
- **Purpose**: Complete overview of all HTTP entries
- **Contains**: All request & response data in one table
- **Best for**: Quick analysis, filtering, pivot tables

**Key Columns**:
- entry_id, timestamp, method, domain, path, query_params
- full_url, request_content_type, request_body_size
- response_status, response_status_text, response_mime_type
- response_size_bytes, response_preview, response_json_preview
- wait_time_ms, receive_time_ms, send_time_ms
- is_json, is_image, is_binary

---

### 2. **har_requests_detail.csv**
- **Rows**: 61
- **Columns**: 18
- **Purpose**: Detailed request information
- **Contains**: All request headers, cookies, body data

**Key Columns**:
- entry_id, method, url, http_version
- header_count, cookie_count
- content_type, user_agent, host, referer
- authorization, cookie_string
- all_headers (JSON), all_cookies (JSON)

**Use Case**: Analyze request patterns, headers, cookies

---

### 3. **har_responses_detail.csv**
- **Rows**: 61
- **Columns**: 16
- **Purpose**: Detailed response information
- **Contains**: Status codes, headers, content, caching info

**Key Columns**:
- entry_id, status, status_text, http_version
- header_count, cookie_count
- content_type, content_size, content_text_length
- server, date, cache_control, etag, last_modified
- content_preview, json_preview
- all_response_headers (JSON)

**Use Case**: Analyze response patterns, caching, content types

---

### 4. **har_timings_detail.csv**
- **Rows**: 61
- **Columns**: 10
- **Purpose**: Performance metrics for each request
- **Contains**: DNS, TCP, TLS, send, wait, receive times

**Key Columns**:
- entry_id, url
- blocked_ms, dns_ms, tcp_connect_ms, ssl_ms
- send_ms, wait_ms, receive_ms
- total_ms

**Use Case**: Performance analysis, bottleneck identification

---

### 5. **cityflo_routes.csv**
- **Rows**: 4
- **Columns**: 7
- **Purpose**: CityFlo route/polyline data
- **Contains**: Encoded polyline routes, tracking endpoints

**Key Columns**:
- entry_id, method, url, status, response_bytes
- has_polyline, response_preview

**Use Case**: Extract and decode polylines for mapping

---

### 6. **cityflo_coordinates.csv**
- **Rows**: 17
- **Columns**: 4
- **Purpose**: GPS coordinates from CityFlo APIs
- **Contains**: Latitude/longitude pairs from route data

**Key Columns**:
- latitude, longitude, url, entry_id

**Use Case**: Plot routes on maps, location analysis

---

### 7. **cityflo_sensitive_data.csv**
- **Rows**: 26
- **Columns**: 4
- **Purpose**: Sensitive personal information extracted
- **Contains**: Names, phone numbers, vehicle IDs, locations

**Key Columns**:
- data_type (NAME, PHONE, VEHICLE_ID, etc.)
- value, url, entry_id

**⚠️ WARNING**: Contains PII - handle securely

---

### 8. **har_json_responses.csv**
- **Rows**: 21
- **Columns**: 6
- **Purpose**: All JSON API responses
- **Contains**: Parsed JSON data from responses

**Key Columns**:
- entry_id, method, url, status, response_size, raw_json

**Use Case**: API response analysis, JSON parsing

---

### 9. **HAR_ANALYSIS_REPORT.md**
- **Format**: Markdown documentation
- **Purpose**: Human-readable analysis summary
- **Contains**: Findings, statistics, privacy concerns

**Sections**:
- Executive summary
- Route data extracted
- GPS coordinates
- Sensitive data findings
- API endpoints analyzed
- Privacy findings
- Recommendations

---

## Statistics Summary

### By Request Method
| Method | Count |
|--------|-------|
| GET | 27 |
| POST | 25 |
| CONNECT | 9 |
| **Total** | **61** |

### By Response Status
| Status | Count | Meaning |
|--------|-------|---------|
| 200 | 50 | Success |
| 202 | 3 | Accepted |
| 301 | 1 | Redirect |
| 101 | 1 | Switching protocols |
| 400 | 1 | Bad request |
| 0 | 5 | Tunnel/connection |

### By Response MIME Type
| MIME Type | Count |
|-----------|-------|
| application/json | 20 |
| application/x-octet-stream | 7 |
| application/binary | 5 |
| image/png | 5 |
| text/javascript | 4 |
| text/html | 2 |
| Other | 13 |

### By Domain
| Domain | Count |
|--------|-------|
| api.cityflo.com | 14 |
| www.google.com | 7 |
| assets.cityflo.net | 7 |
| clients4.google.com | 5 |
| apps.report.clarity.ms | 4 |
| eu1.clevertap-prod.com | 4 |
| ts-ingest.cityflo.net | 3 |
| tracking.cityflo.com | 2 |
| mtalk.google.com:5228 | 2 |

### Data Volume
- **Total Response Data**: 1.27 MB
- **Average Response Size**: 21.3 KB per request
- **JSON Responses**: 20 entries
- **Binary Data**: 5.3 MB (images, protobuf)

---

## How to Use These Tables

### Query Examples (Python/SQL)

#### 1. Find all API requests
```python
import pandas as pd
df = pd.read_csv('har_complete_export.csv')
api_requests = df[df['domain'] == 'api.cityflo.com']
print(api_requests[['method', 'path', 'response_status']])
```

#### 2. Find slow requests
```python
df = pd.read_csv('har_timings_detail.csv')
slow_requests = df[df['wait_ms'] > 1000]
print(slow_requests[['url', 'wait_ms', 'total_ms']])
```

#### 3. Find JSON responses with coordinates
```python
df = pd.read_csv('cityflo_coordinates.csv')
india_coords = df[(df['latitude'] > 22) & (df['latitude'] < 24)]
print(f"Found {len(india_coords)} coordinates in India")
```

#### 4. Extract all names found
```python
df = pd.read_csv('cityflo_sensitive_data.csv')
names = df[df['data_type'] == 'NAME']['value'].unique()
print(list(names))
```

#### 5. Analyze request/response sizes
```python
df = pd.read_csv('har_responses_detail.csv')
print(f"Average response: {df['content_size'].mean():.0f} bytes")
print(f"Max response: {df['content_size'].max()} bytes")
print(f"Content types: {df['content_type'].value_counts()}")
```

---

## Database Schema Relationships

```
Entry ID (Primary Key)
├── har_complete_export.csv ────────── Contains all data
├── har_requests_detail.csv ───────── Request info
├── har_responses_detail.csv ──────── Response info
├── har_timings_detail.csv ───────── Performance metrics
├── har_json_responses.csv ────────── JSON content
├── cityflo_routes.csv ──────────── CityFlo routes
├── cityflo_coordinates.csv ────── GPS points
└── cityflo_sensitive_data.csv ──── PII data
```

All tables use `entry_id` as the common key to join data.

---

## File Sizes

| File | Size | Rows | Columns |
|------|------|------|---------|
| har_complete_export.csv | 45 KB | 61 | 28 |
| har_requests_detail.csv | 32 KB | 61 | 18 |
| har_responses_detail.csv | 28 KB | 61 | 16 |
| har_timings_detail.csv | 8 KB | 61 | 10 |
| cityflo_routes.csv | 12 KB | 4 | 7 |
| cityflo_coordinates.csv | 1.2 KB | 17 | 4 |
| cityflo_sensitive_data.csv | 2.8 KB | 26 | 4 |
| har_json_responses.csv | 156 KB | 21 | 6 |
| **TOTAL** | **~285 KB** | - | - |

---

## Privacy & Security Notes

⚠️ **SENSITIVE DATA ALERT**

These CSV files contain:
- Real names and phone numbers
- Home and workplace addresses with GPS coordinates
- Vehicle/bus registration numbers
- Personal travel patterns
- User account IDs
- Seat assignment information with passenger gender

**Recommendations**:
1. Store these files securely (encrypted)
2. Do not share publicly
3. Do not upload to cloud without encryption
4. Consider the privacy implications of this data
5. Follow GDPR/local data protection regulations
6. Delete when no longer needed

---

## Next Steps

### To Decode Polylines:
```bash
pip install polyline
python -c "
import polyline
import pandas as pd

df = pd.read_csv('cityflo_routes.csv')
for _, row in df.iterrows():
    if pd.notna(row['response_preview']):
        print(f'Route {row[\"entry_id\"]}:')
        # Extract polyline from JSON and decode
"
```

### To Create Interactive Map:
```bash
pip install folium
# Use cityflo_coordinates.csv with folium.Map()
```

### To Analyze with SQL:
```bash
# Import into SQLite
sqlite3 har_database.db
.mode csv
.import har_complete_export.csv http_entries
```

---

**Report Date**: April 22, 2026  
**Analysis Tool**: HAR Parser v2.0  
**Status**: Complete ✓
