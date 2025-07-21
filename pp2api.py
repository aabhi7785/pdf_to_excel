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

def extract(pattern, text, default="Not Found"):
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else default

def get_between(start, end, text):
    pattern = rf"{re.escape(start)}\s*:\s*(.*?)\s*{re.escape(end)}"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1).strip() if match else "Not Found"

def process_pdf(pdf_path):
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


@app.route('/upload-courier-boe', methods=['POST'])
def upload_courier_boe():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({'error': 'Only PDF files allowed'}), 400

    filename_base = os.path.splitext(secure_filename(file.filename))[0]

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        file.save(tmp.name)
        try:
            output_path, _ = process_pdf(tmp.name)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return send_file(output_path, as_attachment=True, download_name=f"{filename_base}.xlsx")

if __name__ == '__main__':
    app.run(debug=True, port=5001)
