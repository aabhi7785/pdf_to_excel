from selenium.webdriver.chrome.webdriver import WebDriver as Chrome


driver = Chrome()
driver.get("https://example.com")
print(driver.title)
driver.quit()
