import streamlit as st
import pandas as pd
import re
from datetime import datetime
import io
import numpy as np

# --- 1. Core Parsing and Splitting Logic Functions ---

def get_half_day_value(date_str):
    """Converts a date string (e.g., '17/09/2025FN') into a half-day numeric value for calculation."""
    match = re.search(r'(\d{2}/\d{2}/\d{4})(FN|AN)', date_str)
    if not match:
        raise ValueError(f"Invalid date format: {date_str}")
    date_part, half_day_part = match.groups()
    date_obj = datetime.strptime(date_part, '%d/%m/%Y')
    value = date_obj.toordinal() * 2 + (0 if half_day_part == 'FN' else 1)
    return date_obj, value, half_day_part

def calculate_leave_days(from_dt_str_full, to_dt_str_full):
    """Calculates leave days based on FN/AN parts for a segment."""
    try:
        _, from_value, _ = get_half_day_value(from_dt_str_full)
        _, to_value, _ = get_half_day_value(to_dt_str_full)
        total_half_days = (to_value - from_value) + 1
        return total_half_days / 2
    except ValueError:
        return np.nan

def parse_and_split_leave(row):
    """Parses leave details, splits records across the month boundary (30/09/2025 AN to 01/10/2025 FN)
    for LAP, LHAP, COL, and returns a list of dictionaries for each sanctioned segment."""
    leave_details = str(row['Leave Details'])
    records = []
    
    try:
        sept_30_an_boundary_val = get_half_day_value('30/09/2025AN')[1]
    except ValueError:
        return records

    # Regex to find all segments: (LeaveType) (Days.D) days (Content_Inside_Brackets)
    leave_segments = re.findall(r'([A-Z]+)\s+([\d.]+)\s+days\s+\((.*?)\)', leave_details)

    for leave_type, total_days_str, date_ranges_str in leave_segments:
        # Pattern to find each complete date group: DATE_FN/AN - DATE_FN/AN (Anything_Inside_Brackets)
        date_groups = re.findall(r'(\d{2}/\d{2}/\d{4}FN|\d{2}/\d{2}/\d{4}AN)-(\d{2}/\d{2}/\d{4}FN|\d{2}/\d{2}/\d{4}AN)\s*\(([^)]*)\)', date_ranges_str)

        for from_dt_str_full, to_dt_str_full, _ in date_groups: # Authority info is captured but ignored by '_'
            
            try:
                _, from_value, _ = get_half_day_value(from_dt_str_full)
                _, to_value, _ = get_half_day_value(to_dt_str_full)
            except ValueError:
                continue

            # --- Splitting Logic (User Requirement) ---
            is_splittable = leave_type in ['LAP', 'LHAP', 'COL']
            
            if is_splittable and from_value <= sept_30_an_boundary_val and to_value > sept_30_an_boundary_val:
                # 1. September part
                sept_part_to_dt_full = '30/09/2025AN'
                sept_days = calculate_leave_days(from_dt_str_full, sept_part_to_dt_full)
                
                records.append({
                    'Name': row['Name'], 'HRMS ID': row['HRMS ID'], 'IPAS No': row['IPAS No'], 
                    'Designation': row['Designation'], 'Leave Type': leave_type, 
                    'From Date': from_dt_str_full, 'To Date': sept_part_to_dt_full, 
                    'Leave Days': sept_days
                })

                # 2. October part
                oct_part_from_dt_full = '01/10/2025FN'
                oct_days = calculate_leave_days(oct_part_from_dt_full, to_dt_str_full)
                
                records.append({
                    'Name': row['Name'], 'HRMS ID': row['HRMS ID'], 'IPAS No': row['IPAS No'], 
                    'Designation': row['Designation'], 'Leave Type': leave_type, 
                    'From Date': oct_part_from_dt_full, 'To Date': to_dt_str_full, 
                    'Leave Days': oct_days
                })

            else:
                # No splitting required
                segment_days_calculated = calculate_leave_days(from_dt_str_full, to_dt_str_full)
                records.append({
                    'Name': row['Name'], 'HRMS ID': row['HRMS ID'], 'IPAS No': row['IPAS No'], 
                    'Designation': row['Designation'], 'Leave Type': leave_type, 
                    'From Date': from_dt_str_full, 'To Date': to_dt_str_full, 
                    'Leave Days': segment_days_calculated
                })

    return records

# --- 2. Streamlit Application ---

st.set_page_config(layout="wide", page_title="Leave Data Processor")

st.title(" लीव डेटा प्रोसेसर (Leave Data Processor) 🔄")
st.markdown("---")
st.info("यह टूल **Sanction Authority** को हटाता है, **LAP, LHAP, COL** लीव को **30/09/2025** की सीमा पर विभाजित करता है, और तारीखों से **FN/AN** हटाता है।")
st.markdown("---")


uploaded_file = st.file_uploader(
    "Excel (.xlsx) या CSV फ़ाइल अपलोड करें", 
    type=['xlsx', 'csv']
)
