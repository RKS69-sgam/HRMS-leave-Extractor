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
    """Parses leave details, splits records across the month boundary (30/09/2025 AN to 01/10/2025 FN)"""
    leave_details = str(row['Leave Details'])
    records = []
    
    try:
        sept_30_an_boundary_val = get_half_day_value('30/09/2025AN')[1]
    except ValueError:
        return records

    # Regex is robust for the most common errors (extra brackets, etc.)
    leave_segments = re.findall(r'([A-Z]+)\s+([\d.]+)\s+days\s+\((.*?)\)?', leave_details)

    for leave_type, total_days_str, date_ranges_str in leave_segments:
        # Pattern to find each complete date group: DATE_FN/AN - DATE_FN/AN (Anything_Inside_Brackets)
        date_groups = re.findall(r'(\d{2}/\d{2}/\d{4}FN|\d{2}/\d{2}/\d{4}AN)-(\d{2}/\d{2}/\d{4}FN|\d{2}/\d{2}/\d{4}AN)\s*\(([^)]*)\)', date_ranges_str)

        for from_dt_str_full, to_dt_str_full, authority_raw in date_groups: 
            
            try:
                _, from_value, _ = get_half_day_value(from_dt_str_full)
                _, to_value, _ = get_half_day_value(to_dt_str_full)
            except ValueError:
                continue

            # --- Splitting Logic (User Requirement) ---
            is_splittable = leave_type in ['LAP', 'LHAP', 'COL']
            
            common_data = {
                'Name': row['Name'], 'HRMS ID': row['HRMS ID'], 'IPAS No': row['IPAS No'], 
                'Designation': row['Designation'], 'Leave Type': leave_type
            }

            if is_splittable and from_value <= sept_30_an_boundary_val and to_value > sept_30_an_boundary_val:
                # 1. September part
                sept_part_to_dt_full = '30/09/2025AN'
                sept_days = calculate_leave_days(from_dt_str_full, sept_part_to_dt_full)
                
                records.append({
                    **common_data, 
                    'From Date': from_dt_str_full, 'To Date': sept_part_to_dt_full, 
                    'Leave Days': sept_days
                })

                # 2. October part
                oct_part_from_dt_full = '01/10/2025FN'
                oct_days = calculate_leave_days(oct_part_from_dt_full, to_dt_str_full)
                
                records.append({
                    **common_data, 
                    'From Date': oct_part_from_dt_full, 'To Date': to_dt_str_full, 
                    'Leave Days': oct_days
                })

            else:
                # No splitting required
                segment_days_calculated = calculate_leave_days(from_dt_str_full, to_dt_str_full)
                records.append({
                    **common_data, 
                    'From Date': from_dt_str_full, 'To Date': to_dt_str_full, 
                    'Leave Days': segment_days_calculated
                })

    return records

# --- 2. Streamlit Application ---

st.set_page_config(layout="wide", page_title="Leave Data Processor")

st.title(" लीव डेटा प्रोसेसर (Leave Data Processor) 🔄")
st.markdown("---")
st.info("यह नया वर्ज़न पहली पंक्ति (row 0) को हेडर के रूप में उपयोग करता है और डेटा को इंडेक्स द्वारा मैप करता है।")
st.markdown("---")


uploaded_file = st.file_uploader(
    "Excel (.xlsx) या CSV फ़ाइल अपलोड करें", 
    type=['xlsx', 'csv']
)

if uploaded_file is not None:
    try:
        # ** FIX: Read header=0 and then rename columns by index position **
        if uploaded_file.name.endswith('.xlsx'):
            raw_df = pd.read_excel(uploaded_file, header=0)
        else:
            # For CSV, we read header=0
            raw_df = pd.read_csv(uploaded_file, header=0)
        
        # We need to map the data columns by their index position (0-based)
        # Assuming the structure is: [Col 0] [Col 1] [Col 2] [Col 3] [Col 4] [Col 5] [Col 6]
        
        # Clean up column names by index, as they are likely 'Unnamed: X' or junk
        raw_df.columns = [f'Col_{i}' for i in range(len(raw_df.columns))]

        # Map the required columns by their known index position:
        required_col_map = {
            'HRMS ID': 'Col_1', 
            'IPAS No': 'Col_2', 
            'Name': 'Col_3', 
            'Designation': 'Col_5', 
            'Leave Details': 'Col_6'
        }
        
        # Check if all required columns indices are actually present
        for col_name in required_col_map.values():
            if col_name not in raw_df.columns:
                 st.error(f"❌ त्रुटि: अपेक्षित डेटा कॉलम {col_name} फ़ाइल में नहीं मिला।")
                 st.stop()

        # Rename columns to standard names for processing
        raw_df = raw_df.rename(columns={v: k for k, v in required_col_map.items()})
        
        # Drop the first row (index 0) of the loaded DataFrame because it contains the *actual* header names, not data.
        # This is a key step when forcing header=0 on this specific file format.
        raw_df = raw_df.iloc[1:].reset_index(drop=True)

        
        # Apply the parsing function and flatten the list of lists
        with st.spinner('डेटा प्रोसेस हो रहा है...'):
            raw_df = raw_df.dropna(subset=['Leave Details']).reset_index(drop=True)

            parsed_results = raw_df.apply(parse_and_split_leave, axis=1)
            new_data = [item for sublist in parsed_results.tolist() for item in sublist]
            
            # DEFINING FINAL COLUMNS (WITHOUT Sanction authority)
            output_cols_with_keys = [
                'Name', 'HRMS ID', 'IPAS No', 'Designation', 'Leave Type',
                'From Date', 'To Date', 'Leave Days'
            ]
            final_df = pd.DataFrame(new_data, columns=output_cols_with_keys)
            
            # --- FINAL CLEANING AND FORMATTING ---
            
            final_df['Leave Days'] = pd.to_numeric(final_df['Leave Days'], errors='coerce')

            # 1. Remove FN/AN from Dates (User Request)
            final_df['From Date'] = final_df['From Date'].astype(str).str.replace(r'(FN|AN)$', '', regex=True)
            final_df['To Date'] = final_df['To Date'].astype(str).str.replace(r'(FN|AN)$', '', regex=True)

            # 2. Drop rows with NaN in critical columns (parsing/calculation errors)
            final_df.dropna(subset=['Leave Days', 'From Date', 'To Date'], inplace=True)
            final_df['Leave Days'] = final_df['Leave Days'].round(1)
            
            # 3. Select and reorder the final columns
            final_df = final_df[output_cols_with_keys]

        st.success(f"✅ डेटा सफलतापूर्वक प्रोसेस किया गया! कुल **{len(final_df)}** रिकॉर्ड्स तैयार हैं।")
        st.markdown("---")

        st.subheader("📊 संरचित लीव डेटा का पूर्वावलोकन (Preview of Structured Leave Data)")
        st.dataframe(final_df, height=300)

        # --- Download Button ---
        @st.cache_data
        def convert_df_to_csv(df):
            return df.to_csv(index=False).encode('utf-8')

        csv = convert_df_to_csv(final_df)

        st.download_button(
            label="⬇️ संरचित डेटा CSV फ़ाइल डाउनलोड करें",
            data=csv,
            file_name='Structured_Leave_Report_Clean_Final_V3.csv',
            mime='text/csv',
        )

    except Exception as e:
        st.error(f"⚠️ डेटा प्रोसेसिंग में एक अप्रत्याशित त्रुटि आई (An unexpected error occurred during data processing): {e}")
        st.error("कृपया सुनिश्चित करें कि आपकी फ़ाइल का फॉर्मेट सही है और शीर्षक पंक्ति (header) आपकी कच्ची फ़ाइल में **पहली पंक्ति** में है।")

st.sidebar.markdown("---")
st.sidebar.info(
    "**उपयोग के निर्देश:**\n"
    "1. यह नया कोड कॉपी करें और **`leave_data_processor_final.py`** फ़ाइल को बदल दें।\n"
    "2. टर्मिनल में चलाएँ: `streamlit run leave_data_processor_final.py`\n"
    "3. ब्राउज़र में अपनी raw Excel/CSV फ़ाइल अपलोड करें।"
)
