from flask import Flask, request, jsonify, send_file, render_template
import os, re, json, tempfile, time
import pandas as pd
from werkzeug.utils import secure_filename
from selenium.webdriver.chrome.webdriver import WebDriver as Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

# ===================== COURIER PDF PROCESSING (from pp2api.py) =====================
def extract(pattern, text, default="Not Found"):
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else default

def get_between(start, end, text):
    pattern = rf"{re.escape(start)}\s*:\s*(.*?)\s*{re.escape(end)}"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else "Not Found"

def process_courier_pdf(pdf_path):
    pdf_name_only = os.path.splitext(os.path.basename(pdf_path))[0]
    download_folder = os.path.dirname(pdf_path)
    json_path = os.path.join(download_folder, "converted.json")

    options = Options()
    options.add_experimental_option("prefs", {
        "download.default_directory": download_folder,
        "download.prompt_for_download": False,
        "directory_upgrade": True
    })
    driver = Chrome(options=options)
    driver.get("https://ilovepdf4.com/pdf-to-json/")
    wait = WebDriverWait(driver, 20)

    try:
        iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
        driver.switch_to.frame(iframe)
    except:
        pass

    upload_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
    upload_input.send_keys(pdf_path)

    convert_btn = wait.until(EC.element_to_be_clickable((By.ID, "convertButton")))
    convert_btn.click()

    for _ in range(30):
        if os.path.exists(json_path):
            break
        time.sleep(1)

    driver.quit()

    if not os.path.exists(json_path):
        raise FileNotFoundError("Converted JSON file not found.")

    with open(json_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    os.remove(json_path)

    full_text = " ".join([entry["content"] for entry in raw_data if entry.get("content")])

    challan_match = re.search(r"TR-6 Challan Number\s+Total Amount\s+Challan Date\s+(.*?)\s+DECLARATION", full_text, re.DOTALL)
    tr6_number = total_amt = challan_date = "Not Found"
    if challan_match:
        values = re.search(r"(\d+)\s+(\d+)\s+(\d{2}/\d{2}/\d{4})", challan_match.group(1))
        if values:
            tr6_number, total_amt, challan_date = values.groups()

    metadata = {
        "CBE Number": extract(r"CBE-XIII Number\s*([A-Z0-9_/-]+)", full_text),
        "HAWB Number": extract(r"HAWB Number\s*:\s*(\S+)", full_text),
        "Name of Consignor": get_between("Name of Consignor", "Address of Consignor", full_text),
        "Address of Consignor": get_between("Address of Consignor", "Name of Consignee", full_text),
        "Name of Consignee": get_between("Name of Consignee", "Address of Consignee", full_text),
        "Address of Consignee": get_between("Address of Consignee", "Import Export Code", full_text),
        "Interest Amount": extract(r"Interest Amount\s*:\s*(\S+)", full_text),
        "TR-6 Challan Number": tr6_number,
        "Total Amount": total_amt,
        "Challan Date": challan_date
    }

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
        items.append(item)

    duty_pattern = re.compile(
        r"(BCD|AIDC|SW SRCHRG|IGST|CMPNSTRY)\s+"
        r"(\d+(?:\.\d+)?)\s+"
        r"(\d+(?:\.\d+)?)\s+"
        r"(\d+(?:\.\d+)?)\s+"
        r"(\d+(?:\.\d+)?)",
        re.IGNORECASE
    )
    matches = duty_pattern.findall(full_text)

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

    final_data = []
    row_count = min(len(items), len(duty_records))
    for i in range(row_count):
        row = {
            **metadata,
            **items[i],
            **duty_records[i],
            "BE Type": "",
            "CB Name": "",
            "Total freight": "",
            "Total insurance": "",
            "Incoterms": "",
            "Penalty Amount": "",
            "Fine Amount": ""
        }
        final_data.append(row)

    df = pd.DataFrame(final_data)
    output_file = os.path.join(download_folder, f"{pdf_name_only}.xlsx")
    df.to_excel(output_file, index=False)
    return output_file, pdf_name_only

# ===================== BOE PDF PROCESSING (from ttapi.py) =====================

def extract(pattern, text, default="Not found"):
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else default

def process_boe_pdf(pdf_path):
    pdf_name_only = os.path.splitext(os.path.basename(pdf_path))[0]
    download_folder = os.path.dirname(pdf_path)
    json_filename = "converted.json"
    json_path = os.path.join(download_folder, json_filename)

    options = Options()
    options.add_experimental_option("prefs", {
        "download.default_directory": download_folder,
        "download.prompt_for_download": False,
        "directory_upgrade": True
    })
    driver = Chrome(options=options)
    driver.get("https://ilovepdf4.com/pdf-to-json/")
    wait = WebDriverWait(driver, 20)
    try:
        iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
        driver.switch_to.frame(iframe)
    except:
        pass

    upload_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
    upload_input.send_keys(pdf_path)
    convert_btn = wait.until(EC.element_to_be_clickable((By.ID, "convertButton")))
    convert_btn.click()

    for _ in range(30):
        if os.path.exists(json_path):
            break
        time.sleep(1)

    driver.quit()
    if not os.path.exists(json_path):
        raise FileNotFoundError("Converted JSON not found.")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    os.remove(json_path)

    full_text = " ".join([entry["content"] for entry in data])
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
    df_items = pd.DataFrame(item_pattern, columns=[
        "Item Description", "Currency for Unit Price", "Unit Price",
        "Unit of Measure", "Quantity", "Rate Of Exchange", "Assessable Value"
    ])
    for col in df_items.select_dtypes(include=['object']).columns:
        df_items[col] = df_items[col].str.strip()

    manufacturer_matches = re.findall(r"Name of Manufacturer\s*:\s*(.*?)\s*Brand\s*:", full_text, re.DOTALL)
    manufacturer_column = [m.strip() for m in manufacturer_matches[:len(df_items)]]
    df_items["Name of Manufacturer"] = manufacturer_column + [""] * (len(df_items) - len(manufacturer_column))

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

    final_data = []
    row_count = min(len(df_items), len(df_duties))
    for i in range(row_count):
        combined = {
            **metadata,
            **df_items.iloc[i].to_dict(),
            **df_duties.iloc[i].to_dict(),
            "BE Type": "",
            "CB Name": "",
            "Total freight": "",
            "Total insurance": "",
            "Incoterms": "",
            "penalty_amount": "",
            "fine_amount": ""
        }
        final_data.append(combined)

    output_path = os.path.join(download_folder, f"{pdf_name_only}_converted.xlsx")
    pd.DataFrame(final_data).to_excel(output_path, index=False)
    return output_path



# ===================== UPLOAD ENDPOINT =====================
@app.route('/upload-pdf', methods=['POST'])
def upload_pdf():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({'error': 'Only PDF files allowed'}), 400

    doc_type = request.form.get('docType', 'courier')  # default to courier if not provided
    filename_base = os.path.splitext(secure_filename(file.filename))[0]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        file.save(tmp.name)
        try:
            if doc_type == "courier":
                output_path, _ = process_courier_pdf(tmp.name)
            elif doc_type == "boe":
                output_path = process_boe_pdf(tmp.name)  # Only one value returned
            else:
                return jsonify({'error': 'Invalid document type'}), 400
        except Exception as e:
            print(f"Error during PDF processing: {e}")
            return jsonify({'error': str(e)}), 500

    try:
        return send_file(output_path, as_attachment=True, download_name=f"{filename_base}.xlsx")
    except Exception as e:
        print(f"Error sending file: {e}")
        return jsonify({'error': 'Failed to send the Excel file.'}), 500



if __name__ == '__main__':
    app.run(debug=True, port=5001)