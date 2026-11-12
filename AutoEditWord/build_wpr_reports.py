from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "Weekly Progress Report.pdf"
OUTPUT_DIR = ROOT / "WPR_Reconstructed"
COMBINED = ROOT / "Weekly_Progress_Reports_Reconstructed.pdf"
FONT_FILE = "C:/Windows/Fonts/verdana.ttf"
VERTICAL_TEXT_SHIFT = 10
INTERNSHIP_START = date(2026, 8, 17)
INTERNSHIP_END = date(2026, 11, 20)

WEEK_THEMES = [
    ("Android route selection", "Added explicit Home-to-Office and Office-to-Home options before recording a commute.", "Connected the selected direction to session metadata so the two routes can be separated during later processing.", ["Built the two route choices.", "Stored the selected direction with each recording.", "Tested starting and stopping both route types.", "Checked that morning and evening sessions remained distinguishable.", "Recorded the route-selection behavior for the Android workflow."]),
    ("Five-second GPS polyline updates", "Added a location update loop that pulls a GPS point every five seconds.", "Drew the recorded path as a translucent polyline so movement is visible while the session is running.", ["Added the five-second location interval.", "Created the live translucent polyline.", "Updated the line as new points arrived.", "Checked the line during both commute directions.", "Verified that the displayed path matched the saved points."]),
    ("Satellite status and signal display", "Added the number of visible satellites and the number reporting a usable fix.", "Displayed satellite signal strength values and used 25 as a practical indication of good strength without assigning an unsupported unit.", ["Read the satellite status values.", "Separated visible satellites from satellites with a fix.", "Displayed the signal-strength readings.", "Tested the status while the phone moved outside.", "Recorded how satellite availability affected the recording."]),
    ("On-device session database", "Created the Android phone database for storing sessions and their location points.", "Added deletion of old sessions from the phone so accumulated recordings do not keep slowing the application.", ["Created the session tables and relationships.", "Saved location points under the active session.", "Loaded the stored sessions for review.", "Deleted an old session directly from the phone.", "Checked that deleting a session reduced the stored backlog."]),
    ("Leaflet map marker and caching", "Created the GPS locator marker with Leaflet and integrated the map display with the recorded route.", "Followed Leaflet's caching-related implementation so the map and marker remain usable during repeated route viewing.", ["Added the Leaflet map and GPS marker.", "Updated the marker as the current position changed.", "Drew the route behind the marker.", "Checked cached map behavior during repeated use.", "Verified that the locator and polyline stayed synchronized."]),
    ("Android diagnostics and obstruction alert", "Added a debug log for application errors and recording failures.", "Added a 30-second vibration alert to tell the user to move the phone outside when satellite communication is obstructed.", ["Added structured debug messages for failures.", "Triggered the obstruction timer after 30 seconds.", "Added phone vibration feedback.", "Tested the alert with poor satellite visibility.", "Checked that the alert helped identify blocked GPS conditions."]),
    ("Permissions and battery behavior", "Added the required location permissions and handled the phone's battery restrictions for recording.", "Configured the relevant battery settings so the Android process can continue collecting GPS points without being stopped silently.", ["Requested the required location permissions.", "Handled permission denial and re-entry.", "Reviewed battery optimization settings.", "Tested recording while the screen and app state changed.", "Verified that the recorder continued collecting points."]),
    ("Browser pruning and eraser", "Built the browser pruning workflow with an eraser for removing bad GPS observations.", "Used the eraser to remove the least reliable points from the stack of displayed polylines and reconnect the remaining path.", ["Loaded multiple recorded polylines.", "Selected noisy and off-road points.", "Removed points with the eraser.", "Checked the reconnection between neighboring points.", "Saved the cleaned trajectory for later processing."]),
    ("Route snapping and reference polylines", "Implemented snapping of recorded points to representative morning and evening route polylines.", "Calculated nearest-route positions and off-route distances so noisy coordinates can be compared on a common route.", ["Selected reference sessions for both directions.", "Projected GPS points onto the reference polylines.", "Calculated along-route distance.", "Measured off-route error.", "Reviewed the snapped CSV outputs."]),
    ("ETA features and route profiles", "Built progress, speed, route-bin, and congestion features from the cleaned and snapped sessions.", "Created route profiles with average speed, session support, coordinates, and congestion values for ETA prediction.", ["Calculated monotonic route progress.", "Derived speed from progress and timestamps.", "Assigned 120-metre route bins.", "Aggregated profile speeds and support counts.", "Inspected congestion and choke-point candidates."]),
    ("ETA model training", "Trained Random Forest with 300 trees, HistGradientBoosting with depth 8, learning rate 0.05, and 500 iterations.", "Compared XGBoost with 200 estimators, depth 8, learning rate 0.04, 0.85 row and column subsampling, using GroupShuffleSplit with a 25% test set.", ["Prepared the eight ETA feature columns.", "Trained the Random Forest baseline.", "Trained HistGradientBoosting and XGBoost.", "Measured MAE, RMSE, R2, and weighted metrics.", "Saved model comparisons and learning diagnostics."]),
    ("ETA prediction and final integration", "Implemented CLI ETA prediction using route, start time, progress, coordinates, destination, and optional session ID.", "Blended the trained model with local route-profile ETA, session statistics, and upcoming choke points for the final prediction output.", ["Tested morning and evening prediction inputs.", "Checked latitude/longitude route-position lookup.", "Tested destination-aware ETA scaling.", "Verified session-aware blending and choke-point output.", "Completed the final report evidence. Packaged the generated outputs and submission files."]),
]

DAY_DETAILS = [
    [
        "The direction is now available before a recording session begins.",
        "The saved metadata identifies which route was selected.",
        "Both choices were exercised with separate test recordings.",
        "The route value remains available when the session is exported.",
        "The recording flow now supports the two commute directions consistently.",
    ],
    [
        "The timer controls the interval between consecutive location requests.",
        "The line is updated without hiding the underlying map.",
        "New points are appended in chronological order.",
        "The trace was observed while the route direction changed.",
        "The live display and exported coordinates describe the same path.",
    ],
    [
        "The status panel now distinguishes visibility from a usable fix.",
        "The fix count changes independently from the total satellite count.",
        "The readings are shown without guessing a measurement unit.",
        "The test confirmed that open-sky conditions improve the readings.",
        "The information gives the user a direct indication of GPS quality.",
    ],
    [
        "The schema keeps each session separate from its location-point records.",
        "Points are associated with the correct active session.",
        "The session list can be read back after recording stops.",
        "Deletion removes the selected session instead of only hiding it.",
        "The phone no longer needs to retain every old recording indefinitely.",
    ],
    [
        "The marker follows the latest GPS coordinate on the map.",
        "The map position and current route direction remain visible together.",
        "The path remains readable while the marker moves forward.",
        "Repeated map loads use the configured cached resources.",
        "The map layer, marker, and route line now form one usable view.",
    ],
    [
        "The log records enough context to identify where a failure occurred.",
        "The timer is tied to the period without a usable satellite update.",
        "The phone gives an immediate physical warning instead of relying only on the screen.",
        "The test reproduced the warning under obstructed conditions.",
        "The alert directs the user to move the phone outside before retrying.",
    ],
    [
        "The application requests access before starting location collection.",
        "The recorder returns to a usable state after the permission flow.",
        "Battery restrictions were reviewed as a separate cause of interrupted tracking.",
        "The recorder was checked during background and screen-off conditions.",
        "Location collection is now protected against the main permission and battery interruptions.",
    ],
    [
        "The eraser operates on the visible route data rather than deleting the source files blindly.",
        "Neighboring points are joined after the selected point is removed.",
        "The cleaned line was compared with the original noisy trace.",
        "The remaining path was checked for gaps caused by over-pruning.",
        "The edited trajectory can now be used as a cleaner input for snapping.",
    ],
    [
        "The reference route provides a common geometry for both commute directions.",
        "Each point receives a nearest position on that geometry.",
        "The distance measure identifies observations that drift away from the route.",
        "The projected progress can be compared across different sessions.",
        "The generated snapped files preserve the original session identity.",
    ],
    [
        "The feature table combines route position with observed movement conditions.",
        "Speed is calculated from consecutive progress and timestamp values.",
        "The bins make sessions comparable at fixed route distances.",
        "Support counts show how much historical data backs each profile value.",
        "The resulting profiles provide the inputs needed by the ETA models.",
    ],
    [
        "The training table uses route type, start minute, weekday, progress, off-route distance, speed, profile speed, and support.",
        "The group split keeps rows from the same session out of both partitions.",
        "The three regressors were trained against the remaining-time target.",
        "The metrics expose both ordinary and sample-weighted model behavior.",
        "The saved diagnostics make the model comparison reproducible.",
    ],
    [
        "The command accepts either progress values or coordinates near the reference route.",
        "The nearest profile bin supplies the local speed and support context.",
        "The destination path is scaled separately from the full route estimate.",
        "The output reports the model, local ETA, session blend, and choke points.",
        "The final files contain the completed prediction workflow and its supporting evidence.",
    ],
]

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def weeks():
    report_starts = [
        INTERNSHIP_START + timedelta(days=7 * index)
        for index in range(14)
        if INTERNSHIP_START + timedelta(days=7 * index) not in {
            date(2026, 10, 19),
            date(2026, 11, 9),
        }
    ]
    yield from report_starts[:12]


def draw_text(page, rect, text, size=9, color=(0, 0, 0), align=0, lineheight=1.15):
    page.insert_textbox(rect, text, fontname="Verdana", fontfile=FONT_FILE, fontsize=size, color=color, align=align, lineheight=lineheight)


def draw_centered_text(page, rect, text, size=7.5, color=(0, 0, 0), lineheight=1.05):
    font = fitz.Font(fontname="Verdana", fontfile=FONT_FILE)
    max_width = rect.width
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and font.text_length(candidate, fontsize=size) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)

    line_height = size * lineheight
    text_height = max(line_height, len(lines) * line_height)
    top = rect.y0 + max(0, (rect.height - text_height) / 2) + VERTICAL_TEXT_SHIFT
    target = fitz.Rect(rect.x0, top, rect.x1, top + text_height + 2)
    page.insert_textbox(
        target,
        "\n".join(lines),
        fontname="Verdana",
        fontfile=FONT_FILE,
        fontsize=size,
        color=color,
        align=0,
        lineheight=lineheight,
    )


def fill_page(template_doc, week_start, theme_index):
    page = template_doc[0]
    theme, first, second, daily_work = WEEK_THEMES[theme_index % len(WEEK_THEMES)]

    draw_text(page, fitz.Rect(310, 122, 540, 137), week_start.strftime("%d %B %Y"), 9)
    draw_text(page, fitz.Rect(140, 147, 275, 162), "A914138123021", 9)
    draw_text(page, fitz.Rect(100, 168, 295, 183), "UJAN SEN", 9)
    draw_text(page, fitz.Rect(125, 191, 300, 205), "B.Sc Data Science Honors/Research", 7.8)
    draw_text(page, fitz.Rect(225, 212, 540, 228), " ", 9)
    draw_text(page, fitz.Rect(225, 246, 540, 262), "DR. ANWESHA LAW", 9)
    draw_text(page, fitz.Rect(225, 270, 540, 286), "Not Applicable", 9)
    draw_text(page, fitz.Rect(225, 316, 540, 331), "Offline", 9)
    draw_text(page, fitz.Rect(63, 365, 550, 387), "Route-Aware Machine Learning Framework for GPS-Based ETA Prediction", 8.5)

    draw_centered_text(page, fitz.Rect(63, 395, 550, 429), f"Complete work for: {theme}. {first}", 7.8)
    draw_centered_text(page, fitz.Rect(63, 436, 550, 473), second, 7.8)
    future_work = (
        "Finalize the report evidence, package the generated outputs, and prepare the submission."
        if week_start == INTERNSHIP_END - timedelta(days=4)
        else "Continue the next pipeline stage, validate the outputs, and document decisions for the project report."
    )
    draw_centered_text(page, fitz.Rect(63, 484, 550, 521), future_work, 7.8)

    for i, day in enumerate(DAYS):
        day_date = week_start + timedelta(days=i)
        daily_text = daily_work[i]
        if not (theme_index == len(WEEK_THEMES) - 1 and i == len(DAYS) - 1):
            daily_text = f"{daily_text} {DAY_DETAILS[theme_index][i]}"
        text = f"{day_date.strftime('%d %b')}: {daily_text}"
        row_rect = fitz.Rect(163, 583 + i * 32, 566, 617 + i * 32)
        draw_centered_text(page, row_rect, text, 6.5, lineheight=1.05)


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    report_weeks = list(weeks())
    if len(report_weeks) != 12 or report_weeks[-1] + timedelta(days=4) != INTERNSHIP_END:
        raise ValueError("WPR schedule must contain 12 reports and end on 20 November 2026")
    for existing in OUTPUT_DIR.glob("WPR_*.pdf"):
        existing.unlink()

    combined = fitz.open()
    for index, week_start in enumerate(report_weeks):
        document = fitz.open(TEMPLATE)
        fill_page(document, week_start, index)
        individual = OUTPUT_DIR / f"WPR_{week_start.isoformat()}.pdf"
        document.save(individual)
        combined.insert_pdf(document)
        document.close()
    combined.save(COMBINED)
    combined.close()
    print(f"Generated {len(report_weeks)} weekly reports")
    print(COMBINED)


if __name__ == "__main__":
    main()
