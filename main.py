import os
import time
import logging
import csv
import traceback
from glob import glob
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from dotenv import load_dotenv
from retrying import retry
from tabulate import tabulate

from run_support import (
    PROGRESS_FILENAME,
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    consolidate_csvs,
    files_for_consolidation,
    load_progress,
    run_batch,
    summarise_results,
)

# Setup logging with detailed format
logging.basicConfig(
    level=logging.INFO,
    filename='icici_extract.log',
    format='%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
)

load_dotenv()
USERNAME = os.getenv('ICICI_USERNAME')
PASSWORD = os.getenv('ICICI_PASSWORD')
SUB_ACCOUNTS = [
    'IN303028-76957800-6500081466-NRE',
    'IN303028-76957818-7500062485-NRO',
    'IN303028-76957826-7510072528-NPNRO'
]

# Accounts that additionally download My Portfolio and Orderbook.
EXTRA_DATA_ACCOUNTS = {'IN303028-76957826-7510072528-NPNRO'}

# Configuration
CONFIG = {
    'download_base_dir': os.path.abspath("downloads"),
    'tradebook_period': '1 Week',  # Options: '1 Week', '1 Month', etc.
    'max_download_wait': 30,  # Seconds to wait for downloads
    'consolidate_output': True,  # Combine CSVs for each data type
    'login_timeout': 180,  # Timeout for login and OTP handling (3 minutes)
    'switch_timeout': 60,  # Timeout for account switching
}

# Browser handles.  They are created by init_driver() just before the first
# account is processed, so importing this module (and running the resume
# logic/tests) does not launch Chrome.
driver = None
wait = None


def init_driver():
    """Create the WebDriver and the shared WebDriverWait on first use."""
    global driver, wait
    if driver is not None:
        return
    # Imported here so that importing main.py (resume logic, tests) does not
    # require the ChromeDriver manager to be present or to hit the network.
    from webdriver_manager.chrome import ChromeDriverManager

    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_experimental_option("prefs", {
        "download.default_directory": CONFIG['download_base_dir'],
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "profile.default_content_setting_values.notifications": 2,
    })
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    wait = WebDriverWait(driver, 30)
    logging.info("WebDriver initialized")
    return driver

def get_account_download_dir(account_id):
    """Get the download directory for a specific account."""
    account_dir = os.path.join(CONFIG['download_base_dir'], account_id)
    os.makedirs(account_dir, exist_ok=True)
    return account_dir

def csv_search_dirs(account_id):
    """Directories where a browser download may land.

    Chrome is configured with the base download directory, while files are
    filed per account.  Both are searched so a download is picked up
    wherever Chrome writes it, then moved into the account directory.
    """
    return [get_account_download_dir(account_id), CONFIG['download_base_dir']]

def csv_snapshot(account_id):
    """CSV file names already present before a download is triggered.

    Used to distinguish a download started by this run from a file left
    behind by an earlier run.
    """
    return {
        os.path.basename(path)
        for directory in csv_search_dirs(account_id)
        for path in glob(os.path.join(directory, "*.csv"))
    }

def wait_for_download(account_id, partial_name, timeout=30, before=None):
    """Wait for a new file matching ``partial_name`` to finish downloading."""
    before = set(before or ())
    start_time = time.time()
    while time.time() - start_time < timeout:
        candidates = [
            path
            for directory in csv_search_dirs(account_id)
            for path in glob(os.path.join(directory, f"*{partial_name}*.csv"))
            if os.path.basename(path) not in before
            and not path.lower().endswith(('.crdownload', '.part', '.tmp'))
        ]
        if candidates:
            return max(candidates, key=os.path.getmtime)
        time.sleep(1)
    raise TimeoutError(f"No new file matching {partial_name} found in {timeout} seconds for account {account_id}")

def rename_downloaded_file(original_path, account_id, data_type):
    """Rename downloaded file to include account ID and data type."""
    download_dir = get_account_download_dir(account_id)
    new_name = os.path.join(download_dir, f"{account_id}_{data_type}_{int(time.time())}.csv")
    os.rename(original_path, new_name)
    logging.info(f"Renamed {original_path} to {new_name}")
    return new_name

def login():
    """Log in to ICICI Direct, allowing manual OTP entry on the website."""
    logging.info("Starting login")
    try:
        driver.get("https://secure.icicidirect.com/customer/login")
        logging.info(f"Navigated to login page. Title: {driver.title}, URL: {driver.current_url}")
        driver.set_window_size(1536, 816)
        wait.until(EC.presence_of_element_located((By.ID, "txtu"))).send_keys(USERNAME)
        wait.until(EC.presence_of_element_located((By.ID, "txtp"))).send_keys(PASSWORD)
        wait.until(EC.element_to_be_clickable((By.ID, "btnlogin"))).click()
        logging.info("Login button clicked")

        # Wait for either OTP page or dashboard
        start_time = time.time()
        otp_required = False
        while time.time() - start_time < CONFIG['login_timeout']:
            try:
                # Check for OTP field
                otp_field_locators = [
                    (By.ID, "higootp"),
                    (By.XPATH, "//input[@type='text' and contains(@id, 'otp')]")
                ]
                for locator in otp_field_locators:
                    try:
                        wait.until(EC.presence_of_element_located(locator))
                        otp_required = True
                        logging.info("OTP page detected. Waiting for manual OTP entry on website.")
                        break
                    except:
                        continue
                # Check for dashboard
                dashboard_locators = [
                    (By.CSS_SELECTOR, ".mrl10"),
                    (By.XPATH, "//a[@id='dropdownMenuButton1']")
                ]
                for locator in dashboard_locators:
                    try:
                        wait.until(EC.presence_of_element_located(locator))
                        logging.info(f"Dashboard detected. Title: {driver.title}, URL: {driver.current_url}")
                        return
                    except:
                        continue
                if otp_required:
                    logging.info(f"Still on OTP page. Title: {driver.title}, URL: {driver.current_url}")
                else:
                    logging.info(f"Checking for OTP or dashboard. Title: {driver.title}, URL: {driver.current_url}")
                time.sleep(2)  # Poll every 2 seconds
            except Exception as e:
                logging.warning(f"Login check failed: {str(e)}")
                time.sleep(2)
        raise TimeoutError(f"Login failed: Did not reach dashboard within {CONFIG['login_timeout']} seconds")
    except Exception as e:
        logging.error(f"Login failed: {str(e)}\n{traceback.format_exc()}")
        raise

@retry(stop_max_attempt_number=3, wait_fixed=2000)
def switch_account(account_id):
    """Switch to the specified sub-account with retry logic."""
    logging.info(f"Switching to account {account_id}")
    try:
        # Click account button
        account_btn_locators = [
            (By.CSS_SELECTOR, ".mrl10"),
            (By.XPATH, "//a[@id='dropdownMenuButton1']/span[2]"),
            (By.XPATH, "//a[contains(@class, 'dropdown-toggle')]")
        ]
        account_btn = None
        for locator in account_btn_locators:
            try:
                account_btn = wait.until(EC.element_to_be_clickable(locator))
                logging.info(f"Found account button with locator {locator}")
                ActionChains(driver).move_to_element(account_btn).click().perform()
                logging.info(f"Clicked account button. Title: {driver.title}, URL: {driver.current_url}")
                break
            except:
                logging.warning(f"Failed to find account button with locator {locator}")
                continue
        if not account_btn:
            raise Exception("Account switch button not found")

        # Click account option (e.g., 'Select Account')
        account_option_locators = [
            (By.CSS_SELECTOR, ".p-2:nth-child(2) .fw-bold"),
            (By.XPATH, "//div[@id='pnlHeadLogin']//li[2]/div/div[2]"),
            (By.XPATH, "//li[contains(@class, 'dropdown-item')]//div[contains(text(), 'Select Account')]")
        ]
        account_option = None
        for locator in account_option_locators:
            try:
                account_option = wait.until(EC.element_to_be_clickable(locator))
                logging.info(f"Found account option with locator {locator}")
                ActionChains(driver).move_to_element(account_option).click().perform()
                logging.info(f"Clicked account option. Title: {driver.title}, URL: {driver.current_url}")
                break
            except:
                logging.warning(f"Failed to find account option with locator {locator}")
                continue
        if not account_option:
            raise Exception("Account option not found")

        # Select account from dropdown
        dropdown = wait.until(EC.presence_of_element_located((By.ID, "drpAccount")))
        select = Select(dropdown)
        options = [option.get_attribute("value") for option in select.options]
        logging.info(f"Available account IDs: {options}")

        # Try exact match
        if account_id in options:
            select.select_by_value(account_id)
            logging.info(f"Selected account {account_id} by exact match")
        else:
            # Try partial match
            for option in options:
                if account_id.split('-')[-2] in option:  # Match middle part (e.g., 6500081466)
                    select.select_by_value(option)
                    logging.info(f"Selected account {option} by partial match for {account_id}")
                    break
            else:
                raise ValueError(f"Account ID {account_id} not found in dropdown options: {options}")

        # Click confirm button
        confirm_btn_locators = [
            (By.CSS_SELECTOR, ".btn-short"),
            (By.XPATH, "//div[@id='pnlSelMDP']/div[2]/input"),
            (By.XPATH, "//input[@type='button' and contains(@value, 'Confirm')]")
        ]
        for locator in confirm_btn_locators:
            try:
                confirm_btn = wait.until(EC.element_to_be_clickable(locator))
                logging.info(f"Found confirm button with locator {locator}")
                ActionChains(driver).move_to_element(confirm_btn).click().perform()
                logging.info(f"Clicked confirm button. Title: {driver.title}, URL: {driver.current_url}")
                break
            except:
                logging.warning(f"Failed to find confirm button with locator {locator}")
                continue
        else:
            raise Exception("Confirm button not found")

        logging.info(f"Switched to account {account_id}")
        time.sleep(1)
    except Exception as e:
        logging.error(f"Failed to switch to account {account_id}: {str(e)}\n{traceback.format_exc()}")
        raise

@retry(stop_max_attempt_number=3, wait_fixed=2000)
def download_tradebook(account_id):
    """Download Trade Book CSV for the current account with retry logic."""
    logging.info(f"Downloading Trade Book for account {account_id}")
    try:
        wait.until(EC.element_to_be_clickable((By.LINK_TEXT, "Trade Book"))).click()
        logging.info(f"Clicked Trade Book link. Title: {driver.title}, URL: {driver.current_url}")
        wait.until(EC.element_to_be_clickable((By.ID, "hypPeriod"))).click()
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "label[for='month']"))).click()  # Click on the month option
        time.sleep(2)
        wait.until(EC.element_to_be_clickable((By.ID, "btnview"))).click()
        time.sleep(5)
        download_menu = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@id='dvequity']//div[@class='pull-right']")))
        ActionChains(driver).move_to_element(download_menu).click().perform()
        csv_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(),'CSV')]")))
        existing = csv_snapshot(account_id)
        driver.execute_script("arguments[0].click();", csv_link)  # JavaScript click
        downloaded_file = wait_for_download(account_id, "TradeBook", before=existing)
        renamed = rename_downloaded_file(downloaded_file, account_id, "tradebook")
        time.sleep(2)
        return renamed
    except Exception as e:
        logging.error(f"Failed to download Trade Book for account {account_id}: {str(e)}\n{traceback.format_exc()}")
        raise

@retry(stop_max_attempt_number=3, wait_fixed=2000)
def download_portfolio(account_id):
    """Download Portfolio Summary CSV for the current account with retry logic."""
    logging.info(f"Downloading Portfolio for account {account_id}")
    try:
        wait.until(EC.element_to_be_clickable((By.XPATH, "//a[@class='sub-navlink' and contains(text(), 'Portfolio')]"))).click()
        logging.info(f"Clicked Portfolio link. Title: {driver.title}, URL: {driver.current_url}")
        time.sleep(5)
        third_li = wait.until(EC.presence_of_element_located((By.XPATH, "(//div[@class='pull-right']//ul[contains(@class,'grid_menu')]/li)[3]")))
        third_li.click()
        time.sleep(2)
        summary_csv = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Summary: CSV')]")))
        existing = csv_snapshot(account_id)
        driver.execute_script("arguments[0].click();", summary_csv)  # JavaScript click
        downloaded_file = wait_for_download(account_id, "Summary", before=existing)
        renamed = rename_downloaded_file(downloaded_file, account_id, "portfolio")
        time.sleep(2)
        return renamed
    except Exception as e:
        logging.error(f"Failed to download Portfolio for account {account_id}: {str(e)}\n{traceback.format_exc()}")
        raise

@retry(stop_max_attempt_number=3, wait_fixed=2000)
def show_orderbook(account_id):
    """Extract Order Book data from the GTT table, display as a formatted table, and save to CSV."""
    logging.info(f"Extracting Order Book data for account {account_id}")
    try:
        # Navigate to Order Book
        wait = WebDriverWait(driver, 20)
        wait.until(EC.element_to_be_clickable((By.XPATH, '//a[@class="sub-navlink" and contains(text(), "Order Book")]'))).click()
        logging.info(f"Clicked Order Book link. Title: {driver.title}, URL: {driver.current_url}")
        time.sleep(2)  # Wait for the page to load
        # Navigate to GTT tab
        wait.until(EC.element_to_be_clickable((By.XPATH, "//ul[contains(@class, 'tabs-menu')]//a[normalize-space(text())='GTT']"))).click()
        logging.info(f"Clicked GTT tab. Title: {driver.title}, URL: {driver.current_url}")
        time.sleep(2)  # Wait for the GTT tab to load

        # Wait for table to load
        table_xpath = '/html/body/form/div[3]/div[3]/div/span/div[2]/div/div[2]/div/div/div[1]/form/div[2]/div[4]/div/div/div/div/table[2]'
        wait.until(EC.presence_of_element_located((By.XPATH, table_xpath)))
        table = driver.find_element(By.XPATH, table_xpath)

        # Extract headers
        headers = table.find_elements(By.XPATH, './/thead/tr/th')
        header_list = [header.text.strip() for header in headers if header.text.strip()]
        if not header_list:
            raise Exception("No headers found in Order Book table")
        logging.info(f"Extracted headers: {header_list}")

        # Extract rows
        rows = table.find_elements(By.XPATH, './/tbody/tr')
        logging.info(f"Found {len(rows)} rows in Order Book table")
        row_data = []
        for row in rows:
            # Skip hidden expandable rows
            if "expand_content" in row.get_attribute("class"):
                logging.debug("Skipped expand_content row")
                continue
            columns = row.find_elements(By.XPATH, './/td')
            row_list = [column.text.strip() for column in columns]
            # Include row if it has at least one non-empty cell
            if row_list and any(cell.strip() for cell in row_list):
                # Clean Stock column (remove 'Single' and extra spaces)
                if row_list and len(row_list) > 0:
                    row_list[0] = row_list[0].replace("Single", "").strip()
                # Normalize row length
                if len(row_list) < len(header_list):
                    row_list.extend([""] * (len(header_list) - len(row_list)))
                elif len(row_list) > len(header_list):
                    row_list = row_list[:len(header_list)]
                row_data.append(row_list)
            else:
                logging.debug(f"Skipped row due to no non-empty cells: {row_list}")

        if not row_data:
            print(f"No data rows found in Order Book table for account {account_id}")
            logging.warning(f"No data rows found in Order Book table for account {account_id}")
            return []

        # Display the table
        print(f"\nOrder Book for Account {account_id}:")
        print(tabulate(row_data, headers=header_list, tablefmt="grid", stralign="left", floatfmt=".2f"))
        logging.info(f"Displayed {len(row_data)} rows for account {account_id}")

        # Save to CSV
        account_dir = get_account_download_dir(account_id)
        orders_path = os.path.join(account_dir, f"{account_id}_orders.csv")
        cleaned_orders_path = os.path.join(account_dir, f"{account_id}_orders_cleaned.csv")
        with open(orders_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header_list)
            writer.writerows(row_data)
        logging.info(f"Orders saved to {orders_path}")

        # Clean Stock column in CSV
        clean_stock_column(orders_path, cleaned_orders_path)

        time.sleep(2)  # Allow time for file operations to complete
        logging.info(f"Extracted and displayed {len(row_data)} rows from Order Book for account {account_id}")
        return row_data

    except Exception as e:
        logging.error(f"Failed to extract Order Book data for {account_id}: {str(e)}\n{traceback.format_exc()}")
        raise

def clean_stock_column(input_path, output_path):
    """Clean the Stock column in the CSV by removing 'Single' and extra spaces."""
    try:
        with open(input_path, 'r', encoding='utf-8') as infile, open(output_path, 'w', newline='', encoding='utf-8') as outfile:
            reader = csv.reader(infile)
            writer = csv.writer(outfile)
            headers = next(reader)
            writer.writerow(headers)
            stock_col_idx = headers.index('Stock') if 'Stock' in headers else 0
            for row in reader:
                if row and len(row) > stock_col_idx:
                    row[stock_col_idx] = row[stock_col_idx].replace("Single", "").strip()
                writer.writerow(row)
        logging.info(f"Cleaned Stock column and saved to {output_path}")
    except Exception as e:
        logging.error(f"Failed to clean Stock column: {str(e)}")
        raise

def angular_stable(driver):
    try:
        return driver.execute_script("return window.getAllAngularTestabilities && window.getAllAngularTestabilities().every(t => t.isStable())")
    except Exception as e:
        logging.warning(f"Angular testability check failed: {str(e)}")
        return True  # Fallback to proceed if Angular check fails

@retry(stop_max_attempt_number=3, wait_fixed=2000)
def download_myportfolio(account_id):
    """Download My Portfolio CSV for the current account with retry logic."""
    logging.info(f"Downloading My Portfolio for account {account_id}")
    try:
        # Click Mutual Funds link
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'a[mnu-name="mf"]'))).click()
        logging.info(f"Clicked Mutual Funds link. Title: {driver.title}, URL: {driver.current_url}")
        time.sleep(5)  # Wait for the page to load
        # Switch to iframe
        iframe = wait.until(EC.presence_of_element_located((By.ID, "ifrmangwh")))
        driver.switch_to.frame(iframe)
        logging.info("Switched to iframe 'ifrmangwh'")

        # Wait for Angular to stabilize with error handling
        try:
            WebDriverWait(driver, 20).until(angular_stable)
            logging.info("Angular application is stable in iframe")
        except Exception as e:
            logging.warning(f"Angular stable check failed in iframe: {str(e)}\n{traceback.format_exc()}")
            # Proceed if Angular check fails, relying on Div1 visibility

        # Wait for modal
        try:
            time.sleep(5)
            modal = wait.until(EC.presence_of_element_located((By.ID, "Div1")))
            WebDriverWait(driver, 20).until(EC.visibility_of_element_located((By.ID, "Div1")))
            wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@id='Div1']//a[text()='Get Started']"))).click()        
            wait.until(EC.element_to_be_clickable((By.XPATH, "//a[normalize-space(text())='Back to old MF']"))).click()
            time.sleep(5)
        except Exception as e:
            logging.error(f"Error finding Div1 modal: {str(e)}\n{traceback.format_exc()}")
            raise
        finally:
            driver.switch_to.default_content()
            logging.info("Switched back to default content")
        
        # Wait for page to stabilize after Back to old MF
        WebDriverWait(driver, 20).until(lambda d: d.execute_script("return document.readyState === 'complete'"))
        logging.info("Page stabilized after Back to old MF")
        
        try:
            time.sleep(3)
            dropdown_holding = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="pnlmnudsp"]//ul[1]/li[2]')))
            ActionChains(driver).move_to_element(dropdown_holding).click().perform()
            time.sleep(3)
            wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(),'My Portfolio')]"))).click()
            
            time.sleep(3)  # Wait for the page to load
            download_menu = wait.until(EC.presence_of_element_located((By.XPATH, "((//div[@id='dvFilter']//div)[2]/ul/li)[1]")))
            ActionChains(driver).move_to_element(download_menu).click().perform()
            
            wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(),'CSV')]"))).click()
            existing = csv_snapshot(account_id)
            downloaded_file = wait_for_download(account_id, "Portfolio", before=existing)
            renamed = rename_downloaded_file(downloaded_file, account_id, "myportfolio")
            time.sleep(2)
            return renamed
        except Exception as e:
            logging.error(f"Failed to download My Portfolio for {account_id}: {str(e)}\n{traceback.format_exc()}")
            raise
    except Exception as e:
        logging.error(f"Failed to download My Portfolio for {account_id}: {str(e)}\n{traceback.format_exc()}")
        raise

@retry(stop_max_attempt_number=3, wait_fixed=2000)
def download_orderbook(account_id):
    """Download My Orderbook CSV for the current account with retry logic."""
    logging.info(f"Downloading Orderbook for account {account_id}")
    try:
        dropdown_order = wait.until(EC.presence_of_element_located((By.XPATH, '//*[@id="pnlmnudsp"]//ul[1]/li[9]')))
        print(f"Dropdown Orders element found: {dropdown_order.is_displayed()}")
        ActionChains(driver).move_to_element(dropdown_order).click().perform()
        wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(),'Order Book')]"))).click()
        time.sleep(3)
        
        wait.until(EC.element_to_be_clickable((By.ID, "hypPeriod"))).click()
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "label[for='month']"))).click()  # Click on the month option
        time.sleep(2)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@id='MFOrderBookDiv']//input[@value='View']"))).click()
        time.sleep(2)
        
        wait.until(EC.element_to_be_clickable((By.XPATH, "//a[@class='dropdown' and normalize-space()='Download']"))).click()
        existing = csv_snapshot(account_id)
        wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(),'CSV')]"))).click()

        downloaded_file = wait_for_download(account_id, "OrderBook", before=existing)
        renamed = rename_downloaded_file(downloaded_file, account_id, "orderbook")
        time.sleep(2)
        return renamed
    except Exception as e:
        logging.error(f"Failed to download Orderbook for {account_id}: {str(e)}\n{traceback.format_exc()}")
        raise
    
def process_account(account_id):
    """Run the existing collection flow for one account.

    Returns the paths produced for this account.  Any failure is propagated
    to run_batch(), which records the conclusion and moves to the next
    account.
    """
    logging.info(f"Processing account {account_id}")
    produced = []
    switch_account(account_id)
    produced.append(download_tradebook(account_id))
    produced.append(download_portfolio(account_id))
    orders = show_orderbook(account_id)
    if orders:
        produced.append(os.path.join(get_account_download_dir(account_id), f"{account_id}_orders_cleaned.csv"))
    if account_id in EXTRA_DATA_ACCOUNTS:
        produced.append(download_myportfolio(account_id))
        produced.append(download_orderbook(account_id))
    return [path for path in produced if path and os.path.isfile(path)]


def main():
    """Main function to orchestrate data extraction."""
    os.makedirs(CONFIG['download_base_dir'], exist_ok=True)
    progress = load_progress(CONFIG['download_base_dir'], PROGRESS_FILENAME)
    results = []
    try:
        results = run_batch(
            SUB_ACCOUNTS,
            process_account,
            CONFIG['download_base_dir'],
            PROGRESS_FILENAME,
            pre_run=lambda: (init_driver(), login()),
            progress=progress,
        )
        # Only files belonging to accounts that succeeded (or were skipped
        # because their files already exist) take part in the merge.
        order_files = files_for_consolidation(results, "_orders_cleaned.csv")
        consolidate_csvs(
            "orders",
            order_files,
            CONFIG['download_base_dir'],
            enabled=CONFIG['consolidate_output'],
        )
    except Exception as e:
        logging.error(f"Script failed: {str(e)}\n{traceback.format_exc()}")
    finally:
        if driver is not None:
            driver.quit()
            logging.info("Browser closed")
        summary = summarise_results(results)
        logging.info(
            "Run summary: %d succeeded, %d skipped, %d failed",
            summary[STATUS_SUCCESS],
            summary[STATUS_SKIPPED],
            summary[STATUS_FAILED],
        )
        print(
            f"Run summary: {summary[STATUS_SUCCESS]} succeeded, "
            f"{summary[STATUS_SKIPPED]} skipped, {summary[STATUS_FAILED]} failed"
        )


if __name__ == "__main__":
    main()