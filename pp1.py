import os
import re
import json
import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# === CONFIGURATION ===
pdf_path = r"C:\Users\User\Downloads\New BOE XIII.pdf"  # Set your PDF path here
download_dir = os.path.dirname(pdf_path)
pdf_name = os.path.splitext(os.path.basename(pdf_path))[0]
json_path = os.path.join(download_dir, "converted.json")
output_excel = os.path.join(download_dir, f"{pdf_name}.xlsx")

# === SELENIUM AUTOMATION: Convert PDF to JSON ===
options = Options()
options.add_experimental_option("prefs", {
    "download.default_directory": download_dir,
    "download.prompt_for_download": False,
    "directory_upgrade": True
})
driver = webdriver.Chrome(options=options)

driver.get("https://ilovepdf4.com/pdf-to-json/")
wait = WebDriverWait(driver, 20)

try:
    iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
    driver.switch_to.frame(iframe)
except:
    pass

upload_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
upload_input.send_keys(pdf_path)

convert_button = wait.until(EC.element_to_be_clickable((By.ID, "convertButton")))
convert_button.click()

print("⏳ Waiting for conversion and download...")
for _ in range(30):
    if os.path.exists(json_path):
        break
    time.sleep(1)

driver.quit()

if not os.path.exists(json_path):
    raise FileNotFoundError("Converted JSON file not found.")

# === LOAD JSON ===
with open(json_path, "r", encoding="utf-8") as f:
    pages = json.load(f)
os.remove(json_path)  # Clean up the downloaded JSON

full_text = " ".join([p["content"] for p in pages])

# === METADATA EXTRACTION ===
def extract(pattern, text=full_text, default="Not Found"):
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else default

def get_between(start, end, text=full_text):
    pattern = rf"{re.escape(start)}\s*:\s*(.*?)\s*{re.escape(end)}"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else "Not Found"

# Extract TR-6 Challan block
challan_match = re.search(r"TR-6 Challan Number\s+Total Amount\s+Challan Date\s+(.*?)\s+DECLARATION", full_text, re.DOTALL)
tr6_number = total_amt = challan_date = "Not Found"
if challan_match:
    values = re.search(r"(\d+)\s+(\d+)\s+(\d{2}/\d{2}/\d{4})", challan_match.group(1))
    if values:
        tr6_number, total_amt, challan_date = values.groups()

metadata = {
    "CBE Number": extract(r"CBE-XIII Number\s*([A-Z0-9_/-]+)"),
    "HAWB Number": extract(r"HAWB Number\s*:\s*(\S+)"),
    "Name of Consignor": get_between("Name of Consignor", "Address of Consignor"),
    "Address of Consignor": get_between("Address of Consignor", "Name of Consignee"),
    "Name of Consignee": get_between("Name of Consignee", "Address of Consignee"),
    "Address of Consignee": get_between("Address of Consignee", "Import Export Code"),
    "Interest Amount": extract(r"Interest Amount\s*:\s*(\S+)"),
    "TR-6 Challan Number": tr6_number,
    "Total Amount": total_amt,
    "Challan Date": challan_date
}

# === ITEM EXTRACTION ===
item_blocks = re.findall(r"ITEM\s*:(.*?)NOTIFICATION USED FOR THE ITEM", full_text, re.DOTALL)
items = []
for block in item_blocks:
    item = {
        "Country of Origin": extract(r"Country of Origin\s*:\s*(.*?)\s", block),
        "Description of Goods": get_between("Description of Goods", "Name of Manufacturer", block),
        "Quantity": extract(r"Quantity\s*:\s*(\d+)", block),
        "Invoice Value": extract(r"Invoice Value\s*:\s*(\d+\.?\d*)", block),
        "Unit Price": extract(r"Unit Price\s*:\s*(\d+\.?\d*)", block),
        "Currency": extract(r"Currency of Unit Price\s*:\s*(\w+)", block),
        "Rate of Exchange": extract(r"Rate of Exchange\s*:\s*(\d+\.?\d*)", block),
        "Assessable Value": extract(r"Assessable Value\s*:\s*(\d+\.?\d*)", block),
        "Insurance": extract(r"Insurance\s*:\s*(\d+\.?\d*)", block),
        "Freight": extract(r"Freight\s*:\s*(\d+\.?\d*)", block),
        "Name of Manufacturer": get_between("Name of Manufacturer", "Address of Manufacturer", block)
    }

    # Duties
    duties = re.findall(r"(BCD|AIDC|SW Srchrg|IGST|CMPNSTRY)\s+(\d+\.?\d*)\s+(\d+\.?\d*)\s+(\d+\.?\d*)\s+(\d+\.?\d*)", block)
    for duty in duties:
        key = duty[0].strip().lower().replace(" ", "_")
        item[f"{key}_ad_valorem"] = float(duty[1])
        item[f"{key}_specific_rate"] = float(duty[2])
        item[f"{key}_duty_forgone"] = float(duty[3])
        item[f"{key}_duty_amount"] = float(duty[4])
    items.append(item)

# === Merge Everything + Add Extra Empty Columns ===
final_data = []
for item in items:
    combined = {
        **metadata,
        **item,
        "BE Type": "",
        "CB Name": "",
        "Total freight": "",
        "Total insurance": "",
        "Incoterms": "",
        "Penalty Amount": "",
        "Fine Amount": ""
    }
    final_data.append(combined)

# === Export ===
df = pd.DataFrame(final_data)
df.to_excel(output_excel, index=False)
print(f"✅ Excel saved at: {output_excel}")
