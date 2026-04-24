# GPS Session Cleaner - Dynamic CSV File Loading

## Changes Made

The application has been updated to **dynamically load CSV files** from the `csv/` folder instead of having them hard-coded in the source.

### What Changed

1. **Removed hard-coded file list** - The `CSV_FILES` array with 35+ hard-coded session names has been removed from `app.js`

2. **Created Node.js Backend Server** - New `server.js` file that:
   - Serves static HTML/CSS/JS files
   - Provides `/api/list-csv-files` endpoint to dynamically discover CSV files in the `csv/` folder
   - Provides `/api/delete-csv` endpoint for file deletion

3. **Updated app.js** - Now:
   - Calls `getCsvFileList()` to fetch available CSV files from the server
   - Dynamically loads whatever CSV files exist in `csv/` folder at runtime
   - No more maintenance needed when adding/removing session files

## How to Run

### Prerequisites
- Node.js installed (download from https://nodejs.org/)

### Installation & Start

1. Open a terminal in this directory
2. Install dependencies:
   ```
   npm install
   ```

3. Start the server:
   ```
   npm start
   ```

4. Open your browser to: `http://localhost:8000`

The server will automatically discover and list all CSV files in the `csv/` folder. Simply add or remove `.csv` files from that folder, and the application will pick them up without any code changes.

## Features

- **Auto-discovery**: Automatically finds all `.csv` files in the `csv/` folder
- **No hard-coding**: CSV file list is generated at runtime
- **Scalable**: Works with any number of session files
- **Dynamic deletion**: File dropdown updates automatically

## File Structure

```
├── server.js              (Node.js Express server)
├── app.js                 (Updated frontend logic)
├── index.html             (Main HTML)
├── styles.css             (Styling)
├── package.json           (Node dependencies)
└── csv/                   (CSV files directory)
    ├── session_001_...csv
    ├── session_002_...csv
    └── ...
```
