import os
import time
import re
import json
import pandas as pd
from selenium.webdriver.chrome.webdriver import WebDriver as Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# === CONFIG ===
pdf_file_path = r"C:\Users\User\Downloads\New BOE VI.pdf"
download_folder = r"C:\Users\User\Downloads"
json_filename = "converted.json"  # expected download name

# === SETUP SELENIUM CHROME DRIVER ===
options = Options()
options.add_experimental_option("prefs", {
    "download.default_directory": download_folder,
    "download.prompt_for_download": False,
    "directory_upgrade": True
})
driver = Chrome(options=options)

# === OPEN PAGE ===
driver.get("https://ilovepdf4.com/pdf-to-json/")
wait = WebDriverWait(driver, 20)

# === HANDLE iframe (if present) ===
try:
    iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
    driver.switch_to.frame(iframe)
except:
    pass  # Continue even if no iframe

# === UPLOAD PDF ===
upload_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
upload_input.send_keys(pdf_file_path)

# === CLICK CONVERT ===
convert_btn = wait.until(EC.element_to_be_clickable((By.ID, "convertButton")))
convert_btn.click()

# === WAIT FOR DOWNLOAD ===
print("⏳ Converting and downloading JSON...")
time.sleep(20)

# === CLOSE BROWSER ===
driver.quit()

# === LOAD DOWNLOADED JSON ===
json_path = os.path.join(download_folder, json_filename)
if not os.path.exists(json_path):
    raise FileNotFoundError("JSON file not downloaded.")

with open(json_path, "r", encoding="utf-8") as f:
    data = json.load(f)

full_text = " ".join([entry["content"] for entry in data])

def extract(pattern, text, default="Not found"):
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else default

# === Metadata ===
challan_block = extract(r"Challan Date\s*(.*?)\s*DECLARATION", full_text)
challan_values = re.search(r"(\d+)\s+(\d+)\s+(\d+)\s+(\d{2}/\d{2}/\d{4})", challan_block)
tr6_challan_number = challan_values.group(2) if challan_values else "Not found"
total_amount = challan_values.group(3) if challan_values else "Not found"
challan_date = challan_values.group(4) if challan_values else "Not found"

metadata = {
    "CBEXIV Number": extract(r"CBEXIV Number\s*:\s*(.*?)\s", full_text),
    "Importer Name": extract(r"Import Export Branch Code\s*:\s*.*?Name\s*:\s*(.*?)\s+Address", full_text),
    "Importer Address": extract(r"Import Export Branch Code\s*:\s*.*?Address\s*:\s*(.*?)\s*Category Of Importer", full_text),
    "Supplier Name": extract(r"SUPPLIER DETAILS\s.*?Name\s*:\s*(.*?)\s+Address", full_text),
    "Supplier Address": extract(r"SUPPLIER DETAILS\s.*?Address\s*:\s*(.*?)\s*IF SUPPLIER IS NOT THE SELLER", full_text),
    "BOE Date": extract(r"BOE Date\s*:\s*(.*?)\s", full_text),
    "Country of Origin": extract(r"Country of Origin\s*:\s*(.*?)\s", full_text),
    "Country of Consignment": extract(r"Country of Consignment\s*:\s*(.*?)\s", full_text),
    "House Airway Bill (HAWB) Number": extract(r"House Airway Bill \(HAWB\) Number\s*:\s*(.*?)\s", full_text),
    "Master Airway Bill (MAWB) Number": extract(r"Master Airway Bill \(MAWB\) Number\s*:\s*(.*?)\s", full_text),
    "Interest Amount": extract(r"Interest Amount\s*:\s*(.*?)\s", full_text),
    "Invoice Number": extract(r"Invoice Number\s*:\s*(.*?)\s", full_text),
    "Date of Invoice": extract(r"Date of Invoice\s*:\s*(.*?)\s", full_text),
    "Invoice Value": extract(r"Invoice Value\s*:\s*(.*?)\s", full_text),
    "Currency": extract(r"Currency\s*:\s*(USD|INR|EUR|[A-Z]{3})", full_text),
    "TR-6 Challan Number": tr6_challan_number,
    "Total Amount": total_amount,
    "Challan Date": challan_date
}

# === Freight & Insurance ===
freight_content = next((entry["content"] for entry in data if "Currency Freight" in entry["content"]), "")
freight_match = re.search(r"Currency Freight\s*:\s*(.*?)\s*Loading", freight_content, re.DOTALL)
if freight_match:
    section = freight_match.group(1).strip()
    values = re.findall(r"(\d+\.?\d*)\s+(\d+\.?\d*)\s+([A-Z]{3})\s+Insurance\s*:\s*(\d+\.?\d*)\s+(\d+\.?\d*)\s+([A-Z]{3})", section)
    if values:
        freight_rate, freight_amount, freight_currency, insurance_rate, insurance_amount, insurance_currency = values[0]
        metadata.update({
            "freight_rate": freight_rate,
            "freight_amount": freight_amount,
            "freight_currency": freight_currency,
            "insurance_rate": insurance_rate,
            "insurance_amount": insurance_amount,
            "insurance_currency": insurance_currency
        })

# === Items ===
item_pattern = re.findall(
    r"Item Description\s*:\s*(.*?)\s*General Description\s*:\s*"
    r"Currency for Unit Price\s*:\s*(.*?)\s*"
    r"Unit Price\s*:\s*(.*?)\s*"
    r"Unit of Measure\s*:\s*(.*?)\s*"
    r"Quantity\s*:\s*(.*?)\s*"
    r"Rate Of Exchange\s*:\s*(.*?)\s*Accessories"
    r".*?Assessable Value\s*:\s*(\d+\.?\d*)",
    full_text, re.DOTALL
)
item_columns = [
    "Item Description", "Currency for Unit Price", "Unit Price",
    "Unit of Measure", "Quantity", "Rate Of Exchange", "Assessable Value"
]
df_items = pd.DataFrame(item_pattern, columns=item_columns)
df_items = df_items.applymap(lambda x: x.strip() if isinstance(x, str) else x)

# === Duties ===
duty_pattern = re.compile(
    r"(BCD|AIDC|SW SRCHRG|IGST|CMPNSTRY)\s+"
    r"(\d+(?:\.\d+)?)\s+"
    r"(\d+(?:\.\d+)?)\s+"
    r"(\d+(?:\.\d+)?)\s+"
    r"(\d+(?:\.\d+)?)", re.IGNORECASE
)

matches = []
for entry in data:
    matches.extend(duty_pattern.findall(entry["content"]))

duty_records = []
for i in range(0, len(matches), 5):
    group = matches[i:i+5]
    row = {}
    for duty, ad, sr, fg, amt in group:
        key = duty.lower().replace(" ", "_")
        row[f"{key}_ad_valorem"] = float(ad)
        row[f"{key}_specific_rate"] = float(sr)
        row[f"{key}_duty_forgone"] = float(fg)
        row[f"{key}_duty_amount"] = float(amt)
    duty_records.append(row)

df_duties = pd.DataFrame(duty_records)

# === Merge All Data ===
final_data = []
row_count = min(len(df_items), len(df_duties))
for i in range(row_count):
    combined = {**metadata, **df_items.iloc[i].to_dict(), **df_duties.iloc[i].to_dict()}
    final_data.append(combined)

# === Save to Excel ===
df_final = pd.DataFrame(final_data)
df_final.to_excel("final_complete_output.xlsx", index=False)
print("✅ Final Excel file 'final_complete_output.xlsx' created.")
