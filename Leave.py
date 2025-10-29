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

    # Value: ordinal * 2 + (0 for FN, 1 for AN)
    value = date_obj.toordinal() * 2 + (0 if half_day_part == 'FN' else 1)
    return date_obj, value, half_day_part

def calculate_leave_days(from_dt_str_full, to_dt_str_full):
    """Calculates leave days based on FN/AN parts for a segment."""
    try:
        _, from_value, _ = get_half_day_value(from_dt_str_full)
        _, to_value, _ = get_half_day_value(to_dt_str_full)
        
        # Total half-days = (to_value - from_value) + 1 (inclusive count)
        total_half_days = (to_value - from_value) + 1
        return total_half_days / 2
    except ValueError:
        return np.nan

def parse_and_split_leave(row):
    """Parses leave details, splits records across the month boundary (30/09/2025 AN to 01/10/2025 FN)
    for LAP, LHAP, COL, and returns a list of dictionaries for each sanctioned segment."""
    leave_details = row['Leave Details']
    records = []
    
    # Define the splitting boundary (30th Sep 2025 Afternoon)
    try:
        sept_30_an_boundary_val = get_half_day_value('30/09/2025AN')[1]
    except ValueError:
        return records

    # Regex to find all leave segments: (LeaveType) (Days.D) days (DateRange (SanctionAuthority))
    leave_segments = re.findall(r'([A-Z]+)\s+([\d.]+)\s+days\s+\((.*?)\)', leave_details)

    for leave_type, total_days_str, date_ranges_str in leave_segments:
        # Split multiple date ranges within a single leave type
        date_authority_pairs = [s.strip() for s in re.split(r'\s*,\s*', date_ranges_str)]

        for pair in date_authority_pairs:
            # Pattern: (FromDateFN/AN)-(ToDateFN/AN) (AuthorityID) AuthorityName
            date_range_match = re.match(r'(.+?FN|.+?AN)-(.+?FN|.+?AN)\s+\((.+?)\)\s*(.*)', pair)

            if not date_range_match:
                continue

            from_dt_str_full, to_dt_str_full, authority_id, authority_name = date_range_match.groups()
            sanction_authority = f"({authority_id}) {authority_name.strip()}"
            
            try:
                # Extract half-day values
                _, from_value, _ = get_half_day_value(from_dt_str_full)
                _, to_value, _ = get_half_day_value(to_dt_str_full)
            except ValueError:
                continue

            # --- Splitting Logic (User Requirement) ---
            is_splittable = leave_type in ['LAP', 'LHAP', 'COL']
            
            if is_splittable and from_value <= sept_30_an_boundary_val and to_value > sept_30_an_boundary_val:
                # 1. September part (up to 30/09/2025 AN)
                sept_part_to_dt_full = '30/09/2025AN'
                sept_days = calculate_leave_days(from_dt_str_full, sept_part_to_dt_full)
                
                records.append({
                    'Name': row['Name'], 'HRMS ID': row['HRMS ID'], 'IPAS No': row['IPAS No'], 
                    'Designation': row['Designation'], 'Leave Type': leave_type, 
                    'From Date': from_dt_str_full, 'To Date': sept_part_to_dt_full, 
                    'Leave Days': sept_days, 'Sanction authority': sanction_authority
                })

                # 2. October part (from 01/10/2025 FN to end date)
                oct_part_from_dt_full = '01/10/2025FN'
                oct_days = calculate_leave_days(oct_part_from_dt_full, to_dt_str_full)
                
                records.append({
                    'Name': row['Name'], 'HRMS ID': row['HRMS ID'], 'IPAS No': row['IPAS No'], 
                    'Designation': row['Designation'], 'Leave Type': leave_type, 
                    'From Date': oct_part_from_dt_full, 'To Date': to_dt_str_full, 
                    'Leave Days': oct_days, 'Sanction authority': sanction_authority
                })

            else:
                # No splitting required
                segment_days_calculated = calculate_leave_days(from_dt_str_full, to_dt_str_full)
                records.append({
                    'Name': row['Name'], 'HRMS ID': row['HRMS ID'], 'IPAS No': row['IPAS No'], 
                    'Designation': row['Designation'], 'Leave Type': leave_type, 
                    'From Date': from_dt_str_full, 'To Date': to_dt_str_full, 
                    'Leave Days': segment_days_calculated, 'Sanction authority': sanction_authority
                })

    return records

# --- 2. Streamlit Application ---

st.set_page_config(layout="wide", page_title="Leave Data Processor")

st.title(" लीव डेटा प्रोसेसर (Leave Data Processor) 🔄")
st.markdown("---")
st.info("यह टूल **LAP, LHAP, और COL** लीव को मासिक सीमा (**30/09/2025**) पर स्वचालित रूप से विभाजित करता है और आउटपुट तारीखों से **FN/AN** हटा देता है।")
st.markdown("---")


uploaded_file = st.file_uploader(
    "Excel (.xlsx) या CSV फ़ाइल अपलोड करें", 
    type=['xlsx', 'csv']
)

if uploaded_file is not None:
    try:
        # Read the uploaded file
        if uploaded_file.name.endswith('.xlsx'):
            # Assuming the raw data starts from the second row (index 1) as per user's header
            raw_df = pd.read_excel(uploaded_file, header=1)
        else: # CSV file
            raw_df = pd.read_csv(uploaded_file, header=1)

        # Standardize column names based on user's header structure (Row 1 is the header)
        raw_df.columns = raw_df.columns.str.strip().str.replace(r'[^\w\s]', '', regex=True)
        raw_df = raw_df.rename(columns={raw_df.columns[0]: 'No'})
        
        # Check for required columns based on the input structure
        required_cols = ['HRMS ID', 'IPAS No', 'Name', 'Designation', 'Leave Details']
        if not all(col in raw_df.columns for col in required_cols):
            st.error("फ़ाइल में आवश्यक कॉलम नहीं हैं। कृपया सुनिश्चित करें कि शीर्षक पंक्ति (header) सही है।")
            st.stop()

        # Apply the parsing function and flatten the list of lists
        with st.spinner('डेटा प्रोसेस हो रहा है...'):
            parsed_results = raw_df.apply(parse_and_split_leave, axis=1)
            new_data = [item for sublist in parsed_results.tolist() for item in sublist]
            final_df = pd.DataFrame(new_data)
            
            # --- FINAL CLEANING AND FORMATTING ---
            
            # 1. Remove FN/AN from Dates (User Request)
            final_df['From Date'] = final_df['From Date'].astype(str).str.replace(r'(FN|AN)$', '', regex=True)
            final_df['To Date'] = final_df['To Date'].astype(str).str.replace(r'(FN|AN)$', '', regex=True)

            # 2. Drop rows with calculation issues and round Leave Days
            final_df.dropna(subset=['Leave Days'], inplace=True)
            final_df['Leave Days'] = final_df['Leave Days'].round(1)
            
            # 3. Select and reorder the final columns
            output_cols = [
                'Name', 'HRMS ID', 'IPAS No', 'Designation', 'Leave Type',
                'From Date', 'To Date', 'Leave Days', 'Sanction authority'
            ]
            final_df = final_df[output_cols]

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
            file_name='Structured_Leave_Report_Clean.csv',
            mime='text/csv',
        )

    except Exception as e:
        st.error(f"⚠️ डेटा प्रोसेसिंग में त्रुटि (Error during data processing): {e}")
        st.error("कृपया सुनिश्चित करें कि आपकी फ़ाइल का फॉर्मेट सही है और शीर्षक पंक्ति (header) 'HRMS ID, IPAS No, Name...' से शुरू होती है।")

st.sidebar.markdown("---")
st.sidebar.info(
    "**उपयोग के निर्देश:**\n"
    "1. `leave_data_processor_final.py` फ़ाइल को सेव करें।\n"
    "2. टर्मिनल में चलाएँ: `streamlit run leave_data_processor_final.py`\n"
    "3. ब्राउज़र में अपनी raw Excel/CSV फ़ाइल अपलोड करें।"
)
