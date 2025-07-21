import time
from selenium.webdriver.chrome.webdriver import WebDriver as Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
# === CONFIG ===
pdf_file_path = r"C:\Users\User\Downloads\Courier BOE XIV.pdf"  # <-- Replace with your PDF path
download_folder = r"C:\Users\User\Downloads"

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

# === HANDLE iframe IF PRESENT ===
try:
    iframe = wait.until(EC.presence_of_element_located((By.TAG_NAME, "iframe")))
    driver.switch_to.frame(iframe)
    print("✅ Switched to iframe.")
except:
    print("ℹ️ No iframe found or switching failed. Continuing...")

# === FIND FILE INPUT AND UPLOAD PDF ===
try:
    upload_input = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']")))
    upload_input.send_keys(pdf_file_path)
    print("✅ PDF uploaded.")
except Exception as e:
    print("❌ Failed to upload PDF:", e)
    driver.quit()
    exit()

# === CLICK CONVERT BUTTON ===
try:
    convert_button = wait.until(EC.element_to_be_clickable((By.ID, "convertButton")))
    convert_button.click()
    print("🔄 Conversion started.")
except Exception as e:
    print("❌ Failed to click Convert button:", e)
    driver.quit()
    exit()

# === WAIT FOR DOWNLOAD TO FINISH ===
print("⏳ Waiting for download to complete...")
time.sleep(15)  # Adjust if your file is large or internet is slow

# === DONE ===
print("✅ Done! Check your Downloads folder for the JSON file.")
driver.quit()
