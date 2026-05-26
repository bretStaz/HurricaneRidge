import os
import sys
import json
from datetime import datetime
import pytz
import requests

def main():
    print("[INFO] Starting Hurricane Ridge status update pipeline...")
    
    # ---------------------------------------------------------
    # 1. Fetch Weather Data (National Weather Service API)
    # ---------------------------------------------------------
    weather_temp = "Data unavailable"
    weather_wind = "Data unavailable"
    
    # Custom User-Agent required by NWS to avoid 403 Forbidden errors
    nws_headers = {
        "User-Agent": "HurricaneRidgeStatusApp/1.0 (contact@example.com)"
    }
    
    print("[INFO] Fetching weather from National Weather Service...")
    try:
        # Step 1: Query the metadata endpoint for coordinates (Hurricane Ridge Visitor Center)
        points_url = "https://api.weather.gov/points/47.9691,-123.4983"
        print(f"[INFO] Accessing points metadata: {points_url}")
        r_points = requests.get(points_url, headers=nws_headers, timeout=10)
        r_points.raise_for_status()
        
        # Step 2: Extract and fetch the specific forecast endpoint
        forecast_url = r_points.json()["properties"]["forecast"]
        print(f"[INFO] Retrieving forecast grid: {forecast_url}")
        r_forecast = requests.get(forecast_url, headers=nws_headers, timeout=10)
        r_forecast.raise_for_status()
        
        # Step 3: Parse the first forecast period
        forecast_data = r_forecast.json()
        periods = forecast_data.get("properties", {}).get("periods", [])
        if periods:
            first_period = periods[0]
            temp = first_period.get("temperature")
            temp_unit = first_period.get("temperatureUnit", "F")
            speed = first_period.get("windSpeed")
            direction = first_period.get("windDirection", "")
            
            # Format temperature (e.g., 45°F)
            if temp is not None:
                weather_temp = f"{temp}°{temp_unit}"
            
            # Format wind speed & direction (e.g., 15 mph NW)
            if speed is not None and direction:
                weather_wind = f"{speed} {direction}"
            elif speed is not None:
                weather_wind = speed
                
            print(f"[INFO] Weather parsed successfully: {weather_temp}, {weather_wind}")
        else:
            print("[WARN] Weather periods structure empty or missing.")
    except Exception as e:
        print(f"[ERROR] Weather API call failed: {e}")
        # Proceed with weather set to "Data unavailable"

    # ---------------------------------------------------------
    # 2. Fetch Alerts (National Park Service API)
    # ---------------------------------------------------------
    status = "YES"
    status_message = "Gate is open. Drive safely and expect lines at the toll booth."
    
    nps_api_key = os.environ.get("NPS_API_KEY")
    nps_headers = {}
    if nps_api_key:
        nps_headers["X-Api-Key"] = nps_api_key
    else:
        print("[WARN] NPS_API_KEY environment variable not set. Attempting request without key.")

    alerts_url = "https://developer.nps.gov/api/v1/alerts?parkCode=olym"
    print(f"[INFO] Fetching alerts from NPS: {alerts_url}")
    try:
        r_alerts = requests.get(alerts_url, headers=nps_headers, timeout=10)
        r_alerts.raise_for_status()
        
        alerts_list = r_alerts.json().get("data", [])
        print(f"[INFO] NPS returned {len(alerts_list)} alerts.")
        
        # Filter and parse active alerts referencing Hurricane Ridge
        matching_alerts = []
        for alert in alerts_list:
            title = (alert.get("title", "") or "").lower()
            description = (alert.get("description", "") or "").lower()
            combined_text = f"{title} {description}"
            
            # Must mention "hurricane" and "ridge"
            if "hurricane" in combined_text and "ridge" in combined_text:
                # Check for explicit indicators that Hurricane Ridge remains open
                is_ridge_open = False
                open_phrases = [
                    "ridge road will remain open", 
                    "ridge road remains open", 
                    "ridge road is open", 
                    "ridge will remain open", 
                    "ridge remains open", 
                    "ridge is open"
                ]
                if any(phrase in combined_text for phrase in open_phrases):
                    is_ridge_open = True
                
                # Check for explicit indicators that Hurricane Ridge is closed
                is_ridge_closed = False
                closed_phrases = [
                    "ridge road is closed",
                    "ridge road will be closed",
                    "ridge road closed",
                    "ridge is closed",
                    "ridge closed",
                    "road is closed due to"
                ]
                if any(phrase in combined_text for phrase in closed_phrases):
                    is_ridge_closed = True
                
                # Check for general closure and capacity keywords
                has_closure = any(word in combined_text for word in ["closed", "weather", "snow", "trees"])
                has_capacity = any(word in combined_text for word in ["capacity", "full", "delays", "line"])
                
                alert_status = "YES"
                # If the alert mentions closure but indicates Ridge remains open (and not explicitly closed),
                # we treat the road as open (YES). Otherwise, it evaluates to closed (NO).
                if has_closure:
                    if is_ridge_open and not is_ridge_closed:
                        alert_status = "YES"
                    else:
                        alert_status = "NO"
                elif has_capacity:
                    alert_status = "FULL"
                
                alert["computed_status"] = alert_status
                matching_alerts.append(alert)
                
        if matching_alerts:
            print(f"[INFO] Found {len(matching_alerts)} alerts mentioning 'Hurricane Ridge'. Processing rules...")
            
            # Prioritize NO (closed) > FULL (capacity limit) > YES (open) across all matching alerts
            final_status = "YES"
            final_message = "Gate is open. Drive safely and expect lines at the toll booth."
            
            # We seek the highest priority alert state found
            no_alerts = [a for a in matching_alerts if a["computed_status"] == "NO"]
            full_alerts = [a for a in matching_alerts if a["computed_status"] == "FULL"]
            yes_alerts = [a for a in matching_alerts if a["computed_status"] == "YES"]
            
            if no_alerts:
                final_status = "NO"
                # Use the description of the first closure alert
                final_message = no_alerts[0].get("description", "")
            elif full_alerts:
                final_status = "FULL"
                final_message = full_alerts[0].get("description", "")
            elif yes_alerts:
                final_status = "YES"
                # Use the description of the informational alert unless it refers to Hurricane Hill
                desc = yes_alerts[0].get("description", "")
                if desc and "hurricane hill" not in desc.lower():
                    final_message = desc
                else:
                    final_message = "Gate is open. Drive safely and expect lines at the toll booth."
                    
            status = final_status
            status_message = final_message
            print(f"[INFO] Evaluation result -> Status: {status}")
        else:
            print("[INFO] No active alerts for Hurricane Ridge found. Status: YES.")
            
    except Exception as e:
        print(f"[ERROR] NPS alerts API call failed: {e}")
        # Severe error for gate status: set status to ERROR
        status = "ERROR"
        status_message = "NPS API is currently unreachable."

    # ---------------------------------------------------------
    # 3. Webcam URL
    # ---------------------------------------------------------
    webcam_url = "https://www.nps.gov/webcams-olym/hrparkinglot.jpg"

    # ---------------------------------------------------------
    # 4. Generate Pacific Time Timestamp
    # ---------------------------------------------------------
    try:
        pacific_tz = pytz.timezone("US/Pacific")
        now = datetime.now(pacific_tz)
        
        # Build standard time format: e.g., "8:35 AM"
        time_formatted = now.strftime("%I:%M %p")
        # Strip leading zero on hour if it exists
        if time_formatted.startswith("0"):
            time_formatted = time_formatted[1:]
            
        tz_abbr = now.strftime("%Z")
        last_updated = f"Updated Today at {time_formatted} {tz_abbr}"
        print(f"[INFO] Timestamp generated: {last_updated}")
    except Exception as e:
        print(f"[ERROR] Failed to format timestamp: {e}")
        last_updated = "Updated Today"

    # ---------------------------------------------------------
    # 5. Build Output and Write status.json
    # ---------------------------------------------------------
    status_payload = {
        "status": status,
        "status_message": status_message,
        "last_updated": last_updated,
        "weather_temp": weather_temp,
        "weather_wind": weather_wind,
        "webcam_url": webcam_url
    }
    
    output_filename = "status.json"
    # Write to the same directory where this script lives
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, output_filename)
    
    print(f"[INFO] Saving output payload to {output_path}...")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(status_payload, f, indent=2, ensure_ascii=False)
        print("[INFO] Pipeline completed successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to write output file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
