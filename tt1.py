import time
from selenium.webdriver.chrome.webdriver import WebDriver as Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

# === CONFIGURATION ===
pdf_file_path = r"C:\Users\User\Downloads\converted.json"

# === SETUP SELENIUM ===
options = Options()
options.add_experimental_option("prefs", {
    "download.default_directory": r"C:\Users\User\Downloads",  # Change to your desired download path
    "download.prompt_for_download": False,
    "directory_upgrade": True
})
driver = Chrome(options=options)

# === STEP 1: Load the website ===
driver.get("https://ilovepdf4.com/pdf-to-json/")

# === STEP 2: Upload the PDF file ===
upload_input = driver.find_element(By.ID, "pdfupload")
upload_input.send_keys(pdf_file_path)

# === STEP 3: Wait and Click Convert Button ===
time.sleep(2)
convert_button = driver.find_element(By.ID, "convert-btn")
convert_button.click()

# === STEP 4: Wait for download link ===
time.sleep(15)  # Wait for file to process and download to start

# === Done ===
print("✅ PDF uploaded and conversion triggered. Check your Downloads folder.")
driver.quit()
